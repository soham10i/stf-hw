"""
When the plant drifts: do the guarantees hold, can the drift be seen, can they be won back?

Every guarantee of pdm/conformal.py assumes a new machine is exchangeable with the calibration
machines. A line commissioned elsewhere is not: a hotter hall, noisier sensors, heavier duty, a part
from another supplier that wears along another law. The twin can build exactly that machine: the
test machines 64-79 run again with one thing changed (month.Month(shift=...)), keeping each
machine's own wear, disturbances and random draws - so every difference below is the shift's.

  hot     the hall 6 degC warmer
  noisy   every sensor twice as noisy (a worn sensor, EMI)
  fast    every part wears 1.6 x as fast (heavier duty)
  law     every wear law's exponent x 0.7: wear shows earlier than the model's law believes
          (another supplier's part - the model-plant mismatch a twin can carry unnoticed)

1  STATIC: the calibration of pdm/conformal.py and its risk-controlled p*, applied unchanged.

2  DETECTION FROM THE INPUTS, WITHOUT LABELS. The filter's standardised innovations come with
   every order. Per order the median of the squared innovations across the parts (one part near
   its knee - the gearbox under a 5 x disturbance reaches 200 - is a local anomaly for the CUSUM,
   not a drift of the plant), per block of BLOCK orders their median, after a burn-in while the
   filter settles; each block ranked against the calibration machines' blocks is a conformal
   p-value. A conformal test martingale (Vovk, Nouretdinov & Gammerman 2003) bets against their
   uniformity; by Ville's inequality P(it ever reaches 1/delta) <= delta while nothing changed.

3  DETECTION FROM THE OUTCOMES. A shift that the filter absorbs into its wear estimate leaves the
   innovations white and shows only in WHEN parts fail. Each failure labels its stretch; the
   stretch's mean lower-bound score (how optimistic P10 was) ranked against the calibration
   stretches is a p-value per failure - failures are the exchangeable units - and the same
   martingale runs over the fleet's failures in the order they happen (Podkopaev & Ramdas 2022:
   only the labels tell a harmful shift from a benign one).

4  RECOVERY, WITH DELAYED LABELS. On the fleet's clock a failure labels its whole stretch at once.
   Weighted conformal (Barber, Candes, Ramdas & Tibshirani 2023): calibration and new scores in one
   weighted quantile, each weight decaying by RHO per failure since it arrived, so the old fleet
   fades out; adaptive conformal inference (Gibbs & Candes 2021) moves the miscoverage level by
   gamma (alpha - err) after each failure. Pooled, and per part (Mondrian) with the pooled quantile
   where a part has too few stretches yet.

5  THE DECISION, ONLINE. The alarm threshold tracked the same way - quantile tracking as in
   conformal PID control (Angelopoulos, Candes & Tibshirani 2023): after each failure
   p* <- p* - eta (late - alpha). And the best fixed p* in hindsight: can any threshold save it?

    STF_VARIANT=up7 python3 -m pdm.drift        (from stf-cad/hbw; or `make drift`)
"""
import json
import os
import time
from multiprocessing import Pool

import numpy as np

from pdm import conformal as K
from pdm import cp, data
from pdm import model as Mo
from pdm import run as R

SHIFTS = {
    "hot":   {"temp": 6.0},
    "noisy": {"sig": 2.0},
    "fast":  {"rate": 1.6},
    "law":   {"p": 0.7},
}
SAY = {"nominal": "the test machines as they are", "hot": "hall +6 degC", "noisy": "sensor noise x 2",
       "fast": "wear x 1.6", "law": "wear-law exponent x 0.7"}
CACHE = os.path.join(os.path.dirname(data.CACHE), "pdm_drift.npz")
BURN = 135            # orders (two shifts) while the filter settles
BLOCK = 15            # orders per detection block (a shift is ~67 orders)
DELTA = 0.01          # Ville: P(false alarm ever) <= 1 %
RHO = 0.95            # weight decay per failure seen
GAMMA = 0.02          # ACI step
ETA = 0.2             # online p* step


# ---------------------------------------------------------------- the shifted fleets

def _one(args):
    name, i = args
    os.environ.setdefault("STF_VARIANT", "up7")
    from ml import fleet
    return name, i, fleet.machine(i, SHIFTS[name])


