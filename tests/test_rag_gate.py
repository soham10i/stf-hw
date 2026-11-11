"""The RAG gate (eval_gate.compare_rag) in CI: retrieval and the hallucination detector, measured
offline (hash vectors, a local store, no reranker, no claim judge), may not fall below
tests/golden/rag_baseline.json by more than their tolerances. A change that makes them better
is accepted with `make rag-baseline`; one that makes them worse fails here."""

from __future__ import annotations

import json
import os

import pytest

from services.api.eval import eval_gate, eval_grounding
from services.api.rag import vectors as V

pytest.importorskip("fastapi")

BASELINE = os.path.join(os.path.dirname(__file__), "golden", "rag_baseline.json")


@pytest.fixture(scope="module")
def report():
    mp = pytest.MonkeyPatch()
    for k, v in {"STF_EMBEDDER": "hash", "STF_VECTOR_BACKEND": "sqlite", "STF_RERANKER_URL": "",
                 "STF_CLAIM_JUDGE": "off"}.items():
        mp.setenv(k, v)
    V.reset_store()
    try:
        yield eval_grounding.rag_report()
    finally:
        V.reset_store()
        mp.undo()


def test_retrieval_and_grounding_hold_the_baseline(report):
    with open(BASELINE, encoding="utf-8") as f:
        base = json.load(f)
    out = eval_gate.compare_rag(base, report)
    assert out["passed"], out["failures"]


def test_the_detector_never_flags_a_hand_written_true_claim(report):
    # the policy strips or hedges what is flagged: a false alarm costs an honest answer
    assert report["grounding"]["hand_false_alarm_rate"] == 0.0


def test_every_invented_number_is_caught():
    rows = eval_grounding.run([c for c in eval_grounding.perturbed()][:10])
    numbers = [c for r in rows for c in r["claims"] if c["kind"] == "number"]
    assert numbers and all(c["verdict"] == "unsupported" for c in numbers)
