"""Evaluation promotion gate: same cases, no silent quality/cost/latency regression."""

from services.api.eval_gate import compare


def report(passed=True, p95=10, cost=1, unpriced=0):
    row = {
        "q": "question", "tools_ok": passed, "facts_ok": True, "faithful": True,
        "route_ok": True, "declines": None,
    }
    return {
        "rows": [row],
        "summary": {"overall": {
            "latency_s": {"p95": p95}, "estimated_model_cost_usd": cost,
            "unpriced_calls": unpriced,
        }},
    }


def test_gate_passes_equal_or_better_candidate():
    assert compare(report(), report(cost=1.2))["passed"]


def test_gate_rejects_quality_latency_cost_and_unpriced_regressions():
    out = compare(report(), report(False, p95=100, cost=8, unpriced=2))
    assert not out["passed"] and len(out["failures"]) == 4


def test_gate_rejects_changing_the_question_set():
    before = report()
    after = report()
    after["rows"][0]["q"] = "different"
    assert "candidate questions differ from baseline" in compare(before, after)["failures"]


# --- grounding in the answer reports
def grounded(g=0.9, h=0.1, c=0.5):
    r = report()
    r["summary"]["grounding"] = {"groundedness": g, "hallucination_rate": h,
                                 "citation_coverage": c}
    return r


def test_gate_rejects_a_drop_in_groundedness_or_a_rise_in_hallucinations():
    assert compare(grounded(), grounded(0.88, 0.12, 0.45))["passed"]
    out = compare(grounded(), grounded(0.8, 0.2, 0.3))
    assert not out["passed"] and len(out["failures"]) == 3
    assert compare(report(), grounded())["passed"]  # an old report without grounding: skipped


# --- the RAG gate
def rag(mrr=0.7, recall=0.7, fa=0.0):
    return {"retrieval": {"mrr": mrr, "hit@8": 0.9},
            "grounding": {"precision": 1.0, "recall": recall, "hand_recall": 0.8,
                          "false_alarm_rate": fa, "hand_false_alarm_rate": 0.0,
                          "confidence_auroc": 0.93, "ece": 0.1}}


def test_rag_gate_passes_within_tolerance_and_names_each_regression():
    from services.api.eval_gate import compare_rag

    assert compare_rag(rag(), rag(0.69, 0.68))["passed"]
    out = compare_rag(rag(), rag(0.6, 0.5, 0.1))
    assert not out["passed"]
    assert {f.split(" ")[0] for f in out["failures"]} == {
        "retrieval.mrr", "grounding.recall", "grounding.false_alarm_rate"}
    missing = rag()
    del missing["grounding"]["recall"]
    failures = compare_rag(rag(), missing)["failures"]
    assert "grounding.recall is missing from the candidate" in failures
