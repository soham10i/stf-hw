"""The copilot as a graph (agent.py): LangGraph and the plain loop run the same nodes along the
same edges, so every kind of question gets the same answer on both engines; the edges route as
drawn; a spent budget still refuses; the drawing comes from the compiled graph."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("langgraph")

from fastapi import HTTPException  # noqa: E402

from services.api import agent as A  # noqa: E402
from services.api import chat as C  # noqa: E402
from services.api import security as sec  # noqa: E402

from .test_chat import req  # noqa: E402
from .test_orchestrate import SEARCH_REPLY, groq_chat, limited  # noqa: E402

GROQ_OK = {"choices": [{"message": {"content": "The belt warns in 0.6 shifts."}}]}


def rules_chat():
    chat = C.Chat(sec.Settings.from_env(), C.ChatSettings(key=None, model="m", daily_limit=10))
    chat.c.ollama_model = None
    return chat


def busy(url, key, body):
    raise limited(body["model"])


CASES = {
    "rules": (rules_chat, None, {"question": "which part needs service first?"}),
    "model": (groq_chat, lambda u, k, b: GROQ_OK, {"question": "which part needs service first?"}),
    "web": (
        groq_chat,
        lambda u, k, b: SEARCH_REPLY,
        {"question": "what PFHd does PL d need?", "provider": "groq", "mode": "web"},
    ),
    "busy": (groq_chat, busy, {"question": "which part needs service first?"}),
}


def run(engine, monkeypatch, case):
    monkeypatch.setenv("STF_AGENT", engine)
    make, post, body = CASES[case]
    chat, events = make(), []
    if post:
        chat.post_groq = post
    out = asyncio.run(
        chat.ask(C.ChatRequest(**body), req(), emit=lambda k, t: events.append((k, t)))
    )
    out = {k: v for k, v in out.items() if k != "ms"}
    return out, events


@pytest.mark.parametrize("case", list(CASES))
def test_both_engines_answer_alike(monkeypatch, case):
    graph, g_events = run("graph", monkeypatch, case)
    linear, l_events = run("linear", monkeypatch, case)
    assert graph == linear and g_events == l_events
    assert graph["model"] == {
        "rules": "rules",
        "model": "groq openai/gpt-oss-120b",
        "web": "groq openai/gpt-oss-20b + web search",
        "busy": "rules",
    }[case]
    if case == "busy":
        assert graph["note"].startswith("Every model is busy")


def test_the_edges_route_as_drawn():
    assert A.after_prepare({"out": {"answer": "cached"}}) == A.END
    assert A.after_prepare({}) == "route"
    assert A.after_route({"rules": True, "web": True}) == "tools_only"
    assert A.after_route({"web": True}) == "web" and A.after_route({}) == "answer"
    assert A.after_web({"outcome": {}}) == "respond" and A.after_web({}) == "answer"
    assert A.after_answer({"rules": True}) == "tools_only" and A.after_answer({}) == "respond"


def test_a_repeated_question_ends_at_prepare(monkeypatch):
    monkeypatch.setenv("STF_AGENT", "graph")
    chat, calls = groq_chat(), []

    def post(url, key, body):
        calls.append(1)
        return GROQ_OK

    chat.post_groq = post
    body = {"question": "which part needs service first?"}
    first = asyncio.run(chat.ask(C.ChatRequest(**body), req()))
    again = asyncio.run(chat.ask(C.ChatRequest(**body), req()))
    assert again is first and len(calls) == 1


def test_a_spent_daily_budget_still_refuses_through_the_graph(monkeypatch):
    monkeypatch.setenv("STF_AGENT", "graph")
    chat = groq_chat()
    chat.cap.take = lambda: False
    with pytest.raises(HTTPException) as e:
        asyncio.run(chat.ask(C.ChatRequest(question="which part needs service first?"), req()))
    assert e.value.status_code == 429


def test_the_engine_switch(monkeypatch):
    monkeypatch.setenv("STF_AGENT", "linear")
    assert A.engine() == "linear"
    monkeypatch.delenv("STF_AGENT")
    assert A.engine() == "graph"
    monkeypatch.setattr(A, "HAVE_LANGGRAPH", False)
    assert A.engine() == "linear"  # without langgraph the same nodes run as a loop


def test_the_drawing_is_the_compiled_graph():
    m = A.mermaid()
    for node in A.NODES:
        assert node in m
    assert "prepare -.-> route" in m.replace("\t", "") or "prepare -.-> route;" in m


def test_chat_graph_endpoint():
    from fastapi.testclient import TestClient

    from services.api.app import app

    r = TestClient(app).get("/chat/graph")
    assert r.status_code == 200
    data = r.json()
    assert data["engine"] in ("graph", "linear") and data["nodes"][0] == "prepare"
    assert "tools_only" in data["mermaid"]
