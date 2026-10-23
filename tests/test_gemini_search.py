"""Gemini's Google Search for the copilot (services/api/gemini_search.py, token_budget.py, and the
web-search order in chat.py): the token budget sets how much a search may do and shrinks as it is
used, a grounded answer gets its links and graded sources, a deep research stops at its ceiling,
and a search that cannot be afforded or fails hands the question to Groq. No network: Gemini,
Groq and the page reads are fakes."""

import calendar
import io
import json
import urllib.error

import pytest

pytest.importorskip("fastapi")

from services.api import chat as C  # noqa: E402
from services.api import gemini_search as GS  # noqa: E402
from services.api import security as sec  # noqa: E402
from services.api import token_budget as TB  # noqa: E402

from .test_orchestrate import SEARCH_REPLY, ask, limited  # noqa: E402

BIG = TB.Limits(day=100_000, minute=100_000, guest=100_000, web=8_000, deep=40_000, searches=100)


def budget(limits=BIG, t=0.0):
    clock = [t]
    return TB.TokenBudget(limits, clock=lambda: clock[0]), clock


# ------------------------------------------------------------------ the token budget
def test_the_tier_falls_as_tokens_are_used_and_the_allowance_shrinks():
    b, _ = budget()
    seen = []
    for used in (0, 60_000, 85_000, 93_000):
        b.record(used - b.used)
        seen.append((used, b.tier(), b.allow("deep", 1_000)))
    assert [t for _, t, _ in seen] == ["full", "lean", "minimal", "minimal"]
    full, lean, minimal, tight = (a for *_, a in seen)
    assert (full.searches, lean.searches, minimal.searches, tight.searches) == (4, 3, 2, 1)
    assert full.max_output > lean.max_output > minimal.max_output
    assert full.context_chars > lean.context_chars > minimal.context_chars
    assert full.thoughts and not lean.thoughts and full.url_context and not lean.url_context
    assert full.ceiling > tight.ceiling  # a question may spend only what is left


def test_a_spent_budget_allows_no_search_and_the_caller_hands_over():
    b, _ = budget()
    b.record(97_000)
    assert b.tier() == "spent" and b.allow("web", 500) is None


def test_the_minute_window_empties_and_the_day_rolls_over():
    b, clock = budget(TB.Limits(), t=calendar.timegm((2026, 1, 1, 12, 0, 0)))
    b.record(110_000)  # 92 % of the minute's 120000
    assert b.tier() == "minimal"
    clock[0] += 61
    assert b.tier() == "full" and b.left()["day"] == 600_000 - 110_000
    clock[0] = calendar.timegm((2026, 1, 2, 0, 0, 5))  # past midnight UTC
    assert b.left()["day"] == 600_000 and b.status()["tokens_day"]["used"] == 0


def test_one_guest_cannot_use_the_whole_budget():
    b, _ = budget(
        TB.Limits(day=600_000, minute=120_000, guest=10_000, web=8_000, deep=40_000, searches=50)
    )
    b.record(9_500, guest="visitor-a")
    assert b.tier("visitor-a") == "spent" and b.allow("web", 500, "visitor-a") is None
    assert b.tier("visitor-b") == "full" and b.allow("web", 500, "visitor-b")


def test_a_question_that_does_not_fit_or_has_no_searches_left_is_refused():
    b, _ = budget()
    b.record(93_000)  # minimal: 7000 left
    assert b.allow("web", 10_000) is None  # the prompt alone is over the ceiling
    c, _ = budget(
        TB.Limits(day=600_000, minute=120_000, guest=80_000, web=8_000, deep=40_000, searches=2)
    )
    c.record(0, queries=2)
    assert c.allow("web", 500) is None


def test_usage_is_read_from_the_response():
    assert TB.usage_tokens({"usageMetadata": {"totalTokenCount": 1650}}) == 1650
    assert (
        TB.usage_tokens(
            {
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 30,
                }
            }
        )
        == 150
    )
    assert TB.usage_tokens({}) == 0
    grounded = {"candidates": [{"groundingMetadata": {"webSearchQueries": ["a", "b"]}}]}
    assert TB.searches_in(grounded) == 2


def test_limits_come_from_the_environment():
    lim = TB.Limits.from_env({"GEMINI_TOKENS_PER_DAY": "1000", "GEMINI_DEEP_TOKENS": "bad"})
    assert lim.day == 1000 and lim.deep == TB.Limits().deep


