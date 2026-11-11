"""
The copilot's answer quality, one row per answer (agent/quality.py makes the row).

A row holds scores, never words: the request id, the time, the route and model, how many claims
the answer made and how many the evidence backs (groundedness), the share carrying a citation,
the numbers nothing backs, how corrective retrieval judged the passages, what the hallucination
policy did (pass, strip, hedge, decline), the calibrated confidence, the latency, the tokens and
the estimated cost. No question, no answer, no guest id: a row cannot say who asked or what, so
it needs no consent and is kept even when usage tracking is off.

Two stores, picked like the visits' (visits.py): the copilot_quality table on Supabase when
SUPABASE_URL and the service key answer, else the same SQLite file the guests use. Writes go
through one background thread, so an answer never waits on the database.

  STF_QUALITY=1|0        keep the rows at all (default 1)
  STF_QUALITY_DAYS=90    how long a row is kept (pruned at most hourly)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from services.api.core import keepalive
from services.api.core.logging_config import get_logger
from services.api.storage.store import ROOT

logger = get_logger(__name__)

TABLE = "copilot_quality"
# every column but the id, in the order the SQLite table declares them
COLUMNS = (
    "request_id", "t", "mode", "model", "engine", "cached", "rules", "claims", "supported",
    "unsupported", "unsure", "groundedness", "min_support", "citation_coverage", "cited_by_model",
    "citation_precision", "numbers_unverified", "retrieval_verdict", "action", "declined",
    "regenerated", "confidence", "judge_calls", "latency_ms", "tokens", "cost_usd",
)
NUMERIC = (
    "groundedness", "citation_coverage", "cited_by_model", "citation_precision", "confidence",
    "latency_ms", "tokens", "cost_usd",
)
FAILURES = (sqlite3.Error, urllib.error.URLError, TimeoutError, ValueError, OSError)


# --- the stores
class SqliteQuality:
    name = "sqlite"

    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
              request_id TEXT PRIMARY KEY, t REAL NOT NULL, mode TEXT, model TEXT, engine TEXT,
              cached INTEGER, rules INTEGER, claims INTEGER, supported INTEGER,
              unsupported INTEGER, unsure INTEGER, groundedness REAL, min_support REAL,
              citation_coverage REAL, cited_by_model REAL, citation_precision REAL,
              numbers_unverified INTEGER, retrieval_verdict TEXT, action TEXT, declined INTEGER,
              regenerated INTEGER, confidence REAL, judge_calls INTEGER, latency_ms INTEGER,
              tokens INTEGER, cost_usd REAL);
            CREATE INDEX IF NOT EXISTS {TABLE}_t ON {TABLE} (t DESC);
            """
        )

    def add(self, row: dict) -> None:
        values = [_sql(row.get(c)) for c in COLUMNS]
        with self._lock:
            # a retried request keeps its id: the newer answer replaces the older row
            self._db.execute(
                f"INSERT OR REPLACE INTO {TABLE} ({', '.join(COLUMNS)})"
                f" VALUES ({', '.join('?' * len(COLUMNS))})",
                values,
            )

    def get(self, request_id: str) -> dict | None:
        with self._lock:
            cur = self._db.execute(
                f"SELECT {', '.join(COLUMNS)} FROM {TABLE} WHERE request_id = ?", (request_id,)
            )
            row = cur.fetchone()
        return _row(dict(zip(COLUMNS, row, strict=True))) if row else None

    def since(self, t0: float, limit: int = 5000) -> list[dict]:
        with self._lock:
            cur = self._db.execute(
                f"SELECT {', '.join(COLUMNS)} FROM {TABLE} WHERE t >= ? ORDER BY t LIMIT ?",
                (t0, limit),
            )
            rows = cur.fetchall()
        return [_row(dict(zip(COLUMNS, r, strict=True))) for r in rows]

    def lapse(self, before: float) -> None:
        with self._lock:
            self._db.execute(f"DELETE FROM {TABLE} WHERE t < ?", (before,))


class SupabaseQuality:
    """The same table in Postgres (supabase/migrations), over PostgREST with the service key."""

    name = "supabase"

    def __init__(self, url: str, key: str) -> None:
        self.url, self.key = url.rstrip("/"), key

    def _req(self, method: str, path: str, body: Any = None, prefer: str = "return=minimal"):
        req = urllib.request.Request(
            self.url + "/rest/v1/" + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.key}",
                "apikey": self.key,
                "Content-Type": "application/json",
                "Prefer": prefer,
            },
        )
        with keepalive.urlopen(req, timeout=10) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def ready(self) -> str | None:
        try:
            self._req("GET", f"{TABLE}?select=request_id&limit=1")
            return None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return "Supabase rejected the service key (SUPABASE_SERVICE_KEY)"
            if e.code == 404:
                return f"the {TABLE} table is missing (supabase/migrations)"
            return f"Supabase answered {e.code}"
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            return f"Supabase is unreachable ({type(e).__name__})"

    def add(self, row: dict) -> None:
        body = {c: row.get(c) for c in COLUMNS}
        body["t"] = _iso(row["t"])
        self._req("POST", f"{TABLE}?on_conflict=request_id", body,
                  prefer="return=minimal,resolution=merge-duplicates")

    def get(self, request_id: str) -> dict | None:
        rid = urllib.parse.quote(request_id, safe="")
        rows = self._req("GET", f"{TABLE}?select=*&request_id=eq.{rid}&limit=1") or []
        return _from_pg(rows[0]) if rows else None

    def since(self, t0: float, limit: int = 5000) -> list[dict]:
        when = urllib.parse.quote(_iso(t0), safe="")
        rows = self._req(
            "GET", f"{TABLE}?select=*&t=gte.{when}&order=t.asc&limit={int(limit)}"
        ) or []
        return [_from_pg(r) for r in rows]

    def lapse(self, before: float) -> None:
        self._req("DELETE", f"{TABLE}?t=lt.{urllib.parse.quote(_iso(before), safe='')}")


