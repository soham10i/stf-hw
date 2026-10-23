"""The copilot's source policy, answer depth, token meter and literature search."""

from __future__ import annotations

import asyncio
import io
import json

from services.api import chat as C
from services.api import depth as D
from services.api import scholar as SCH
from services.api import source_policy as SP
from services.api import token_budget as TB
from services.api import websearch as W
from tests.test_orchestrate import groq_chat, req


# ------------------------------------------------------------------ grades
def test_hosts_are_graded():
    assert SP.grade("https://www.iso.org/standard/73481.html") == "authoritative"
    assert SP.grade("https://www.nist.gov/x") == "authoritative"
    assert SP.grade("https://ocw.mit.edu/x") == "authoritative"  # .edu by suffix
    assert SP.grade("https://www.cam.ac.uk/x") == "authoritative"  # .ac.uk by suffix
    assert SP.grade("https://doi.org/10.3390/machines11020276") == "authoritative"
    assert SP.grade("https://en.wikipedia.org/wiki/PLC") == "reference"
    assert SP.grade("https://plc-blog.example/pl-d") == "community"
    for bad in (
        "https://www.reddit.com/r/PLC/comments/x",
        "https://old.reddit.com/r/x",
        "https://www.quora.com/What-is",
        "https://x.com/someone/status/1",
        "https://boards.4chan.org/g/",
        "https://www.tiktok.com/@x",
    ):
        assert SP.grade(bad) == "blocked", bad
    # a look-alike host is not the real one
    assert SP.grade("https://iso.org.evil.example/") == "community"
    assert SP.grade("https://notreddit.com/") == "community"


def test_the_operator_can_extend_the_lists(monkeypatch):
    monkeypatch.setenv("STF_SOURCES_BLOCK", "spam.example")
    monkeypatch.setenv("STF_SOURCES_TRUST", "my-lab.example")
    assert SP.grade("https://a.spam.example/") == "blocked"
    assert SP.grade("https://my-lab.example/report") == "authoritative"


def test_levels():
    assert SP.allowed("https://plc-blog.example/", "vetted")
    assert not SP.allowed("https://plc-blog.example/", "strict")
    assert SP.allowed("https://en.wikipedia.org/wiki/x", "strict")
    assert not SP.allowed("https://reddit.com/r/x", "vetted")
    assert "Reddit" in SP.rules("vetted") and "ONLY" in SP.rules("strict")


def test_clean_drops_blocked_pages_from_sources_and_links():
    f = W.Found(
        text="PL d [ISO](https://www.iso.org/a) is common [a thread](https://www.reddit.com/r/PLC/1).",
        sources=[
            {"url": "https://www.reddit.com/r/PLC/1", "title": "thread", "cited": True},
            {"url": "https://plc-blog.example/x", "title": "blog", "cited": False},
            {"url": "https://www.iso.org/a", "title": "ISO", "cited": True},
        ],
    )
    out, n = SP.clean(f, "vetted")
    assert n == 1  # one page, cited twice over
    assert "reddit" not in out.text and "[ISO](https://www.iso.org/a)" in out.text
    assert [s["url"] for s in out.sources] == [
        "https://www.iso.org/a",
        "https://plc-blog.example/x",
    ]
    assert out.sources[0]["grade"] == "authoritative" and out.sources[0]["trusted"]
    strict, n = SP.clean(
        W.Found(text="", sources=[{"url": "https://plc-blog.example/x", "title": "b"}]), "strict"
    )
    assert n == 1 and strict.sources == []


def test_duckduckgo_leaves_blocked_hosts_out(monkeypatch):
    sent = {}
    html = (
        '<a class="result__a" href="https://www.reddit.com/r/PLC/1">Thread</a>'
        '<a class="result__snippet">x</a>'
        '<a class="result__a" href="https://www.iso.org/a">ISO</a>'
        '<a class="result__snippet">y</a>'
    )

    def fake_get(url, data=None, timeout=20):
        sent["q"] = data.decode()
        return html

    monkeypatch.setattr(W, "_get", fake_get)
    rows = W.ddg_search("PL d")
    assert [r["url"] for r in rows] == ["https://www.iso.org/a"]
    assert "-site%3Areddit.com" in sent["q"]


# ------------------------------------------------------------------ depth
def test_depth_is_picked_from_the_route_or_the_operator():
    assert D.pick(None, "deep", "research").name == "thorough"
    assert D.pick(None, "twin", "status").name == "brief"
    assert D.pick(None, "docs", "explain").name == "standard"
    assert D.pick("brief", "deep", "research").name == "brief"  # the operator's choice wins
    assert "researcher" in D.instruction(D.PROFILES["thorough"], "researcher")


def test_groq_is_given_the_depths_length():
    b = C.groq_model({"max_tokens": 1500}, "openai/gpt-oss-120b", max_tokens=6000)
    assert b["max_tokens"] == 6000
    assert C.groq_model({}, "openai/gpt-oss-120b", long=True)["max_tokens"] == 4000


def test_a_request_over_the_tokens_per_minute_is_retried_shorter():
    chat = groq_chat()
    sizes = []

    def fake(url, key, body):
        sizes.append(body["max_tokens"])
        if body["max_tokens"] > 4000:
            err = json.dumps({"error": {"message": "Request too large: tokens per minute"}})
            raise C.urllib.error.HTTPError("u", 413, "too large", {}, io.BytesIO(err.encode()))
        return {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 900}}

    chat.post_groq = fake
    out = asyncio.run(
        chat.ask(
            C.ChatRequest(
                question="which part needs service first?", provider="groq", depth="thorough"
            ),
            req(),
        )
    )
    assert sizes[:2] == [6000, 3000]
    assert out["answer"] == "ok" and out["usage"]["depth"] == "thorough"


# ------------------------------------------------------------------ the token meter
def test_the_meter_counts_every_shape():
    m = TB.meter_start()
    TB.meter("gemini", {"usageMetadata": {"totalTokenCount": 120}})
    TB.meter("groq", {"usage": {"total_tokens": 80}})
    TB.meter("local", {"prompt_eval_count": 10, "eval_count": 5})
    assert m == {"tokens": 215, "calls": 3, "by": {"gemini": 120, "groq": 80, "local": 15}}


# ------------------------------------------------------------------ the literature
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, data):
        self.data, self.url = data, ""

    def open(self, request, timeout=0):
        self.url = request.full_url
        return _Resp(json.dumps(self.data).encode())


def test_openalex_works_come_back_with_their_abstracts():
    op = _Opener(
        {
            "results": [
                {
                    "doi": "https://doi.org/10.3390/machines11020276",
                    "title": "Digital Twins for Virtual Commissioning",
                    "publication_year": 2023,
                    "cited_by_count": 31,
                    "primary_location": {"source": {"display_name": "Machines"}},
                    "abstract_inverted_index": {"twins": [1], "Digital": [0], "commission": [2]},
                    "authorships": [{"author": {"display_name": "A. Author"}}],
                }
            ]
        }
    )
    f = SCH.found("virtual commissioning", 3, op)
    assert "search=virtual+commissioning" in op.url and "has_abstract%3Atrue" in op.url
    assert f.sources[0]["url"] == "https://doi.org/10.3390/machines11020276"
    assert f.sources[0]["grade"] == "authoritative"
    assert "Digital twins commission" in f.text and "Machines" in f.text
    assert f.pages == "Digital twins commission"


def test_the_literature_is_off_in_tests():
    assert SCH.works("anything") == []
