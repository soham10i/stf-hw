"""
Guest sessions: each visitor is a guest of their own, so no two people see each other's
copilot conversations, inspection photos or live twin - until sign-in (SSO) replaces them.

A guest is issued by the server, not claimed by the browser: a random id in a cookie,
`stf_guest = <id>.<signature>`, HttpOnly (page scripts cannot read it), SameSite=Lax (other
sites' requests do not carry it), Secure over HTTPS, signed with STF_SESSION_SECRET so it cannot
be forged or guessed into someone else's. Every request that reaches the API under one is that
guest's: the id replaces whatever X-STF-User the browser sends, and the current guest is
available to the rest of the API (current()).

The database keeps the guests and their documents (the copilot's sessions):

  SqliteDb    a file, STF_DB_PATH (default <STF_DATA_DIR>/stf.db) - the default, and what a
              local run uses. On a host with an ephemeral disk (Render's free tier) it lasts
              until the next deploy.
  SupabaseDb  Postgres on Supabase over its REST API (PostgREST), when SUPABASE_URL and
              SUPABASE_SERVICE_KEY are set and its tables exist (docs/DATABASE.md has the SQL):
              survives deploys. Without the tables the API stays on SQLite and says so (GET /guest).

A guest record holds no personal data: when it was made, when last seen, how many visits. It
lapses after STF_GUEST_DAYS of inactivity (default 30), and its documents with it. DELETE /guest
forgets the guest at once - its conversations and photos - and the next request starts a new one.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import security as sec
from .logging_config import get_logger
from .store import ROOT

logger = get_logger(__name__)

COOKIE = "stf_guest"
ID_HEX = 32
TIMEOUT_S = 10
TOUCH_EVERY_S = 300

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("stf_guest", default=None)


def current() -> str | None:
    """Return the guest ID associated with the current asynchronous request context.

    Returns:
        str | None: 32-character hexadecimal guest ID, or None if no guest is bound.
    """
    return _current.get()


def _valid_id(s: str) -> bool:
    return len(s) == ID_HEX and all(c in "0123456789abcdef" for c in s)


# ----------------------------------------------------------------------------- the databases
class SqliteDb:
    """SQLite-backed database adapter for guest sessions and copilot documents.

    Attributes:
        name: Backend identifier string ('sqlite').
        path: Filesystem path to the SQLite database file.
    """

    name = "sqlite"

    def __init__(self, path: str) -> None:
        """Initialize SQLite database, enabling WAL journal mode and creating tables.

        Args:
            path: Target database file path.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS guests (
              id TEXT PRIMARY KEY, created REAL NOT NULL, last_seen REAL NOT NULL,
              visits INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS documents (
              col TEXT NOT NULL, owner TEXT NOT NULL, id TEXT NOT NULL, doc TEXT NOT NULL,
              t REAL NOT NULL, PRIMARY KEY (col, owner, id));
            CREATE INDEX IF NOT EXISTS documents_owner ON documents (col, owner, t DESC);
            """
        )
        logger.debug("Initialized SqliteDb at '%s'", path)

    def _q(self, sql: str, args: tuple = ()) -> list[tuple]:
        """Execute a SQL query inside a thread-safe lock.

        Args:
            sql: Query string.
            args: Query parameter tuple.

        Returns:
            list[tuple]: Query result rows.

        Raises:
            sqlite3.Error: If query execution fails.
        """
        try:
            with self._lock:
                return self._db.execute(sql, args).fetchall()
        except sqlite3.Error as e:
            logger.error("SqliteDb query failed: %s with args %s: %s", sql, args, e)
            raise

    # guests
    def guest(self, id: str) -> dict | None:
        """Fetch guest metadata record by ID."""
        r = self._q("SELECT id, created, last_seen, visits FROM guests WHERE id = ?", (id,))
        return dict(zip(("id", "created", "last_seen", "visits"), r[0], strict=True)) if r else None

    def add_guest(self, id: str, now: float) -> None:
        """Insert a newly issued guest record."""
        self._q("INSERT OR IGNORE INTO guests VALUES (?, ?, ?, 1)", (id, now, now))

    def touch(self, id: str, now: float) -> None:
        """Update a returning guest's last_seen timestamp and increment visit counter."""
        self._q("UPDATE guests SET last_seen = ?, visits = visits + 1 WHERE id = ?", (now, id))

    def forget(self, id: str) -> None:
        """Delete a guest's record and all associated documents."""
        self._q("DELETE FROM documents WHERE owner = ?", (id,))
        self._q("DELETE FROM guests WHERE id = ?", (id,))

    def lapse(self, before: float) -> int:
        """Purge inactive guests not seen since before timestamp."""
        old = [r[0] for r in self._q("SELECT id FROM guests WHERE last_seen < ?", (before,))]
        for g in old:
            self.forget(g)
        return len(old)

    def guests(self) -> int:
        """Return the total count of registered guests."""
        return self._q("SELECT COUNT(*) FROM guests")[0][0]

    # documents (store.DocStore)
    def get(self, col: str, owner: str, id: str) -> dict | None:
        """Retrieve a stored JSON document."""
        r = self._q(
            "SELECT doc FROM documents WHERE col = ? AND owner = ? AND id = ?", (col, owner, id)
        )
        return json.loads(r[0][0]) if r else None

    def put(self, col: str, owner: str, id: str, doc: dict) -> None:
        """Persist or replace a document record."""
        self._q(
            "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?)",
            (col, owner, id, json.dumps(doc, ensure_ascii=False), time.time()),
        )

    def delete(self, col: str, owner: str, id: str) -> bool:
        """Delete a single document record."""
        with self._lock:
            n = self._db.execute(
                "DELETE FROM documents WHERE col = ? AND owner = ? AND id = ?", (col, owner, id)
            ).rowcount
        return n > 0

    def list(self, col: str, owner: str, fields: tuple[str, ...], limit: int = 100) -> list[dict]:
        """List documents belonging to an owner, newest first, projecting requested summary fields."""
        rows = self._q(
            "SELECT id, doc FROM documents WHERE col = ? AND owner = ? ORDER BY t DESC LIMIT ?",
            (col, owner, limit),
        )
        out = []
        for id, raw in rows:
            doc = json.loads(raw)
            out.append({"id": id, **{k: doc.get(k) for k in fields}})
        return out


class SupabaseDb:
    """The same tables in Postgres on Supabase, over PostgREST, with the service key (server)."""

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
        return json.loads(raw) if raw else None

    def ready(self) -> str | None:
        """None when both tables answer; else why not."""
        try:
            self._req("GET", "guests?select=id&limit=1")
            self._req("GET", "documents?select=id&limit=1")
            return None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return "Supabase rejected the service key (SUPABASE_SERVICE_KEY)"
            if e.code == 404:
                return "the Supabase tables are missing (supabase/migrations, docs/DATABASE.md)"
            return f"Supabase answered {e.code}"
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            return f"Supabase is unreachable ({type(e).__name__})"

    @staticmethod
    def _eq(**kv: str) -> str:
        return "&".join(f"{k}=eq.{urllib.parse.quote(v, safe='')}" for k, v in kv.items())

    def guest(self, id: str) -> dict | None:
        r = self._req("GET", f"guests?select=id,created,last_seen,visits&{self._eq(id=id)}")
        return r[0] if r else None

    def add_guest(self, id: str, now: float) -> None:
        self._req(
            "POST",
            "guests",
            {"id": id, "created": now, "last_seen": now, "visits": 1},
            prefer="resolution=ignore-duplicates,return=minimal",
        )

    def touch(self, id: str, now: float) -> None:
        g = self.guest(id)
        if g:
            self._req(
                "PATCH",
                f"guests?{self._eq(id=id)}",
                {"last_seen": now, "visits": g["visits"] + 1},
                prefer="return=minimal",
            )

    def forget(self, id: str) -> None:
        self._req("DELETE", f"documents?{self._eq(owner=id)}", prefer="return=minimal")
        self._req("DELETE", f"guests?{self._eq(id=id)}", prefer="return=minimal")

    def lapse(self, before: float) -> int:
        old = self._req("GET", f"guests?select=id&last_seen=lt.{before}") or []
        for g in old:
            self.forget(g["id"])
        return len(old)

    def guests(self) -> int:
        return len(self._req("GET", "guests?select=id") or [])

    def get(self, col: str, owner: str, id: str) -> dict | None:
        r = self._req("GET", f"documents?select=doc&{self._eq(col=col, owner=owner, id=id)}")
        return r[0]["doc"] if r else None

    def put(self, col: str, owner: str, id: str, doc: dict) -> None:
        self._req(
            "POST",
            "documents",
            {"col": col, "owner": owner, "id": id, "doc": doc, "t": time.time()},
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def delete(self, col: str, owner: str, id: str) -> bool:
        r = self._req(
            "DELETE",
            f"documents?{self._eq(col=col, owner=owner, id=id)}",
            prefer="return=representation",
        )
        return bool(r)

    def list(self, col: str, owner: str, fields: tuple[str, ...], limit: int = 100) -> list[dict]:
        own = self._eq(col=col, owner=owner)
        q = f"documents?select=id,doc&{own}&order=t.desc&limit={int(limit)}"
        return [
            {"id": r["id"], **{k: r["doc"].get(k) for k in fields}}
            for r in self._req("GET", q) or []
        ]


def db_from_env(env: dict) -> tuple[Any, str]:
    """The database and a note on why it is the one in use."""
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_SECRET_KEY")
    want = (env.get("STF_DB") or "auto").lower()
    path = env.get("STF_DB_PATH") or os.path.join(env.get("STF_DATA_DIR") or ROOT, "stf.db")
    if want in ("auto", "supabase") and url and key:
        db = SupabaseDb(url, key)
        why = db.ready()
        if why is None:
            return db, "Supabase Postgres"
        return SqliteDb(path), f"SQLite: {why}"
    return SqliteDb(path), "SQLite" + (
        "" if want == "sqlite" else ": no SUPABASE_URL / SUPABASE_SERVICE_KEY"
    )


# ----------------------------------------------------------------------------- the sessions
def _secret(env: dict) -> bytes:
    """STF_SESSION_SECRET, else one kept beside the local database (a local run: cookies stay
    valid across restarts); a deployment sets it (render.yaml generates one)."""
    s = env.get("STF_SESSION_SECRET")
    if s:
        return s.encode()
    path = os.path.join(env.get("STF_DATA_DIR") or ROOT, "session_secret")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip().encode()
    except OSError:
        s = secrets.token_hex(32)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(s)
        os.chmod(path, 0o600)
        return s.encode()


class Guests:
    def __init__(self, env: dict, db: Any = None, note: str = "") -> None:
        self.db, self.note = (db, note or db.name) if db is not None else db_from_env(env)
        self.key = _secret(env)
        self.days = float(env.get("STF_GUEST_DAYS", "30"))
        # a new guest per client: a burst of 20, then one a minute (a crawler cannot fill the table)
        self.limiter = sec.RateLimiter(rate=1 / 60, burst=20)
        self._seen: dict[str, float] = {}
        self._made = 0

    def sign(self, id: str) -> str:
        return f"{id}.{hmac.new(self.key, id.encode(), hashlib.sha256).hexdigest()[:32]}"

    def verify(self, cookie: str | None) -> str | None:
        if not cookie or "." not in cookie:
            return None
        id, _ = cookie.split(".", 1)
        return id if _valid_id(id) and hmac.compare_digest(self.sign(id), cookie) else None

    def resolve(self, cookie: str | None, client: str) -> tuple[str, bool]:
        """The request's guest, and whether it is new (its cookie must be set)."""
        now = time.time()
        id = self.verify(cookie)
        try:
            if id and (id in self._seen or self.db.guest(id)):
                if now - self._seen.get(id, 0) > TOUCH_EVERY_S:
                    self._seen[id] = now
                    self.db.touch(id, now)
                return id, False
            id = secrets.token_hex(ID_HEX // 2)
            if self.limiter.allow(client):  # beyond the limit: a guest for this request only
                self.db.add_guest(id, now)
                self._seen[id] = now
                self._made += 1
                if self._made % 200 == 1:
                    self.db.lapse(now - self.days * 86400)
        except (sqlite3.Error, urllib.error.URLError, TimeoutError, ValueError, KeyError):
            id = id or secrets.token_hex(ID_HEX // 2)  # the database is down: still a guest, unkept
        return id, True

    def cookie(self, id: str, secure: bool) -> str:
        age = int(self.days * 86400)
        return f"{COOKIE}={self.sign(id)}; Path=/; Max-Age={age}; HttpOnly; SameSite=Lax" + (
            "; Secure" if secure else ""
        )

    def clear_cookie(self, secure: bool) -> str:
        return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" + (
            "; Secure" if secure else ""
        )

    def status(self, id: str | None) -> dict:
        g = None
        try:
            g = self.db.guest(id) if id else None
        except (sqlite3.Error, urllib.error.URLError, TimeoutError, ValueError):
            pass
        return {
            "guest": (id or "")[:8],
            "since": g["created"] if g else None,
            "visits": g["visits"] if g else None,
            "kept_days": self.days,
            "database": self.db.name,
            "note": self.note,
        }


def bind(guest: str) -> contextvars.Token:
    return _current.set(guest)


def unbind(token: contextvars.Token) -> None:
    _current.reset(token)
