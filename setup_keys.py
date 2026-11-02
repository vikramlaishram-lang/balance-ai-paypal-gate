from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create demo Gate keys outside the project")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    root = Path(__file__).resolve().parent
    try:
        directory.relative_to(root)
    except ValueError:
        pass
    else:
        raise SystemExit("Refusing to place authority keys inside the project.")
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("gate-token.key", "approver.key"):
        target = directory / name
        if target.exists():
            raise SystemExit(f"Refusing to overwrite existing key: {target}")
        target.write_bytes(secrets.token_bytes(32))
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    print(f"Created two keys in {directory}; their values were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
