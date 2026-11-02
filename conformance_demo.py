from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.conformance import run_mutation_suite


if __name__ == "__main__":
    print(json.dumps(run_mutation_suite(), indent=2, sort_keys=True))
