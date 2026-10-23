"""The live link between the 3D twin and the dashboard (services/api/livehub.py, WS /twin/live):
the twin's messages reach the visitor's dashboards and their commands reach the twin; each role
may send only its own kinds; one visitor never sees another's twin."""

import importlib
import json
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from services.api import guests as G  # noqa: E402
from services.api import livehub as LH  # noqa: E402
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
            c.websocket_connect(
                "/twin/live?role=dashboard", headers=_cookie(appmod, "d" * 32)
            ) as other:
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
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/twin/live?role=admin") as ws:
            ws.receive_text()


# ---- the abuse limits (docs/SECURITY_FINDINGS.md F1-F4, F8) ----


@pytest.fixture()
def appmod(monkeypatch):
    monkeypatch.setenv("STF_API_TOKEN", "s3cret-token")
    monkeypatch.setenv("STF_LIVE_PER_CLIENT", "3")
    import services.api.app as m

    return importlib.reload(m)


def _visitor(appmod, ip="203.0.113.7"):
    """A browser on its own address that has loaded a page (GET /guest issues its cookie)."""
    c = TestClient(appmod.app, client=(ip, 50000))
    assert c.get("/guest").status_code == 200
    return c


def test_a_socket_without_a_guest_cookie_is_refused(appmod):
    """No falling back to the address: people behind one NAT must not share a room."""
    with TestClient(appmod.app, client=("203.0.113.7", 50000)) as c:
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect("/twin/live?role=dashboard") as ws:
                ws.receive_text()
        assert e.value.code == 1008


def test_two_guests_on_one_address_never_share_a_room(appmod):
    a, b = _visitor(appmod), _visitor(appmod)  # same address, different guests
    with a.websocket_connect("/twin/live?role=twin") as twin_a, \
            b.websocket_connect("/twin/live?role=dashboard") as dash_b:
        assert twin_a.receive_json()["type"] == "peers"
        assert dash_b.receive_json() == {"type": "peers", "twins": 0, "dashboards": 1}
        # each guest is alone in a room of its own: a's twin cannot reach b's dashboard
        assert len(appmod.hub.rooms) == 2
        assert all(len(r.conns) == 1 for r in appmod.hub.rooms.values())


def test_one_address_may_hold_only_a_few_live_sockets(appmod):
    v = _visitor(appmod)
    opened = []
    try:
        for _ in range(3):  # STF_LIVE_PER_CLIENT
            ws = v.websocket_connect("/twin/live?role=dashboard").__enter__()
            ws.receive_json()
            opened.append(ws)
        with pytest.raises(WebSocketDisconnect) as e:
            with v.websocket_connect("/twin/live?role=dashboard") as ws:
                ws.receive_text()
        assert e.value.code == 1013
    finally:
        for ws in opened:
            ws.__exit__(None, None, None)


def test_a_room_takes_a_bounded_number_of_twins_and_dashboards():
    hub = LH.LiveHub()
    twins = [hub.join("g", object(), "twin") for _ in range(LH.MAX_TWINS + 1)]
    dashes = [hub.join("g", object(), "dashboard") for _ in range(LH.MAX_DASHBOARDS + 1)]
    assert twins[-1] is None and all(twins[:-1])
    assert dashes[-1] is None and all(dashes[:-1])


def test_the_room_relay_budget_drops_a_flood():
    room = LH._Room()
    big = 300_000
    sent = sum(room.take(big) for _ in range(40))  # 12 MB at once
    assert sent * big <= LH.ROOM_BYTES_PER_S * LH.BURST_S
    room.at -= 1.0  # a second later the budget has refilled by one second's worth
    assert room.take(big)


def test_uvicorn_refuses_huge_websocket_frames():
    """Frames above the largest live-link message are refused before they are buffered."""
    import pathlib

    cmd = pathlib.Path(__file__).resolve().parents[1].joinpath("Dockerfile").read_text()
    assert "--ws-max-size 400000" in cmd
    assert LH.MAX_MSG < 400_000


def test_the_operator_status_is_not_public(appmod):
    with TestClient(appmod.app, client=("203.0.113.7", 50000)) as c:
        assert c.get("/admin/status").status_code == 403
        assert "rejected" not in c.get("/health").json()
        r = c.get("/admin/status", headers={"x-stf-token": "s3cret-token"})
        assert r.status_code == 200 and "rejected" in r.json()


def test_daily_caps_are_shared_across_instances(tmp_path):
    """Two instances (or one restarted) count against one day total (usage.py)."""
    from services.api import token_budget as TB
    from services.api import usage as U
    from services.api.chat import DailyCap

    store = U.SqliteUsage(str(tmp_path / "u.db"))
    a, b = U.Shared(store), U.Shared(store)
    cap_a = DailyCap(3, shared=a, name="chat:questions")
    assert cap_a.take() and cap_a.take() and cap_a.take() and not cap_a.take()
    a._pool.shutdown(wait=True)

    cap_b = DailyCap(3, shared=b, name="chat:questions")  # a fresh instance
    b.total(time.strftime("%Y-%m-%d", time.gmtime()), "chat:questions")  # first read
    b._pool.shutdown(wait=True)
    assert not cap_b.take()  # the day's 3 were already used elsewhere

    budget = TB.TokenBudget(TB.Limits(day=1000), shared=U.Shared(store), name="gemini:cloud")
    budget.record(900)
    budget.shared._pool.shutdown(wait=True)
    fresh = TB.TokenBudget(TB.Limits(day=1000), shared=U.Shared(store), name="gemini:cloud")
    fresh.left()  # triggers the first read
    fresh.shared._pool.shutdown(wait=True)
    assert fresh.left()["day"] == 100
