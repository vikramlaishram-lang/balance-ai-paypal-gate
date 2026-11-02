from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from .journal import Journal, canonical_json, sha256_text
from .paypal import approval_link, order_captures
from .security import (
    SecurityError,
    act_digest,
    capture_retry_digest,
    mint_execution_token,
    supersession_digest,
    supersession_document,
    trusted_invoice_act_digest,
    verify_approval,
)


class GateError(RuntimeError):
    pass


class ExecutorPort(Protocol):
    def execute(self, token: str, request: dict[str, Any]) -> dict[str, Any]: ...


class AnchorSink(Protocol):
    def publish(self, record: dict[str, Any]) -> None: ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _amount(value: str) -> str:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise GateError("Amount must be a decimal number.") from exc
    if not result.is_finite() or result <= 0 or result.as_tuple().exponent < -2:
        raise GateError("Amount must be positive with at most two decimal places.")
    return f"{result:.2f}"


def _public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for name in ("user_approved", "create_attempted", "capture_attempted"):
        result[name] = bool(result.get(name))
    if result.get("approval_allowlist_json"):
        result["approval_allowlist"] = json.loads(result.pop("approval_allowlist_json"))
    else:
        result.pop("approval_allowlist_json", None)
        result["approval_allowlist"] = None
    result["proposal_digest"] = result["request_digest"]
    return result


