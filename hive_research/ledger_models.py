"""Tamper-evident audit ledger tables (stdlib sqlite3).

One append-only, hash-chained event stream per run spans *every* actor: agent
roles, LLM calls, tool invocations, hand-offs in and out, and human decisions.
The chain is what makes the record auditable: each row commits to its
predecessor, so an edit, a deletion, or an insertion after the fact all break
verification.

Kept apart from :mod:`hive_research.pool` because this is a different shape of
data — a run id, a monotonic sequence and hash columns, none of which are
domain rows. It uses the same sqlite3 conventions as ``pool`` (WAL, one
thread-local connection) so both databases behave identically under the
threaded HTTP server.

Ported from the mapper's ``app/ledger_models.py``, which expressed these tables
as SQLAlchemy models. Only the parts with a job in a research ingest are kept:
sessions, approvals and leadership alert state belonged to that app's sitting /
dashboard model and are not reproduced here. A human decision is recorded as an
event (see :func:`hive_research.assurance_ledger.record_human_decision`), which
is what made an approval unforgeable in the first place.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_runs (
    id TEXT PRIMARY KEY,
    label TEXT,
    kind TEXT NOT NULL DEFAULT 'ingest',
    status TEXT NOT NULL DEFAULT 'open',
    mandate_json TEXT,
    mandate_hash TEXT,
    genesis_hash TEXT NOT NULL,
    head_hash TEXT,
    head_seq INTEGER NOT NULL DEFAULT -1,
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS ledger_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES ledger_runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    intent TEXT,
    verdict TEXT,
    severity TEXT,
    data_json TEXT NOT NULL,
    input_refs TEXT,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL,
    proof_json TEXT,
    trace TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_event_seq
    ON ledger_events(run_id, seq);
CREATE INDEX IF NOT EXISTS ix_ledger_events_run ON ledger_events(run_id, seq);
CREATE INDEX IF NOT EXISTS ix_ledger_events_kind ON ledger_events(kind);
CREATE INDEX IF NOT EXISTS ix_ledger_events_actor ON ledger_events(actor);
CREATE INDEX IF NOT EXISTS ix_ledger_events_verdict ON ledger_events(verdict);
CREATE INDEX IF NOT EXISTS ix_ledger_events_hash ON ledger_events(hash);

CREATE TABLE IF NOT EXISTS ledger_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES ledger_runs(id) ON DELETE CASCADE,
    claim_hash TEXT NOT NULL,
    seq INTEGER,
    actor TEXT,
    text TEXT NOT NULL,
    citations_json TEXT,
    n_sources INTEGER NOT NULL DEFAULT 0,
    confidence TEXT,
    verdict TEXT,
    verifier TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_ledger_claims_hash ON ledger_claims(claim_hash);
CREATE INDEX IF NOT EXISTS ix_ledger_claims_run ON ledger_claims(run_id);

-- A row here usually exists *because* a chain write failed, so it cannot be
-- part of the chain. A hole in the evidence that exists only as a line on
-- stderr is a hole nobody reads.
CREATE TABLE IF NOT EXISTS ledger_audit_drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT,
    recorder TEXT,
    actor TEXT,
    error TEXT,
    detail_json TEXT
);

CREATE INDEX IF NOT EXISTS ix_ledger_drops_run ON ledger_audit_drops(run_id);
CREATE INDEX IF NOT EXISTS ix_ledger_drops_ts ON ledger_audit_drops(ts);
"""


class LedgerStore:
    """Thread-safe sqlite3 access for the ledger.

    One connection per thread, created lazily, exactly as :mod:`pool` does it.
    WAL matters here more than it does there: the pipeline writes events from
    worker threads while the server reads them from a request thread, and a
    reader must never see a half-committed chain head.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._init_lock:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.conn = c
        return c

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    # -- rows ---------------------------------------------------------------

    def event_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """Project a stored row onto the shape :func:`hive_research.ledger.verify_events`
        expects. Kept here so the storage shape and the audit shape cannot drift."""
        return {
            "run_id": row["run_id"],
            "seq": row["seq"],
            "ts": row["ts"],
            "actor_type": row["actor_type"],
            "actor": row["actor"],
            "kind": row["kind"],
            "intent": row["intent"],
            "verdict": row["verdict"],
            "severity": row["severity"],
            "data_json": row["data_json"],
            "input_refs": row["input_refs"],
            "prev_hash": row["prev_hash"],
            "hash": row["hash"],
            "proof_json": row["proof_json"],
            "trace": row["trace"],
        }

    def record_drop(self, run_id: str | None, recorder: str, actor: str,
                    error: str, detail: dict[str, Any] | None = None) -> None:
        """Record an audit record the ledger failed to write.

        Best-effort by construction: if this write fails too there is nowhere
        further to escalate, so it is swallowed rather than allowed to raise
        from inside an error handler.
        """
        try:
            import json as _json
            from datetime import datetime, timezone

            self.conn.execute(
                "INSERT INTO ledger_audit_drops "
                "(ts, run_id, recorder, actor, error, detail_json) VALUES (?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), run_id, recorder, actor,
                 error[:2000], _json.dumps(detail or {}, default=str)),
            )
            self.conn.commit()
        except Exception:
            pass


_store: LedgerStore | None = None
_store_lock = threading.Lock()


def get_store(db_path: str | Path | None = None) -> LedgerStore:
    """Process-wide ledger store.

    ``db_path`` is only honoured on first call; afterwards the live store is
    returned so a test that swaps the path cannot leave two open databases
    writing the same run.
    """
    global _store
    with _store_lock:
        if _store is None:
            if db_path is None:
                raise RuntimeError(
                    "ledger store not initialised: call init_store(path) "
                    "or pass db_path on the first get_store()")
            _store = LedgerStore(db_path)
        return _store


def init_store(db_path: str | Path) -> LedgerStore:
    """Set the process-wide ledger store explicitly (config load, tests)."""
    global _store
    with _store_lock:
        _store = LedgerStore(db_path)
        return _store


def reset_store() -> None:
    """Drop the process-wide store. Tests use this between temp dirs."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None