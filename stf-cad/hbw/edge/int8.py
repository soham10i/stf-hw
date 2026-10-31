"""
Integer-only int8 inference, the arithmetic of an Edge TPU, TFLite and CMSIS-NN (Jacob et al., CVPR
2018; Krishnamoorthi 2018), written out so every rounding is visible and testable. numpy only.

  weights      int8, symmetric, one scale per output channel: w = s_w[o] * q, q in [-127, 127]
  activations  int8, affine, one scale and zero point per tensor: x = s * (q - z), q in [-128, 127]
  bias         int32 at the accumulator's scale s_in * s_w[o]
  accumulate   int32: sum (q_x - z_x) * q_w + q_b
  requantize   to the next tensor's scale by a fixed-point multiplier M = s_in s_w / s_out held as
               a Q31 integer and a power-of-two shift - no floating point on the device. ReLU is
               the clamp at the output's zero point.

The products are int8 x int8 and a layer sums at most a few hundred of them, so every partial sum
is an integer below 2^24 and a float32 matrix product computes it exactly; the accumulations below
use BLAS for speed and the requantization is done in int64, as the device does it.
"""
import numpy as np

QMIN, QMAX = -128, 127


# ---------------------------------------------------------------- scales
def act_params(lo, hi):
    """Affine int8 parameters (scale, zero point) for a tensor observed in [lo, hi]; the range is
    widened to include 0 so that zero (the padding, ReLU's floor) is exact."""
    lo, hi = min(float(lo), 0.0), max(float(hi), 0.0)
    s = (hi - lo) / (QMAX - QMIN) if hi > lo else 1e-8
    z = int(np.clip(round(QMIN - lo / s), QMIN, QMAX))
    return s, z


def quantize(x, s, z):
    return np.clip(np.round(np.asarray(x, np.float64) / s) + z, QMIN, QMAX).astype(np.int8)


def dequantize(q, s, z):
    return (np.asarray(q, np.float32) - z) * np.float32(s)


def weight_q(w):
    """Per-output-channel symmetric int8 (axis 0 is the output channel) -> (q int8, s_w per channel)."""
    w = np.asarray(w, np.float64)
    m = np.abs(w.reshape(len(w), -1)).max(1)
    s = np.where(m > 0, m / 127.0, 1.0)
    q = np.clip(np.round(w / s.reshape(-1, *([1] * (w.ndim - 1)))), -127, 127).astype(np.int8)
    return q, s


def bias_q(b, s_in, s_w):
    return np.round(np.asarray(b, np.float64) / (s_in * s_w)).astype(np.int64)


# ---------------------------------------------------------------- fixed point
def multiplier(M):
    """A real multiplier M > 0 as (m0, e): M = m0 * 2^(e - 31), m0 a Q31 integer in [2^30, 2^31)."""
    M = np.atleast_1d(np.asarray(M, np.float64))
    f, e = np.frexp(M)                                # M = f 2^e, f in [0.5, 1)
    m0 = np.round(f * (1 << 31)).astype(np.int64)
    over = m0 == (1 << 31)
    m0[over] //= 2
    e = e + over
    return m0, e.astype(np.int64)


def _high_mul(a, m0):
    """gemmlowp's SaturatingRoundingDoublingHighMul: round(a * m0 / 2^31), ties away from zero."""
    p = a * m0
    nudge = np.where(p >= 0, 1 << 30, 1 - (1 << 30))
    q = p + nudge
    return np.where(q >= 0, q >> 31, -((-q) >> 31))   # C division truncates toward zero


def _shift_round(x, n):
    """RoundingDivideByPOT: x / 2^n rounded to nearest, ties away from zero (n >= 0)."""
    mask = (np.int64(1) << n) - 1
    rem = x & mask
    thr = (mask >> 1) + (x < 0)
    return (x >> n) + (rem > thr)


def scale_int(acc, m0, e):
    """acc (int64) x M, in integers only (TFLite MultiplyByQuantizedMultiplier). m0, e broadcast
    against acc (per channel: shape them to the channel axis)."""
    acc = np.asarray(acc, np.int64)
    left = np.maximum(e, 0)
    right = np.maximum(-e, 0)
    return _shift_round(_high_mul(acc << left, m0), right)


def requantize(acc, m0, e, z_out, relu=False):
    y = scale_int(acc, m0, e) + z_out
    return np.clip(y, z_out if relu else QMIN, QMAX).astype(np.int8)


