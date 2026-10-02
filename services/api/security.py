"""
Access control for the live twin API.

The API drives a machine (simulated today, real tomorrow), so it separates
READ (layout, health, orders, the frame stream) from COMMAND (POST /command):

  * reads are open to the configured origins;
  * a command is accepted only from the operator's own machine (the request's
    Host is localhost), or with the operator token STF_API_TOKEN in the
    X-STF-Token header. A tunnel or proxy (ngrok, the Vite dev proxy reached
    from outside) therefore gives a READ-ONLY twin unless a token is set;
  * commands are rate-limited per client.

Configuration (environment):
  STF_ALLOWED_ORIGINS  comma-separated browser origins (default: the local web app)
  STF_API_TOKEN        operator token; unset = commands from localhost only
  STF_MAX_WS_CLIENTS   concurrent frame-stream clients (default 32)
"""

from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, WebSocket

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


@dataclass(frozen=True)
class Settings:
    allowed_origins: tuple[str, ...]
    api_token: str | None
    max_ws_clients: int
    commands_per_second: float = 4.0
    command_burst: int = 8

    @staticmethod
    def from_env() -> Settings:
        hosts, ports = ("localhost", "127.0.0.1"), (5173, 4173)
        default = ",".join(f"http://{h}:{p}" for p in ports for h in hosts)
        raw = os.environ.get("STF_ALLOWED_ORIGINS", default)
        # on Render the service's own public address is an allowed origin (it serves the app)
        own = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
        origins = tuple(dict.fromkeys(o.strip() for o in [*raw.split(","), own] if o.strip()))
        token = os.environ.get("STF_API_TOKEN") or None
        return Settings(origins, token, int(os.environ.get("STF_MAX_WS_CLIENTS", "32")))


def _host(header: str | None) -> str:
    h = (header or "").strip().lower()
    if h.startswith("["):                      # [::1]:8000
        return h[: h.find("]") + 1]
    return h.split(":")[0]


def is_local(request_host: str | None) -> bool:
    return _host(request_host) in LOCAL_HOSTS


def token_ok(settings: Settings, presented: str | None) -> bool:
    if not (settings.api_token and presented):
        return False
    return hmac.compare_digest(settings.api_token, presented)


@dataclass
class RateLimiter:
    """Token bucket per client key."""
    rate: float
    burst: int
    _buckets: dict[str, tuple[float, float]] = field(default_factory=dict)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        tokens, last = self._buckets.get(key, (float(self.burst), now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1.0, now)
        return True


class CommandGuard:
    """FastAPI dependency: may this request command the machine?"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.limiter = RateLimiter(settings.commands_per_second, settings.command_burst)

    async def __call__(self, request: Request) -> None:
        # a browser page from a foreign origin may not command, even towards localhost (CSRF)
        origin = request.headers.get("origin")
        if origin and origin not in self.settings.allowed_origins and \
                _host(origin.split("://", 1)[-1]) != _host(request.headers.get("host")):
            note("command: foreign origin")
            raise HTTPException(status_code=403, detail="origin not allowed")
        # Host is what the client asked for; a DNS-rebinding page arrives with its own
        # name, not localhost
        local = is_local(request.headers.get("host"))
        if not (local or token_ok(self.settings, request.headers.get("x-stf-token"))):
            note("command: not local, no token")
            raise HTTPException(
                status_code=403, detail="commands need the operator's machine or an operator token"
            )
        client = request.client.host if request.client else "?"
        if client in ("127.0.0.1", "::1"):          # behind the local web proxy: the real client
            client = (request.headers.get("x-forwarded-for") or client).split(",")[0].strip()
        if not self.limiter.allow(client):
            note("command: rate limit")
            raise HTTPException(status_code=429, detail="too many commands")


def ws_origin_ok(settings: Settings, ws: WebSocket) -> bool:
    """Cross-site WebSocket hijacking guard: a browser always sends Origin."""
    origin = ws.headers.get("origin")
    if origin is None:                          # not a browser (CLI tools, tests)
        return True
    if origin in settings.allowed_origins:
        return True
    # the page's own origin, when the web app is served through a tunnel/proxy
    return _host(origin.split("://", 1)[-1]) == _host(ws.headers.get("host"))


class ClientCounter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.n = 0

    def try_add(self) -> bool:
        if self.n >= self.limit:
            return False
        self.n += 1
        return True

    def remove(self) -> None:
        self.n = max(0, self.n - 1)


# recent rejected requests, for /health (no secrets, just counts)
REJECTED: deque[tuple[float, str]] = deque(maxlen=200)
COUNTS: dict[str, int] = defaultdict(int)


def note(kind: str) -> None:
    REJECTED.append((time.time(), kind))
    COUNTS[kind] += 1
