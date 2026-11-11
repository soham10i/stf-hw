"""
How good one answer was, as the graph saw it: the claims made and backed (claims.py), the
citations they carry, the numbers nothing backs (verify.py), the retrieval verdict (crag.py),
what the policy did (answer_policy.py), the confidence (confidence.py), the time, the tokens and
the cost.

summary() is the payload's `quality` (the dashboard shows it beside the answer); row() is the
same with the request id, the time and the route, kept per answer by storage/quality.py and read
back by GET /copilot/quality. Neither holds the question or the answer.
"""

from __future__ import annotations

import time
from typing import Any

from services.api.core import request_context

from . import answer_policy

_tracker: Any = None  # storage.quality.Quality, set by the app


def set_tracker(tracker: Any) -> None:
    global _tracker
    _tracker = tracker


def get_tracker() -> Any:
    return _tracker


def summary(q, bad: list[str] | None, rules: bool) -> dict:
    """The answer's scores, from the graph's working memory (graph.Question)."""
    r, d = q.report, q.decision
    facts = r.facts() if r is not None else []
    return {
        "claims": len(facts),
        "supported": r.count("supported") if r is not None else 0,
        "unsupported": r.count("unsupported") if r is not None else 0,
        "unsure": r.count("unsure") if r is not None else 0,
        "groundedness": r.groundedness() if r is not None else None,
        "min_support": r.min_support() if r is not None else None,
        "citation_coverage": _round(answer_policy.coverage(r)),
        "cited_by_model": _round(q.cited_by_model),
        "citation_precision": _round(r.citation_precision()) if r is not None else None,
        "numbers_unverified": len(bad or []),
        "retrieval_verdict": q.verdict,
        "action": d.action if d is not None else "pass",
        "declined": bool(r is not None and r.declined()) or bool(d and d.action == "decline"),
        "regenerated": q.regenerated,
        "confidence": q.confidence,
        "judge_calls": q.judge_calls,
        "rules": rules,
    }


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def row(q, out: dict, engine: str, cached: bool) -> dict | None:
    """The row storage/quality.py keeps for this answer, or None outside a request."""
    rid = request_context.request_id()
    if not rid:
        return None
    s = dict(out.get("quality") or {})
    usage = q.usage or {}
    return {
        **s,
        "request_id": rid,
        "t": time.time(),
        "mode": (out.get("route") or {}).get("mode"),
        "model": out.get("model"),
        "engine": engine,
        "cached": cached,
        # a cached reply spent nothing now; its scores are the original answer's
        "latency_ms": round(1000 * (time.monotonic() - q.started)) if cached else out.get("ms"),
        "tokens": 0 if cached else usage.get("tokens"),
        "cost_usd": 0.0 if cached else usage.get("estimated_model_cost_usd"),
        "judge_calls": 0 if cached else s.get("judge_calls"),
    }


def record(q, out: dict, engine: str, cached: bool) -> None:
    """Keep the answer's row, when the app gave a tracker (off the request's path)."""
    if _tracker is not None:
        _tracker.record(row(q, out, engine, cached))
