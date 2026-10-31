"""
Calibrated remaining life: conformal prediction on top of the physics-informed filter.

The filter (pdm/model.py) gives each order a remaining-life distribution, P10/P50/P90. Its two
uncertainty scales were tuned so that the P10-P90 interval holds the true life 80 % of the time
on the population machines - on average. Nothing promises that on a new machine, for one part, or
in the last shift before a failure, where a maintenance decision is actually taken. Conformal
prediction (Vovk, Gammerman & Shafer 2005) turns any predictor into intervals with a coverage
guarantee that holds in finite samples, assuming only that the calibration machines and the new
machine are exchangeable - drawn from the same fleet. It does not need the filter to be right;
it measures how wrong the filter is on machines it never fitted and widens (or narrows) by that.

1  CALIBRATION MACHINES 16-31: neither fitted the filter (0-15) nor graded it (64-79).

2  SCORES IN LOG TIME. Remaining life is a scale quantity (an error of 20 orders matters with 30
   left, not with 300), so every score is taken on log(1 + RUL).

3  TWO-SIDED: CONFORMALISED QUANTILE REGRESSION (Romano, Patterson & Candes 2019). The score is
   how far the truth fell outside [P10, P90]: s = max(lo - y, y - hi). Its finite-sample quantile
   q at ceil((n + 1)(1 - alpha)) / n gives [P10 e^-q, P90 e^q] (in 1 + RUL), which holds the truth
   with probability >= 1 - alpha.

4  ONE-SIDED: A LOWER BOUND ON THE REMAINING LIFE. A maintenance decision needs "the part lasts at
   least L orders with 90 % probability", not an interval: s = lo - y, L = (1 + P10) e^-q - 1.

5  MONDRIAN BY COMPONENT (Vovk et al. 2003). Marginal coverage can hide a part that is always
   missed (the gearbox's steep law gives the filter little to work with until late). Calibrating
   each component on its own scores gives the guarantee per component; components with too few
   calibration failures fall back to the pooled quantile.

6  DEPENDENCE. Orders on one machine are not exchangeable with each other - the machines are. The
   pooled quantile over all orders of exchangeable machines keeps the guarantee on average over
   machines; the spread from machine to machine is reported (a bootstrap over test machines), not
   hidden.

7  THE DECISION ITSELF: CONFORMAL RISK CONTROL (Angelopoulos, Bates, Fisch, Lei & Schuster 2024).
   The window opens when P(failure within the horizon) >= p*. Choosing p* on the population (as
   pdm/run.py does) gives no promise about the share of failures warned too late. The loss of a
   failure - 1 if its window opened less than a shift ahead - only grows with p*, so the largest
   p* whose calibration loss satisfies (n R(p*) + 1) / (n + 1) <= alpha bounds the expected share
   of late failures on new machines by alpha; of those p*, it is the one with the fewest false
   alarms.

Graded on the test machines: coverage (marginal, per component, by true remaining life), interval
width, the lower bound's coverage, and the late share of the risk-controlled decision.

    STF_VARIANT=up7 python3 -m pdm.conformal     (from stf-cad/hbw; or `make conformal`)
"""
import json
import os
import pickle
import time

import numpy as np

from pdm import cp
from pdm import data
from pdm import model as Mo
from pdm import run as R

CAL = list(range(16, 32))
ALPHA = 0.1                      # 90 % intervals and lower bounds
ALPHA_LATE = 0.05                # at most 5 % of failures warned less than a shift ahead
MIN_SEG = 5                      # calibration failures a group needs for its own quantile
LIFE_BINS = [45, 150]            # predicted (P50) remaining life: under a shift, under three, more
BUCKETS = [(0, 45), (45, 150), (150, R.RUL_CAP)]    # true remaining life: a shift, three, the rest
P_FINE = [round(x, 3) for x in np.concatenate([np.arange(0.01, 0.1, 0.01), np.arange(0.1, 0.81, 0.05)])]
N_BOOT = 1000
CACHE = os.path.join(os.path.dirname(data.CACHE), "pdm_tracks.pkl")
OUT = R.OUT


# ---------------------------------------------------------------- the filter's tracks, cached

