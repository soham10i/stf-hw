"""Model usage pricing and shared paid-spend circuit breakers.

Costs are list-price estimates from provider-reported token usage, never invoices. Grounding,
network, tax and currency conversion are excluded. Unknown models are explicitly unpriced rather
than silently treated as free. Override the table with GEMINI_PRICING_JSON when Google changes a
price, for example {"gemini-x": {"input": 1.0, "output": 5.0}} (USD per million tokens).

SpendBudget stores integer micro-USD in the same shared counters as token budgets. It stops new
paid calls at configured daily and optional fixed pilot-window limits; an in-flight call can still
finish, so this is an application circuit breaker, not a billing-account hard cap.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# Verified for the feasibility report on 2026-10-26; USD per million input/output tokens.
GEMINI_PRICES = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}
MICRO = 1_000_000


def usage_parts(data: dict) -> tuple[int, int]:
    """Input and output tokens; Gemini thinking is billed as output."""
    if not isinstance(data, dict):
        return 0, 0
    u = data.get("usageMetadata")
    if u:
        return (
            int((u.get("promptTokenCount") or 0) + (u.get("toolUsePromptTokenCount") or 0)),
            int((u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)),
        )
    u = data.get("usage")
    if u:
        return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
    return int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)


def prices(env: dict | None = None) -> dict[str, tuple[float, float]]:
    """The built-in price table plus validated operator overrides."""
    out = dict(GEMINI_PRICES)
    env = os.environ if env is None else env
    try:
        extra = json.loads(env.get("GEMINI_PRICING_JSON", "{}"))
        for model, row in extra.items():
            i, o = float(row["input"]), float(row["output"])
            if i >= 0 and o >= 0:
                out[str(model)] = (i, o)
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    return out


def estimate(model: str | None, data: dict, env: dict | None = None) -> dict:
    """One response's usage and list-price estimate; priced=False means unknown, not free."""
    input_tokens, output_tokens = usage_parts(data)
    price = prices(env).get(model or "")
    gemini = data.get("usageMetadata") or {}
    openai = data.get("usage") or {}
    reported_total = int(
        gemini.get("totalTokenCount") or openai.get("total_tokens")
        or data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
    )
    complete = input_tokens + output_tokens > 0 or reported_total == 0
    priced = price is not None and complete
    cost = (input_tokens * price[0] + output_tokens * price[1]) / MICRO if priced else 0.0
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 8),
        "priced": priced,
    }


def _utc_day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


@dataclass
class SpendBudget:
    """A daily and optional fixed-window paid-model budget, shared across service instances."""

    daily_limit: float = 5.0
    total_limit: float | None = None
    period_days: int = 60
    period_start: str | None = None
    shared: Any = field(default=None, repr=False)
    name: str = "gemini:cloud"
    clock: Any = field(default=time.time, repr=False)
    _day: str = ""
    _day_micro: int = 0
    _period_micro: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.daily_limit < 0 or (self.total_limit is not None and self.total_limit < 0):
            raise ValueError("spend limits must be non-negative")
        if self.total_limit is not None:
            if not self.period_start or self.period_days < 1:
                raise ValueError(
                    "a pilot spend limit needs GEMINI_CLOUD_BUDGET_START and positive days"
                )
            dt.date.fromisoformat(self.period_start)  # fail fast on an ambiguous budget window

    @property
    def period(self) -> str:
        return f"{self.period_start}:{self.period_days}d"

    def _roll(self, now: float) -> None:
        day = _utc_day(now)
        if day != self._day:
            self._day, self._day_micro = day, 0

    def _shared(self, day: str, suffix: str) -> int:
        return self.shared.total(day, f"{self.name}:{suffix}") if self.shared is not None else 0

    def _period_active(self, now: float) -> bool:
        """A fixed pilot authorizes paid calls only inside [start, start + days)."""
        if self.total_limit is None:
            return True
        start = dt.date.fromisoformat(self.period_start or "")
        today = dt.datetime.fromtimestamp(now, dt.UTC).date()
        return start <= today < start + dt.timedelta(days=self.period_days)

    def allowed(self) -> bool:
        """Whether another paid call may start (an in-flight call is never cancelled)."""
        now = self.clock()
        if not self._period_active(now):
            return False
        with self._lock:
            self._roll(now)
            daily = max(self._day_micro, self._shared(self._day, "cost_micro"))
            period = max(self._period_micro, self._shared(self.period, "cost_micro"))
        if daily >= round(self.daily_limit * MICRO):
            return False
        return not (
            self.total_limit is not None and period >= round(self.total_limit * MICRO)
        )

    def record(self, cost_usd: float) -> None:
        """Record a completed call's positive estimated cost in both applicable windows."""
        micro = max(0, round(cost_usd * MICRO))
        if not micro:
            return
        now = self.clock()
        with self._lock:
            self._roll(now)
            self._day_micro += micro
            self._period_micro += micro
            day = self._day
        if self.shared is not None:
            self.shared.add(day, f"{self.name}:cost_micro", micro)
            if self.total_limit is not None:
                self.shared.add(self.period, f"{self.name}:cost_micro", micro)

    def status(self) -> dict:
        """Operator-facing counters and circuit state; no guest or credential data."""
        now = self.clock()
        with self._lock:
            self._roll(now)
            daily = max(self._day_micro, self._shared(self._day, "cost_micro"))
            period = max(self._period_micro, self._shared(self.period, "cost_micro"))
        out = {
            "allowed": self.allowed(),
            "daily": {
                "estimated_usd": round(daily / MICRO, 6),
                "limit_usd": self.daily_limit,
            },
        }
        if self.total_limit is not None:
            out["pilot"] = {
                "active": self._period_active(now),
                "estimated_usd": round(period / MICRO, 6),
                "limit_usd": self.total_limit,
                "start": self.period_start,
                "days": self.period_days,
            }
        return out
