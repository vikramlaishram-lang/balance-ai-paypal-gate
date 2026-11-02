from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.agent_tools import AgentTools


def result(message_id, value):
    return {"jsonrpc": "2.0", "id": message_id, "result": value}


def error(message_id, code, message):
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    tools = AgentTools(args.db)
    for raw in sys.stdin:
        request = {}
        try:
            request = json.loads(raw)
            method = request.get("method")
            message_id = request.get("id")
            if method == "notifications/initialized":
                continue
            if method == "initialize":
                response = result(
                    message_id,
                    {
                        "protocolVersion": request.get("params", {}).get(
                            "protocolVersion", "2025-06-18"
                        ),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "balance-agent-boundary", "version": "0.2.0"},
                        "instructions": "Pure propose, read-only inspect, and non-authoritative recommend. No PayPal credentials or write tools.",
                    },
                )
            elif method == "tools/list":
                response = result(message_id, {"tools": tools.tool_definitions()})
            elif method == "tools/call":
                params = request.get("params", {})
                value = tools.call(params.get("name", ""), params.get("arguments", {}))
                response = result(
                    message_id,
                    {
                        "content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}],
                        "structuredContent": value,
                        "isError": False,
                    },
                )
            else:
                response = error(message_id, -32601, "Method not found")
        except Exception as exc:
            response = error(request.get("id") if isinstance(request, dict) else None, -32602, str(exc))
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

