"""The retrieval eval harness (services/api/eval_retrieval.py): golden-set sanity in CI.

Thresholds are floors against regressions, tuned below the observed baseline (hash
embedder, SQLite store, offline): a change that drops retrieval below them fails the
suite. The CLI report is the tool for tuning; this file only guards the floor.
"""

from __future__ import annotations

import pytest

from services.api import eval_retrieval as ER
from services.api import grounding
from services.api import vectors as V

pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def result():
    return ER.score()


def test_golden_sources_are_in_the_knowledge_base():
    # a renamed or dropped doc must update the golden set loudly, not silently
    files = {p.file for p in grounding.get_bm25().passages}
    missing = [g["file"] for g in ER.GOLDEN if g["file"] not in files]
    assert not missing, f"golden sources missing from the kb: {missing}"


def test_metrics_are_within_bounds(result):
    assert result["n"] == len(ER.GOLDEN)
    assert set(result["metrics"]) == {"all", "lex", "sem"}
    for mode, m in result["metrics"].items():
        assert 0.0 <= m["hit@1"] <= m["hit@3"] <= m["hit@8"] <= 1.0, mode
        assert 0.0 <= m["mrr"] <= 1.0 and 0.0 <= m["ndcg"] <= 1.0, mode
        assert m["n"] == (len(ER.GOLDEN) if mode == "all" else len(ER.GOLDEN) // 2)


def test_baseline_floors(result):
    # floors under the observed baseline (hash embedder): a regression in BM25, the
    # fusion rule or the embedder drops a metric below these and fails the suite
    all_, lex, sem = result["metrics"]["all"], result["metrics"]["lex"], result["metrics"]["sem"]
    assert all_["hit@8"] >= 0.75, all_
    assert lex["hit@3"] >= 0.5, lex
    assert sem["hit@5"] >= 0.75, sem
    assert all_["mrr"] >= 0.5, all_


def test_lexical_anchors_hit_at_rank_one(result):
    # the obvious word-for-word questions must be answered by the very top hit -
    # a miss here means BM25 itself broke, not the fusion or the vectors
    anchors = [g for g in ER.GOLDEN if g["mode"] == "lex"]
    by_q = {q["q"]: q for q in result["questions"]}
    hits = sum(1 for g in anchors if by_q[g["q"]]["best_rank"] == 1)
    assert hits >= 4, [by_q[g["q"]] for g in anchors]


def test_scoring_is_deterministic(result):
    again = ER.score()
    assert again["questions"] == result["questions"]


def test_bm25_only_run_still_answers_the_lexical_half(monkeypatch):
    # with vectors off the harness still runs and BM25 carries its half - the report
    # stays meaningful on a host with no embedder at all
    monkeypatch.setenv("STF_EMBEDDER", "off")
    V.reset_store()
    try:
        r = ER.score()
    finally:
        V.reset_store()
    assert r["backend"] == "bm25"
    assert r["metrics"]["lex"]["hit@5"] >= 0.5, r["metrics"]
