"""Conformal prediction and risk control behind the calibrated remaining life
(stf-cad/hbw/pdm/cp.py): the finite-sample quantile, that the intervals and lower bounds hold as
often as they promise on exchangeable data - even from a badly wrong predictor - and that risk
control picks the most permissive threshold that keeps its bound. numpy only; the pipeline is
graded by `make conformal`."""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stf-cad" / "hbw"))
from pdm import cp  # noqa: E402


def test_conformal_q_is_the_finite_sample_rank():
    s = np.arange(1, 20)                       # n = 19: ceil(20 * 0.9) = 18th smallest
    assert cp.conformal_q(s, 0.1) == 18
    assert cp.conformal_q(np.arange(5), 0.1) == math.inf     # too few to promise 90 %


def test_log_life_keeps_never_finite():
    assert np.isfinite(cp.log_life([np.inf, 1e12, -3])).all()
    assert cp.log_life([0])[0] == 0


def _miscalibrated(rng, n):
    """A predictor whose P10-P90 is far too narrow and biased: truth ~ lognormal, the 'interval'
    a fixed band around a wrong median."""
    y = rng.lognormal(4.0, 0.6, n)
    lo, hi = np.full(n, 70.0), np.full(n, 90.0)
    return cp.log_life(y), cp.log_life(lo), cp.log_life(hi)


@pytest.mark.parametrize("alpha", [0.1, 0.2])
def test_cqr_interval_holds_its_promise_from_a_wrong_predictor(alpha):
    rng = np.random.default_rng(5)
    hits = []
    for _ in range(200):
        y, lo, hi = _miscalibrated(rng, 300)
        q = cp.conformal_q(cp.cqr_score(y[:200], lo[:200], hi[:200]), alpha)
        hits.append(((lo[200:] - q <= y[200:]) & (y[200:] <= hi[200:] + q)).mean())
    raw = ((lo <= y) & (y <= hi)).mean()
    assert raw < 0.3                               # the predictor alone is badly wrong
    assert np.mean(hits) >= 1 - alpha - 0.01       # conformal fixes it on average
    assert np.mean(hits) <= 1 - alpha + 0.03       # without being uselessly wide


def test_lower_bound_holds_one_sided():
    rng = np.random.default_rng(6)
    above = []
    for _ in range(200):
        y, lo, _ = _miscalibrated(rng, 300)
        q = cp.conformal_q(cp.lower_score(y[:200], lo[:200]), 0.1)
        above.append((y[200:] >= lo[200:] - q).mean())
    assert 0.89 <= np.mean(above) <= 0.93


def test_mondrian_falls_back_where_a_group_has_too_few_units():
    rng = np.random.default_rng(7)
    s = np.concatenate([rng.normal(0, 1, 500), rng.normal(5, 1, 500), rng.normal(0, 1, 30)])
    g = np.repeat([0, 1, 2], [500, 500, 30])
    # group 2 is a single unit
    units = np.concatenate([np.arange(500) // 10, 100 + np.arange(500) // 10, [200] * 30])
    per, pooled = cp.mondrian_q(s, g, units, 0.1, min_units=5)
    assert per[0][1] and per[1][1] and not per[2][1]
    assert per[1][0] > per[0][0] + 3               # the shifted group gets its own, wider quantile
    assert per[2][0] == pooled


def test_crc_picks_the_largest_threshold_inside_the_bound():
    rng = np.random.default_rng(8)
    lams = np.linspace(0, 1, 11)
    # the risk grows with lambda
    grid = [(lam, (rng.random(400) < lam * 0.2).astype(float)) for lam in lams]
    lam, bounds = cp.crc_choose(grid, 0.1)
    assert lam is not None
    ok = [lam_ for lam_, b in bounds if b <= 0.1]
    assert lam == max(ok)
    assert dict(bounds)[lam] <= 0.1
    assert cp.crc_choose([(0.5, np.ones(10))], 0.1)[0] is None


def test_weighted_q_equals_conformal_q_with_equal_weights():
    rng = np.random.default_rng(9)
    s = rng.normal(0, 1, 199)
    assert cp.weighted_q(s, np.ones(199), 0.1) == pytest.approx(cp.conformal_q(s, 0.1))


def test_weighted_q_follows_the_recent_scores():
    old, new = np.zeros(500), np.full(500, 5.0)
    s = np.concatenate([old, new])
    fresh = np.concatenate([np.full(500, 0.01), np.ones(500)])
    assert cp.weighted_q(s, fresh, 0.1) == 5.0          # the old fleet has faded out
    assert cp.weighted_q(s, fresh[::-1], 0.1) == 0.0


def test_aci_steps_toward_the_target_and_stays_bounded():
    a = 0.1
    a = cp.aci_step(a, 0.1, err=1.0, gamma=0.05)        # a miss: the next interval widens
    assert a < 0.1
    for _ in range(100):
        a = cp.aci_step(a, 0.1, err=0.0, gamma=0.05)
    assert a == 0.5                                     # clipped


def test_conformal_p_values_are_uniform_and_flag_a_shift():
    rng = np.random.default_rng(10)
    ref = rng.normal(0, 1, 4000)
    p = cp.p_values(ref, rng.normal(0, 1, 4000), rng)
    assert abs(p.mean() - 0.5) < 0.02 and abs((p < 0.1).mean() - 0.1) < 0.015
    assert cp.p_values(ref, rng.normal(2, 1, 1000), rng).mean() < 0.1


def test_test_martingale_keeps_villes_bound_and_detects_a_shift():
    rng = np.random.default_rng(11)
    ref = rng.normal(0, 1, 2000)
    thr = np.log(100)
    false = sum(cp.mixture_martingale(cp.p_values(ref, rng.normal(0, 1, 300), rng)).max() >= thr
                for _ in range(300))
    assert false / 300 <= 0.02                          # Ville: <= 1 % (plus sampling slack)
    lm = cp.mixture_martingale(cp.p_values(ref, rng.normal(1.0, 1, 300), rng))
    assert (lm >= thr).any() and int(np.argmax(lm >= thr)) < 60
