from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from balance_paypal.agent_tools import AgentTools
from balance_paypal.executor import ExecutorError, TokenBoundExecutor
from balance_paypal.fixture import FixturePayPalSandbox
from balance_paypal.gate import FileAnchorSink, GateError, GateService
from balance_paypal.journal import Journal
from balance_paypal.security import mint_execution_token, sign_approval


ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP = ROOT / "data" / "test-temp"
TEST_TEMP.mkdir(parents=True, exist_ok=True)


class Harness:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP)
        self.root = Path(self.temp.name)
        self.db = self.root / "gate.sqlite3"
        self.provider = FixturePayPalSandbox()
        self.token_key = b"t" * 32
        self.approval_key = b"a" * 32
        self.executor = TokenBoundExecutor(self.provider, self.token_key)
        self.anchor_dir = self.root / "anchors"
        self.gate = GateService(
            Journal(self.db), self.executor, token_key=self.token_key,
            approval_key=self.approval_key, anchor_sink=FileAnchorSink(self.anchor_dir),
        )
        self.invoice_id = "trusted-invoice-demo-001"
        self.gate.register_invoice(self.invoice_document())

    def close(self):
        self.temp.cleanup()

    def proposal(self):
        return {
            "request_key": "gate-request-001",
            "description": "One dollar PayPal safety demonstration",
            "payee_id": "sandbox-merchant",
            "amount": "1.00",
            "currency": "USD",
            "reference": "invoice-demo-001",
            "agent_provider": "OLLAMA_LOCAL",
            "agent_model": "qwen3:8b-fixture",
            "prompt_digest": "b" * 64,
            "rationale": "The user requested the demonstration payment.",
        }

    def invoice_document(self, invoice_id="trusted-invoice-demo-001"):
        return {
            "invoice_id": invoice_id,
            "merchant_id": "sandbox-merchant",
            "amount": "1.00",
            "currency": "USD",
            "reference": "invoice-demo-001",
            "operation": "PAYPAL_CAPTURE_ORDER",
        }

    def admitted(self):
        return self.gate.admit(
            self.proposal(), invoice_id=self.invoice_id,
            allowed_payees=["sandbox-merchant"],
            max_amount="1.00", allowed_currencies=["USD"],
        )

    def approved(self):
        mission = self.admitted()
        approval = sign_approval(
            self.approval_key, act_digest_value=mission["act_digest"],
            approver="os-user:test\\approver", expires_at=int(time.time()) + 600,
        )
        return self.gate.approve(mission["mission_id"], approval)

    def order_created(self):
        mission = self.approved()
        return self.gate.create_order(mission["mission_id"])


class GateArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def tearDown(self):
        self.h.close()

    def test_admissibility_and_decision_are_separate(self):
        mission = self.h.admitted()
        self.assertEqual("ADMISSIBLE", mission["admissibility"])
        self.assertEqual("NONE", mission["decision"])
        self.assertEqual("ADMITTED", mission["status"])
        self.assertRegex(mission["policy_hash"], r"^[0-9a-f]{64}$")

    def test_gate_accepts_and_recomputes_pure_agent_proposal_document(self):
        proposal = AgentTools(self.h.db).call("propose", self.h.proposal())
        mission = self.h.gate.admit(
            proposal, invoice_id=self.h.invoice_id, allowed_payees=["sandbox-merchant"],
            max_amount="1.00", allowed_currencies=["USD"],
        )
        self.assertEqual(proposal["act_digest"], mission["proposal_act_digest"])
        self.assertNotEqual(proposal["act_digest"], mission["act_digest"])
        self.assertEqual("ADMITTED", mission["status"])

    def test_policy_rejection_has_no_dispatch(self):
        mission = self.h.gate.admit(
            self.h.proposal(), invoice_id=self.h.invoice_id,
            allowed_payees=["another-merchant"],
            max_amount="1.00", allowed_currencies=["USD"],
        )
        self.assertEqual("REJECTED", mission["admissibility"])
        self.assertEqual("HOLD", mission["decision"])
        self.assertEqual(0, self.h.provider.create_calls)

    def test_malicious_agent_change_is_rejected_against_trusted_invoice(self):
        proposal = self.h.proposal()
        proposal["amount"] = "9.00"
        proposal["reference"] = "agent-changed-reference"
        mission = self.h.gate.admit(
            proposal,
            invoice_id=self.h.invoice_id,
            allowed_payees=["sandbox-merchant"],
            max_amount="10.00",
            allowed_currencies=["USD"],
        )
        self.assertEqual("REJECTED", mission["admissibility"])
        self.assertEqual("TRUSTED_INVOICE_MISMATCH", mission["admission_reason"])
        invoice = self.h.gate.inspect_invoice(self.h.invoice_id)
        self.assertEqual("OPEN", invoice["status"])
        self.assertIsNone(invoice["active_mission_id"])
        self.assertEqual(0, self.h.provider.create_calls)

    def test_second_mission_cannot_bypass_invoice_lock(self):
        first = self.h.admitted()
        replacement = self.h.proposal()
        replacement["request_key"] = "gate-request-replacement"
        second = self.h.gate.admit(
            replacement,
            invoice_id=self.h.invoice_id,
            allowed_payees=["sandbox-merchant"],
            max_amount="1.00",
            allowed_currencies=["USD"],
        )
        self.assertEqual("REJECTED", second["admissibility"])
        self.assertEqual(
            "INVOICE_LOCKED_REQUIRES_SIGNED_SUPERSESSION",
            second["admission_reason"],
        )
        self.assertEqual(
            first["mission_id"],
            self.h.gate.inspect_invoice(self.h.invoice_id)["active_mission_id"],
        )

    def test_lock_refusal_records_all_non_lock_checks_and_eligible_twin(self):
        first = self.h.admitted()
        replacement = self.h.proposal()
        replacement["request_key"] = "otherwise-eligible-locked-proposal"
        refused = self.h.gate.admit(
            replacement,
            invoice_id=self.h.invoice_id,
            allowed_payees=["sandbox-merchant"],
            max_amount="1.00",
            allowed_currencies=["USD"],
        )
        refusal_event = self.h.gate.journal.events(refused["mission_id"])[-1]
        self.assertEqual("PROPOSAL_REJECTED", refusal_event["event_type"])
        self.assertTrue(all(refusal_event["payload"]["non_lock_checks"].values()))
        self.assertEqual(
            "INVOICE_LOCKED_REQUIRES_SIGNED_SUPERSESSION",
            refused["admission_reason"],
        )
        self.assertEqual(
            first["mission_id"],
            self.h.gate.inspect_invoice(self.h.invoice_id)["active_mission_id"],
        )

        twin_invoice_id = "trusted-invoice-eligible-twin-001"
        twin_document = self.h.invoice_document(twin_invoice_id)
        twin_document["reference"] = "invoice-eligible-twin-001"
        self.h.gate.register_invoice(twin_document)
        twin_proposal = self.h.proposal()
        twin_proposal["request_key"] = "eligible-structural-twin"
        twin_proposal["reference"] = twin_document["reference"]
        twin = self.h.gate.admit(
            twin_proposal,
            invoice_id=twin_invoice_id,
            allowed_payees=["sandbox-merchant"],
            max_amount="1.00",
            allowed_currencies=["USD"],
        )
        twin_event = self.h.gate.journal.events(twin["mission_id"])[-1]
        self.assertEqual("ADMITTED", twin["status"])
        self.assertEqual("PROPOSAL_ADMITTED", twin_event["event_type"])
        self.assertTrue(all(twin_event["payload"]["non_lock_checks"].values()))

    def test_concurrent_missions_only_one_can_lock_invoice(self):
        outputs = []

        def admit(request_key):
            proposal = self.h.proposal()
            proposal["request_key"] = request_key
            outputs.append(
                self.h.gate.admit(
                    proposal,
                    invoice_id=self.h.invoice_id,
                    allowed_payees=["sandbox-merchant"],
                    max_amount="1.00",
                    allowed_currencies=["USD"],
                )
            )

        threads = [
            threading.Thread(target=admit, args=("concurrent-mission-a",)),
            threading.Thread(target=admit, args=("concurrent-mission-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(1, sum(item["status"] == "ADMITTED" for item in outputs))
        self.assertEqual(1, sum(item["status"] == "PROPOSED" for item in outputs))

    def test_completed_invoice_stays_paid_and_cannot_be_reopened(self):
        mission = self.h.order_created()
        self.h.provider.payer_approve(mission["paypal_order_id"])
        self.h.gate.capture(mission["mission_id"])
        final = self.h.gate.reconcile(mission["mission_id"])
        self.assertEqual("COMPLETED", final["status"])
        invoice = self.h.gate.inspect_invoice(self.h.invoice_id)
        self.assertEqual("PAID", invoice["status"])
        self.assertEqual(mission["mission_id"], invoice["active_mission_id"])
        replacement = self.h.proposal()
        replacement["request_key"] = "paid-invoice-replacement"
        refused = self.h.gate.admit(
            replacement,
            invoice_id=self.h.invoice_id,
            allowed_payees=["sandbox-merchant"],
            max_amount="1.00",
            allowed_currencies=["USD"],
        )
        self.assertEqual("INVOICE_ALREADY_PAID", refused["admission_reason"])

    def test_paypal_invoice_id_maps_merchant_reference_not_local_invoice_identity(self):
        mission = self.h.order_created()
        unit = self.h.provider.orders[mission["paypal_order_id"]]["purchase_units"][0]
        self.assertEqual("invoice-demo-001", unit["invoice_id"])
        self.assertEqual(mission["payment_reference"], unit["invoice_id"])
        self.assertNotEqual(mission["trusted_invoice_id"], unit["invoice_id"])

    def test_reconciliation_rejects_changed_paypal_invoice_id(self):
        mission = self.h.order_created()
        order = self.h.provider.orders[mission["paypal_order_id"]]
        order["purchase_units"][0]["invoice_id"] = "different-merchant-reference"
        result = self.h.gate.reconcile(mission["mission_id"])
        self.assertEqual("OUTCOME_UNKNOWN", result["status"])
        self.assertIn("ANOMALY_PAYPAL_INVOICE_BINDING", result["outcome_basis"])

    def test_same_mission_create_reentry_after_unknown_is_not_dispatched(self):
        mission = self.h.order_created()
        self.h.provider.payer_approve(mission["paypal_order_id"])
        unknown = self.h.gate.capture(mission["mission_id"], drop_response=True)
        self.assertEqual("OUTCOME_UNKNOWN", unknown["status"])
        create_calls_before = self.h.provider.create_calls
        capture_calls_before = self.h.provider.capture_calls
        refused = self.h.gate.create_order(mission["mission_id"])
        self.assertEqual("NOT_DISPATCHED", refused["dispatch_decision"])
        self.assertEqual(mission["paypal_order_id"], refused["paypal_order_id"])
        self.assertEqual(create_calls_before, self.h.provider.create_calls)
        self.assertEqual(capture_calls_before, self.h.provider.capture_calls)
        self.assertEqual(
            "CREATE_REENTRY_NOT_DISPATCHED",
            self.h.gate.journal.events(mission["mission_id"])[-1]["event_type"],
        )

    def test_terminal_failure_requires_signed_supersession_for_replacement(self):
        mission = self.h.order_created()
        order = self.h.provider.orders[mission["paypal_order_id"]]
        order["status"] = "COMPLETED"
        order["purchase_units"][0]["payments"] = {"captures": [{
            "id": "CAPTURE-DECLINED",
            "status": "DECLINED",
            "amount": {"currency_code": "USD", "value": "1.00"},
        }]}
        terminal = self.h.gate.reconcile(mission["mission_id"])
        self.assertEqual("DECLINED", terminal["status"])
        self.assertEqual(
            "TERMINAL_UNSUCCESSFUL",
            self.h.gate.inspect_invoice(self.h.invoice_id)["status"],
        )
        replacement_key = "signed-supersession-replacement"
        request = self.h.gate.supersession_approval_request(
            mission["mission_id"], replacement_key
        )
        approval = sign_approval(
            self.h.approval_key,
            act_digest_value=request["approval_digest"],
            approver="os-user:test\\approver",
            expires_at=int(time.time()) + 600,
        )
        authorized = self.h.gate.authorize_supersession(
            mission["mission_id"], replacement_key, approval
        )
        self.assertEqual("NOT_DISPATCHED", authorized["dispatch"])
        replacement = self.h.proposal()
        replacement["request_key"] = replacement_key
        admitted = self.h.gate.admit(
            replacement,
            invoice_id=self.h.invoice_id,
            allowed_payees=["sandbox-merchant"],
            max_amount="1.00",
            allowed_currencies=["USD"],
        )
        self.assertEqual("ADMITTED", admitted["status"])
        self.assertEqual(authorized["supersession_id"], admitted["supersession_id"])
        self.assertEqual(
            admitted["mission_id"],
            self.h.gate.inspect_invoice(self.h.invoice_id)["active_mission_id"],
        )
        event_types = {
            event["event_type"] for event in self.h.gate.journal.events(mission["mission_id"])
        }
        self.assertIn("SIGNED_SUPERSESSION_AUTHORIZED", event_types)
        self.assertIn("SIGNED_SUPERSESSION_CONSUMED", event_types)

    def test_approval_signature_is_bound_to_act_digest(self):
        mission = self.h.admitted()
        approval = sign_approval(
            self.h.approval_key, act_digest_value="0" * 64,
            approver="os-user:test\\approver", expires_at=int(time.time()) + 600,
        )
        with self.assertRaisesRegex(GateError, "current act digest"):
            self.h.gate.approve(mission["mission_id"], approval)

    def test_approval_signature_cannot_be_replayed_to_another_mission(self):
        first = self.h.admitted()
        approval = sign_approval(
            self.h.approval_key, act_digest_value=first["act_digest"],
            approver="os-user:test\\approver", expires_at=int(time.time()) + 600,
        )
        self.h.gate.approve(first["mission_id"], approval)
        second_invoice_id = "trusted-invoice-demo-002"
        self.h.gate.register_invoice(self.h.invoice_document(second_invoice_id))
        second_proposal = self.h.proposal()
        second_proposal["request_key"] = "gate-request-002"
        second = self.h.gate.admit(
            second_proposal, invoice_id=second_invoice_id,
            allowed_payees=["sandbox-merchant"],
            max_amount="1.00", allowed_currencies=["USD"],
        )
        with self.assertRaisesRegex(GateError, "current act digest"):
            self.h.gate.approve(second["mission_id"], approval)

    def test_executor_rejects_valid_token_for_different_body(self):
        request = {
            "mission_id": "mission-1", "operation": "CAPTURE_ORDER",
            "act_digest": "a" * 64,
            "body": {"order_id": "ORDER-1", "request_id": "request-1"},
        }
        token = mint_execution_token(
            self.h.token_key, mission_id="mission-1", operation="CAPTURE_ORDER",
            act_digest_value="a" * 64, request=request,
        )
        altered = {**request, "body": {"order_id": "ORDER-2", "request_id": "request-1"}}
        with self.assertRaisesRegex(ExecutorError, "NOT_DISPATCHED"):
            self.h.executor.execute(token, altered)
        self.assertEqual(0, self.h.provider.capture_calls)

    def test_lost_confirmation_agent_recommendation_and_get_recovery(self):
        mission = self.h.order_created()
        self.h.provider.payer_approve(mission["paypal_order_id"])
        unknown = self.h.gate.capture(mission["mission_id"], drop_response=True)
        self.assertEqual("OUTCOME_UNKNOWN", unknown["status"])
        recommendation = AgentTools(self.h.db).call(
            "recommend",
            {
                "mission_id": mission["mission_id"], "recommendation": "RECONCILE",
                "rationale": "Capture confirmation was lost.", "agent_provider": "OLLAMA_LOCAL",
                "agent_model": "qwen3:8b-fixture", "prompt_digest": "c" * 64,
            },
        )
        self.assertEqual("NOT_DISPATCHED", recommendation["dispatch"])
        final = self.h.gate.reconcile(mission["mission_id"])
        self.assertEqual("COMPLETED", final["status"])
        self.assertEqual(1, self.h.provider.capture_calls)
        self.assertEqual(1, len(list(self.h.anchor_dir.glob("*.json"))))

    def test_concurrent_capture_callers_only_one_dispatches(self):
        mission = self.h.order_created()
        self.h.provider.payer_approve(mission["paypal_order_id"])
        self.h.gate.observe_payer_approval(mission["mission_id"])
        entered = threading.Event()
        release = threading.Event()
        original = self.h.provider.capture_order

        def slow(order_id, request_id):
            entered.set()
            release.wait(timeout=5)
            return original(order_id, request_id)

        self.h.provider.capture_order = slow
        outputs = []
        first = threading.Thread(target=lambda: outputs.append(self.h.gate.capture(mission["mission_id"])))
        first.start()
        self.assertTrue(entered.wait(timeout=5))
        second = self.h.gate.capture(mission["mission_id"])
        release.set()
        first.join(timeout=5)
        self.assertEqual("NOT_DISPATCHED", second["dispatch_decision"])
        self.assertEqual(1, self.h.provider.capture_calls)

    def test_approved_no_capture_after_attempt_remains_unknown(self):
        mission = self.h.order_created()
        self.h.provider.payer_approve(mission["paypal_order_id"])
        self.h.gate.observe_payer_approval(mission["mission_id"])
        with self.h.gate.journal.transaction() as connection:
            connection.execute(
                "UPDATE missions SET capture_attempted = 1, status = 'CAPTURE_ATTEMPTED' WHERE mission_id = ?",
                (mission["mission_id"],),
            )
        final = self.h.gate.reconcile(mission["mission_id"])
        self.assertEqual("OUTCOME_UNKNOWN", final["status"])
        self.assertEqual("PAYPAL_GET_CAPTURE_NOT_OBSERVED", final["outcome_basis"])
        self.assertEqual("SAME_ID_RETRY_OR_HOLD", final["next_action"])
        retry = self.h.gate.capture(mission["mission_id"])
        self.assertEqual("NOT_DISPATCHED", retry["dispatch_decision"])

    def test_human_approved_same_id_retry_inside_window_then_get(self):
        mission = self.h.order_created()
        self.h.provider.payer_approve(mission["paypal_order_id"])
        original = self.h.provider.capture_order

        def fail_before_effect(order_id, request_id):
            raise RuntimeError("injected failure before provider effect")

        self.h.provider.capture_order = fail_before_effect
        self.h.gate.capture(mission["mission_id"])
        observed = self.h.gate.reconcile(mission["mission_id"])
        self.assertEqual("PAYPAL_GET_CAPTURE_NOT_OBSERVED", observed["outcome_basis"])
        request = self.h.gate.capture_retry_approval_request(mission["mission_id"])
        approval = sign_approval(
            self.h.approval_key,
            act_digest_value=request["approval_digest"],
            approver="os-user:test\\approver",
            expires_at=int(time.time()) + 600,
        )
        self.h.provider.capture_order = original
        retried = self.h.gate.retry_capture_same_id(mission["mission_id"], approval)
        self.assertEqual("OUTCOME_UNKNOWN", retried["status"])
        self.assertEqual(1, retried["capture_retry_count"])
        final = self.h.gate.reconcile(mission["mission_id"])
        self.assertEqual("COMPLETED", final["status"])
        self.assertEqual(1, self.h.provider.capture_calls)
        with self.assertRaisesRegex(GateError, "NOT_DISPATCHED"):
            self.h.gate.retry_capture_same_id(mission["mission_id"], approval)

    def test_approved_no_capture_before_barrier_is_ready_once(self):
        mission = self.h.order_created()
        self.h.provider.payer_approve(mission["paypal_order_id"])
        observed = self.h.gate.reconcile(mission["mission_id"])
        self.assertEqual("PAYER_APPROVED", observed["status"])
        self.assertEqual("CAPTURE_ONCE", observed["next_action"])
        self.assertFalse(observed["capture_attempted"])

    def test_pending_declined_and_multiple_capture_anomaly(self):
        for capture_status, expected in (("PENDING", "OUTCOME_UNKNOWN"), ("DECLINED", "DECLINED")):
            harness = Harness()
            try:
                mission = harness.order_created()
                order = harness.provider.orders[mission["paypal_order_id"]]
                order["status"] = "COMPLETED"
                order["purchase_units"][0]["payments"] = {"captures": [{
                    "id": "CAPTURE-1", "status": capture_status,
                    "amount": {"currency_code": "USD", "value": "1.00"},
                }]}
                self.assertEqual(expected, harness.gate.reconcile(mission["mission_id"])["status"])
            finally:
                harness.close()
        mission = self.h.order_created()
        order = self.h.provider.orders[mission["paypal_order_id"]]
        order["status"] = "COMPLETED"
        capture = {"id": "C", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "1.00"}}
        order["purchase_units"][0]["payments"] = {"captures": [capture, dict(capture)]}
        result = self.h.gate.reconcile(mission["mission_id"])
        self.assertEqual("OUTCOME_UNKNOWN", result["status"])
        self.assertEqual("HOLD_FOR_REVIEW", result["next_action"])
        self.assertIn("ANOMALY_MULTIPLE_CAPTURES", result["outcome_basis"])

    def test_events_are_database_immutable_and_chain_verifies(self):
        mission = self.h.admitted()
        connection = sqlite3.connect(self.h.db)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("UPDATE events SET event_type = 'TAMPERED'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("DELETE FROM events")
        finally:
            connection.close()
        self.assertTrue(self.h.gate.journal.verify_chain(mission["mission_id"]))

    def test_trusted_invoice_authority_fields_are_database_immutable(self):
        connection = sqlite3.connect(self.h.db)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "authority fields are immutable"):
                connection.execute(
                    "UPDATE trusted_invoices SET amount = '9.00' WHERE invoice_id = ?",
                    (self.h.invoice_id,),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "cannot be deleted"):
                connection.execute(
                    "DELETE FROM trusted_invoices WHERE invoice_id = ?",
                    (self.h.invoice_id,),
                )
        finally:
            connection.close()

    def test_trusted_merchant_reference_respects_paypal_invoice_id_limit(self):
        document = self.h.invoice_document("trusted-invoice-too-long")
        document["reference"] = "x" * 128
        with self.assertRaisesRegex(GateError, "invalid authority fields"):
            self.h.gate.register_invoice(document)

    def test_provider_call_event_has_three_time_sources(self):
        mission = self.h.order_created()
        calls = [event for event in self.h.gate.journal.events(mission["mission_id"])
                 if event["event_type"] == "PAYPAL_CALL_OBSERVED"]
        timing = calls[0]["payload"]["timing"]
        self.assertIn("wall_started_at", timing)
        self.assertIn("monotonic_started_ns", timing)
        self.assertTrue(timing["paypal_date"])
        self.assertEqual("FIXTURE-NOT-PAYPAL-EVIDENCE", timing["paypal_debug_id"])

    def test_after_effect_5xx_stays_unknown_then_get_recovers(self):
        mission = self.h.order_created()
        self.h.provider.payer_approve(mission["paypal_order_id"])
        original = self.h.provider.capture_order

        def effect_then_fail(order_id, request_id):
            original(order_id, request_id)
            raise RuntimeError("injected HTTP 5xx after provider effect")

        self.h.provider.capture_order = effect_then_fail
        unknown = self.h.gate.capture(mission["mission_id"])
        self.assertEqual("OUTCOME_UNKNOWN", unknown["status"])
        final = self.h.gate.reconcile(mission["mission_id"])
        self.assertEqual("COMPLETED", final["status"])
        self.assertEqual(1, self.h.provider.capture_calls)

    def test_restart_after_barrier_and_effect_does_not_post_again(self):
        mission = self.h.order_created()
        self.h.provider.payer_approve(mission["paypal_order_id"])
        self.h.gate.observe_payer_approval(mission["mission_id"])
        with self.h.gate.journal.transaction() as connection:
            connection.execute(
                """UPDATE missions SET capture_attempted = 1, status = 'CAPTURE_ATTEMPTED'
                   WHERE mission_id = ?""",
                (mission["mission_id"],),
            )
        self.h.provider.capture_order(mission["paypal_order_id"], mission["capture_request_id"])
        restarted = GateService(
            Journal(self.h.db), self.h.executor, token_key=self.h.token_key,
            approval_key=self.h.approval_key,
        )
        refused = restarted.capture(mission["mission_id"])
        self.assertEqual("NOT_DISPATCHED", refused["dispatch_decision"])
        self.assertEqual("COMPLETED", restarted.reconcile(mission["mission_id"])["status"])
        self.assertEqual(1, self.h.provider.capture_calls)

    def test_lost_create_response_replays_same_request_id_only(self):
        mission = self.h.approved()
        unknown = self.h.gate.create_order(mission["mission_id"], drop_response=True)
        self.assertEqual("OUTCOME_UNKNOWN", unknown["status"])
        recovered = self.h.gate.retry_create_same_id(mission["mission_id"])
        self.assertEqual("ORDER_CREATED", recovered["status"])
        self.assertEqual(1, len(self.h.provider.orders))
        self.assertEqual(2, self.h.provider.create_calls)


if __name__ == "__main__":
    unittest.main()
