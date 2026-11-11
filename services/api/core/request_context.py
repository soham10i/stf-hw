"""
The request id: one per HTTP request or socket, in every log line written while it is served,
in the X-Request-ID response header and in every error body, so a visitor's report ("it said
5f0c9a1e2b7d4c38") leads straight to the server's log lines.

A caller's own X-Request-ID is kept when it is a plain token (a proxy or a test may set one);
otherwise a new id is made. A plain ASGI middleware, not BaseHTTPMiddleware: it adds no task
per request and leaves streamed responses alone.
"""

from __future__ import annotations

import re
import secrets
from contextvars import ContextVar

HEADER = b"x-request-id"
_VALID = re.compile(rb"^[A-Za-z0-9._-]{8,64}$")
_current: ContextVar[str | None] = ContextVar("request_id", default=None)


def request_id() -> str | None:
    """The id of the request being served, or None outside one."""
    return _current.get()


def new_id() -> str:
    return secrets.token_hex(8)


class RequestIdMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        given = next((v for k, v in scope.get("headers", ()) if k == HEADER), b"")
        rid = given.decode() if _VALID.match(given) else new_id()
        # not reset afterwards: the server runs each request on its own task (its own context),
        # and the 500 handler, outside this middleware, still needs the id for its body
        _current.set(rid)

        async def send_with_id(message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", ()), (HEADER, rid.encode())]
            await send(message)

        await self.app(scope, receive, send_with_id)
