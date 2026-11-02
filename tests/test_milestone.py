from __future__ import annotations

"""Archived v0.1 fixture regression checks; not loaded by run_tests.py."""

import tempfile
import threading
import unittest
from pathlib import Path

from balance_paypal.fixture import FixturePayPalSandbox
from balance_paypal.journal import Journal
from balance_paypal.paypal import PayPalError, PayPalSandboxClient, SANDBOX_BASE_URL
from balance_paypal.service import BalanceError, BalancePayPalService


ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP = ROOT / "data" / "test-temp"
TEST_TEMP.mkdir(parents=True, exist_ok=True)


class Harness:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP)
        self.db = Path(self.temp.name) / "journal.sqlite3"
        self.provider = FixturePayPalSandbox()
        self.service = BalancePayPalService(Journal(self.db), self.provider)

    def close(self):
        self.temp.cleanup()

    def proposed(self):
        return self.service.propose(
            request_key="agent-request-001",
            description="One dollar hackathon demonstration",
            payee_id="sandbox-merchant",
            amount="1.00",
            currency="USD",
        )

    def ready(self):
        mission = self.proposed()
        self.service.approve(
            mission["mission_id"],
            approval_actor="os-user:test\\human-owner",
            proposal_digest=mission["proposal_digest"],
            max_amount="1.00",
            allowed_payees=["sandbox-merchant"],
        )
        mission = self.service.create_order(mission["mission_id"])
        self.provider.payer_approve(mission["paypal_order_id"])
        return mission


class MilestoneTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def tearDown(self):
        self.h.close()

    def test_proposal_has_no_paypal_effect(self):
        mission = self.h.proposed()
        self.assertEqual("PROPOSED", mission["status"])
        self.assertEqual(0, self.h.provider.create_calls)
        self.assertEqual(0, self.h.provider.capture_calls)

    def test_explicit_human_approval_is_required(self):
        mission = self.h.proposed()
        with self.assertRaisesRegex(BalanceError, "USER_APPROVAL_REQUIRED"):
            self.h.service.create_order(mission["mission_id"])
        self.assertEqual(0, self.h.provider.create_calls)

    def test_agent_cannot_self_approve(self):
        mission = self.h.proposed()
        with self.assertRaisesRegex(BalanceError, "human approver"):
            self.h.service.approve(
                mission["mission_id"],
                approval_actor="ai-agent",
                proposal_digest=mission["proposal_digest"],
                max_amount="1.00",
                allowed_payees=["sandbox-merchant"],
            )

    def test_proposal_idempotency_replays_without_duplicate(self):
        first = self.h.proposed()
        second = self.h.proposed()
        self.assertEqual(first["mission_id"], second["mission_id"])
        self.assertEqual(1, len(self.h.service.journal.events(first["mission_id"])))

    def test_proposal_key_conflict_is_rejected(self):
        self.h.proposed()
        with self.assertRaisesRegex(BalanceError, "IDEMPOTENCY_CONFLICT"):
            self.h.service.propose(
                request_key="agent-request-001",
                description="Different proposal",
                payee_id="sandbox-merchant",
                amount="2.00",
                currency="USD",
            )

    def test_order_creation_is_locally_idempotent(self):
        mission = self.h.proposed()
        self.h.service.approve(
            mission["mission_id"],
            approval_actor="os-user:test\\human-owner",
            proposal_digest=mission["proposal_digest"],
            max_amount="1.00",
            allowed_payees=["sandbox-merchant"],
        )
        first = self.h.service.create_order(mission["mission_id"])
        second = self.h.service.create_order(mission["mission_id"])
        self.assertEqual(first["paypal_order_id"], second["paypal_order_id"])
        self.assertEqual(1, self.h.provider.create_calls)

    def test_approval_is_bound_to_exact_digest_limit_and_payee(self):
        mission = self.h.proposed()
        with self.assertRaisesRegex(BalanceError, "APPROVAL_BINDING_MISMATCH"):
            self.h.service.approve(
                mission["mission_id"],
                approval_actor="os-user:test\\human",
                proposal_digest="0" * 64,
                max_amount="1.00",
                allowed_payees=["sandbox-merchant"],
            )
        with self.assertRaisesRegex(BalanceError, "APPROVAL_LIMIT_EXCEEDED"):
            self.h.service.approve(
                mission["mission_id"],
                approval_actor="os-user:test\\human",
                proposal_digest=mission["proposal_digest"],
                max_amount="0.50",
                allowed_payees=["sandbox-merchant"],
            )
        with self.assertRaisesRegex(BalanceError, "PAYEE_NOT_ALLOWLISTED"):
            self.h.service.approve(
                mission["mission_id"],
                approval_actor="os-user:test\\human",
                proposal_digest=mission["proposal_digest"],
                max_amount="1.00",
                allowed_payees=["different-merchant"],
            )

    def test_normal_capture_still_requires_get_reconciliation(self):
        mission = self.h.ready()
        after_capture = self.h.service.capture(mission["mission_id"])
        self.assertEqual("OUTCOME_UNKNOWN", after_capture["status"])
        self.assertEqual("CAPTURE_RESPONSE_ONLY", after_capture["outcome_basis"])
        final = self.h.service.reconcile(mission["mission_id"])
        self.assertEqual("COMPLETED", final["status"])
        self.assertEqual("PAYPAL_GET_ORDER_COMPLETED_CAPTURE", final["outcome_basis"])
        self.assertEqual(1, self.h.provider.capture_calls)

    def test_lost_confirmation_reconciles_same_order_without_second_capture(self):
        mission = self.h.ready()
        original_order_id = mission["paypal_order_id"]
        after_drop = self.h.service.capture(
            mission["mission_id"], simulate_lost_confirmation=True
        )
        self.assertEqual("OUTCOME_UNKNOWN", after_drop["status"])
        self.assertEqual(1, self.h.provider.capture_calls)
        final = self.h.service.reconcile(mission["mission_id"])
        self.assertEqual("COMPLETED", final["status"])
        self.assertEqual(original_order_id, self.h.provider.get_calls[-1])
        self.assertEqual(1, self.h.provider.capture_calls)
        self.assertEqual("FIXTURE-CAPTURE-0001", final["capture_id"])

    def test_capture_reentry_uses_get_and_never_posts_again(self):
        mission = self.h.ready()
        self.h.service.capture(mission["mission_id"], simulate_lost_confirmation=True)
        recovered = self.h.service.capture(mission["mission_id"])
        self.assertEqual("COMPLETED", recovered["status"])
        self.assertEqual(1, self.h.provider.capture_calls)

    def test_agent_retry_proposal_is_refused_without_provider_call(self):
        mission = self.h.ready()
        self.h.service.capture(mission["mission_id"], simulate_lost_confirmation=True)
        decision = self.h.service.request_capture_retry(
            mission["mission_id"],
            agent_context={
                "provider": "OLLAMA_LOCAL",
                "model": "qwen3:8b-fixture",
                "prompt_digest": "c" * 64,
                "rationale": "The model wants to repeat the capture after a timeout.",
            },
        )
        self.assertEqual("DENY", decision["decision"])
        self.assertEqual("RECONCILE_ORIGINAL_ORDER", decision["required_next_action"])
        self.assertEqual(1, self.h.provider.capture_calls)

    def test_approved_order_after_failed_dispatch_is_proven_not_captured(self):
        mission = self.h.ready()

        def fail_before_effect(order_id, request_id):
            self.h.provider.capture_calls += 1
            raise RuntimeError("injected pre-effect failure")

        self.h.provider.capture_order = fail_before_effect
        with self.assertRaisesRegex(BalanceError, "Outcome is unknown"):
            self.h.service.capture(mission["mission_id"])
        reconciled = self.h.service.reconcile(mission["mission_id"])
        self.assertEqual("CAPTURE_NOT_OBSERVED", reconciled["status"])
        self.assertEqual(
            "OPERATOR_DECIDES_SAME_ID_RETRY_WITHIN_RETENTION", reconciled["next_action"]
        )

    def test_operator_can_retry_same_id_once_after_get_proves_no_capture(self):
        mission = self.h.ready()
        original_capture = self.h.provider.capture_order
        calls = {"count": 0}

        def fail_once(order_id, request_id):
            calls["count"] += 1
            if calls["count"] == 1:
                self.h.provider.capture_calls += 1
                raise RuntimeError("injected pre-effect failure")
            return original_capture(order_id, request_id)

        self.h.provider.capture_order = fail_once
        with self.assertRaises(BalanceError):
            self.h.service.capture(mission["mission_id"])
        observed = self.h.service.reconcile(mission["mission_id"])
        final = self.h.service.retry_capture_same_id(
            mission["mission_id"],
            approval_digest=observed["approval_digest"],
            operator_actor="os-user:test\\human-owner",
        )
        self.assertEqual("COMPLETED", final["status"])
        self.assertEqual(2, self.h.provider.capture_calls)
        self.assertEqual(1, len(self.h.provider.orders))

    def test_pending_declined_and_voided_decision_table(self):
        scenarios = [
            ("PENDING", "PAYMENT_PENDING", "RECONCILE_LATER_NO_RETRY"),
            ("DECLINED", "PAYMENT_DECLINED", "STOP_OR_NEW_EXPLICIT_PROPOSAL"),
        ]
        for index, (capture_status, expected_status, expected_next) in enumerate(scenarios):
            harness = Harness()
            try:
                mission = harness.ready()
                order = harness.provider.orders[mission["paypal_order_id"]]
                order["status"] = "COMPLETED"
                order["purchase_units"][0]["payments"] = {
                    "captures": [
                        {
                            "id": f"CAPTURE-{index}",
                            "status": capture_status,
                            "amount": {"currency_code": "USD", "value": "1.00"},
                        }
                    ]
                }
                result = harness.service.reconcile(mission["mission_id"])
                self.assertEqual(expected_status, result["status"])
                self.assertEqual(expected_next, result["next_action"])
            finally:
                harness.close()
        mission = self.h.ready()
        self.h.provider.orders[mission["paypal_order_id"]]["status"] = "VOIDED"
        voided = self.h.service.reconcile(mission["mission_id"])
        self.assertEqual("ORDER_EXPIRED_OR_VOIDED", voided["status"])
        self.assertEqual("STOP_OR_NEW_EXPLICIT_PROPOSAL", voided["next_action"])

    def test_concurrent_capture_callers_produce_one_provider_post(self):
        mission = self.h.ready()
        entered = threading.Event()
        release = threading.Event()
        original_capture = self.h.provider.capture_order

        def slow_capture(order_id, request_id):
            entered.set()
            release.wait(timeout=5)
            return original_capture(order_id, request_id)

        self.h.provider.capture_order = slow_capture
        errors = []

        def invoke_capture():
            try:
                self.h.service.capture(mission["mission_id"])
            except Exception as exc:
                errors.append(exc)

        first = threading.Thread(target=invoke_capture)
        first.start()
        self.assertTrue(entered.wait(timeout=5))
        second = threading.Thread(target=invoke_capture)
        second.start()
        second.join(timeout=5)
        release.set()
        first.join(timeout=5)
        self.assertFalse(errors)
        self.assertEqual(1, self.h.provider.capture_calls)

    def test_restart_preserves_dispatch_barrier_and_reconciles(self):
        mission = self.h.ready()
        self.h.service.capture(mission["mission_id"], simulate_lost_confirmation=True)
        restarted = BalancePayPalService(Journal(self.h.db), self.h.provider)
        final = restarted.capture(mission["mission_id"])
        self.assertEqual("COMPLETED", final["status"])
        self.assertEqual(1, self.h.provider.capture_calls)

    def test_reconciliation_rejects_cross_mission_order(self):
        mission = self.h.ready()
        self.h.provider.orders[mission["paypal_order_id"]]["purchase_units"][0][
            "reference_id"
        ] = "another-mission"
        with self.assertRaisesRegex(BalanceError, "not bound"):
            self.h.service.reconcile(mission["mission_id"])

    def test_journal_chain_is_valid(self):
        mission = self.h.ready()
        self.h.service.capture(mission["mission_id"], simulate_lost_confirmation=True)
        self.h.service.reconcile(mission["mission_id"])
        self.assertTrue(self.h.service.journal.verify_chain(mission["mission_id"]))


class SandboxBoundaryTests(unittest.TestCase):
    def test_client_base_url_is_sandbox(self):
        client = PayPalSandboxClient(client_id="fixture-id", client_secret="fixture-secret")
        self.assertEqual("https://api-m.sandbox.paypal.com", client.base_url)
        self.assertEqual(SANDBOX_BASE_URL, client.base_url)

    def test_live_mode_is_refused(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"PAYPAL_MODE": "live"}):
            with self.assertRaisesRegex(PayPalError, "except sandbox"):
                PayPalSandboxClient(client_id="fixture-id", client_secret="fixture-secret")


if __name__ == "__main__":
    unittest.main()

