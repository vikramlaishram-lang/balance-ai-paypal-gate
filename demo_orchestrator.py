from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from balance_paypal.demo_orchestration import (
    OrchestrationError,
    free_port,
    read_only_configuration_preflight,
    run_effect_free_preflight,
    run_live_orchestrated,
    tree_identity,
    write_json,
)


ROOT = Path(__file__).resolve().parent


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Balance v0.5.2 demo orchestration candidate")
    commands = result.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("effect-free-preflight")
    preflight.add_argument("--output-dir", type=Path, required=True)
    preflight.add_argument("--collector-port", type=int, default=0)
    preflight.add_argument("--executor-port", type=int, default=0)

    config = commands.add_parser("config-preflight")
    config.add_argument("--output", type=Path)
    config.add_argument("--collector-port", type=int, default=8767)
    config.add_argument("--executor-port", type=int, default=8766)

    identity = commands.add_parser("source-identity")
    identity.add_argument("--output", type=Path)

    live = commands.add_parser("live")
    live.add_argument("--permit-live-run", action="store_true")
    live.add_argument("--evidence-dir", type=Path, required=True)
    live.add_argument("--collector-port", type=int, default=0)
    live.add_argument("runner_args", nargs=argparse.REMAINDER)

    resume = commands.add_parser("resume-live")
    resume.add_argument("--permit-live-run", action="store_true")
    resume.add_argument("--evidence-dir", type=Path, required=True)
    resume.add_argument("--prior-evidence-dir", type=Path, required=True)
    resume.add_argument("--collector-port", type=int, default=0)
    resume.add_argument("runner_args", nargs=argparse.REMAINDER)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "effect-free-preflight":
            collector_port = args.collector_port or free_port()
            executor_port = args.executor_port or free_port()
            while executor_port == collector_port:
                executor_port = free_port()
            value = run_effect_free_preflight(ROOT, args.output_dir, collector_port, executor_port)
        elif args.command == "config-preflight":
            value = read_only_configuration_preflight(ROOT, args.collector_port, args.executor_port)
            if args.output:
                write_json(args.output, value)
        elif args.command == "source-identity":
            value = tree_identity(ROOT)
            if args.output:
                write_json(args.output, value)
        elif args.command in {"live", "resume-live"}:
            if not args.permit_live_run:
                raise OrchestrationError(
                    "live runner is locked; --permit-live-run is required and authorizes effects"
                )
            collector_port = args.collector_port or free_port()
            runner_args = args.runner_args[1:] if args.runner_args[:1] == ["--"] else args.runner_args
            return run_live_orchestrated(
                ROOT,
                args.evidence_dir,
                collector_port,
                runner_args,
                runner_command=args.command,
                prior_evidence_dir=getattr(args, "prior_evidence_dir", None),
            )
        else:
            raise AssertionError(args.command)
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except (OrchestrationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
