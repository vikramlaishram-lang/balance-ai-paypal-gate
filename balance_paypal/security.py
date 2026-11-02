from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path
from typing import Any

from .journal import canonical_json, sha256_text


class SecurityError(RuntimeError):
    pass


def external_path(value: str, *, project_root: Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(project_root.resolve())
    except ValueError:
        return path
    raise SecurityError(f"{label} must be outside the project directory.")


def read_key_file(path: Path, *, label: str) -> bytes:
    resolved = path.expanduser().resolve()
    data = resolved.read_bytes()
    if len(data) < 32:
        raise SecurityError(f"{label} must contain at least 32 bytes.")
    return data


def act_document(*, amount: str, currency: str, payee_id: str, reference: str) -> dict[str, str]:
    return {
        "amount": amount,
        "currency": currency,
        "payee_id": payee_id,
        "reference": reference,
    }


def act_digest(**values: str) -> str:
    return sha256_text(canonical_json(act_document(**values)))


def trusted_invoice_act_document(
    *,
    invoice_id: str,
    operation: str,
    amount: str,
    currency: str,
    payee_id: str,
    reference: str,
) -> dict[str, str]:
    return {
        "amount": amount,
        "currency": currency,
        "invoice_id": invoice_id,
        "operation": operation,
        "payee_id": payee_id,
        "reference": reference,
    }


def trusted_invoice_act_digest(**values: str) -> str:
    return sha256_text(canonical_json(trusted_invoice_act_document(**values)))


def supersession_document(
    *,
    invoice_id: str,
    invoice_digest: str,
    original_mission_id: str,
    original_paypal_order_id: str,
    original_outcome_basis: str,
    replacement_request_key: str,
    replacement_act_digest: str,
) -> dict[str, str]:
    return {
        "invoice_digest": invoice_digest,
        "invoice_id": invoice_id,
        "operation": "SUPERSEDE_TERMINAL_UNSUCCESSFUL_PAYMENT",
        "original_mission_id": original_mission_id,
        "original_outcome_basis": original_outcome_basis,
        "original_paypal_order_id": original_paypal_order_id,
        "replacement_act_digest": replacement_act_digest,
        "replacement_operation": "CREATE_NEW_PAYPAL_ORDER",
        "replacement_request_key": replacement_request_key,
    }


def supersession_digest(**values: str) -> str:
    return sha256_text(canonical_json(supersession_document(**values)))


def capture_retry_document(
    *,
    mission_id: str,
    paypal_order_id: str,
    capture_request_id: str,
    original_act_digest: str,
) -> dict[str, str]:
    return {
        "capture_request_id": capture_request_id,
        "mission_id": mission_id,
        "operation": "CAPTURE_ORDER_RETRY_SAME_REQUEST_ID",
        "original_act_digest": original_act_digest,
        "paypal_order_id": paypal_order_id,
    }


def capture_retry_digest(**values: str) -> str:
    return sha256_text(canonical_json(capture_retry_document(**values)))


def request_digest(request: dict[str, Any]) -> str:
    return sha256_text(canonical_json(request))


def _mac(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_approval(
    key: bytes, *, act_digest_value: str, approver: str, expires_at: int
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "act_digest": act_digest_value,
        "approver": approver,
        "expires_at": int(expires_at),
        "scheme": "HMAC-SHA256-DEMO",
    }
    document["signature"] = _mac(key, canonical_json(document))
    return document


def verify_approval(
    key: bytes, document: dict[str, Any], *, expected_act_digest: str, now: int | None = None
) -> None:
    required = {"act_digest", "approver", "expires_at", "scheme", "signature"}
    if set(document) != required or document.get("scheme") != "HMAC-SHA256-DEMO":
        raise SecurityError("Approval document has an unsupported shape or scheme.")
    supplied = str(document["signature"])
    unsigned = {key_name: document[key_name] for key_name in required if key_name != "signature"}
    if not hmac.compare_digest(supplied, _mac(key, canonical_json(unsigned))):
        raise SecurityError("Approval signature is invalid.")
    if document["act_digest"] != expected_act_digest:
        raise SecurityError("Approval is not bound to the current act digest.")
    if int(document["expires_at"]) < int(now if now is not None else time.time()):
        raise SecurityError("Approval has expired.")
    if not str(document["approver"]).strip():
        raise SecurityError("Approval lacks an approver identity.")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def mint_execution_token(
    key: bytes,
    *,
    mission_id: str,
    operation: str,
    act_digest_value: str,
    request: dict[str, Any],
    ttl_seconds: int = 60,
    now: int | None = None,
) -> str:
    issued_at = int(now if now is not None else time.time())
    claims = {
        "act_digest": act_digest_value,
        "exp": issued_at + ttl_seconds,
        "iat": issued_at,
        "mission_id": mission_id,
        "nonce": str(uuid.uuid4()),
        "operation": operation,
        "request_digest": request_digest(request),
        "version": 1,
    }
    payload = _b64encode(canonical_json(claims).encode("utf-8"))
    return f"{payload}.{_mac(key, payload)}"


def verify_execution_token(
    key: bytes,
    token: str,
    *,
    mission_id: str,
    operation: str,
    act_digest_value: str,
    request: dict[str, Any],
    now: int | None = None,
) -> dict[str, Any]:
    try:
        payload, supplied_mac = token.split(".", 1)
        if not hmac.compare_digest(supplied_mac, _mac(key, payload)):
            raise SecurityError("Execution token signature is invalid.")
        claims = json.loads(_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecurityError("Execution token is malformed.") from exc
    current = int(now if now is not None else time.time())
    expected = {
        "mission_id": mission_id,
        "operation": operation,
        "act_digest": act_digest_value,
        "request_digest": request_digest(request),
    }
    for name, value in expected.items():
        if claims.get(name) != value:
            raise SecurityError(f"Execution token {name} does not match the request.")
    if int(claims.get("exp", 0)) < current or int(claims.get("iat", current + 1)) > current:
        raise SecurityError("Execution token is expired or not yet valid.")
    return claims