def load():
    """{shift: {machine: (X, failures, rule warnings)}}, the nominal test machines included."""
    have = {}
    if os.path.exists(CACHE):
        have = np.load(CACHE, allow_pickle=True)["fleet"].item()
    todo = [(n, i) for n in SHIFTS for i in data.TEST if (n, i) not in have]
    if todo:
        with Pool(min(len(todo), os.cpu_count() or 4)) as p:
            for n, i, m in p.imap_unordered(_one, todo):
                have[(n, i)] = m
                print(f"  {n} machine {i}: {len(m[0])} orders, {len(m[1])} failures", flush=True)
        np.savez_compressed(CACHE, fleet=np.array(have, dtype=object))
    out = {"nominal": data.load(data.TEST)}
    for n in SHIFTS:
        out[n] = {i: have[(n, i)] for i in data.TEST}
    return out


def with_times(p):
    """Each scored point's own order index (its stretch fails at p["fail"])."""
    p["t"] = p["fail"] - p["rul"].astype(int)
    return p


# ---------------------------------------------------------------- 2 detection from the inputs

def innovation_blocks(trk, ids):
    """Per machine: per block, the median over its orders of the median squared innovation
    across the parts."""
    out = {}
    for i in ids:
        E = np.stack([trk[(i, k)].innov for k in Mo.COMPS], 1)
        e2 = np.nanmedian(E ** 2, axis=1)[BURN:]
        nb = len(e2) // BLOCK
        out[i] = np.median(e2[: nb * BLOCK].reshape(nb, BLOCK), axis=1)
    return out


def detect_inputs(ref_blocks, blocks, rng):
    ref = np.concatenate(list(ref_blocks.values()))
    thr = np.log(1 / DELTA)
    first = {}
    for i, b in blocks.items():
        lm = cp.mixture_martingale(cp.p_values(ref, b, rng))
        first[i] = BURN + (int(np.argmax(lm >= thr)) + 1) * BLOCK if (lm >= thr).any() else None
    hit = [v for v in first.values() if v is not None]
    return {"machines_alarmed": len(hit), "machines": len(first),
            "median_delay_orders": float(np.median(hit)) if hit else None, "first": first}


# ---------------------------------------------------------------- 3 detection from the outcomes

def stretch_scores(p):
    """Per labelled stretch (one failure): its mean lower-bound score and the order it failed at."""
    s = K.lower_scores(p)
    segs = np.unique(p["seg"])
    return np.array([s[p["seg"] == g].mean() for g in segs]), np.array([p["fail"][p["seg"] == g][0] for g in segs])


def detect_outcomes(cal, test, rng):
    ref, _ = stretch_scores(cal)
    x, t = stretch_scores(test)
    o = np.argsort(t, kind="stable")
    lm = cp.mixture_martingale(cp.p_values(ref, x[o], rng))
    thr = np.log(1 / DELTA)
    k = int(np.argmax(lm >= thr)) if (lm >= thr).any() else None
    return {"failures_to_alarm": (k + 1) if k is not None else None, "failures": len(x),
            "alarm_order": int(t[o][k]) if k is not None else None,
            "log_m": [round(float(v), 2) for v in lm]}


# ---------------------------------------------------------------- 4 recovery with delayed labels

