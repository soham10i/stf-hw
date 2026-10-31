"""
The maintenance decision, with the remaining life's lower bound as its shield.

The plant runs two shifts, 06-22; the night gap 22-06 costs no production. A part whose window has
opened can be renewed tonight for free - if it lasts until tonight - or the cell stops now and loses
the service minutes of production. Renewing too early throws life away; too late, and the part fails
in service (hours down, cookies scrapped). The decision needs exactly what T1 calibrated: a lower
bound L on the remaining life that holds with probability 1 - alpha.

  SHIELD   waiting is allowed only while L >= the orders until the next night gap; otherwise the
           cell stops now. Every "wait" then fails before its gap with probability <= alpha (as far
           as the calibration holds - T2 says when it does not).

Policies, each on every failure stretch of the test machines (a part from new - or from the run's
start - to its failure):
  run to failure      never renews
  U6 rules            the rule monitor's warning -> renew tonight (the month.py work order)
  window -> tonight   the pre-failure window (p*) -> renew tonight, whatever happens before
  window + shield     the window -> renew tonight while the shield allows, stop now when it does not
  shield alone        no window: renew at a gap when L < the orders until the gap after it, stop
                      now when L < the orders until tonight - the guarantee alone decides

Graded by renewal-reward (Barlow & Hunter 1960; Jardine & Tsang 2013): a stretch ends in a planned
renewal or a failure; costs and orders summed over all stretches give the long-run rates - in-service
failures, production hours lost and renewals per 1000 orders, and the life used at renewal. Plus the
shield's own check: of the waits it allowed, the share that failed before their gap.

Costs and service minutes are month.py's (ASSUMED there). Order times are rebuilt from the order
durations (order_time_ratio x the nominal order + changeover; 16 production hours a day); fault
stops are not in the features and not counted, so the gaps come slightly late - the same for every
policy.

    STF_VARIANT=up7 python3 -m pdm.decide       (from stf-cad/hbw; or `make decide`)
"""
import json
import os
import time

import month as M
import numpy as np

from pdm import conformal as K
from pdm import cp, data
from pdm import drift as D
from pdm import model as Mo

DAY_S = 16 * 3600.0                 # production seconds per day (06-22)
I_OT = M.FEATURES.index("order_time_ratio")


