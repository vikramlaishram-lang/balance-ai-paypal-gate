from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.fault_matrix import run_fault_matrix


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials-per-fault", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(run_fault_matrix(args.trials_per_fault), indent=2, sort_keys=True))
