from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.security import (
    capture_retry_digest,
    external_path,
    read_key_file,
    sign_approval,
    supersession_digest,
    trusted_invoice_act_digest,
)


def approval_request(path: Path) -> tuple[str, dict[str, object]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    purpose = document.get("purpose")
    if purpose == "INITIAL_PAYMENT":
        required = {
            "purpose", "mission_id", "act_digest", "amount", "currency",
            "payee_id", "reference", "invoice_id", "invoice_digest", "operation",
        }
        if set(document) != required:
            raise SystemExit("Initial approval request has an unsupported shape.")
        expected = trusted_invoice_act_digest(
            invoice_id=str(document["invoice_id"]),
            operation=str(document["operation"]),
            amount=str(document["amount"]),
            currency=str(document["currency"]),
            payee_id=str(document["payee_id"]),
            reference=str(document["reference"]),
        )
        if document["act_digest"] != expected:
            raise SystemExit("Approval request act digest does not match its displayed fields.")
        digest = expected
    elif purpose == "SUPERSESSION":
        required = {
            "purpose", "invoice_id", "invoice_digest", "operation",
            "original_mission_id", "original_outcome_basis",
            "original_paypal_order_id", "replacement_act_digest",
            "replacement_operation", "replacement_request_key", "amount",
            "currency", "payee_id", "reference", "approval_digest",
        }
        if set(document) != required:
            raise SystemExit("Supersession approval request has an unsupported shape.")
        expected_act = trusted_invoice_act_digest(
            invoice_id=str(document["invoice_id"]),
            operation="PAYPAL_CAPTURE_ORDER",
            amount=str(document["amount"]),
            currency=str(document["currency"]),
            payee_id=str(document["payee_id"]),
            reference=str(document["reference"]),
        )
        if document["replacement_act_digest"] != expected_act:
            raise SystemExit("Supersession replacement act does not match the invoice fields.")
        expected = supersession_digest(
            invoice_id=str(document["invoice_id"]),
            invoice_digest=str(document["invoice_digest"]),
            original_mission_id=str(document["original_mission_id"]),
            original_paypal_order_id=str(document["original_paypal_order_id"]),
            original_outcome_basis=str(document["original_outcome_basis"]),
            replacement_request_key=str(document["replacement_request_key"]),
            replacement_act_digest=str(document["replacement_act_digest"]),
        )
        if document["approval_digest"] != expected:
            raise SystemExit("Supersession digest does not match its displayed fields.")
        digest = expected
    elif purpose == "SAME_ID_CAPTURE_RETRY":
        required = {
            "purpose", "mission_id", "paypal_order_id", "capture_request_id",
            "original_act_digest", "amount", "currency", "payee_id", "reference",
            "approval_digest",
        }
        if set(document) != required:
            raise SystemExit("Retry approval request has an unsupported shape.")
        expected = capture_retry_digest(
            mission_id=str(document["mission_id"]),
            paypal_order_id=str(document["paypal_order_id"]),
            capture_request_id=str(document["capture_request_id"]),
            original_act_digest=str(document["original_act_digest"]),
        )
        if document["approval_digest"] != expected:
            raise SystemExit("Retry approval digest does not match its displayed fields.")
        digest = expected
    else:
        raise SystemExit("Approval request has an unsupported purpose.")
    return digest, document


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Display, recompute, and sign one exact shared-key demo approval"
    )
    parser.add_argument("act_digest", nargs="?", help="Deprecated digest-only mode")
    parser.add_argument("--request-file", type=Path)
    parser.add_argument("--confirm")
    parser.add_argument("--ttl-seconds", type=int, default=600)
    args = parser.parse_args()
    if bool(args.request_file) == bool(args.act_digest):
        raise SystemExit("Provide exactly one of --request-file or the deprecated digest.")
    request = None
    if args.request_file:
        digest, request = approval_request(args.request_file)
        print("Approval request:", file=sys.stderr)
        for name in ("purpose", "invoice_id", "amount", "currency", "payee_id",
                     "reference", "operation", "mission_id", "paypal_order_id",
                     "capture_request_id", "original_mission_id",
                     "original_paypal_order_id", "original_outcome_basis",
                     "replacement_request_key", "replacement_operation"):
            if request.get(name) is not None:
                print(f"  {name}: {request[name]}", file=sys.stderr)
        print(f"  recomputed_digest: {digest}", file=sys.stderr)
        confirmation = args.confirm
        if confirmation is None:
            confirmation = input("Type APPROVE to sign exactly these displayed fields: ").strip()
        if confirmation != "APPROVE":
            raise SystemExit("Approval was not given.")
    else:
        digest = str(args.act_digest)
        print(
            "WARNING: digest-only mode does not show payment fields; use --request-file.",
            file=sys.stderr,
        )
        if args.confirm != "APPROVE":
            raise SystemExit("Digest-only mode requires --confirm APPROVE.")
    raw = os.environ.get("BALANCE_APPROVER_KEY_FILE", "").strip()
    if not raw:
        raise SystemExit("Set BALANCE_APPROVER_KEY_FILE to an external key file.")
    key_path = external_path(raw, project_root=ROOT, label="Approver key")
    key = read_key_file(key_path, label="Approver key")
    actor = f"os-user:{os.environ.get('USERDOMAIN', socket.gethostname())}\\{getpass.getuser()}"
    document = sign_approval(
        key,
        act_digest_value=digest,
        approver=actor,
        expires_at=int(time.time()) + args.ttl_seconds,
    )
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