class FileAnchorSink:
    """Publishes terminal heads to a separately configured directory."""

    def __init__(self, directory: Path):
        self.directory = directory.expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def publish(self, record: dict[str, Any]) -> None:
        target = self.directory / f"{record['mission_id']}-{record['sequence']}.json"
        handle, temporary = tempfile.mkstemp(prefix="anchor-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(canonical_json(record) + "\n")
            Path(temporary).replace(target)
        finally:
            Path(temporary).unlink(missing_ok=True)


class HTTPExecutorClient:
    def __init__(self, base_url: str, timeout_seconds: int = 40):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise GateError("Executor must be a loopback HTTP service on the trusted host.")
        self.url = base_url.rstrip("/") + "/execute"
        self.timeout_seconds = timeout_seconds

    def execute(self, token: str, request: dict[str, Any]) -> dict[str, Any]:
        call = urllib.request.Request(
            self.url,
            data=canonical_json({"token": token, "request": request}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(call, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GateError(f"Executor refused or failed the call: {detail}") from exc
        except (urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GateError("Executor was unavailable or returned unreadable output.") from exc
        return result


class GateService:
    """Owns policy, approval verification, barriers, tokens, and outcome decisions."""

    def __init__(
        self,
        journal: Journal,
        executor: ExecutorPort,
        *,
        token_key: bytes,
        approval_key: bytes,
        anchor_sink: AnchorSink | None = None,
    ):
        self.journal = journal
        self.executor = executor
        self.token_key = token_key
        self.approval_key = approval_key
        self.anchor_sink = anchor_sink

    @staticmethod
    def _event_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _request_id(mission_id: str, operation: str) -> str:
        return str(uuid.uuid5(uuid.UUID(mission_id), operation))

    def _append(self, connection, mission_id: str, event_type: str, payload: dict[str, Any]) -> str:
        return self.journal.append_event(
            connection,
            event_id=self._event_id(),
            mission_id=mission_id,
            event_type=event_type,
            payload=payload,
            occurred_at=utc_now(),
        )

    @staticmethod
    def _required(connection, mission_id: str):
        row = connection.execute(
            "SELECT * FROM missions WHERE mission_id = ?", (mission_id,)
        ).fetchone()
        if not row:
            raise GateError("Mission was not found.")
        return row

    def inspect(self, mission_id: str) -> dict[str, Any]:
        row = self.journal.mission(mission_id)
        if not row:
            raise GateError("Mission was not found.")
        result = _public(row)
        result["journal_chain_valid"] = self.journal.verify_chain(mission_id)
        return result

    def register_invoice(self, document: dict[str, Any]) -> dict[str, Any]:
        required = {
            "invoice_id", "merchant_id", "amount", "currency", "reference", "operation"
        }
        if set(document) != required or not all(
            isinstance(document[name], str) for name in required
        ):
            raise GateError("Trusted invoice has an unsupported shape.")
        invoice_id = document["invoice_id"].strip()
        merchant_id = document["merchant_id"].strip()
        amount = _amount(document["amount"])
        currency = document["currency"].strip().upper()
        reference = document["reference"].strip()
        operation = document["operation"].strip().upper()
        if (
            not all((invoice_id, merchant_id, reference))
            or not re.fullmatch(r"[A-Z]{3}", currency)
            or operation != "PAYPAL_CAPTURE_ORDER"
            or len(reference) > 127
        ):
            raise GateError("Trusted invoice has missing or invalid authority fields.")
        record = {
            "amount": amount,
            "currency": currency,
            "invoice_id": invoice_id,
            "merchant_id": merchant_id,
            "operation": operation,
            "reference": reference,
        }
        digest = sha256_text(canonical_json(record))
        now = utc_now()
        with self.journal.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM trusted_invoices WHERE invoice_id = ?", (invoice_id,)
            ).fetchone()
            if existing:
                if existing["invoice_digest"] != digest:
                    raise GateError("TRUSTED_INVOICE_CONFLICT: invoice identity is immutable.")
                return dict(existing)
            connection.execute(
                """
                INSERT INTO trusted_invoices (
                    invoice_id, merchant_id, amount, currency, payment_reference,
                    operation, invoice_digest, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
                """,
                (
                    invoice_id, merchant_id, amount, currency, reference,
                    operation, digest, now, now,
                ),
            )
        return self.inspect_invoice(invoice_id)

    def inspect_invoice(self, invoice_id: str) -> dict[str, Any]:
        invoice = self.journal.invoice(invoice_id)
        if not invoice:
            raise GateError("Trusted invoice was not found.")
        return invoice

    def admit(
        self,
        proposal: dict[str, Any],
        *,
        invoice_id: str,
        allowed_payees: list[str],
        max_amount: str,
        allowed_currencies: list[str],
    ) -> dict[str, Any]:
        required = {
            "request_key", "description", "payee_id", "amount", "currency", "reference",
            "agent_provider", "agent_model", "prompt_digest", "rationale",
        }
        generated = {"act_digest", "authority", "effect"}
        proposal_fields = frozenset(proposal)
        if proposal_fields not in {frozenset(required), frozenset(required | generated)} or not all(
            isinstance(proposal[name], str) for name in required
        ):
            raise GateError("Proposal does not match the Gate admission schema.")
        amount = _amount(proposal["amount"])
        currency = proposal["currency"].strip().upper()
        payee_id = proposal["payee_id"].strip()
        reference = proposal["reference"].strip()
        description = proposal["description"].strip()
        request_key = proposal["request_key"].strip()
        if not all((payee_id, reference, description, request_key)) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise GateError("Proposal has missing or invalid payment fields.")
        proposal_act = act_digest(
            amount=amount, currency=currency, payee_id=payee_id, reference=reference
        )
        if generated.issubset(proposal):
            if (
                proposal["act_digest"] != proposal_act
                or proposal["authority"] != "NONE"
                or proposal["effect"] != "NONE"
            ):
                raise GateError("Agent proposal metadata does not match the canonical no-authority act.")
        invoice = self.inspect_invoice(invoice_id.strip())
        trusted_act = trusted_invoice_act_digest(
            invoice_id=invoice["invoice_id"],
            operation=invoice["operation"],
            amount=invoice["amount"],
            currency=invoice["currency"],
            payee_id=invoice["merchant_id"],
            reference=invoice["payment_reference"],
        )
        invoice_matches = (
            amount == invoice["amount"]
            and currency == invoice["currency"]
            and payee_id == invoice["merchant_id"]
            and reference == invoice["payment_reference"]
        )
        normalized_payees = sorted({value.strip() for value in allowed_payees if value.strip()})
        normalized_currencies = sorted({value.strip().upper() for value in allowed_currencies})
        cap = _amount(max_amount)
        policy_record = {
            "allowed_currencies": normalized_currencies,
            "allowed_payees": normalized_payees,
            "max_amount": cap,
            "paypal_mode": "sandbox",
            "version": 1,
        }
        policy_hash = sha256_text(canonical_json(policy_record))
        policy_admissible = (
            payee_id in normalized_payees
            and currency in normalized_currencies
            and Decimal(amount) <= Decimal(cap)
        )
        non_lock_checks = {
            "amount_matches_invoice": amount == invoice["amount"],
            "amount_within_policy_cap": Decimal(amount) <= Decimal(cap),
            "currency_allowed_by_policy": currency in normalized_currencies,
            "currency_matches_invoice": currency == invoice["currency"],
            "payee_allowed_by_policy": payee_id in normalized_payees,
            "payee_matches_invoice": payee_id == invoice["merchant_id"],
            "reference_matches_invoice": reference == invoice["payment_reference"],
        }
        admissible = policy_admissible and invoice_matches
        admission_reason = (
            "MATCHED_TRUSTED_INVOICE_AND_POLICY"
            if admissible
            else "TRUSTED_INVOICE_MISMATCH"
            if not invoice_matches
            else "POLICY_REJECTED"
        )
        request_record = {
            "request_key": request_key,
            "description": description,
            "payee_id": payee_id,
            "amount": amount,
            "currency": currency,
            "reference": reference,
            "proposal_act_digest": proposal_act,
            "trusted_invoice_id": invoice["invoice_id"],
            "trusted_invoice_digest": invoice["invoice_digest"],
            "act_digest": trusted_act,
        }
        request_hash = sha256_text(canonical_json(request_record))
        now = utc_now()
        with self.journal.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM missions WHERE request_key = ?", (request_key,)
            ).fetchone()
            if existing:
                if existing["request_digest"] != request_hash:
                    raise GateError("IDEMPOTENCY_CONFLICT: request key belongs to another proposal.")
                return _public(existing)
            invoice = connection.execute(
                "SELECT * FROM trusted_invoices WHERE invoice_id = ?", (invoice["invoice_id"],)
            ).fetchone()
            if not invoice:
                raise GateError("Trusted invoice disappeared during admission.")
            mission_id = str(uuid.uuid4())
            supersession = None
            if admissible and invoice["active_mission_id"]:
                supersession = connection.execute(
                    """
                    SELECT * FROM supersessions
                    WHERE invoice_id = ? AND original_mission_id = ?
                      AND replacement_request_key = ? AND replacement_act_digest = ?
                      AND status = 'AUTHORIZED'
                    """,
                    (
                        invoice["invoice_id"], invoice["active_mission_id"], request_key,
                        trusted_act,
                    ),
                ).fetchone()
                if not supersession:
                    admissible = False
                    admission_reason = (
                        "INVOICE_ALREADY_PAID"
                        if invoice["status"] == "PAID"
                        else "INVOICE_LOCKED_REQUIRES_SIGNED_SUPERSESSION"
                    )
            connection.execute(
                """
                INSERT INTO missions (
                    mission_id, request_key, request_digest, description, payment_reference,
                    payee_id, amount, currency, status, admissibility, decision, act_digest,
                    approval_limit, approval_allowlist_json, policy_hash, create_request_id,
                    capture_request_id, created_at, updated_at, trusted_invoice_id,
                    invoice_digest, proposal_act_digest, admission_reason, supersession_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, 'NONE', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mission_id, request_key, request_hash, description, reference, payee_id,
                    amount, currency, "ADMISSIBLE" if admissible else "REJECTED", trusted_act, cap,
                    canonical_json(normalized_payees), policy_hash,
                    self._request_id(mission_id, "create-order"),
                    self._request_id(mission_id, "capture-order"), now, now,
                    invoice["invoice_id"], invoice["invoice_digest"], proposal_act,
                    admission_reason, supersession["supersession_id"] if supersession else None,
                ),
            )
            self._append(
                connection,
                mission_id,
                "AGENT_PROPOSAL_RECEIVED",
                {
                    "proposal_act_digest": proposal_act,
                    "trusted_act_digest": trusted_act,
                    "trusted_invoice_id": invoice["invoice_id"],
                    "agent_provider": proposal["agent_provider"],
                    "agent_model": proposal["agent_model"],
                    "prompt_digest": proposal["prompt_digest"],
                    "rationale": proposal["rationale"],
                    "authority": "NONE",
                    "effect": "NONE",
                },
            )
            if admissible:
                if supersession:
                    connection.execute(
                        """
                        UPDATE supersessions SET status = 'CONSUMED', replacement_mission_id = ?,
                            consumed_at = ? WHERE supersession_id = ? AND status = 'AUTHORIZED'
                        """,
                        (mission_id, now, supersession["supersession_id"]),
                    )
                    self._append(
                        connection,
                        supersession["original_mission_id"],
                        "SIGNED_SUPERSESSION_CONSUMED",
                        {
                            "invoice_id": invoice["invoice_id"],
                            "replacement_mission_id": mission_id,
                            "replacement_request_key": request_key,
                            "supersession_id": supersession["supersession_id"],
                        },
                    )
                connection.execute(
                    """
                    UPDATE trusted_invoices SET status = 'LOCKED', active_mission_id = ?,
                        updated_at = ? WHERE invoice_id = ?
                    """,
                    (mission_id, now, invoice["invoice_id"]),
                )
                connection.execute(
                    "UPDATE missions SET status = 'ADMITTED', updated_at = ? WHERE mission_id = ?",
                    (now, mission_id),
                )
                self._append(
                    connection,
                    mission_id,
                    "PROPOSAL_ADMITTED",
                    {"admissibility": "ADMISSIBLE", "decision": "NONE", "policy_cap": cap,
                     "policy_payees": normalized_payees, "policy_currencies": normalized_currencies,
                     "policy_hash": policy_hash, "trusted_invoice_id": invoice["invoice_id"],
                     "invoice_digest": invoice["invoice_digest"],
                     "non_lock_checks": non_lock_checks,
                     "admission_reason": admission_reason,
                     "supersession_id": supersession["supersession_id"] if supersession else None},
                )
            else:
                connection.execute(
                    "UPDATE missions SET decision = 'HOLD', updated_at = ? WHERE mission_id = ?",
                    (now, mission_id),
                )
                self._append(
                    connection,
                    mission_id,
                    "PROPOSAL_REJECTED",
                    {"admissibility": "REJECTED", "decision": "HOLD", "effect": "NONE",
                     "trusted_invoice_id": invoice["invoice_id"],
                     "admission_reason": admission_reason,
                     "non_lock_checks": non_lock_checks,
                     "proposal_act_digest": proposal_act,
                     "trusted_act_digest": trusted_act},
                )
        return self.inspect(mission_id)

    def approve(self, mission_id: str, approval: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.journal.transaction() as connection:
            row = self._required(connection, mission_id)
            if row["status"] == "APPROVED":
                if row["approval_signature"] != approval.get("signature"):
                    raise GateError("Mission was approved by a different signature.")
                return _public(row)
            if row["status"] != "ADMITTED" or row["admissibility"] != "ADMISSIBLE":
                raise GateError("Only an admitted proposal can be approved.")
            try:
                verify_approval(
                    self.approval_key, approval, expected_act_digest=row["act_digest"]
                )
            except SecurityError as exc:
                raise GateError(str(exc)) from exc
            reused = connection.execute(
                "SELECT mission_id FROM missions WHERE approval_signature = ? AND mission_id != ?",
                (approval["signature"], mission_id),
            ).fetchone()
            if reused:
                raise GateError("Approval signature was already consumed by another mission.")
            connection.execute(
                """
                UPDATE missions SET status = 'APPROVED', decision = 'APPROVED',
                    user_approved = 1, approved_by = ?, approval_proposal_digest = ?,
                    approval_digest = ?, approval_signature = ?, updated_at = ?
                WHERE mission_id = ?
                """,
                (
                    approval["approver"], row["request_digest"], row["act_digest"],
                    approval["signature"], now, mission_id,
                ),
            )
            self._append(
                connection,
                mission_id,
                "SIGNED_APPROVAL_VERIFIED",
                {"act_digest": row["act_digest"], "approver": approval["approver"],
                 "expires_at": approval["expires_at"], "scheme": approval["scheme"]},
            )
        return self.inspect(mission_id)

    def supersession_approval_request(
        self, original_mission_id: str, replacement_request_key: str
    ) -> dict[str, Any]:
        mission = self.inspect(original_mission_id)
        replacement_request_key = replacement_request_key.strip()
        allowed_bases = {
            "PAYPAL_GET_DECLINED_CAPTURE",
            "PAYPAL_GET_ORDER_EXPIRED_OR_VOIDED",
        }
        if (
            mission["status"] != "DECLINED"
            or mission["outcome_basis"] not in allowed_bases
            or not mission.get("paypal_order_id")
        ):
            raise GateError(
                "Supersession requires a terminal unsuccessful PayPal GET outcome."
            )
        if not replacement_request_key:
            raise GateError("Supersession requires a replacement request key.")
        invoice = self.inspect_invoice(mission["trusted_invoice_id"])
        if invoice["active_mission_id"] != original_mission_id:
            raise GateError("Original mission no longer owns the trusted invoice lock.")
        document = supersession_document(
            invoice_id=invoice["invoice_id"],
            invoice_digest=invoice["invoice_digest"],
            original_mission_id=original_mission_id,
            original_paypal_order_id=mission["paypal_order_id"],
            original_outcome_basis=mission["outcome_basis"],
            replacement_request_key=replacement_request_key,
            replacement_act_digest=mission["act_digest"],
        )
        return {
            "purpose": "SUPERSESSION",
            **document,
            "amount": invoice["amount"],
            "currency": invoice["currency"],
            "payee_id": invoice["merchant_id"],
            "reference": invoice["payment_reference"],
            "approval_digest": supersession_digest(
                **{
                    key: document[key]
                    for key in (
                        "invoice_id", "invoice_digest", "original_mission_id",
                        "original_paypal_order_id", "original_outcome_basis",
                        "replacement_request_key", "replacement_act_digest",
                    )
                }
            ),
        }

    def authorize_supersession(
        self,
        original_mission_id: str,
        replacement_request_key: str,
        approval: dict[str, Any],
    ) -> dict[str, Any]:
        request = self.supersession_approval_request(
            original_mission_id, replacement_request_key
        )
        try:
            verify_approval(
                self.approval_key,
                approval,
                expected_act_digest=request["approval_digest"],
            )
        except SecurityError as exc:
            raise GateError(str(exc)) from exc
        supersession_id = str(uuid.uuid4())
        now = utc_now()
        with self.journal.transaction() as connection:
            original = self._required(connection, original_mission_id)
            invoice = connection.execute(
                "SELECT * FROM trusted_invoices WHERE invoice_id = ?",
                (request["invoice_id"],),
            ).fetchone()
            if (
                original["status"] != "DECLINED"
                or original["outcome_basis"] != request["original_outcome_basis"]
                or not invoice
                or invoice["active_mission_id"] != original_mission_id
            ):
                raise GateError("Supersession evidence changed before authorization.")
            connection.execute(
                """
                INSERT INTO supersessions (
                    supersession_id, invoice_id, original_mission_id,
                    replacement_request_key, replacement_act_digest, evidence_basis,
                    provider_order_id, approval_digest, approval_signature, approved_by,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'AUTHORIZED', ?)
                """,
                (
                    supersession_id, request["invoice_id"], original_mission_id,
                    replacement_request_key, request["replacement_act_digest"],
                    request["original_outcome_basis"], request["original_paypal_order_id"],
                    request["approval_digest"], approval["signature"], approval["approver"], now,
                ),
            )
            self._append(
                connection,
                original_mission_id,
                "SIGNED_SUPERSESSION_AUTHORIZED",
                {
                    "approval_digest": request["approval_digest"],
                    "approver": approval["approver"],
                    "evidence_basis": request["original_outcome_basis"],
                    "invoice_id": request["invoice_id"],
                    "provider_order_id": request["original_paypal_order_id"],
                    "replacement_act_digest": request["replacement_act_digest"],
                    "replacement_request_key": replacement_request_key,
                    "supersession_id": supersession_id,
                },
            )
        return {
            "supersession_id": supersession_id,
            "status": "AUTHORIZED",
            "invoice_id": request["invoice_id"],
            "original_mission_id": original_mission_id,
            "replacement_request_key": replacement_request_key,
            "replacement_act_digest": request["replacement_act_digest"],
            "dispatch": "NOT_DISPATCHED",
        }

    def _request(self, mission: dict[str, Any], operation: str, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "mission_id": mission["mission_id"],
            "operation": operation,
            "act_digest": mission["act_digest"],
            "body": body,
        }

    def _dispatch(self, mission: dict[str, Any], operation: str, body: dict[str, Any]) -> dict[str, Any]:
        request = self._request(mission, operation, body)
        token = mint_execution_token(
            self.token_key,
            mission_id=mission["mission_id"],
            operation=operation,
            act_digest_value=mission["act_digest"],
            request=request,
            ttl_seconds=60,
        )
        return self.executor.execute(token, request)

    def _record_provider_call(
        self, mission_id: str, operation: str, envelope: dict[str, Any]
    ) -> None:
        with self.journal.transaction() as connection:
            self._required(connection, mission_id)
            self._append(
                connection,
                mission_id,
                "PAYPAL_CALL_OBSERVED",
                {"operation": operation, "timing": envelope.get("timing", {})},
            )

    def create_order(self, mission_id: str, *, drop_response: bool = False) -> dict[str, Any]:
        now = utc_now()
        with self.journal.transaction() as connection:
            row = self._required(connection, mission_id)
            if row["paypal_order_id"]:
                self._append(
                    connection,
                    mission_id,
                    "CREATE_REENTRY_NOT_DISPATCHED",
                    {
                        "decision": "REUSE_ORIGINAL_ORDER",
                        "effect": "NONE",
                        "paypal_order_id": row["paypal_order_id"],
                        "reason": "MISSION_ALREADY_BOUND_TO_ORIGINAL_ORDER",
                    },
                )
                return {**_public(row), "dispatch_decision": "NOT_DISPATCHED"}
            if row["status"] != "APPROVED":
                raise GateError("A signed approval is required before order creation.")
            won = connection.execute(
                """UPDATE missions SET create_attempted = 1, create_started_at = ?, updated_at = ?
                   WHERE mission_id = ? AND create_attempted = 0""",
                (now, now, mission_id),
            ).rowcount
            if won != 1:
                raise GateError("NOT_DISPATCHED: create attempt is already latched.")
            self._append(
                connection, mission_id, "CREATE_ATTEMPT_BARRIER_COMMITTED",
                {"paypal_request_id": row["create_request_id"], "act_digest": row["act_digest"]},
            )
        mission = self.inspect(mission_id)
        body = {
            "mission_id": mission_id,
            "payee_id": mission["payee_id"],
            "amount": mission["amount"],
            "currency": mission["currency"],
            "description": mission["description"],
            "request_id": mission["create_request_id"],
            "invoice_id": mission["payment_reference"],
        }
        try:
            envelope = self._dispatch(mission, "CREATE_ORDER", body)
            self._record_provider_call(mission_id, "CREATE_ORDER", envelope)
            if not envelope.get("ok", True):
                raise GateError(f"Executor create failed: {envelope.get('error_class')}")
            if drop_response:
                raise GateError("Injected lost create-order confirmation.")
            order = envelope["payload"]
            self._validate_bindings(mission, order)
            order_id = str(order.get("id", ""))
            approve_url = approval_link(order)
            if not order_id or not approve_url:
                raise GateError("PayPal create response lacked an ID or approval URL.")
        except Exception as exc:
            with self.journal.transaction() as connection:
                connection.execute(
                    "UPDATE missions SET status = 'OUTCOME_UNKNOWN', next_action = ?, updated_at = ? WHERE mission_id = ?",
                    ("RETRY_CREATE_SAME_REQUEST_ID_WITHIN_6H", utc_now(), mission_id),
                )
                self._append(connection, mission_id, "CREATE_OUTCOME_UNKNOWN", {"error_class": type(exc).__name__})
            return self.inspect(mission_id)
        with self.journal.transaction() as connection:
            connection.execute(
                """UPDATE missions SET paypal_order_id = ?, approval_url = ?, provider_status = ?,
                   status = 'ORDER_CREATED', next_action = 'PAYER_APPROVAL', updated_at = ?
                   WHERE mission_id = ?""",
                (order_id, approve_url, order.get("status"), utc_now(), mission_id),
            )
            self._append(
                connection, mission_id, "PAYPAL_ORDER_CREATED",
                {"paypal_order_id": order_id, "paypal_request_id": mission["create_request_id"],
                 "trusted_invoice_id": mission.get("trusted_invoice_id"),
                 "paypal_invoice_id": mission["payment_reference"]},
            )
        return self.inspect(mission_id)

    def retry_create_same_id(self, mission_id: str) -> dict[str, Any]:
        mission = self.inspect(mission_id)
        if mission["status"] != "OUTCOME_UNKNOWN" or mission["next_action"] != "RETRY_CREATE_SAME_REQUEST_ID_WITHIN_6H":
            raise GateError("Create retry is not the recorded next action.")
        started = datetime.fromisoformat(mission["create_started_at"])
        if (datetime.now(timezone.utc) - started).total_seconds() >= 21600:
            raise GateError("The documented six-hour PayPal request-ID window has elapsed.")
        body = {
            "mission_id": mission_id, "payee_id": mission["payee_id"], "amount": mission["amount"],
            "currency": mission["currency"], "description": mission["description"],
            "request_id": mission["create_request_id"],
            "invoice_id": mission["payment_reference"],
        }
        envelope = self._dispatch(mission, "CREATE_ORDER", body)
        self._record_provider_call(mission_id, "CREATE_ORDER_RETRY_SAME_ID", envelope)
        if not envelope.get("ok", True):
            raise GateError(f"Executor create retry failed: {envelope.get('error_class')}")
        order = envelope["payload"]
        self._validate_bindings(mission, order)
        order_id = str(order.get("id", ""))
        approve_url = approval_link(order)
        if not order_id or not approve_url:
            raise GateError("PayPal create retry lacked an ID or approval URL.")
        with self.journal.transaction() as connection:
            connection.execute(
                """UPDATE missions SET paypal_order_id = ?, approval_url = ?, provider_status = ?,
                   status = 'ORDER_CREATED', next_action = 'PAYER_APPROVAL', updated_at = ?
                   WHERE mission_id = ?""",
                (order_id, approve_url, order.get("status"), utc_now(), mission_id),
            )
            self._append(connection, mission_id, "CREATE_RETRIED_SAME_REQUEST_ID", {"paypal_order_id": order_id})
        return self.inspect(mission_id)

    def _get_order(self, mission: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if not mission.get("paypal_order_id"):
            raise GateError("Mission has no PayPal order ID.")
        envelope = self._dispatch(
            mission, "GET_ORDER", {"order_id": mission["paypal_order_id"]}
        )
        self._record_provider_call(mission["mission_id"], "GET_ORDER", envelope)
        if not envelope.get("ok", True):
            raise GateError(f"Executor GET failed: {envelope.get('error_class')}")
        return envelope["payload"], envelope

    def observe_payer_approval(self, mission_id: str) -> dict[str, Any]:
        mission = self.inspect(mission_id)
        order, _ = self._get_order(mission)
        self._validate_bindings(mission, order)
        if order.get("status") != "APPROVED":
            raise GateError(f"PayPal order is not payer-approved; status is {order.get('status')}.")
        with self.journal.transaction() as connection:
            connection.execute(
                "UPDATE missions SET status = 'PAYER_APPROVED', provider_status = 'APPROVED', updated_at = ? WHERE mission_id = ?",
                (utc_now(), mission_id),
            )
            self._append(connection, mission_id, "PAYER_APPROVAL_OBSERVED_BY_GET", {"paypal_order_id": mission["paypal_order_id"]})
        return self.inspect(mission_id)

    def capture(self, mission_id: str, *, drop_response: bool = False) -> dict[str, Any]:
        mission = self.inspect(mission_id)
        if mission["status"] == "ORDER_CREATED":
            mission = self.observe_payer_approval(mission_id)
        now = utc_now()
        with self.journal.transaction() as connection:
            row = self._required(connection, mission_id)
            if row["capture_attempted"]:
                self._append(
                    connection, mission_id, "CAPTURE_REENTRY_NOT_DISPATCHED",
                    {"decision": "RECONCILE", "effect": "NONE"},
                )
                return {**_public(row), "dispatch_decision": "NOT_DISPATCHED"}
            if row["status"] != "PAYER_APPROVED":
                raise GateError("Capture requires payer approval established by GET.")
            won = connection.execute(
                """UPDATE missions SET capture_attempted = 1, capture_started_at = ?,
                   status = 'CAPTURE_ATTEMPTED', next_action = 'RECONCILE', updated_at = ?
                   WHERE mission_id = ? AND capture_attempted = 0""",
                (now, now, mission_id),
            ).rowcount
            if won != 1:
                raise GateError("NOT_DISPATCHED: capture attempt lost the atomic barrier race.")
            self._append(
                connection, mission_id, "CAPTURE_ATTEMPT_BARRIER_COMMITTED",
                {"paypal_request_id": row["capture_request_id"], "act_digest": row["act_digest"]},
            )
        mission = self.inspect(mission_id)
        try:
            envelope = self._dispatch(
                mission,
                "CAPTURE_ORDER",
                {"order_id": mission["paypal_order_id"], "request_id": mission["capture_request_id"]},
            )
            self._record_provider_call(mission_id, "CAPTURE_ORDER", envelope)
            if not envelope.get("ok", True):
                response_class = f"EXECUTOR_ERROR:{envelope.get('error_class')}"
            else:
                response_class = "DROPPED_AFTER_PROVIDER_EFFECT" if drop_response else "TRANSPORT_RESPONSE_RECEIVED"
        except Exception as exc:
            response_class = type(exc).__name__
        with self.journal.transaction() as connection:
            connection.execute(
                """UPDATE missions SET status = 'OUTCOME_UNKNOWN', outcome_basis = 'CAPTURE_DISPATCH_NOT_OUTCOME',
                   next_action = 'RECONCILE', updated_at = ? WHERE mission_id = ?""",
                (utc_now(), mission_id),
            )
            self._append(
                connection, mission_id, "CAPTURE_OUTCOME_UNKNOWN",
                {"response_class": response_class, "decision": "RECONCILE"},
            )
        return self.inspect(mission_id)

    def capture_retry_approval_request(self, mission_id: str) -> dict[str, Any]:
        mission = self.inspect(mission_id)
        if (
            mission["status"] != "OUTCOME_UNKNOWN"
            or mission["outcome_basis"] != "PAYPAL_GET_CAPTURE_NOT_OBSERVED"
            or not mission["capture_attempted"]
            or mission["capture_retry_count"] != 0
        ):
            raise GateError("A same-ID capture retry is not currently admissible.")
        digest = capture_retry_digest(
            mission_id=mission_id,
            paypal_order_id=mission["paypal_order_id"],
            capture_request_id=mission["capture_request_id"],
            original_act_digest=mission["act_digest"],
        )
        return {
            "purpose": "SAME_ID_CAPTURE_RETRY",
            "mission_id": mission_id,
            "paypal_order_id": mission["paypal_order_id"],
            "capture_request_id": mission["capture_request_id"],
            "original_act_digest": mission["act_digest"],
            "amount": mission["amount"],
            "currency": mission["currency"],
            "payee_id": mission["payee_id"],
            "reference": mission["payment_reference"],
            "approval_digest": digest,
        }

    def retry_capture_same_id(
        self, mission_id: str, approval: dict[str, Any]
    ) -> dict[str, Any]:
        now = utc_now()
        with self.journal.transaction() as connection:
            row = self._required(connection, mission_id)
            if (
                row["status"] != "OUTCOME_UNKNOWN"
                or row["outcome_basis"] != "PAYPAL_GET_CAPTURE_NOT_OBSERVED"
                or not row["capture_attempted"]
                or row["capture_retry_count"] != 0
            ):
                raise GateError("NOT_DISPATCHED: same-ID capture retry is not admissible.")
            started = datetime.fromisoformat(row["capture_started_at"])
            if (datetime.now(timezone.utc) - started).total_seconds() >= 21600:
                raise GateError(
                    "NOT_DISPATCHED: the documented six-hour Orders request-ID window elapsed."
                )
            retry_digest = capture_retry_digest(
                mission_id=mission_id,
                paypal_order_id=row["paypal_order_id"],
                capture_request_id=row["capture_request_id"],
                original_act_digest=row["act_digest"],
            )
            try:
                verify_approval(
                    self.approval_key,
                    approval,
                    expected_act_digest=retry_digest,
                )
            except SecurityError as exc:
                raise GateError(f"NOT_DISPATCHED: {exc}") from exc
            won = connection.execute(
                """UPDATE missions SET capture_retry_count = 1, next_action = 'RECONCILE',
                   updated_at = ? WHERE mission_id = ? AND capture_retry_count = 0""",
                (now, mission_id),
            ).rowcount
            if won != 1:
                raise GateError("NOT_DISPATCHED: same-ID capture retry is already latched.")
            self._append(
                connection,
                mission_id,
                "SAME_ID_CAPTURE_RETRY_APPROVED",
                {
                    "approval_digest": retry_digest,
                    "approver": approval["approver"],
                    "expires_at": approval["expires_at"],
                    "paypal_order_id": row["paypal_order_id"],
                    "paypal_request_id": row["capture_request_id"],
                },
            )
        mission = self.inspect(mission_id)
        try:
            envelope = self._dispatch(
                mission,
                "CAPTURE_ORDER",
                {
                    "order_id": mission["paypal_order_id"],
                    "request_id": mission["capture_request_id"],
                },
            )
            self._record_provider_call(
                mission_id, "CAPTURE_ORDER_RETRY_SAME_ID", envelope
            )
            response_class = (
                "TRANSPORT_RESPONSE_RECEIVED"
                if envelope.get("ok", True)
                else f"EXECUTOR_ERROR:{envelope.get('error_class')}"
            )
        except Exception as exc:
            response_class = type(exc).__name__
        with self.journal.transaction() as connection:
            connection.execute(
                """UPDATE missions SET status = 'OUTCOME_UNKNOWN',
                   outcome_basis = 'SAME_ID_CAPTURE_RETRY_DISPATCH_NOT_OUTCOME',
                   next_action = 'RECONCILE', updated_at = ? WHERE mission_id = ?""",
                (utc_now(), mission_id),
            )
            self._append(
                connection,
                mission_id,
                "SAME_ID_CAPTURE_RETRY_OUTCOME_UNKNOWN",
                {"response_class": response_class, "decision": "RECONCILE"},
            )
        return self.inspect(mission_id)

    def reconcile(self, mission_id: str) -> dict[str, Any]:
        mission = self.inspect(mission_id)
        try:
            order, _ = self._get_order(mission)
            self._validate_bindings(mission, order)
            captures = order_captures(order)
            if len(captures) > 1:
                raise GateError("ANOMALY_MULTIPLE_CAPTURES")
            status = "OUTCOME_UNKNOWN"
            basis = "PAYPAL_GET_ANOMALOUS_OR_UNRESOLVED"
            next_action = "HOLD_FOR_REVIEW"
            capture_id = None
            if len(captures) == 1:
                capture = captures[0]
                self._validate_capture(mission, capture)
                capture_id = capture.get("id")
                if capture.get("status") == "COMPLETED":
                    status, basis, next_action = "COMPLETED", "PAYPAL_GET_COMPLETED_CAPTURE", "NONE"
                elif capture.get("status") == "PENDING":
                    status, basis, next_action = "OUTCOME_UNKNOWN", "PAYPAL_GET_PENDING_CAPTURE", "HOLD"
                elif capture.get("status") in {"DECLINED", "FAILED"}:
                    status, basis, next_action = "DECLINED", "PAYPAL_GET_DECLINED_CAPTURE", "NEW_SIGNED_MISSION_IF_DESIRED"
            elif order.get("status") == "APPROVED":
                if mission["capture_attempted"]:
                    status = "OUTCOME_UNKNOWN"
                    basis = "PAYPAL_GET_CAPTURE_NOT_OBSERVED"
                    next_action = (
                        "SAME_ID_RETRY_OR_HOLD"
                        if mission["capture_retry_count"] == 0
                        else "HOLD_FOR_REVIEW"
                    )
                else:
                    status, basis, next_action = "PAYER_APPROVED", "PAYPAL_GET_PAYER_APPROVED", "CAPTURE_ONCE"
            elif order.get("status") in {"VOIDED", "EXPIRED"}:
                status, basis, next_action = "DECLINED", "PAYPAL_GET_ORDER_EXPIRED_OR_VOIDED", "NEW_SIGNED_MISSION_IF_DESIRED"
            elif order.get("status") in {"CREATED", "PAYER_ACTION_REQUIRED"}:
                status, basis, next_action = "ORDER_CREATED", "PAYPAL_GET_AWAITING_PAYER", "HOLD"
        except Exception as exc:
            detail = str(exc).replace("\r", " ").replace("\n", " ")[:240]
            status, basis, next_action, capture_id = (
                "OUTCOME_UNKNOWN",
                f"GET_FAILED_OR_ANOMALOUS:{type(exc).__name__}:{detail}",
                "HOLD_FOR_REVIEW", None,
            )
        with self.journal.transaction() as connection:
            connection.execute(
                """UPDATE missions SET status = ?, outcome_basis = ?, next_action = ?,
                   capture_id = COALESCE(?, capture_id), updated_at = ? WHERE mission_id = ?""",
                (status, basis, next_action, capture_id, utc_now(), mission_id),
            )
            invoice_status = None
            if mission.get("trusted_invoice_id"):
                invoice = connection.execute(
                    "SELECT * FROM trusted_invoices WHERE invoice_id = ?",
                    (mission["trusted_invoice_id"],),
                ).fetchone()
                if invoice and status == "COMPLETED":
                    invoice_status = (
                        "PAID"
                        if invoice["active_mission_id"] == mission_id
                        else "ANOMALY_MULTIPLE_PAYMENT_PATHS"
                    )
                    connection.execute(
                        "UPDATE trusted_invoices SET status = ?, updated_at = ? WHERE invoice_id = ?",
                        (invoice_status, utc_now(), mission["trusted_invoice_id"]),
                    )
                elif (
                    invoice
                    and status == "DECLINED"
                    and invoice["active_mission_id"] == mission_id
                ):
                    invoice_status = "TERMINAL_UNSUCCESSFUL"
                    connection.execute(
                        "UPDATE trusted_invoices SET status = ?, updated_at = ? WHERE invoice_id = ?",
                        (invoice_status, utc_now(), mission["trusted_invoice_id"]),
                    )
            head = self._append(
                connection, mission_id, "OUTCOME_ESTABLISHED_BY_PAYPAL_GET",
                {"status": status, "outcome_basis": basis, "next_action": next_action,
                 "capture_id": capture_id, "trusted_invoice_status": invoice_status},
            )
            sequence = connection.execute(
                "SELECT sequence FROM events WHERE event_hash = ?", (head,)
            ).fetchone()["sequence"]
        if status in {"COMPLETED", "DECLINED"} and self.anchor_sink:
            self.anchor_sink.publish(
                {"mission_id": mission_id, "sequence": sequence, "head_hash": head,
                 "terminal_state": status, "published_at": utc_now()}
            )
        return self.inspect(mission_id)

    @staticmethod
    def _validate_bindings(mission: dict[str, Any], order: dict[str, Any]) -> None:
        units = order.get("purchase_units", [])
        if len(units) != 1:
            raise GateError("ANOMALY_PURCHASE_UNIT_COUNT")
        unit = units[0]
        if unit.get("reference_id") != mission["mission_id"] or unit.get("custom_id") != mission["mission_id"]:
            raise GateError("ANOMALY_REFERENCE_BINDING")
        if mission.get("trusted_invoice_id") and unit.get("invoice_id") != mission["payment_reference"]:
            raise GateError("ANOMALY_PAYPAL_INVOICE_BINDING")
        amount = unit.get("amount", {})
        if amount.get("value") != mission["amount"] or amount.get("currency_code") != mission["currency"]:
            raise GateError("ANOMALY_AMOUNT_BINDING")
        if unit.get("payee", {}).get("merchant_id") != mission["payee_id"]:
            raise GateError("ANOMALY_PAYEE_BINDING")

    @staticmethod
    def _validate_capture(mission: dict[str, Any], capture: dict[str, Any]) -> None:
        amount = capture.get("amount", {})
        if amount.get("value") != mission["amount"] or amount.get("currency_code") != mission["currency"]:
            raise GateError("ANOMALY_CAPTURE_AMOUNT_BINDING")
