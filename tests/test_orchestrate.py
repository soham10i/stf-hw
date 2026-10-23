"""The copilot's orchestration (services/api/orchestrate.py, websearch.py, chat.py): the route a
question takes and why, the model's thinking kept apart from its answer, Groq's models handing
over at their limits, the web search's sources graded, the streamed answer, and an answer from
the documents when no model is free. No network: every provider is a fake."""

import asyncio
import io
import json
import urllib.error

import pytest

pytest.importorskip("fastapi")

from services.api import chat as C  # noqa: E402
from services.api import orchestrate as O  # noqa: E402
from services.api import security as sec  # noqa: E402
from services.api import tools as T  # noqa: E402
from services.api import websearch as W  # noqa: E402

from .test_chat import req  # noqa: E402

MATH = "Give me the complete math behind the preventive maintenance and how it is calculated"


def route(q, choice=None, search=True):
    return O.decide(q, [n for n, _ in T.route(q, T.Ctx())], choice, search)


# ------------------------------------------------------------------ the route
@pytest.mark.parametrize(
    "q, mode",
    [
        ("hi", "chat"),
        ("which part needs service first?", "twin"),
        (MATH, "docs"),
        ("how is the health index calculated?", "docs"),
        ("what does the gripper robot do", "docs"),
        ("how do Siemens PLCs handle safety?", "web"),
        ("what is the latest version of IEC 62443?", "web"),
        ("what is the weather tomorrow", "web"),
        ("deep research: compare predictive maintenance methods used in industry", "deep"),
    ],
)
def test_each_question_takes_its_route(q, mode):
    p = route(q)
    assert p.mode == mode, p.why
    assert p.why and all(isinstance(w, str) for w in p.why)
    assert p.web == (mode in ("web", "deep"))


def test_the_operators_choice_wins_and_no_provider_means_the_documents():
    assert route("which part needs service first?", "web").mode == "web"
    assert route("how do Siemens PLCs handle safety?", "docs").mode == "docs"
    p = route("how do Siemens PLCs handle safety?", search=False)
    assert p.mode == "docs" and not p.web and "no web search provider" in p.why[-1]


def test_a_question_about_this_twin_never_goes_to_the_web():
    for q in ("why is the HBW belt slipping", "what does HBW-C01 mean"):
        assert route(q).mode in ("docs", "twin")


# ------------------------------------------------------ routing on meaning, not only words
def _semantic_hit(monkeypatch):
    """The vector side alone matches: words differ, the cosine says the passage covers it."""
    from services.api.grounding import Passage

    p = Passage(id=1, doc="Docs", path=["A"], text="t", file="a.md", line=1, anchor="a")
    hit = {"passage": p, "score": 0.4, "cover": 0.1, "vscore": 0.83, "via": "vector", "rrf": 0.1}
    monkeypatch.setattr(O.V, "hybrid_search", lambda q, top_k=8: [hit])


def test_a_meaning_match_routes_to_docs(monkeypatch):
    _semantic_hit(monkeypatch)
    plan = O.decide("why does a vacuum gripper lose its pick sometimes?", [], None, True)
    assert plan.mode == "docs", plan.why
    assert "by meaning" in " ".join(plan.why)
    assert plan.signals["vec_score"] == 0.83 and plan.signals["via"] == "vector"


def test_an_external_question_still_goes_to_the_web(monkeypatch):
    # a standards/vendor question stays web even when a passage matches it by meaning
    _semantic_hit(monkeypatch)
    plan = O.decide("how do Siemens PLCs handle safety?", [], None, True)
    assert plan.mode == "web"


def test_routing_survives_a_retrieval_failure(monkeypatch):
    def boom(q, top_k=8):
        raise RuntimeError("store down")

    monkeypatch.setattr(O.V, "hybrid_search", boom)
    # a question about this twin is answered from the documents no matter what retrieval does
    assert route("what does the crane do in this project?").mode == "docs"
    assert route("what is the weather tomorrow").mode == "web"


# ------------------------------------------------------------------ thinking apart from the answer
def test_thinking_is_kept_apart_from_the_answer():
    assert C.split_think("<think>check the soft limit</think>The belt warns.") == (
        "check the soft limit",
        "The belt warns.",
    )
    data = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "weighing the EWMA", "thought": True}, {"text": "HI = 52."}]
                }
            }
        ]
    }
    assert C.parse(data) == "HI = 52."
    assert C.thoughts(data) == "weighing the EWMA"
    g = {"choices": [{"message": {"content": "x", "reasoning": "first the wear law"}}]}
    assert C.groq_thinking(g) == "first the wear law"


