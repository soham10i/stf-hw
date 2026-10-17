"""The council's copilot fixes (kimi-code/COUNCIL_REVIEW.md), pinned by tests:

- copilot_setup answers "which model does the local setup use" from the .env / environment;
- open_page fetches a public page but never a private, local or non-http(s) URL (SSRF guard);
- the session's context text ranks the facts that overlap the question and keeps its preamble;
- identical session-less questions reuse the cached answer (live_state answers are never cached);
- lean retrieval (small local models) asks search_docs for fewer passages;
- Gemini's body carries google_search when grounding is on. No network.
"""

import json

import pytest

pytest.importorskip("fastapi")

from services.api import chat as C  # noqa: E402
from services.api import sessions as S  # noqa: E402
from services.api import tools as T  # noqa: E402
from tests.test_sessions import ask, make  # noqa: E402

CTX = T.Ctx()
PREAMBLE = "## Established earlier in this session\n"


# ---------------------------------------------------------------------- copilot_setup
def test_setup_tool_uses_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "council-test-model:1")
    monkeypatch.setenv("GEMINI_MODELS", "m-a, m-b")
    r = T.copilot_setup({}, CTX)
    d = {k: v for k, v in r.facts}
    assert d["local text model (Ollama)"] == "council-test-model:1"
    assert d["Gemini chat models, fallback order"].endswith("m-a -> m-b")
    assert "council-test-model:1" in r.text


def test_setup_question_routes_to_setup_tool():
    calls = T.route(
        "Which setup model is used by local system to get text generation in local mode?", CTX
    )
    assert ("copilot_setup", {}) in calls


def test_setup_tool_is_declared():
    assert "copilot_setup" in T.TOOLS and "open_page" in T.TOOLS


# ---------------------------------------------------------------------- open_page
def test_open_page_rejects_private_and_bad_scheme():
    for url, why in (
        ("http://127.0.0.1:8000/x", "private"),
        ("http://localhost/x", "localhost"),
        ("http://169.254.169.254/latest", "link-local"),
        ("ftp://example.com/x", "scheme"),
        ("not-a-url", "scheme"),
    ):
        r = T.open_page({"url": url}, CTX)
        assert r.tool == "open_page" and "excerpt" not in dict(r.facts), f"{url} ({why}) fetched!"


def test_open_page_quotes_a_fetched_page(monkeypatch):
    monkeypatch.setattr(T, "_public_host", lambda host: True)
    monkeypatch.setattr(
        T,
        "_http_get",
        lambda url: (
            b"<html><head><style>body{}</style></head><body><script>x()</script>"
            b"<p>Belt wear data, verified.</p></body></html>",
            "text/html",
        ),
    )
    r = T.open_page({"url": "https://example.com/belt"}, CTX)
    text = dict(r.facts)["excerpt"]
    assert "Belt wear data, verified." in text and "script" not in text
    assert r.sources == ["https://example.com/belt"]


# ---------------------------------------------------------------------- context_text
def test_context_text_ranks_question_facts():
    s = S.new("overview")
    s["context"]["facts"] = [
        [f"fact {i}", f"value {i}", "test source"] for i in range(14)
    ]
    s["context"]["facts"][3] = ["belt", "warns in 12.5 shifts", "condition model"]
    out = S.context_text(s, "and the belt?")
    assert out.startswith(PREAMBLE)
    assert "| belt | warns in 12.5 shifts | [condition model] |" in out
    rows = [x for x in out.split("\n") if x.startswith("| ") and not x.startswith("| Fact")]
    assert len(rows) <= 14  # at most the capped facts


def test_context_text_without_question_keeps_preamble():
    s = S.new("overview")
    s["context"]["facts"] = [["a", "1", "src"], ["b", "2", "src"]]
    assert S.context_text(s).startswith(PREAMBLE)


# ---------------------------------------------------------------------- response cache
def test_identical_sessionless_question_is_cached(tmp_path):
    chat, sent = make(tmp_path)
    a = ask(chat, "what is the oven", user=None)
    b = ask(chat, "what is the oven", user=None)
    assert a["answer"] == b["answer"]
    assert len(sent) == 1, "the second ask must reuse the cache, not call Gemini again"


def test_live_state_answer_is_not_cached(tmp_path):
    chat, sent = make(tmp_path)
    ask(chat, "what is the cell doing right now", user=None)
    ask(chat, "what is the cell doing right now", user=None)
    assert len(sent) == 2, "live answers must not be served from the cache"


# ---------------------------------------------------------------------- lean retrieval
def test_lean_route_asks_for_fewer_passages():
    q = "how does the oven work"
    lean = dict(T.route(q, CTX, lean=True))["search_docs"]
    full = dict(T.route(q, CTX))["search_docs"]
    assert lean["k"] < full["k"]


# ---------------------------------------------------------------------- grounding
def test_build_body_carries_google_search_when_asked():
    body = C.build_body(C.ChatRequest(question="q"), search=True)
    kinds = [list(t)[0] for t in body["tools"]]
    assert "google_search" in kinds and "functionDeclarations" in kinds
    plain = C.build_body(C.ChatRequest(question="q"))
    assert [list(t)[0] for t in plain["tools"]] == ["functionDeclarations"]


def test_settings_read_grounding_flag(monkeypatch):
    monkeypatch.setenv("GEMINI_GROUNDING", "1")
    assert C.ChatSettings.from_env().grounding
    monkeypatch.setenv("GEMINI_GROUNDING", "0")
    assert not C.ChatSettings.from_env().grounding


# ---------------------------------------------------------------------- declarations stay valid
def test_new_tools_declare_in_both_models():
    decl = {d["name"] for d in T.declarations()}
    assert {"copilot_setup", "open_page"} <= decl
    for d in T.declarations():
        assert d["parameters"]["type"] == "object"
        json.dumps(d)  # serializable into both providers' bodies
