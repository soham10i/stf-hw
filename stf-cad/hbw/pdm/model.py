"""
The pre-failure window, per component, order by order.

1  NORMAL-BEHAVIOUR MODEL (the wind-industry practice: model what the signal does when healthy,
   watch the residual). The hall temperature moves some signals (a warm belt slips more, a warm
   manifold leaks more); its effect is fitted on the population machines against the slow trend
   (a rolling median) and divided out: r_c = r_obs / exp(beta (T - 21 C)).

2  PHYSICS-INFORMED HEALTH STATE. Each part wears along its own law (health.py):
   r = 1 + (r_fail - 1) w^p, w the share of its life used. The state is w itself - linear in use,
   failure at exactly w = 1 - so the degradation model can be the simplest correct one: a level
   and a wear rate (a Wiener process with drift whose rate may change when a disturbance starts).

3  EXTENDED KALMAN FILTER. State [w, rate]; dynamics w += rate per order, the rate a slow random
   walk; the measurement is the part's own law r = 1 + (r_fail - 1) w^p with multiplicative noise
   of the population's measured spread. Where the law is flat (a sudden-onset part early in life,
   p = 10 for the gearbox) the measurement carries no information and the filter says so: its
   uncertainty stays wide, honestly. The state is kept physical after every update - wear in
   [0, 1.2], its rate never negative (a constrained, truncated filter): without that a steep law
   can push the estimate below zero, where the law is flat and the filter never recovers.
   Standardised innovations e_t ~ N(0, 1) while the model holds.

4  REMAINING USEFUL LIFE AS A DISTRIBUTION. Draw (w, rate) from the filter's posterior; for each,
   the first passage of a Wiener process with drift to w = 1 is inverse Gaussian (Wald):
   mean (1 - w) / rate, shape (1 - w)^2 / sigma_d^2. Their mixture gives P10/P50/P90 and
   P(failure within H orders) - the number the decision needs.

5  DETECTION OF ABNORMAL WEAR. The innovations feed a CUSUM (a wear rate above the model's) and
   Bayesian online change-point detection (when it began); across components Hotelling's T^2
   (behaviour no single part's model explains).
"""
from dataclasses import dataclass, field

import month as M
import numpy as np

COMPS = list(M.COMP)
I_TEMP = M.FEATURES.index("temp_c")
T_REF = 21.0
N_DRAW = 300
RNG = np.random.default_rng(11)


@dataclass
class Population:
    """What the fleet teaches: per component the temperature coefficient and the noise level, and
    two uncertainty scales - how fast a wear rate may change, how much wear wanders around its
    rate - calibrated so the remaining-life intervals hold as often as they claim."""
    beta: dict = field(default_factory=dict)
    noise: dict = field(default_factory=dict)
    q_scale: float = 0.01
    d_scale: float = 0.3


def _roll_median(x: np.ndarray, w: int = 61) -> np.ndarray:
    pad = w // 2
    xp = np.pad(x, pad, mode="edge")
    idx = np.arange(len(x))[:, None] + np.arange(w)[None, :]
    return np.median(xp[idx], axis=1)


def fit_population(fleet: dict, ids: list[int]) -> Population:
    """The normal-behaviour model and the noise levels, from the population machines: log r
    against the hall temperature, both taken relative to their slow trend (so wear does not
    pass for a temperature effect), then the robust spread (MAD) of what is left."""
    pop = Population()
    for c, k in enumerate(COMPS):
        xs, ys = [], []
        for i in ids:
            X = fleet[i][0]
            y = np.log(np.maximum(X[:, c], 1e-6))
            T = X[:, I_TEMP]
            xs.append(T - _roll_median(T))
            ys.append(y - _roll_median(y))
        x, y = np.concatenate(xs), np.concatenate(ys)
        b = float((x * y).sum() / max(1e-12, (x * x).sum()))
        res = y - b * x
        pop.beta[k] = b
        pop.noise[k] = float(1.4826 * np.median(np.abs(res - np.median(res))))
    return pop


@dataclass
class Track:
    """Per order: the filter's wear state and rate, the remaining life (P10/P50/P90, orders) and
    the probability of failure within the horizon; the standardised innovation."""
    w: np.ndarray
    rate: np.ndarray
    p10: np.ndarray
    p50: np.ndarray
    p90: np.ndarray
    p_fail: np.ndarray
    innov: np.ndarray


