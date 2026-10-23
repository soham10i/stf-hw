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

from .logging_config import get_logger

logger = get_logger(__name__)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


@dataclass(frozen=True)
class Settings:
    """Security configuration: allowed browser origins, the admin API token, limits."""

    allowed_origins: tuple[str, ...]
    api_token: str | None
    max_ws_clients: int
    commands_per_second: float = 4.0
    command_burst: int = 8

    @staticmethod
    def from_env() -> Settings:
        """Resolve settings from the environment (STF_ALLOWED_ORIGINS, STF_API_TOKEN, ...)."""
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
    if h.startswith("["):  # [::1]:8000
        return h[: h.find("]") + 1]
    return h.split(":")[0]


def is_local(request_host: str | None) -> bool:
    """Whether a request's Host header names this machine (loopback)."""
    return _host(request_host) in LOCAL_HOSTS


LOOPBACK = ("127.0.0.1", "::1")


def _forwarded_for(request: Request | WebSocket) -> list[str]:
    raw = request.headers.get("x-forwarded-for") or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


def is_local_request(request: Request) -> bool:
    """The operator's own machine: the Host says localhost, the TCP peer is loopback, and any
    proxy hop (the Vite dev proxy adds X-Forwarded-For) is loopback too. The Host header alone
    is the client's to choose, so it never suffices on its own."""
    if not is_local(request.headers.get("host")):
        return False
    if request.headers.get("forwarded") or request.headers.get("x-real-ip"):
        return False
    if any(h not in LOOPBACK for h in _forwarded_for(request)):
        return False
    # the raw TCP peer: uvicorn's proxy-header rewrite never runs for a localhost-only request
    # without X-Forwarded-For, and with one every entry was just checked to be loopback
    peer = request.scope.get("client")
    return bool(peer) and peer[0] in LOOPBACK


def proxy_hops() -> int:
    """How many proxies in front append to X-Forwarded-For: STF_PROXY_HOPS, else 1 on Cloud Run
    (K_SERVICE is set in every Cloud Run container), else 0."""
    default = "1" if os.environ.get("K_SERVICE") else "0"
    try:
        return max(0, int(os.environ.get("STF_PROXY_HOPS", default) or 0))
    except ValueError:
        return 0


def client_ip(request: Request | WebSocket) -> str:
    """The caller's address, for rate limits and the visit log.

    X-Forwarded-For is written by whoever sends the request, so it is trusted only as far as
    the deployment says: STF_PROXY_HOPS is how many proxies in front APPEND to it (Cloud Run's
    front end: 1). The entry that many places from the right is the address the outermost
    trusted proxy saw; everything to its left is client-written. STF_PROXY_HOPS=0 (the
    default off Cloud Run: no proxy) ignores the header and uses the TCP peer - an app
    reached directly must never take its rate-limit key from a header (found by Strix
    against a local instance)."""
    hops = proxy_hops()
    xff = _forwarded_for(request) if hops else []
    if len(xff) >= hops > 0:
        return xff[-hops]
    peer = request.scope.get("client")
    return peer[0] if peer else "?"


def origin_ok(settings: Settings, request: Request) -> bool:
    """No Origin (not a browser), an allowed origin, or the page's own origin."""
    origin = request.headers.get("origin")
    return not (
        origin
        and origin not in settings.allowed_origins
        and _host(origin.split("://", 1)[-1]) != _host(request.headers.get("host"))
    )


