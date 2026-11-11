"""
How sure the copilot may be of an answer: the probability that every claim in it is backed by
what it was given, from the signals the checks already produce - groundedness and the weakest
claim (claims.py), unbacked numbers (verify.py), the model's own citations, and how retrieval
judged the passages (crag.py).

The score is a logistic model over those features. Its weights are fitted offline on labelled
answers (eval_grounding.py --fit, L2-regularised Newton steps) and kept beside this module in
confidence_weights.json; without that file the hand-set DEFAULT stands. The same evaluation
reports how well the probabilities are calibrated: Brier score, expected calibration error over
ten bins, and AUROC against the labels.
"""

from __future__ import annotations

import json
import math
import os

import numpy as np

from services.api.core.logging_config import get_logger

logger = get_logger(__name__)

FEATURES = (
    "groundedness",  # supported / checkable claims, unsure counting one half
    "min_support",  # the weakest claim's support
    "unsupported_share",  # unsupported / checkable claims
    "numbers_ok",  # 1 when verify.py backs every number
    "cited",  # share of claims the model cited
    "retrieval",  # crag's verdict as a number (VERDICT)
    "declined",  # the answer says it does not know
)
VERDICT = {"relevant": 1.0, "relevant after rewrite": 0.7, "unjudged": 0.5, "skipped": 0.5,
           "none": 0.0}
# before any fit: grounded words and backed numbers matter most, retrieval and citations a little
DEFAULT = {
    "bias": -3.0, "groundedness": 3.0, "min_support": 1.5, "unsupported_share": -2.0,
    "numbers_ok": 1.5, "cited": 0.3, "retrieval": 0.5, "declined": 0.5,
}
WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "confidence_weights.json")

_weights: dict[str, float] | None = None


def get_weights() -> dict[str, float]:
    """The fitted weights (confidence_weights.json), or DEFAULT when none were fitted."""
    global _weights
    if _weights is None:
        try:
            with open(WEIGHTS_PATH, encoding="utf-8") as f:
                _weights = {k: float(v) for k, v in json.load(f)["weights"].items()}
        except (OSError, ValueError, KeyError) as e:
            logger.debug("no fitted confidence weights (%s): the defaults stand", e)
            _weights = dict(DEFAULT)
    return _weights


def reset_weights() -> None:
    global _weights
    _weights = None


def features(report, unverified: list[str] | None, verdict: str | None) -> dict[str, float]:
    """An answer's feature vector from its claim report (claims.Report)."""
    facts = report.facts() if report is not None else []
    n = len(facts)
    g = report.groundedness() if report is not None else None
    return {
        "groundedness": 1.0 if g is None else g,
        "min_support": 1.0 if not facts else min(c.support for c in facts),
        "unsupported_share": 0.0 if not n else sum(c.verdict == "unsupported" for c in facts) / n,
        "numbers_ok": 0.0 if unverified else 1.0,
        "cited": 0.0 if not n else sum(bool(c.cited) for c in facts) / n,
        "retrieval": VERDICT.get(verdict or "skipped", 0.5),
        "declined": 1.0 if report is not None and report.declined() else 0.0,
    }


def confidence(x: dict[str, float], weights: dict[str, float] | None = None) -> float:
    """The probability that every claim is backed, rounded to three places."""
    w = weights or get_weights()
    z = w.get("bias", 0.0) + sum(w.get(k, 0.0) * x.get(k, 0.0) for k in FEATURES)
    return round(1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z)))), 3)


def of(report, unverified: list[str] | None, verdict: str | None) -> float | None:
    """An answer's confidence, or None when it states nothing to check (a greeting, a decline):
    the fit never saw such answers, and "every claim is backed" says nothing about them."""
    if report is None or (not report.facts() and not unverified):
        return None
    return confidence(features(report, unverified, verdict))


# --- fitting and calibration (eval_grounding.py)
def fit(xs: list[dict[str, float]], ys: list[int], l2: float = 1.0,
        steps: int = 25) -> dict[str, float]:
    """Logistic regression by Newton's method, L2 on the weights (not the bias). A feature that
    never varies in the data (the offline set has no citations and no retrieval verdicts) cannot
    be learned: it keeps its DEFAULT weight, as a fixed offset, instead of being fitted to 0."""
    full = np.array([[r[k] for k in FEATURES] for r in xs])
    y = np.array(ys, dtype=float)
    free = [i for i in range(len(FEATURES)) if float(np.ptp(full[:, i])) > 1e-9]
    fixed = [i for i in range(len(FEATURES)) if i not in free]
    held = np.array([DEFAULT[FEATURES[i]] for i in fixed])
    offset = full[:, fixed] @ held if fixed else np.zeros(len(ys))
    x = np.column_stack([np.ones(len(ys)), full[:, free]])
    w = np.zeros(x.shape[1])
    reg = np.eye(x.shape[1]) * l2
    reg[0, 0] = 0.0
    for _ in range(steps):
        p = 1.0 / (1.0 + np.exp(-np.clip(x @ w + offset, -30, 30)))
        grad = x.T @ (p - y) + reg @ w
        hess = (x.T * (p * (1 - p))) @ x + reg + np.eye(x.shape[1]) * 1e-9
        step = np.linalg.solve(hess, grad)
        w -= step
        if float(np.abs(step).max()) < 1e-8:
            break
    out = {"bias": round(float(w[0]), 4)}
    for j, i in enumerate(free, 1):
        out[FEATURES[i]] = round(float(w[j]), 4)
    for i, v in zip(fixed, held, strict=True):
        out[FEATURES[i]] = float(v)
    return {"bias": out["bias"], **{k: out[k] for k in FEATURES}}


def brier(ps: list[float], ys: list[int]) -> float:
    return round(sum((p - y) ** 2 for p, y in zip(ps, ys, strict=True)) / max(1, len(ps)), 4)


def ece(ps: list[float], ys: list[int], bins: int = 10) -> float:
    """Expected calibration error: the bins' |accuracy - confidence|, weighted by their size."""
    total, n = 0.0, len(ps)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(p, y) for p, y in zip(ps, ys, strict=True)
               if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if sel:
            total += len(sel) / n * abs(sum(y for _, y in sel) / len(sel)
                                        - sum(p for p, _ in sel) / len(sel))
    return round(total, 4)


def auroc(ps: list[float], ys: list[int]) -> float | None:
    """The chance a backed answer scores above an unbacked one (ties count one half)."""
    pos = [p for p, y in zip(ps, ys, strict=True) if y]
    neg = [p for p, y in zip(ps, ys, strict=True) if not y]
    if not pos or not neg:
        return None
    wins = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg)
    return round(wins / (len(pos) * len(neg)), 4)