def track(X: np.ndarray, k: str, pop: Population, resets: list[int], horizon: int = 90,
          start_w: tuple[float, float] = (0.35, 0.3), rul: bool = True) -> Track:
    """Run the filter over one machine for component k. `resets`: orders at which the part was
    renewed (the maintenance log), after which the state restarts at a new part."""
    c = COMPS.index(k)
    C = M.COMP[k]
    p, rf, s = float(C["p"]), float(C["r_fail"]), max(pop.noise[k], 1e-4)
    nu = C["per_order"] / C["life"]                          # nominal wear per order (rate 1)
    q_rate = (pop.q_scale * nu) ** 2                         # the rate's random walk per order
    sig_d2 = (pop.d_scale * nu) ** 2                         # wear diffusion per order
    n = len(X)
    out = {f: np.full(n, np.nan) for f in ("w", "rate", "p10", "p50", "p90", "p_fail", "innov")}
    r_c = X[:, c] / np.exp(pop.beta[k] * (X[:, I_TEMP] - T_REF))
    resets = set(resets)

    def fresh(new_part: bool):
        m0, v0 = (0.02, 0.01) if new_part else start_w
        return np.array([m0, nu]), np.diag([v0 ** 2, (3 * nu) ** 2])

    x, P = fresh(False)
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    Q = np.diag([1e-12, q_rate])
    for t in range(n):
        if t in resets:
            x, P = fresh(True)
        x = F @ x
        P = F @ P @ F.T + Q
        # iterated EKF update (Gauss-Newton on the measurement law): a steep law - the gearbox's
        # p = 10 - is relinearised where the state lands, not where it was predicted
        xp, xi = x.copy(), x.copy()
        for _ in range(3):
            wz = min(max(xi[0], 1e-3), 1.2)
            h = 1 + (rf - 1) * wz ** p
            Hj = (rf - 1) * p * wz ** (p - 1)
            R = (s * h) ** 2
            S = Hj * Hj * P[0, 0] + R
            K = P[:, 0] * Hj / S
            xi = xp + K * (r_c[t] - h - Hj * (xp[0] - xi[0]))
            xi[0] = min(max(xi[0], 0.0), 1.2)                  # wear is never negative...
        wz0 = min(max(xp[0], 1e-3), 1.2)
        h0 = 1 + (rf - 1) * wz0 ** p
        H0 = (rf - 1) * p * wz0 ** (p - 1)
        S0 = H0 * H0 * P[0, 0] + (s * h0) ** 2
        e0 = r_c[t] - h0                                       # the innovation of the prediction
        x = xi
        x[1] = max(x[1], 0.0)                                  # ...and never runs backwards
        P = P - np.outer(K, Hj * P[0, :])
        P = (P + P.T) / 2
        out["w"][t], out["rate"][t], out["innov"][t] = x[0], x[1], e0 / np.sqrt(S0)
        if not rul:
            continue
        # the remaining life: the mixture of first-passage times over the posterior
        draws = RNG.multivariate_normal(x, P, N_DRAW, method="cholesky") if np.all(np.linalg.eigvalsh(P) > 0) \
            else np.tile(x, (N_DRAW, 1))
        gap = 1.0 - draws[:, 0]
        rate = draws[:, 1]
        T = np.full(N_DRAW, np.inf)
        dead = gap <= 0
        T[dead] = 0.0
        ok = (~dead) & (rate > 1e-12)
        if ok.any():
            mean = gap[ok] / rate[ok]
            shape = gap[ok] ** 2 / sig_d2
            T[ok] = RNG.wald(mean, shape)
        q = np.quantile(np.where(np.isinf(T), 1e9, T), [0.1, 0.5, 0.9])
        out["p10"][t], out["p50"][t], out["p90"][t] = q
        out["p_fail"][t] = float((T <= horizon).mean())
    return Track(**out)


def calibrate_noise(fleet: dict, ids: list[int], pop: Population) -> None:
    """Innovation-based adaptive estimation (Mehra 1970): run the filters on the population and
    scale each component's noise until its standardised innovations have unit spread (robust)."""
    for k in COMPS:
        for _ in range(2):
            e = []
            for i in ids:
                X, F, _ = fleet[i]
                tr = track(X, k, pop, [f + 1 for f, kk in F if kk == k], rul=False)
                e.append(tr.innov[~np.isnan(tr.innov)])
            e = np.concatenate(e)
            sd = 1.4826 * float(np.median(np.abs(e - np.median(e))))
            pop.noise[k] *= max(0.5, min(3.0, sd))


def alarms(tr: Track, p_star: float, run: int = 3) -> list[int]:
    """Orders where P(failure within the horizon) has been at least p* for `run` orders running:
    the pre-failure window is open."""
    hit = tr.p_fail >= p_star
    out, n = [], 0
    for t, h in enumerate(hit):
        n = n + 1 if h else 0
        if n >= run:
            out.append(t)
    return out
