from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.contrast import run_contrast


def main() -> int:
    parser = argparse.ArgumentParser(description="Network-free deterministic demo evidence")
    parser.add_argument("--trials", type=int, default=20)
    args = parser.parse_args()
    print(
        json.dumps(
            run_contrast(args.trials, ROOT / "data" / "test-temp"),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

