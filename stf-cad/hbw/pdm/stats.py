"""
The statistics of the pipeline, in numpy alone.

  chi2_quantile   Wilson-Hilferty approximation (the limit of a chi-squared control chart)
  cusum           Page's one-sided CUSUM (Page 1954): a small persistent shift, found early
  ewma_chart      Roberts' EWMA chart with exact time-varying limits (Roberts 1959; Lucas &
                  Saccucci 1990)
  t2              Hotelling's T^2 of standardised residuals across components (MSPC, the
                  multivariate statistical process control of MacGregor & Kourti 1995)
  bocpd           Bayesian online change-point detection (Adams & MacKay 2007): the posterior
                  of the run length since the last change, Gaussian observations with an
                  unknown mean and a known variance, a constant hazard
"""
import math

import numpy as np


def norm_ppf(p: float) -> float:
    """The standard normal quantile (Acklam's rational approximation, |error| < 1.2e-9)."""
    a = (-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.383577518672690e2,
         -3.066479806614716e1, 2.506628277459239)
    b = (-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1,
         -1.328068155288572e1)
    c = (-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734,
         4.374664141464968, 2.938163982698783)
    d = (7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416)
    lo, hi = 0.02425, 1 - 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > hi:
        return -norm_ppf(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def chi2_quantile(p: float, k: int) -> float:
    """The p-quantile of chi-squared with k degrees of freedom (Wilson & Hilferty 1931)."""
    z = norm_ppf(p)
    return k * (1 - 2 / (9 * k) + z * math.sqrt(2 / (9 * k))) ** 3


def cusum(x: np.ndarray, k: float = 0.5, h: float = 5.0, reset: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Upper one-sided CUSUM of standardised x: S_t = max(0, S_{t-1} + x_t - k), alarm S_t > h.
    k = half the shift to detect (in sigmas), h = 5: an in-control run length of ~465 samples
    for k = 0.5. `reset` marks samples after which the statistic restarts (a part renewed)."""
    s, out = 0.0, np.zeros(len(x))
    for t, v in enumerate(x):
        if reset is not None and reset[t]:
            s = 0.0
        s = max(0.0, s + (0.0 if np.isnan(v) else v) - k)
        out[t] = s
    return out, out > h


def ewma_chart(x: np.ndarray, lam: float = 0.1, L: float = 3.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """EWMA of standardised x and its exact upper limit L * sqrt(lam/(2-lam) (1-(1-lam)^2t))."""
    z, out = 0.0, np.zeros(len(x))
    for t, v in enumerate(x):
        z = lam * (0.0 if np.isnan(v) else v) + (1 - lam) * z
        out[t] = z
    t = np.arange(1, len(x) + 1)
    ucl = L * np.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * t)))
    return out, ucl, out > ucl


def t2(E: np.ndarray, alpha: float = 0.001) -> tuple[np.ndarray, float]:
    """Hotelling's T^2 of standardised, independent residuals (orders x components): their sum of
    squares, chi-squared with as many degrees of freedom as components when the model holds.
    NaN columns (a component not observed at that order) are left out of both."""
    ok = ~np.isnan(E)
    stat = np.where(ok, E, 0.0) ** 2
    return stat.sum(1), chi2_quantile(1 - alpha, E.shape[1])


def bocpd(x: np.ndarray, hazard: float = 1 / 500, mu0: float = 0.0, kappa0: float = 1.0,
          sigma: float = 1.0, r_max: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """Adams & MacKay (2007), Gaussian likelihood with known sigma and a normal prior on the mean
    (mu0, sigma^2 / kappa0). Returns, per sample, the probability that a change happened within
    the last few samples (run length < 5) and the most probable run length. The run length is
    truncated at r_max (the tail mass is folded into the last bin)."""
    n = len(x)
    R = np.zeros(r_max + 1)
    R[0] = 1.0
    mu = np.array([mu0])
    kap = np.array([kappa0])
    cp, ml = np.zeros(n), np.zeros(n, dtype=int)
    for t in range(n):
        v = x[t]
        if np.isnan(v):
            cp[t], ml[t] = cp[t - 1] if t else 0.0, ml[t - 1] + 1 if t else 0
            continue
        m = len(mu)
        # predictive of v under each run length: N(mu, sigma^2 (1 + 1/kappa))
        var = sigma ** 2 * (1 + 1 / kap)
        pred = np.exp(-0.5 * (v - mu) ** 2 / var) / np.sqrt(2 * np.pi * var)
        growth = R[:m] * pred * (1 - hazard)
        change = (R[:m] * pred * hazard).sum()
        newR = np.zeros(r_max + 1)
        newR[0] = change
        k = min(m, r_max)
        newR[1:k + 1] = growth[:k]
        if m > r_max:                        # fold the tail into the last run length
            newR[r_max] += growth[r_max:].sum()
        s = newR.sum()
        R = newR / s if s > 0 else np.eye(1, r_max + 1, 0).ravel()
        # the posterior of the mean for each run length
        mu_new = (kap * mu + v) / (kap + 1)
        kap_new = kap + 1
        mu = np.concatenate([[mu0], mu_new])[: r_max + 1]
        kap = np.concatenate([[kappa0], kap_new])[: r_max + 1]
        if len(mu) > r_max + 1:
            mu, kap = mu[: r_max + 1], kap[: r_max + 1]
        cp[t] = R[:5].sum()
        ml[t] = int(R.argmax())
    return cp, ml