async def read_body(request: Request, limit: int) -> bytes:
    """The request body, refusing (413) before more than `limit` bytes are held in memory:
    a declared Content-Length is checked first, a chunked body is counted as it arrives."""
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > limit:
                raise HTTPException(status_code=413, detail=f"at most {limit} bytes")
        except ValueError:
            raise HTTPException(status_code=400, detail="bad Content-Length") from None
    chunks, n = [], 0
    async for chunk in request.stream():
        n += len(chunk)
        if n > limit:
            raise HTTPException(status_code=413, detail=f"at most {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def token_ok(settings: Settings, presented: str | None) -> bool:
    """Constant-time check of the admin API token (no token configured: always False)."""
    if not (settings.api_token and presented):
        return False
    return hmac.compare_digest(settings.api_token, presented)


@dataclass
class RateLimiter:
    """Token bucket per client key."""

    rate: float
    burst: int
    max_keys: int = 50_000
    _buckets: dict[str, tuple[float, float]] = field(default_factory=dict)

    def allow(self, key: str, now: float | None = None) -> bool:
        """Take one token from the client's bucket; True when the burst/rate permits."""
        now = time.monotonic() if now is None else now
        if len(self._buckets) > self.max_keys:  # many addresses: drop the full (idle) buckets
            idle = (self.burst - 1) / self.rate if self.rate > 0 else 0.0
            self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < idle}
        tokens, last = self._buckets.get(key, (float(self.burst), now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1.0, now)
        return True


class CommandGuard:
    """FastAPI security dependency enforcing origin verification, local host / token
    auth, and rate limits."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the guard with API settings and a token bucket rate limiter.

        Args:
            settings: Security configuration containing allowed origins, API token, and limits.
        """
        self.settings = settings
        self.limiter = RateLimiter(settings.commands_per_second, settings.command_burst)

    async def __call__(self, request: Request) -> None:
        """Authorize an incoming machine command request.

        Args:
            request: The incoming FastAPI HTTP request.

        Raises:
            HTTPException: 403 Forbidden if origin is untrusted or host lacks authentication.
            HTTPException: 429 Too Many Requests if the client rate limit is exceeded.
        """
        if not origin_ok(self.settings, request):
            note("command: foreign origin")
            raise HTTPException(status_code=403, detail="origin not allowed")
        local = is_local_request(request)
        if not (local or token_ok(self.settings, request.headers.get("x-stf-token"))):
            note("command: not local, no token")
            raise HTTPException(
                status_code=403, detail="commands need the operator's machine or an operator token"
            )
        if not self.limiter.allow(client_ip(request)):
            note("command: rate limit")
            raise HTTPException(status_code=429, detail="too many commands")


def ws_origin_ok(settings: Settings, ws: WebSocket) -> bool:
    """Validate whether an incoming WebSocket connection origin is authorized.

    Cross-site WebSocket hijacking guard: standard browsers always send Origin.

    Args:
        settings: Security settings containing allowed origins.
        ws: Incoming WebSocket connection.

    Returns:
        bool: True if authorized, False otherwise.
    """
    origin = ws.headers.get("origin")
    if origin is None:  # not a browser (e.g. CLI tools, test suites)
        return True
    if origin in settings.allowed_origins:
        return True
    # The page's own origin, when the web app is served through a tunnel/proxy
    return _host(origin.split("://", 1)[-1]) == _host(ws.headers.get("host"))


class ClientCounter:
    """Thread-safe connection counter enforcing max concurrent active client limits."""

    def __init__(self, limit: int) -> None:
        """Initialize client counter with concurrency limit.

        Args:
            limit: Maximum allowed concurrent active clients.
        """
        self.limit = limit
        self.n = 0

    def try_add(self) -> bool:
        """Attempt to register an additional active client.

        Returns:
            bool: True if admitted within limit, False if capacity reached.
        """
        if self.n >= self.limit:
            return False
        self.n += 1
        return True

    def remove(self) -> None:
        """Decrement active client count when a client disconnects."""
        self.n = max(0, self.n - 1)


# Recent rejected requests for health check reporting (no secrets, just counts)
REJECTED: deque[tuple[float, str]] = deque(maxlen=200)
COUNTS: dict[str, int] = defaultdict(int)


def note(kind: str) -> None:
    """Record a rejected security check for audit logging and health diagnostic metrics.

    Args:
        kind: String identifier describing the security rejection reason.
    """
    REJECTED.append((time.time(), kind))
    COUNTS[kind] += 1
    logger.warning("Security check rejected: %s", kind)
