"""Owner visitor notifications (services/api/notify.py): off unless configured, one notice
per guest per throttle window, email and webhook failures degrade to a log line."""

import urllib.error

import pytest

pytest.importorskip("fastapi")
from services.api import notify as N  # noqa: E402

GEO = type("Geo", (), {"place": lambda self, ip: ("Germany", "Bavaria", "Munich", 48.1, 11.6)})()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def blocked(*a, **k):
        raise urllib.error.URLError("no network in tests")

    monkeypatch.setattr(N.urllib.request, "urlopen", blocked)

    class NoSmtp:
        def __init__(self, *a, **k):
            raise OSError("no network in tests")

    monkeypatch.setattr(N.smtplib, "SMTP_SSL", NoSmtp)


def env(**kw):
    base = {
        "STF_NOTIFY_EMAIL": "owner@example.com",
        "STF_SMTP_HOST": "smtp.example.com",
        "STF_SMTP_USER": "sender@example.com",
        "STF_SMTP_PASS": "secret",
    }
    base.update(kw)
    return base


def test_off_without_any_channel():
    n = N.Notifier({})
    assert not n.on
    assert n.visit("g1", "copilot", "8.8.8.8", "ua") is False


def test_off_when_email_address_missing_even_with_smtp():
    n = N.Notifier(env(STF_NOTIFY_EMAIL=""))
    assert not n.on


def test_one_notice_per_guest_per_window(monkeypatch):
    sent = []

    class FakeSmtp:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr(N.smtplib, "SMTP_SSL", FakeSmtp)
    n = N.Notifier(env(), geo=GEO)
    assert n.on
    assert n.visit("g1", "overview", "8.8.8.8", "Mozilla/5.0") is True
    assert len(sent) == 1
    msg = sent[0]
    assert msg["To"] == "owner@example.com"
    assert "Munich" in str(msg.get_content())
    assert "overview" in str(msg.get_content())
    # same guest again inside the window: throttled, no second email
    assert n.visit("g1", "copilot", "8.8.8.8", "Mozilla/5.0") is False
    assert len(sent) == 1
    # a different guest is a different notice
    assert n.visit("g2", "copilot", "9.9.9.9", None) is True
    assert len(sent) == 2


def test_window_expires_and_guest_notices_again(monkeypatch):
    clock = iter([1000.0, 1000.0 + 13 * 3600])

    class FakeSmtp:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def send_message(self, msg):
            pass

    monkeypatch.setattr(N.smtplib, "SMTP_SSL", FakeSmtp)
    n = N.Notifier(env(STF_NOTIFY_EVERY_HOURS="12"), geo=GEO, now=lambda: next(clock))
    assert n.visit("g1", "a", "1.1.1.1", None) is True
    assert n.visit("g1", "b", "1.1.1.1", None) is True  # 13 h later: fresh window


def test_smtp_failure_degrades_to_false_not_raise(monkeypatch):
    n = N.Notifier(env(), geo=GEO)
    # _no_network makes SMTP_SSL raise OSError -> warning logged, False returned
    assert n.visit("g1", "copilot", "8.8.8.8", None) is False


def test_webhook_channel_alone(monkeypatch):
    posted = []

    class FakeResp:
        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(r, timeout=None):
        posted.append((r.full_url, r.data))
        return FakeResp()

    monkeypatch.setattr(N.urllib.request, "urlopen", fake_urlopen)
    n = N.Notifier({"STF_NOTIFY_WEBHOOK": "https://ntfy.sh/stf-test"}, geo=GEO)
    assert n.on and not n.email_to
    assert n.visit("g1", "copilot", "8.8.8.8", None) is True
    assert len(posted) == 1
    url, body = posted[0]
    assert url == "https://ntfy.sh/stf-test"
    assert b"copilot" in body and b"Munich" in body


def test_private_ip_reports_no_place(monkeypatch):
    class FakeSmtp:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def send_message(self, msg):
            self.msg = msg

    monkeypatch.setattr(N.smtplib, "SMTP_SSL", FakeSmtp)
    local_geo = type("Geo", (), {"place": lambda self, ip: ("Local", "", "", None, None)})()
    n = N.Notifier(env(), geo=local_geo)
    assert n.visit("g1", "overview", "127.0.0.1", None) is True
