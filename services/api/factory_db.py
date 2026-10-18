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
    name = "supabase"

    def __init__(self, url: str, key: str) -> None:
        self.url, self.key = url.rstrip("/"), key

    def _req(self, method: str, path: str, body: Any = None, prefer: str = "") -> Any:
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
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - the configured project URL
            raw = r.read()
            return (json.loads(raw) if raw else None), r.headers

    def insert(self, table: str, rows: list[dict]) -> int:
        for i in range(0, len(rows), BATCH):
            self._req("POST", table, rows[i : i + BATCH], prefer="return=minimal")
        return len(rows)

    def clear(self, table: str) -> None:
        q = "source=neq.twin" if "source" in TABLES[table][0] else f"{TABLES[table][1]}=not.is.null"
        self._req("DELETE", f"{table}?{q}", prefer="return=minimal")

    def count(self, table: str) -> int:
        _, h = self._req("GET", f"{table}?select={TABLES[table][1]}&limit=1", prefer="count=exact")
        return int((h.get("Content-Range") or "*/0").split("/")[-1])

    def recent(self, table: str, owner: str, limit: int = 50) -> list[dict]:
        q = urllib.parse.quote(owner, safe="")
        rows, _ = self._req("GET", f"{table}?owner=eq.{q}&order=t.desc&limit={int(limit)}")
        return rows or []


class SqliteFactory:
    """The same tables in the API's SQLite file (a local run without Supabase)."""

    name = "sqlite"

    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.db:
            for t, (cols, _) in TABLES.items():
                self.db.execute(f"create table if not exists {t} ({', '.join(cols)})")

    def insert(self, table: str, rows: list[dict]) -> int:
        cols = TABLES[table][0]
        with self.lock, self.db:
            self.db.executemany(
                f"insert into {table} ({', '.join(cols)}) values ({', '.join('?' * len(cols))})",
                [tuple(r.get(c) for c in cols) for r in rows],
            )
        return len(rows)

    def clear(self, table: str) -> None:
        keep = " where source != 'twin'" if "source" in TABLES[table][0] else ""
        with self.lock, self.db:
            self.db.execute(f"delete from {table}{keep}")

    def count(self, table: str) -> int:
        with self.lock:
            return self.db.execute(f"select count(*) from {table}").fetchone()[0]

    def recent(self, table: str, owner: str, limit: int = 50) -> list[dict]:
        cols = TABLES[table][0]
        with self.lock:
            cur = self.db.execute(
                f"select {', '.join(cols)} from {table} where owner = ? order by t desc limit ?",
                (owner, int(limit)),
            )
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def factory_from(db: Any) -> SupabaseFactory | SqliteFactory:
    """The factory tables beside the guests' database guests.py chose."""
    if getattr(db, "name", "") == "supabase":
        return SupabaseFactory(db.url, db.key)
    return SqliteFactory(db.path)
