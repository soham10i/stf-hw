"""
Daily usage counters shared by every instance of the service, for the caps that protect paid
keys (token_budget.py, chat.DailyCap).

The caps used to be counters in memory: Cloud Run starts a new instance (all counters at zero)
after every scale to zero, and runs several at once under load, so a daily cap was really a cap
per instance lifetime. Here each count is also added to a row in the guests' database - SQLite
locally, Supabase (table usage_counters, function stf_usage_add:
supabase/migrations/20261022120000_stf_usage_counters.sql) in production - and every instance
reads the day's total back.

Nothing here may slow a request: additions are sent from one background thread, and a read
returns the last total seen (refreshed in the background every REFRESH_S). The caller takes
max(its own count, the shared total), so a cap is never looser than the in-memory one was.
When the database is unreachable or lacks the table, everything degrades to the old behaviour.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from . import keepalive
from .logging_config import get_logger

logger = get_logger(__name__)

REFRESH_S = 15.0
TIMEOUT_S = 5


class Store(Protocol):
    """A day's named counters: the duck-type every usage backend implements."""

    def add(self, day: str, name: str, n: int) -> int:
        """Add n to a counter, returning its new total."""
        ...

    def get(self, day: str, name: str) -> int:
        """A counter's current total (0 when unset)."""
        ...


class SqliteUsage:
    """The Store over a local SQLite file (single-writer, lock-guarded)."""

    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS usage_counters (day TEXT NOT NULL, name TEXT NOT NULL,"
            " n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, name))"
        )

    def add(self, day: str, name: str, n: int) -> int:
        """Add n to a counter, returning its new total."""
        with self._lock:
            return self._db.execute(
                "INSERT INTO usage_counters (day, name, n) VALUES (?, ?, ?) ON CONFLICT (day, name)"
                " DO UPDATE SET n = n + excluded.n RETURNING n",
                (day, name, n),
            ).fetchone()[0]

    def get(self, day: str, name: str) -> int:
        """A counter's current total (0 when unset)."""
        with self._lock:
            r = self._db.execute(
                "SELECT n FROM usage_counters WHERE day = ? AND name = ?", (day, name)
            ).fetchone()
        return r[0] if r else 0


class SupabaseUsage:
    """PostgREST with the service key: an atomic increment through the stf_usage_add function."""

    def __init__(self, url: str, key: str) -> None:
        self.url, self.key = url.rstrip("/"), key

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        req = urllib.request.Request(
            f"{self.url}/rest/v1/{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.key}",
                "apikey": self.key,
                "Content-Type": "application/json",
            },
        )
        with keepalive.urlopen(req, timeout=TIMEOUT_S) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def add(self, day: str, name: str, n: int) -> int:
        """Add n to a counter atomically (RPC), returning its new total."""
        return int(self._req("POST", "rpc/stf_usage_add", {"p_day": day, "p_name": name, "p_n": n}))

    def get(self, day: str, name: str) -> int:
        """A counter's current total (0 when unset)."""
        q = urllib.parse.urlencode({"select": "n", "day": f"eq.{day}", "name": f"eq.{name}"})
        rows = self._req("GET", f"usage_counters?{q}") or []
        return int(rows[0]["n"]) if rows else 0


class Shared:
    """Non-blocking view of a Store: add() queues, total() answers from the last value seen."""

    def __init__(self, store: Store | None) -> None:
        self.store = store
        self._seen: dict[tuple[str, str], tuple[int, float]] = {}  # (day, name) -> (n, when)
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="usage")
        self._failed_at = 0.0

    def _ok(self) -> bool:
        # after a failure, leave the database alone for a minute (it is down or lacks the table)
        return self.store is not None and time.monotonic() - self._failed_at > 60.0

    def _keep(self, day: str, name: str, n: int) -> None:
        with self._lock:
            old = self._seen.get((day, name), (0, 0.0))[0]
            self._seen[(day, name)] = (max(old, n), time.monotonic())

    def _run(self, fn, day: str, name: str, *args) -> None:
        try:
            self._keep(day, name, fn(day, name, *args))
        # URLError and TimeoutError are OSErrors
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
            if time.monotonic() - self._failed_at > 600.0:
                logger.warning("Shared usage counter unavailable (caps are per instance): %s", e)
            self._failed_at = time.monotonic()

    def add(self, day: str, name: str, n: int) -> None:
        """Queue an increment on the writer thread (never blocks the caller)."""
        if n > 0 and self._ok():
            self._pool.submit(self._run, self.store.add, day, name, n)  # type: ignore[union-attr]

    def total(self, day: str, name: str) -> int:
        """The day's shared total as last seen (0 before the first read); refreshes when stale."""
        with self._lock:
            n, at = self._seen.get((day, name), (0, 0.0))
            stale = time.monotonic() - at > REFRESH_S
            if stale:
                self._seen[(day, name)] = (n, time.monotonic())  # one refresh in flight
        if stale and self._ok():
            self._pool.submit(self._run, self.store.get, day, name)  # type: ignore[union-attr]
        return n


def shared_from(db: Any) -> Shared:
    """The shared counters in the same database as the guests (guests.db_from_env's choice)."""
    try:
        if getattr(db, "name", "") == "supabase":
            return Shared(SupabaseUsage(db.url, db.key))
        if getattr(db, "name", "") == "sqlite":
            return Shared(SqliteUsage(db.path))
    except (sqlite3.Error, OSError) as e:
        logger.warning("No shared usage counters: %s", e)
    return Shared(None)
