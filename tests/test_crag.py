"""Corrective retrieval (crag.py) and the docs_rag node: the judge reranks the passages; when
none helps the search is rewritten once and judged again; a "none" keeps the passages but
sends a question that is not about this twin to the web - never against the operator's choice;
with no model free the search's order stands."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from services.api import chat as C  # noqa: E402
from services.api import crag as CR  # noqa: E402
from services.api import security as sec  # noqa: E402

from .test_agent import shape  # noqa: E402
from .test_chat import req  # noqa: E402
from .test_orchestrate import SEARCH_REPLY  # noqa: E402


def script(*replies):
    """An `ask` that answers in turn and records which prompt it got."""
    asked = []

    def ask(system, user):
        asked.append("judge" if system == CR.JUDGE else "rewrite")
        return replies[min(len(asked), len(replies)) - 1]

    return ask, asked


Q = "how does the colour sensor work?"


def test_the_judge_reranks_and_keeps_k():
    plain = CR.candidates(Q)
    ask, asked = script("[3, 1, 99, \"x\", 3]")  # out of range, junk and repeats are ignored
    j = CR.correct(Q, None, ask, k=4)
    assert j.verdict == "relevant" and asked == ["judge"] and j.calls == 1
    ids = [h["passage"].id for h in j.hits]
    assert ids[:2] == [plain[2]["passage"].id, plain[0]["passage"].id] and len(ids) == 4


def test_nothing_helps_so_the_search_is_rewritten_once():
    ask, asked = script("[]", '["colour sensor signal", "sorting line colour"]', "[1]")
    j = CR.correct(Q, None, ask)
    assert j.verdict == "relevant after rewrite" and asked == ["judge", "rewrite", "judge"]
    assert j.rewrites == ["colour sensor signal", "sorting line colour"] and j.hits


def test_a_none_verdict_keeps_the_passages():
    ask, _ = script("[]", '["a", "b"]', "[]")
    j = CR.correct(Q, None, ask)
    assert j.verdict == "none" and j.hits  # a judge can be wrong: the passages stay


def test_no_model_leaves_the_search_as_it_was():
    j = CR.correct(Q, None, lambda s, u: "", k=4)
    want = [h["passage"].id for h in CR.candidates(Q)[:4]]
    assert j.verdict == "unjudged" and [h["passage"].id for h in j.hits] == want


def test_the_fusion_counts_the_original_double():
    a, b = CR.candidates(Q)[:3], CR.candidates("sorting line")[:3]
    fused = CR.fuse([a, b])
    # rank 1 of the original outweighs rank 1 of a rewrite
    assert fused[0]["passage"].id == a[0]["passage"].id


# ------------------------------------------------------------------ the node
def groq_chat(judge_reply):
    chat = C.Chat(
        sec.Settings.from_env(),
        C.ChatSettings(key=None, model="m", daily_limit=10, groq_key="gsk",
                       groq_model="openai/gpt-oss-120b", groq_models=["openai/gpt-oss-120b"]),
    )
    chat.c.ollama_model = None
    sent = []

    def post(url, key, body):
        system = body["messages"][0]["content"]
        if body.get("tools") == [{"type": "browser_search"}]:
            sent.append("search")
            return SEARCH_REPLY
        if system == CR.JUDGE:
            sent.append("judge")
            return {"choices": [{"message": {"content": judge_reply}}]}
        if system == CR.REWRITE:
            sent.append("rewrite")
            return {"choices": [{"message": {"content": '["a", "b"]'}}]}
        sent.append("write")
        return {"choices": [{"message": {"content": "It measures reflected light."}}]}

    chat.post_groq = post
    return chat, sent


def ask(chat, body, engine, monkeypatch):
    monkeypatch.setenv("STF_AGENT", engine)
    monkeypatch.setenv("STF_CRAG", "judge")
    return asyncio.run(chat.ask(C.ChatRequest(**body), req()))


@pytest.mark.parametrize("engine", ["graph", "linear"])
def test_the_node_judges_the_passages_before_the_answer(engine, monkeypatch):
    chat, sent = groq_chat("[2, 1]")
    out = ask(chat, {"question": Q}, engine, monkeypatch)
    assert sent == ["judge", "write"] and out["route"]["mode"] == "docs"
    assert any("judged the passages: relevant" in s for s in out["steps"])
    plain = CR.candidates(Q)
    assert out["cites"][0]["label"] == CR._where(plain[1])  # the judge's first pick leads


def test_both_engines_take_the_same_path(monkeypatch):
    runs = []
    for engine in ("graph", "linear"):
        chat, sent = groq_chat("[]")
        out = ask(chat, {"question": "how does a vacuum ejector create suction?"}, engine,
                  monkeypatch)
        runs.append((shape(out), sent))
    assert runs[0] == runs[1]


def test_not_covered_and_not_about_the_twin_goes_to_the_web(monkeypatch):
    chat, sent = groq_chat("[]")
    out = ask(chat, {"question": "how does a vacuum ejector create suction?"}, "graph",
              monkeypatch)
    assert sent[:4] == ["judge", "rewrite", "judge", "search"]
    assert out["route"]["mode"] == "web" and "judged not to cover it" in out["route"]["why"][-1]


def test_the_operators_choice_of_the_documents_stands(monkeypatch):
    chat, sent = groq_chat("[]")
    out = ask(chat, {"question": "how does a vacuum ejector create suction?", "mode": "docs"},
              "graph", monkeypatch)
    assert "search" not in sent and out["route"]["mode"] == "docs"


def test_a_question_about_the_twin_keeps_its_documents(monkeypatch):
    chat, sent = groq_chat("[]")
    out = ask(chat, {"question": "why is the oven preheated?"}, "graph", monkeypatch)
    assert "search" not in sent and out["route"]["mode"] in ("docs", "twin")  # never the web
    assert any("do not cover it well" in s for s in out["steps"])


def test_off_means_no_judge(monkeypatch):
    chat, sent = groq_chat("[1]")
    monkeypatch.setenv("STF_AGENT", "graph")
    asyncio.run(chat.ask(C.ChatRequest(question=Q), req()))  # conftest: STF_CRAG=off
    assert sent == ["write"]


def test_a_rate_limited_helper_rests_without_resting_the_chat():
    import io
    import urllib.error

    chat, _ = groq_chat("[1]")
    calls = []

    def busy(url, key, body):
        calls.append(body["model"])
        raise urllib.error.HTTPError("u", 429, "slow", {}, io.BytesIO(b"{}"))

    chat.post_groq = busy
    assert chat.quick("s", "u") == "" and chat.quick("s", "u") == ""
    assert len(calls) == 1  # the second call did not ask Groq again
    assert chat.out.get("groq", 0.0) == 0.0  # the chat's own Groq models are not rested
