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
    with TestClient(appmod.app) as c:
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
    assert lim.allow("b", now=0.0)                 # per client


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
