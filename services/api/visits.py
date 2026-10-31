"""
Usage traction, consent-gated (visits.py).

The banner the site shows first (web/src/dashboard/Consent.tsx) asks the visitor whether their
usage may be measured. Only when the answer is "yes" does anything get stored here: one row
per page visit - the guest id (the same anonymous session id the rest of the API uses, never
a name or an email), the page, the time and the IP shortened to its network (the last byte of
an IPv4 address, everything past the /48 of an IPv6 one, set to zero: coarse_ip). The full
address is never stored and never sent anywhere, and no place is looked up from it. "No"
stores nothing - the session cookie still works, it is functional. The privacy page
(web/public/legal/privacy.html) describes exactly this; change both together.

The same module also ships the server's WARNING-and-above logs to Supabase
(SupabaseLogHandler): a logs table beside the visits, so a deployment can watch its health
from the same project. Everything degrades: no Supabase -> the visits/logs stay in the local
SQLite (same file the guests use).

  STF_TRACKING=1|0       measure usage at all (default 1; 0 answers the beacon with 204)
  STF_TRACK_DAYS=180     how long the consent cookie is kept
  STF_VISIT_DAYS=90      how long a visit row and a shipped log line are kept (pruned hourly);
                         DELETE /guest removes a guest's visits at once
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from . import keepalive
from .logging_config import get_logger
from .store import ROOT

logger = get_logger(__name__)

COOKIE = "stf_consent"
BATCH = 25  # app-log records per insert


# ----------------------------------------------------------------------------- the address
def coarse_ip(ip: str | None) -> str | None:
    """An address shortened to its network, as stored: 93.184.216.34 -> 93.184.216.0,
    2a00:1450:4001:82a::200e -> 2a00:1450:4001::. A private or loopback address (a developer's
    machine) is "local"; anything that is not an address is dropped."""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
        return "local"
    bits = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{bits}", strict=False).network_address)


# ----------------------------------------------------------------------------- the stores
class SqliteVisits:
    """visits + app_logs tables in the same SQLite file the guests use."""

    name = "sqlite"

    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS visits (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              guest TEXT NOT NULL, t REAL NOT NULL, page TEXT NOT NULL,
              ip TEXT, ua TEXT);
            CREATE INDEX IF NOT EXISTS visits_guest_t ON visits (guest, t DESC);
            CREATE TABLE IF NOT EXISTS app_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              t REAL NOT NULL, level TEXT NOT NULL, logger TEXT NOT NULL, message TEXT NOT NULL);
            """
        )

    def add_visit(self, v: dict) -> None:
        """Record one page visit (SQLite backend)."""
        with self._lock:
            self._db.execute(
                "INSERT INTO visits (guest, t, page, ip, ua) VALUES (?, ?, ?, ?, ?)",
                (v["guest"], v["t"], v["page"], v.get("ip"), v.get("ua")),
            )

    def add_logs(self, rows: list[dict]) -> None:
        """Buffer log rows for one batch insert (SQLite backend)."""
        with self._lock:
            self._db.executemany(
                "INSERT INTO app_logs (t, level, logger, message) VALUES (?, ?, ?, ?)",
                [(r["t"], r["level"], r["logger"], r["message"]) for r in rows],
            )

    def visits(self, guest: str, limit: int = 200) -> list[dict]:
        """One guest's visit history (SQLite backend)."""
        with self._lock:
            cur = self._db.execute(
                "SELECT guest, t, page, ip, ua FROM visits"
                " WHERE guest = ? ORDER BY t DESC LIMIT ?",
                (guest, limit),
            )
            cols = ("guest", "t", "page", "ip", "ua")
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def forget(self, guest: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM visits WHERE guest = ?", (guest,))

    def lapse(self, before: float) -> None:
        """Delete visits and log lines older than `before` (a Unix time)."""
        with self._lock:
            self._db.execute("DELETE FROM visits WHERE t < ?", (before,))
            self._db.execute("DELETE FROM app_logs WHERE t < ?", (before,))


class SupabaseVisits:
    """The same two tables in Postgres on Supabase, over PostgREST with the service key."""

    name = "supabase"

    def __init__(self, url: str, key: str) -> None:
        self.url, self.key = url.rstrip("/"), key

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        req = urllib.request.Request(
            self.url + "/rest/v1/" + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.key}",
                "apikey": self.key,
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        with keepalive.urlopen(req, timeout=10) as r:  # kept-alive: no TLS handshake per query
            raw = r.read()
        return json.loads(raw) if raw else None

    def ready(self) -> str | None:
        """None when the Supabase tables answer; otherwise why they cannot be used."""
        try:
            self._req("GET", "visits?select=guest&limit=1")
            self._req("GET", "app_logs?select=id&limit=1")
            return None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return "Supabase rejected the service key (SUPABASE_SERVICE_KEY)"
            if e.code == 404:
                return "the visits/app_logs tables are missing (supabase/migrations)"
            return f"Supabase answered {e.code}"
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            return f"Supabase is unreachable ({type(e).__name__})"

    def add_visit(self, v: dict) -> None:
        """Insert one visit row, timestamp converted to ISO 8601 (PostgREST contract)."""
        # Postgres' timestamptz wants ISO 8601, not a Unix float (PostgREST answers 400)
        self._req("POST", "visits", {**v, "t": _iso(v["t"])})

    def add_logs(self, rows: list[dict]) -> None:
        """Insert buffered log rows, timestamps converted to ISO 8601."""
        self._req("POST", "app_logs", [{**r, "t": _iso(r["t"])} for r in rows])

    def visits(self, guest: str, limit: int = 200) -> list[dict]:
        """One guest's visit history (Supabase backend)."""
        q = urllib.parse.quote(guest, safe="")
        path = f"visits?select=guest,t,page,ip,ua&guest=eq.{q}&order=t.desc&limit={int(limit)}"
        return self._req("GET", path) or []

    def forget(self, guest: str) -> None:
        self._req("DELETE", f"visits?guest=eq.{urllib.parse.quote(guest, safe='')}")

    def lapse(self, before: float) -> None:
        """Delete visits and log lines older than `before` (a Unix time)."""
        when = urllib.parse.quote(_iso(before), safe="")
        self._req("DELETE", f"visits?t=lt.{when}")
        self._req("DELETE", f"app_logs?t=lt.{when}")


def _iso(t: float) -> str:
    """A Unix epoch second as ISO 8601 UTC, the shape Postgres' timestamptz accepts."""
    return datetime.fromtimestamp(t, tz=UTC).isoformat()


def store_from_env(env: dict) -> tuple[Any, str]:
    """The visits store, and a note on why it is the one in use (same pick as guests.py)."""
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_SECRET_KEY")
    want = (env.get("STF_DB") or "auto").lower()
    path = env.get("STF_DB_PATH") or os.path.join(env.get("STF_DATA_DIR") or ROOT, "stf.db")
    if want in ("auto", "supabase") and url and key:
        db = SupabaseVisits(url, key)
        why = db.ready()
        if why is None:
            return db, "Supabase Postgres"
        logger.warning("Visits stay on SQLite: %s", why)
        return SqliteVisits(path), f"SQLite: {why}"
    return SqliteVisits(path), "SQLite"


# ----------------------------------------------------------------------------- the tracker
class Visits:
    """Records what was looked at, only after the visitor said yes. Dedupes a guest re-sending
    the same page inside ten seconds, so an SPA's eager beacon cannot fill the table."""

    def __init__(self, env: dict, store: Any = None, note: str = ""):
        if store is not None:
            self.store, self.note = store, note or store.name
        else:
            self.store, self.note = store_from_env(env)
        self.on = env.get("STF_TRACKING", "1") != "0"
        self.days = float(env.get("STF_TRACK_DAYS", "180"))
        self.keep_s = float(env.get("STF_VISIT_DAYS", "90")) * 86400
        self._pruned = 0.0
        self._last: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def _fresh(self, key: tuple, now: float) -> bool:
        with self._lock:
            if now - self._last.get(key, 0.0) < 10.0:
                return False
            self._last[key] = now
            if len(self._last) > 4096:
                for k in [k for k, t in self._last.items() if now - t > 3600]:
                    self._last.pop(k, None)
        return True

    def forget(self, guest: str) -> None:
        """A guest's visits, gone at once (DELETE /guest)."""
        try:
            self.store.forget(guest)
        except (sqlite3.Error, urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            logger.warning("Could not forget the guest's visits: %s", e)

    def record(
        self,
        guest: str | None,
        page: str,
        ip: str | None,
        ua: str | None,
        consent: bool,
        now: float | None = None,
    ) -> bool:
        """A beacon. consent False (or the tracker off) stores nothing - that is the promise."""
        if not self.on or not consent:
            return False
        now = now if now is not None else time.time()
        if not guest or not self._fresh((guest, page), now):
            return False
        row = {
            "guest": guest,
            "t": now,
            "page": page[:200],
            "ip": coarse_ip(ip),
            "ua": (ua or "")[:300],
        }
        try:
            self.store.add_visit(row)
            if now - self._pruned > 3600:  # the retention promise, checked at most hourly
                self._pruned = now
                self.store.lapse(now - self.keep_s)
        except (sqlite3.Error, urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            logger.warning("Could not store the visit: %s", e)
        return True


# ----------------------------------------------------------------------------- log shipping
class SupabaseLogHandler(logging.Handler):
    """A logging handler that batches WARNING-and-above records into the app_logs table,
    flushing on a timer (each record must cost nothing to the request being served)."""

    def __init__(self, store: Any, level: int = logging.WARNING, flush_s: float = 5.0) -> None:
        super().__init__(level)
        self.store, self.flush_s = store, flush_s
        self._rows: list[dict] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._closed = False
        # a cap on records shipped per minute: a scan that sends thousands of bad requests
        # (each a WARNING) must not fill the logs table on the free database
        self.max_per_min, self._window, self._n = 120, 0.0, 0

    def emit(self, record: logging.LogRecord) -> None:
        """A log record arrives: rate-limit, buffer, and ship by size or timer. Never raises."""
        try:
            row = {
                "t": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record)[:2000],
            }
            with self._lock:
                if self._closed:
                    return
                if record.created - self._window >= 60.0:
                    self._window, self._n = record.created, 0
                self._n += 1
                if self._n > self.max_per_min:
                    return
                self._rows.append(row)
                if len(self._rows) >= BATCH:
                    rows, self._rows = self._rows, []
                else:
                    self._arm_locked()
                    return
            self._ship(rows)
        except Exception:  # a logger must never raise into the app
            self.handleError(record)

    def _arm_locked(self) -> None:
        if self._timer is None or not self._timer.is_alive():
            self._timer = threading.Timer(self.flush_s, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        """Ship whatever is buffered now (called by the timer and at shutdown)."""
        with self._lock:
            if not self._rows:
                self._timer = None
                return
            rows, self._rows = self._rows, []
        self._ship(rows)

    def _ship(self, rows: list[dict]) -> None:
        try:
            self.store.add_logs(rows)
        except (sqlite3.Error, urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            logger.warning("Could not ship %d log records: %s", len(rows), e)

    def close(self) -> None:
        """Stop the shipping timer and mark the handler closed (shutdown hook)."""
        with self._lock:
            self._closed = True
            if self._timer:
                self._timer.cancel()
                self._timer = None
        self.flush()
        super().close()


def consent_cookie(value: str, days: float, secure: bool) -> str:
    """The Set-Cookie header value recording the visitor's analytics consent."""
    age = int(days * 86400)
    return f"{COOKIE}={value}; Path=/; Max-Age={age}; SameSite=Lax" + ("; Secure" if secure else "")