def tracks(fleet, pop, ids, tag=None):
    """The filter's tracks for `ids`, cached per (machine, uncertainty scales): the 19-minute
    calibration grid of pdm/run.py is not repeated, its chosen scales are read from pdm.json.
    `tag` names a fleet other than the nominal one (pdm/drift.py's shifted machines)."""
    key = (round(pop.q_scale, 6), round(pop.d_scale, 6)) + ((tag,) if tag else ()) + (("temp_failure",) if pop.temp_failure else ())
    have = {}
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as fh:
            have = pickle.load(fh)
    todo = [i for i in ids if (key, i) not in have]
    if todo:
        new = R.tracks(fleet, todo, pop)
        for (i, k), tr in new.items():
            have.setdefault((key, i), {})[k] = tr
        with open(CACHE, "wb") as fh:
            pickle.dump(have, fh)
    return {(i, k): have[(key, i)][k] for i in ids for k in Mo.COMPS}


# ---------------------------------------------------------------- the scored points

def points(fleet, ids, trk):
    """Every order whose remaining life is known and under the cap (the orders pdm/run.py grades):
    machine, component index, segment id, true life, P10, P50, P90, the order its stretch fails at."""
    rows = []
    seg = 0
    for i in ids:
        F = fleet[i][1]
        for c, k in enumerate(Mo.COMPS):
            tr = trk[(i, k)]
            start = 0
            for f in sorted(f for f, kk in F if kk == k):
                t = np.arange(start, f + 1)
                rul = f - t
                m = rul < R.RUL_CAP
                t, rul = t[m], rul[m]
                rows.append(np.stack([np.full(len(t), i), np.full(len(t), c), np.full(len(t), seg), rul,
                                      tr.p10[t], tr.p50[t], tr.p90[t], np.full(len(t), f)], 1))
                seg += 1
                start = f + 1
    a = np.concatenate(rows) if rows else np.zeros((0, 8))
    return {"machine": a[:, 0].astype(int), "comp": a[:, 1].astype(int), "seg": a[:, 2].astype(int),
            "rul": a[:, 3], "p10": a[:, 4], "p50": a[:, 5], "p90": a[:, 6], "fail": a[:, 7].astype(int)}


def cqr_scores(p):
    return cp.cqr_score(cp.log_life(p["rul"]), cp.log_life(p["p10"]), cp.log_life(p["p90"]))


def lower_scores(p):
    return cp.lower_score(cp.log_life(p["rul"]), cp.log_life(p["p10"]))


def life_bin(p):
    """The filter's own median remaining life, binned at a shift and three shifts: an observable
    stand-in for how close the part is to failing."""
    return np.digitize(p["p50"], LIFE_BINS)


def fit(cal, alpha=ALPHA):
    """The calibration quantiles for the interval (q2) and the lower bound (q1): pooled, per
    component (Mondrian), and per component and predicted life. A group's own quantile needs
    MIN_SEG calibration failures (its independent units); else it falls back a level - the
    component's, then the pooled."""
    s2, s1 = cqr_scores(cal), lower_scores(cal)
    q2, p2 = cp.mondrian_q(s2, cal["comp"], cal["seg"], alpha, MIN_SEG)
    q1, p1 = cp.mondrian_q(s1, cal["comp"], cal["seg"], alpha, MIN_SEG)
    cell = cal["comp"] * 10 + life_bin(cal)
    c2, _ = cp.mondrian_q(s2, cell, cal["seg"], alpha, MIN_SEG)
    c1, _ = cp.mondrian_q(s1, cell, cal["seg"], alpha, MIN_SEG)
    out = {"pooled": {"q2": p2, "q1": p1}, "comp": {}}
    for c, k in enumerate(Mo.COMPS):
        m = cal["comp"] == c
        own = q2.get(c, (p2, False))[1]
        e = {"segments": int(len(np.unique(cal["seg"][m]))), "own": bool(own),
             "q2": q2.get(c, (p2, False))[0], "q1": q1.get(c, (p1, False))[0], "bins": []}
        for b in range(len(LIFE_BINS) + 1):
            g = c * 10 + b
            mine = c2.get(g, (None, False))[1]
            e["bins"].append({"own": bool(mine), "q2": c2[g][0] if mine else e["q2"], "q1": c1[g][0] if mine else e["q1"]})
        out["comp"][k] = e
    return out


