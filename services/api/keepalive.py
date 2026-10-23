"""
Kept-alive HTTPS for the backend's Supabase calls: a drop-in for `urllib.request.urlopen`.

urllib opens a new TCP + TLS connection for every request. To Supabase that handshake costs as
much as the query itself: measured 120 ms per query on a new connection against 60 ms on a kept
one (tests/perf/bench_backend.py, docs/perf/). Here each worker thread keeps one connection per
host and reuses it; the request and the response are urllib's own types, so a caller changes one
line:

    with keepalive.urlopen(req, timeout=10) as r:   # was urllib.request.urlopen
        raw = r.read()

Errors are urllib's: a non-2xx status raises urllib.error.HTTPError (with the body readable), a
network failure urllib.error.URLError or TimeoutError. A kept connection the server has closed
in the meantime fails at once on the next request; that request is sent again on a fresh
connection - only when it cannot have been processed (the connection was reused and failed
before a response) and only for an idempotent method, or for any method when nothing was sent.
A write (POST, PATCH) only reuses a connection idle under MAX_IDLE_WRITE_S, so that case is rare
for writes; when it happens the caller sees the URLError it already handles.
"""
from __future__ import annotations

import http.client
import io
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request

_local = threading.local()
_ctx = ssl.create_default_context()
IDEMPOTENT = {"GET", "HEAD", "DELETE", "PUT", "OPTIONS"}
# a kept connection idle longer than this is dropped before use (servers close idle ones). A
# write cannot be sent again safely if the server closed the connection under it, so a write only
# takes a connection that was busy moments ago.
MAX_IDLE_S = 50.0
MAX_IDLE_WRITE_S = 15.0


class Response(io.BytesIO):
    """What urlopen returns: read(), status, headers, getcode(), a context manager."""

    def __init__(
        self, status: int, reason: str, headers: http.client.HTTPMessage, body: bytes, url: str
    ):
        super().__init__(body)
        self.status, self.reason, self.headers, self.url = status, reason, headers, url

    def getcode(self) -> int:
        """urllib compatibility: the response status code."""
        return self.status

    def info(self) -> http.client.HTTPMessage:
        """urllib compatibility: the response headers."""
        return self.headers


def _conns() -> dict:
    if not hasattr(_local, "conns"):
        _local.conns = {}
    return _local.conns


def _connection(scheme: str, netloc: str, timeout: float, method: str = "GET"):
    import time

    key = (scheme, netloc)
    entry = _conns().get(key)
    idle = MAX_IDLE_S if method in IDEMPOTENT else MAX_IDLE_WRITE_S
    if entry and time.monotonic() - entry[1] < idle:
        conn = entry[0]
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        return conn, True
    if entry:
        entry[0].close()
    conn = (http.client.HTTPSConnection(netloc, timeout=timeout, context=_ctx) if scheme == "https"
            else http.client.HTTPConnection(netloc, timeout=timeout))
    _conns()[key] = (conn, time.monotonic())
    return conn, False


def _drop(scheme: str, netloc: str) -> None:
    entry = _conns().pop((scheme, netloc), None)
    if entry:
        entry[0].close()


def urlopen(req: urllib.request.Request | str, timeout: float = 30.0) -> Response:
    """Sends `req` on this thread's kept connection to its host and returns the whole response."""
    import time

    if isinstance(req, str):
        req = urllib.request.Request(req)
    url = req.full_url
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https"):
        raise urllib.error.URLError(f"unsupported scheme: {u.scheme}")
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    method = req.get_method()
    headers = dict(req.header_items())
    body = req.data
    for attempt in (0, 1):
        conn, reused = _connection(u.scheme, u.netloc, timeout, method)
        sent = False
        try:
            conn.request(method, path, body=body, headers=headers)
            sent = True
            r = conn.getresponse()
            data = r.read()
        except (
            http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError,
            http.client.CannotSendRequest, http.client.BadStatusLine,
        ) as e:
            _drop(u.scheme, u.netloc)
            # a stale kept connection: safe to send again when it cannot have been processed
            if attempt == 0 and reused and (not sent or method in IDEMPOTENT):
                continue
            raise urllib.error.URLError(e) from e
        except TimeoutError as e:
            _drop(u.scheme, u.netloc)
            raise TimeoutError(f"{method} {u.netloc}: timed out after {timeout} s") from e
        except OSError as e:
            _drop(u.scheme, u.netloc)
            raise urllib.error.URLError(e) from e
        _conns()[(u.scheme, u.netloc)] = (conn, time.monotonic())
        if r.getheader("connection", "").lower() == "close":
            _drop(u.scheme, u.netloc)
        if not 200 <= r.status < 300:
            raise urllib.error.HTTPError(url, r.status, r.reason, r.headers, io.BytesIO(data))
        return Response(r.status, r.reason, r.headers, data, url)
    raise AssertionError("unreachable")