# ---------------------------------------------------------------- layers
class Conv:
    """A quantized convolution: 1-D causal dilated (kernel K, left zero padding (K-1) * dil, as
    ml/model.py) or 2-D 'same' 3x3. Built from fp32 weights and the calibrated scales of its
    input and output."""

    def __init__(self, w, b, s_in, z_in, s_out, z_out, relu, dil=1, dims=1):
        self.q, self.s_w = weight_q(w)
        self.b = bias_q(b, s_in, self.s_w)
        self.m0, self.e = multiplier(s_in * self.s_w / s_out)
        self.s_in, self.z_in, self.s_out, self.z_out = s_in, z_in, s_out, z_out
        self.relu, self.dil, self.dims = relu, dil, dims
        k = self.q.shape[2]
        self.pad = (k - 1) * dil
        n = self.q[0].size                                    # products summed per output
        self.dt = np.float32 if n * 255 * 127 < 2 ** 24 else np.float64      # exact either way
        self.wm = self.q.reshape(len(self.q), -1).T.astype(self.dt)          # (Cin*K[*K]) x Cout

    def acc(self, q):
        x = q.astype(self.dt) - self.z_in                     # zero padding is z_in in q, 0 here
        if self.dims == 1:
            B, C, T = x.shape
            x = np.pad(x, ((0, 0), (0, 0), (self.pad, 0)))
            K = self.q.shape[2]
            cols = np.stack([x[:, :, k * self.dil:k * self.dil + T] for k in range(K)], 3)   # B C T K
            cols = cols.transpose(0, 2, 1, 3).reshape(B, T, C * K)
            a = cols @ self.wm                                                               # B T O
            return a.transpose(0, 2, 1).astype(np.int64) + self.b[None, :, None]
        B, C, H, W = x.shape
        x = np.pad(x, ((0, 0), (0, 0), (1, 1), (1, 1)))
        cols = np.stack([x[:, :, i:i + H, j:j + W] for i in range(3) for j in range(3)], 2)  # B C 9 H W
        cols = cols.transpose(0, 3, 4, 1, 2).reshape(B, H * W, C * 9)
        a = (cols @ self.wm).reshape(B, H, W, -1).transpose(0, 3, 1, 2)
        return a.astype(np.int64) + self.b[None, :, None, None]

    def __call__(self, q):
        sh = (1, -1) + (1,) * self.dims
        return requantize(self.acc(q), self.m0.reshape(sh), self.e.reshape(sh), self.z_out, self.relu)


class Linear:
    def __init__(self, w, b, s_in, z_in, s_out, z_out, relu):
        self.q, self.s_w = weight_q(w)
        self.b = bias_q(b, s_in, self.s_w)
        self.m0, self.e = multiplier(s_in * self.s_w / s_out)
        self.z_in, self.z_out, self.relu = z_in, z_out, relu
        self.wm = self.q.T.astype(np.float32)

    def __call__(self, q):
        a = ((q.astype(np.float32) - self.z_in) @ self.wm).astype(np.int64) + self.b
        return requantize(a, self.m0, self.e, self.z_out, self.relu)


class Add:
    """TFLite's quantized ADD: both inputs to a common, finer scale (a 20-bit left shift), summed,
    then to the output's scale - integers throughout."""
    SHIFT = 20

    def __init__(self, sa, za, sb, zb, s_out, z_out):
        twice = 2 * max(sa, sb)
        self.ma, self.ea = multiplier(sa / twice)
        self.mb, self.eb = multiplier(sb / twice)
        self.mo, self.eo = multiplier(twice / ((1 << self.SHIFT) * s_out))
        self.za, self.zb, self.z_out = za, zb, z_out

    def __call__(self, qa, qb):
        a = scale_int((qa.astype(np.int64) - self.za) << self.SHIFT, self.ma, self.ea)
        b = scale_int((qb.astype(np.int64) - self.zb) << self.SHIFT, self.mb, self.eb)
        return requantize(a + b, self.mo, self.eo, self.z_out)


class Rescale:
    """The same values at another scale (TFLite's requantize before a concatenation, or a mean:
    `n` summed int8 values divided by n inside the multiplier)."""

    def __init__(self, s_in, z_in, s_out, z_out, n=1):
        self.m0, self.e = multiplier(s_in / (n * s_out))
        self.z_in, self.z_out = z_in, z_out

    def __call__(self, acc_or_q, summed=False):
        a = np.asarray(acc_or_q, np.int64)
        return requantize(a if summed else a - self.z_in, self.m0, self.e, self.z_out)


def maxpool2(q):
    """2x2 max pooling: exact on int8 (max commutes with a monotone affine map)."""
    B, C, H, W = q.shape
    return q.reshape(B, C, H // 2, 2, W // 2, 2).max((3, 5))


LOGISTIC = (1 / 256, -128)   # TFLite's fixed int8 output parameters of a sigmoid


def logistic(q, s, z):
    """int8 sigmoid; the device uses a lookup table over the 256 input codes - the same values."""
    lut = quantize(1 / (1 + np.exp(-dequantize(np.arange(QMIN, QMAX + 1), s, z))), *LOGISTIC)
    return lut[q.astype(np.int64) - QMIN]


# ---------------------------------------------------------------- calibration
class Observer:
    """The range of one tensor over the calibration data: min/max, or the 0.01-99.99 %
    percentiles (clips rare outliers, finer steps for the rest)."""

    def __init__(self, how="minmax", keep=400_000, seed=0):
        self.how, self.lo, self.hi, self.keep = how, np.inf, -np.inf, keep
        self.samples, self.rng = [], np.random.default_rng(seed)

    def __call__(self, x):
        x = np.asarray(x, np.float32).ravel()
        self.lo, self.hi = min(self.lo, float(x.min())), max(self.hi, float(x.max()))
        if self.how == "percentile":
            k = min(len(x), 20_000)
            self.samples.append(self.rng.choice(x, k, replace=False))
        return x

    def params(self):
        if self.how == "percentile" and self.samples:
            s = np.concatenate(self.samples)
            return act_params(np.percentile(s, 0.01), np.percentile(s, 99.99))
        return act_params(self.lo, self.hi)
