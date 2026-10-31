"""Integer-only int8 inference (stf-cad/hbw/edge/int8.py): the fixed-point requantisation rounds as
the device does, and each quantized layer reproduces its fp32 layer to within its output step.
numpy only; the networks are graded by `make edge`."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stf-cad" / "hbw"))
from edge import int8 as Q  # noqa: E402


def test_multiplier_represents_the_real_scale():
    for M in (1e-5, 0.003, 0.25, 0.5, 0.9999, 1.7, 40.0):
        m0, e = Q.multiplier(M)
        assert (1 << 30) <= m0[0] < (1 << 31)
        assert m0[0] * 2.0 ** (e[0] - 31) == pytest.approx(M, rel=1e-9)


def test_fixed_point_scaling_rounds_to_nearest():
    rng = np.random.default_rng(1)
    acc = rng.integers(-2 ** 22, 2 ** 22, 20000)
    for M in (0.0007, 0.031, 0.49, 1.3):
        m0, e = Q.multiplier(M)
        got = Q.scale_int(acc, m0, e)
        err = np.abs(got - acc * M)
        assert err.max() < 1.0            # rounded twice (Q31, then the shift): under a step
        assert err.mean() < 0.35          # near 0.25 as to-nearest (a floor gives 0.5)


def test_quantize_round_trip_and_exact_zero():
    s, z = Q.act_params(-1.3, 4.1)
    x = np.linspace(-1.3, 4.1, 1001)
    assert np.abs(Q.dequantize(Q.quantize(x, s, z), s, z) - x).max() <= s / 2 + 1e-9
    assert Q.dequantize(Q.quantize([0.0], s, z), s, z)[0] == 0.0
    s, z = Q.act_params(0.0, 3.0)                 # after a ReLU: zero point at the floor
    assert z == Q.QMIN


def _conv1d(x, w, b, dil):
    pad = (w.shape[2] - 1) * dil
    xp = np.pad(x, ((0, 0), (0, 0), (pad, 0)))
    T = x.shape[2]
    cols = np.stack([xp[:, :, k * dil:k * dil + T] for k in range(w.shape[2])], 3)
    return np.einsum("bctk,ock->bot", cols, w) + b[None, :, None]


@pytest.mark.parametrize("dil", [1, 4])
def test_causal_dilated_conv_matches_fp32_within_a_step(dil):
    rng = np.random.default_rng(2)
    x = rng.normal(0, 1, (8, 6, 48))
    w, b = rng.normal(0, 0.3, (5, 6, 3)), rng.normal(0, 0.1, 5)
    y = np.maximum(_conv1d(x, w, b, dil), 0)
    si, zi = Q.act_params(x.min(), x.max())
    so, zo = Q.act_params(0, y.max())
    conv = Q.Conv(w, b, si, zi, so, zo, relu=True, dil=dil)
    got = Q.dequantize(conv(Q.quantize(x, si, zi)), so, zo)
    err = np.abs(got - y)
    assert err.max() < 4 * so                                 # input + weight rounding, a few steps
    assert err.mean() < so
    # causal: the output at t never sees inputs after t
    x2 = x.copy()
    x2[:, :, 30:] += 5
    got2 = Q.dequantize(conv(Q.quantize(np.clip(x2, x.min(), x.max()), si, zi)), so, zo)
    assert np.array_equal(got[:, :, :30], got2[:, :, :30])


def test_conv2d_and_maxpool():
    rng = np.random.default_rng(3)
    x = rng.uniform(-0.5, 0.5, (4, 3, 16, 16))
    w, b = rng.normal(0, 0.3, (8, 3, 3, 3)), rng.normal(0, 0.05, 8)
    xp = np.pad(x, ((0, 0), (0, 0), (1, 1), (1, 1)))
    ref = np.zeros((4, 8, 16, 16))
    for i in range(3):
        for j in range(3):
            ref += np.einsum("bchw,oc->bohw", xp[:, :, i:i + 16, j:j + 16], w[:, :, i, j])
    ref = np.maximum(ref + b[None, :, None, None], 0)
    si, zi = Q.act_params(-0.5, 0.5)
    so, zo = Q.act_params(0, ref.max())
    q = Q.Conv(w, b, si, zi, so, zo, relu=True, dims=2)(Q.quantize(x, si, zi))
    assert np.abs(Q.dequantize(q, so, zo) - ref).max() < 4 * so
    pooled = Q.dequantize(Q.maxpool2(q), so, zo)
    assert np.abs(pooled - ref.reshape(4, 8, 8, 2, 8, 2).max((3, 5))).max() < 4 * so


def test_add_and_mean_rescale():
    rng = np.random.default_rng(4)
    a, b = rng.uniform(0, 3, (6, 10)), rng.uniform(0, 0.7, (6, 10))
    pa, pb, po = Q.act_params(0, 3), Q.act_params(0, 0.7), Q.act_params(0, 3.7)
    got = Q.dequantize(Q.Add(*pa, *pb, *po)(Q.quantize(a, *pa), Q.quantize(b, *pb)), *po)
    assert np.abs(got - (a + b)).max() <= pa[0] / 2 + pb[0] / 2 + po[0] / 2 + 1e-9
    qa = Q.quantize(a, *pa)
    pm = Q.act_params(0, 3)
    m = Q.Rescale(*pa, *pm, n=10)((qa.astype(np.int64) - pa[1]).sum(1), summed=True)
    assert np.abs(Q.dequantize(m, *pm) - a.mean(1)).max() <= pa[0] / 2 + pm[0] / 2 + 1e-9


def test_logistic_uses_the_fixed_output_scale():
    s, z = Q.act_params(-8, 8)
    x = np.linspace(-8, 8, 200)
    got = Q.dequantize(Q.logistic(Q.quantize(x, s, z), s, z), *Q.LOGISTIC)
    assert np.abs(got - 1 / (1 + np.exp(-x))).max() < s / 4 + 1 / 256
