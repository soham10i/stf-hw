"""The notify endpoints (app.py /notify/status, /notify/test): status is open and
secret-free, the test send is operator-guarded like /command, and an unconfigured
service answers 409, not an exception."""

import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from services.api import notify as N  # noqa: E402

LOCAL = {"host": "localhost:8000"}
TUNNEL = {"host": "example.ngrok-free.dev"}
ENV = {
    "STF_NOTIFY_EMAIL": "owner@example.com",
    "STF_SMTP_HOST": "smtp.example.com",
    "STF_SMTP_USER": "sender@example.com",
    "STF_SMTP_PASS": "secret",
}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("STF_API_TOKEN", "s3cret-token")
    monkeypatch.setenv("STF_NOTIFY_LOCAL", "")  # deterministic: the dev-machine guard stays off
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)

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
    import services.api.app as appmod

    appmod = importlib.reload(appmod)
    with TestClient(appmod.app, client=("127.0.0.1", 50000)) as c:
        c.sent = sent  # type: ignore[attr-defined]
        yield c


def test_status_is_open_and_secret_free(client):
    r = client.get("/notify/status", headers=TUNNEL)
    assert r.status_code == 200
    body = r.json()
    assert body["on"] is True
    assert "email" in " ".join(body["channels"])
    assert "every_hours" in body and body["every_hours"] > 0
    assert "pass" not in r.text.lower() or "smtp.example.com" not in r.text
    assert "secret" not in r.text


def test_localhost_refuses_unless_armed(client, monkeypatch):
    # a configured local run must not email the owner: localhost refuses, sends nothing
    r = client.post("/notify/test", headers=LOCAL)
    assert r.status_code == 409
    assert "local address" in r.json()["error"]
    assert len(client.sent) == 0  # type: ignore[attr-defined]

    # armed explicitly (STF_NOTIFY_LOCAL=1), a local test send works - the button's path
    monkeypatch.setenv("STF_NOTIFY_LOCAL", "1")
    import services.api.app as appmod

    appmod = importlib.reload(appmod)
    with TestClient(appmod.app, client=("127.0.0.1", 50000)) as armed:
        ok = armed.post("/notify/test", headers=LOCAL)
        assert ok.status_code == 200
        assert ok.json()["sent"] is True
        assert len(client.sent) == 1  # type: ignore[attr-defined]
        assert "test" in client.sent[0]["Subject"].lower()  # type: ignore[attr-defined]


def test_test_notice_through_tunnel_needs_token(client):
    assert client.post("/notify/test", headers=TUNNEL).status_code == 403
    ok = client.post("/notify/test", headers={**TUNNEL, "x-stf-token": "s3cret-token"})
    assert ok.status_code == 200
    wrong = client.post("/notify/test", headers={**TUNNEL, "x-stf-token": "wrong"})
    assert wrong.status_code == 403


def test_unconfigured_service_says_so(monkeypatch):
    # blank rather than del: the app's env is {**dotenv(), **os.environ}, so an empty
    # string in os.environ must shadow a real .env file's values
    for k in ENV:
        monkeypatch.setenv(k, "")
    import services.api.app as appmod

    appmod = importlib.reload(appmod)
    with TestClient(appmod.app, client=("127.0.0.1", 50000)) as c:
        assert c.get("/notify/status").json()["on"] is False
        r = c.post("/notify/test", headers=LOCAL)
        assert r.status_code == 409
        assert "not configured" in r.json()["error"]


def test_guest_session_load_notifies_owner(client):
    r = client.get("/guest?page=twin")
    assert r.status_code == 200
    data = r.json()
    assert "session_id" in data and data["session_id"]
    sess_id = data["session_id"]
    assert len(client.sent) == 1  # type: ignore[attr-defined]
    mail = client.sent[0]  # type: ignore[attr-defined]
    body = str(mail.get_content())
    assert f"session {sess_id}" in body
    assert "twin" in body
    assert sess_id[:8] in mail["Subject"]

    # Subsequent visit by same guest is throttled (no duplicate email)
    r2 = client.get("/guest?page=twin")
    assert r2.status_code == 200
    assert len(client.sent) == 1  # type: ignore[attr-defined]