def test_rate_limit_waits_are_read():
    assert C.retry_after("Please try again in 9.12s. Need more tokens?") == pytest.approx(9.12)
    assert C.retry_after("try again in 1m3.5s") == pytest.approx(63.5)
    assert C.retry_after("no hint") is None


def test_gpt_oss_is_asked_for_its_reasoning():
    b = C.groq_model({"max_tokens": 1500}, "openai/gpt-oss-120b", "medium", long=True)
    assert b["include_reasoning"] is True and b["reasoning_effort"] == "medium"
    assert b["max_tokens"] == 4000
    b = C.groq_model(b, "qwen/qwen3.8-27b")
    assert "include_reasoning" not in b and b["reasoning_format"] == "parsed"


# ------------------------------------------------------------------ Groq: hand-over and thinking
def groq_chat():
    chat = C.Chat(
        sec.Settings.from_env(),
        C.ChatSettings(
            key=None,
            model="gemini-test",
            daily_limit=100,
            groq_key="gsk_test",
            groq_model="openai/gpt-oss-120b",
            groq_models=["openai/gpt-oss-120b", "qwen/qwen3.8-27b"],
        ),
    )
    chat.c.ollama_model = None
    return chat


def limited(model):
    body = json.dumps(
        {"error": {"message": f"Rate limit reached for model `{model}`. Please try again in 40s."}}
    )
    return urllib.error.HTTPError("u", 429, "limit", {}, io.BytesIO(body.encode()))


def ask(chat, body, emit=None):
    return asyncio.run(chat.ask(C.ChatRequest(**body), req(), emit=emit))


def test_a_groq_model_at_its_limit_hands_over_and_its_thinking_is_shown():
    chat = groq_chat()
    sent = []

    def fake(url, key, body):
        sent.append(body["model"])
        if body["model"] == "openai/gpt-oss-120b":
            raise limited(body["model"])
        return {
            "choices": [
                {
                    "message": {
                        "content": "<think>the belt first</think>The belt warns in 0.6 shifts."
                    }
                }
            ]
        }

    chat.post_groq = fake
    events = []
    out = ask(
        chat,
        {"question": "which part needs service first?", "provider": "groq"},
        lambda k, t: events.append(k),
    )
    assert sent == ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
    assert out["model"] == "groq qwen/qwen3.8-27b"
    assert out["answer"] == "The belt warns in 0.6 shifts."
    assert out["thinking"] == "the belt first"
    assert any(s["from"] == "groq openai/gpt-oss-120b" for s in out["switched"])
    assert out["route"]["mode"] == "twin"
    assert "route" in events and "thinking" in events and "step" in events


def test_no_model_free_still_explains_from_the_documents():
    chat = groq_chat()
    chat.post_groq = lambda url, key, body: (_ for _ in ()).throw(limited(body["model"]))
    out = ask(chat, {"question": MATH, "provider": "groq"})
    assert out["model"] == "rules" and out["style"] == "derive"
    assert "What the documents say" in out["answer"]
    assert "$" in out["answer"]  # the equations, quoted with their LaTeX
    assert any(
        c["kind"] == "doc" and c["file"].startswith("docs/maintenance") for c in out["cites"]
    )


# ------------------------------------------------------------------ the web
SEARCH_REPLY = {
    "choices": [
        {
            "message": {
                "content": "PL d needs a PFHd from 1e-7 to 1e-6 per hour "
                "[ISO 13849-1](https://www.iso.org/standard/73481.html)【4†L56-L59】.",
                "reasoning": "look for the PFHd table",
                "executed_tools": [
                    {
                        "type": "browser_search",
                        "arguments": '{"query": "ISO 13849 PL d PFHd"}',
                        "output": "PFHd 1e-7 to 1e-6 per hour for PL d",
                        "search_results": {
                            "results": [
                                {
                                    "title": "ISO 13849-1",
                                    "url": "https://www.iso.org/standard/73481.html",
                                },
                                {"title": "A blog", "url": "https://plc-blog.example/pl-d"},
                            ]
                        },
                    }
                ],
            }
        }
    ]
}


