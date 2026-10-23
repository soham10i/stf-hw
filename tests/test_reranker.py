"""The cross-encoder reranker seam (services/api/vectors.py, Reranker): ordering, failure
fallback, and the hybrid_search integration. No network: keepalive.urlopen is scripted,
the same seam the pgvector tests use."""

from __future__ import annotations

import json
import urllib.error

import pytest

from services.api import vectors as V
from services.api.grounding import Passage

pytest.importorskip("fastapi")


def passages(n: int) -> list[Passage]:
    return [
        Passage(id=i + 1, doc="Docs", path=[f"S{i}"], text=f"passage {i}", file=f"{i}.md")
        for i in range(n)
    ]


def hits_of(ps: list[Passage]) -> list[dict]:
    return [
        {"passage": p, "score": 5.0 - r, "cover": 0.5, "vscore": 0.9, "via": "both", "rrf": 1.0}
        for r, p in enumerate(ps)
    ]


class FakeResp:
    def __init__(self, body):
        self._raw = json.dumps(body).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_scores(monkeypatch, scores, calls: list):
    def handler(req, timeout=0):
        body = json.loads(req.data)
        calls.append(body)
        return FakeResp([{"index": i, "score": s} for i, s in enumerate(scores)])

    monkeypatch.setattr(V.keepalive, "urlopen", handler)
    return calls


# ------------------------------------------------------------------ construction
def test_reranker_is_off_without_url():
    V.reset_reranker()
    assert V.get_reranker({"STF_RERANKER_URL": ""}) is None
    assert V.get_reranker({}) is None
    V.reset_reranker()


def test_reranker_builds_from_url_and_appends_rerank():
    r = V.Reranker("https://tei.example.run")
    assert r.url == "https://tei.example.run/rerank"
    assert V.Reranker("https://tei.example.run/rerank").url == "https://tei.example.run/rerank"


# ------------------------------------------------------------------ ordering
def test_apply_reorders_the_head_and_keeps_the_tail(monkeypatch):
    ps = passages(4)
    r = V.Reranker("http://127.0.0.1:3000", pool=3)
    calls = fake_scores(monkeypatch, [0.1, 0.9, 0.5], [])  # head scores: reorder to 1,2,0
    out = r.apply("q", hits_of(ps))
    assert [h["passage"].id for h in out] == [2, 3, 1, 4]  # head reordered, tail untouched
    assert out[0]["rscore"] == 0.9
    sent = calls[0]
    assert sent["query"] == "q" and len(sent["texts"]) == 3  # only the head went out


def test_apply_sends_path_and_truncates_text(monkeypatch):
    ps = [
        Passage(id=1, doc="Docs", path=["Machine", "Oven"], text="x" * 2000, file="a.md"),
        Passage(id=2, doc="Docs", path=["B"], text="short", file="b.md"),
    ]
    r = V.Reranker("http://127.0.0.1:3000")
    calls = fake_scores(monkeypatch, [0.5, 0.4], [])
    r.apply("q", hits_of(ps))
    text = calls[0]["texts"][0]
    assert text.startswith("Machine Oven ")
    assert len(text) <= V.RERANK_TEXT


def test_apply_needs_at_least_two_candidates():
    r = V.Reranker("http://127.0.0.1:3000")
    assert r.apply("q", hits_of(passages(1))) is None


# ------------------------------------------------------------------ failure fallback
def test_failure_keeps_the_order_and_retries(monkeypatch):
    ps = passages(3)
    r = V.Reranker("http://127.0.0.1:3000")
    calls = []

    def down(req, timeout=0):
        calls.append(1)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(V.keepalive, "urlopen", down)
    original = hits_of(ps)
    assert r.apply("q", original) is None
    assert r._dead is False  # one failure does not disable the reranker (a cold start can time out)
    assert r.apply("q", original) is None
    assert len(calls) == 2