def online(cal, test, kind, per_part):
    """Intervals (kind "cqr") or lower bounds (kind "lower") on the test fleet's clock: a point at
    order t is served the quantile computed after the last failure before t. Weighted conformal
    + ACI, pooled or per part. Returns a boolean 'covered' per test point."""
    score = K.cqr_scores if kind == "cqr" else K.lower_scores
    s_cal, s_new = score(cal), score(test)
    segs = np.unique(test["seg"])
    end = {g: int(test["fail"][test["seg"] == g][0]) for g in segs}
    events = sorted(segs, key=lambda g: end[g])
    t_ev = np.array([end[g] for g in events])
    idx = np.searchsorted(t_ev, test["t"], side="left")          # failures known before the point
    C = len(Mo.COMPS)
    qs = np.empty((len(events) + 1, C))
    alpha = K.ALPHA
    new_s, new_c, new_seg, new_j = [], [], [], []
    for j in range(len(events) + 1):
        w = np.concatenate([np.full(len(s_cal), RHO ** j)] + [np.full(len(a), RHO ** (j - b)) for a, b in zip(new_s, new_j)])
        s = np.concatenate([s_cal] + new_s)
        comp = np.concatenate([cal["comp"]] + new_c)
        seg = np.concatenate([cal["seg"]] + new_seg)
        pooled = cp.weighted_q(s, w, alpha)
        for c in range(C):
            m = comp == c
            own = per_part and len(np.unique(seg[m])) >= K.MIN_SEG
            qs[j, c] = cp.weighted_q(s[m], w[m], alpha) if own else pooled
        if j == len(events):
            break
        m = test["seg"] == events[j]
        new_s.append(s_new[m]); new_c.append(test["comp"][m]); new_seg.append(test["seg"][m] + 100_000); new_j.append(j + 1)
        err = float((s_new[m] > qs[idx[m], test["comp"][m]]).mean())     # served before this failure
        alpha = cp.aci_step(alpha, K.ALPHA, err, GAMMA)
    return s_new <= qs[idx, test["comp"]]


def static(cal, test):
    """T1's best static method (per part x predicted life), applied unchanged."""
    iv = K.apply(test, K.fit(cal))["component_life"]
    y = cp.log_life(test["rul"])
    return (iv["lo"] <= y) & (y <= iv["hi"]), y >= iv["lb"]


def report(test, cov):
    last = test["rul"] < 45
    per = [cov[test["comp"] == c].mean() for c in range(len(Mo.COMPS)) if (test["comp"] == c).any()]
    return {"all": round(float(cov.mean()), 3), "last_shift": round(float(cov[last].mean()), 3),
            "worst_part": round(float(min(per)), 3)}


# ---------------------------------------------------------------- 5 the decision, online

def _alarms(p_fail, th, start, stop):
    run = 0
    for t in range(start, stop):
        run = run + 1 if p_fail[t] >= th[t] else 0
        if run >= 3:
            return t
    return None


def online_p_star(fleet, trk, p0):
    """p* tracked on the fleet's clock: after each failure p* <- p* - eta (late - alpha)."""
    ids = sorted(fleet)
    T = max(len(fleet[i][0]) for i in ids)
    th = np.full(T, p0)
    p = p0
    late = []
    for f, i, k in sorted((f, i, k) for i in ids for f, k in fleet[i][1]):
        prev = [ff for ff, kk in fleet[i][1] if kk == k and ff < f]
        start = (max(prev) + 1) if prev else 0
        a = _alarms(trk[(i, k)].p_fail, th, start, f + 1)
        late.append(0 if a is not None and f - a >= R.CRIT else 1)
        p = float(np.clip(p - ETA * (late[-1] - K.ALPHA_LATE), 0.01, 0.8))
        th[f + 1:] = p
    false, orders = 0, 0
    for i in ids:
        X, F, _ = fleet[i]
        n = len(X)
        orders += n
        for k in Mo.COMPS:
            pf = trk[(i, k)].p_fail
            al, run = [], 0
            for t in range(n):
                run = run + 1 if pf[t] >= th[t] else 0
                if run >= 3:
                    al.append(t)
            false += R.decisions(al, n, F, k)[1]
    return {"late": int(sum(late)), "failures": len(late), "late_share": round(float(np.mean(late)), 4),
            "false_per_1000": round(1000 * false / max(1, orders), 2), "p_star_end": round(p, 3)}


def hindsight(fleet, trk):
    """The late share and false alarms of every fixed p*, on the shifted fleet itself: is there a
    threshold that would have saved it?"""
    out = []
    for p in K.P_FINE:
        loss, false, orders = K.late_losses(fleet, sorted(fleet), trk, p)
        out.append({"p_star": p, "late_share": round(float(loss.mean()), 4), "false_per_1000": round(1000 * false / orders, 2)})
    ok = [r for r in out if r["late_share"] <= K.ALPHA_LATE]
    return {"best": min(ok, key=lambda r: r["false_per_1000"]) if ok else None, "lowest_late": min(out, key=lambda r: r["late_share"])}


# ---------------------------------------------------------------- run

