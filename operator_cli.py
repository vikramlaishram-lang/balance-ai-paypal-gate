from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.config import load_local_env, paypal_credentials_available
from balance_paypal.journal import Journal
from balance_paypal.paypal import PayPalSandboxClient
from balance_paypal.service import BalanceError, BalancePayPalService


DEFAULT_DB = ROOT / "data" / "balance-paypal.sqlite3"


class NoProvider:
    def __getattr__(self, name: str):
        raise BalanceError(f"{name} requires the credential-holding operator process.")


def operator_identity() -> str:
    domain = os.environ.get("USERDOMAIN", socket.gethostname())
    return f"os-user:{domain}\\{getpass.getuser()}"


def credential_file() -> Path:
    raw = os.environ.get("BALANCE_PAYPAL_CREDENTIAL_FILE", "").strip()
    if not raw:
        raise BalanceError(
            "Set BALANCE_PAYPAL_CREDENTIAL_FILE to a Sandbox credential file outside this repository."
        )
    path = Path(raw).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise BalanceError("PayPal credential file must be outside the project directory.")
    load_local_env(path)
    if not paypal_credentials_available():
        raise BalanceError("The external credential file lacks Sandbox client credentials.")
    return path


def is_inside_project(path: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(ROOT.resolve())
    except (OSError, ValueError):
        return False
    return True


def local_service(database: Path) -> BalancePayPalService:
    return BalancePayPalService(Journal(database), NoProvider())


def paypal_service(database: Path) -> BalancePayPalService:
    credential_file()
    return BalancePayPalService(Journal(database), PayPalSandboxClient())


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Credential-holding human operator boundary")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    show = commands.add_parser("show")
    show.add_argument("mission_id")
    approve = commands.add_parser("approve")
    approve.add_argument("mission_id")
    approve.add_argument("--proposal-digest", required=True)
    approve.add_argument("--max-amount", required=True)
    approve.add_argument("--allow-payee", action="append", required=True)
    for name in ("create-order", "capture", "reconcile"):
        command = commands.add_parser(name)
        command.add_argument("mission_id")
        if name == "capture":
            command.add_argument("--simulate-lost-confirmation", action="store_true")
    retry = commands.add_parser("same-id-retry")
    retry.add_argument("mission_id")
    retry.add_argument("--approval-digest", required=True)
    anchor = commands.add_parser("anchor-head")
    anchor.add_argument("mission_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    print(
        "ERROR: operator_cli.py is retired. Use gate_cli.py, approver_cli.py, and executor_cli.py.",
        file=sys.stderr,
    )
    return 2
    # The unreachable parser is retained only so old demo transcripts remain readable.
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            raw = os.environ.get("BALANCE_PAYPAL_CREDENTIAL_FILE", "")
            path = Path(raw).expanduser() if raw else None
            print_json(
                {
                    "operator_identity": operator_identity(),
                    "credential_file_configured": bool(path),
                    "credential_file_exists": bool(path and path.exists()),
                    "credential_file_inside_project": bool(path and is_inside_project(path)),
                    "values_printed": False,
                    "paypal_mode": "sandbox-only",
                }
            )
            return 0
        if args.command in {"show", "approve", "anchor-head"}:
            service = local_service(args.db)
        else:
            service = paypal_service(args.db)
        if args.command == "show":
            result = service.inspect(args.mission_id)
        elif args.command == "approve":
            result = service.approve(
                args.mission_id,
                approval_actor=operator_identity(),
                proposal_digest=args.proposal_digest,
                max_amount=args.max_amount,
                allowed_payees=args.allow_payee,
            )
        elif args.command == "create-order":
            result = service.create_order(args.mission_id)
        elif args.command == "capture":
            result = service.capture(
                args.mission_id,
                simulate_lost_confirmation=args.simulate_lost_confirmation,
            )
        elif args.command == "reconcile":
            result = service.reconcile(args.mission_id)
        elif args.command == "same-id-retry":
            result = service.retry_capture_same_id(
                args.mission_id,
                approval_digest=args.approval_digest,
                operator_actor=operator_identity(),
            )
        elif args.command == "anchor-head":
            events = service.journal.events(args.mission_id)
            result = {
                "mission_id": args.mission_id,
                "event_count": len(events),
                "head_hash": events[-1]["event_hash"] if events else None,
                "instruction": "Write this record to storage controlled by a separate principal or append-only service.",
            }
        else:
            raise AssertionError(args.command)
        print_json(result)
        return 0
    except (BalanceError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