def test_repeated_failures_disable_and_stop_calling(monkeypatch):
    ps = passages(3)
    r = V.Reranker("http://127.0.0.1:3000")
    calls = []

    def down(req, timeout=0):
        calls.append(1)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(V.keepalive, "urlopen", down)
    original = hits_of(ps)
    for _ in range(V.RERANK_MAX_FAILS):
        assert r.apply("q", original) is None
    assert r._dead is True
    n = len(calls)
    assert r.apply("q", original) is None  # no further HTTP attempt once disabled
    assert len(calls) == n


def test_success_resets_the_failure_count(monkeypatch):
    ps = passages(3)
    r = V.Reranker("http://127.0.0.1:3000")
    down_calls = []

    def down(req, timeout=0):
        down_calls.append(1)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(V.keepalive, "urlopen", down)
    original = hits_of(ps)
    for _ in range(V.RERANK_MAX_FAILS - 1):
        assert r.apply("q", original) is None
    fake_scores(monkeypatch, [0.3, 0.2, 0.1], [])  # one success resets the count
    assert r.apply("q", original) is not None
    assert r._dead is False
    monkeypatch.setattr(V.keepalive, "urlopen", down)
    assert r.apply("q", original) is None
    assert r._dead is False  # the earlier failures no longer count


def test_timeout_is_configurable():
    r = V.Reranker("http://127.0.0.1:3000", timeout=42)
    assert r.timeout == 42
    assert V.Reranker("http://127.0.0.1:3000").timeout == V.RERANK_TIMEOUT_S


def test_get_reranker_honours_timeout_env(monkeypatch):
    V.reset_reranker()
    r = V.get_reranker({
        "STF_RERANKER_URL": "https://tei.example.run", "STF_RERANKER_TIMEOUT_S": "7"
    })
    assert r is not None and r.timeout == 7
    V.reset_reranker()


# ------------------------------------------------------------------ hybrid_search integration
def test_hybrid_search_uses_the_reranker_when_one_is_configured(monkeypatch):
    p = passages(3)
    bm25 = [{"passage": x, "score": 9.0 - i, "cover": 0.6} for i, x in enumerate(p)]

    class FakeBm25:
        passages = p

        def search(self, query, top_k=3):
            return bm25[:top_k]

    class FakeStore:
        embedder = V.HashEmbedder()
        name = "fake"

        def top(self, query, k):
            return [(x.id, 0.5) for x in p[:k]]

        def matrix(self):
            return [x.id for x in p], V.HashEmbedder().embed([f"passage {i}" for i in range(3)])

    monkeypatch.setattr(V, "get_bm25", lambda: FakeBm25())
    monkeypatch.setattr(V, "get_store", lambda: FakeStore())
    fake_scores(monkeypatch, [0.2, 0.95, 0.4], [])
    monkeypatch.setattr(V, "get_reranker", lambda: V.Reranker("http://127.0.0.1:3000"))
    out = V.hybrid_search("q", top_k=3)
    assert [h["passage"].id for h in out] == [2, 3, 1]  # 0.95, 0.4, 0.2
    assert out[0]["rscore"] == 0.95


def test_hybrid_search_without_a_reranker_keeps_the_fused_order(monkeypatch):
    monkeypatch.setattr(V, "get_reranker", lambda: None)
    p = passages(2)
    bm25 = [
        {"passage": p[0], "score": 9.0, "cover": 0.6},
        {"passage": p[1], "score": 8.0, "cover": 0.6},
    ]

    class FakeBm25:
        passages = p

        def search(self, query, top_k=3):
            return bm25[:top_k]

    class FakeStore:
        embedder = V.HashEmbedder()
        name = "fake"

        def top(self, query, k):
            return [(p[0].id, 0.5)]

        def matrix(self):
            return [x.id for x in p], V.HashEmbedder().embed(["passage 0", "passage 1"])

    monkeypatch.setattr(V, "get_bm25", lambda: FakeBm25())
    monkeypatch.setattr(V, "get_store", lambda: FakeStore())
    out = V.hybrid_search("q", top_k=2)
    assert [h["passage"].id for h in out] == [1, 2]
    assert "rscore" not in out[0]