def gaps(X):
    """Per order: the index of the first order after the next night gap (len(X) if none)."""
    secs = np.cumsum(X[:, I_OT] * M.T0 + M.CHANGEOVER)
    day = (secs // DAY_S).astype(int)
    nxt = np.full(len(X), len(X))
    for t in range(len(X) - 2, -1, -1):
        nxt[t] = t + 1 if day[t + 1] != day[t] else nxt[t + 1]
    return nxt


def lower_bounds(trk, i, k, q):
    """The calibrated lower bound on remaining life (orders) at every order of machine i, part k
    (per part x predicted life, pdm/conformal.py)."""
    tr = trk[(i, k)]
    c = Mo.COMPS.index(k)
    b = np.digitize(tr.p50, K.LIFE_BINS)
    q1 = np.array([x["q1"] for x in q["comp"][k]["bins"]])[b]
    return np.expm1(np.maximum(cp.log_life(tr.p10) - q1, 0.0))


def stretches(fleet, i, k):
    F = sorted(f for f, kk in fleet[i][1] if kk == k)
    out, start = [], 0
    for f in F:
        out.append((start, f))
        start = f + 1
    return out


def act(policy, s, f, g, lb, win, rule):
    """One stretch [s, f] (f: the failure). Returns (end order, outcome, waits allowed, waits that
    failed before their gap). Outcome: 'gap' (renewed tonight), 'stop' (renewed now), 'fail'."""
    waits = failed_waits = 0
    plan = None                                   # the gap the renewal is planned for
    for t in range(s, f + 1):
        if plan is not None and t >= plan:
            return t, "gap", waits, failed_waits
        if policy == "run to failure":
            continue
        if policy == "U6 rules":
            if plan is None and t in rule:
                plan = g[t]
            continue
        if policy == "window -> tonight":
            if plan is None and win[t]:
                plan = g[t]
            continue
        if policy == "window + shield":
            if win[t] or plan is not None:
                if lb[t] < g[t] - t:
                    return t, "stop", waits, failed_waits
                if plan is None:
                    plan = g[t]
                    waits += 1
                    failed_waits += int(f < plan)
            continue
        if policy == "shield alone":
            if lb[t] < g[t] - t:
                return t, "stop", waits, failed_waits
            nxt = g[g[t]] if g[t] < len(g) else len(g)
            if plan is None and t + 1 == g[t] and lb[t] < nxt - t:      # the last order before a gap
                plan = g[t]
                waits += 1
                failed_waits += int(f < plan)
    return f, "fail", waits, failed_waits


POLICIES = ["run to failure", "U6 rules", "window -> tonight", "window + shield", "shield alone"]
SWEEP = [0.01, 0.05, 0.1, 0.2, 0.3, 0.5]       # the shield's miscoverage level alpha


def cost_alpha(k):
    """The risk-neutral shield level of part k: wait while P(fail before the gap) <= the cost of
    stopping now over the cost of failing (production hours; a scrapped cookie as one order's time),
    i.e. alpha_k = C_stop / C_fail, kept in [0.01, 0.5]."""
    h, sc, _ = M.FAIL.get(k, M.FAIL_DEFAULT)
    fail_h = h + sc * (M.T0 + M.CHANGEOVER) / 9 / 3600
    return float(min(0.5, max(0.01, (M.PM_MIN.get(k, 30) / 60) / fail_h)))


def grade(fleet, trk, q, p_star, policies=POLICIES):
    """q: the calibration (pdm/conformal.fit), or {part: calibration} - a shield level per part."""
    out = {}
    for pol in policies:
        orders = fails = stops = gaps_n = waits = failed_waits = 0
        down_h = scrap = 0.0
        life = []
        for i in sorted(fleet):
            X, F, Rw = fleet[i]
            g = gaps(X)
            for k in Mo.COMPS:
                tr = trk[(i, k)]
                lb = lower_bounds(trk, i, k, q[k] if k in q else q)
                al = set(Mo.alarms(tr, p_star))
                win = np.zeros(len(X), bool)
                if al:
                    win[sorted(al)] = True
                rule = {o for o, kk in Rw if kk == k}
                for s, f in stretches(fleet, i, k):
                    end, how, w, fw = act(pol, s, f, g, lb, win, rule)
                    orders += end - s + 1
                    waits += w
                    failed_waits += fw
                    life.append((end - s + 1) / (f - s + 1))
                    if how == "fail":
                        fails += 1
                        h, sc, _ = M.FAIL.get(k, M.FAIL_DEFAULT)
                        down_h += h
                        scrap += sc
                    elif how == "stop":
                        stops += 1
                        down_h += M.PM_MIN.get(k, 30) / 60
                    else:
                        gaps_n += 1
        per = 1000 / max(1, orders)
        out[pol] = {"failures_per_1000": round(fails * per, 3), "down_h_per_1000": round(down_h * per, 3),
                    "scrap_per_1000": round(scrap * per, 3), "renewals_per_1000": round((fails + stops + gaps_n) * per, 3),
                    "stops_now": stops, "renewed_tonight": gaps_n, "failed_in_service": fails,
                    "life_used_median": round(float(np.median(life)), 3) if life else None,
                    "waits": waits, "waits_failed": failed_waits,
                    "waits_failed_share": round(failed_waits / waits, 4) if waits else None}
    return out


def main():
    t0 = time.time()
    fleets = D.load()
    _, pop, _ = K.population()
    cal_fleet = data.load(K.CAL)
    trk_cal = K.tracks(cal_fleet, pop, K.CAL)
    cal = K.points(cal_fleet, K.CAL, trk_cal)
    q = K.fit(cal)
    q_sweep = {a: K.fit(cal, a) for a in SWEEP}
    alphas = {k: cost_alpha(k) for k in Mo.COMPS}
    q_cost = {k: K.fit(cal, a) for k, a in alphas.items()}
    with open(os.path.join(K.OUT, "conformal.json")) as fh:
        p_star = json.load(fh)["risk_control"]["p_star"]
    doc = {"alpha": K.ALPHA, "p_star": p_star, "policies": POLICIES, "shifts": {}, "say": D.SAY,
           "pm_min": M.PM_MIN, "fail": {k: v[:2] for k, v in M.FAIL.items()}, "cost_alpha": alphas, "sweep": {}}
    for name, fl in fleets.items():
        trk = K.tracks(fl, pop, data.TEST, tag=None if name == "nominal" else f"drift:{name}")
        doc["shifts"][name] = grade(fl, trk, q, p_star)
        doc["shifts"][name]["window + cost-aware shield"] = grade(fl, trk, q_cost, p_star, ["window + shield"])["window + shield"]
        doc["sweep"][name] = {str(a): grade(fl, trk, qa, p_star, ["window + shield"])["window + shield"] for a, qa in q_sweep.items()}
        print(f"{name}")
        for pol, r in doc["shifts"][name].items():  # noqa: B007
            print(f"   {pol:18s} fail/1000 {r['failures_per_1000']:.3f}  down h/1000 {r['down_h_per_1000']:.3f}  "
                  f"renew/1000 {r['renewals_per_1000']:.3f}  life used {r['life_used_median']}  "
                  f"stop/tonight/fail {r['stops_now']}/{r['renewed_tonight']}/{r['failed_in_service']}  "
                  f"waits failed {r['waits_failed']}/{r['waits']}", flush=True)
    print("cost-aware alpha per part:", {k: round(v, 3) for k, v in alphas.items()})
    for a, r in doc["sweep"]["nominal"].items():
        print(f"   nominal shield alpha {a}: fail/1000 {r['failures_per_1000']}  down h/1000 {r['down_h_per_1000']}  "
              f"life used {r['life_used_median']}  waits failed {r['waits_failed']}/{r['waits']}")
    doc["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(K.OUT, "decide.json"), "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print(f"  {doc['seconds']} s")
    return doc


if __name__ == "__main__":
    main()
