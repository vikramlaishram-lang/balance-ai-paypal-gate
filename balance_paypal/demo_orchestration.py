"""Fail-closed collector lifecycle orchestration for the v0.5.2 demo candidate."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .collector_audit import replay_collector_log


BASE_COMMIT = "e1ca697ae0e943755a3711993d87906176fdb381"
CANDIDATE_VERSION = "v0.5.2-demo-orchestration"


class OrchestrationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def http_json(url: str, value: Any | None = None, timeout: float = 2.0) -> dict[str, Any]:
    data = None if value is None else canonical(value).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="GET" if value is None else "POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for_health(url: str, process: subprocess.Popen[str], timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = "not contacted"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise OrchestrationError(f"process exited before readiness (code {process.returncode})")
        try:
            result = http_json(url, timeout=0.5)
            if result.get("ready") is True:
                return result
            last_error = "health response did not assert ready"
        except Exception as exc:
            last_error = type(exc).__name__
        time.sleep(0.05)
    raise OrchestrationError(f"readiness timeout ({last_error})")


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def tree_identity(root: Path) -> dict[str, Any]:
    excluded_parts = {"__pycache__", ".git", "out", "outputs", "evidence-runs"}
    excluded_suffixes = {".pyc", ".pyo"}
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in excluded_parts for part in path.parts):
            continue
        if path.suffix.lower() in excluded_suffixes:
            continue
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        files.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    tree_hash = hashlib.sha256(canonical(files).encode("utf-8")).hexdigest()
    return {
        "candidate_version": CANDIDATE_VERSION,
        "base_commit": BASE_COMMIT,
        "generated_utc": utc_now(),
        "tree_sha256": tree_hash,
        "file_count": len(files),
        "files": files,
    }


class CollectorSession:
    def __init__(self, root: Path, output_dir: Path, collector_port: int):
        self.root = root.resolve()
        self.output_dir = output_dir.resolve()
        self.collector_port = collector_port
        self.collector_url = f"http://127.0.0.1:{collector_port}"
        self.log_path = self.output_dir / "collector.jsonl"
        self.state_path = self.output_dir / "orchestration-state.json"
        self.stdout_path = self.output_dir / "collector.stdout.txt"
        self.stderr_path = self.output_dir / "collector.stderr.txt"
        self.process: subprocess.Popen[str] | None = None
        self.window_id: str | None = None
        self.state: dict[str, Any] = {
            "candidate_version": CANDIDATE_VERSION,
            "base_commit": BASE_COMMIT,
            "status": "INITIALIZING",
            "started_utc": utc_now(),
            "collector_url": self.collector_url,
            "collector_log": str(self.log_path),
            "events": [],
        }

    def record(self, event: str, **facts: Any) -> None:
        self.state["events"].append({"utc": utc_now(), "event": event, **facts})
        write_json(self.state_path, self.state)

    def start(self, name: str) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=False)
        write_json(self.state_path, self.state)
        if not port_available(self.collector_port):
            raise OrchestrationError(f"collector port {self.collector_port} is not available")
        stdout = self.stdout_path.open("x", encoding="utf-8")
        stderr = self.stderr_path.open("x", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(self.root / "collector_cli.py"),
             "--log", str(self.log_path), "--port", str(self.collector_port)],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
        self.record("COLLECTOR_PROCESS_STARTED", collector_pid=self.process.pid)
        health = wait_for_health(self.collector_url + "/health", self.process)
        if health.get("collector_pid") != self.process.pid or health.get("window_id") is not None:
            raise OrchestrationError("collector readiness identity mismatch")
        self.record("COLLECTOR_READY", health=health)
        begin = http_json(self.collector_url + "/begin", {"name": name})
        window_id = begin.get("window_id")
        if not isinstance(window_id, str) or not window_id:
            raise OrchestrationError("collector did not return a window identity")
        verify = http_json(self.collector_url + "/health")
        if verify.get("window_id") != window_id:
            raise OrchestrationError("collector health did not preserve the opened window")
        self.window_id = window_id
        self.state["window_id"] = window_id
        self.state["status"] = "ACTIVE"
        self.record("WINDOW_OPENED", counts=begin.get("counts"), collector_pid=self.process.pid)
        return begin

    def executor_environment(self) -> dict[str, str]:
        if not self.window_id:
            raise OrchestrationError("collector window is not active")
        environment = dict(os.environ)
        environment["BALANCE_EXECUTOR_COLLECTOR_URL"] = self.collector_url
        environment["BALANCE_EXECUTOR_COLLECTOR_WINDOW_ID"] = self.window_id
        return environment

    def close_complete(self) -> dict[str, Any]:
        if not self.window_id:
            raise OrchestrationError("cannot close a window that was not opened")
        result = http_json(self.collector_url + "/end", {"window_id": self.window_id})
        if result.get("window_id") != self.window_id:
            raise OrchestrationError("collector returned the wrong terminal window identity")
        audit = replay_collector_log(self.log_path)
        if not audit["chain_valid"] or not audit["complete"] or audit["counts"] != result.get("counts"):
            raise OrchestrationError("independent collector replay failed")
        self.state["status"] = "COMPLETE"
        self.state["finished_utc"] = utc_now()
        self.state["collector_end"] = result
        self.state["independent_replay"] = audit
        self.record("WINDOW_CLOSED_AND_REPLAYED")
        return audit

    def mark_incomplete(self, reason: str) -> dict[str, Any]:
        audit = replay_collector_log(self.log_path) if self.log_path.exists() else None
        self.state["status"] = "INCOMPLETE"
        self.state["finished_utc"] = utc_now()
        self.state["incomplete_reason"] = reason
        self.state["independent_replay"] = audit
        self.record("WINDOW_PRESERVED_INCOMPLETE", reason=reason)
        return audit or {}

    def stop(self) -> None:
        stop_process(self.process)


def effect_free_executor_probe(
    root: Path,
    session: CollectorSession,
    executor_port: int,
) -> dict[str, Any]:
    if not port_available(executor_port):
        raise OrchestrationError(f"executor port {executor_port} is not available")
    stdout_path = session.output_dir / "executor.stdout.txt"
    stderr_path = session.output_dir / "executor.stderr.txt"
    stdout = stdout_path.open("x", encoding="utf-8")
    stderr = stderr_path.open("x", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", str(root / "executor_cli.py"), "serve",
         "--port", str(executor_port), "--effect-free-preflight"],
        cwd=root,
        env=session.executor_environment(),
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        text=True,
    )
    session.record("EFFECT_FREE_EXECUTOR_STARTED", executor_pid=process.pid, port=executor_port)
    try:
        health = wait_for_health(f"http://127.0.0.1:{executor_port}/health", process)
        if health.get("collector_window_id") != session.window_id:
            raise OrchestrationError("Executor health returned the wrong collector window")
        request = {
            "mission_id": "effect-free-probe",
            "operation": "CREATE_ORDER",
            "act_digest": "0" * 64,
            "body": {},
        }
        status = None
        body: dict[str, Any] = {}
        try:
            body = http_json(
                f"http://127.0.0.1:{executor_port}/execute",
                {"token": "deliberately-invalid", "request": request},
            )
            status = 200
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        if status != 403 or "NOT_DISPATCHED" not in body.get("error", ""):
            raise OrchestrationError("invalid-token preflight was not refused fail-closed")
        health_after = http_json(f"http://127.0.0.1:{executor_port}/health")
        if health_after.get("provider_tripwire_calls") != 0:
            raise OrchestrationError("effect-free provider tripwire was reached")
        result = {
            "executor_pid": process.pid,
            "health_before": health,
            "health_after": health_after,
            "invalid_token_http_status": status,
            "invalid_token_result": body,
            "provider_tripwire_calls": 0,
        }
        session.record("EFFECT_FREE_EXECUTOR_PROBE_PASSED", result=result)
        return result
    finally:
        stop_process(process)


def run_effect_free_preflight(
    root: Path,
    output_dir: Path,
    collector_port: int,
    executor_port: int,
) -> dict[str, Any]:
    session = CollectorSession(root, output_dir, collector_port)
    try:
        session.start("v0.5.2-effect-free-preflight")
        probe = effect_free_executor_probe(root, session, executor_port)
        audit = session.close_complete()
        expected_counts = {"ingress": 1, "create": 0, "capture": 0, "get": 0, "refused": 1}
        if audit["counts"] != expected_counts:
            raise OrchestrationError(f"unexpected effect-free counts: {audit['counts']}")
        result = {
            "result": "PASS",
            "scope": "effect-free-orchestration-only",
            "candidate_version": CANDIDATE_VERSION,
            "base_commit": BASE_COMMIT,
            "window_id": session.window_id,
            "collector_pid": session.process.pid if session.process else None,
            "executor_pid": probe["executor_pid"],
            "counts": audit["counts"],
            "chain_valid": audit["chain_valid"],
            "complete": audit["complete"],
            "paypal_api_calls": 0,
            "live_model_inferences": 0,
            "credential_files_read": 0,
            "payment_authorizations": 0,
            "started_utc": session.state["started_utc"],
            "finished_utc": session.state["finished_utc"],
        }
        write_json(output_dir / "effect-free-preflight-result.json", result)
        return result
    except Exception as exc:
        session.mark_incomplete(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        session.stop()


def read_only_configuration_preflight(root: Path, collector_port: int, executor_port: int) -> dict[str, Any]:
    required = [
        "BALANCE_PAYPAL_CREDENTIAL_FILE",
        "BALANCE_TOKEN_KEY_FILE",
        "BALANCE_APPROVER_KEY_FILE",
        "BALANCE_ANCHOR_DIR",
    ]
    paths = {}
    for name in required:
        raw = os.environ.get(name, "").strip()
        resolved = Path(raw).expanduser().resolve() if raw else None
        paths[name] = {
            "configured": bool(raw),
            "absolute": bool(resolved and resolved.is_absolute()),
            "exists": bool(resolved and resolved.exists()),
            "outside_candidate": bool(resolved and root.resolve() not in resolved.parents and resolved != root.resolve()),
            "contents_read": False,
        }

    ollama = {"endpoint": "http://127.0.0.1:11434", "reachable": False,
              "expected_model": "qwen3:8b", "model_available": False, "inference_performed": False}
    try:
        tags = http_json("http://127.0.0.1:11434/api/tags", timeout=1.0)
        names = [str(model.get("name", "")) for model in tags.get("models", [])]
        ollama["reachable"] = True
        ollama["model_available"] = any(name == "qwen3:8b" or name.startswith("qwen3:8b-") for name in names)
        ollama["observed_model_names"] = names
    except Exception as exc:
        ollama["error_type"] = type(exc).__name__

    paypal_source = (root / "balance_paypal" / "paypal.py").read_text(encoding="utf-8")
    sandbox_static = (
        'SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"' in paypal_source
        and 'if mode != "sandbox"' in paypal_source
        and "Refused a request outside PayPal Sandbox" in paypal_source
    )
    return {
        "generated_utc": utc_now(),
        "candidate_version": CANDIDATE_VERSION,
        "external_paths": paths,
        "ollama": ollama,
        "paypal": {"sandbox_only_static_check": sandbox_static, "credentials_read": False,
                   "api_call_performed": False},
        "ports": {
            "collector": {"port": collector_port, "available": port_available(collector_port)},
            "executor": {"port": executor_port, "available": port_available(executor_port)},
        },
        "candidate_identity": tree_identity(root),
    }


def run_live_orchestrated(
    root: Path,
    output_dir: Path,
    collector_port: int,
    runner_args: list[str],
    *,
    runner_command: str = "live",
    prior_evidence_dir: Path | None = None,
) -> int:
    """Run the existing live command only after an explicit CLI permit.

    On any non-zero exit or orchestration failure the window is intentionally not ended;
    the retained state is INCOMPLETE and must not be presented as a completed audit.
    """
    session = CollectorSession(root, output_dir, collector_port)
    runner: subprocess.Popen[str] | None = None
    try:
        if runner_command not in {"live", "resume-live"}:
            raise OrchestrationError("unsupported runner command")
        session.start("v0.5.2-" + runner_command)
        if runner_command == "resume-live":
            if prior_evidence_dir is None:
                raise OrchestrationError("resume-live requires the prior incomplete evidence directory")
            prior_state_path = prior_evidence_dir.resolve() / "orchestration-state.json"
            try:
                prior_state = json.loads(prior_state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise OrchestrationError("prior orchestration state is unreadable") from exc
            if prior_state.get("status") != "INCOMPLETE" or not prior_state.get("window_id"):
                raise OrchestrationError("resume-live requires a retained INCOMPLETE prior window")
            session.record(
                "PRIOR_INCOMPLETE_WINDOW_LINKED",
                prior_evidence_dir=str(prior_evidence_dir.resolve()),
                prior_window_id=prior_state["window_id"],
                prior_finished_utc=prior_state.get("finished_utc"),
            )
        probe_port = free_port()
        probe = effect_free_executor_probe(root, session, probe_port)
        session.record(
            "LIVE_PREREQUISITE_EXECUTOR_PROBE_PASSED",
            executor_pid=probe["executor_pid"],
            probe_port=probe_port,
            collector_window_id=session.window_id,
        )
        stdout_path = output_dir / "runner.stdout.txt"
        with stdout_path.open("x", encoding="utf-8") as stdout:
            runner = subprocess.Popen(
                [sys.executable, "-I", "-B", str(root / "demo_runner.py"), runner_command, *runner_args],
                cwd=root,
                env=session.executor_environment(),
                stdin=None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            session.record(
                "LIVE_RUNNER_STARTED",
                runner_pid=runner.pid,
                runner_command=runner_command,
                args=runner_args,
            )
            if runner.stdout is None:
                raise OrchestrationError("runner output pipe was not created")
            for line in runner.stdout:
                print(line, end="", flush=True)
                stdout.write(line)
                stdout.flush()
            code = runner.wait()
        if code != 0:
            session.mark_incomplete(f"runner exited with code {code}")
            return code
        session.close_complete()
        return 0
    except BaseException as exc:
        session.mark_incomplete(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        stop_process(runner)
        session.stop()
