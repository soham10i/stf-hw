"""The vector store and hybrid retrieval (services/api/vectors.py), and the operator's own
OpenAI-compatible provider (services/api/chat.py: openai).

Everything runs on the zero-dependency hash embedder - no model downloads, no network. The
BM25 index and the vector store are replaced with fakes where the fusion rules are the point.
"""

from __future__ import annotations

import io
import json
import urllib.error

import numpy as np
import pytest

from services.api import chat as C
from services.api import security as sec
from services.api import tools as T
from services.api import vectors as V
from services.api.grounding import Passage

pytest.importorskip("fastapi")


def toy_passages() -> list[Passage]:
    return [
        Passage(id=1, doc="Docs", path=["A"], text="the oven heats the belt", file="a.md"),
        Passage(id=2, doc="Docs", path=["B"], text="the robot arm stacks cookies", file="b.md"),
        Passage(id=3, doc="Docs", path=["C"], text="the vision camera judges colour", file="c.md"),
    ]


class FakeBm25:
    """Returns scripted hits; .passages backs the id -> Passage map."""

    def __init__(self, passages, hits):
        self.passages = passages
        self._hits = hits

    def search(self, query, top_k=3):
        return self._hits[:top_k]


class ToyEmbedder(V.Embedder):
    name = "toy"
    dim = 3

    def __init__(self, rows: dict[str, np.ndarray]):
        self.rows = rows

    def embed(self, texts):
        out = np.stack([self.rows[t] for t in texts])
        return out / np.linalg.norm(out, axis=1, keepdims=True)


class FakeStore:
    """Answers top() from a script; matrix()/embedder back the cosine-floor rule."""

    def __init__(self, top, ids, matrix, embedder):
        self._top = top
        self._ids = ids
        self._matrix = matrix
        self.embedder = embedder

    def top(self, query, k):
        return self._top[:k]

    def matrix(self):
        return self._ids, self._matrix


# ---------------------------------------------------------------------- the hash embedder
def test_hash_embedder_is_deterministic_and_normalised():
    e = V.HashEmbedder()
    a = e.embed(["the oven belt heats the oven"])
    b = e.embed(["the oven belt heats the oven"])
    c = e.embed(["a completely different sentence about sorting"])
    assert a.shape == (1, V.DIM)
    np.testing.assert_allclose(a, b)
    assert np.isclose(np.linalg.norm(a[0]), 1.0)
    assert not np.allclose(a, c)


def test_make_embedder_off_and_fallbacks():
    assert V.make_embedder({"STF_EMBEDDER": "off"}) is None
    # a bare "http" without an endpoint, and a "minilm" without the package: both fall back
    h = V.make_embedder({"STF_EMBEDDER": "http"})
    assert isinstance(h, V.HashEmbedder)
    m = V.make_embedder({"STF_EMBEDDER": "minilm"})
    assert isinstance(m, V.HashEmbedder)


# ---------------------------------------------------------------------- the store
def test_store_persists_and_reloads(tmp_path):
    e = ToyEmbedder(
        {"x": np.array([1.0, 0, 0]), "y": np.array([0, 1.0, 0]), "z": np.array([0, 0, 1.0])}
    )
    p = str(tmp_path / "v.sqlite")
    s1 = V.VectorStore(p, e)
    s1.build([10, 11, 12], ["x", "y", "z"])
    s2 = V.VectorStore(p, e)
    ids, m = s2.matrix()
    assert ids == [10, 11, 12]
    assert m.shape == (3, 3)
    assert s2.top("x", 2)[0][0] == 10


def test_store_ready_only_for_the_current_passage_set(tmp_path):
    e = V.HashEmbedder()
    s = V.VectorStore(str(tmp_path / "v.sqlite"), e)
    s.build([1, 2], ["alpha text", "beta text"])
    assert s.ready([1, 2])
    assert not s.ready([1, 2, 3])  # the kb changed: a rebuild is due


# ---------------------------------------------------------------------- hybrid fusion
def _fuse(monkeypatch, bm25_hits, vec_top, floor_rows, query_vec, passages):
    fake_bm = FakeBm25(passages, bm25_hits)
    emb = ToyEmbedder({"q": query_vec})
    ids = [p.id for p in passages]
    matrix = np.stack([floor_rows[pid] for pid in ids])
    matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    fake_store = FakeStore(vec_top, ids, matrix, emb)
    monkeypatch.setattr(V, "get_bm25", lambda: fake_bm)
    monkeypatch.setattr(V, "get_store", lambda: fake_store)
    return V.hybrid_search("q")