def _sql(v: Any) -> Any:
    return int(v) if isinstance(v, bool) else v


def _row(r: dict) -> dict:
    for k in ("cached", "rules", "declined", "regenerated"):
        if r.get(k) is not None:
            r[k] = bool(r[k])
    return r


def _from_pg(r: dict) -> dict:
    out = {c: r.get(c) for c in COLUMNS}
    t = out.get("t")
    if isinstance(t, str):
        out["t"] = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
    return out


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=UTC).isoformat()


def store_from_env(env: dict) -> tuple[Any, str]:
    """The quality store, and why it is the one in use (the same pick as visits.py)."""
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_SECRET_KEY")
    want = (env.get("STF_DB") or "auto").lower()
    path = env.get("STF_DB_PATH") or os.path.join(env.get("STF_DATA_DIR") or ROOT, "stf.db")
    if want in ("auto", "supabase") and url and key:
        db = SupabaseQuality(url, key)
        why = db.ready()
        if why is None:
            return db, "Supabase Postgres"
        logger.warning("Copilot quality stays on SQLite: %s", why)
        return SqliteQuality(path), f"SQLite: {why}"
    return SqliteQuality(path), "SQLite"


# --- the aggregates
def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def _pct(xs: list, q: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return float(xs[min(len(xs) - 1, int(q * len(xs)))])


def totals(rows: list[dict]) -> dict:
    """What a set of answers adds up to. The rates count answers, the means average them; an
    answer with nothing factual to check has no groundedness and is left out of that mean."""
    n = len(rows)
    actions: dict[str, int] = {}
    for r in rows:
        actions[r.get("action") or "pass"] = actions.get(r.get("action") or "pass", 0) + 1
    checked = [r for r in rows if (r.get("claims") or 0) > 0]
    return {
        "answers": n,
        "groundedness": _mean([r.get("groundedness") for r in checked]),
        "citation_coverage": _mean([r.get("citation_coverage") for r in checked]),
        "cited_by_model": _mean([r.get("cited_by_model") for r in checked]),
        "confidence": _mean([r.get("confidence") for r in rows]),
        # an answer that, as shown, still states something nothing backs
        "hallucination_rate": round(sum(
            1 for r in rows if (r.get("unsupported") or 0) > 0 or (r.get("numbers_unverified") or 0)
        ) / n, 4) if n else None,
        "decline_rate": round(sum(1 for r in rows if r.get("declined")) / n, 4) if n else None,
        "regenerated_rate": round(sum(1 for r in rows if r.get("regenerated")) / n, 4)
        if n else None,
        "actions": actions,
        "latency_ms_p50": _pct([r.get("latency_ms") for r in rows], 0.5),
        "latency_ms_p95": _pct([r.get("latency_ms") for r in rows], 0.95),
        "tokens": sum(r.get("tokens") or 0 for r in rows),
        "cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in rows), 6),
        "judge_calls": sum(r.get("judge_calls") or 0 for r in rows),
    }


def series(rows: list[dict], t0: float, bucket_s: float) -> list[dict]:
    """The rows in time buckets from t0, each bucket with its totals (empty ones left out)."""
    buckets: dict[int, list[dict]] = {}
    for r in rows:
        buckets.setdefault(int((r["t"] - t0) // bucket_s), []).append(r)
    return [{"t": round(t0 + i * bucket_s, 3), **totals(b)} for i, b in sorted(buckets.items())]


# --- the tracker
class Quality:
    """Keeps one row per answer, off the request's path."""

    def __init__(self, env: dict, store: Any = None, note: str = "") -> None:
        self.on = env.get("STF_QUALITY", "1") != "0"
        self.keep_s = float(env.get("STF_QUALITY_DAYS", "90")) * 86400
        self._store, self._env, self.note = store, env, note or (store.name if store else "")
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quality")
        self._pruned = 0.0
        self._lock = threading.Lock()

    @property
    def store(self) -> Any:
        # chosen on first use: picking it may probe Supabase, which import time must not wait on
        with self._lock:
            if self._store is None:
                self._store, self.note = store_from_env(self._env)
            return self._store

    def record(self, row: dict | None, wait: bool = False) -> None:
        """Keep a row (agent/quality.py); never raises, never blocks unless wait (tests)."""
        if not self.on or not row or not row.get("request_id"):
            return
        fut = self._pool.submit(self._write, row)
        if wait:
            fut.result()

    def _write(self, row: dict) -> None:
        try:
            self.store.add(row)
            now = time.time()
            if now - self._pruned > 3600:  # the retention promise, checked at most hourly
                self._pruned = now
                self.store.lapse(now - self.keep_s)
        except FAILURES as e:
            logger.warning("Could not store the answer's quality: %s", e)

    def get(self, request_id: str) -> dict | None:
        return self.store.get(request_id)

    def overview(self, hours: float = 24.0, bucket_s: float = 3600.0,
                 now: float | None = None) -> dict:
        """GET /copilot/quality: the totals over the window and its buckets."""
        now = now if now is not None else time.time()
        t0 = now - hours * 3600
        rows = self.store.since(t0)
        return {
            "from": round(t0, 3), "to": round(now, 3), "bucket_s": bucket_s,
            "store": self.note or self.store.name,
            "totals": totals(rows),
            "series": series(rows, t0, bucket_s),
        }
