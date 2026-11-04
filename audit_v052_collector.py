from __future__ import annotations

import argparse
import json
from pathlib import Path

from balance_paypal.collector_audit import replay_collector_log


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a Balance collector JSONL chain")
    parser.add_argument("log", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    result = replay_collector_log(args.log)
    print(json.dumps(result, indent=2, sort_keys=True))
    good = result["chain_valid"] and (result["complete"] or args.allow_incomplete)
    return 0 if good else 2


if __name__ == "__main__":
    raise SystemExit(main())