def test_hybrid_fuses_bm25_and_vectors(monkeypatch):
    p = toy_passages()
    hits = [
        {"passage": p[0], "score": 5.0, "cover": 0.5},
        {"passage": p[1], "score": 3.0, "cover": 0.3},
    ]
    # vectors rank p0 first too, and surface p2 - but p2's cosine does not clear the margin
    top = [(1, 0.90), (2, 0.50), (3, 0.95)]
    rows = {1: np.array([1.0, 0, 0]), 2: np.array([0, 1.0, 0]), 3: np.array([0, 0, 1.0])}
    out = _fuse(monkeypatch, hits, top, rows, np.array([1.0, 0, 0]), p)
    assert [h["passage"].id for h in out] == [1, 2]  # p3 stays out: 0.95 < 1.0 + margin
    assert out[0]["via"] == "both"
    assert out[0]["vscore"] == pytest.approx(0.90)
    assert out[1]["via"] == "both"  # p2 is in both rankings too
    for h in out:  # the BM25 shape the callers consume is intact
        assert set(h) >= {"passage", "score", "cover", "vscore", "via"}


def test_hybrid_admits_a_semantic_hit_past_the_margin(monkeypatch):
    p = toy_passages()
    hits = [{"passage": p[0], "score": 5.0, "cover": 0.5}]
    # p0 matches lexically but is far in the embedding; p3 is the true semantic neighbour
    top = [(3, 0.99), (1, 0.20)]
    rows = {1: np.array([1.0, 0, 0]), 2: np.array([0, 1.0, 0]), 3: np.array([0, 0, 1.0])}
    out = _fuse(monkeypatch, hits, top, rows, np.array([0, 0, 1.0]), p)
    ids = [h["passage"].id for h in out]
    assert ids == [1, 3]  # the lexical hit still leads under RRF; the semantic one joins it
    assert out[1]["via"] == "vector"
    assert out[1]["score"] == 0.0  # no lexical score: proven by meaning, not by words
    assert out[1]["vscore"] == pytest.approx(0.99)


def test_hybrid_without_a_store_is_pure_bm25(monkeypatch):
    p = toy_passages()
    hits = [{"passage": p[0], "score": 5.0, "cover": 0.5}]
    monkeypatch.setattr(V, "get_bm25", lambda: FakeBm25(p, hits))
    monkeypatch.setattr(V, "get_store", lambda: None)
    out = V.hybrid_search("anything")
    assert [h["passage"].id for h in out] == [1]
    assert out[0]["vscore"] == 0.0 and out[0]["via"] == "bm25"


# ---------------------------------------------------------------------- search_docs on top
def test_search_docs_shape_and_off_switch(monkeypatch):
    monkeypatch.setenv("STF_EMBEDDER", "off")
    V.reset_store()
    r = T.search_docs({"query": "oven process heating"}, T.Ctx())
    assert r.tool == "search_docs"
    if r.facts:  # the real kb may or may not cover it; either way cites stay well-formed
        assert all(set(c) >= {"label", "file", "line", "score", "quote"} for c in r.cites)
    r2 = T.search_docs({"query": "qxz9 wk2p jm8t vb4n"}, T.Ctx())
    assert r2.facts == [] and "No document covers" in r2.text


def test_copilot_setup_reports_retrieval(monkeypatch):
    monkeypatch.setenv("STF_EMBEDDER", "off")
    V.reset_store()
    r = T.copilot_setup({}, T.Ctx())
    assert any("BM25" in f[1] for f in r.facts if f[0] == "document retrieval")


# ---------------------------------------------------------------------- the openai provider
def _chat(**settings):
    base = dict(key="k", model="gemini-test", daily_limit=100)
    base.update(settings)
    return C.Chat(sec.Settings.from_env(), C.ChatSettings(**base))


def test_openai_settings_from_env(monkeypatch):
    for k in ("OPENAI_API_KEY", "OPENAI_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "Qwen/Test-7B")
    c = C.ChatSettings.from_env()
    assert c.openai_url == "https://llm.example.test/v1"
    assert c.openai_model == "Qwen/Test-7B"
    assert c.openai_key is None  # a local vLLM server takes no key


def test_openai_joins_the_chain_after_upb_before_ollama(monkeypatch):
    chat = _chat(
        openai_url="https://llm.example.test/v1", openai_key=None, ollama_model="qwen"
    )
    names = [p["name"] for p in chat.status()["order"]]
    assert names.index("openai") < names.index("ollama")
    assert chat.status()["openai"] is True
    assert chat.status()["model"] == "gemini-test"  # Gemini still answers first


def test_openai_answers_and_cools_on_limit(monkeypatch):
    chat = _chat(openai_url="https://llm.example.test/v1", openai_key="")

    def ok_post(url, key, body):
        return {"choices": [{"message": {"content": "Understood."}}]}

    monkeypatch.setattr(chat, "post_groq", ok_post)
    text, bad = chat.converse(
        "openai",
        C.ChatRequest(question="say OK", provider="auto"), T.Ctx(), [], [], lambda t: [], {}
    )
    assert text == "Understood." and bad == []

    def busy_post(url, key, body):
        raise urllib.error.HTTPError(
            url, 429, "rate limit", {}, io.BytesIO(json.dumps({"error": "slow down"}).encode())
        )

    monkeypatch.setattr(chat, "post_groq", busy_post)
    with pytest.raises(C.ModelError) as e:
        chat.converse(
            "openai",
            C.ChatRequest(question="again", provider="auto"), T.Ctx(), [], [], lambda t: [], {}
        )
    assert e.value.cool and e.value.cool > 0
