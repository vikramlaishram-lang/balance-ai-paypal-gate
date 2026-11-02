from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Journal:
    """SQLite mission projection plus an append-only per-mission hash chain."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with closing(self.connect()) as connection:
            with connection:
                connection.executescript(
                    """
                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    request_key TEXT NOT NULL UNIQUE,
                    request_digest TEXT NOT NULL,
                    description TEXT NOT NULL,
                    payment_reference TEXT,
                    payee_id TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    admissibility TEXT,
                    decision TEXT,
                    act_digest TEXT,
                    approval_signature TEXT,
                    user_approved INTEGER NOT NULL DEFAULT 0,
                    approved_by TEXT,
                    approval_proposal_digest TEXT,
                    approval_limit TEXT,
                    approval_allowlist_json TEXT,
                    policy_hash TEXT,
                    approval_digest TEXT,
                    paypal_order_id TEXT UNIQUE,
                    approval_url TEXT,
                    create_request_id TEXT NOT NULL,
                    capture_request_id TEXT NOT NULL,
                    capture_attempted INTEGER NOT NULL DEFAULT 0,
                    capture_retry_count INTEGER NOT NULL DEFAULT 0,
                    capture_id TEXT,
                    provider_status TEXT,
                    outcome_basis TEXT,
                    next_action TEXT,
                    capture_started_at TEXT,
                    create_attempted INTEGER NOT NULL DEFAULT 0,
                    create_started_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trusted_invoices (
                    invoice_id TEXT PRIMARY KEY,
                    merchant_id TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    payment_reference TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    invoice_digest TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    active_mission_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (active_mission_id) REFERENCES missions(mission_id)
                );

                CREATE TABLE IF NOT EXISTS supersessions (
                    supersession_id TEXT PRIMARY KEY,
                    invoice_id TEXT NOT NULL,
                    original_mission_id TEXT NOT NULL,
                    replacement_request_key TEXT NOT NULL UNIQUE,
                    replacement_act_digest TEXT NOT NULL,
                    evidence_basis TEXT NOT NULL,
                    provider_order_id TEXT NOT NULL,
                    approval_digest TEXT NOT NULL,
                    approval_signature TEXT NOT NULL UNIQUE,
                    approved_by TEXT NOT NULL,
                    status TEXT NOT NULL,
                    replacement_mission_id TEXT,
                    created_at TEXT NOT NULL,
                    consumed_at TEXT,
                    FOREIGN KEY (invoice_id) REFERENCES trusted_invoices(invoice_id),
                    FOREIGN KEY (original_mission_id) REFERENCES missions(mission_id),
                    FOREIGN KEY (replacement_mission_id) REFERENCES missions(mission_id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    mission_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY (mission_id) REFERENCES missions(mission_id)
                );

                CREATE INDEX IF NOT EXISTS idx_events_mission_sequence
                    ON events(mission_id, sequence);

                CREATE TRIGGER IF NOT EXISTS events_no_update
                BEFORE UPDATE ON events BEGIN
                    SELECT RAISE(ABORT, 'events are append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS events_no_delete
                BEFORE DELETE ON events BEGIN
                    SELECT RAISE(ABORT, 'events are append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS trusted_invoices_core_no_update
                BEFORE UPDATE OF invoice_id, merchant_id, amount, currency,
                    payment_reference, operation, invoice_digest, created_at
                ON trusted_invoices BEGIN
                    SELECT RAISE(ABORT, 'trusted invoice authority fields are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trusted_invoices_no_delete
                BEFORE DELETE ON trusted_invoices BEGIN
                    SELECT RAISE(ABORT, 'trusted invoices cannot be deleted');
                END;
                    """
                )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(missions)").fetchall()
                }
                migrations = {
                    "payee_id": "TEXT NOT NULL DEFAULT 'legacy-unspecified'",
                    "approval_proposal_digest": "TEXT",
                    "approval_limit": "TEXT",
                    "approval_allowlist_json": "TEXT",
                    "policy_hash": "TEXT",
                    "approval_digest": "TEXT",
                    "next_action": "TEXT",
                    "capture_started_at": "TEXT",
                    "capture_retry_count": "INTEGER NOT NULL DEFAULT 0",
                    "payment_reference": "TEXT",
                    "admissibility": "TEXT",
                    "decision": "TEXT",
                    "act_digest": "TEXT",
                    "approval_signature": "TEXT",
                    "create_attempted": "INTEGER NOT NULL DEFAULT 0",
                    "create_started_at": "TEXT",
                    "trusted_invoice_id": "TEXT",
                    "invoice_digest": "TEXT",
                    "proposal_act_digest": "TEXT",
                    "admission_reason": "TEXT",
                    "supersession_id": "TEXT",
                }
                for name, definition in migrations.items():
                    if name not in columns:
                        connection.execute(
                            f"ALTER TABLE missions ADD COLUMN {name} {definition}"
                        )
                connection.execute(
                    """CREATE UNIQUE INDEX IF NOT EXISTS idx_missions_approval_signature
                       ON missions(approval_signature) WHERE approval_signature IS NOT NULL"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_missions_trusted_invoice ON missions(trusted_invoice_id)"
                )

    @staticmethod
    def append_event(
        connection: sqlite3.Connection,
        *,
        event_id: str,
        mission_id: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: str,
    ) -> str:
        row = connection.execute(
            "SELECT event_hash FROM events WHERE mission_id = ? ORDER BY sequence DESC LIMIT 1",
            (mission_id,),
        ).fetchone()
        previous_hash = row["event_hash"] if row else "0" * 64
        payload_json = canonical_json(payload)
        envelope = canonical_json(
            {
                "event_id": event_id,
                "event_type": event_type,
                "mission_id": mission_id,
                "occurred_at": occurred_at,
                "payload": payload,
                "previous_hash": previous_hash,
            }
        )
        event_hash = sha256_text(envelope)
        connection.execute(
            """
            INSERT INTO events (
                event_id, mission_id, event_type, payload_json,
                previous_hash, event_hash, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, mission_id, event_type, payload_json, previous_hash, event_hash, occurred_at),
        )
        return event_hash

    def mission(self, mission_id: str) -> dict[str, Any] | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM missions WHERE mission_id = ?", (mission_id,)
            ).fetchone()
        return dict(row) if row else None

    def invoice(self, invoice_id: str) -> dict[str, Any] | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM trusted_invoices WHERE invoice_id = ?", (invoice_id,)
            ).fetchone()
        return dict(row) if row else None

    def events(self, mission_id: str) -> list[dict[str, Any]]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE mission_id = ? ORDER BY sequence", (mission_id,)
            ).fetchall()
        result = []
        for row in rows:
            event = dict(row)
            event["payload"] = json.loads(event.pop("payload_json"))
            result.append(event)
        return result

    def verify_chain(self, mission_id: str) -> bool:
        previous_hash = "0" * 64
        for event in self.events(mission_id):
            if event["previous_hash"] != previous_hash:
                return False
            envelope = canonical_json(
                {
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "mission_id": event["mission_id"],
                    "occurred_at": event["occurred_at"],
                    "payload": event["payload"],
                    "previous_hash": event["previous_hash"],
                }
            )
            if sha256_text(envelope) != event["event_hash"]:
                return False
            previous_hash = event["event_hash"]
        return True

