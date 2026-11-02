from __future__ import annotations

import json
import unittest
from pathlib import Path

from balance_paypal.agent_tools import AgentTools
from balance_paypal.agent import AgentError, OllamaPaymentAgent


def response_for(value: dict[str, object]):
    return {"message": {"role": "assistant", "content": json.dumps(value)}, "done": True}


class AgentTests(unittest.TestCase):
    def test_structured_ai_intent_creates_proposal_but_no_paypal_effect(self):
        captured_payloads = []

        def transport(payload):
            captured_payloads.append(payload)
            return response_for(
                {
                    "action": "REQUEST_PAYMENT",
                    "description": "Pay the merchant invoice",
                    "payee_id": "sandbox-merchant",
                    "amount": "25.00",
                    "currency": "USD",
                    "reference": "invoice-demo-001",
                    "rationale": "The customer explicitly requested merchant checkout.",
                    "missing_fields": [],
                }
            )

        agent = OllamaPaymentAgent(model="fixture-model", transport=transport)
        intent = agent.interpret("Please pay the merchant invoice for USD 25.00")
        context = intent["agent_context"]
        proposal = AgentTools(Path("does-not-exist.sqlite3")).call(
            "propose",
            {
                "request_key": "ai-request-001", "description": intent["description"],
                "payee_id": intent["payee_id"], "amount": intent["amount"],
                "currency": intent["currency"], "reference": intent["reference"],
                "agent_provider": context["provider"], "agent_model": context["model"],
                "prompt_digest": context["prompt_digest"], "rationale": context["rationale"],
            },
        )
        self.assertEqual("NONE", proposal["authority"])
        self.assertEqual("NONE", proposal["effect"])
        self.assertEqual(0, captured_payloads[0]["options"]["temperature"])
        self.assertIsInstance(captured_payloads[0]["format"], dict)

    def test_clarification_is_not_a_payment_proposal(self):
        agent = OllamaPaymentAgent(
            transport=lambda _: response_for(
                {
                    "action": "CLARIFY",
                    "description": "Pay a merchant invoice",
                    "payee_id": "",
                    "amount": "",
                    "currency": "",
                    "reference": "",
                    "rationale": "The amount and currency were omitted.",
                    "missing_fields": ["amount", "currency"],
                }
            )
        )
        intent = agent.interpret("Pay the merchant invoice")
        self.assertEqual("CLARIFY", intent["action"])
        self.assertEqual(["amount", "currency"], intent["missing_fields"])

    def test_model_can_request_capture_retry_without_payment_authority(self):
        agent = OllamaPaymentAgent(
            transport=lambda _: response_for(
                {
                    "action": "RETRY_CAPTURE",
                    "description": "",
                    "payee_id": "",
                    "amount": "",
                    "currency": "",
                    "reference": "",
                    "rationale": "The capture response was lost, so retry it.",
                    "missing_fields": [],
                }
            )
        )
        intent = agent.interpret("Retry the capture because its response was lost")
        self.assertEqual("RETRY_CAPTURE", intent["action"])
        self.assertEqual("OLLAMA_LOCAL", intent["agent_context"]["provider"])

    def test_invalid_structured_output_is_rejected(self):
        agent = OllamaPaymentAgent(
            transport=lambda _: {"message": {"content": "not-json"}}
        )
        with self.assertRaisesRegex(AgentError, "invalid structured response"):
            agent.interpret("Pay USD 1.00 for the demo")

    def test_nonlocal_ollama_endpoint_is_refused(self):
        with self.assertRaisesRegex(AgentError, "local HTTP endpoint"):
            OllamaPaymentAgent(base_url="https://example.com")


if __name__ == "__main__":
    unittest.main()

