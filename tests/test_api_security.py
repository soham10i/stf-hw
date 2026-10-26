"""Access control of the live API (services/api/security.py)."""

import importlib

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from services.api import security as sec  # noqa: E402

LOCAL = {"host": "localhost:8000"}
TUNNEL = {"host": "example.ngrok-free.dev"}
GOOD = {"op": "home"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("STF_API_TOKEN", "s3cret-token")
    import services.api.app as appmod

    appmod = importlib.reload(appmod)
    # the operator's own machine: the TCP peer is loopback (Host alone is not enough)
    with TestClient(appmod.app, client=("127.0.0.1", 50000)) as c:
        yield c


@pytest.fixture()
def remote(monkeypatch):
    """A client on the internet, whatever headers it sends."""
    monkeypatch.setenv("STF_API_TOKEN", "s3cret-token")
    import services.api.app as appmod

    appmod = importlib.reload(appmod)
    with TestClient(appmod.app, client=("203.0.113.7", 50000)) as c:
        yield c


def test_reads_are_open(client):
    assert client.get("/health", headers=TUNNEL).status_code == 200
    assert client.get("/orders", headers=TUNNEL).status_code == 200


def test_command_from_localhost(client):
    assert client.post("/command", json=GOOD, headers=LOCAL).status_code == 200


def test_command_through_a_tunnel_is_refused(client):
    assert client.post("/command", json=GOOD, headers=TUNNEL).status_code == 403


def test_command_with_token_through_a_tunnel(client):
    r = client.post("/command", json=GOOD, headers={**TUNNEL, "x-stf-token": "s3cret-token"})
    assert r.status_code == 200
    r = client.post("/command", json=GOOD, headers={**TUNNEL, "x-stf-token": "wrong"})
    assert r.status_code == 403


def test_foreign_origin_cannot_command_localhost(client):
    """A malicious page in the operator's browser (CSRF to localhost)."""
    r = client.post("/command", json=GOOD, headers={**LOCAL, "origin": "https://evil.example"})
    assert r.status_code == 403


def test_dns_rebinding_name_is_not_local(client):
    r = client.post("/command", json=GOOD, headers={"host": "evil.example:8000"})
    assert r.status_code == 403


BAD = [{"op": "rm -rf"}, {"op": "retrieve", "slot": "Z9"}, {"op": "retrieve", "slot": "B2; drop"}]


@pytest.mark.parametrize("body", BAD)
def test_invalid_commands_rejected_at_the_boundary(client, body):
    assert client.post("/command", json=body, headers=LOCAL).status_code == 422


def test_rate_limit():
    lim = sec.RateLimiter(rate=1.0, burst=3)
    first = [lim.allow("a", now=0.0) for _ in range(4)]
    assert first == [True, True, True, False]
    assert lim.allow("a", now=1.5)
    assert lim.allow("b", now=0.0)  # per client


def test_ws_foreign_origin_closed(client):
    evil = {**LOCAL, "origin": "https://evil.example"}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers=evil) as ws:
            ws.receive_json()


def test_ws_own_origin_streams(client):
    own = {**LOCAL, "origin": "http://localhost:5173"}
    with client.websocket_connect("/ws", headers=own) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_host_parsing():
    assert all(sec.is_local(h) for h in ("localhost:8000", "127.0.0.1", "[::1]:8000"))
    assert not sec.is_local("localhost.evil.example") and not sec.is_local(None)


def test_spoofed_host_from_a_remote_peer_is_not_local(remote):
    """Host: localhost is the client's to write; a remote peer never gets the local shortcut."""
    assert remote.post("/command", json=GOOD, headers=LOCAL).status_code == 403


def test_forwarded_request_is_not_local(client):
    """Through a proxy (a non-loopback hop in X-Forwarded-For) a localhost Host is not local."""
    r = client.post("/command", json=GOOD, headers={**LOCAL, "x-forwarded-for": "198.51.100.9"})
    assert r.status_code == 403


def test_vite_dev_proxy_stays_local(client):
    """The local Vite proxy adds a loopback X-Forwarded-For: still the operator's machine."""
    r = client.post("/command", json=GOOD, headers={**LOCAL, "x-forwarded-for": "127.0.0.1"})
    assert r.status_code == 200


def _req(xff: str):
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": ("10.0.0.2", 1)})


