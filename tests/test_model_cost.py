"""Model-aware cost telemetry and paid-spend circuit-breaker units."""

import pytest

from services.api import model_cost as MC
from services.api import token_budget as TB


def test_gemini_usage_prices_input_output_and_thinking_separately():
    data = {"usageMetadata": {
        "promptTokenCount": 14_000,
        "toolUsePromptTokenCount": 1_000,
        "candidatesTokenCount": 2_000,
        "thoughtsTokenCount": 500,
        "totalTokenCount": 17_500,
    }}
    row = MC.estimate("gemini-3.8-flash", data)
    assert row == {
        "input_tokens": 15_000,
        "output_tokens": 2_500,
        "cost_usd": 0.020625,
        "priced": True,
    }


def test_unknown_model_is_unpriced_not_claimed_free():
    row = MC.estimate("future-model", {"usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    assert row["cost_usd"] == 0 and row["priced"] is False


def test_operator_price_override():
    env = {"GEMINI_PRICING_JSON": '{"future-model":{"input":2,"output":4}}'}
    row = MC.estimate(
        "future-model", {"usage": {"prompt_tokens": 100, "completion_tokens": 50}}, env
    )
    assert row["priced"] and row["cost_usd"] == pytest.approx(0.0004)


def test_request_meter_collects_model_and_cost_breakdown():
    m = TB.meter_start()
    TB.meter("gemini", {"usageMetadata": {"totalTokenCount": 1100}})
    TB.meter_model("gemini", "gemini-3.8-flash", {"usageMetadata": {
        "promptTokenCount": 1000, "candidatesTokenCount": 100}})
    TB.meter_model("groq", "groq openai/gpt-oss-120b", {
        "usage": {"prompt_tokens": 20, "completion_tokens": 5}})
    assert m["tokens"] == 1100
    assert m["input_tokens"] == 1020 and m["output_tokens"] == 105
    assert m["estimated_model_cost_usd"] == pytest.approx(0.001125)
    assert m["models"]["gemini:gemini-3.8-flash"]["calls"] == 1
    assert m.get("unpriced_calls", 0) == 0  # non-Gemini providers are outside this estimate


def test_daily_circuit_opens_and_utc_day_resets():
    now = [1_800_000_000.0]
    budget = MC.SpendBudget(daily_limit=1.0, clock=lambda: now[0])
    budget.record(0.25)
    assert budget.allowed()
    budget.record(0.75)
    assert not budget.allowed()
    assert budget.status()["daily"]["estimated_usd"] == 1.0
    now[0] += 86_400
    assert budget.allowed()


def test_pilot_window_requires_explicit_start_and_enforces_total_and_expiry():
    with pytest.raises(ValueError, match="BUDGET_START"):
        MC.SpendBudget(total_limit=100)
    now = [MC.dt.datetime(2026, 10, 27, tzinfo=MC.dt.UTC).timestamp()]
    budget = MC.SpendBudget(
        total_limit=2,
        period_start="2026-10-27",
        period_days=60,
        clock=lambda: now[0],
    )
    budget.record(1)
    assert budget.allowed() and budget.status()["pilot"]["active"]
    budget.record(1)
    status = budget.status()
    assert not status["allowed"] and status["pilot"]["days"] == 60
    now[0] -= 86_400
    assert not budget.allowed() and not budget.status()["pilot"]["active"]
    now[0] += 61 * 86_400
    assert not budget.allowed() and not budget.status()["pilot"]["active"]
