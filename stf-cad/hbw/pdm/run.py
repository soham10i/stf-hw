"""
The predictive-maintenance pipeline, fitted on the population and graded on unseen machines.

    STF_VARIANT=up7 python3 -m pdm.run          (from stf-cad/hbw; or `make pdm`)

FIT      machines 0-15: the normal-behaviour model, the noise levels, the decision threshold p*.
GRADED   machines 64-79 (the TCN's test machines, ml/train.py), with the TCN's own rule for a
         decision (ml/train.py decisions): for every failure, did the window open at least a
         shift (45 orders) ahead; alarms after the last failure where none followed are false,
         at most one per shift. Plus what a distribution can be graded on: the error of the
         median remaining life, and how often the true life fell inside P10-P90.
SHOWCASE the two months of production (month.py) without the two saves: the HBW spindle and the
         VGR gearbox fail - when did the pipeline open their pre-failure windows, and when did
         the U6 rules warn.
OUTPUT   web/public/pdm/pdm.json for the dashboard.
OPTION   PDM_FOUNDATION=chronos: Chronos-Bolt's zero-shot forecast of the health state, graded
         by the same decision (pdm/foundation.py; needs `pip install chronos-forecasting`).
"""
import json
import os
import time
from multiprocessing import Pool

import month as M
import numpy as np

from pdm import data
from pdm import model as Mo
from pdm import stats as S

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "web", "public", "pdm")
ML_RESULTS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "web", "public", "ml", "results.json")
CRIT = 45            # orders: about a shift - the least lead that lets the work go into a night gap
RUL_CAP = 300        # as the TCN: remaining life is graded where it is under 300 orders
HORIZON = 90         # P(failure within 90 orders, about two shifts)
P_GRID = [0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5]
Q_GRID = [0.01, 0.05, 0.2]       # the wear rate's random walk, x the nominal rate, per order
D_GRID = [0.3, 1.0, 3.0]         # the wear's diffusion, x the nominal rate, per order


