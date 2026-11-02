from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Protocol

from .security import SecurityError, verify_execution_token


class ExecutorError(RuntimeError):
    pass


class PayPalExecutorPort(Protocol):
    def create_order(self, **kwargs: Any) -> dict[str, Any]: ...
    def capture_order(self, order_id: str, request_id: str) -> dict[str, Any]: ...
    def get_order(self, order_id: str) -> dict[str, Any]: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TokenBoundExecutor:
    """The only component allowed to hold PayPal credentials."""

    def __init__(self, provider: PayPalExecutorPort, token_key: bytes):
        self.provider = provider
        self.token_key = token_key

    def execute(self, token: str, request: dict[str, Any]) -> dict[str, Any]:
        required = {"mission_id", "operation", "act_digest", "body"}
        if set(request) != required or not isinstance(request["body"], dict):
            raise ExecutorError("Executor request has an invalid shape.")
        try:
            verify_execution_token(
                self.token_key,
                token,
                mission_id=str(request["mission_id"]),
                operation=str(request["operation"]),
                act_digest_value=str(request["act_digest"]),
                request=request,
            )
        except SecurityError as exc:
            raise ExecutorError(f"NOT_DISPATCHED: {exc}") from exc
        start_wall = _utc_now()
        start_mono = time.monotonic_ns()
        body = request["body"]
        operation = request["operation"]
        if operation not in {"CREATE_ORDER", "CAPTURE_ORDER", "GET_ORDER"}:
            raise ExecutorError("NOT_DISPATCHED: unsupported operation.")
        if hasattr(self.provider, "last_response_metadata"):
            self.provider.last_response_metadata = {}
        payload = None
        error_class = None
        try:
            if operation == "CREATE_ORDER":
                payload = self.provider.create_order(**body)
            elif operation == "CAPTURE_ORDER":
                payload = self.provider.capture_order(body["order_id"], body["request_id"])
            else:
                payload = self.provider.get_order(body["order_id"])
        except Exception as exc:
            error_class = type(exc).__name__
        end_mono = time.monotonic_ns()
        metadata = getattr(self.provider, "last_response_metadata", {}) or {}
        return {
            "ok": error_class is None,
            "payload": payload,
            "error_class": error_class,
            "timing": {
                "wall_started_at": start_wall,
                "wall_finished_at": _utc_now(),
                "monotonic_started_ns": start_mono,
                "monotonic_finished_ns": end_mono,
                "paypal_date": metadata.get("paypal_date"),
                "paypal_debug_id": metadata.get("paypal_debug_id"),
            },
        }
