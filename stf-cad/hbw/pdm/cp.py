"""
Conformal prediction and conformal risk control, in numpy alone (used by pdm/conformal.py).

  log_life        log(1 + remaining life): the scale every score is taken on
  conformal_q     the finite-sample split-conformal quantile (Vovk, Gammerman & Shafer 2005)
  cqr_score       conformalised quantile regression's score (Romano, Patterson & Candes 2019)
  lower_score     the one-sided score of a lower bound
  mondrian_q      one quantile per group (Vovk et al. 2003), the pooled one where a group has
                  too few independent units to promise anything
  crc_choose      conformal risk control (Angelopoulos, Bates, Fisch, Lei & Schuster 2024): the
                  most permissive threshold whose calibration risk keeps the guarantee
"""
import math

import numpy as np


def log_life(x):
    """log(1 + x) for remaining life in orders; an infinite or 'never' life (1e9) stays finite."""
    return np.log1p(np.minimum(np.maximum(np.asarray(x, float), 0.0), 1e9))


def conformal_q(scores, alpha: float) -> float:
    """The ceil((n + 1)(1 - alpha))-th smallest of n calibration scores. A new score from the same
    exchangeable source is at most this with probability >= 1 - alpha; infinite when n is too
    small for that promise (n < 1/alpha - 1)."""
    s = np.sort(np.asarray(scores, float))
    n = len(s)
    k = math.ceil((n + 1) * (1 - alpha))
    return float(s[k - 1]) if 1 <= k <= n else math.inf


def cqr_score(y, lo, hi):
    """How far y fell outside [lo, hi] (negative: how far inside). Interval: [lo - q, hi + q]."""
    return np.maximum(np.asarray(lo) - y, np.asarray(y) - hi)


def lower_score(y, lo):
    """How far y fell below the lower bound lo. Bound: lo - q."""
    return np.asarray(lo) - y


def mondrian_q(scores, groups, units, alpha: float, min_units: int) -> tuple[dict, float]:
    """Per group g the conformal quantile of its own scores, if it has at least `min_units`
    independent units (`units`: the unit id of each score - e.g. a failure segment); else the
    pooled quantile. Returns ({group: (q, own)}, pooled q)."""
    scores, groups, units = np.asarray(scores, float), np.asarray(groups), np.asarray(units)
    pooled = conformal_q(scores, alpha)
    out = {}
    for g in np.unique(groups):
        m = groups == g
        own = len(np.unique(units[m])) >= min_units
        out[g.item() if hasattr(g, "item") else g] = (conformal_q(scores[m], alpha) if own else pooled, own)
    return out, pooled


def crc_bound(losses, B: float = 1.0) -> float:
    """The conformal risk control statistic (n R + B) / (n + 1) of n calibration losses in [0, B]."""
    losses = np.asarray(losses, float)
    n = len(losses)
    return float((losses.sum() + B) / (n + 1))


def crc_choose(grid, alpha: float, B: float = 1.0):
    """grid: [(lambda, losses)] with the loss non-decreasing in lambda. The largest lambda whose
    crc_bound <= alpha bounds the expected loss on a new unit by alpha. Returns (lambda or None,
    [(lambda, bound)])."""
    bounds = [(lam, crc_bound(l, B)) for lam, l in grid]
    ok = [lam for lam, b in bounds if b <= alpha]
    return (max(ok) if ok else None), bounds


def weighted_q(scores, weights, alpha: float) -> float:
    """Conformal prediction beyond exchangeability (Barber, Candes, Ramdas & Tibshirani 2023): the
    1 - alpha quantile of the scores under their weights, the new point's own weight 1 at +inf."""
    scores, weights = np.asarray(scores, float), np.asarray(weights, float)
    o = np.argsort(scores)
    cw = np.cumsum(weights[o]) / (weights.sum() + 1.0)
    k = np.searchsorted(cw, 1 - alpha, side="left")
    return float(scores[o][k]) if k < len(scores) else math.inf


def aci_step(alpha_t: float, target: float, err: float, gamma: float, lo: float = 1e-3, hi: float = 0.5) -> float:
    """Adaptive conformal inference (Gibbs & Candes 2021): alpha_{t+1} = alpha_t + gamma (target - err),
    err the share of the newly scored points the interval missed."""
    return float(min(hi, max(lo, alpha_t + gamma * (target - err))))


def p_values(ref, x, rng) -> np.ndarray:
    """Smoothed conformal p-values of x against reference scores, large = strange: uniform on
    [0, 1] while x and the reference are exchangeable."""
    ref = np.sort(np.asarray(ref, float))
    x = np.asarray(x, float)
    n = len(ref)
    right = np.searchsorted(ref, x, side="right")
    eq = right - np.searchsorted(ref, x, side="left")
    return (n - right + rng.random(len(x)) * (eq + 1)) / (n + 1)


_EPS = np.linspace(0.005, 0.995, 199)


def mixture_martingale(p) -> np.ndarray:
    """log M_n of the simple mixture conformal test martingale (Vovk, Nouretdinov & Gammerman 2003):
    M_n = int_0^1 prod_i eps p_i^(eps - 1) d eps. While the p-values are independent and uniform,
    P(M ever reaches 1/delta) <= delta (Ville 1939)."""
    lp = np.log(np.maximum(np.asarray(p, float), 1e-12))
    acc = np.cumsum(np.log(_EPS)[None, :] + (_EPS - 1)[None, :] * lp[:, None], axis=0)
    m = acc.max(1, keepdims=True)
    return m[:, 0] + np.log(np.exp(acc - m).mean(1))
