"""The statistics of the predictive-maintenance pipeline (stf-cad/hbw/pdm/stats.py): the
quantiles behind its control limits, and that each detector finds what it is for and stays
quiet when nothing changes. numpy only; the model itself is graded by `make pdm`."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stf-cad" / "hbw"))
from pdm import stats as S  # noqa: E402


@pytest.mark.parametrize(
    "p,want", [(0.5, 0.0), (0.975, 1.959964), (0.999, 3.090232), (0.001, -3.090232)]
)
def test_norm_ppf(p, want):
    assert S.norm_ppf(p) == pytest.approx(want, abs=1e-5)


@pytest.mark.parametrize("p,k,want", [(0.999, 10, 29.588), (0.95, 2, 5.991), (0.99, 30, 50.892)])
def test_chi2_quantile_matches_tables(p, k, want):
    assert S.chi2_quantile(p, k) == pytest.approx(want, rel=0.01)


def test_cusum_finds_a_half_sigma_shift_and_stays_quiet_without_one():
    rng = np.random.default_rng(3)
    calm = rng.normal(0, 1, 2000)
    _, a = S.cusum(calm)
    assert a.mean() < 0.01  # in control: the run length is ~465 per false alarm
    shifted = np.concatenate([rng.normal(0, 1, 500), rng.normal(1.0, 1, 200)])
    _, a = S.cusum(shifted)
    first = int(np.argmax(a[500:])) + 500
    assert a[500:].any() and first < 540         # a one-sigma shift found within ~10-20 samples


def test_cusum_restarts_at_a_renewal():
    x = np.full(40, 2.0)
    reset = np.zeros(40, bool)
    reset[20] = True
    s, _ = S.cusum(x, reset=reset)
    assert s[19] == pytest.approx(30.0) and s[20] == pytest.approx(1.5)


def test_ewma_limit_converges_to_the_asymptote():
    _, ucl, _ = S.ewma_chart(np.zeros(500), lam=0.1, L=3.0)
    assert ucl[-1] == pytest.approx(3 * np.sqrt(0.1 / 1.9), rel=1e-6)
    assert ucl[0] < ucl[-1]


def test_t2_false_alarm_rate_is_alpha_under_the_model():
    rng = np.random.default_rng(5)
    E = rng.normal(0, 1, (20000, 10))
    stat, lim = S.t2(E, alpha=0.01)
    assert 0.006 < (stat > lim).mean() < 0.014


def test_bocpd_locates_a_change_in_mean():
    rng = np.random.default_rng(9)
    x = np.concatenate([rng.normal(0, 1, 300), rng.normal(2.5, 1, 200)])
    cp, run = S.bocpd(x, hazard=1 / 300)
    assert int(np.argmax(cp[250:])) + 250 in range(298, 310)
    assert run[-1] in range(180, 205)            # the run length since the change, at the end