def apply(p, q):
    """Intervals and lower bounds for the scored points: the filter's own, then conformal pooled,
    per component, and per component and predicted life."""
    lo, hi = cp.log_life(p["p10"]), cp.log_life(p["p90"])
    q2c = np.array([q["comp"][k]["q2"] for k in Mo.COMPS])[p["comp"]]
    q1c = np.array([q["comp"][k]["q1"] for k in Mo.COMPS])[p["comp"]]
    B2 = np.array([[b["q2"] for b in q["comp"][k]["bins"]] for k in Mo.COMPS])
    B1 = np.array([[b["q1"] for b in q["comp"][k]["bins"]] for k in Mo.COMPS])
    b = life_bin(p)
    q2b, q1b = B2[p["comp"], b], B1[p["comp"], b]
    qp2, qp1 = q["pooled"]["q2"], q["pooled"]["q1"]
    return {
        "filter":  {"lo": lo, "hi": hi, "lb": lo},
        "pooled":  {"lo": lo - qp2, "hi": hi + qp2, "lb": lo - qp1},
        "component": {"lo": lo - q2c, "hi": hi + q2c, "lb": lo - q1c},
        "component_life": {"lo": lo - q2b, "hi": hi + q2b, "lb": lo - q1b},
    }


# ---------------------------------------------------------------- grading

def _cover(p, iv, m=None):
    y = cp.log_life(p["rul"])
    m = np.ones(len(y), bool) if m is None else m
    if not m.any():
        return None
    inside = (iv["lo"][m] <= y[m]) & (y[m] <= iv["hi"][m])
    above = y[m] >= iv["lb"][m]
    width = np.expm1(np.minimum(iv["hi"][m], 30)) - np.expm1(np.maximum(iv["lo"][m], 0))
    return {"n": int(m.sum()), "coverage": round(float(inside.mean()), 3),
            "lower_coverage": round(float(above.mean()), 3),
            "width_median": round(float(np.median(np.minimum(width, 1e4))), 1),
            "lower_median": round(float(np.median(np.expm1(np.maximum(iv["lb"][m], 0)))), 1)}


def _boot(p, iv, rng):
    """A bootstrap over test machines: the machine-to-machine spread of the coverage."""
    y = cp.log_life(p["rul"])
    machines = np.unique(p["machine"])
    per = {i: (p["machine"] == i) for i in machines}
    ins = (iv["lo"] <= y) & (y <= iv["hi"])
    above = y >= iv["lb"]
    c2, c1 = [], []
    for _ in range(N_BOOT):
        pick = rng.choice(machines, len(machines))
        m = np.concatenate([np.nonzero(per[i])[0] for i in pick])
        c2.append(ins[m].mean()); c1.append(above[m].mean())
    q = lambda v: [round(float(np.quantile(v, 0.05)), 3), round(float(np.quantile(v, 0.95)), 3)]
    return {"coverage_90ci": q(c2), "lower_coverage_90ci": q(c1)}


def grade(p, ivs):
    rng = np.random.default_rng(31)
    y = p["rul"]
    out = {}
    for name, iv in ivs.items():
        r = {"all": _cover(p, iv), **_boot(p, iv, rng)}
        r["by_life"] = {f"{a}-{b}": _cover(p, iv, (y >= a) & (y < b)) for a, b in BUCKETS}
        r["by_comp"] = {k: _cover(p, iv, p["comp"] == c) for c, k in enumerate(Mo.COMPS)}
        cs = [v["coverage"] for v in r["by_comp"].values() if v]
        r["worst_comp_coverage"] = min(cs) if cs else None
        out[name] = r
    return out


# ---------------------------------------------------------------- the decision: risk control

