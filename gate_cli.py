from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.gate import FileAnchorSink, GateError, GateService, HTTPExecutorClient
from balance_paypal.journal import Journal
from balance_paypal.security import external_path, read_key_file


DEFAULT_DB = ROOT / "data" / "gate.sqlite3"


def load_policy(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "version", "paypal_mode", "merchant_id", "max_amount", "allowed_currencies"
    }
    if set(document) != required:
        raise GateError("Policy file has an unsupported shape.")
    if document["version"] != 1 or document["paypal_mode"] != "sandbox":
        raise GateError("Policy must be version 1 and locked to PayPal Sandbox.")
    if not isinstance(document["merchant_id"], str) or not document["merchant_id"].strip():
        raise GateError("Policy must name exactly one Sandbox merchant ID.")
    currencies = document["allowed_currencies"]
    if not isinstance(currencies, list) or not currencies or not all(
        isinstance(value, str) for value in currencies
    ):
        raise GateError("Policy allowed_currencies must be a non-empty string list.")
    return document


def service(database: Path) -> GateService:
    for name in list(os.environ):
        if "PAYPAL" in name.upper():
            os.environ.pop(name, None)
    token_path = os.environ.get("BALANCE_TOKEN_KEY_FILE", "").strip()
    approver_path = os.environ.get("BALANCE_APPROVER_KEY_FILE", "").strip()
    if not token_path or not approver_path:
        raise GateError("Gate requires external token and approver verification key files.")
    anchor_raw = os.environ.get("BALANCE_ANCHOR_DIR", "").strip()
    token_file = external_path(token_path, project_root=ROOT, label="Gate token key")
    approver_file = external_path(
        approver_path, project_root=ROOT, label="Approver verification key"
    )
    anchor = FileAnchorSink(
        external_path(anchor_raw, project_root=ROOT, label="Anchor directory")
    ) if anchor_raw else None
    return GateService(
        Journal(database),
        HTTPExecutorClient(os.environ.get("BALANCE_EXECUTOR_URL", "http://127.0.0.1:8766")),
        token_key=read_key_file(token_file, label="Gate token key"),
        approval_key=read_key_file(approver_file, label="Approver verification key"),
        anchor_sink=anchor,
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Balance policy and authority Gate")
    result.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = result.add_subparsers(dest="command", required=True)
    register_invoice = commands.add_parser("register-invoice")
    register_invoice.add_argument("--invoice-file", type=Path, required=True)
    show_invoice = commands.add_parser("show-invoice")
    show_invoice.add_argument("invoice_id")
    admit = commands.add_parser("admit")
    admit.add_argument("--proposal-file", type=Path, required=True)
    admit.add_argument("--policy-file", type=Path, required=True)
    admit.add_argument("--invoice-id", required=True)
    for name in (
        "show",
        "approval-request",
        "retry-approval-request",
        "create-order",
        "retry-create",
        "capture",
        "reconcile",
    ):
        command = commands.add_parser(name)
        command.add_argument("mission_id")
        if name in {"create-order", "capture"}:
            command.add_argument("--drop-response", action="store_true")
    approve = commands.add_parser("approve")
    approve.add_argument("mission_id")
    approve.add_argument("--approval-file", type=Path, required=True)
    retry_capture = commands.add_parser("retry-capture-same-id")
    retry_capture.add_argument("mission_id")
    retry_capture.add_argument("--approval-file", type=Path, required=True)
    supersession_request = commands.add_parser("supersession-request")
    supersession_request.add_argument("mission_id")
    supersession_request.add_argument("--replacement-request-key", required=True)
    authorize_supersession = commands.add_parser("authorize-supersession")
    authorize_supersession.add_argument("mission_id")
    authorize_supersession.add_argument("--replacement-request-key", required=True)
    authorize_supersession.add_argument("--approval-file", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        gate = service(args.db)
        if args.command == "register-invoice":
            output = gate.register_invoice(
                json.loads(args.invoice_file.read_text(encoding="utf-8"))
            )
        elif args.command == "show-invoice":
            output = gate.inspect_invoice(args.invoice_id)
        elif args.command == "admit":
            policy = load_policy(args.policy_file)
            output = gate.admit(
                json.loads(args.proposal_file.read_text(encoding="utf-8")),
                invoice_id=args.invoice_id,
                allowed_payees=[str(policy["merchant_id"])],
                max_amount=str(policy["max_amount"]),
                allowed_currencies=list(policy["allowed_currencies"]),
            )
        elif args.command == "show":
            output = gate.inspect(args.mission_id)
        elif args.command == "approval-request":
            mission = gate.inspect(args.mission_id)
            output = {
                "purpose": "INITIAL_PAYMENT",
                "mission_id": mission["mission_id"], "act_digest": mission["act_digest"],
                "amount": mission["amount"], "currency": mission["currency"],
                "payee_id": mission["payee_id"], "reference": mission["payment_reference"],
                "invoice_id": mission["trusted_invoice_id"],
                "invoice_digest": mission["invoice_digest"],
                "operation": "PAYPAL_CAPTURE_ORDER",
            }
        elif args.command == "retry-approval-request":
            output = gate.capture_retry_approval_request(args.mission_id)
        elif args.command == "approve":
            output = gate.approve(
                args.mission_id,
                json.loads(args.approval_file.read_text(encoding="utf-8")),
            )
        elif args.command == "create-order":
            output = gate.create_order(args.mission_id, drop_response=args.drop_response)
        elif args.command == "retry-create":
            output = gate.retry_create_same_id(args.mission_id)
        elif args.command == "capture":
            output = gate.capture(args.mission_id, drop_response=args.drop_response)
        elif args.command == "retry-capture-same-id":
            output = gate.retry_capture_same_id(
                args.mission_id,
                json.loads(args.approval_file.read_text(encoding="utf-8")),
            )
        elif args.command == "supersession-request":
            output = gate.supersession_approval_request(
                args.mission_id, args.replacement_request_key
            )
        elif args.command == "authorize-supersession":
            output = gate.authorize_supersession(
                args.mission_id,
                args.replacement_request_key,
                json.loads(args.approval_file.read_text(encoding="utf-8")),
            )
        elif args.command == "reconcile":
            output = gate.reconcile(args.mission_id)
        else:
            raise AssertionError(args.command)
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    except (GateError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
