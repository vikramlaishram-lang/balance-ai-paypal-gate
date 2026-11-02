from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.config import load_local_env, paypal_credentials_available
from balance_paypal.paypal import PayPalSandboxClient, approval_link, order_captures
from balance_paypal.security import external_path


class DemoError(RuntimeError):
    pass


def credentials() -> None:
    raw = os.environ.get("BALANCE_PAYPAL_CREDENTIAL_FILE", "").strip()
    if not raw:
        raise DemoError("Set BALANCE_PAYPAL_CREDENTIAL_FILE to an external Sandbox credential file.")
    path = external_path(raw, project_root=ROOT, label="PayPal credential file")
    load_local_env(path)
    if not paypal_credentials_available():
        raise DemoError("The external credential file lacks PayPal Sandbox credentials.")


def wait_for_buyer(client: PayPalSandboxClient, order: dict, label: str) -> None:
    url = approval_link(order)
    if not url:
        raise DemoError(f"{label} order lacks a Sandbox approval URL.")
    print(f"{label} Sandbox order: {order['id']}")
    print(url)
    phrase = input(f"After approving {label.lower()} order in Sandbox, type {label} APPROVED: ").strip()
    if phrase != f"{label} APPROVED":
        raise DemoError(f"{label} buyer approval was not confirmed.")
    observed = client.get_order(str(order["id"]))
    if observed.get("status") != "APPROVED":
        raise DemoError(
            f"PayPal still reports {observed.get('status')} for {label.lower()} order; no capture sent."
        )


def completed_capture(order: dict) -> dict:
    captures = [
        capture for capture in order_captures(order)
        if capture.get("status") == "COMPLETED"
    ]
    if len(captures) != 1:
        raise DemoError("Expected exactly one completed capture on each Sandbox order.")
    return captures[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Controlled Sandbox-only broken baseline: treat a lost confirmation as failure "
            "and create a replacement order. Never use with live credentials."
        )
    )
    parser.add_argument("--merchant-id", required=True)
    parser.add_argument("--amount", default="1.00")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--authorize-two-sandbox-orders",
        required=True,
        help="Must equal I_UNDERSTAND_TWO_SANDBOX_ORDERS",
    )
    args = parser.parse_args()
    if args.authorize_two_sandbox_orders != "I_UNDERSTAND_TWO_SANDBOX_ORDERS":
        raise SystemExit("Refused: explicit two-order Sandbox authorization phrase is missing.")
    if os.environ.get("PAYPAL_MODE", "sandbox").strip().lower() != "sandbox":
        raise SystemExit("Refused: this deliberately broken baseline is Sandbox-only.")
    credentials()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    client = PayPalSandboxClient()
    calls: list[dict[str, object]] = []

    def record(operation: str) -> None:
        calls.append(
            {
                "operation": operation,
                "paypal_debug_id": client.last_response_metadata.get("paypal_debug_id"),
                "paypal_date": client.last_response_metadata.get("paypal_date"),
            }
        )

    first_mission = str(uuid.uuid4())
    first = client.create_order(
        mission_id=first_mission,
        payee_id=args.merchant_id,
        amount=args.amount,
        currency=args.currency,
        description="Broken baseline: original merchant checkout",
        request_id=str(uuid.uuid4()),
    )
    record("CREATE_ORIGINAL_ORDER")
    wait_for_buyer(client, first, "FIRST")
    record("GET_ORIGINAL_ORDER_APPROVAL")
    client.capture_order(str(first["id"]), str(uuid.uuid4()))
    record("CAPTURE_ORIGINAL_ORDER_RESPONSE_DROPPED")
    print("Injected fault: the application discards the first capture response.")
    confirmation = input(
        "Type CREATE REPLACEMENT SANDBOX ORDER to demonstrate the broken policy: "
    ).strip()
    if confirmation != "CREATE REPLACEMENT SANDBOX ORDER":
        raise DemoError("Replacement order was not explicitly authorized.")

    second_mission = str(uuid.uuid4())
    second = client.create_order(
        mission_id=second_mission,
        payee_id=args.merchant_id,
        amount=args.amount,
        currency=args.currency,
        description="Broken baseline: replacement after unknown outcome",
        request_id=str(uuid.uuid4()),
    )
    record("CREATE_REPLACEMENT_ORDER")
    wait_for_buyer(client, second, "SECOND")
    record("GET_REPLACEMENT_ORDER_APPROVAL")
    client.capture_order(str(second["id"]), str(uuid.uuid4()))
    record("CAPTURE_REPLACEMENT_ORDER")

    first_final = client.get_order(str(first["id"]))
    record("GET_ORIGINAL_ORDER_FINAL")
    second_final = client.get_order(str(second["id"]))
    record("GET_REPLACEMENT_ORDER_FINAL")
    first_capture = completed_capture(first_final)
    second_capture = completed_capture(second_final)
    evidence = {
        "classification": "DELIBERATELY_BROKEN_SANDBOX_REPLACEMENT_ORDER_BASELINE",
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "paypal_environment": "SANDBOX",
        "real_money": False,
        "policy_error": "TREATED_UNKNOWN_AS_FAILURE_AND_CREATED_REPLACEMENT_ORDER",
        "same_order_capture_retry_tested": False,
        "orders": [
            {"order_id": first["id"], "capture_id": first_capture["id"]},
            {"order_id": second["id"], "capture_id": second_capture["id"]},
        ],
        "completed_orders": 2,
        "completed_captures": 2,
        "amount_each": args.amount,
        "currency": args.currency,
        "paypal_calls": calls,
        "credentials_recorded": False,
    }
    target = output_dir / "naive-replacement-sandbox-evidence.json"
    target.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Two separate Sandbox orders completed. This demonstrates the replacement-order risk.")
    print("Evidence: " + str(target))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DemoError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(2)