def late_losses(fleet, ids, trk, p_star):
    """Per failure: 1 if the window opened less than a shift ahead (or never), else 0; and the
    false alarms, graded as pdm/run.py does."""
    loss, false, orders = [], 0, 0
    for i in ids:
        X, F, _ = fleet[i]
        orders += len(X)
        for k in Mo.COMPS:
            leads, fa, missed = R.decisions(Mo.alarms(trk[(i, k)], p_star), len(X), F, k)
            loss += [0 if l >= R.CRIT else 1 for l in leads] + [1] * missed
            false += fa
    return np.array(loss, float), false, orders


def risk_control(fleet, trk, alpha=ALPHA_LATE):
    """The largest p* whose calibration late share keeps (n R + 1) / (n + 1) <= alpha; the
    smallest p* tried if none does (the guarantee is then not met, and said so)."""
    grid, losses = [], []
    for p in P_FINE:
        loss, false, orders = late_losses(fleet, CAL, trk, p)
        losses.append((p, loss))
        grid.append({"p_star": p, "late_share": round(float(loss.mean()), 4), "bound": round(cp.crc_bound(loss), 4),
                     "false_per_1000": round(1000 * false / max(1, orders), 2), "failures": len(loss)})
    chosen, _ = cp.crc_choose(losses, alpha)
    return (chosen if chosen is not None else P_FINE[0]), grid, chosen is not None


def decision_on(fleet, ids, trk, p_star, name):
    loss, false, orders = late_losses(fleet, ids, trk, p_star)
    return {"name": name, "p_star": p_star, "failures": len(loss), "late": int(loss.sum()),
            "late_share": round(float(loss.mean()), 4) if len(loss) else None,
            "false_per_1000": round(1000 * false / max(1, orders), 2)}


# ---------------------------------------------------------------- run

def population():
    """The fitted population, with the uncertainty scales and p* pdm/run.py chose (pdm.json)."""
    with open(os.path.join(OUT, "pdm.json")) as fh:
        doc = json.load(fh)
    fleet = data.load(data.FIT + CAL + data.TEST)
    pop = Mo.fit_population(fleet, data.FIT)
    Mo.calibrate_noise(fleet, data.FIT, pop)
    pop.q_scale, pop.d_scale = doc["q_scale"], doc["d_scale"]
    return fleet, pop, doc["p_star"]


def main():
    t0 = time.time()
    fleet, pop, p_pop = population()
    trk = tracks(fleet, pop, CAL + data.TEST)
    cal, test = points(fleet, CAL, trk), points(fleet, data.TEST, trk)
    q = fit(cal)
    res = grade(test, apply(test, q))
    p_crc, grid, feasible = risk_control(fleet, trk)
    dec = [decision_on(fleet, data.TEST, trk, p_pop, "p* from the population (pdm/run.py)"),
           decision_on(fleet, data.TEST, trk, p_crc, f"p* by conformal risk control (late share <= {ALPHA_LATE})")]
    doc = {
        "method": "split conformal on the filter's remaining-life quantiles, in log(1 + RUL): CQR interval, "
                  "one-sided lower bound, Mondrian per component; conformal risk control of the alarm threshold",
        "alpha": ALPHA, "alpha_late": ALPHA_LATE, "cal_machines": CAL, "test_machines": data.TEST,
        "cal_points": len(cal["rul"]), "cal_segments": int(len(np.unique(cal["seg"]))), "test_points": len(test["rul"]),
        "quantiles": q, "intervals": res, "risk_control": {"grid": grid, "feasible": feasible, "p_star": p_crc},
        "decisions": dec, "seconds": round(time.time() - t0, 1),
    }
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "conformal.json"), "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    for name, r in res.items():
        a = r["all"]
        print(f"  {name:14s} cover {a['coverage']:.3f} {r['coverage_90ci']}  lower-bound cover {a['lower_coverage']:.3f}  "
              f"width {a['width_median']}  worst comp {r['worst_comp_coverage']}  "
              + "  ".join(f"{b}: {v['coverage']}" for b, v in r["by_life"].items() if v))
    for d in dec:
        print(f"  {d['name']}: p* {d['p_star']}  late {d['late']}/{d['failures']}  false/1000 {d['false_per_1000']}")
    print(f"  {doc['seconds']} s")
    return doc


if __name__ == "__main__":
    main()
