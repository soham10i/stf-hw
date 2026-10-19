"""Usage traction and log shipping (services/api/visits.py): nothing is stored without consent,
a private IP is never looked up, the geo cache keeps one query per neighbourhood, visits dedupe,
and the log handler batches without raising into the app. No network."""

import json
import logging
import sqlite3
import urllib.error

import pytest

pytest.importorskip("fastapi")
from services.api import visits as VIS  # noqa: E402


def store(tmp_path):
    return VIS.SqliteVisits(str(tmp_path / "v.db"))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test may touch the geo API: the default Geo resolves everything as unreachable."""
    monkeypatch.setattr(
        VIS.urllib.request, "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("no network in tests")),
    )


def test_declined_or_off_stores_nothing(tmp_path):
    v = VIS.Visits({}, store(tmp_path), geo=VIS.Geo())
    assert v.record("g1", "overview", "8.8.8.8", "ua", consent=False) is False
    assert v.record("g1", "overview", "8.8.8.8", "ua", consent=True) is True
    assert len(v.store.visits("g1")) == 1
    off = VIS.Visits({"STF_TRACKING": "0"}, store(tmp_path / "b"), geo=VIS.Geo())
    assert off.record("g1", "copilot", "8.8.8.8", "ua", consent=True) is False


def test_a_visit_row_holds_the_guest_page_ip_and_place(tmp_path, monkeypatch):
    v = VIS.Visits({}, store(tmp_path), geo=VIS.Geo())
    seen = []

    def fake_place(ip):
        seen.append(ip)
        return ("Germany", "Bavaria", "Munich", 48.1, 11.6)

    monkeypatch.setattr(v.geo, "place", fake_place)
    assert v.record("abc123", "copilot", "8.8.8.8", "Mozilla/5.0", consent=True, now=1000.0)
    rows = v.store.visits("abc123")
    assert len(rows) == 1
    r = rows[0]
    assert (r["guest"], r["page"], r["ip"]) == ("abc123", "copilot", "8.8.8.8")
    assert (r["country"], r["region"], r["city"]) == ("Germany", "Bavaria", "Munich")
    assert (r["lat"], r["lon"]) == (48.1, 11.6) and r["t"] == 1000.0
    assert seen == ["8.8.8.8"]


def test_private_and_loopback_ips_never_leave_the_machine(tmp_path, monkeypatch):
    v = VIS.Visits({}, store(tmp_path), geo=VIS.Geo())
    called = []
    monkeypatch.setattr(
        VIS.urllib.request, "urlopen", lambda *a, **k: called.append(a) or None
    )
    for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.20", "::1", "fe80::1"):
        assert v.geo.place(ip) == ("Local", "", "", None, None), ip
    assert called == []  # no lookup was even attempted


def test_geo_caches_by_prefix_for_a_day(tmp_path, monkeypatch):
    g = VIS.Geo()
    calls = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            calls.append(1)
            return json.dumps(
                {"status": "success", "country": "France", "region": "IDF",
                 "city": "Paris", "lat": 48.8, "lon": 2.3}
            ).encode()

    monkeypatch.setattr(VIS.urllib.request, "urlopen", lambda *a, **k: Resp())
    first = g.place("8.8.8.8")
    assert first[0] == "France" and len(calls) == 1
    assert g.place("8.8.8.4") == first  # same /24: served from the cache
    assert len(calls) == 1
    g.place("1.1.1.1")  # another neighbourhood: one more lookup (the mock answers the same)
    assert len(calls) == 2
    assert g.place("not-an-ip") is None
    off = VIS.Geo(on=False)
    assert off.place("8.8.8.8") is None


def test_visits_dedupe_within_ten_seconds(tmp_path):
    v = VIS.Visits({}, store(tmp_path), geo=VIS.Geo())
    assert v.record("g", "overview", None, None, consent=True, now=100.0)
    assert not v.record("g", "overview", None, None, consent=True, now=105.0)
    assert v.record("g", "copilot", None, None, consent=True, now=105.0)
    assert v.record("g", "overview", None, None, consent=True, now=111.0)
    assert [r["page"] for r in reversed(v.store.visits("g"))] == [
        "overview",
        "copilot",
        "overview",
    ]


def test_a_store_failure_does_not_raise(tmp_path, monkeypatch):
    v = VIS.Visits({}, store(tmp_path), geo=VIS.Geo())
    monkeypatch.setattr(
        v.store, "add_visit",
        lambda row: (_ for _ in ()).throw(sqlite3.Error("disk full")),
    )
    assert v.record("g", "overview", None, None, consent=True) is True  # logged, not raised


def test_the_log_handler_batches_and_ships(tmp_path):
    s = store(tmp_path)
    h = VIS.SupabaseLogHandler(s, flush_s=60.0)
    h.setFormatter(logging.Formatter("%(message)s"))
    lg = logging.getLogger("test.visits")
    lg.addHandler(h)
    lg.setLevel(logging.WARNING)
    lg.warning("something odd %d", 1)
    lg.info("below the handler's level: never shipped")
    assert s.visits("nobody") == []
    rows = s._db.execute("SELECT level, logger, message FROM app_logs").fetchall()
    assert rows == []  # not yet: the batch flushes on size or on flush()
    h.flush()
    rows = s._db.execute("SELECT level, logger, message FROM app_logs").fetchall()
    assert rows == [("WARNING", "test.visits", "something odd 1")]
    # a full batch flushes on its own
    for i in range(VIS.BATCH):
        lg.warning("row %d", i)
    n = s._db.execute("SELECT COUNT(*) FROM app_logs").fetchone()[0]
    assert n == 1 + VIS.BATCH
    lg.removeHandler(h)
    h.close()


def test_the_log_handler_never_raises_into_the_app(tmp_path, monkeypatch):
    s = store(tmp_path)
    monkeypatch.setattr(
        s, "add_logs", lambda rows: (_ for _ in ()).throw(urllib.error.URLError("down"))
    )
    h = VIS.SupabaseLogHandler(s, flush_s=60.0)
    lg = logging.getLogger("test.visits.raise")
    lg.addHandler(h)
    lg.propagate = False
    lg.error("still fine")  # must not raise
    h.flush()
    lg.removeHandler(h)
    h.close()


def test_consent_cookie_shape():
    c = VIS.consent_cookie("accepted", 180, secure=True)
    assert c.startswith("stf_consent=accepted; Path=/; Max-Age=15552000; SameSite=Lax; Secure")
    c = VIS.consent_cookie("declined", 180, secure=False)
    assert "Secure" not in c