# ------------------------------------------------------------------ a grounded answer
TEXT = "PL d needs a PFHd from 1e-7 to 1e-6 per hour."
GOOGLE = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"
GROUNDED = {
    "candidates": [
        {
            "content": {"parts": [{"text": "weighing", "thought": True}, {"text": TEXT}]},
            "finishReason": "STOP",
            "groundingMetadata": {
                "webSearchQueries": ["ISO 13849 PL d PFHd"],
                "groundingChunks": [
                    {"web": {"uri": GOOGLE + "AAA", "title": "iso.org"}},
                    {"web": {"uri": GOOGLE + "BBB", "title": "plc-blog.example"}},
                ],
                "groundingSupports": [
                    {"segment": {"endIndex": len(TEXT.encode())}, "groundingChunkIndices": [0]}
                ],
            },
        }
    ],
    "usageMetadata": {"totalTokenCount": 1650},
}
PAGES = {
    GOOGLE + "AAA": (
        "https://www.iso.org/standard/73481.html",
        "ISO 13849-1:2023",
        "PFHd 1e-7 to 1e-6 per hour for PL d",
    ),
    GOOGLE + "BBB": ("https://plc-blog.example/pl-d", "", ""),
}


@pytest.fixture
def pages(monkeypatch):
    """Following Google's redirects and reading pages, without the network."""
    monkeypatch.setattr(GS, "_open", lambda url, read: PAGES.get(url, (url, "", "")))


def allowance(**kw):
    base = dict(
        tier="full",
        mode="web",
        max_output=4096,
        thinking=2048,
        thoughts=True,
        url_context=False,
        context_chars=12_000,
        searches=1,
        ceiling=8_000,
    )
    return TB.Allowance(**{**base, **kw})


def test_each_supported_sentence_gets_its_pages_links_at_utf8_offsets():
    text = "Wärme: 30 °C is typical. Next sentence."
    end = len("Wärme: 30 °C is typical.".encode())
    data = {
        "candidates": [
            {
                "groundingMetadata": {
                    "groundingSupports": [
                        {"segment": {"endIndex": end}, "groundingChunkIndices": [0, 9]}
                    ]
                }
            }
        ]
    }
    out = GS.link(text, data, {0: {"title": "ISO", "url": "https://iso.org/x"}})
    assert out == "Wärme: 30 °C is typical. [ISO](https://iso.org/x) Next sentence."


def test_sources_follow_the_redirect_cited_first_and_graded_by_their_real_host(monkeypatch):
    def fake(url, read):
        if url.endswith("CCC"):  # a redirect that would not open: Google's own title is the domain
            return url, "", ""
        return {
            GOOGLE + "AAA": ("https://www.iso.org/s", "ISO 13849", "text"),
            GOOGLE + "BBB": ("https://plc-blog.example/x", "", ""),
        }[url]

    monkeypatch.setattr(GS, "_open", fake)
    data = {
        "candidates": [
            {
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": GOOGLE + k, "title": t}}
                        for k, t in (
                            ("AAA", "iso.org"),
                            ("BBB", "plc-blog.example"),
                            ("CCC", "wikipedia.org"),
                        )
                    ],
                    "groundingSupports": [
                        {"segment": {"endIndex": 5}, "groundingChunkIndices": [1]}
                    ],
                }
            }
        ]
    }
    rows, by_chunk, text = GS.sources_of(data)
    assert [(r["url"].split("//")[1].split("/")[0], r["cited"], r["trusted"]) for r in rows] == [
        ("plc-blog.example", True, False),
        ("www.iso.org", False, True),
        ("vertexaisearch.cloud.google.com", False, True),
    ]
    assert rows[1]["title"] == "ISO 13849" and text == "text" and set(by_chunk) == {0, 1, 2}


def test_a_search_asks_for_google_search_on_its_allowance_and_counts_the_tokens(pages):
    b, _ = budget()
    sent = []

    def call(body, tune):
        sent.append(tune(body, "gemini-2.5-flash"))
        return GROUNDED, "gemini-2.5-flash"

    a = allowance(thinking=512, thoughts=False, max_output=1536)
    found = GS.search("what PFHd does PL d need?", "ctx", call, a, b, guest="g")
    assert sent[0]["tools"] == [{"google_search": {}}]
    assert sent[0]["generationConfig"]["maxOutputTokens"] == 1536
    assert sent[0]["generationConfig"]["thinkingConfig"] == {
        "includeThoughts": False,
        "thinkingBudget": 512,
    }
    assert found.via == "gemini" and found.model == "gemini-2.5-flash"
    assert "[ISO 13849-1:2023](https://www.iso.org/standard/73481.html)" in found.text
    assert "searched Google: “ISO 13849 PL d PFHd”" in found.steps
    assert "1e-6" in found.pages and "weighing" not in found.text
    assert (b.used, b.queries, b.left("g")["guest"]) == (1650, 1, BIG.guest - 1650)


