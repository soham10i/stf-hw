"""
Gemini token accounting for the copilot: what has been spent, what a search may spend now.

A question that searches the web costs tokens - the twin's context going in, the model's thinking
and answer coming out, a few grounded searches for a deep research. This module counts them from
the `usageMetadata` Google returns and sets, for each search, an *allowance* that shrinks as the
budget is used, so the service degrades gradually (shorter context, less thinking, fewer
sub-searches) instead of running dry and failing:

  tier      the budget left (the smallest of the day's, the minute's and the guest's share)
  full      more than half left: the whole context, some thinking, up to four sub-searches
  lean      a fifth to a half: half the context, little thinking, three sub-searches
  minimal   5 % to 20 %: a short context, no thinking, two sub-searches
  spent     under 5 %, or no grounded searches left today: no Gemini search; the caller hands
            the question to the next provider (Groq, DuckDuckGo)

These are the operator's own limits, set below Google's quotas so the key is never run into a
wall by one busy hour or one visitor. Counters live in memory (they restart with the service,
like the question cap in chat.py).

  GEMINI_TOKENS_PER_DAY      all Gemini tokens a UTC day, whole service      (default 600000)
  GEMINI_TOKENS_PER_MINUTE   in any rolling minute                           (default 120000)
  GEMINI_TOKENS_PER_GUEST    one guest's share of the day                    (default 80000)
  GEMINI_WEB_TOKENS          the most one web search may use                 (default 8000)
  GEMINI_DEEP_TOKENS         the most one deep research may use              (default 40000)
  GEMINI_SEARCHES_PER_DAY    grounded Google searches a day                  (default 200)
"""

from __future__ import annotations

import contextvars
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .logging_config import get_logger

logger = get_logger(__name__)

WINDOW_S = 60.0
PLAN_TOKENS = 800  # the planner's call in a deep research, reserved
WRITEUP_TOKENS = 4096  # the answer written from a deep research's findings, reserved
FLOOR = 512  # a search needs at least this much beyond its prompt to say anything

# the tier table: what a search may do while this much of the budget is left
TIERS: dict[str, dict] = {
    "full": dict(over=0.5, web=4096, per=2048, searches=4, url=True, thinking=2048, context=12000),
    "lean": dict(over=0.2, web=2048, per=1536, searches=3, url=False, thinking=512, context=6000),
    "minimal": dict(over=0.05, web=1024, per=1024, searches=2, url=False, thinking=0, context=2500),
}


def est_tokens(text: str) -> int:
    """A prompt's tokens before it is sent: about one per three characters (a safe over-count)."""
    return len(text) // 3 + 1


def usage_tokens(data: dict) -> int:
    """The tokens one Gemini response used, from its usageMetadata (prompt, answer and thinking)."""
    u = data.get("usageMetadata") or {}
    if u.get("totalTokenCount"):
        return int(u["totalTokenCount"])
    return int(
        sum(
            u.get(k) or 0
            for k in (
                "promptTokenCount",
                "candidatesTokenCount",
                "thoughtsTokenCount",
                "toolUsePromptTokenCount",
            )
        )
    )


# ------------------------------------------------------------------ one question's meter
"""Every model call a question makes, whoever answers it, adds its tokens to the question's meter
(a context variable: asyncio.to_thread and the deep research's sub-searches carry it along), so
the reply can say what it cost: {"tokens", "calls", "by": {provider: tokens}}."""
_METER: contextvars.ContextVar[dict | None] = contextvars.ContextVar("stf_meter", default=None)


def meter_start() -> dict:
    """Open a per-request meter (context-local); paired with `meter` calls, read by the API."""
    m: dict = {"tokens": 0, "calls": 0, "by": {}}
    _METER.set(m)
    return m


def any_tokens(data: dict) -> int:
    """A response's tokens in any of the three shapes: Gemini, OpenAI-compatible, Ollama."""
    if not isinstance(data, dict):
        return 0
    n = usage_tokens(data)
    if n:
        return n
    u = data.get("usage") or {}
    if u.get("total_tokens"):
        return int(u["total_tokens"])
    if u:
        return int((u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0))
    return int((data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0))


