from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.journal import Journal, canonical_json
from balance_paypal.security import external_path, mint_execution_token, read_key_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove the Executor refuses a token bound to another act digest"
    )
    parser.add_argument("mission_id")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "gate.sqlite3")
    args = parser.parse_args()
    key_raw = os.environ.get("BALANCE_TOKEN_KEY_FILE", "").strip()
    if not key_raw:
        raise SystemExit("Set BALANCE_TOKEN_KEY_FILE to the external Gate token key.")
    endpoint = os.environ.get("BALANCE_EXECUTOR_URL", "http://127.0.0.1:8766").rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Executor URL must be loopback HTTP.")
    mission = Journal(args.db).mission(args.mission_id)
    if not mission or not mission.get("paypal_order_id"):
        raise SystemExit("Mission or PayPal order was not found.")
    real_request = {
        "mission_id": args.mission_id,
        "operation": "GET_ORDER",
        "act_digest": mission["act_digest"],
        "body": {"order_id": mission["paypal_order_id"]},
    }
    other_request = {**real_request, "act_digest": "0" * 64}
    key_path = external_path(key_raw, project_root=ROOT, label="Gate token key")
    token = mint_execution_token(
        read_key_file(key_path, label="Gate token key"),
        mission_id=args.mission_id,
        operation="GET_ORDER",
        act_digest_value="0" * 64,
        request=other_request,
    )
    request = urllib.request.Request(
        endpoint + "/execute",
        data=canonical_json({"token": token, "request": real_request}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=10).close()
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        refused = exc.code == 403 and str(body.get("error", "")).startswith("NOT_DISPATCHED:")
        result = {
            "mission_id": args.mission_id,
            "refused": refused,
            "dispatch": "NOT_DISPATCHED" if refused else "UNEXPECTED_ERROR",
            "provider_call_attempted": False if refused else None,
            "reason": str(body.get("error", "")).split(":", 1)[-1].strip(),
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if refused else 1
    print(json.dumps({"refused": False, "dispatch": "UNEXPECTEDLY_ACCEPTED"}, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