def test_sources_are_graded_and_tool_marks_dropped():
    msg = SEARCH_REPLY["choices"][0]["message"]
    found = W.search("q", "ctx", lambda b: SEARCH_REPLY, "openai/gpt-oss-20b")
    assert "【" not in found.text
    assert [(s["url"], s["trusted"], s["cited"]) for s in found.sources] == [
        ("https://www.iso.org/standard/73481.html", True, True),
        ("https://plc-blog.example/pl-d", False, False),
    ]
    assert found.reasoning == [msg["reasoning"]]
    assert found.steps == ["searched the web: “ISO 13849 PL d PFHd”"]
    assert W.trusted("https://en.wikipedia.org/wiki/ISO_13849") and not W.trusted(
        "https://wikipedia.org.evil.io/"
    )


def test_a_web_question_is_searched_and_answered_with_its_links():
    chat = groq_chat()
    bodies = []

    def fake(url, key, body):
        bodies.append(body)
        return SEARCH_REPLY

    chat.post_groq = fake
    out = ask(chat, {"question": "what PFHd does PL d need?", "provider": "groq", "mode": "web"})
    assert bodies[0]["tools"] == [{"type": "browser_search"}]
    assert out["route"]["mode"] == "web" and out["style"] == "research"
    assert out["model"] == "groq openai/gpt-oss-20b + web search"
    web = [c for c in out["cites"] if c["kind"] == "web"]
    assert web[0]["label"] == "https://www.iso.org/standard/73481.html" and web[0]["trusted"]
    assert out["thinking"] == "look for the PFHd table"
    assert not out.get("unverified")  # the figures are in the pages it read


def test_deep_research_plans_searches_then_a_model_writes_it_up():
    chat = groq_chat()
    seen = []

    def fake(url, key, body):
        if body.get("tools") == [{"type": "browser_search"}]:
            seen.append("search")
            return SEARCH_REPLY
        if "JSON list" in body["messages"][0]["content"]:
            seen.append("plan")
            return {"choices": [{"message": {"content": '["PL d PFHd", "PL d category"]'}}]}
        seen.append("write")
        return {
            "choices": [
                {
                    "message": {
                        "content": "Two sources agree [ISO 13849-1](https://www.iso.org/standard/73481.html)."
                    }
                }
            ]
        }

    chat.post_groq = fake
    out = ask(chat, {"question": "deep research on PL d requirements", "provider": "groq"})
    assert seen == ["plan", "search", "search", "write"]
    assert out["route"]["mode"] == "deep" and "web_research" in out["tools"]
    assert any(s.startswith("planned 2 searches") for s in out["steps"])


# ------------------------------------------------------------------ the stream
def test_the_answer_streams_its_route_steps_and_answer(monkeypatch):
    from fastapi.testclient import TestClient

    import services.api.app as appmod

    with TestClient(appmod.app) as client:
        r = client.post(
            "/chat/stream",
            json={"question": "which part needs service first?", "provider": "rules"},
            headers={"host": "localhost:8000"},
        )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    kinds = [line.split(": ", 1)[1] for line in r.text.splitlines() if line.startswith("event: ")]
    assert kinds[0] == "route" and "step" in kinds and kinds[-1] == "answer"
    last = json.loads(r.text.strip().splitlines()[-1].split("data: ", 1)[1])
    assert last["route"]["mode"] == "twin" and last["model"] == "rules"


def test_gpt_oss_citation_marks_become_the_copilots():
    assert C.tidy("HI = 52 【Maintenance > Health index】 and 【4†L56-L59】.") == (
        "HI = 52 [Maintenance > Health index] and ."
    )


def test_a_question_about_the_bake_reaches_the_oven_model():
    called = [
        n for n, _ in T.route("how long does a cookie bake, and how many come out right?", T.Ctx())
    ]
    assert "oven_process" in called
    r = T.call("oven_process", {}, T.Ctx())
    if "not available" in r.text:
        pytest.skip("make bake has not been run")
    assert "cookies an hour" in r.text and r.link == {"page": "process", "label": "Oven process"}
    assert any(k.startswith("right first time") for k, _ in r.facts)
    assert O.decide("how long does a cookie bake?", called).mode == "twin"


def test_the_fallback_order_and_a_resting_provider():
    chat = C.Chat(
        sec.Settings.from_env(),
        C.ChatSettings(key="g", model="m", daily_limit=9, groq_key="q", upb_key="u"),
    )
    chat.c.ollama_model = "local"
    assert chat._provider(None) == ["gemini", "groq", "upb", "ollama"]
    assert chat._provider("upb") == ["upb", "gemini", "groq", "ollama"]
    assert chat._provider("local") == ["ollama", "gemini", "groq", "upb"]
    import time as _t

    chat.out["gemini"] = _t.time() + 60  # at its limit: tried last, not first
    assert chat._provider(None) == ["groq", "upb", "ollama", "gemini"]
