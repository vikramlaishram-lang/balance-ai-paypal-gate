from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.agent_tools import AgentTools
from balance_paypal.executor import ExecutorError, TokenBoundExecutor
from balance_paypal.fixture import FixturePayPalSandbox
from balance_paypal.gate import GateService
from balance_paypal.journal import Journal
from balance_paypal.security import mint_execution_token, sign_approval


def main() -> int:
    test_root = ROOT / "data" / "demo-temp"
    test_root.mkdir(parents=True, exist_ok=True)
    token_key = b"fixture-token-key-not-for-live-use-0001"
    approval_key = b"fixture-approval-key-not-for-live-001"
    provider = FixturePayPalSandbox()
    with tempfile.TemporaryDirectory(dir=test_root) as directory:
        database = Path(directory) / "gate.sqlite3"
        executor = TokenBoundExecutor(provider, token_key)
        gate = GateService(
            Journal(database), executor, token_key=token_key, approval_key=approval_key
        )
        gate.register_invoice(
            {
                "invoice_id": "trusted-invoice-three-moments",
                "merchant_id": "sandbox-merchant",
                "amount": "1.00",
                "currency": "USD",
                "reference": "invoice-three-moments",
                "operation": "PAYPAL_CAPTURE_ORDER",
            }
        )
        proposal = {
            "request_key": "three-moments-001",
            "description": "One dollar PayPal safety demonstration",
            "payee_id": "sandbox-merchant",
            "amount": "1.00",
            "currency": "USD",
            "reference": "invoice-three-moments",
            "agent_provider": "OLLAMA_LOCAL",
            "agent_model": "qwen3:8b-fixture",
            "prompt_digest": "d" * 64,
            "rationale": "Fixture representation of the bounded model output.",
        }
        mission = gate.admit(
            proposal, invoice_id="trusted-invoice-three-moments",
            allowed_payees=["sandbox-merchant"], max_amount="1.00",
            allowed_currencies=["USD"],
        )
        approval = sign_approval(
            approval_key, act_digest_value=mission["act_digest"],
            approver="os-user:fixture\\approver", expires_at=int(time.time()) + 600,
        )
        gate.approve(mission["mission_id"], approval)
        mission = gate.create_order(mission["mission_id"])
        provider.payer_approve(mission["paypal_order_id"])
        unknown = gate.capture(mission["mission_id"], drop_response=True)
        recommendation = AgentTools(database).call(
            "recommend",
            {
                "mission_id": mission["mission_id"], "recommendation": "RECONCILE",
                "rationale": "The capture response was lost.", "agent_provider": "OLLAMA_LOCAL",
                "agent_model": "qwen3:8b-fixture", "prompt_digest": "e" * 64,
            },
        )
        final = gate.reconcile(mission["mission_id"])

        legitimate_request = {
            "mission_id": mission["mission_id"], "operation": "GET_ORDER",
            "act_digest": mission["act_digest"],
            "body": {"order_id": mission["paypal_order_id"]},
        }
        other_request = {
            **legitimate_request,
            "act_digest": "0" * 64,
        }
        wrong_token = mint_execution_token(
            token_key, mission_id=mission["mission_id"], operation="GET_ORDER",
            act_digest_value="0" * 64, request=other_request,
        )
        refused = False
        refusal = ""
        try:
            executor.execute(wrong_token, legitimate_request)
        except ExecutorError as exc:
            refused = True
            refusal = str(exc).split(":", 1)[0]

        output = {
            "classification": "DETERMINISTIC_FIXTURE_NO_NETWORK_NOT_LIVE_PAYPAL_OR_MODEL",
            "payment": {
                "paypal_order_id": final["paypal_order_id"],
                "capture_id": final["capture_id"],
                "after_dropped_response": unknown["status"],
                "outcome_from_get": final["status"],
                "provider_capture_calls": provider.capture_calls,
            },
            "agent_retry": {
                "recommendation": recommendation["recommendation"],
                "permission": recommendation["permission"],
                "dispatch": recommendation["dispatch"],
            },
            "wrong_digest_token": {"refused": refused, "result": refusal},
            "journal_chain_valid": gate.journal.verify_chain(mission["mission_id"]),
        }
        print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
