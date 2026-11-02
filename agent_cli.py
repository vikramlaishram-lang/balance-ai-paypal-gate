from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.agent import AgentError, OllamaPaymentAgent
from balance_paypal.config import load_local_env
from balance_paypal.mcp_client import MCPError, ProposalMCPClient


DEFAULT_DB = ROOT / "data" / "balance-paypal.sqlite3"


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Proposal-only qwen agent; no PayPal credentials or execution tools"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    propose = commands.add_parser("propose")
    propose.add_argument("--request-key", required=True)
    propose.add_argument("--prompt", required=True)
    retry = commands.add_parser("propose-retry")
    retry.add_argument("mission_id")
    retry.add_argument("--prompt", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("mission_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # The model-side process gets only its local model settings. Strip payment
    # credentials even if the parent shell accidentally contains them.
    for key in list(os.environ):
        upper = key.upper()
        if (
            "PAYPAL" in upper
            or "SECRET" in upper
            or "TOKEN" in upper
            or upper.endswith("_KEY")
            or upper.endswith("_KEY_FILE")
        ):
            os.environ.pop(key, None)
    load_local_env(ROOT / ".agent.env.local")
    try:
        with ProposalMCPClient(args.db, ROOT / "mcp_server.py") as client:
            if args.command == "inspect":
                result = client.call_tool("inspect", {"mission_id": args.mission_id})
            else:
                intent = OllamaPaymentAgent().interpret(args.prompt)
                context = intent["agent_context"]
            if args.command == "propose":
                if intent["action"] != "REQUEST_PAYMENT":
                    raise AgentError(
                        "Payment proposal requires clarification: "
                        + ", ".join(intent["missing_fields"])
                    )
                result = client.call_tool(
                    "propose",
                    {
                        "request_key": args.request_key,
                        "description": intent["description"],
                        "payee_id": intent["payee_id"],
                        "amount": intent["amount"],
                        "currency": intent["currency"],
                        "reference": intent["reference"],
                        "agent_provider": context["provider"],
                        "agent_model": context["model"],
                        "prompt_digest": context["prompt_digest"],
                        "rationale": context["rationale"],
                    },
                )
            elif args.command == "propose-retry":
                if intent["action"] != "RETRY_CAPTURE":
                    raise AgentError("The model did not produce a capture-retry proposal.")
                result = client.call_tool(
                    "recommend",
                    {
                        "mission_id": args.mission_id,
                        "recommendation": "RECONCILE",
                        "agent_provider": context["provider"],
                        "agent_model": context["model"],
                        "prompt_digest": context["prompt_digest"],
                        "rationale": context["rationale"],
                    },
                )
        print_json(result)
        return 0
    except (AgentError, MCPError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

