from __future__ import annotations

from copy import deepcopy
from email.utils import formatdate
from typing import Any


class FixturePayPalSandbox:
    """Deterministic in-memory PayPal-shaped fixture. It makes no network calls."""

    def __init__(self):
        self.orders: dict[str, dict[str, Any]] = {}
        self.create_calls = 0
        self.capture_calls = 0
        self.get_calls: list[str] = []
        self._next_order = 1
        self._next_capture = 1
        self.last_response_metadata = {
            "paypal_date": formatdate(usegmt=True),
            "paypal_debug_id": "FIXTURE-NOT-PAYPAL-EVIDENCE",
        }

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
        self.last_response_metadata = {
            "paypal_date": formatdate(usegmt=True),
            "paypal_debug_id": "FIXTURE-NOT-PAYPAL-EVIDENCE",
        }
        self.create_calls += 1
        for order in self.orders.values():
            if order["_create_request_id"] == request_id:
                return deepcopy(order)
        order_id = f"FIXTURE-ORDER-{self._next_order:04d}"
        self._next_order += 1
        purchase_unit = {
            "reference_id": mission_id,
            "custom_id": mission_id,
            "payee": {"merchant_id": payee_id},
            "description": description,
            "amount": {"currency_code": currency, "value": amount},
        }
        if invoice_id:
            purchase_unit["invoice_id"] = invoice_id
        order = {
            "id": order_id,
            "intent": "CAPTURE",
            "status": "CREATED",
            "purchase_units": [purchase_unit],
            "links": [
                {"rel": "approve", "href": f"https://sandbox.example.test/approve/{order_id}"}
            ],
            "_create_request_id": request_id,
            "_capture_request_id": None,
        }
        self.orders[order_id] = order
        return deepcopy(order)

    def payer_approve(self, order_id: str) -> None:
        self.orders[order_id]["status"] = "APPROVED"

    def capture_order(self, order_id: str, request_id: str) -> dict[str, Any]:
        self.last_response_metadata = {
            "paypal_date": formatdate(usegmt=True),
            "paypal_debug_id": "FIXTURE-NOT-PAYPAL-EVIDENCE",
        }
        self.capture_calls += 1
        order = self.orders[order_id]
        if order["_capture_request_id"] == request_id:
            return deepcopy(order)
        if order["status"] != "APPROVED":
            raise RuntimeError("Fixture order is not payer-approved.")
        capture_id = f"FIXTURE-CAPTURE-{self._next_capture:04d}"
        self._next_capture += 1
        unit = order["purchase_units"][0]
        unit["payments"] = {
            "captures": [
                {
                    "id": capture_id,
                    "status": "COMPLETED",
                    "amount": deepcopy(unit["amount"]),
                }
            ]
        }
        order["status"] = "COMPLETED"
        order["_capture_request_id"] = request_id
        return deepcopy(order)

    def get_order(self, order_id: str) -> dict[str, Any]:
        self.last_response_metadata = {
            "paypal_date": formatdate(usegmt=True),
            "paypal_debug_id": "FIXTURE-NOT-PAYPAL-EVIDENCE",
        }
        self.get_calls.append(order_id)
        return deepcopy(self.orders[order_id])