def test_only_flash_2_5_models_get_a_thinking_budget_and_the_body_is_not_changed():
    body = GS._body("q", "ctx", allowance(url_context=True))
    assert body["tools"] == [{"google_search": {}}, {"url_context": {}}]
    new = GS.tune(body, "gemini-3.5-flash", allowance(thoughts=True))
    assert new["generationConfig"]["thinkingConfig"] == {"includeThoughts": True}
    assert "maxOutputTokens" not in body["generationConfig"]


# ------------------------------------------------------------------ deep research
def test_deep_research_plans_searches_and_stops_at_the_token_ceiling(pages):
    b, _ = budget()
    asked, said = [], []

    def call(body, tune):
        if "tools" not in body:  # the planner
            return {
                "candidates": [{"content": {"parts": [{"text": '["one", "two", "three"]'}]}}],
                "usageMetadata": {"totalTokenCount": 100},
            }, "m"
        asked.append(body["contents"][0]["parts"][0]["text"].rsplit("\n\n", 1)[-1])
        return GROUNDED, "m"

    a = allowance(
        tier="lean", mode="deep", max_output=1536, searches=3, ceiling=8_000, context_chars=6_000
    )
    found = GS.deep("research this", "", call, a, b, emit=said.append)
    assert sorted(asked) == ["one", "two"]  # 8000 - plan - write-up leaves room for two
    assert any("room for 2" in s for s in said) and found.via == "gemini"
    assert found.text.count("## Finding") == 2 and b.used == 100 + 2 * 1650


def test_a_failed_sub_search_is_skipped_and_all_failing_is_an_error(pages):
    def call(body, tune):
        if "tools" not in body:
            return {"candidates": [{"content": {"parts": [{"text": '["ok", "bad"]'}]}}]}, "m"
        if body["contents"][0]["parts"][0]["text"].endswith("bad"):
            raise RuntimeError("Gemini did not answer in time")
        return GROUNDED, "m"

    a = allowance(mode="deep", searches=2, ceiling=40_000)
    assert GS.deep("q", "", call, a).text.count("## Finding") == 1

    def never(body, tune):
        raise RuntimeError("at its limit")

    with pytest.raises(RuntimeError, match="every Gemini search"):
        GS.deep("q", "", never, allowance(mode="deep", searches=1))


# ------------------------------------------------------------------ in the chat
def both():
    chat = C.Chat(
        sec.Settings.from_env(),
        C.ChatSettings(
            key="g-key",
            model="gemini-test",
            daily_limit=100,
            groq_key="gsk_test",
            groq_model="openai/gpt-oss-120b",
            groq_models=["openai/gpt-oss-120b"],
        ),
    )
    chat.c.ollama_model = None
    return chat


def test_the_web_is_searched_with_gemini_first_and_the_answer_is_linked(pages):
    chat, seen = both(), []

    def gemini(url, key, body):
        seen.append((url, key))
        return GROUNDED

    chat.post_search = gemini
    chat.post_groq = lambda *a: pytest.fail("Groq must not be asked while Gemini answers")
    out = ask(chat, {"question": "what PFHd does PL d need?", "mode": "web"})
    assert out["model"] == "gemini-test + Google Search" and seen == [
        (
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent",
            "g-key",
        )
    ]
    assert "[ISO 13849-1:2023](https://www.iso.org/standard/73481.html)" in out["answer"]
    web = [c for c in out["cites"] if c["kind"] == "web"]
    assert web[0]["label"] == "https://www.iso.org/standard/73481.html" and web[0]["trusted"]
    assert (
        not out.get("unverified") and chat.budget.used == 1650
    )  # the figures are in the page read
    assert chat.status()["search"]["budget"]["tokens_day"]["used"] == 1650


def test_a_spent_budget_or_a_failing_gemini_hands_the_search_to_groq(pages):
    for spoil in ("budget", "limit"):
        chat = both()
        if spoil == "budget":
            chat.budget.record(chat.c.limits.day)
            chat.post_search = lambda *a: pytest.fail("a spent budget must not call Gemini")
        else:
            chat.post_search = lambda url, key, body: (_ for _ in ()).throw(limited("gemini-test"))
        chat.post_groq = lambda url, key, body: SEARCH_REPLY
        out = ask(chat, {"question": "what PFHd does PL d need?", "mode": "web"})
        assert out["model"] == "groq openai/gpt-oss-20b + web search", spoil
        assert any("Gemini" in s for s in out["steps"]), spoil


