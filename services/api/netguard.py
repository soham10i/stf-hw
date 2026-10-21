"""
Outbound fetches of URLs the server did not choose (search results, a page the copilot opens):
public addresses only (SSRF guard).

Checking the host's DNS answer before the request is not enough: the name can resolve to a
public address for the check and to 127.0.0.1 or the cloud metadata service a moment later
(DNS rebinding), and a public page can redirect anywhere. So the check is made on the socket
itself, after it connects and before a byte of HTTP is sent - every connection, every redirect.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request


def public_ip(raw: str) -> bool:
    """A globally routable address: not loopback, private, link-local (metadata), CGNAT,
    0.0.0.0 or an IPv4-mapped IPv6 form of any of those."""
    try:
        ip = ipaddress.ip_address(raw.split("%")[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return ip.is_global and (mapped is None or mapped.is_global)


def public_host(host: str, port: int | None = None) -> bool:
    """Every address the host resolves to is public (a fast, early refusal)."""
    host = (host or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".localhost", ".internal")):
        return False
    try:
        infos = socket.getaddrinfo(host, port)
    except (OSError, UnicodeError):
        return False
    return bool(infos) and all(public_ip(i[4][0]) for i in infos)


def public_url(url: str) -> bool:
    try:
        u = urllib.parse.urlparse(url)
        port = u.port
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.hostname) and public_host(u.hostname, port)


def _check_peer(sock: socket.socket) -> None:
    peer = sock.getpeername()[0]
    if not public_ip(peer):
        sock.close()
        raise urllib.error.URLError(f"refused: connected to a non-public address ({peer})")


class _HTTPConnection(http.client.HTTPConnection):
    def connect(self) -> None:
        super().connect()
        _check_peer(self.sock)


class _HTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        # the TCP connection and the TLS handshake, then the peer check: no request is sent
        # before it passes
        super().connect()
        _check_peer(self.sock)


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):  # noqa: ANN001
        return self.do_open(_HTTPConnection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):  # noqa: ANN001
        return self.do_open(_HTTPSConnection, req, context=self._context)


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Only http(s) redirects (never file:, ftp:); the socket check covers the address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if urllib.parse.urlparse(newurl).scheme not in ("http", "https"):
            raise urllib.error.URLError("redirect to a non-http(s) URL refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# no ProxyHandler: an outbound proxy would make the peer check meaningless
opener = urllib.request.OpenerDirector()
for _h in (_HTTPHandler(), _HTTPSHandler(), _Redirects(), urllib.request.HTTPErrorProcessor(),
           urllib.request.HTTPDefaultErrorHandler()):
    opener.add_handler(_h)
