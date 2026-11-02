from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

from .journal import sha256_text


class AgentError(RuntimeError):
    pass


PAYMENT_INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["REQUEST_PAYMENT", "RETRY_CAPTURE", "CLARIFY"],
        },
        "description": {"type": "string"},
        "payee_id": {"type": "string"},
        "amount": {"type": "string"},
        "currency": {"type": "string"},
        "reference": {"type": "string"},
        "rationale": {"type": "string"},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "action",
        "description",
        "payee_id",
        "amount",
        "currency",
        "reference",
        "rationale",
        "missing_fields",
    ],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """You are the intent interpreter for a payment-safety demonstration.
Extract a proposed one-time payment or a capture-retry request from the user's instruction.
You can propose; you cannot approve, create, retry, or capture a payment. Never invent an
amount, currency, payee identifier, reference, or recipient purpose.
If any of those details are missing or ambiguous, return action CLARIFY and name the missing
fields. Return action RETRY_CAPTURE only when the user explicitly asks to repeat a capture whose
outcome is unknown; leave payment fields empty for that action. Otherwise return action
REQUEST_PAYMENT. Amount must be a positive decimal string with at most two fractional digits,
and currency must be a three-letter uppercase ISO code.
Return only JSON matching the supplied schema."""


Transport = Callable[[dict[str, Any]], dict[str, Any]]


class OllamaPaymentAgent:
    """Local Ollama structured-output adapter; it has no PayPal capabilities."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 300,
        transport: Transport | None = None,
    ):
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise AgentError("Ollama must use a local HTTP endpoint on localhost.")
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise AgentError("Ollama base URL contains unsupported components.")
        self.model = (model or os.environ.get("OLLAMA_MODEL", "qwen3:8b")).strip()
        if not self.model:
            raise AgentError("OLLAMA_MODEL cannot be empty.")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.last_request_payload: dict[str, Any] | None = None
        self.last_raw_response: dict[str, Any] | None = None

    def interpret(self, prompt: str) -> dict[str, Any]:
        prompt = prompt.strip()
        if not prompt:
            raise AgentError("The agent instruction cannot be empty.")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "format": PAYMENT_INTENT_SCHEMA,
            "options": {"temperature": 0},
        }
        self.last_request_payload = payload
        response = self.transport(payload) if self.transport else self._http_call(payload)
        self.last_raw_response = response
        try:
            raw_content = response["message"]["content"]
            intent = json.loads(raw_content)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AgentError("Ollama returned an invalid structured response.") from exc
        self._validate(intent)
        intent["agent_context"] = {
            "provider": "OLLAMA_LOCAL",
            "model": self.model,
            "prompt_digest": sha256_text(prompt),
            "rationale": intent["rationale"],
        }
        return intent

    def _http_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AgentError(
                "Local Ollama is unavailable. Start Ollama and pull the configured model."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentError("Local Ollama returned an unreadable response.") from exc

    @staticmethod
    def _validate(intent: Any) -> None:
        if not isinstance(intent, dict):
            raise AgentError("Agent output must be an object.")
        expected = set(PAYMENT_INTENT_SCHEMA["required"])
        if set(intent) != expected:
            raise AgentError("Agent output fields do not match the payment-intent schema.")
        if intent["action"] not in {"REQUEST_PAYMENT", "RETRY_CAPTURE", "CLARIFY"}:
            raise AgentError("Agent output contains an unsupported action.")
        if not isinstance(intent["missing_fields"], list) or not all(
            isinstance(value, str) for value in intent["missing_fields"]
        ):
            raise AgentError("Agent missing_fields must be a string list.")
        for name in ("description", "payee_id", "amount", "currency", "reference", "rationale"):
            if not isinstance(intent[name], str):
                raise AgentError(f"Agent field {name} must be a string.")
        if intent["action"] == "CLARIFY":
            if not intent["missing_fields"]:
                raise AgentError("A clarification response must identify missing fields.")
            return
        if intent["action"] == "RETRY_CAPTURE":
            if intent["missing_fields"] or not intent["rationale"].strip():
                raise AgentError("A retry proposal must contain rationale and no missing fields.")
            return
        if intent["missing_fields"]:
            raise AgentError("A payment request cannot also contain missing fields.")
        if (
            not intent["description"].strip()
            or not intent["payee_id"].strip()
            or not intent["reference"].strip()
            or not intent["rationale"].strip()
        ):
            raise AgentError("The payment request lacks a description, payee, reference, or rationale.")

