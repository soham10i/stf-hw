"""The Vertex AI lane: the trial credit's endpoint, a bearer token instead of a key, and a
missing token handing the question to the next lane instead of failing it."""

from __future__ import annotations

import io
import urllib.error

import pytest

pytest.importorskip("fastapi")

from services.api import chat as C  # noqa: E402
from services.api import gcp_auth as GA  # noqa: E402
from services.api import security as sec  # noqa: E402

from .test_gemini_search import PLAIN  # noqa: E402
from .test_orchestrate import ask  # noqa: E402


def with_vertex(monkeypatch, token="tok-1"):
    """The AI Studio key (g-key) and a Vertex project: Vertex is asked first."""
    if token:
        monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", token)
    else:
        monkeypatch.delenv("GOOGLE_OAUTH_ACCESS_TOKEN", raising=False)
        monkeypatch.setattr(GA, "TOKENS", GA.Tokens(sources=()))
    chat = C.Chat(
        sec.Settings.from_env(),
        C.ChatSettings(
            key="g-key",
            model="gemini-test",
            daily_limit=100,
            vertex_project="stf-demo",
            vertex_location="global",
        ),
    )
    chat.c.ollama_model = None
    return chat


def test_endpoint_global_and_regional():
    assert GA.endpoint("p", "global", "gemini-3.8-flash") == (
        "https://aiplatform.googleapis.com/v1/projects/p/locations/global"
        "/publishers/google/models/gemini-3.8-flash:generateContent"
    )
    assert GA.endpoint("p", "europe-west1", "m").startswith(
        "https://europe-west1-aiplatform.googleapis.com/v1/projects/p/locations/europe-west1/"
    )


def test_the_vertex_lane_is_asked_first_with_a_bearer_token(monkeypatch):
    chat, calls = with_vertex(monkeypatch), []

    def fake(url, key, body):
        calls.append((url, key))
        return PLAIN

    chat.post = fake
    out = ask(chat, {"question": "which part needs service first?"})
    url, key = calls[0]
    assert "aiplatform.googleapis.com/v1/projects/stf-demo/locations/global" in url
    assert key == "Bearer tok-1" and out["answer"].startswith("The belt")
    assert chat.cloud.label == "Vertex AI" and chat.cloud.budget.used == 700
    assert chat.cap.limit == 2000  # billed: the daily question cap is lifted as for a cloud key


def test_no_token_hands_over_to_ai_studio(monkeypatch):
    chat, keys = with_vertex(monkeypatch, token=None), []

    def fake(url, key, body):
        keys.append(key)
        return PLAIN

    chat.post = fake
    out = ask(chat, {"question": "which part needs service first?"})
    assert keys == ["g-key"] and out["answer"].startswith("The belt")
    assert chat.status()["search"]["lanes"][0]["refused"]  # rests, not asked on every question


def test_post_sends_a_bearer_token_as_authorization(monkeypatch):
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen.update(req.headers)
        return Resp(b"{}")

    monkeypatch.setattr(C.urllib.request, "urlopen", urlopen)
    C._post("https://aiplatform.googleapis.com/x", "Bearer t", {})
    assert seen.get("Authorization") == "Bearer t" and "X-goog-api-key" not in seen
    C._post("https://generativelanguage.googleapis.com/x", "g-key", {})
    assert seen.get("X-goog-api-key") == "g-key"


def test_tokens_are_cached_until_shortly_before_they_expire(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_ACCESS_TOKEN", raising=False)
    now, n = [0.0], [0]

    def source():
        n[0] += 1
        return f"t{n[0]}", 3600.0

    def broken():
        raise urllib.error.URLError("no metadata server")

    tokens = GA.Tokens(sources=(broken, source), clock=lambda: now[0])
    assert tokens.get() == "t1" and tokens.get() == "t1"
    now[0] = 3600 - GA.EARLY_S + 1  # inside the renewal margin
    assert tokens.get() == "t2"
    with pytest.raises(GA.NoToken, match="metadata"):
        GA.Tokens(sources=(broken,)).get()
