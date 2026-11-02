from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.journal import Journal


def main() -> int:
    parser = argparse.ArgumentParser(description="Recompute a mission event chain and check an anchor")
    parser.add_argument("mission_id")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--anchor", type=Path)
    args = parser.parse_args()
    journal = Journal(args.db)
    events = journal.events(args.mission_id)
    result = {
        "mission_id": args.mission_id,
        "chain_valid": journal.verify_chain(args.mission_id),
        "event_count": len(events),
        "head_hash": events[-1]["event_hash"] if events else None,
        "anchor_matches": None,
    }
    if args.anchor:
        anchor = json.loads(args.anchor.read_text(encoding="utf-8"))
        result["anchor_matches"] = anchor.get("head_hash") == result["head_hash"]
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["chain_valid"] and result["anchor_matches"] is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
