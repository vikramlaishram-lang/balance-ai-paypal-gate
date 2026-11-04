from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.collector_audit import ZERO_COUNTS, replay_collector_log
from balance_paypal.demo_orchestration import (
    CollectorSession,
    OrchestrationError,
    effect_free_executor_probe,
    free_port,
    http_json,
    port_available,
    run_effect_free_preflight,
    run_live_orchestrated,
    stop_process,
    utc_now,
    wait_for_health,
    write_json,
)
from balance_paypal.observed_executor import CollectorClient, ObservationFailure, ObservedProvider


def _distinct_ports() -> tuple[int, int]:
    first = free_port()
    second = free_port()
    while second == first:
        second = free_port()
    return first, second


def _request_executor(port: int) -> tuple[int, dict]:
    request = {
        "mission_id": "negative-test",
        "operation": "CREATE_ORDER",
        "act_digest": "0" * 64,
        "body": {},
    }
    try:
        return 200, http_json(
            f"http://127.0.0.1:{port}/execute",
            {"token": "deliberately-invalid", "request": request},
            timeout=5.0,
        )
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _launch_effect_free_executor(
    directory: Path,
    port: int,
    collector_url: str,
    window_id: str,
) -> subprocess.Popen[str]:
    directory.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["BALANCE_EXECUTOR_COLLECTOR_URL"] = collector_url
    environment["BALANCE_EXECUTOR_COLLECTOR_WINDOW_ID"] = window_id
    stdout = (directory / "executor.stdout.txt").open("x", encoding="utf-8")
    stderr = (directory / "executor.stderr.txt").open("x", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-I", "-B", str(ROOT / "executor_cli.py"), "serve",
         "--port", str(port), "--effect-free-preflight"],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        text=True,
    )


def _result(name: str, passed: bool, **facts) -> dict:
    counts = facts.get("counts")
    if isinstance(counts, dict):
        provider_dispatches = sum(int(counts.get(key, 0)) for key in ("create", "capture", "get"))
    else:
        provider_dispatches = facts.pop("provider_dispatches", None)
    return {
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "finished_utc": utc_now(),
        "provider_dispatches": provider_dispatches,
        **facts,
    }


class _NotReadyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"ready":false}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        return


class _ProcessSentinel:
    def poll(self):
        return None


class _CountingProvider:
    def __init__(self):
        self.calls = 0

    def create_order(self, **kwargs):
        self.calls += 1
        return {"id": "should-not-exist"}


def positive_control(out: Path) -> dict:
    collector_port, executor_port = _distinct_ports()
    result = run_effect_free_preflight(ROOT, out, collector_port, executor_port)
    audit = replay_collector_log(out / "collector.jsonl")
    passed = (
        result["result"] == "PASS"
        and audit["chain_valid"]
        and audit["complete"]
        and audit["counts"] == {"ingress": 1, "create": 0, "capture": 0, "get": 0, "refused": 1}
    )
    return _result(
        "unmutated_control",
        passed,
        counts=audit["counts"],
        collector_counts_available=True,
        collector_pid=result["collector_pid"],
        executor_pid=result["executor_pid"],
        window_id=result["window_id"],
        chain_valid=audit["chain_valid"],
        complete=audit["complete"],
        evidence=str(out),
    )


def collector_missing(out: Path) -> dict:
    collector_port, executor_port = _distinct_ports()
    process = _launch_effect_free_executor(
        out, executor_port, f"http://127.0.0.1:{collector_port}", "missing-collector-window"
    )
    try:
        health = wait_for_health(f"http://127.0.0.1:{executor_port}/health", process)
        status, body = _request_executor(executor_port)
        health_after = http_json(f"http://127.0.0.1:{executor_port}/health")
        passed = (
            status == 403
            and "collector unavailable/mismatched" in body.get("error", "")
            and health_after.get("provider_tripwire_calls") == 0
        )
        return _result(
            "collector_missing",
            passed,
            counts=None,
            collector_counts_available=False,
            request_attempts=1,
            provider_tripwire_calls=health_after.get("provider_tripwire_calls"),
            provider_dispatches=0,
            limitation="No configured collector existed; collector counts are unavailable by construction.",
            executor_pid=process.pid,
            health=health,
            http_status=status,
            error=body.get("error"),
            evidence=str(out),
        )
    finally:
        stop_process(process)


