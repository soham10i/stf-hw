"""
The factory's data in the database (supabase/migrations/20261018030000_stf_factory_data.sql):
the simulated month's orders, events, sensor readings and signals, its days, the energy month,
the bake process, and the camera's inspections - the same tables on Supabase (PostgREST, the
service key) or, for a local run, in the API's SQLite file. guests.py chooses which.

  FactoryDb.insert(table, rows)            add rows (in batches)
  FactoryDb.clear(table)                   remove the seeded rows (a guest's twin rows stay)
  FactoryDb.count(table)                   how many rows
  FactoryDb.recent(table, owner, limit)    a guest's newest rows (inspections, orders)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .logging_config import get_logger

logger = get_logger(__name__)

TABLES = {
    # table: (columns, the column that is never null, used to empty it over PostgREST)
    "orders": (
        (
            "source",
            "owner",
            "t",
            "day",
            "shift",
            "dur_s",
            "flavour",
            "qty",
            "baked",
            "good",
            "scrap",
            "qc_fault",
            "returned",
            "hall_c",
        ),
        "t",
    ),
    "events": (("t", "kind", "what", "comp", "code", "lost_s", "down_h"), "t"),
    "sensor_readings": (
        ("t", "component", "observed", "ewma_r", "health_index", "rul_shifts"),
        "t",
    ),
    "signals": (
        (
            "t",
            "temp_c",
            "a4_chocolate_mv",
            "a4_strawberry_mv",
            "a4_vanilla_mv",
            "i_hbw_a",
            "air_duty",
        ),
        "t",
    ),
    "daily_kpis": (
        (
            "day",
            "date",
            "orders",
            "baked",
            "good",
            "scrap",
            "run_h",
            "faults",
            "maint",
            "failures",
            "a",
            "p",
            "q",
            "oee",
        ),
        "day",
    ),
    "energy_15min": (
        (
            "t_h",
            "load_w",
            "pv_w",
            "grid_w",
            "battery_w",
            "soc",
            "price_eur_kwh",
            "co2_g_kwh",
            "dr_event",
            "irradiance_w_m2",
        ),
        "t_h",
    ),
    "bakes": (
        (
            "policy",
            "n",
            "lot",
            "fridge",
            "thick_mm",
            "t0_c",
            "x0",
            "bake_s",
            "browning",
            "water_pct",
            "core_peak_c",
            "verdict",
            "target",
        ),
        "policy",
    ),
    "inspections": (
        (
            "source",
            "owner",
            "t",
            "n",
            "flavour",
            "truth",
            "condition",
            "p",
            "verdict",
            "ae",
            "unusual",
            "capture_id",
        ),
        "n",
    ),
}
BATCH = 1000
TIMEOUT_S = 30


class SupabaseFactory:
    """PostgreSQL storage adapter communicating with Supabase via PostgREST.

    Attributes:
        name: Backend identifier string ('supabase').
        url: Base URL of the Supabase project.
        key: Supabase service role API key.
    """

    name = "supabase"

    def __init__(self, url: str, key: str) -> None:
        """Initialize Supabase factory adapter.

        Args:
            url: Base URL of the Supabase instance.
            key: Service role API key for authenticated PostgREST calls.
        """
        self.url, self.key = url.rstrip("/"), key

    def _req(self, method: str, path: str, body: Any = None, prefer: str = "") -> Any:
        """Execute an HTTP request against the Supabase PostgREST endpoint.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE).
            path: Relative REST endpoint path.
            body: Optional request payload.
            prefer: Value for the 'Prefer' header (e.g. 'return=minimal').

        Returns:
            Any: Decoded JSON response body and response headers.

        Raises:
            urllib.error.HTTPError: If the remote API returns a non-2xx status code.
            urllib.error.URLError: If network connection to Supabase fails.
            TimeoutError: If the request exceeds TIMEOUT_S.
        """
        h = {
            "Authorization": f"Bearer {self.key}",
            "apikey": self.key,
            "Content-Type": "application/json",
        }
        if prefer:
            h["Prefer"] = prefer
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.url + "/rest/v1/" + path, method=method, data=data, headers=h
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - the configured project URL
                raw = r.read()
                return (json.loads(raw) if raw else None), r.headers
        except urllib.error.HTTPError as e:
            logger.error("Supabase request failed [%s %s]: HTTP %d", method, path, e.code)
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            logger.error("Supabase connection error [%s %s]: %s", method, path, e)
            raise

    def insert(self, table: str, rows: list[dict]) -> int:
        """Insert records in batches into the specified Supabase table.

        Args:
            table: Target table name.
            rows: List of dictionary records to insert.

        Returns:
            int: Total number of rows inserted.
        """
        for i in range(0, len(rows), BATCH):
            self._req("POST", table, rows[i : i + BATCH], prefer="return=minimal")
        logger.debug("Inserted %d rows into Supabase table '%s'", len(rows), table)
        return len(rows)

    def clear(self, table: str) -> None:
        """Clear seeded factory data while preserving visitor records.

        Args:
            table: Target table name to truncate.
        """
        q = "source=neq.twin" if "source" in TABLES[table][0] else f"{TABLES[table][1]}=not.is.null"
        self._req("DELETE", f"{table}?{q}", prefer="return=minimal")
        logger.debug("Cleared table '%s' on Supabase", table)

    def count(self, table: str) -> int:
        """Query the exact total row count of the specified table.

        Args:
            table: Table name to query.

        Returns:
            int: Total number of rows.
        """
        _, h = self._req("GET", f"{table}?select={TABLES[table][1]}&limit=1", prefer="count=exact")
        return int((h.get("Content-Range") or "*/0").split("/")[-1])

    def recent(self, table: str, owner: str, limit: int = 50) -> list[dict]:
        """Fetch the most recent rows for a specific owner, sorted by timestamp descending.

        Args:
            table: Target table name.
            owner: Guest ID or identifier of the record owner.
            limit: Maximum number of rows to retrieve.

        Returns:
            list[dict]: Retrieved records.
        """
        q = urllib.parse.quote(owner, safe="")
        rows, _ = self._req("GET", f"{table}?owner=eq.{q}&order=t.desc&limit={int(limit)}")
        return rows or []


class SqliteFactory:
    """Local SQLite storage adapter implementing the same schema as Supabase.

    Used when running locally or when Supabase credentials are not supplied.

    Attributes:
        name: Backend identifier string ('sqlite').
        db: SQLite connection object.
        lock: Threading lock ensuring thread-safe access.
    """

    name = "sqlite"

    def __init__(self, path: str) -> None:
        """Initialize SQLite database, creating tables and indexes if missing.

        Args:
            path: Filesystem path to the SQLite database file.
        """
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.db:
            for t, (cols, _) in TABLES.items():
                self.db.execute(f"create table if not exists {t} ({', '.join(cols)})")
        logger.debug("Initialized SqliteFactory at '%s'", path)

    def insert(self, table: str, rows: list[dict]) -> int:
        """Insert records in bulk into the specified SQLite table.

        Args:
            table: Target table name.
            rows: List of dictionary records to insert.

        Returns:
            int: Number of rows inserted.
        """
        cols = TABLES[table][0]
        try:
            with self.lock, self.db:
                self.db.executemany(
                    f"insert into {table} ({', '.join(cols)}) values ("
                    f"{', '.join('?' * len(cols))})",
                    [tuple(r.get(c) for c in cols) for r in rows],
                )
        except sqlite3.Error as e:
            logger.error("Failed to insert %d rows into SQLite table '%s': %s", len(rows), table, e)
            raise
        return len(rows)

    def clear(self, table: str) -> None:
        """Clear seeded factory data while preserving visitor records.

        Args:
            table: Target table name.
        """
        keep = " where source != 'twin'" if "source" in TABLES[table][0] else ""
        try:
            with self.lock, self.db:
                self.db.execute(f"delete from {table}{keep}")
        except sqlite3.Error as e:
            logger.error("Failed to clear SQLite table '%s': %s", table, e)
            raise

    def count(self, table: str) -> int:
        """Query total row count in an SQLite table.

        Args:
            table: Table name to query.

        Returns:
            int: Total count of rows in the table.
        """
        try:
            with self.lock:
                return self.db.execute(f"select count(*) from {table}").fetchone()[0]
        except sqlite3.Error as e:
            logger.error("Failed to count rows in SQLite table '%s': %s", table, e)
            raise

    def recent(self, table: str, owner: str, limit: int = 50) -> list[dict]:
        """Fetch the most recent rows for a specific owner, sorted by timestamp descending.

        Args:
            table: Target table name.
            owner: Guest ID or identifier of the record owner.
            limit: Maximum number of rows to retrieve.

        Returns:
            list[dict]: List of matching records converted to dictionaries.
        """
        cols = TABLES[table][0]
        try:
            with self.lock:
                cur = self.db.execute(
                    f"select {', '.join(cols)} from {table} "
                    "where owner = ? order by t desc limit ?",
                    (owner, int(limit)),
                )
                return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        except sqlite3.Error as e:
            logger.error("Failed to fetch recent records from SQLite table '%s': %s", table, e)
            raise


def factory_from(db: Any) -> SupabaseFactory | SqliteFactory:
    """Factory function instantiating the appropriate factory storage adapter.

    Inspects the underlying guests database adapter and matches its backend (Supabase or SQLite).

    Args:
        db: Initialized guests database instance (SupabaseDb or SqliteDb).

    Returns:
        SupabaseFactory | SqliteFactory: Matching factory database adapter.
    """
    if getattr(db, "name", "") == "supabase":
        return SupabaseFactory(db.url, db.key)
    return SqliteFactory(db.path)
