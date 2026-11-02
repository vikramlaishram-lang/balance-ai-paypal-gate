from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"


class PayPalError(RuntimeError):
    pass


class PayPalSandboxClient:
    """Small PayPal Orders v2 client locked to the Sandbox hostname."""

    base_url = SANDBOX_BASE_URL

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
        timeout_seconds: int = 30,
    ):
        mode = os.environ.get("PAYPAL_MODE", "sandbox").strip().lower()
        if mode != "sandbox":
            raise PayPalError("This candidate refuses every PayPal mode except sandbox.")
        self.client_id = client_id or os.environ.get("PAYPAL_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("PAYPAL_CLIENT_SECRET", "")
        if not self.client_id or not self.client_secret:
            raise PayPalError("PayPal Sandbox credentials are not configured.")
        self.return_url = return_url or os.environ.get(
            "PAYPAL_RETURN_URL", "http://localhost:8765/paypal/return"
        )
        self.cancel_url = cancel_url or os.environ.get(
            "PAYPAL_CANCEL_URL", "http://localhost:8765/paypal/cancel"
        )
        self.timeout_seconds = timeout_seconds
        self.last_response_metadata: dict[str, str | None] = {}

    def _access_token(self) -> str:
        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        basic = base64.b64encode(raw).decode("ascii")
        request = urllib.request.Request(
            f"{self.base_url}/v1/oauth2/token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("ascii"),
            method="POST",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        response = self._open(request)
        token = response.get("access_token")
        if not token:
            raise PayPalError("PayPal Sandbox did not return an access token.")
        return str(token)

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/") or self.base_url != SANDBOX_BASE_URL:
            raise PayPalError("Refused a request outside PayPal Sandbox.")
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method, headers=headers
        )
        return self._open(request)

    def _open(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = response.read()
                self.last_response_metadata = {
                    "paypal_date": response.headers.get("Date"),
                    "paypal_debug_id": response.headers.get("Paypal-Debug-Id"),
                }
        except urllib.error.HTTPError as exc:
            self.last_response_metadata = {
                "paypal_date": exc.headers.get("Date"),
                "paypal_debug_id": exc.headers.get("Paypal-Debug-Id"),
            }
            debug_id = exc.headers.get("Paypal-Debug-Id", "unavailable")
            raise PayPalError(
                f"PayPal Sandbox returned HTTP {exc.code}; debug id {debug_id}."
            ) from exc
        except urllib.error.URLError as exc:
            self.last_response_metadata = {"paypal_date": None, "paypal_debug_id": None}
            raise PayPalError("PayPal Sandbox could not be reached; outcome may be unknown.") from exc
        if not data:
            return {}
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PayPalError("PayPal Sandbox returned an unreadable response.") from exc

    def create_order(
        self,
        *,
        mission_id: str,
        payee_id: str,
        amount: str,
        currency: str,
        description: str,
        request_id: str,
        invoice_id: str | None = None,
    ) -> dict[str, Any]:
        purchase_unit = {
            "reference_id": mission_id,
            "custom_id": mission_id,
            "payee": {"merchant_id": payee_id},
            "description": description,
            "amount": {"currency_code": currency, "value": amount},
        }
        if invoice_id:
            purchase_unit["invoice_id"] = invoice_id
        return self._api_request(
            "POST",
            "/v2/checkout/orders",
            request_id=request_id,
            body={
                "intent": "CAPTURE",
                "purchase_units": [purchase_unit],
                "payment_source": {
                    "paypal": {
                        "experience_context": {
                            "return_url": self.return_url,
                            "cancel_url": self.cancel_url,
                            "user_action": "PAY_NOW",
                        }
                    }
                },
            },
        )

    def capture_order(self, order_id: str, request_id: str) -> dict[str, Any]:
        return self._api_request(
            "POST", f"/v2/checkout/orders/{order_id}/capture", body={}, request_id=request_id
        )

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._api_request("GET", f"/v2/checkout/orders/{order_id}")


def approval_link(order: dict[str, Any]) -> str | None:
    for link in order.get("links", []):
        if link.get("rel") in {"payer-action", "approve"}:
            return str(link.get("href"))
    return None


def completed_capture(order: dict[str, Any]) -> dict[str, Any] | None:
    completed = [capture for capture in order_captures(order) if capture.get("status") == "COMPLETED"]
    if len(completed) > 1:
        raise PayPalError("Reconciliation found more than one completed capture.")
    return completed[0] if completed else None


def order_captures(order: dict[str, Any]) -> list[dict[str, Any]]:
    captures: list[dict[str, Any]] = []
    for unit in order.get("purchase_units", []):
        for capture in unit.get("payments", {}).get("captures", []):
            captures.append(capture)
    return captures

