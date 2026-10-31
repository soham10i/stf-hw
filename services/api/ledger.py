"""
The guarded actions' ledger (docs/architecture/guarded-action-plan.md): what the copilot
proposed, whether it ran - at most once - and the signed audit chain of every attempt.

Three tables, the same in both stores (supabase/migrations/20261028120000_stf_actions.sql):

  action_proposals   one row per proposal; its status only moves forward (TRANSITIONS), and
                     every move is a conditional update, so of two decisions racing for one
                     proposal exactly one wins
  action_executions  written BEFORE the side effect: a re-run that finds its row reconciles
                     instead of acting a second time
  action_audit       append-only; each record carries the signature of the one before it
                     (prev_sig), so an edited or removed record breaks the chain

  SqliteLedger  a file, STF_ACTIONS_DB (default <STF_DATA_DIR>/actions.db): a local run, tests
  PgLedger      Postgres, schema `agent`, over a direct connection (SUPABASE_DB_URL, Supabase's
                session pooler): a deployment. PostgREST never sees the schema.

Each store also hands out the actuation graph's LangGraph checkpointer (saver()): on Postgres
the same pool and schema, on SQLite a second file beside the ledger.

A public deployment (Cloud Run, Render) without SUPABASE_DB_URL gets no ledger at all: an
approval kept on an instance's ephemeral disk would vanish with the instance, so actions stay
off there (ledger_from_env).
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

from .logging_config import get_logger
from .store import ROOT

logger = get_logger(__name__)

# a proposal's status, and where each may move next
TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"pending", "refused"}),
    "pending": frozenset({"approved", "rejected", "expired", "refused"}),
    "approved": frozenset({"executing", "refused", "expired"}),
    "executing": frozenset({"done", "unknown", "refused"}),  # refused: the last check said no
    "unknown": frozenset({"done"}),  # an operator's reconciliation
}
FINAL = frozenset({"done", "refused", "rejected", "expired"})
DECISION_FIELDS = frozenset({"decided_by", "decided_at", "note", "precheck"})
EXEC_STATES = frozenset({"started", "done", "unknown", "refused"})

PROPOSAL_COLS = (
    "id", "thread_id", "guest", "kind", "params", "payload_hash", "reason", "evidence",
    "precheck", "status", "created_at", "expires_at",
)
AUDIT_COLS = (
    "id", "at", "actor", "action", "params", "pre", "post", "status", "reason", "prev_sig", "sig",
)
JSON_COLS = frozenset({"params", "evidence", "precheck", "result"})
AUDIT_LOCK = 0x57F_A0D1  # the advisory lock that serializes the chain across instances
AUDIT_MIN_DAYS = 30  # the youngest record the chain may lose (the migration's trigger agrees)

SQLITE_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS action_proposals (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL UNIQUE, guest TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('order_submit', 'order_cancel')),
  params TEXT NOT NULL, payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
  reason TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '[]',
  precheck TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL CHECK (status IN ('proposed', 'pending', 'approved', 'executing', 'done',
    'refused', 'rejected', 'expired', 'unknown')),
  created_at REAL NOT NULL, expires_at REAL NOT NULL, decided_by TEXT, decided_at REAL,
  note TEXT, CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS action_proposals_guest ON action_proposals (guest);
CREATE INDEX IF NOT EXISTS action_proposals_created ON action_proposals (created_at);
CREATE TABLE IF NOT EXISTS action_executions (
  proposal_id TEXT PRIMARY KEY REFERENCES action_proposals (id) ON DELETE CASCADE,
  state TEXT NOT NULL CHECK (state IN ('started', 'done', 'unknown', 'refused')),
  order_id INTEGER, result TEXT, started_at REAL NOT NULL, finished_at REAL
);
CREATE TABLE IF NOT EXISTS action_audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, at REAL NOT NULL,
  actor TEXT NOT NULL, action TEXT NOT NULL, params TEXT NOT NULL, pre TEXT NOT NULL,
  post TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, prev_sig TEXT NOT NULL,
  sig TEXT NOT NULL CHECK (length(sig) = 64)
);
CREATE INDEX IF NOT EXISTS action_audit_action ON action_audit (action, seq);
CREATE TRIGGER IF NOT EXISTS action_audit_no_update BEFORE UPDATE ON action_audit
BEGIN SELECT RAISE(ABORT, 'action_audit is append-only'); END;
"""