def test_google_search_quota_is_metered_apart_and_never_takes_the_chats_models_out(pages):
    """A key can answer plain questions yet have no Google Search quota (every grounded call is a
    429): searches rest and go to Groq at once, and the chat's own pool is left alone."""
    chat, calls = both(), []

    def refused(url, key, body):
        calls.append(body)
        raise limited("gemini-test")

    chat.post_search = refused
    chat.post_groq = lambda url, key, body: SEARCH_REPLY
    ask(chat, {"question": "what PFHd does PL d need?", "mode": "web"})
    assert len(calls) == 1 and chat.pool.available() == ["gemini-test"]  # the chat pool is free
    assert chat.status()["search"]["gemini_rest_s"] > 600 and chat.search_pool.available() == []
    out = ask(chat, {"question": "what PFHd does PL d need? again", "mode": "web"})
    assert len(calls) == 1  # resting: Gemini was not asked again
    assert out["model"].startswith("groq ") and any("resting" in s for s in out["steps"])
    plain = {"candidates": [{"content": {"parts": [{"text": "The belt warns in 0.6 shifts."}]}}]}
    chat.post = lambda url, key, body: plain  # a plain answer still works
    assert ask(chat, {"question": "which part needs service first?"})["answer"].startswith(
        "The belt"
    )


def test_a_slow_search_model_is_skipped_for_the_next_one(pages):
    chat, asked = both(), []
    chat.pool = C.GP.Pool(["slow-model", "gemini-test"])
    chat.search_pool = C.GP.Pool(list(chat.pool.models))

    def gemini(url, key, body):
        asked.append(url.split("/models/")[1].split(":")[0])
        if asked[-1] == "slow-model":
            raise TimeoutError
        return GROUNDED

    chat.post_search = gemini
    body = GS._body("q", "ctx", allowance())
    _, model = chat._gemini_call(body, lambda b, m: b)
    assert asked == ["slow-model", "gemini-test"] and model == "gemini-test"
    assert chat.search_pool.available() == ["gemini-test"]  # the slow one rests


def test_the_operators_order_decides_who_searches_first(pages):
    chat = both()
    chat.c.search_order = ("groq", "gemini")
    chat.post_search = lambda *a: pytest.fail("Groq answers first in this order")
    chat.post_groq = lambda url, key, body: SEARCH_REPLY
    out = ask(chat, {"question": "what PFHd does PL d need?", "mode": "web"})
    assert out["model"].startswith("groq ")


def test_deep_research_on_gemini_is_counted_whole_with_its_write_up(pages):
    chat = both()

    def search(url, key, body):
        if "tools" not in body:
            return {
                "candidates": [
                    {"content": {"parts": [{"text": '["PL d PFHd", "PL d category"]'}]}}
                ],
                "usageMetadata": {"totalTokenCount": 100},
            }
        return GROUNDED

    chat.post_search = search
    chat.post_groq = lambda *a: pytest.fail("Groq must not be asked")
    chat.post = lambda url, key, body: {
        "candidates": [{"content": {"parts": [{"text": "Two sources agree."}]}}],
        "usageMetadata": {"totalTokenCount": 900},
    }
    out = ask(chat, {"question": "deep research on PL d requirements"})
    assert out["route"]["mode"] == "deep" and "web_research" in out["tools"]
    assert (chat.budget.used, chat.budget.queries) == (100 + 2 * 1650 + 900, 2)
    assert any("deep research with Gemini" in s for s in out["steps"])


def test_the_status_shows_the_order_and_the_budget_but_never_the_key():
    st = both().status()
    assert (
        st["search"]["order"] == ["gemini", "groq", "ddg"]
        and st["search"]["budget"]["tier"] == "full"
    )
    assert "g-key" not in json.dumps(st)


def test_the_search_order_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_ORDER", "groq, ddg ,nonsense")
    assert C.ChatSettings.from_env().search_order == ("groq", "ddg")
    monkeypatch.setenv("WEB_SEARCH_ORDER", "")
    assert C.ChatSettings.from_env().search_order == ("gemini", "groq", "ddg")


def test_a_model_that_rejects_the_url_context_tool_is_asked_again_without_it(pages):
    chat, tools = both(), []

    def gemini(url, key, body):
        tools.append([next(iter(t)) for t in body["tools"]])
        if len(tools) == 1:
            raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"{}"))
        return GROUNDED

    chat.post_search = gemini
    body = GS._body("q", "ctx", allowance(url_context=True))
    data, model = chat._gemini_call(body, lambda b, m: b)
    assert tools == [["google_search", "url_context"], ["google_search"]] and model == "gemini-test"


