"""services/api/keepalive.py against a local HTTP/1.1 server that counts its connections."""
from __future__ import annotations

import http.server
import threading
import urllib.error
import urllib.request

import pytest

from services.api import keepalive


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive
    connections = 0
    requests = 0

    def setup(self):
        Handler.connections += 1
        super().setup()

    def _send(self, code, body=b"", close=False):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        if close:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        Handler.requests += 1
        if self.path == "/missing":
            return self._send(404, b'{"error":"no such row"}')
        if self.path == "/close":
            self._send(200, b"bye", close=True)
            self.close_connection = True
            return
        if self.path == "/drop":
            # closes without answering: what a server's idle timeout looks like to the next request
            self.close_connection = True
            return
        self._send(200, b'{"ok":true}')

    def do_POST(self):
        Handler.requests += 1
        n = int(self.headers.get("Content-Length", 0))
        self._send(201, self.rfile.read(n))

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    Handler.connections = Handler.requests = 0
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    keepalive._conns().clear()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    keepalive._conns().clear()


def test_reuses_one_connection(server):
    for _ in range(20):
        with keepalive.urlopen(server + "/rows", timeout=5) as r:
            assert r.status == 200 and r.read() == b'{"ok":true}'
    assert Handler.requests == 20
    assert Handler.connections == 1


def test_posts_a_body_and_returns_the_response(server):
    req = urllib.request.Request(
        server + "/rows", data=b'[{"a":1}]', method="POST",
        headers={"Content-Type": "application/json"},
    )
    with keepalive.urlopen(req, timeout=5) as r:
        assert r.status == 201 and r.read() == b'[{"a":1}]'


def test_a_non_2xx_status_is_urllibs_http_error_with_its_body(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        keepalive.urlopen(server + "/missing", timeout=5)
    assert e.value.code == 404
    assert e.value.read() == b'{"error":"no such row"}'
    # and the connection is still good for the next request
    keepalive.urlopen(server + "/rows", timeout=5)
    assert Handler.connections == 1


def test_a_connection_the_server_closed_is_replaced(server):
    keepalive.urlopen(server + "/close", timeout=5)
    keepalive.urlopen(server + "/rows", timeout=5)
    assert Handler.connections == 2


def test_a_read_on_a_dropped_connection_is_sent_again(server):
    keepalive.urlopen(server + "/rows", timeout=5)
    # the server drops the kept connection without answering: a GET is sent again, once
    keepalive.urlopen(server + "/rows", timeout=5)
    with pytest.raises(urllib.error.URLError):
        keepalive.urlopen(server + "/drop", timeout=5)  # dropped twice: the error surfaces


def test_a_refused_connection_is_urllibs_url_error():
    keepalive._conns().clear()
    with pytest.raises(urllib.error.URLError):
        keepalive.urlopen("http://127.0.0.1:1/x", timeout=2)