def decisions(alarms_at, n, fails, k):
    """ml/train.py's decision grading, unchanged: per failure of k the lead of the first alarm
    since its last failure; alarms in the stretch after its last failure where no failure
    followed (and the run did not end within RUL_CAP) are false, one per shift at most."""
    fi = sorted(i for i, kk in fails if kk == k)
    leads, missed, start = [], 0, 0
    for f in fi:
        a = [i for i in alarms_at if start <= i <= f]
        if a:
            leads.append(f - a[0])
        else:
            missed += 1
        start = f + 1
    tail = [i for i in alarms_at if i >= start and n - i > RUL_CAP]
    return leads, len(set(i // 45 for i in tail)), missed


def summarise(name, leads, false, missed, orders, **extra):
    lead = np.array(leads) if leads else np.array([0])
    n_fail = len(leads) + missed
    ok = int((lead >= CRIT).sum()) if leads else 0
    return {"name": name, "failures": n_fail, "warned_1shift": ok, "warned_1shift_pct": round(100 * ok / max(1, n_fail), 1),
            "missed": missed, "late": int((lead < CRIT).sum()) if leads else 0,
            "lead_median_orders": float(np.median(lead)) if leads else None,
            "false": false, "false_per_1000": round(1000 * false / max(1, orders), 2), **extra}


def _machine_tracks(args):
    i, X, F, pop = args
    return i, {k: Mo.track(X, k, pop, [f + 1 for f, kk in F if kk == k], horizon=HORIZON) for k in Mo.COMPS}


def tracks(fleet, ids, pop):
    """Every component's track on every machine, the part renewed after each failure - one
    machine per core."""
    out = {}
    with Pool(min(len(ids), os.cpu_count() or 4)) as pool:
        for i, per in pool.imap_unordered(_machine_tracks, [(i, fleet[i][0], fleet[i][1], pop) for i in ids]):
            for k, tr in per.items():
                out[(i, k)] = tr
    return out


def grade(fleet, ids, trk, p_star, name, with_rul=True):
    leads, false, missed, orders = [], 0, 0, 0
    ae, n_ae, inside = 0.0, 0, 0
    for i in ids:
        X, F, _ = fleet[i]
        n = len(X)
        orders += n
        for k in Mo.COMPS:
            tr = trk[(i, k)]
            l, fa, mi = decisions(Mo.alarms(tr, p_star), n, F, k)
            leads += l; false += fa; missed += mi
            # the remaining life where it is known and under the cap
            fi = sorted(f for f, kk in F if kk == k)
            start = 0
            for f in fi:
                t = np.arange(start, f + 1)
                rul = f - t
                m = rul < RUL_CAP
                p50 = np.minimum(tr.p50[t][m], RUL_CAP)
                ae += float(np.abs(p50 - rul[m]).sum()); n_ae += int(m.sum())
                inside += int(((tr.p10[t][m] <= rul[m]) & (rul[m] <= tr.p90[t][m])).sum())
                start = f + 1
    if not with_rul:
        return summarise(name, leads, false, missed, orders, p_star=p_star)
    return summarise(name, leads, false, missed, orders, rul_mae_orders=round(ae / max(1, n_ae), 1),
                     p10_p90_coverage=round(inside / max(1, n_ae), 3), p_star=p_star)


def rules(fleet, ids):
    leads, false, missed, orders = [], 0, 0, 0
    for i in ids:
        X, F, R = fleet[i]
        orders += len(X)
        for k in Mo.COMPS:
            l, fa, mi = decisions(sorted(o for o, kk in R if kk == k), len(X), F, k)
            leads += l; false += fa; missed += mi
    return summarise("U6 rules (EWMA + soft limit + trend)", leads, false, missed, orders)


def detection(fleet, ids, trk):
    """The detectors on the innovations: how often each fires on a part far from failure (its
    false-alarm rate where the model should hold) and how far ahead of failures it first fires."""
    out = {"cusum": {"alarms_far": 0, "orders_far": 0, "lead": []}, "t2": {"exceed": 0, "orders": 0}}
    for i in ids:
        X, F, _ = fleet[i]
        n = len(X)
        E = np.stack([trk[(i, k)].innov for k in Mo.COMPS], 1)
        stat, lim = S.t2(E)
        out["t2"]["exceed"] += int((stat > lim).sum()); out["t2"]["orders"] += n
        out["t2"]["limit"] = round(lim, 2)
        for k in Mo.COMPS:
            fi = sorted(f for f, kk in F if kk == k)
            reset = np.zeros(n, bool)
            for f in fi:
                if f + 1 < n:
                    reset[f + 1] = True
            _, a = S.cusum(trk[(i, k)].innov, reset=reset)
            # orders more than RUL_CAP from any failure: where nothing should be found
            far = np.ones(n, bool)
            for f in fi:
                far[max(0, f - RUL_CAP):f + 1] = False
            out["cusum"]["alarms_far"] += int(a[far].sum()); out["cusum"]["orders_far"] += int(far.sum())
            start = 0
            for f in fi:
                hit = np.nonzero(a[start:f + 1])[0]
                if len(hit):
                    out["cusum"]["lead"].append(int(f - (start + hit[0])))
                start = f + 1
    c = out["cusum"]
    return {"cusum_false_rate": round(c["alarms_far"] / max(1, c["orders_far"]), 4),
            "cusum_lead_median": float(np.median(c["lead"])) if c["lead"] else None,
            "t2_exceed_rate": round(out["t2"]["exceed"] / max(1, out["t2"]["orders"]), 4),
            "t2_limit_999": out["t2"].get("limit")}


def showcase(pop, p_star):
    """The two months without the two saves: the spindle and the gearbox run to failure."""
    cf = M.Month(skip_pm=M.SAVES).run()
    X = np.array(cf.feat, dtype=float)
    ts = [o["t"] for o in cf.orders]
    out = {}
    for k in M.SAVES:
        fi = sorted(f for f, kk in cf.fail_idx if kk == k)
        tr = Mo.track(X, k, pop, [f + 1 for f in fi], horizon=HORIZON)
        al = Mo.alarms(tr, p_star)
        f = fi[0] if fi else None
        first = next((a for a in al if f is None or a <= f), None)
        warn = next((e for e in cf.events if e["kind"] == "warning" and e.get("comp") == k), None)
        w_i = next((j for j, t in enumerate(ts) if warn and t >= warn["t"]), None)
        reset = np.zeros(len(X), bool)
        _, ca = S.cusum(tr.innov, reset=reset)
        onset = int(np.argmax(ca)) if ca.any() else None
        cp, _ = S.bocpd(np.nan_to_num(tr.innov), hazard=1 / 1000)
        step = max(1, len(X) // 600)
        sl = slice(0, len(X), step)
        out[k] = {
            "name": M.COMP[k]["name"], "fail_order": f, "fail_h": ts[f] if f is not None else None,
            "window_order": first, "window_h": ts[first] if first is not None else None,
            "rule_order": w_i, "rule_h": warn["t"] if warn else None,
            "cusum_onset_order": onset, "cusum_onset_h": ts[onset] if onset is not None else None,
            "p50_at_window": round(float(tr.p50[first]), 1) if first is not None else None,
            "p10_at_window": round(float(tr.p10[first]), 1) if first is not None else None,
            "p90_at_window": round(float(tr.p90[first]), 1) if first is not None else None,
            "trace": {"h": [round(ts[j], 2) for j in range(0, len(X), step)],
                      "w": [round(float(v), 4) for v in tr.w[sl]],
                      "p_fail": [round(float(v), 3) for v in tr.p_fail[sl]],
                      "p10": [round(float(min(v, 2000)), 1) for v in tr.p10[sl]],
                      "p50": [round(float(min(v, 2000)), 1) for v in tr.p50[sl]],
                      "p90": [round(float(min(v, 2000)), 1) for v in tr.p90[sl]],
                      "change_p": [round(float(v), 3) for v in cp[sl]]},
        }
    return out


def main():
    t0 = time.time()
    fleet = data.load()
    pop = Mo.fit_population(fleet, data.FIT)
    print("normal-behaviour model (log r per degC):", {k: round(v, 4) for k, v in pop.beta.items() if abs(v) > 1e-4})
    Mo.calibrate_noise(fleet, data.FIT, pop)
    # the uncertainty scales: the P10-P90 interval should hold the true life 80 % of the time, at
    # the least median error - judged on the population only
    calib, fit_trk = [], None
    for q in Q_GRID:
        for d in D_GRID:
            pop.q_scale, pop.d_scale = q, d
            trk = tracks(fleet, data.FIT, pop)
            r = grade(fleet, data.FIT, trk, 0.3, "fit")
            score = abs(r["p10_p90_coverage"] - 0.8) + r["rul_mae_orders"] / 1000
            calib.append({"q_scale": q, "d_scale": d, "coverage": r["p10_p90_coverage"], "mae": r["rul_mae_orders"], "score": score})
            print(f"  calibrate q {q} d {d}: coverage {r['p10_p90_coverage']} MAE {r['rul_mae_orders']}", flush=True)
            if score <= min(c["score"] for c in calib):
                fit_trk = trk
    best_c = min(calib, key=lambda c: c["score"])
    pop.q_scale, pop.d_scale = best_c["q_scale"], best_c["d_scale"]
    # the decision threshold: among the p* that open at least 95 % of the population's windows a
    # shift ahead, the one with the fewest false alarms (else the most windows opened in time)
    tried = [grade(fleet, data.FIT, fit_trk, p, "fit") for p in P_GRID]
    full = [r for r in tried if r["warned_1shift_pct"] >= 95] or [max(tried, key=lambda r: r["warned_1shift_pct"])]
    best = min(full, key=lambda r: (r["false_per_1000"], -r["p_star"]))
    p_star = best["p_star"]
    print(f"p* = {p_star} (population: {best['warned_1shift_pct']} % a shift ahead, {best['false_per_1000']} false per 1000)")
    test_trk = tracks(fleet, data.TEST, pop)
    ours = grade(fleet, data.TEST, test_trk, p_star, "Statistical pipeline (NBM + physics-informed EKF + first-passage RUL)")
    rule = rules(fleet, data.TEST)
    extra = []
    if os.environ.get("PDM_FOUNDATION") == "chronos":
        # the foundation model's second opinion, on the same health states and the same decision
        from dataclasses import replace

        from pdm import foundation as FM
        fm = FM.Chronos()
        fm_trk = {key: replace(tr, p_fail=FM.p_fail_series(fm, tr.w, HORIZON)) for key, tr in test_trk.items()}
        extra.append(grade(fleet, data.TEST, fm_trk, p_star, "Chronos-Bolt zero-shot on the health state", with_rul=False))
    det = detection(fleet, data.TEST, test_trk)
    ml = json.load(open(ML_RESULTS))["results"] if os.path.exists(ML_RESULTS) else []
    per_comp = {}
    for k in Mo.COMPS:
        l_all, mi_all, fa_all = [], 0, 0
        for i in data.TEST:
            X, F, _ = fleet[i]
            l, fa, mi = decisions(Mo.alarms(test_trk[(i, k)], p_star), len(X), F, k)
            l_all += l; mi_all += mi; fa_all += fa
        nf = len(l_all) + mi_all
        if nf:
            per_comp[k] = {"failures": nf, "ok": int(sum(1 for x in l_all if x >= CRIT)),
                           "lead_median": float(np.median(l_all)) if l_all else None, "false": fa_all}
    show = showcase(pop, p_star)
    doc = {
        "method": "normal-behaviour model -> physics-informed extended Kalman filter -> first-passage remaining-life distribution "
                  "-> decision P(failure within the horizon) >= p*; CUSUM, BOCPD and Hotelling T^2 on the filter's innovations",
        "fit_machines": data.FIT, "test_machines": data.TEST, "horizon_orders": HORIZON, "lead_needed_orders": CRIT,
        "p_star": p_star, "calibration": calib, "q_scale": pop.q_scale, "d_scale": pop.d_scale,
        "beta_per_degC": {k: round(v, 5) for k, v in pop.beta.items()},
        "noise": {k: round(v, 5) for k, v in pop.noise.items()},
        "results": [rule, ours] + extra + [r for r in ml if r["name"] != rule["name"]],
        "per_component": per_comp, "detectors": det, "showcase": show,
        "seconds": round(time.time() - t0, 1),
    }
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "pdm.json"), "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    for r in doc["results"]:
        print(f"  {r['name'][:62]:62s} warned {r['warned_1shift_pct']:5.1f} %  missed {r['missed']:2d}  late {r['late']:2d}  "
              f"lead {r['lead_median_orders']}  false/1000 {r['false_per_1000']}"
              + (f"  RUL MAE {r['rul_mae_orders']}" if "rul_mae_orders" in r else "")
              + (f"  P10-P90 cover {r['p10_p90_coverage']}" if "p10_p90_coverage" in r else ""))
    print("  detectors:", det)
    for k, v in show.items():
        print(f"  showcase {k}: fails at h {v['fail_h']}, window opens h {v['window_h']} "
              f"(P10/P50/P90 {v['p10_at_window']}/{v['p50_at_window']}/{v['p90_at_window']} orders), U6 rule h {v['rule_h']}, "
              f"CUSUM onset h {v['cusum_onset_h']}")
    print(f"  {doc['seconds']} s")
    return doc


if __name__ == "__main__":
    main()
