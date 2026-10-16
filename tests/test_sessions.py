"""Sessions and the context store (sessions.py, store.py): a conversation keeps its turns and the
facts the tools established, and any model that answers next gets them - Gemini, the next Gemini
model, the local model. History is per user. Styles shape the answer (respond.py). No network."""

import asyncio
import io
import json
import urllib.error

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

from services.api import chat as C  # noqa: E402
from services.api import respond as R  # noqa: E402
from services.api import security as sec  # noqa: E402
from services.api.store import JsonStore  # noqa: E402

KEY = "test-key-not-real"
USER = "user-abcdef12"


def req(user=USER):
    h = [(b"host", b"localhost:8000")] + ([(b"x-stf-user", user.encode())] if user else [])
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat",
        "headers": h,
        "client": ("127.0.0.1", 5000),
    }
    return Request(scope)


def make(tmp_path, ollama=None):
    chat = C.Chat(
        sec.Settings.from_env(),
        C.ChatSettings(key=KEY, model="g1", daily_limit=100, models=["g2"], ollama_model=ollama),
        store=JsonStore(str(tmp_path)),
    )
    chat.limiter = sec.RateLimiter(rate=1000, burst=1000)
    sent = []

    def fake(url, k, body):
        model = url.split("/models/")[1].split(":")[0]
        sent.append(("gemini", model, json.loads(json.dumps(body))))
        text = "The HBW belt needs attention [condition-monitoring model]."
        return {"candidates": [{"content": {"parts": [{"text": text}]}}]}

    chat.post = fake
    return chat, sent


def ask(chat, q, **kw):
    user = kw.pop("user", USER)
    return asyncio.run(chat.ask(C.ChatRequest(question=q, **kw), req(user)))


def last_prompt(sent):
    who, _, body = sent[-1]
    if who == "gemini":
        return body["contents"][-1]["parts"][0]["text"]
    return body["messages"][-1]["content"]


def test_a_session_keeps_turns_and_facts(tmp_path):
    chat, sent = make(tmp_path)
    a = ask(chat, "what needs service first?")
    sid = a["session"]["id"]
    assert a["session"]["title"] == "what needs service first?" and a["session"]["facts"] > 0
    b = ask(chat, "and how long does it have?", session_id=sid)
    assert b["session"]["id"] == sid
    p = last_prompt(sent)
    assert "Established earlier in this session" in p and "HBW belt" in p
    roles = [c["role"] for c in sent[-1][2]["contents"]]
    assert roles[:2] == ["user", "model"], "the earlier turn is the model's history"
    doc = chat.session(req(), sid)
    assert [t["role"] for t in doc["turns"]] == ["user", "assistant", "user", "assistant"]


def test_the_local_model_gets_the_same_context_when_gemini_is_out(tmp_path):
    chat, sent = make(tmp_path, ollama="qwen")
    sid = ask(chat, "what needs service first?")["session"]["id"]

    def busy(url, k, body):
        err = {"error": {"details": [{"retryDelay": "60s"}]}}
        raise urllib.error.HTTPError("x", 429, "q", {}, io.BytesIO(json.dumps(err).encode()))

    chat.post = busy
    chat._ollama_alive = lambda: True

    def ollama(url, body):
        sent.append(("ollama", "qwen", json.loads(json.dumps(body))))
        return {"message": {"content": "Still the HBW belt [condition-monitoring model]."}}

    chat.post_ollama = ollama
    out = ask(chat, "remind me which part it was", session_id=sid)
    assert out["model"] == "qwen" and out["session"]["id"] == sid
    assert "HBW belt" in last_prompt(sent), "the context store travels to the next model"
    assert any(s["from"] in ("g1", "g2", "Gemini") for s in out["switched"])
    assert out["session"]["models"] == ["g1", "qwen"]


def test_the_local_tab_falls_back_to_gemini(tmp_path):
    chat, sent = make(tmp_path, ollama="qwen")
    chat._ollama_alive = lambda: False
    out = ask(chat, "what is the OEE?", provider="ollama")
    assert out["model"] == "g1" and out["switched"][0]["why"] == "not running"


def test_history_is_listed_opened_and_deleted_per_user(tmp_path):
    chat, _ = make(tmp_path)
    sid = ask(chat, "what is the OEE?")["session"]["id"]
    ask(chat, "what needs service first?")
    lst = chat.sessions(req())
    assert len(lst) == 2 and {"title", "updated", "n_turns"} <= set(lst[0])
    assert chat.sessions(req("someone-else-1")) == [], "another user sees nothing"
    with pytest.raises(HTTPException):
        chat.session(req("someone-else-1"), sid)
    assert chat.forget(req(), sid) == {"deleted": True} and len(chat.sessions(req())) == 1


def test_without_a_user_nothing_is_stored(tmp_path):
    chat, _ = make(tmp_path)
    out = asyncio.run(chat.ask(C.ChatRequest(question="what is the OEE?"), req(user=None)))
    assert "session" not in out and not list(tmp_path.iterdir())


def test_styles_follow_the_kind_of_question():
    assert R.classify("hi") == "greeting"
    assert R.classify("compare the belt and the spindle wear") == "compare"
    assert R.classify("the HMI shows VGR-V01, what now?") == "steps"
    assert R.classify("is the oven hot right now?") == "status"
    assert R.classify("how does the oven heat the cookies?") == "explain"
    assert R.classify("what is the OEE?") == "quick"
    assert "markdown table" in R.instruction("compare")


def test_the_answer_says_its_style(tmp_path):
    chat, sent = make(tmp_path)
    out = ask(chat, "compare the belt and the spindle wear")
    assert out["style"] == "compare" and "FORMAT (compare)" in last_prompt(sent)
    assert out["facts"], "key figures for the card"
