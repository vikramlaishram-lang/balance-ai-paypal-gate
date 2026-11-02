from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import socket
import sys
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
QF_ROOT = ROOT / "qualification" / "qf-01"
DEFAULT_BINDING = QF_ROOT / "QF-01-CANDIDATE-BINDING.json"
DEFAULT_EVIDENCE = ROOT / "data" / "qf-01" / "QF-01-PHASE1-EVIDENCE.json"
CONTRACT_SHA256 = "b365df35ac73b9ffe8445b53da24c7c872202ee2859783564a261dc2979e7ea0"
MODEL_NAME = "qwen3:8b"
PHASE1_TESTS = (
    "GateArchitectureTests.test_admissibility_and_decision_are_separate",
    "GateArchitectureTests.test_malicious_agent_change_is_rejected_against_trusted_invoice",
    "GateArchitectureTests.test_lock_refusal_records_all_non_lock_checks_and_eligible_twin",
    "GateArchitectureTests.test_concurrent_missions_only_one_can_lock_invoice",
    "GateArchitectureTests.test_completed_invoice_stays_paid_and_cannot_be_reopened",
    "GateArchitectureTests.test_same_mission_create_reentry_after_unknown_is_not_dispatched",
    "GateArchitectureTests.test_terminal_failure_requires_signed_supersession_for_replacement",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def candidate_paths() -> list[Path]:
    paths: set[Path] = set()
    for pattern in (
        "*.py",
        "balance_paypal/*.py",
        "tests/*.py",
        "qualification/qf-01/fixtures/*.json",
        "qualification/qf-01/prompts/*.json",
    ):
        paths.update(path for path in ROOT.glob(pattern) if path.is_file())
    for relative in (
        "qualification/qf-01/EXECUTION_PROFILE.md",
        "policy.sandbox.example.json",
        "trusted-invoice.example.json",
    ):
        path = ROOT / relative
        if path.is_file():
            paths.add(path)
    return sorted(paths, key=lambda path: path.relative_to(ROOT).as_posix())


def model_manifest_path() -> Path:
    return (
        Path(os.environ.get("USERPROFILE", str(Path.home())))
        / ".ollama"
        / "models"
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / "qwen3"
        / "8b"
    )


def model_record() -> dict[str, object]:
    path = model_manifest_path()
    if not path.is_file():
        raise SystemExit(f"Ollama model manifest is unavailable: {path}")
    raw = path.read_bytes()
    manifest = json.loads(raw)
    model_layers = [
        layer for layer in manifest.get("layers", [])
        if layer.get("mediaType") == "application/vnd.ollama.image.model"
    ]
    if len(model_layers) != 1:
        raise SystemExit("The Ollama manifest did not contain exactly one model layer.")
    return {
        "name": MODEL_NAME,
        "manifest_sha256": sha256_bytes(raw),
        "config_digest": manifest["config"]["digest"],
        "model_layer_digest": model_layers[0]["digest"],
        "manifest_path_class": "LOCAL_OLLAMA_MANIFEST",
    }


def verify_denominators() -> dict[str, int]:
    counts = {
        "adversarial_model_prompts": len(json.loads((QF_ROOT / "prompts" / "adversarial.json").read_text(encoding="utf-8"))),
        "legitimate_model_prompts": len(json.loads((QF_ROOT / "prompts" / "legitimate.json").read_text(encoding="utf-8"))),
        "scripted_malicious_proposals": len(json.loads((QF_ROOT / "fixtures" / "scripted-malicious-proposals.json").read_text(encoding="utf-8"))),
    }
    if set(counts.values()) != {10}:
        raise SystemExit(f"QF-01 denominator violation: {counts}")
    return counts


def build_binding(contract_path: Path | None) -> dict[str, object]:
    files = {
        path.relative_to(ROOT).as_posix(): sha256_file(path)
        for path in candidate_paths()
    }
    contract_record: dict[str, object] = {
        "id": "QF-01",
        "frozen_date": "2026-10-26",
        "sha256": CONTRACT_SHA256,
        "verification": "EXTERNAL_DIGEST_DECLARED_CONTRACT_BYTES_NOT_IN_WORKSPACE",
    }
    if contract_path is not None:
        contract_path = contract_path.expanduser().resolve()
        actual = sha256_file(contract_path)
        if actual != CONTRACT_SHA256:
            raise SystemExit(
                f"Contract hash mismatch: expected {CONTRACT_SHA256}, got {actual}."
            )
        contract_record["verification"] = "LOCAL_ARTIFACT_HASH_VERIFIED"
        contract_record["artifact_name"] = contract_path.name
    return {
        "schema_version": 1,
        "binding_id": "Balance-Gate-PayPal-v0.5-QF-01",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "contract": contract_record,
        "candidate": {
            "name": "Balance Gate PayPal",
            "version": "v0.5",
            "aggregate_sha256": sha256_bytes(canonical_bytes(files)),
            "files": files,
        },
        "fixtures_and_prompts": verify_denominators(),
        "ollama_model": model_record(),
        "protection_boundary": "ONE_GATE_OWNED_TRUSTED_INVOICE_NOT_REAL_WORLD_PURCHASE",
    }


def write_new_json(path: Path, value: object) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"Refused to overwrite existing evidence artifact: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def bind(args: argparse.Namespace) -> int:
    binding = build_binding(args.contract)
    write_new_json(args.output, binding)
    print(json.dumps({
        "binding": str(args.output.resolve()),
        "candidate_aggregate_sha256": binding["candidate"]["aggregate_sha256"],
        "contract_sha256": CONTRACT_SHA256,
        "contract_verification": binding["contract"]["verification"],
        "model_manifest_sha256": binding["ollama_model"]["manifest_sha256"],
        "model_layer_digest": binding["ollama_model"]["model_layer_digest"],
    }, indent=2, sort_keys=True))
    return 0


def verify_binding(path: Path) -> dict[str, object]:
    binding = json.loads(path.read_text(encoding="utf-8"))
    expected_files = binding["candidate"]["files"]
    actual_files = {
        candidate.relative_to(ROOT).as_posix(): sha256_file(candidate)
        for candidate in candidate_paths()
    }
    if actual_files != expected_files:
        changed = sorted(
            name for name in set(actual_files) | set(expected_files)
            if actual_files.get(name) != expected_files.get(name)
        )
        raise SystemExit(f"Candidate binding verification failed; changed files: {changed}")
    aggregate = sha256_bytes(canonical_bytes(actual_files))
    if aggregate != binding["candidate"]["aggregate_sha256"]:
        raise SystemExit("Candidate aggregate digest mismatch.")
    if model_record() != binding["ollama_model"]:
        raise SystemExit("Pinned Ollama model manifest changed.")
    if verify_denominators() != binding["fixtures_and_prompts"]:
        raise SystemExit("Pinned QF-01 denominators changed.")
    return binding


@contextmanager
def deny_outbound_connections():
    def denied(*_args, **_kwargs):
        raise AssertionError("QF-01 Phase 1 forbids outbound socket connections.")

    with mock.patch.object(socket.socket, "connect", denied), mock.patch.object(
        socket, "create_connection", denied
    ):
        yield


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.successes: list[str] = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.successes.append(test.id())


def phase1(args: argparse.Namespace) -> int:
    binding_path = args.binding.expanduser().resolve()
    binding = verify_binding(binding_path)
    tests_path = ROOT / "tests"
    sys.path.insert(0, str(tests_path))
    import test_gate_architecture  # type: ignore

    suite = unittest.TestSuite()
    for test_name in PHASE1_TESTS:
        suite.addTest(unittest.defaultTestLoader.loadTestsFromName(test_name, test_gate_architecture))
    stream = io.StringIO()
    runner = unittest.TextTestRunner(
        stream=stream, verbosity=2, resultclass=RecordingResult
    )
    with deny_outbound_connections():
        result = runner.run(suite)
    evidence = {
        "classification": "QF_01_PHASE_1_LOCAL_OFFLINE_QUALIFICATION",
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "contract_sha256": binding["contract"]["sha256"],
        "contract_verification": binding["contract"]["verification"],
        "binding_file_sha256": sha256_file(binding_path),
        "candidate_aggregate_sha256": binding["candidate"]["aggregate_sha256"],
        "ollama_model": binding["ollama_model"],
        "phase": 1,
        "network_control": "OUTBOUND_SOCKET_CONNECT_DENIED_DURING_TEST_EXECUTION",
        "paypal_environment": "NOT_STARTED",
        "real_paypal_api_calls": 0,
        "provider_used": "DETERMINISTIC_IN_PROCESS_FIXTURE_ONLY",
        "protection_boundary": binding["protection_boundary"],
        "selected_tests": list(PHASE1_TESTS),
        "results": {
            "run": result.testsRun,
            "passed": len(result.successes),
            "failures": len(result.failures),
            "errors": len(result.errors),
            "successful_test_ids": result.successes,
        },
        "test_output": stream.getvalue(),
        "passed": result.wasSuccessful() and result.testsRun == len(PHASE1_TESTS),
    }
    write_new_json(args.output, evidence)
    print(json.dumps({
        "classification": evidence["classification"],
        "output": str(args.output.resolve()),
        "passed": evidence["passed"],
        "tests_run": result.testsRun,
        "tests_passed": len(result.successes),
        "real_paypal_api_calls": 0,
        "network_control": evidence["network_control"],
    }, indent=2, sort_keys=True))
    return 0 if evidence["passed"] else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Bind and execute frozen Balance QF-01 qualification phases.")
    commands = result.add_subparsers(dest="command", required=True)
    bind_command = commands.add_parser("bind", help="Hash-pin candidate, fixtures, prompts, and Ollama model.")
    bind_command.add_argument("--contract", type=Path)
    bind_command.add_argument("--output", type=Path, default=DEFAULT_BINDING)
    phase1_command = commands.add_parser("phase1", help="Run the offline QF-01 Phase 1 checks.")
    phase1_command.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    phase1_command.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "bind":
        return bind(args)
    return phase1(args)


if __name__ == "__main__":
    raise SystemExit(main())