# ------------------------------------------------------------------ a Google Cloud (billed) key
def with_cloud():
    """The AI Studio key (g-key) and a Google Cloud key (c-key): Cloud is asked first."""
    chat = C.Chat(
        sec.Settings.from_env(),
        C.ChatSettings(
            key="g-key",
            model="gemini-test",
            daily_limit=100,
            cloud_key="c-key",
            groq_key="gsk_test",
            groq_model="openai/gpt-oss-120b",
            groq_models=["openai/gpt-oss-120b"],
        ),
    )
    chat.c.ollama_model = None
    return chat


PLAIN = {
    "candidates": [{"content": {"parts": [{"text": "The belt warns in 0.6 shifts."}]}}],
    "usageMetadata": {"totalTokenCount": 700},
}


def test_the_cloud_key_is_asked_first_and_counted_on_its_own_budget():
    chat, keys = with_cloud(), []

    def fake(url, key, body):
        keys.append(key)
        return PLAIN

    chat.post = fake
    out = ask(chat, {"question": "which part needs service first?"})
    assert keys == ["c-key"] and out["answer"].startswith("The belt")
    assert chat.cloud.budget.used == 700 and chat.budget.used == 0  # Studio's free budget untouched
    assert chat.cap.limit == 2000  # a billed key lifts the daily question cap


def test_a_cloud_key_at_its_limit_or_refused_hands_over_to_ai_studio():
    for failure in ("limit", "refused"):
        chat, keys = with_cloud(), []

        def fake(url, key, body, failure=failure, keys=keys):
            keys.append(key)
            if key == "c-key":
                code = 429 if failure == "limit" else 403
                raise urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"{}"))
            return PLAIN

        chat.post = fake
        out = ask(chat, {"question": "which part needs service first?"})
        assert keys == ["c-key", "g-key"] and out["answer"].startswith("The belt"), failure
        if failure == "refused":  # a refused key is left out for the next questions
            ask(chat, {"question": "which part needs service first? once more"})
            assert keys.count("c-key") == 1
            assert chat.status()["search"]["lanes"][0]["refused"]


def test_searches_use_the_cloud_budget_first_then_ai_studio(pages):
    chat, keys = with_cloud(), []

    def gemini(url, key, body):
        keys.append(key)
        return GROUNDED

    chat.post_search = gemini
    chat.post_groq = lambda *a: pytest.fail("Groq must not be asked")
    ask(chat, {"question": "what PFHd does PL d need?", "mode": "web"})
    assert keys == ["c-key"] and chat.cloud.budget.used == 1650 and chat.budget.used == 0
    chat.cloud.budget.record(TB.CLOUD.day)  # the cloud budget is spent: the free key searches
    ask(chat, {"question": "which standard sets PL d? tell me from the web", "mode": "web"})
    assert keys == ["c-key", "g-key"] and chat.budget.used == 1650


def test_a_cloud_search_quota_rests_only_the_cloud_lane(pages):
    chat, keys = with_cloud(), []

    def gemini(url, key, body):
        keys.append(key)
        if key == "c-key":
            raise limited("gemini-test")
        return GROUNDED

    chat.post_search = gemini
    ask(chat, {"question": "what PFHd does PL d need?", "mode": "web"})
    assert keys == ["c-key", "g-key"]  # the Studio key searched when the Cloud one was refused
    lanes = {ln["name"]: ln for ln in chat.status()["search"]["lanes"]}
    assert lanes["cloud"]["rest_s"] > 600 and lanes["studio"]["rest_s"] == 0


def test_the_status_lists_the_lanes_and_never_a_key():
    st = with_cloud().status()
    assert [ln["name"] for ln in st["search"]["lanes"]] == ["cloud", "studio"]
    assert "per_question" not in st["search"]["budget"]  # the pacing figures are the operator's
    deep_budget = with_cloud().status(detail=True)["search"]["budget"]["per_question"]["deep"]
    assert deep_budget == TB.CLOUD.deep
    assert "c-key" not in json.dumps(st) and "g-key" not in json.dumps(st)


def test_the_cloud_key_and_its_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_CLOUD_API_KEY", "c-key")
    monkeypatch.setenv("GEMINI_CLOUD_TOKENS_PER_DAY", "1000000")
    monkeypatch.setenv("GEMINI_CLOUD_MODELS", "gemini-3.7-flash, gemini-3-flash-preview")
    c = C.ChatSettings.from_env()
    assert c.cloud_key == "c-key" and c.cloud_limits.day == 1_000_000
    assert c.cloud_limits.deep == TB.CLOUD.deep and c.limits.day == TB.Limits().day
    assert c.cloud_models == ["gemini-3.7-flash", "gemini-3-flash-preview"]
