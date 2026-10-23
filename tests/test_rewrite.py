"""Query rewriting for hybrid retrieval (services/api/rewrite.py).

Spell-fix runs against a toy vocabulary; the hybrid-search tests reuse the
vectors.py fakes to check which rewritten query reaches BM25 and the store.
"""

from __future__ import annotations

import numpy as np
import pytest

from services.api import rewrite as R
from services.api import vectors as V
from services.api.grounding import Passage

pytest.importorskip("fastapi")

VOCAB_TEXT = "the oven heats the belt to one hundred eighty degrees celsius"


class ToyBm25:
    def __init__(self, passages, hits=()):
        self.passages = passages
        self.queries: list[str] = []  # what search() actually received

    def search(self, query, top_k=3):
        self.queries.append(query)
        return []


class ToyStore:
    def __init__(self, embedder):
        self.embedder = embedder
        self.queries: list[str] = []

    def top(self, query, k):
        self.queries.append(query)
        return []

    def matrix(self):
        return [], np.zeros((0, V.DIM))


@pytest.fixture()
def vocab_bm25(monkeypatch):
    p = [Passage(id=1, doc="Docs", path=["A"], text=VOCAB_TEXT, file="a.md")]
    bm = ToyBm25(p)
    monkeypatch.setattr(R, "get_bm25", lambda: bm)  # rewrite's own binding
    monkeypatch.setattr(V, "get_bm25", lambda: bm)  # and vectors' (returns no hits)
    R.reset()
    yield bm
    R.reset()


# ---------------------------------------------------------------------- spell_fix

def test_spell_fix_corrects_transposed_letters(vocab_bm25):
    assert R.spell_fix("what does the ovne do") == "what does the oven do"


def test_spell_fix_leaves_known_words_and_gibberish(vocab_bm25):
    assert R.spell_fix("oven belt") == "oven belt"
    assert R.spell_fix("qxzvt") == "qxzvt"  # no candidate within distance 2


def test_spell_fix_keeps_casing_and_punctuation(vocab_bm25):
    assert R.spell_fix("Ovne,") == "Oven,"
    assert R.spell_fix("the ovne.") == "the oven."


def test_spell_fix_picks_the_more_frequent_word(vocab_bm25):
    # "belt" appears twice in the corpus, "bolt" zero: "bol t" style misspelling of
    # the rarer-looking neighbour should still land on a real word
    assert R.spell_fix("belk") == "belt"


# regression tests from the 2026-10-23 validation run against the real corpus

def test_spell_fix_never_corrects_stopwords(vocab_bm25):
    # "what" is not in the toy corpus vocab; without the guard it was corrected to
    # the closest kb term ("chat" in the real corpus)
    assert R.spell_fix("what is heat") == "what is heat"


def test_spell_fix_prefers_a_nearby_function_word(vocab_bm25):
    # "dose" is a real noun but as a typo it stands for "does", not "done"
    assert R.spell_fix("why dose the belt warn") == "why does the belt warn"


def test_spell_fix_skips_identifiers_with_digits(vocab_bm25):
    assert R.spell_fix("the 24v motor") == "the 24v motor"


# ---------------------------------------------------------------------- expand

def test_expand_adds_page_vocabulary():
    q = R.expand("why is it yellow", "dashboard-quality")
    assert q.startswith("why is it yellow ")
    assert "vision" in q and "quality" in q
    # second expansion of the same text must not duplicate terms
    assert R.expand(q, "dashboard-quality") == q


def test_expand_without_page_is_identity():
    assert R.expand("why is it yellow", None) == "why is it yellow"
    assert R.expand("why is it yellow", "no-such-page") == "why is it yellow"


def test_vector_query_expands_only_when_bm25_empty():
    assert R.vector_query("yellow", "dashboard-quality", bm25_empty=True) != "yellow"
    assert R.vector_query("yellow", "dashboard-quality", bm25_empty=False) == "yellow"


# ---------------------------------------------------------------------- wiring

def test_hybrid_search_uses_spell_fixed_query_for_bm25(monkeypatch, vocab_bm25):
    store = ToyStore(V.HashEmbedder())
    monkeypatch.setattr(V, "get_store", lambda: store)
    V.hybrid_search("ovne temprature", top_k=3)
    # the lexical search is the first .search() call; later probes (_bm25_cosines)
    # intentionally re-issue the ORIGINAL query for the cosine-floor rule
    assert vocab_bm25.queries[0] == "oven temprature"


def test_hybrid_search_expands_vector_query_when_bm25_empty(monkeypatch, vocab_bm25):
    store = ToyStore(V.HashEmbedder())
    monkeypatch.setattr(V, "get_store", lambda: store)
    V.hybrid_search("yellow", top_k=3, page="dashboard-quality")
    assert store.queries == [R.expand("yellow", "dashboard-quality")]
