"""Independent replay for the v0.5.1/v0.5.2 JSONL observation collector."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .observed_executor import canonical, digest


ZERO_COUNTS = {"ingress": 0, "create": 0, "capture": 0, "get": 0, "refused": 0}


def replay_collector_log(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    try:
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"line {number}: invalid JSON ({exc.msg})")
                continue
            rows.append(row)
    except OSError as exc:
        return {
            "chain_valid": False,
            "complete": False,
            "errors": [f"log unreadable: {type(exc).__name__}"],
            "counts": dict(ZERO_COUNTS),
            "records": 0,
            "window_id": None,
        }

    expected_previous = "0" * 64
    counts = dict(ZERO_COUNTS)
    begin_rows = 0
    end_rows = 0
    window_id = None
    collector_pids: set[int] = set()
    executor_pids: set[int] = set()

    for index, row in enumerate(rows, 1):
        core = {key: value for key, value in row.items() if key != "entry_sha256"}
        if row.get("seq") != index:
            errors.append(f"record {index}: sequence mismatch")
        if row.get("previous_sha256") != expected_previous:
            errors.append(f"record {index}: previous hash mismatch")
        actual_hash = digest(core)
        if row.get("entry_sha256") != actual_hash:
            errors.append(f"record {index}: entry hash mismatch")
        expected_previous = str(row.get("entry_sha256", ""))
        current_window = row.get("window_id")
        if window_id is None:
            window_id = current_window
        elif current_window != window_id:
            errors.append(f"record {index}: window identity changed")
        if isinstance(row.get("collector_pid"), int):
            collector_pids.add(row["collector_pid"])

        kind = row.get("kind")
        record = row.get("record", {})
        if kind == "WINDOW_BEGIN":
            begin_rows += 1
            if record.get("counts") != ZERO_COUNTS:
                errors.append(f"record {index}: non-zero begin counters")
        elif kind == "EXECUTOR_EVENT":
            event_kind = record.get("kind")
            operation = record.get("operation")
            if isinstance(record.get("pid"), int):
                executor_pids.add(record["pid"])
            if record.get("window_id") != window_id:
                errors.append(f"record {index}: embedded event window mismatch")
            if event_kind == "EXECUTOR_REQUEST_RECEIVED":
                counts["ingress"] += 1
            elif event_kind == "PROVIDER_DISPATCH_BEGIN":
                field = {
                    "CREATE_ORDER": "create",
                    "CAPTURE_ORDER": "capture",
                    "GET_ORDER": "get",
                }.get(operation)
                if field is None:
                    errors.append(f"record {index}: unexpected dispatch operation")
                else:
                    counts[field] += 1
            elif event_kind == "EXECUTOR_REQUEST_REFUSED":
                counts["refused"] += 1
        elif kind == "WINDOW_END":
            end_rows += 1
            if record.get("counts") != counts:
                errors.append(f"record {index}: terminal counters do not replay")
        else:
            errors.append(f"record {index}: unexpected record kind {kind!r}")

    if begin_rows != 1:
        errors.append(f"expected one WINDOW_BEGIN, observed {begin_rows}")
    if end_rows > 1:
        errors.append(f"expected at most one WINDOW_END, observed {end_rows}")
    complete = begin_rows == 1 and end_rows == 1
    return {
        "chain_valid": not errors,
        "complete": complete,
        "errors": errors,
        "counts": counts,
        "records": len(rows),
        "window_id": window_id,
        "chain_head": expected_previous if rows else "0" * 64,
        "collector_pids": sorted(collector_pids),
        "executor_pids": sorted(executor_pids),
    }