def collector_not_ready(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _NotReadyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    observed_error = None
    try:
        try:
            wait_for_health(f"http://127.0.0.1:{port}/health", _ProcessSentinel(), timeout=0.3)
        except OrchestrationError as exc:
            observed_error = str(exc)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    passed = observed_error is not None
    value = _result(
        "collector_not_ready",
        passed,
        counts=dict(ZERO_COUNTS),
        collector_counts_available=False,
        request_attempts=0,
        executor_started=False,
        error=observed_error,
        evidence=str(out),
    )
    write_json(out / "result.json", value)
    return value


def incorrect_window(out: Path) -> dict:
    collector_port, executor_port = _distinct_ports()
    session = CollectorSession(ROOT, out, collector_port)
    process = None
    try:
        session.start("negative-incorrect-window")
        wrong = "substitute-" + str(session.window_id)
        process = _launch_effect_free_executor(
            out / "executor", executor_port, session.collector_url, wrong
        )
        wait_for_health(f"http://127.0.0.1:{executor_port}/health", process)
        status, body = _request_executor(executor_port)
        audit = session.close_complete()
        passed = status == 403 and audit["counts"] == ZERO_COUNTS
        return _result(
            "incorrect_window_identity",
            passed,
            counts=audit["counts"],
            collector_counts_available=True,
            expected_window=session.window_id,
            supplied_window=wrong,
            http_status=status,
            error=body.get("error"),
            chain_valid=audit["chain_valid"],
            complete=audit["complete"],
            evidence=str(out),
        )
    finally:
        stop_process(process)
        session.stop()


def expired_closed_window(out: Path) -> dict:
    collector_port, executor_port = _distinct_ports()
    session = CollectorSession(ROOT, out, collector_port)
    process = None
    try:
        session.start("negative-closed-window")
        closed_window = str(session.window_id)
        initial_audit = session.close_complete()
        process = _launch_effect_free_executor(
            out / "executor", executor_port, session.collector_url, closed_window
        )
        wait_for_health(f"http://127.0.0.1:{executor_port}/health", process)
        status, body = _request_executor(executor_port)
        replay = replay_collector_log(session.log_path)
        passed = status == 403 and replay["counts"] == ZERO_COUNTS and replay["complete"]
        return _result(
            "expired_or_closed_window",
            passed,
            counts=replay["counts"],
            collector_counts_available=True,
            window_id=closed_window,
            http_status=status,
            error=body.get("error"),
            chain_valid=replay["chain_valid"],
            complete=replay["complete"],
            initial_end_counts=initial_audit["counts"],
            evidence=str(out),
        )
    finally:
        stop_process(process)
        session.stop()


def collector_failure_before_dispatch(out: Path) -> dict:
    collector_port = free_port()
    session = CollectorSession(ROOT, out, collector_port)
    try:
        session.start("negative-collector-failure-before-dispatch")
        collector = CollectorClient(session.collector_url, str(session.window_id), timeout_seconds=0.2)
        provider = _CountingProvider()
        observed = ObservedProvider(provider, collector)
        observed.use("pre-dispatch-correlation")
        session.stop()
        error = None
        try:
            observed.create_order(reference="fictional")
        except ObservationFailure as exc:
            error = str(exc)
        audit = replay_collector_log(session.log_path)
        session.mark_incomplete("collector intentionally stopped before provider dispatch")
        passed = error is not None and provider.calls == 0 and audit["counts"] == ZERO_COUNTS and not audit["complete"]
        return _result(
            "collector_failure_before_provider_dispatch",
            passed,
            counts=audit["counts"],
            collector_counts_available=True,
            fictional_provider_calls=provider.calls,
            error=error,
            chain_valid=audit["chain_valid"],
            complete=audit["complete"],
            evidence=str(out),
        )
    finally:
        session.stop()


def invalid_execution_token(out: Path) -> dict:
    collector_port, executor_port = _distinct_ports()
    session = CollectorSession(ROOT, out, collector_port)
    try:
        session.start("negative-invalid-token")
        probe = effect_free_executor_probe(ROOT, session, executor_port)
        audit = session.close_complete()
        expected = {"ingress": 1, "create": 0, "capture": 0, "get": 0, "refused": 1}
        passed = audit["counts"] == expected and probe["provider_tripwire_calls"] == 0
        return _result(
            "invalid_execution_token",
            passed,
            counts=audit["counts"],
            collector_counts_available=True,
            provider_tripwire_calls=probe["provider_tripwire_calls"],
            http_status=probe["invalid_token_http_status"],
            chain_valid=audit["chain_valid"],
            complete=audit["complete"],
            evidence=str(out),
        )
    finally:
        session.stop()


def interrupted_startup(out: Path) -> dict:
    collector_port, executor_port = _distinct_ports()
    session = CollectorSession(ROOT, out, collector_port)
    process = None
    try:
        session.start("negative-interrupted-startup")
        process = _launch_effect_free_executor(
            out / "executor", executor_port, session.collector_url, "x" * 129
        )
        code = process.wait(timeout=5)
        audit = session.close_complete()
        passed = code != 0 and audit["counts"] == ZERO_COUNTS
        return _result(
            "interrupted_startup",
            passed,
            counts=audit["counts"],
            collector_counts_available=True,
            executor_exit_code=code,
            chain_valid=audit["chain_valid"],
            complete=audit["complete"],
            evidence=str(out),
        )
    finally:
        stop_process(process)
        session.stop()


def runner_failure(out: Path) -> dict:
    port = free_port()
    code = run_live_orchestrated(ROOT, out, port, [])
    audit = replay_collector_log(out / "collector.jsonl")
    state = json.loads((out / "orchestration-state.json").read_text(encoding="utf-8"))
    expected = {"ingress": 1, "create": 0, "capture": 0, "get": 0, "refused": 1}
    passed = code != 0 and state["status"] == "INCOMPLETE" and audit["counts"] == expected and not audit["complete"]
    return _result(
        "runner_failure",
        passed,
        counts=audit["counts"],
        collector_counts_available=True,
        runner_exit_code=code,
        orchestration_status=state["status"],
        chain_valid=audit["chain_valid"],
        complete=audit["complete"],
        evidence=str(out),
    )


def incomplete_window(out: Path) -> dict:
    port = free_port()
    session = CollectorSession(ROOT, out, port)
    try:
        session.start("negative-incomplete-window")
        session.stop()
        session.mark_incomplete("simulated abrupt stop")
        audit = replay_collector_log(session.log_path)
        passed = audit["chain_valid"] and not audit["complete"] and audit["counts"] == ZERO_COUNTS
        return _result(
            "incomplete_collector_window",
            passed,
            counts=audit["counts"],
            collector_counts_available=True,
            chain_valid=audit["chain_valid"],
            complete=audit["complete"],
            evidence=str(out),
        )
    finally:
        session.stop()


def corrupted_replay(out: Path, control_log: Path) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    corrupted = out / "collector-corrupted.jsonl"
    lines = control_log.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    row["record"]["name"] = "CORRUPTED"
    lines[0] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    corrupted.write_text("\n".join(lines) + "\n", encoding="utf-8")
    audit = replay_collector_log(corrupted)
    passed = not audit["chain_valid"] and any("hash mismatch" in item for item in audit["errors"])
    value = _result(
        "corrupted_evidence_replay",
        passed,
        counts=audit["counts"],
        collector_counts_available=True,
        chain_valid=audit["chain_valid"],
        complete=audit["complete"],
        errors=audit["errors"],
        evidence=str(out),
    )
    write_json(out / "result.json", value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = utc_now()
    tests = []
    scenarios = [
        ("00_control", positive_control),
        ("01_collector_missing", collector_missing),
        ("02_collector_not_ready", collector_not_ready),
        ("03_incorrect_window", incorrect_window),
        ("04_closed_window", expired_closed_window),
        ("05_collector_failure", collector_failure_before_dispatch),
        ("06_invalid_token", invalid_execution_token),
        ("07_interrupted_startup", interrupted_startup),
        ("08_runner_failure", runner_failure),
        ("09_incomplete_window", incomplete_window),
    ]
    for directory, scenario in scenarios:
        try:
            value = scenario(out / directory)
        except Exception as exc:
            value = _result(
                scenario.__name__, False, counts=None, collector_counts_available=False,
                error=f"{type(exc).__name__}: {exc}", evidence=str(out / directory)
            )
        tests.append(value)
    tests.append(corrupted_replay(out / "10_corrupted_replay", out / "00_control" / "collector.jsonl"))
    summary = {
        "candidate": "v0.5.2-demo-orchestration",
        "started_utc": started,
        "finished_utc": utc_now(),
        "scope": "effect-free local orchestration qualification",
        "hard_restrictions": {
            "paypal_api_calls": 0,
            "sandbox_create_capture_get": 0,
            "live_model_inferences": 0,
            "payment_authorizations": 0,
        },
        "total": len(tests),
        "passed": sum(test["status"] == "PASS" for test in tests),
        "failed": sum(test["status"] == "FAIL" for test in tests),
        "tests": tests,
    }
    write_json(out / "V052_EFFECT_FREE_RESULTS.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
