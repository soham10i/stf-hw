"""The live link between the 3D twin and the dashboard (services/api/livehub.py, WS /twin/live):
the twin's messages reach the visitor's dashboards and their commands reach the twin; each role
may send only its own kinds; one visitor never sees another's twin."""

import importlib
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from services.api import guests as G  # noqa: E402
from services.api.livehub import LiveHub  # noqa: E402


@pytest.fixture()
def app():
    import services.api.app as appmod

    appmod = importlib.reload(appmod)
    with TestClient(appmod.app, client=("127.0.0.1", 50000)) as c:
        yield appmod, c


def _cookie(appmod, gid: str) -> dict:
    return {"cookie": f"{G.COOKIE}={appmod.guests.sign(gid)}"}


def _next(ws, kind: str, tries: int = 6) -> dict:
    """The next message of a kind (the hub's peer counts come in between)."""
    for _ in range(tries):
        m = json.loads(ws.receive_text())
        if m.get("type") == kind:
            return m
    raise AssertionError(f"no {kind} message")


def test_twin_state_reaches_the_dashboard_and_commands_reach_the_twin(app):
    appmod, c = app
    h = _cookie(appmod, "a" * 32)
    with c.websocket_connect("/twin/live?role=twin", headers=h) as twin, \
            c.websocket_connect("/twin/live?role=dashboard", headers=h) as dash:
        twin.send_text(json.dumps({"type": "state", "running": True, "src": "t", "seq": 1}))
        got = _next(dash, "state")
        assert got["running"] is True
        dash.send_text(json.dumps({"type": "simulate", "broken": "cracked"}))
        assert _next(twin, "simulate")["broken"] == "cracked"


def test_a_late_dashboard_gets_the_last_state_at_once(app):
    appmod, c = app
    h = _cookie(appmod, "b" * 32)
    with c.websocket_connect("/twin/live?role=twin", headers=h) as twin:
        twin.send_text(json.dumps({"type": "state", "running": False, "seq": 7}))
        twin.send_text(json.dumps({"type": "hello"}))  # a round trip: the state is in
        with c.websocket_connect("/twin/live?role=dashboard", headers=h) as dash:
            assert _next(dash, "state")["seq"] == 7


def test_another_visitor_never_sees_the_twin(app):
    appmod, c = app
    with c.websocket_connect("/twin/live?role=twin", headers=_cookie(appmod, "c" * 32)) as twin, \
            c.websocket_connect("/twin/live?role=dashboard", headers=_cookie(appmod, "d" * 32)) as other:
        assert _next(other, "peers")["twins"] == 0  # its room has no twin
        twin.send_text(json.dumps({"type": "state", "running": True}))
        other.send_text(json.dumps({"type": "watch"}))  # nothing comes back to the other room
        assert json.loads(twin.receive_text())["type"] == "peers"


def test_roles_send_only_their_own_kinds():
    assert LiveHub.accepts("twin", json.dumps({"type": "state"}))
    assert LiveHub.accepts("dashboard", json.dumps({"type": "simulate"}))
    assert LiveHub.accepts("dashboard", json.dumps({"type": "state"})) is None  # no faking the twin
    assert LiveHub.accepts("twin", json.dumps({"type": "simulate"})) is None
    assert LiveHub.accepts("twin", "not json") is None
    assert LiveHub.accepts("twin", json.dumps({"type": "frame", "jpeg": "x" * 400_000})) is None


def test_unknown_role_is_refused(app):
    _, c = app
    with pytest.raises(Exception):
        with c.websocket_connect("/twin/live?role=admin") as ws:
            ws.receive_text()
