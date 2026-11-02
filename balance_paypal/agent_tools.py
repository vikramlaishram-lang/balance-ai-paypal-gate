from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .security import act_digest


PROPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "request_key": {"type": "string"},
        "description": {"type": "string"},
        "payee_id": {"type": "string"},
        "amount": {"type": "string"},
        "currency": {"type": "string"},
        "reference": {"type": "string"},
        "agent_provider": {"type": "string"},
        "agent_model": {"type": "string"},
        "prompt_digest": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": [
        "request_key", "description", "payee_id", "amount", "currency", "reference",
        "agent_provider", "agent_model", "prompt_digest", "rationale",
    ],
    "additionalProperties": False,
}

INSPECT_SCHEMA = {
    "type": "object",
    "properties": {"mission_id": {"type": "string"}},
    "required": ["mission_id"],
    "additionalProperties": False,
}

RECOMMEND_SCHEMA = {
    "type": "object",
    "properties": {
        "mission_id": {"type": "string"},
        "recommendation": {"type": "string", "enum": ["RECONCILE", "HOLD", "HANDOFF"]},
        "rationale": {"type": "string"},
        "agent_provider": {"type": "string"},
        "agent_model": {"type": "string"},
        "prompt_digest": {"type": "string"},
    },
    "required": [
        "mission_id", "recommendation", "rationale", "agent_provider", "agent_model",
        "prompt_digest",
    ],
    "additionalProperties": False,
}


class AgentTools:
    """Pure proposals/recommendations plus a read-only Gate projection."""

    def __init__(self, database: Path):
        self.database = database.resolve()

    @staticmethod
    def tool_definitions() -> list[dict[str, Any]]:
        return [
            {
                "name": "propose",
                "description": "Create a typed proposal document. It performs no write or payment.",
                "inputSchema": PROPOSE_SCHEMA,
            },
            {
                "name": "inspect",
                "description": "Read a sanitized mission projection from the Gate journal.",
                "inputSchema": INSPECT_SCHEMA,
            },
            {
                "name": "recommend",
                "description": "Return RECONCILE, HOLD, or HANDOFF. A recommendation is never permission.",
                "inputSchema": RECOMMEND_SCHEMA,
            },
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "propose":
            self._exact(arguments, set(PROPOSE_SCHEMA["required"]))
            result = dict(arguments)
            try:
                normalized_amount = f"{Decimal(arguments['amount']):.2f}"
            except InvalidOperation as exc:
                raise ValueError("Proposal amount is not a decimal.") from exc
            result["amount"] = normalized_amount
            result["currency"] = arguments["currency"].strip().upper()
            result["payee_id"] = arguments["payee_id"].strip()
            result["reference"] = arguments["reference"].strip()
            result["act_digest"] = act_digest(
                amount=result["amount"], currency=result["currency"],
                payee_id=result["payee_id"], reference=result["reference"],
            )
            result["authority"] = "NONE"
            result["effect"] = "NONE"
            return result
        if name == "inspect":
            self._exact(arguments, {"mission_id"})
            return self._inspect(arguments["mission_id"])
        if name == "recommend":
            self._exact(arguments, set(RECOMMEND_SCHEMA["required"]))
            if arguments["recommendation"] not in {"RECONCILE", "HOLD", "HANDOFF"}:
                raise ValueError("Unsupported recommendation.")
            return {**arguments, "authority": "NONE", "permission": False, "dispatch": "NOT_DISPATCHED"}
        raise ValueError(f"Unknown tool: {name}")

    def _inspect(self, mission_id: str) -> dict[str, Any]:
        if not self.database.exists():
            raise ValueError("Gate journal does not exist.")
        connection = sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """SELECT mission_id, status, admissibility, decision, act_digest,
                          paypal_order_id, provider_status, outcome_basis, next_action,
                          capture_attempted
                   FROM missions WHERE mission_id = ?""",
                (mission_id,),
            ).fetchone()
        finally:
            connection.close()
        if not row:
            raise ValueError("Mission was not found.")
        result = dict(row)
        result["capture_attempted"] = bool(result["capture_attempted"])
        result["read_only"] = True
        return result

    @staticmethod
    def _exact(arguments: dict[str, Any], expected: set[str]) -> None:
        if set(arguments) != expected:
            raise ValueError("Tool arguments do not exactly match the typed schema.")
        if not all(isinstance(arguments[key], str) for key in expected):
            raise ValueError("Every tool argument must be a string.")
