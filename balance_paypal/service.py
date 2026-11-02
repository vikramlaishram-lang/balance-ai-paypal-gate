from __future__ import annotations

"""Archived v0.1 fixture service. Real PayPal clients are explicitly refused."""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from .journal import Journal, canonical_json, sha256_text
from .paypal import PayPalError, approval_link, completed_capture, order_captures


class PayPalPort(Protocol):
    def create_order(self, **kwargs: Any) -> dict[str, Any]: ...
    def capture_order(self, order_id: str, request_id: str) -> dict[str, Any]: ...
    def get_order(self, order_id: str) -> dict[str, Any]: ...


class BalanceError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def public_mission(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["user_approved"] = bool(result["user_approved"])
    result["capture_attempted"] = bool(result["capture_attempted"])
    if result.get("approval_allowlist_json"):
        result["approval_allowlist"] = json.loads(result.pop("approval_allowlist_json"))
    else:
        result.pop("approval_allowlist_json", None)
        result["approval_allowlist"] = None
    result["proposal_digest"] = result["request_digest"]
    return result


class BalancePayPalService:
    """Orchestrates intent, authority, PayPal dispatch, observation, and reconciliation."""

    def __init__(self, journal: Journal, paypal: PayPalPort):
        if (
            paypal.__class__.__module__ == "balance_paypal.paypal"
            and paypal.__class__.__name__ == "PayPalSandboxClient"
        ):
            raise BalanceError(
                "Legacy service is fixture-only; real PayPal calls must pass through Gate and Executor."
            )
        self.journal = journal
        self.paypal = paypal

    @staticmethod
    def _event_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _request_id(mission_id: str, operation: str) -> str:
        return str(uuid.uuid5(uuid.UUID(mission_id), operation))

    @staticmethod
    def _normalize_amount(value: str) -> str:
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise BalanceError("Amount must be a decimal number.") from exc
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise BalanceError("Amount must be positive with at most two decimal places.")
        return f"{amount:.2f}"

    def propose(
        self,
        *,
        request_key: str,
        description: str,
        payee_id: str,
        amount: str,
        currency: str = "USD",
        agent_context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_key = request_key.strip()
        description = description.strip()
        payee_id = payee_id.strip()
        currency = currency.strip().upper()
        amount = self._normalize_amount(amount)
        if not request_key or not description or not payee_id:
            raise BalanceError("Request key, description, and payee ID are required.")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise BalanceError("Currency must be a three-letter code.")
        if agent_context is not None:
            required_context = {"provider", "model", "prompt_digest", "rationale"}
            if set(agent_context) != required_context or not all(
                isinstance(agent_context[key], str) and agent_context[key].strip()
                for key in required_context
            ):
                raise BalanceError("Agent context is incomplete or invalid.")
            if not re.fullmatch(r"[0-9a-f]{64}", agent_context["prompt_digest"]):
                raise BalanceError("Agent prompt digest is invalid.")
        request = {
            "request_key": request_key,
            "description": description,
            "payee_id": payee_id,
            "amount": amount,
            "currency": currency,
        }
        digest = sha256_text(canonical_json(request))
        now = utc_now()
        with self.journal.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM missions WHERE request_key = ?", (request_key,)
            ).fetchone()
            if existing:
                if existing["request_digest"] != digest:
                    raise BalanceError("IDEMPOTENCY_CONFLICT: request key was used for another proposal.")
                return public_mission(dict(existing))
            mission_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO missions (
                    mission_id, request_key, request_digest, description, payee_id, amount, currency,
                    status, create_request_id, capture_request_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?, ?, ?)
                """,
                (
                    mission_id,
                    request_key,
                    digest,
                    description,
                    payee_id,
                    amount,
                    currency,
                    self._request_id(mission_id, "create-order"),
                    self._request_id(mission_id, "capture-order"),
                    now,
                    now,
                ),
            )
            if agent_context is not None:
                self.journal.append_event(
                    connection,
                    event_id=self._event_id(),
                    mission_id=mission_id,
                    event_type="AI_PAYMENT_INTENT_INTERPRETED",
                    payload={
                        "provider": agent_context["provider"],
                        "model": agent_context["model"],
                        "prompt_digest": agent_context["prompt_digest"],
                        "rationale": agent_context["rationale"],
                        "authority": "PROPOSAL_ONLY",
                        "effect": "NONE",
                    },
                    occurred_at=now,
                )
            self.journal.append_event(
                connection,
                event_id=self._event_id(),
                mission_id=mission_id,
                event_type="AGENT_PAYMENT_PROPOSED",
                payload={
                    "actor_class": "AI_AGENT_FIXTURE_OR_HOST",
                    "amount": amount,
                    "currency": currency,
                    "description": description,
                    "payee_id": payee_id,
                    "effect": "NONE",
                    "request_key_digest": sha256_text(request_key),
                },
                occurred_at=now,
            )
        return self.get(mission_id)

    def approve(
        self,
        mission_id: str,
        *,
        approval_actor: str,
        proposal_digest: str,
        max_amount: str,
        allowed_payees: list[str],
    ) -> dict[str, Any]:
        approved_by = approval_actor.strip()
        if not approved_by or approved_by.lower() in {"agent", "ai", "ai-agent"}:
            raise BalanceError("A named human approver distinct from the AI agent is required.")
        normalized_limit = self._normalize_amount(max_amount)
        normalized_payees = sorted({value.strip() for value in allowed_payees if value.strip()})
        if not normalized_payees:
            raise BalanceError("Approval requires a non-empty payee allowlist.")
        now = utc_now()
        with self.journal.transaction() as connection:
            row = self._required(connection, mission_id)
            if row["user_approved"]:
                if row["approval_proposal_digest"] != proposal_digest:
                    raise BalanceError("This mission already has an approval for another digest.")
                return public_mission(dict(row))
            if row["status"] != "PROPOSED":
                raise BalanceError("Only a proposed payment can receive initial user approval.")
            if proposal_digest != row["request_digest"]:
                raise BalanceError("APPROVAL_BINDING_MISMATCH: proposal digest is not current.")
            if Decimal(row["amount"]) > Decimal(normalized_limit):
                raise BalanceError("APPROVAL_LIMIT_EXCEEDED: proposal exceeds the approved limit.")
            if row["payee_id"] not in normalized_payees:
                raise BalanceError("PAYEE_NOT_ALLOWLISTED: proposal payee is not approved.")
            approval_record = {
                "actor": approved_by,
                "allowed_payees": normalized_payees,
                "max_amount": normalized_limit,
                "mission_id": mission_id,
                "proposal_digest": proposal_digest,
            }
            approval_digest = sha256_text(canonical_json(approval_record))
            connection.execute(
                """
                UPDATE missions SET user_approved = 1, approved_by = ?, status = 'USER_APPROVED',
                    approval_proposal_digest = ?, approval_limit = ?,
                    approval_allowlist_json = ?, approval_digest = ?, updated_at = ?
                WHERE mission_id = ?
                """,
                (
                    approved_by,
                    proposal_digest,
                    normalized_limit,
                    canonical_json(normalized_payees),
                    approval_digest,
                    now,
                    mission_id,
                ),
            )
            self.journal.append_event(
                connection,
                event_id=self._event_id(),
                mission_id=mission_id,
                event_type="USER_APPROVAL_GRANTED",
                payload={
                    **approval_record,
                    "approval_digest": approval_digest,
                    "effect": "NONE",
                    "scope": "CREATE_AND_CAPTURE_ONE_ORDER",
                },
                occurred_at=now,
            )
        return self.get(mission_id)

    def create_order(self, mission_id: str) -> dict[str, Any]:
        mission = self.get(mission_id)
        if not mission["user_approved"]:
            raise BalanceError("USER_APPROVAL_REQUIRED: proposal alone cannot create a PayPal order.")
        if mission["paypal_order_id"]:
            return mission
        if mission["status"] != "USER_APPROVED":
            raise BalanceError(f"Cannot create an order while mission is {mission['status']}.")
        try:
            order = self.paypal.create_order(
                mission_id=mission_id,
                payee_id=mission["payee_id"],
                amount=mission["amount"],
                currency=mission["currency"],
                description=mission["description"],
                request_id=mission["create_request_id"],
            )
        except Exception as exc:
            raise BalanceError(f"PayPal Sandbox order creation failed: {exc}") from exc
        order_id = str(order.get("id", ""))
        approve_url = approval_link(order)
        if not order_id or not approve_url:
            raise BalanceError("PayPal Sandbox order response lacked an order ID or approval URL.")
        now = utc_now()
        with self.journal.transaction() as connection:
            current = self._required(connection, mission_id)
            if current["paypal_order_id"]:
                if current["paypal_order_id"] != order_id:
                    raise BalanceError("Provider order conflict during idempotent replay.")
                return public_mission(dict(current))
            connection.execute(
                """
                UPDATE missions SET paypal_order_id = ?, approval_url = ?,
                    provider_status = ?, status = 'AWAITING_PAYER_APPROVAL', updated_at = ?
                WHERE mission_id = ?
                """,
                (order_id, approve_url, str(order.get("status", "CREATED")), now, mission_id),
            )
            self.journal.append_event(
                connection,
                event_id=self._event_id(),
                mission_id=mission_id,
                event_type="PAYPAL_ORDER_CREATED",
                payload={
                    "paypal_order_id": order_id,
                    "provider_status": order.get("status"),
                    "paypal_request_id": mission["create_request_id"],
                    "payee_id": mission["payee_id"],
                    "effect": "ORDER_ONLY_NO_CAPTURE",
                },
                occurred_at=now,
            )
        return self.get(mission_id)

    def capture(self, mission_id: str, *, simulate_lost_confirmation: bool = False) -> dict[str, Any]:
        mission = self.get(mission_id)
        order_id = mission.get("paypal_order_id")
        if not mission["user_approved"] or not order_id:
            raise BalanceError("A user-approved PayPal order is required before capture.")
        if mission["capture_attempted"]:
            # The safe recovery path is observation, never another POST /capture.
            return self.reconcile(mission_id)

        observed = self._get_provider_order(order_id)
        provider_status = str(observed.get("status", "UNKNOWN"))
        if provider_status == "COMPLETED":
            return self._apply_reconciliation(mission, observed)
        if provider_status != "APPROVED":
            raise BalanceError(
                f"PayPal payer approval is required; current provider status is {provider_status}."
            )

        # Persist the one-way dispatch barrier before the network write. A crash after
        # this commit can only reconcile; it cannot blindly capture again.
        now = utc_now()
        with self.journal.transaction() as connection:
            current = self._required(connection, mission_id)
            if current["capture_attempted"]:
                raise BalanceError(
                    "Capture dispatch was already recorded by another caller; run reconcile."
                )
            connection.execute(
                """
                UPDATE missions SET capture_attempted = 1, status = 'CAPTURE_DISPATCHED',
                    provider_status = 'APPROVED', capture_started_at = ?,
                    next_action = 'WAIT_OR_RECONCILE', updated_at = ? WHERE mission_id = ?
                """,
                (now, now, mission_id),
            )
            self.journal.append_event(
                connection,
                event_id=self._event_id(),
                mission_id=mission_id,
                event_type="CAPTURE_DISPATCH_STARTED",
                payload={
                    "paypal_order_id": order_id,
                    "paypal_request_id": mission["capture_request_id"],
                    "retry_policy": "RECONCILE_ONLY",
                },
                occurred_at=now,
            )

        try:
            response = self.paypal.capture_order(order_id, mission["capture_request_id"])
        except Exception as exc:
            self._record_unknown(mission_id, order_id, "TRANSPORT_OR_PROVIDER_ERROR")
            raise BalanceError(
                "Capture confirmation was unavailable. Outcome is unknown; run reconcile. "
                "No automatic second capture will be issued."
            ) from exc

        if simulate_lost_confirmation:
            # Deliberately discard the received representation before extracting any
            # status or capture ID. The fixture and live route have already applied it.
            del response
            self._record_unknown(mission_id, order_id, "CONTROLLED_RESPONSE_DROP")
            return self.get(mission_id)

        now = utc_now()
        with self.journal.transaction() as connection:
            connection.execute(
                """
                UPDATE missions SET status = 'OUTCOME_UNKNOWN', provider_status = ?,
                    outcome_basis = 'CAPTURE_RESPONSE_ONLY', next_action = 'RECONCILE_ORDER',
                    updated_at = ? WHERE mission_id = ?
                """,
                (str(response.get("status", "UNKNOWN")), now, mission_id),
            )
            self.journal.append_event(
                connection,
                event_id=self._event_id(),
                mission_id=mission_id,
                event_type="PAYPAL_CAPTURE_RESPONSE_RECEIVED",
                payload={
                    "paypal_order_id": order_id,
                    "transport": "ACKNOWLEDGED",
                    "provider_status": response.get("status"),
                    "completion_admitted": False,
                },
                occurred_at=now,
            )
        return self.get(mission_id)

    def _record_unknown(self, mission_id: str, order_id: str, reason: str) -> None:
        now = utc_now()
        with self.journal.transaction() as connection:
            connection.execute(
                """
                UPDATE missions SET status = 'OUTCOME_UNKNOWN', provider_status = 'UNKNOWN',
                    outcome_basis = ?, next_action = 'RECONCILE_ORDER', updated_at = ?
                WHERE mission_id = ?
                """,
                (reason, now, mission_id),
            )
            self.journal.append_event(
                connection,
                event_id=self._event_id(),
                mission_id=mission_id,
                event_type="CAPTURE_CONFIRMATION_LOST",
                payload={
                    "paypal_order_id": order_id,
                    "transport": "CONFIRMATION_UNAVAILABLE",
                    "effect": "UNKNOWN",
                    "recovery": "GET_ORIGINAL_ORDER_ID",
                    "automatic_retry": False,
                    "reason": reason,
                },
                occurred_at=now,
            )

    def request_capture_retry(
        self, mission_id: str, *, agent_context: dict[str, str]
    ) -> dict[str, Any]:
        required = {"provider", "model", "prompt_digest", "rationale"}
        if set(agent_context) != required:
            raise BalanceError("Agent context is incomplete or invalid.")
        mission = self.get(mission_id)
        now = utc_now()
        decision = {
            "decision": "DENY",
            "reason": "AGENT_PROPOSAL_IS_NOT_RETRY_AUTHORITY",
            "mission_id": mission_id,
            "mission_status": mission["status"],
            "required_next_action": "RECONCILE_ORIGINAL_ORDER",
            "paypal_order_id": mission.get("paypal_order_id"),
        }
        with self.journal.transaction() as connection:
            self._required(connection, mission_id)
            self.journal.append_event(
                connection,
                event_id=self._event_id(),
                mission_id=mission_id,
                event_type="AI_CAPTURE_RETRY_PROPOSED_AND_REFUSED",
                payload={
                    **decision,
                    "agent_provider": agent_context["provider"],
                    "agent_model": agent_context["model"],
                    "prompt_digest": agent_context["prompt_digest"],
                    "rationale": agent_context["rationale"],
                    "effect": "NONE",
                },
                occurred_at=now,
            )
        return decision

    def retry_capture_same_id(
        self, mission_id: str, *, approval_digest: str, operator_actor: str
    ) -> dict[str, Any]:
        mission = self.get(mission_id)
        if mission["status"] != "CAPTURE_NOT_OBSERVED":
            raise BalanceError("Same-ID retry requires a fresh GET proving no capture was observed.")
        if not mission.get("approval_digest") or approval_digest != mission["approval_digest"]:
            raise BalanceError("APPROVAL_BINDING_MISMATCH: retry is not bound to the approval.")
        if mission.get("capture_retry_count", 0) != 0:
            raise BalanceError("Only one explicit same-ID recovery retry is allowed by this demo.")
        if not mission.get("capture_started_at"):
            raise BalanceError("Original capture dispatch time is unavailable.")
        started = datetime.fromisoformat(mission["capture_started_at"])
        if datetime.now(timezone.utc) - started >= timedelta(hours=6):
            raise BalanceError(
                "The documented six-hour Orders key window has elapsed; do not retry automatically."
            )
        now = utc_now()
        with self.journal.transaction() as connection:
            current = self._required(connection, mission_id)
            if current["capture_retry_count"] != 0 or current["status"] != "CAPTURE_NOT_OBSERVED":
                raise BalanceError("Concurrent recovery changed the retry decision; reconcile again.")
            connection.execute(
                """
                UPDATE missions SET capture_retry_count = 1, status = 'SAME_ID_RETRY_DISPATCHED',
                    next_action = 'RECONCILE_ORDER', updated_at = ? WHERE mission_id = ?
                """,
                (now, mission_id),
            )
            self.journal.append_event(
                connection,
                event_id=self._event_id(),
                mission_id=mission_id,
                event_type="OPERATOR_SAME_ID_CAPTURE_RETRY_AUTHORIZED",
                payload={
                    "operator_actor": operator_actor,
                    "approval_digest": approval_digest,
                    "paypal_order_id": mission["paypal_order_id"],
                    "paypal_request_id": mission["capture_request_id"],
                    "precondition": "GET_PROVED_NO_CAPTURE_AT_OBSERVATION",
                    "idempotency_window": "LESS_THAN_6_HOURS",
                },
                occurred_at=now,
            )
        try:
            self.paypal.capture_order(
                mission["paypal_order_id"], mission["capture_request_id"]
            )
        except Exception as exc:
            self._record_unknown(mission_id, mission["paypal_order_id"], "SAME_ID_RETRY_UNCONFIRMED")
            raise BalanceError("Same-ID retry was unconfirmed; reconcile the original order.") from exc
        return self.reconcile(mission_id)

    def reconcile(self, mission_id: str) -> dict[str, Any]:
        mission = self.get(mission_id)
        order_id = mission.get("paypal_order_id")
        if not order_id:
            raise BalanceError("There is no PayPal order to reconcile.")
        order = self._get_provider_order(order_id)
        return self._apply_reconciliation(mission, order)

    def _get_provider_order(self, order_id: str) -> dict[str, Any]:
        try:
            order = self.paypal.get_order(order_id)
        except Exception as exc:
            raise BalanceError("PayPal Sandbox observation failed; outcome remains unresolved.") from exc
        if str(order.get("id", "")) != order_id:
            raise BalanceError("Provider observation returned a different order ID.")
        return order

    def _apply_reconciliation(
        self, mission: dict[str, Any], order: dict[str, Any]
    ) -> dict[str, Any]:
        order_id = mission["paypal_order_id"]
        self._verify_order_binding(mission, order)
        provider_status = str(order.get("status", "UNKNOWN"))
        captures = order_captures(order)
        capture = completed_capture(order)
        if provider_status == "COMPLETED" and capture:
            amount = capture.get("amount", {})
            if amount.get("value") != mission["amount"] or amount.get("currency_code") != mission["currency"]:
                raise BalanceError("Completed capture does not match the authorized amount and currency.")
            next_status = "COMPLETED"
            capture_id = str(capture.get("id", ""))
            basis = "PAYPAL_GET_ORDER_COMPLETED_CAPTURE"
            next_action = "NONE"
        elif any(item.get("status") == "PENDING" for item in captures):
            pending = next(item for item in captures if item.get("status") == "PENDING")
            next_status = "PAYMENT_PENDING"
            capture_id = str(pending.get("id", "")) or None
            basis = "PAYPAL_GET_ORDER_PENDING_CAPTURE"
            next_action = "RECONCILE_LATER_NO_RETRY"
        elif any(item.get("status") in {"DECLINED", "FAILED"} for item in captures):
            declined = next(
                item for item in captures if item.get("status") in {"DECLINED", "FAILED"}
            )
            next_status = "PAYMENT_DECLINED"
            capture_id = str(declined.get("id", "")) or None
            basis = f"PAYPAL_GET_ORDER_{declined.get('status')}_CAPTURE"
            next_action = "STOP_OR_NEW_EXPLICIT_PROPOSAL"
        elif provider_status == "APPROVED":
            next_status = (
                "CAPTURE_NOT_OBSERVED" if mission["capture_attempted"] else "READY_TO_CAPTURE"
            )
            capture_id = None
            basis = (
                "PAYPAL_GET_ORDER_PROVES_NO_CAPTURE_AT_OBSERVATION"
                if mission["capture_attempted"]
                else "PAYPAL_GET_ORDER_APPROVED"
            )
            next_action = (
                "OPERATOR_DECIDES_SAME_ID_RETRY_WITHIN_RETENTION"
                if mission["capture_attempted"]
                else "CAPTURE_ONCE"
            )
        elif provider_status in {"CREATED", "PAYER_ACTION_REQUIRED"}:
            next_status = "AWAITING_PAYER_APPROVAL"
            capture_id = None
            basis = "PAYPAL_GET_ORDER_NOT_APPROVED"
            next_action = "WAIT_FOR_PAYER"
        elif provider_status in {"VOIDED", "EXPIRED"}:
            next_status = "ORDER_EXPIRED_OR_VOIDED"
            capture_id = None
            basis = f"PAYPAL_GET_ORDER_{provider_status}"
            next_action = "STOP_OR_NEW_EXPLICIT_PROPOSAL"
        else:
            next_status = "OUTCOME_UNKNOWN"
            capture_id = None
            basis = f"PAYPAL_GET_ORDER_{provider_status}"
            next_action = "ESCALATE_OR_RECONCILE_LATER"
        now = utc_now()
        with self.journal.transaction() as connection:
            current = self._required(connection, mission["mission_id"])
            if current["status"] == "COMPLETED" and next_status == "COMPLETED":
                return public_mission(dict(current))
            connection.execute(
                """
                UPDATE missions SET status = ?, provider_status = ?, capture_id = COALESCE(?, capture_id),
                    outcome_basis = ?, next_action = ?, updated_at = ? WHERE mission_id = ?
                """,
                (
                    next_status,
                    provider_status,
                    capture_id,
                    basis,
                    next_action,
                    now,
                    mission["mission_id"],
                ),
            )
            self.journal.append_event(
                connection,
                event_id=self._event_id(),
                mission_id=mission["mission_id"],
                event_type="PAYPAL_ORDER_OBSERVED_AND_RECONCILED",
                payload={
                    "paypal_order_id": order_id,
                    "provider_status": provider_status,
                    "capture_id": capture_id,
                    "observation_route": f"GET /v2/checkout/orders/{order_id}",
                    "observation_class": "SYSTEM_OF_RECORD_READ",
                    "established_outcome": next_status == "COMPLETED",
                    "next_status": next_status,
                    "next_action": next_action,
                    "automatic_capture_retry": False,
                },
                occurred_at=now,
            )
        return self.get(mission["mission_id"])

    @staticmethod
    def _verify_order_binding(mission: dict[str, Any], order: dict[str, Any]) -> None:
        units = order.get("purchase_units", [])
        if len(units) != 1:
            raise BalanceError("Provider observation has an unexpected purchase-unit count.")
        unit = units[0]
        if unit.get("reference_id") != mission["mission_id"]:
            raise BalanceError("Provider observation is not bound to this mission.")
        expected_amount = {"currency_code": mission["currency"], "value": mission["amount"]}
        observed_amount = unit.get("amount")
        if observed_amount != expected_amount:
            # Completed PayPal representations may keep the amount on the capture.
            capture = completed_capture(order)
            if not capture or capture.get("amount") != expected_amount:
                raise BalanceError("Provider order amount does not match the mission.")

    @staticmethod
    def _required(connection: Any, mission_id: str) -> Any:
        row = connection.execute(
            "SELECT * FROM missions WHERE mission_id = ?", (mission_id,)
        ).fetchone()
        if not row:
            raise BalanceError(f"Mission not found: {mission_id}")
        return row

    def get(self, mission_id: str) -> dict[str, Any]:
        mission = self.journal.mission(mission_id)
        if not mission:
            raise BalanceError(f"Mission not found: {mission_id}")
        return public_mission(mission)

    def inspect(self, mission_id: str) -> dict[str, Any]:
        return {
            "mission": self.get(mission_id),
            "journal_chain_valid": self.journal.verify_chain(mission_id),
            "events": self.journal.events(mission_id),
        }

