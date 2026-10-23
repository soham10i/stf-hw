"""The research graph (agent.plan -> search x N -> critic -> gather): the planner's
sub-questions run as parallel branches, each down the whole search ladder; the critic adds at
most MAX_REPLANS rounds of searches for what is missing; a branch that fails costs only itself;
the token ceiling stops further branches; both engines take the same path."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

pytest.importorskip("fastapi")

from services.api import agent as A  # noqa: E402
from services.api import chat as C  # noqa: E402
from services.api import security as sec  # noqa: E402

from .test_agent import shape  # noqa: E402
from .test_chat import req  # noqa: E402
from .test_orchestrate import SEARCH_REPLY, limited  # noqa: E402

DEEP = {"question": "deep research on PL d requirements", "provider": "groq"}


def research_chat(plan='["a", "b", "c"]', critic=("[]",), fail=(), slow=0.0):
    chat = C.Chat(
        sec.Settings.from_env(),
        C.ChatSettings(key=None, model="m", daily_limit=10, groq_key="gsk",
                       groq_model="openai/gpt-oss-120b", groq_models=["openai/gpt-oss-120b"]),
    )
    chat.c.ollama_model = None
    chat.c.search_order = ("groq",)  # DuckDuckGo would reach the network
    log, lock, live = [], threading.Lock(), {"now": 0, "max": 0}

    def post(url, key, body):
        system = body["messages"][0]["content"]
        if body.get("tools") == [{"type": "browser_search"}]:
            sub = body["messages"][-1]["content"].rsplit("\n", 1)[-1]
            with lock:
                log.append(("search", sub))
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
            time.sleep(slow)
            with lock:
                live["now"] -= 1
            if any(f in sub for f in fail):
                raise limited(body["model"])
            return SEARCH_REPLY
        if "further web searches" in system:
            n = sum(1 for e in log if e[0] == "critic")
            log.append(("critic", None))
            return {"choices": [{"message": {"content": critic[min(n, len(critic) - 1)]}}]}
        if "JSON list" in system:
            log.append(("plan", None))
            return {"choices": [{"message": {"content": plan}}]}
        log.append(("write", None))
        return {"choices": [{"message": {"content": "Two sources agree."}}]}

    chat.post_groq = post
    return chat, log, live


def ask(chat, engine, monkeypatch, body=DEEP):
    monkeypatch.setenv("STF_AGENT", engine)
    return asyncio.run(chat.ask(C.ChatRequest(**body), req()))


def kinds(log):
    return [k for k, _ in log]


@pytest.mark.parametrize("engine", ["graph", "linear"])
def test_the_plan_fans_out_and_the_findings_are_gathered_in_order(engine, monkeypatch):
    chat, log, live = research_chat(slow=0.05)
    out = ask(chat, engine, monkeypatch)
    assert kinds(log) == ["plan", "search", "search", "search", "critic", "write"]
    assert live["max"] == A.AT_ONCE  # in parallel, never more than AT_ONCE at a time
    web = next(r for r in out["tools"] if r == "web_research")
    assert web and out["route"]["mode"] == "deep"
    assert any(s.startswith("planned 3 searches: a; b; c") for s in out["steps"])


def test_the_critic_adds_a_round_for_what_is_missing(monkeypatch):
    chat, log, _ = research_chat(critic=('["d"]', "[]"))
    out = ask(chat, "graph", monkeypatch)
    assert kinds(log) == ["plan", "search", "search", "search", "critic", "search", "critic",
                          "write"]
    assert any("the critic found gaps: 1 more search: d" in s for s in out["steps"])


def test_the_critic_never_repeats_a_search_and_stops_after_its_rounds(monkeypatch):
    chat, log, _ = research_chat(critic=('["a", "d"]', '["e"]', '["f"]'))
    ask(chat, "graph", monkeypatch)
    searched = [s for k, s in log if k == "search"]
    assert searched.count("a") == 1 and "d" in searched
    assert kinds(log).count("critic") <= A.MAX_REPLANS
    assert len(searched) <= 3 + A.MAX_REPLANS  # depth.subs + MAX_REPLANS at most


def test_a_failed_branch_costs_only_itself(monkeypatch):
    chat, log, _ = research_chat(fail=("b",))
    out = ask(chat, "graph", monkeypatch)
    assert any(s == "search 2 failed" for s in out["steps"])
    assert "web_research" in out["tools"] and kinds(log)[-1] == "write"


def test_every_branch_failing_still_answers(monkeypatch):
    chat, log, _ = research_chat(fail=("a", "b", "c"))
    out = ask(chat, "graph", monkeypatch)
    assert "web_research" not in out["tools"]
    assert any("every search of the research failed" in s for s in out["steps"])


def test_the_token_ceiling_stops_further_branches(monkeypatch):
    monkeypatch.setattr(A, "RESEARCH_TOKENS", 0)
    chat, log, _ = research_chat()
    out = ask(chat, "graph", monkeypatch)
    assert "search" not in kinds(log)
    assert any("not run: the research reached" in s for s in out["steps"])


def test_both_engines_take_the_same_path(monkeypatch):
    runs = []
    for engine in ("graph", "linear"):
        chat, log, _ = research_chat(critic=('["d"]', "[]"))
        out = ask(chat, engine, monkeypatch)
        runs.append(({**shape(out), "steps": None}, kinds(log)))
    assert runs[0] == runs[1]


def test_the_drawing_shows_the_fan_out():
    m = A.mermaid()
    for node in ("docs_rag", "plan", "search", "critic", "gather"):
        assert node in m


def test_duckduckgo_with_a_writer_counts_as_a_search_provider():
    """Only an open model of your own and DuckDuckGo: the router may still send a question to
    the web or to deep research (before, it counted only Groq and Gemini as able to search)."""
    chat = C.Chat(
        sec.Settings.from_env(),
        C.ChatSettings(key=None, model="m", daily_limit=10, openai_url="http://127.0.0.1:1/v1"),
    )
    assert chat.can_search()
    chat.c.search_order = ("gemini", "groq")  # DuckDuckGo not listed: nothing can search
    assert not chat.can_search()
