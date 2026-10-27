"""Phase 0/1 evaluation artifacts retain comparable per-route operational metrics."""

from services.api import eval_copilot as E


def row(route="twin", seconds=1.0, cost=0.02, **kw):
    return {
        "q": "q", "held_out": False, "route": route, "route_ok": True,
        "tools_ok": True, "facts_ok": True, "faithful": True, "declines": None,
        "model": "gemini-test", "note": None, "s": seconds,
        "usage": {"tokens": 100, "input_tokens": 80, "output_tokens": 20,
                  "estimated_model_cost_usd": cost},
        "search_attempts": 0, "search_failures": 0, "web_sources": 0,
        **kw,
    }


def test_summary_has_per_route_quality_latency_search_and_cost():
    rows = [row(), row(seconds=3, cost=0.03),
            row(route="web", seconds=8, cost=0.1, search_attempts=2,
                search_failures=1, web_sources=4, note="search unavailable")]
    out = E.summarize(rows, "gemini")
    assert out["overall"]["quality_passed"] == 3
    assert out["overall"]["tokens"] == 300
    assert out["overall"]["estimated_model_cost_usd"] == 0.15
    assert out["overall"]["latency_s"]["p50"] == 3
    assert out["by_route"]["web"]["search_failures"] == 1
    assert out["by_route"]["web"]["failures"] == 1
    assert out["by_route"]["web"]["web_sources"] == 4


def test_route_regression_does_not_pass_quality_gate():
    out = E.summarize([row(route_ok=False)], "gemini")
    assert out["overall"]["quality_passed"] == 0


def test_percentile_handles_empty_and_interpolates():
    assert E.percentile([], 0.95) == 0
    assert E.percentile([1, 2, 3, 4], 0.5) == 2.5
