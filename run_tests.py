from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    suite = unittest.TestSuite()
    for pattern in (
        "test_agent.py",
        "test_cli.py",
        "test_conformance.py",
        "test_gate_architecture.py",
    ):
        suite.addTests(
            unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern)
        )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)

