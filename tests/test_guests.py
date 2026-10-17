"""Guest sessions (services/api/guests.py): every visitor is a guest of their own, issued by the
server in a signed cookie; a guest's copilot sessions and photos are theirs alone, whatever the
browser claims; DELETE /guest forgets them. Against the app, with its database in a temp dir."""

import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from services.api import guests as G  # noqa: E402
from services.api import sessions as S  # noqa: E402
from tests.test_captures import jpeg  # noqa: E402


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("STF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STF_DB", "sqlite")
    monkeypatch.setenv("STF_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("STF_CAPTURES", "1")
    import services.api.app as appmod

    appmod = importlib.reload(appmod)
    from services.api import captures as C

    appmod.captures.store = C.LocalCaptures(str(tmp_path))
    return appmod


def visitor(appmod):
    return TestClient(appmod.app, base_url="http://localhost:8000")


def test_each_visitor_is_issued_a_guest_of_their_own(app):
    a, b = visitor(app), visitor(app)
    ra = a.get("/guest")
    cookie = ra.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Path=/" in cookie
    ga, gb = ra.json()["guest"], b.get("/guest").json()["guest"]
    assert ga and gb and ga != gb
    assert a.get("/guest").json()["guest"] == ga          # the cookie keeps it
    assert "set-cookie" not in a.get("/guest").headers     # and it is not reissued
    assert app.guests.db.guests() == 2
    assert a.get("/guest").json()["database"] == "sqlite"


def test_a_forged_cookie_is_a_new_guest():
    g = G.Guests({"STF_SESSION_SECRET": "x"}, db=_Mem())
    real, _ = g.resolve(None, "1.2.3.4")
    assert g.verify(g.sign(real)) == real
    assert g.verify(real + "." + "0" * 32) is None
    assert g.verify("../../etc." + "0" * 32) is None
    other, new = g.resolve(real + ".forged", "1.2.3.4")
    assert new and other != real


def test_a_guest_sees_only_their_own_copilot_sessions_whatever_the_browser_claims(app):
    a, b = visitor(app), visitor(app)
    ga = a.get("/guest").cookies.get(G.COOKIE) or a.cookies.get(G.COOKIE)
    gid = app.guests.verify(ga)
    s = S.new("overview")
    S.add_turn(s, "user", "what is the OEE?")
    S.save(app.chat.store, gid, s)
    assert len(a.get("/copilot/sessions").json()["sessions"]) == 1
    b.get("/guest")
    # b claims a's id in the old header: the server's guest wins
    assert b.get("/copilot/sessions", headers={"X-STF-User": gid}).json()["sessions"] == []
    other = b.get(f"/copilot/sessions/{s['id']}", headers={"X-STF-User": gid}).json()
    assert other.get("turns") in (None, [])


def test_photos_are_the_guests_and_forgetting_takes_them_all(app):
    a, b = visitor(app), visitor(app)
    jpg = {"content-type": "image/jpeg"}
    up = a.post("/vision/captures?flavour=vanilla&n=1", content=jpeg(), headers=jpg)
    assert up.status_code == 200, up.text
    pid = up.json()["id"]
    assert [r["id"] for r in a.get("/vision/captures").json()["captures"]] == [pid]
    assert a.get(f"/vision/captures/{pid}.jpg").status_code == 200
    assert b.get("/vision/captures").json()["captures"] == []
    assert b.get(f"/vision/captures/{pid}.jpg").status_code == 404
    gid = app.guests.verify(a.cookies.get(G.COOKIE))
    r = a.delete("/guest")
    assert r.json() == {"forgotten": True} and "Max-Age=0" in r.headers["set-cookie"]
    assert app.guests.db.guest(gid) is None
    assert app.captures.store.list(10, gid) == []


class _Mem:
    """A database in a dict, for the cookie tests."""

    name = "memory"

    def __init__(self):
        self.g = {}

    def guest(self, id):
        return self.g.get(id)

    def add_guest(self, id, now):
        self.g[id] = {"id": id, "created": now, "last_seen": now, "visits": 1}

    def touch(self, id, now):
        self.g[id]["last_seen"] = now

    def lapse(self, before):
        return 0