def study(fleets, pop, cal_fleet, rng, label):
    """Every measurement, for one model of the filter (its own calibration and risk-controlled p*)."""
    tag = "temp_failure" if pop.temp_failure else ""
    trk_cal = K.tracks(cal_fleet, pop, K.CAL)
    cal = K.points(cal_fleet, K.CAL, trk_cal)
    p_crc, _, _ = K.risk_control(cal_fleet, trk_cal)
    ref_blocks = innovation_blocks(trk_cal, K.CAL)
    out = {"p_star_static": p_crc, "shifts": {}}
    for name, fl in fleets.items():
        trk = K.tracks(fl, pop, data.TEST, tag=None if name == "nominal" else f"drift:{name}")
        test = with_times(K.points(fl, data.TEST, trk))
        iv_s, lb_s = static(cal, test)
        iv_a, lb_a = online(cal, test, "cqr", True), online(cal, test, "lower", True)
        di = detect_inputs(ref_blocks, innovation_blocks(trk, data.TEST), rng)
        do = detect_outcomes(cal, test, rng)
        # detect, then adapt: static until either detector fires (per machine from its inputs, for
        # the fleet from its failures), the adaptive quantiles after
        gate = np.array([min(di["first"][i] or 10**9, do["alarm_order"] or 10**9) for i in test["machine"]])
        on = test["t"] >= gate
        d = {
            "failures": int(sum(len(fl[i][1]) for i in data.TEST)),
            "interval": {"static": report(test, iv_s),
                         "weighted_aci_pooled": report(test, online(cal, test, "cqr", False)),
                         "weighted_aci_per_part": report(test, iv_a),
                         "detect_then_adapt": report(test, np.where(on, iv_a, iv_s))},
            "lower_bound": {"static": report(test, lb_s),
                            "weighted_aci_per_part": report(test, lb_a),
                            "detect_then_adapt": report(test, np.where(on, lb_a, lb_s))},
            "adapted_share": round(float(on.mean()), 3),
            "decision": {"static": K.decision_on(fl, data.TEST, trk, p_crc, "static"),
                         "online": online_p_star(fl, trk, p_crc), "hindsight": hindsight(fl, trk)},
            "detect_inputs": {k: v for k, v in di.items() if k != "first"},
            "detect_outcomes": do,
        }
        out["shifts"][name] = d
        iv, lb, dec = d["interval"], d["lower_bound"], d["decision"]
        print(f"[{label}] {name:8s} {d['failures']} failures, adapted {d['adapted_share']}")
        for m in iv:
            print(f"   {m:22s} interval {iv[m]}" + (f"  lower bound {lb[m]}" if m in lb else ""))
        print(f"   decision: static p* {p_crc} late {dec['static']['late']}/{dec['static']['failures']} false {dec['static']['false_per_1000']} | "
              f"online late {dec['online']['late']} false {dec['online']['false_per_1000']} | "
              f"lowest late any p* {dec['hindsight']['lowest_late']['late_share']}")
        print(f"   inputs: {di['machines_alarmed']}/{di['machines']} machines, median {di['median_delay_orders']} orders | "
              f"outcomes: alarm after {do['failures_to_alarm']} of {do['failures']} failures (order {do['alarm_order']})", flush=True)
    return out


def main():
    t0 = time.time()
    rng = np.random.default_rng(23)
    fleets = load()
    _, pop, _ = K.population()
    cal_fleet = data.load(K.CAL)
    doc = {"say": SAY, "alpha": K.ALPHA, "alpha_late": K.ALPHA_LATE, "burn": BURN, "block": BLOCK, "delta": DELTA,
           "rho": RHO, "gamma": GAMMA, "eta": ETA, "models": {}}
    pop.temp_failure = False
    doc["models"]["standard"] = study(fleets, pop, cal_fleet, rng, "failure at w = 1, as first graded")
    pop.temp_failure = True
    doc["models"]["temp_failure"] = study(fleets, pop, cal_fleet, rng, "failure on the raw signal")
    doc["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(K.OUT, "drift.json"), "w") as fh:
        json.dump(doc, fh, separators=(",", ":"), default=float)
    print(f"  {doc['seconds']} s")
    return doc


if __name__ == "__main__":
    main()