Run = Callable[[str, tuple], tuple[int, list[dict]]]


class Ledger:
    """The ledger's queries, written once: `?` placeholders and a table prefix (`agent.` on
    Postgres). A store supplies `_run` (one statement) and `_atomic` (several, as one)."""

    prefix = ""

    # -- what a store implements
    def _run(self, sql: str, args: tuple = ()) -> tuple[int, list[dict]]:
        raise NotImplementedError

    def _atomic(self) -> contextlib.AbstractContextManager[Run]:
        raise NotImplementedError

    def _json(self, v: Any) -> Any:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

    def close(self) -> None:
        """Release the connection(s)."""

    # -- helpers
    def _t(self, name: str) -> str:
        return self.prefix + name

    def _row(self, row: dict | None) -> dict | None:
        if row is None:
            return None
        out = {}
        for k, v in row.items():
            if k in JSON_COLS and isinstance(v, str):
                v = json.loads(v)
            elif k in ("id", "proposal_id") and v is not None:
                v = str(v)  # Postgres hands back a UUID
            out[k] = v
        return out

    def _args(self, row: dict, cols: tuple[str, ...]) -> tuple:
        return tuple(self._json(row[c]) if c in JSON_COLS else row[c] for c in cols)

    # -- proposals
    def put_proposal(self, p: dict) -> bool:
        """Store a new proposal; False when one with its id is already there (a re-run)."""
        if p["status"] not in ("proposed", "pending", "refused"):
            raise ValueError(f"a proposal starts proposed, pending or refused, not {p['status']}")
        n, _ = self._run(
            f"INSERT INTO {self._t('action_proposals')} ({', '.join(PROPOSAL_COLS)}) "
            f"VALUES ({', '.join('?' * len(PROPOSAL_COLS))}) ON CONFLICT (id) DO NOTHING",
            self._args(p, PROPOSAL_COLS),
        )
        return n == 1

    def proposal(self, id: str) -> dict | None:
        _, rows = self._run(f"SELECT * FROM {self._t('action_proposals')} WHERE id = ?", (id,))
        return self._row(rows[0] if rows else None)

    def proposals(self, status: str | None = None, limit: int = 50) -> list[dict]:
        """The newest proposals first, optionally only those with one status."""
        where, args = ("WHERE status = ?", (status,)) if status else ("", ())
        _, rows = self._run(
            f"SELECT * FROM {self._t('action_proposals')} {where} "
            f"ORDER BY created_at DESC LIMIT {int(limit)}",
            args,
        )
        return [self._row(r) for r in rows]

    def transition(self, id: str, frm: str, to: str, **fields: Any) -> bool:
        """Move a proposal from `frm` to `to`, only if it is still at `frm`: True for the one
        caller whose move happened, False for everyone who came too late."""
        if to not in TRANSITIONS.get(frm, ()):
            raise ValueError(f"a proposal cannot move from {frm} to {to}")
        if extra := set(fields) - DECISION_FIELDS:
            raise ValueError(f"not a decision field: {sorted(extra)}")
        cols = ["status", *fields]
        vals = [to, *(self._json(v) if k in JSON_COLS else v for k, v in fields.items())]
        n, _ = self._run(
            f"UPDATE {self._t('action_proposals')} SET {', '.join(f'{c} = ?' for c in cols)} "
            "WHERE id = ? AND status = ?",
            (*vals, id, frm),
        )
        return n == 1

    # -- executions
    def start_execution(self, proposal_id: str, at: float, result: dict | None = None) -> bool:
        """Claim the one execution of a proposal, before acting: False means it was claimed
        already, so the caller must reconcile, never act. `result` holds what a reconciliation
        needs to know about the moment before (the last order id the runtime had issued)."""
        n, _ = self._run(
            f"INSERT INTO {self._t('action_executions')} (proposal_id, state, result, started_at) "
            "VALUES (?, 'started', ?, ?) ON CONFLICT (proposal_id) DO NOTHING",
            (proposal_id, None if result is None else self._json(result), at),
        )
        return n == 1

    def finish_execution(
        self, proposal_id: str, state: str, at: float,
        order_id: int | None = None, result: dict | None = None,
    ) -> bool:
        """Record how an execution ended: done, refused by the guard's last check (nothing
        moved), or unknown (an operator reconciles)."""
        if state not in ("done", "unknown", "refused"):
            raise ValueError(f"an execution ends done, unknown or refused, not {state}")
        n, _ = self._run(
            f"UPDATE {self._t('action_executions')} "
            "SET state = ?, order_id = ?, result = ?, finished_at = ? "
            "WHERE proposal_id = ? AND state IN ('started', 'unknown')",
            (state, order_id, None if result is None else self._json(result), at, proposal_id),
        )
        return n == 1

    def execution(self, proposal_id: str) -> dict | None:
        _, rows = self._run(
            f"SELECT * FROM {self._t('action_executions')} WHERE proposal_id = ?", (proposal_id,)
        )
        return self._row(rows[0] if rows else None)

    # -- retention
    def _drop(self, where: str, arg: Any) -> list[str]:
        with self._atomic() as run:
            _, rows = run(
                f"SELECT thread_id FROM {self._t('action_proposals')} WHERE {where}", (arg,)
            )
            run(f"DELETE FROM {self._t('action_proposals')} WHERE {where}", (arg,))
        return [r["thread_id"] for r in rows]

    def forget(self, guest: str) -> list[str]:
        """Delete a guest's proposals and executions; the threads whose checkpoints go too."""
        return self._drop("guest = ?", guest)

    def lapse(self, before: float) -> list[str]:
        """Delete proposals made before `before`; the threads whose checkpoints go too."""
        return self._drop("created_at < ?", before)

    # -- the audit chain
    def append_audit(self, row: dict, sign: Callable[[dict], str]) -> dict:
        """Append one record to the chain: its prev_sig is the last record's signature, read and
        written in one transaction, so two writers never fork the chain. A record whose id is
        there already is not written again (a re-run node's record): the stored one comes back."""
        with self._atomic() as run:
            _, same = run(
                f"SELECT {', '.join(AUDIT_COLS)} FROM {self._t('action_audit')} WHERE id = ?",
                (row["id"],),
            )
            if same:
                return self._row(same[0])
            _, last = run(
                f"SELECT sig FROM {self._t('action_audit')} ORDER BY seq DESC LIMIT 1", ()
            )
            rec = {**row, "prev_sig": last[0]["sig"] if last else ""}
            rec["sig"] = sign(rec)
            run(
                f"INSERT INTO {self._t('action_audit')} ({', '.join(AUDIT_COLS)}) "
                f"VALUES ({', '.join('?' * len(AUDIT_COLS))})",
                self._args(rec, AUDIT_COLS),
            )
        return rec

    def audit(self, limit: int | None = 50, action: str | None = None) -> list[dict]:
        """The latest records, oldest first (limit None: the whole chain)."""
        where, args = ("WHERE action = ?", (action,)) if action else ("", ())
        lim = "" if limit is None else f"LIMIT {int(limit)}"
        _, rows = self._run(
            f"SELECT {', '.join(AUDIT_COLS)} FROM {self._t('action_audit')} {where} "
            f"ORDER BY seq DESC {lim}",
            args,
        )
        return [self._row(r) for r in reversed(rows)]

    def prune_audit(self, before: float) -> int:
        """Delete records older than `before`, never one younger than AUDIT_MIN_DAYS (the
        Postgres trigger refuses those too)."""
        before = min(before, time.time() - AUDIT_MIN_DAYS * 86400)
        n, _ = self._run(f"DELETE FROM {self._t('action_audit')} WHERE at < ?", (before,))
        return n