def test_client_ip_behind_an_appending_proxy(monkeypatch):
    """Cloud Run's front end appends the real address; a spoofed entry to its left is ignored."""
    monkeypatch.setenv("STF_PROXY_HOPS", "1")
    assert sec.client_ip(_req("1.2.3.4, 203.0.113.7")) == "203.0.113.7"
    assert sec.client_ip(_req("203.0.113.7")) == "203.0.113.7"
    assert sec.client_ip(_req("")) == "10.0.0.2"


def test_client_ip_without_a_proxy_ignores_the_header(monkeypatch):
    """Strix's finding: reached directly, X-Forwarded-For is entirely client-written."""
    monkeypatch.delenv("STF_PROXY_HOPS", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert sec.client_ip(_req("1.2.3.4")) == "10.0.0.2"
    assert sec.client_ip(_req("1.2.3.4, 5.6.7.8")) == "10.0.0.2"


def test_cloud_run_defaults_to_one_hop(monkeypatch):
    monkeypatch.delenv("STF_PROXY_HOPS", raising=False)
    monkeypatch.setenv("K_SERVICE", "stf-live")
    assert sec.client_ip(_req("1.2.3.4, 203.0.113.7")) == "203.0.113.7"


def test_forged_forwarded_for_cannot_mint_guests(remote, monkeypatch):
    """Strix's PoC: a new X-Forwarded-For per request must not reset the guest limiter."""
    monkeypatch.delenv("STF_PROXY_HOPS", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    import services.api.app as appmod

    kept_before = appmod.guests.db.guests()
    for i in range(30):
        remote.get("/guest", headers={"x-forwarded-for": f"198.51.100.{i}"})
        remote.cookies.clear()
    # one client: the burst of 20 is kept, the rest are request-only guests
    assert appmod.guests.db.guests() - kept_before <= 20


def test_api_docs_are_off_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_oversized_body_is_refused_before_it_is_read(client):
    r = client.post(
        "/twin/state", content=b"{" + b" " * 100_000 + b"}",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413


def test_ngrok_origin_not_allowed_by_default(client):
    r = client.get("/health", headers={"origin": "https://attacker.ngrok-free.dev"})
    assert "access-control-allow-origin" not in r.headers
    r = client.get("/health", headers={"origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_notifier_has_a_service_wide_cap():
    from services.api.notify import Notifier

    n = Notifier({
        "STF_NOTIFY_WEBHOOK": "https://example.invalid/x", "STF_NOTIFY_MAX_PER_HOUR": "3"
    })
    fresh = [n._fresh(f"guest{i}") for i in range(10)]  # a new guest per request
    assert fresh.count(True) == 3


def test_page_fetcher_refuses_private_addresses():
    from services.api import tools as T
    from services.api import websearch as W

    for host in ("127.0.0.1", "0.0.0.0", "169.254.169.254", "10.1.2.3", "localhost"):
        assert not T._public_host(host)
        assert not W.public_url(f"http://{host}/")
    assert not W.public_url("file:///etc/passwd")


def test_placeholder_session_secret_is_not_used(tmp_path):
    from services.api import guests as G

    env = {"STF_DATA_DIR": str(tmp_path)}
    for weak in ("CHANGE_ME_64_HEX_CHARS", "short"):
        assert G._secret({**env, "STF_SESSION_SECRET": weak}) != weak.encode()
    strong = "a1" * 32
    assert G._secret({**env, "STF_SESSION_SECRET": strong}) == strong.encode()


def test_fetch_refuses_a_connection_that_lands_on_a_private_address():
    """DNS rebinding: whatever a name resolved to when checked, the connected socket decides."""
    import socket

    import pytest as _pytest

    from services.api import netguard as NG

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        with _pytest.raises(OSError):  # URLError is an OSError
            NG.opener.open(f"http://127.0.0.1:{port}/", timeout=3)
    finally:
        srv.close()


def test_watchdog_writes_need_same_site(client):
    """A scan or an ack is an unauthenticated state change: a foreign origin is refused
    (a browser attack), while a no-Origin caller (CLI, monitor) stays allowed."""
    evil = {"origin": "https://evil.example"}
    assert client.post("/watchdog/scan", headers=evil).status_code == 403
    assert client.post("/watchdog/incidents/no-such-id/ack", headers=evil).status_code == 403
    assert client.post("/watchdog/scan").status_code == 200


def test_watchdog_writes_are_rate_limited(client):
    """The burst is small: the fifth rapid write is refused, so a script cannot churn state."""
    codes = [client.post("/watchdog/scan").status_code for _ in range(6)]
    assert 429 in codes
