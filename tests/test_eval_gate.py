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