class SqliteLedger(Ledger):
    """The ledger in a SQLite file, one connection behind a lock."""

    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SQLITE_SCHEMA)
        self._graph_db: sqlite3.Connection | None = None

    def _exec(self, sql: str, args: tuple) -> tuple[int, list[dict]]:
        cur = self._db.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        return cur.rowcount, rows

    def _run(self, sql: str, args: tuple = ()) -> tuple[int, list[dict]]:
        with self._lock:
            return self._exec(sql, args)

    @contextlib.contextmanager
    def _atomic(self) -> Iterator[Run]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._exec
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def saver(self):
        """LangGraph's SQLite checkpointer, in a file beside this one (its own connection and
        lock: two lock holders on one connection would interleave their transactions)."""
        from langgraph.checkpoint.sqlite import SqliteSaver

        root, _ = os.path.splitext(self.path)
        self._graph_db = sqlite3.connect(f"{root}-graph.db", check_same_thread=False)
        return SqliteSaver(self._graph_db)

    def close(self) -> None:
        with self._lock:
            self._db.close()
            if self._graph_db is not None:
                self._graph_db.close()


class PgLedger(Ledger):
    """The ledger in Postgres (schema `agent`, applied by the migration), through a small
    connection pool opened on first use."""

    prefix = "agent."

    def __init__(self, url: str, max_size: int = 4) -> None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        # the checkpointer shares the pool and names no schema, so every connection looks in
        # `agent` first; the ledger's own queries name it anyway
        self._pool = ConnectionPool(
            url, min_size=0, max_size=max_size, open=False, timeout=10,
            kwargs={"autocommit": True, "row_factory": dict_row},
            configure=lambda conn: conn.execute("SET search_path TO agent, public"),
        )
        self._opened = False
        self._lock = threading.Lock()

    def saver(self):
        """LangGraph's Postgres checkpointer on this pool, its tables created in `agent`."""
        from langgraph.checkpoint.postgres import PostgresSaver

        self._open()
        saver = PostgresSaver(self._pool)
        saver.setup()
        return saver

    def _json(self, v: Any) -> Any:
        from psycopg.types.json import Jsonb

        return Jsonb(v)

    def _open(self) -> None:
        if not self._opened:
            with self._lock:
                if not self._opened:
                    self._pool.open(wait=False)
                    self._opened = True

    def _conn(self):
        self._open()
        return self._pool.connection()

    @staticmethod
    def _exec(conn, sql: str, args: tuple) -> tuple[int, list[dict]]:
        cur = conn.execute(sql.replace("?", "%s"), args)
        rows = cur.fetchall() if cur.description else []
        return cur.rowcount, rows

    def _run(self, sql: str, args: tuple = ()) -> tuple[int, list[dict]]:
        with self._conn() as conn:
            return self._exec(conn, sql, args)

    @contextlib.contextmanager
    def _atomic(self) -> Iterator[Run]:
        with self._conn() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK,))
            yield lambda sql, args: self._exec(conn, sql, args)

    def close(self) -> None:
        if self._opened:
            self._pool.close()


def public_deployment(env: dict) -> bool:
    """Cloud Run or Render: an instance's disk lasts only as long as the instance."""
    return bool(env.get("K_SERVICE") or env.get("RENDER"))


def ledger_from_env(env: dict) -> tuple[Ledger | None, str]:
    """The configured ledger and a note for the status endpoint: Postgres when SUPABASE_DB_URL
    is set, none on a public deployment without it, else a SQLite file."""
    url = (env.get("SUPABASE_DB_URL") or "").strip()
    if url:
        return PgLedger(url), "Postgres (schema agent)"
    if public_deployment(env):
        return None, "no SUPABASE_DB_URL: a public deployment keeps no ledger, actions are off"
    path = env.get("STF_ACTIONS_DB") or os.path.join(env.get("STF_DATA_DIR") or ROOT, "actions.db")
    return SqliteLedger(path), "SQLite"
