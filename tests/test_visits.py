"""Usage traction and log shipping (services/api/visits.py): nothing is stored without consent,
the IP is kept only shortened to its network and never sent anywhere, visits dedupe,
and the log handler batches without raising into the app. No network."""

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
    """Recording a visit makes no network call at all: any attempt fails the test's row."""
    monkeypatch.setattr(
        VIS.urllib.request, "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("no network in tests")),
    )


def test_declined_or_off_stores_nothing(tmp_path):
    v = VIS.Visits({}, store(tmp_path))
    assert v.record("g1", "overview", "8.8.8.8", "ua", consent=False) is False
    assert v.record("g1", "overview", "8.8.8.8", "ua", consent=True) is True
    assert len(v.store.visits("g1")) == 1
    off = VIS.Visits({"STF_TRACKING": "0"}, store(tmp_path / "b"))
    assert off.record("g1", "copilot", "8.8.8.8", "ua", consent=True) is False


def test_a_visit_row_holds_the_guest_page_and_the_shortened_ip(tmp_path, monkeypatch):
    v = VIS.Visits({}, store(tmp_path))
    called = []
    monkeypatch.setattr(VIS.urllib.request, "urlopen", lambda *a, **k: called.append(a))
    assert v.record("abc123", "copilot", "93.184.216.34", "Mozilla/5.0", consent=True, now=1000.0)
    rows = v.store.visits("abc123")
    assert len(rows) == 1
    r = rows[0]
    assert (r["guest"], r["page"], r["ip"], r["t"]) == ("abc123", "copilot", "93.184.216.0", 1000.0)
    assert set(r) == {"guest", "t", "page", "ip", "ua"}  # no place of any kind
    assert called == []  # the address went nowhere


def test_coarse_ip_keeps_only_the_network():
    assert VIS.coarse_ip("93.184.216.34") == "93.184.216.0"
    assert VIS.coarse_ip("2a00:1450:4001:82a::200e") == "2a00:1450:4001::"
    for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.20", "::1", "fe80::1"):
        assert VIS.coarse_ip(ip) == "local", ip
    assert VIS.coarse_ip("not-an-ip") is None and VIS.coarse_ip(None) is None


def test_old_visits_lapse_and_a_forgotten_guest_has_none(tmp_path):
    v = VIS.Visits({"STF_VISIT_DAYS": "1"}, store(tmp_path))
    assert v.record("old", "overview", None, None, consent=True, now=1000.0)
    assert v.record("new", "overview", None, None, consent=True, now=1000.0 + 86400 + 3601)
    assert v.store.visits("old") == [] and len(v.store.visits("new")) == 1
    v.forget("new")
    assert v.store.visits("new") == []


def test_visits_dedupe_within_ten_seconds(tmp_path):
    v = VIS.Visits({}, store(tmp_path))
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
    v = VIS.Visits({}, store(tmp_path))
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