def meter(provider: str, data: dict) -> None:
    """Add one response's token count to the current request's meter."""
    m = _METER.get()
    if m is None:
        return
    n = any_tokens(data)
    m["calls"] += 1
    m["tokens"] += n
    m["by"][provider] = m["by"].get(provider, 0) + n


def searches_in(data: dict) -> int:
    """The grounded Google searches a response ran (its groundingMetadata's webSearchQueries)."""
    n = 0
    for c in data.get("candidates") or []:
        n += len((c.get("groundingMetadata") or {}).get("webSearchQueries") or [])
    return n


@dataclass(frozen=True)
class Limits:
    """Token ceilings for a provider account: per day, minute, guest, and per task kind."""

    day: int = 600_000
    minute: int = 120_000
    guest: int = 80_000
    web: int = 8_000
    deep: int = 40_000
    searches: int = 200

    @classmethod
    def from_env(cls, env: dict, prefix: str = "GEMINI", base: Limits | None = None) -> Limits:
        """The limits from `{prefix}_TOKENS_PER_DAY` and its siblings; `base` gives the defaults."""

        def n(name: str, default: int) -> int:
            """One integer env var clamped to non-negative, defaulting on garbage."""
            try:
                return max(0, int(env.get(f"{prefix}_{name}", default)))
            except (TypeError, ValueError):
                return default

        d = base or cls()
        return cls(
            day=n("TOKENS_PER_DAY", d.day),
            minute=n("TOKENS_PER_MINUTE", d.minute),
            guest=n("TOKENS_PER_GUEST", d.guest),
            web=n("WEB_TOKENS", d.web),
            deep=n("DEEP_TOKENS", d.deep),
            searches=n("SEARCHES_PER_DAY", d.searches),
        )


# a billed Google Cloud project has far more room than the free key: its own, larger defaults
CLOUD = Limits(day=4_000_000, minute=800_000, guest=400_000, web=16_000, deep=80_000, searches=300)


@dataclass(frozen=True)
class Allowance:
    """What one search may do now: set by the tier, bounded by what is left."""

    tier: str
    mode: str  # "web" or "deep"
    max_output: int  # a call's maxOutputTokens (thinking counts against it)
    thinking: int  # a 2.5 model's thinkingBudget; 0 = none
    thoughts: bool  # ask for the thought summary
    url_context: bool  # let the model read whole pages (Gemini's URL context tool)
    context_chars: int  # how much of the twin's context goes in
    searches: int  # sub-searches (deep); 1 for a web search
    ceiling: int  # the most tokens the whole question may use

    def as_dict(self) -> dict:
        """The status-payload subset of the allowance."""
        return {
            "tier": self.tier,
            "max_output": self.max_output,
            "searches": self.searches,
            "ceiling": self.ceiling,
        }


