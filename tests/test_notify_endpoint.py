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
    with TestClient(appmod.app) as c:
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


def test_test_notice_from_localhost(client):
    r = client.post("/notify/test", headers=LOCAL)
    assert r.status_code == 200
    assert r.json()["sent"] is True
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
    with TestClient(appmod.app) as c:
        assert c.get("/notify/status").json()["on"] is False
        r = c.post("/notify/test", headers=LOCAL)
        assert r.status_code == 409
        assert "not configured" in r.json()["error"]
