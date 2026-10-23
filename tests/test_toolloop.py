"""The one tool loop (toolloop.py) and the verify node (agent.verify): every provider asks for a
tool and gets its result back in its own API's words; an answer with a number nothing backs is
sent back once to the model that wrote it, on both engines; a failed or impossible correction
leaves the first answer standing, flagged."""

from __future__ import annotations

import asyncio
import io
import urllib.error

import pytest

pytest.importorskip("fastapi")

from services.api import chat as C  # noqa: E402
from services.api import security as sec  # noqa: E402
from services.api import toolloop as TL  # noqa: E402
from services.api import tools as T  # noqa: E402

from .test_agent import shape  # noqa: E402
from .test_chat import req  # noqa: E402

GOOD = "The belt warns in 0.6 shifts."  # 0.6 is in machine_health's result
BAD = "The belt warns in 7.7 shifts."  # 7.7 is in no evidence


def make(**kw):
    c = C.ChatSettings(**{"key": None, "model": "gemini-test", "daily_limit": 100, **kw})
    chat = C.Chat(sec.Settings.from_env(), c)
    if "ollama_model" not in kw:
        chat.c.ollama_model = None
    return chat


def completion(text=None, call=None, cid="t1"):
    msg = {"content": text or ""}
    if call:
        msg["tool_calls"] = [
            {"id": cid, "function": {"name": call, "arguments": '{"parts": ["hbw_belt"]}'}}
        ]
    return {"choices": [{"message": msg}]}


def gemini(text=None, call=None):
    part = {"functionCall": {"name": call, "args": {}}} if call else {"text": text}
    return {"candidates": [{"content": {"role": "model", "parts": [part]}}]}


def ollama(text=None, call=None):
    msg = {"role": "assistant", "content": text or ""}
    if call:
        msg["tool_calls"] = [{"function": {"name": call, "arguments": {}}}]
    return {"message": msg}


def ask(chat, body, engine, monkeypatch, events=None):
    monkeypatch.setenv("STF_AGENT", engine)
    emit = (lambda k, t: events.append((k, t))) if events is not None else None
    return asyncio.run(chat.ask(C.ChatRequest(**body), req(), emit=emit))


# ------------------------------------------------------------------ the loop, per provider
PROVIDERS = {
    "gemini": (dict(key="g-key"), "post", gemini),
    "groq": (dict(groq_key="gsk", groq_model="openai/gpt-oss-120b",
                  groq_models=["openai/gpt-oss-120b"]), "post_groq", completion),
    "upb": (dict(upb_key="u-key"), "post_groq", completion),
    "openai": (dict(openai_url="https://llm.example.test/v1"), "post_groq", completion),
    "ollama": (dict(ollama_model="qwen"), "post_ollama", ollama),
}


@pytest.mark.parametrize("prov", list(PROVIDERS))
def test_each_provider_calls_a_tool_and_answers_through_the_one_loop(prov):
    kw, attr, reply = PROVIDERS[prov]
    chat, bodies = make(**kw), []

    def fake(*a):
        body = a[-1]
        bodies.append(body)
        return reply(call="machine_health") if len(bodies) == 1 else reply(text=GOOD)

    setattr(chat, attr, fake)
    events, results, called = [], [], []
    meta = {"emit": lambda k, t: events.append((k, t))}
    c = chat.conversation(prov, C.ChatRequest(question="belt?"), T.Ctx(), results, called, meta)
    assert c.run() == GOOD
    assert called == ["machine_health"] and ("step", "called machine health") in events
    sent = bodies[-1]
    if prov == "gemini":
        assert "functionResponse" in sent["contents"][-1]["parts"][0]
    else:
        tool = sent["messages"][-1]
        assert tool["role"] == "tool" and "machine" in tool["content"].lower()
        if prov != "ollama":
            assert tool["tool_call_id"] == "t1"


def test_the_rounds_run_out_then_one_answer_without_tools():
    chat, bodies = make(key="g-key"), []

    def fake(url, key, body):
        bodies.append(dict(body))
        return gemini(text=BAD) if "tools" not in body else gemini(call="machine_health")

    chat.post = fake
    c = chat.conversation("gemini", C.ChatRequest(question="belt?"), T.Ctx(), [], [], {})
    assert c.run() == BAD and c.final and len(bodies) == C.MAX_ROUNDS + 2
    assert not c.correct(["7.7"])  # the final answer is not sent back


def test_an_unknown_tools_arguments_are_empty_not_an_error():
    assert TL._args("{not json") == {} and TL._args('{"a": 1}') == {"a": 1}
    assert TL._args(["x"]) == {}


# ------------------------------------------------------------------ the verify node
def groq_chat(script):
    chat = make(groq_key="gsk", groq_model="openai/gpt-oss-120b",
                groq_models=["openai/gpt-oss-120b"])
    sent = []

    def fake(url, key, body):
        sent.append([m.get("content") for m in body["messages"]])
        step = script[min(len(sent), len(script)) - 1]
        if isinstance(step, Exception):
            raise step
        return completion(text=step)

    chat.post_groq = fake
    return chat, sent


@pytest.mark.parametrize("engine", ["graph", "linear"])
def test_an_unbacked_number_is_sent_back_once_and_corrected(engine, monkeypatch):
    chat, sent = groq_chat([BAD, GOOD])
    events = []
    out = ask(chat, {"question": "which part needs service first?"}, engine, monkeypatch, events)
    assert out["answer"] == GOOD and not out.get("unverified") and len(sent) == 2
    assert "7.7" in sent[1][-1]  # the correction names what nothing backs
    assert any(t.startswith("checking: 7.7") for k, t in events if k == "step")


@pytest.mark.parametrize("engine", ["graph", "linear"])
def test_a_second_unbacked_answer_stands_flagged(engine, monkeypatch):
    chat, sent = groq_chat([BAD, BAD])
    out = ask(chat, {"question": "which part needs service first?"}, engine, monkeypatch)
    assert out["unverified"] == ["7.7"] and len(sent) == 2  # one correction, never two
    assert out["note"].startswith("Not backed by the twin's data: 7.7")


@pytest.mark.parametrize("engine", ["graph", "linear"])
def test_a_failed_correction_keeps_the_first_answer_flagged(engine, monkeypatch):
    err = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b"{}"))
    chat, sent = groq_chat([BAD, err])
    out = ask(chat, {"question": "which part needs service first?"}, engine, monkeypatch)
    assert out["answer"] == BAD and out["unverified"] == ["7.7"]
    assert out["model"] == "groq openai/gpt-oss-120b"  # not handed to another provider
    assert "the correction failed" in out["note"]


def test_both_engines_take_the_same_path_through_a_correction(monkeypatch):
    runs = []
    for engine in ("graph", "linear"):
        chat, _ = groq_chat([BAD, GOOD])
        events = []
        out = ask(chat, {"question": "which part needs service first?"}, engine, monkeypatch,
                  events)
        runs.append((shape(out), events))
    assert runs[0] == runs[1]


def test_upb_answers_carry_upbs_name(monkeypatch):
    chat = make(upb_key="u-key")
    chat.post_groq = lambda url, key, body: completion(text=GOOD)
    out = ask(chat, {"question": "which part needs service first?"}, "graph", monkeypatch)
    assert out["model"] == f"upb {chat.c.upb_model}"