@dataclass
class TokenBudget:
    """Spend tracker enforcing `Limits`: one instance per provider account, shared across
    workers."""

    limits: Limits = field(default_factory=Limits)
    clock: object = field(default=time.time, repr=False)
    day: str = ""
    used: int = 0
    queries: int = 0
    _guests: dict[str, int] = field(default_factory=dict)
    _recent: deque = field(default_factory=deque)  # (time, tokens) in the last minute
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # the day's totals shared with every other instance and with earlier ones (usage.py), so a
    # restart (Cloud Run's scale to zero) or a second instance cannot reset the daily limit;
    # `name` keys this budget's rows (one per Gemini key)
    shared: Any = field(default=None, repr=False)
    name: str = "gemini"

    # ---------------------------------------------------------------- counting
    def _roll(self, now: float) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime(now))
        if today != self.day:
            self.day, self.used, self.queries = today, 0, 0
            self._guests.clear()
        while self._recent and self._recent[0][0] <= now - WINDOW_S:
            self._recent.popleft()

    def record(self, tokens: int, guest: str | None = None, queries: int = 0) -> None:
        """Count a response's tokens (and the grounded searches it ran)."""
        if tokens <= 0 and queries <= 0:
            return
        now = self.clock()  # type: ignore[operator]
        with self._lock:
            self._roll(now)
            self.used += max(0, tokens)
            self.queries += max(0, queries)
            if guest:
                self._guests[guest] = self._guests.get(guest, 0) + max(0, tokens)
            if tokens > 0:
                self._recent.append((now, tokens))
            day = self.day
        if self.shared is not None:
            self.shared.add(day, f"{self.name}:tokens", max(0, tokens))
            self.shared.add(day, f"{self.name}:searches", max(0, queries))

    def left(self, guest: str | None = None) -> dict:
        """Tokens left in each window, and grounded searches left today."""
        now = self.clock()  # type: ignore[operator]
        with self._lock:
            self._roll(now)
            lim = self.limits
            used, queries = self.used, self.queries
            if self.shared is not None:
                used = max(used, self.shared.total(self.day, f"{self.name}:tokens"))
                queries = max(queries, self.shared.total(self.day, f"{self.name}:searches"))
            out = {
                "day": max(0, lim.day - used),
                "minute": max(0, lim.minute - sum(t for _, t in self._recent)),
                "searches": max(0, lim.searches - queries),
            }
            if guest:
                out["guest"] = max(0, lim.guest - self._guests.get(guest, 0))
            return out

    def fraction(self, guest: str | None = None) -> float:
        """The share of the tightest window still free, 0..1."""
        left, lim = self.left(guest), self.limits
        shares = [
            left["day"] / lim.day if lim.day else 0.0,
            left["minute"] / lim.minute if lim.minute else 0.0,
        ]
        if guest and lim.guest:
            shares.append(left["guest"] / lim.guest)
        return min(shares)

    def tier(self, guest: str | None = None) -> str:
        """The spending tier name for the remaining budget ('ok', 'tight', 'last', ...)."""
        frac = self.fraction(guest)
        for name, row in TIERS.items():
            if frac > row["over"]:
                return name
        return "spent"

    # ---------------------------------------------------------------- allowing
    def allow(self, mode: str, prompt_tokens: int, guest: str | None = None) -> Allowance | None:
        """What a `web` or `deep` search may do now, or None when the budget cannot afford one:
        the tier is spent, no grounded searches are left, or the question does not fit."""
        left = self.left(guest)
        tier = self.tier(guest)
        if tier == "spent" or left["searches"] < 1:
            return None
        row = TIERS[tier]
        cap = self.limits.deep if mode == "deep" else self.limits.web
        ceiling = min(cap, left["day"], left["minute"], left.get("guest", cap))
        per_call = row["per"] if mode == "deep" else row["web"]
        cost = prompt_tokens + per_call  # one search, at its most
        searches = 1
        if mode == "deep":
            usable = ceiling - PLAN_TOKENS - WRITEUP_TOKENS
            searches = min(row["searches"], left["searches"], usable // max(1, cost))
        if searches < 1 or ceiling < prompt_tokens + FLOOR:
            logger.info(
                "Gemini %s search does not fit the budget: tier=%s, ceiling=%d, prompt=%d",
                mode,
                tier,
                ceiling,
                prompt_tokens,
            )
            return None
        return Allowance(
            tier=tier,
            mode=mode,
            max_output=min(per_call, max(FLOOR, ceiling - prompt_tokens)),
            thinking=row["thinking"],
            thoughts=tier == "full",
            url_context=row["url"] and mode == "deep",
            context_chars=row["context"],
            searches=int(searches),
            ceiling=int(ceiling),
        )

    def status(self, detail: bool = False) -> dict:
        """The budget as the status endpoint shows it (no guest's own figures). Public: the tier
        and the day's totals the copilot's settings draw. `detail` (the operator's
        /admin/status) adds the minute window and the per-question and per-guest allowances,
        which would tell a visitor exactly how to pace a run at the limits."""
        left, lim = self.left(), self.limits
        out = {
            "tier": self.tier(),
            "tokens_day": {"used": lim.day - left["day"], "limit": lim.day},
            "searches_day": {"used": lim.searches - left["searches"], "limit": lim.searches},
        }
        if detail:
            out["tokens_minute"] = {"used": lim.minute - left["minute"], "limit": lim.minute}
            out["per_question"] = {"web": lim.web, "deep": lim.deep, "per_guest_day": lim.guest}
        return out
