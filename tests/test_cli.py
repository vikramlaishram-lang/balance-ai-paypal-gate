from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from balance_paypal.mcp_client import ProposalMCPClient
from balance_paypal.security import supersession_digest, trusted_invoice_act_digest
from approver_cli import approval_request


ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP = ROOT / "data" / "test-temp"
TEST_TEMP.mkdir(parents=True, exist_ok=True)


class CliTests(unittest.TestCase):
    def test_scripted_malicious_proposal_is_refused_without_dispatch(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            output = Path(directory) / "adversarial.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(ROOT / "adversarial_ai_qualification.py"),
                    "scripted",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(result["passed"])
            self.assertEqual("TRUSTED_INVOICE_MISMATCH", result["gate_decision"]["admission_reason"])
            self.assertEqual({"create": 0, "capture": 0, "get": 0}, result["provider_calls"])

    def test_approver_recomputes_displayed_initial_act(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            request_file = Path(directory) / "approval-request.json"
            document = {
                "purpose": "INITIAL_PAYMENT",
                "mission_id": "mission-1",
                "amount": "1.00",
                "currency": "USD",
                "payee_id": "sandbox-merchant",
                "reference": "invoice-demo-001",
                "invoice_id": "trusted-invoice-demo-001",
                "invoice_digest": "f" * 64,
                "operation": "PAYPAL_CAPTURE_ORDER",
            }
            document["act_digest"] = trusted_invoice_act_digest(
                invoice_id=document["invoice_id"],
                operation=document["operation"],
                amount=document["amount"],
                currency=document["currency"],
                payee_id=document["payee_id"],
                reference=document["reference"],
            )
            request_file.write_text(json.dumps(document), encoding="utf-8")
            digest, displayed = approval_request(request_file)
            self.assertEqual(document["act_digest"], digest)
            self.assertEqual(document, displayed)
            document["amount"] = "2.00"
            request_file.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "does not match"):
                approval_request(request_file)

    def test_approver_recomputes_displayed_supersession(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            request_file = Path(directory) / "supersession-request.json"
            document = {
                "purpose": "SUPERSESSION",
                "invoice_id": "trusted-invoice-demo-001",
                "invoice_digest": "f" * 64,
                "operation": "SUPERSEDE_TERMINAL_UNSUCCESSFUL_PAYMENT",
                "original_mission_id": "mission-original",
                "original_outcome_basis": "PAYPAL_GET_DECLINED_CAPTURE",
                "original_paypal_order_id": "ORDER-ORIGINAL",
                "replacement_request_key": "replacement-request-001",
                "replacement_operation": "CREATE_NEW_PAYPAL_ORDER",
                "amount": "1.00",
                "currency": "USD",
                "payee_id": "sandbox-merchant",
                "reference": "invoice-demo-001",
            }
            document["replacement_act_digest"] = trusted_invoice_act_digest(
                invoice_id=document["invoice_id"],
                operation="PAYPAL_CAPTURE_ORDER",
                amount=document["amount"],
                currency=document["currency"],
                payee_id=document["payee_id"],
                reference=document["reference"],
            )
            document["approval_digest"] = supersession_digest(
                invoice_id=document["invoice_id"],
                invoice_digest=document["invoice_digest"],
                original_mission_id=document["original_mission_id"],
                original_paypal_order_id=document["original_paypal_order_id"],
                original_outcome_basis=document["original_outcome_basis"],
                replacement_request_key=document["replacement_request_key"],
                replacement_act_digest=document["replacement_act_digest"],
            )
            request_file.write_text(json.dumps(document), encoding="utf-8")
            digest, displayed = approval_request(request_file)
            self.assertEqual(document["approval_digest"], digest)
            self.assertEqual(document, displayed)
            document["replacement_request_key"] = "tampered-replacement"
            request_file.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "does not match"):
                approval_request(request_file)

    def test_one_command_restart_demo_recovers_same_mission_without_redispatch(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            output_dir = Path(directory) / "restart-demo"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(ROOT / "demo_runner.py"),
                    "fixture",
                    "--json",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = json.loads(completed.stdout)
            self.assertEqual(
                "DETERMINISTIC_RESTART_DEMO_NO_NETWORK_NOT_LIVE_PAYPAL_OR_MODEL",
                output["classification"],
            )
            self.assertTrue(output["restart"]["different_process"])
            self.assertTrue(output["restart"]["same_mission"])
            self.assertTrue(output["restart"]["same_order"])
            self.assertEqual(
                "OUTCOME_UNKNOWN",
                output["before_restart"]["status_after_dropped_confirmation"],
            )
            self.assertEqual("NOT_DISPATCHED", output["after_restart"]["retry_dispatch"])
            self.assertEqual("COMPLETED", output["after_restart"]["final_status"])
            self.assertEqual(1, output["after_restart"]["capture_dispatch_events"])
            self.assertTrue(output["after_restart"]["verification"]["chain_valid"])
            self.assertTrue(output["after_restart"]["verification"]["anchor_matches"])
            self.assertEqual(2, output["comparison"]["naive"]["captures"])
            self.assertEqual(1, output["comparison"]["governed"]["captures"])
            self.assertTrue((ROOT / output["evidence_file"]).exists())

    def test_four_fault_twenty_case_contrast_is_runnable_without_network(self):
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(ROOT / "fault_matrix_demo.py"), "--trials-per-fault", "5"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        output = json.loads(completed.stdout)
        self.assertEqual(20, output["totals"]["naive_replacement_order_cases"])
        self.assertEqual(0, output["totals"]["governed_replacement_order_cases"])
        self.assertEqual(40, output["totals"]["naive_completed_order_captures"])
        self.assertEqual(20, output["totals"]["governed_completed_order_captures"])

    def test_three_moment_gate_fixture_is_runnable_without_network(self):
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(ROOT / "gate_fixture_demo.py")],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        output = json.loads(completed.stdout)
        self.assertEqual("COMPLETED", output["payment"]["outcome_from_get"])
        self.assertEqual("NOT_DISPATCHED", output["agent_retry"]["dispatch"])
        self.assertTrue(output["wrong_digest_token"]["refused"])

    def test_real_stdio_mcp_tool_returns_proposal_without_a_write_path(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            database = Path(directory) / "mcp.sqlite3"
            with ProposalMCPClient(database, ROOT / "mcp_server.py") as client:
                result = client.call_tool(
                    "propose",
                    {
                        "request_key": "mcp-proposal-001",
                        "description": "Pay the demo merchant",
                        "payee_id": "sandbox-merchant",
                        "amount": "1.00",
                        "currency": "USD",
                        "reference": "invoice-demo-001",
                        "agent_provider": "OLLAMA_LOCAL",
                        "agent_model": "qwen3:8b-fixture",
                        "prompt_digest": "b" * 64,
                        "rationale": "Typed MCP fixture proposal.",
                    },
                )
            self.assertFalse(database.exists())
        self.assertEqual("NONE", result["authority"])
        self.assertEqual("NONE", result["effect"])
        self.assertEqual("sandbox-merchant", result["payee_id"])
        self.assertEqual(64, len(result["act_digest"]))


if __name__ == "__main__":
    unittest.main()

