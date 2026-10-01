"""
Upgrade 8 - choose the alarm threshold honestly, and count the life thrown away.

    STF_VARIANT=up7 python3 -m ml.tune          (after ml.train)

The first alarm rule (predicted life < 90 orders for 3 orders) was picked by
hand. Here the threshold is TUNED on the labelled training machines only
(validation), then scored once on the untouched test machines.

It also adds the metric the first table was missing: a warning that comes
far too early costs part life - the part is renewed while it still had
hundreds of orders left. "Warned >= 1 shift ahead" alone rewards the earliest
alarm; the maintenance planner wants the latest SAFE one.
"""
import json
import os

import numpy as np
import torch

from ml import train as T
from ml.model import Net

THRESHOLDS = (60, 90, 120, 150, 200, 250)
SHIFT = T.CRIT                                  # one shift, in orders


def decide(alarm_lists, fails_by_run, n_by_run):
    leads, false, missed, orders = [], 0, 0, 0
    for r, per_comp in alarm_lists.items():
        n = n_by_run[r]
        orders += n
        for k, al in per_comp.items():
            l, fa, mi = T.decisions(al, n, fails_by_run[r], k)
            leads += l; false += fa; missed += mi
    lead = np.array(leads) if leads else np.array([0])
    n_fail = len(leads) + missed
    ok = lead >= SHIFT
    wasted = lead[ok] - SHIFT                   # life renewed away beyond the one-shift margin
    return {"failures": n_fail, "warned_1shift": int(ok.sum()), "warned_1shift_pct": round(100 * ok.sum() / max(1, n_fail), 1),
            "missed": missed, "late": int((~ok).sum()) if leads else 0,
            "lead_median_orders": float(np.median(lead)) if leads else None,
            "wasted_life_median_orders": float(np.median(wasted)) if len(wasted) else None,
            "wasted_life_median_shifts": round(float(np.median(wasted)) / SHIFT, 1) if len(wasted) else None,
            "false": false, "false_per_1000": round(1000 * false / max(1, orders), 2)}


def ml_alarms(D, net, runs, thr):
    out = {}
    for r in runs:
        pr, _ = T.predict_run(net, D, r)
        out[r] = {k: alarms(pr[:, c], thr) for c, k in enumerate(T.COMPS)}
    return out


def alarms(pred, thr):
    res, run = [], 0
    for i, v in enumerate(pred):
        run = run + 1 if v < thr else 0
        if run >= T.ALARM_RUN:
            res.append(i)
    return res


def main():
    torch.manual_seed(T.SEED)
    D = T.Data()
    train, test = list(range(T.N_TRAIN)), list(range(T.N_TRAIN, T.N_RUNS))
    val = train[:T.N_LABELED]                   # only the labelled machines may choose anything
    nets = {}
    for nm in ("semi", "sup"):
        n = Net(T.N_IN, 1)
        n.load_state_dict(torch.load(os.path.join(os.path.dirname(__file__), "ckpt", f"{nm}.pt"), map_location="cpu", weights_only=True))
        nets[nm] = n.eval()
    fails = {r: D.F[r] for r in range(T.N_RUNS)}
    nrun = {r: len(D.X[r]) for r in range(T.N_RUNS)}
    rule_rate = T.rule_eval(D, val)["false_per_1000"]
    # cache predictions once per model and run
    preds = {nm: {r: T.predict_run(net, D, r)[0] for r in val + test} for nm, net in nets.items()}
    sweep, chosen = {}, {}
    for nm in nets:
        sweep[nm] = []
        for thr in THRESHOLDS:
            al = {r: {k: alarms(preds[nm][r][:, c], thr) for c, k in enumerate(T.COMPS)} for r in val}
            s = decide(al, fails, nrun)
            sweep[nm].append({"threshold": thr, **s})
        # safety first: warn >= 95 % of failures a shift ahead on validation; among the thresholds that do,
        # the smallest - the latest safe alarm, the least life thrown away
        ok = [s for s in sweep[nm] if s["warned_1shift"] >= 0.95 * s["failures"]]
        chosen[nm] = min(ok, key=lambda s: s["threshold"])["threshold"] if ok else \
            max(sweep[nm], key=lambda s: s["warned_1shift"])["threshold"]
    rules_test = {r: {k: sorted(i for i, kk in D.R[r] if kk == k) for k in T.COMPS} for r in test}
    tbl = [{"name": "U6 rules (EWMA + soft limit + trend)", **decide(rules_test, fails, nrun)}]
    names = {"semi": "semi-supervised (pre-train + Mean Teacher)", "sup": f"supervised-only (same {T.N_LABELED} labelled machines)"}
    for nm in nets:
        al = {r: {k: alarms(preds[nm][r][:, c], chosen[nm]) for c, k in enumerate(T.COMPS)} for r in test}
        tbl.append({"name": f"{names[nm]}, threshold {chosen[nm]} (tuned)", **decide(al, fails, nrun)})
    # hybrid, causal: the rules raise the flag; the part is renewed at the network's first alarm after the
    # flag, or at the latest DEADLINE shifts after the flag - no knowledge of when it actually fails
    DEADLINE = 3 * SHIFT
    hyb = {}
    for r in test:
        hyb[r] = {}
        for c, k in enumerate(T.COMPS):
            rw = sorted(i for i, kk in D.R[r] if kk == k)
            ml = alarms(preds["semi"][r][:, c], chosen["semi"])
            hyb[r][k] = sorted(min(next((i for i in ml if i >= w), w + DEADLINE), w + DEADLINE) for w in rw)
    tbl.append({"name": "hybrid: rules raise the flag, the network sets the date", **decide(hyb, fails, nrun)})
    res_p = os.path.join(T.OUT, "results.json")
    res = json.load(open(res_p))
    res["tuned"] = {"method": "threshold chosen on the labelled training machines only (validation): the smallest that "
                              "warns >= 95 % of failures a shift ahead there; then scored once on the test machines; 'wasted life' = orders of part life renewed away beyond the one-shift margin",
                    "thresholds": list(THRESHOLDS), "sweep_validation": sweep, "chosen": chosen, "rule_false_per_1000_val": rule_rate,
                    "table": tbl,
                    "hybrid_note": "causal: at a rule warning the part is renewed at the network's first alarm after it, "
                                   "or 3 shifts after it at the latest"}
    json.dump(res, open(res_p, "w"), separators=(",", ":"))
    w_p = os.path.join(T.OUT, "weights.json")
    W = json.load(open(w_p))
    W["alarm_rul"] = chosen["semi"]
    json.dump(W, open(w_p, "w"), separators=(",", ":"))
    for s in tbl:
        print({k: s[k] for k in ("name", "warned_1shift", "missed", "late", "lead_median_orders", "wasted_life_median_shifts", "false_per_1000")})
    print("chosen", chosen)


if __name__ == "__main__":
    main()
