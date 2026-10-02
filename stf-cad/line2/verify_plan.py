"""
STF-2 verification plan - every number the proofs rest on that is NOT a normative value: the
[assumed] design values in line_model.L, the [assumed] safety constants in hardware.py and safety.py,
and the [typ] catalogue values that feed a proof.

For each numeric one it runs a SENSITIVITY test: the value is moved -20 % and +20 % and the full
model + PLC + safety proofs are re-run. A value whose proofs break inside that band is measured FIRST.

Run: python3 verify_plan.py   -> VERIFICATION_PLAN.md, verification_plan.csv   (~5 min on 10 cores)
"""
import csv
import os
import re
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BAND = 0.20

# how to verify each assumed value (key -> method); keys not listed get the generic method
METHOD = {
    "PITCH": "set on the chain: measure the puck pitch over 10 pucks with a tape",
    "TAKEUP": "measure the drive unit's take-up travel on the delivered unit",
    "PUCK": "measure the moulded puck (D, H) and weigh 10",
    "NEST": "measure the nest D and depth on the puck",
    "COOKIE": "weigh 20 workpieces; D x H from the ft datasheet",
    "PACKING": "fill the reject drawer with cookies, count them",
    "DOUGH_SLUG": "weigh + measure 20 cut slugs at the die", "DOUGH_M": "weigh 20 cut slugs",
    "DOUGH": "lab: water content (oven-dry), conductivity (line-heat probe), cp (DSC); colour index = "
             "Lab colour of baked samples vs bake time at 165 C (fits brown_Ea / brown_t)",
    "TOPPING": "weigh 20 drops; measure the dome", "DEP_HOPPER": "measure the delivered hopper",
    "DOUGH_KG": "fill level vs the ToF reading", "TOP_HOPPER": "measure the delivered hopper", "TOP_KG": "weigh a fill",
    "TOP_F": "pressure trace on the dosing piston with the real jam / chocolate", "DEP_T": "roll motor current at a row cut",
    "BAND": "weigh 1 m of the delivered mesh band (m_area); confirm the pitch on the band",
    "T_AMB": "air thermometer inside the guard next to the oven, running",
    "OVEN_ZONES": "recipe trials: IR1 product temperature + Lab colour at the oven exit",
    "OVEN_H": "heat-flux sensor / lumped copper slug through each zone (h from its heating curve)",
    "COOLING": "copper slug through the hood and along the loop (h from its cooling curve)",
    "T_TRANSFER": "IR1-style spot reading at the pick window", "T_PACK": "probe cookies at the sealer",
    "CHAMBER": "thermography of the skin at steady state; mouth flow with a smoke test",
    "FAN_RUNDOWN": "time the impeller coast-down after KHn drops (tacho / video), 10 stops",
    "AI_LATENCY": "time stamp image capture -> verdict over 1000 images on the edge PC",
    "T_PICK": "delta cycle with the NC trace, 100 picks", "T_GRAB": "vacuum build-up time (IO-Link vac sensor)",
    "PICK_OK": "count grips over a 1000-pick run",
    "DELTA_PAYLOAD": "weigh effector + cup + cookie + half forearms", "DELTA_ARM_M": "weigh an upper arm",
    "DELTA_ACC": "NC trace at the 2 s cycle", "DELTA_VMAX": "NC trace at the 2 s cycle",
    "BOX": "measure the thermoformed tray", "PACK_M": "weigh 10 sealed packs",
    "SEAL_P": "seal trials with the film supplier's window",
    "SHUTTLE_V": "set in the NC; confirm the carrier stroke time",
    "DOOR_T": "time the airlock door strokes (lock OSSD timestamps)",
    "AMR_EXCH": "time the AMR's cassette swap in the chamber over 20 exchanges",
    "F_LOW": "risk assessment decision (ISO/TS 15066 body-region limits) - not a measurement",
    "T_LOGIC": "Beckhoff TwinSAFE reaction-time calculation for the configured watchdogs",
    "OP_YEAR": "production plan", "F_close": "force gauge at the closing edge (ISO 14120, EN 16005 method)",
    "residual": "feeler gauge through the fitted brush strip under a 10 N push",
    "t_mech": "stopping-time measurement (stop-time meter, ISO 13855 Annex) with the contactors dropped",
    "B10d": "manufacturer's B10d for the ordered part number (SISTEMA library)",
    "PL": "manufacturer's certificate for the ordered part number", "PFHd": "manufacturer's certificate",
}


def _l_items():
    """[assumed] entries of line_model.L, parsed from its source (so a new one cannot be forgotten)."""
    import line_model as M
    src = open(os.path.join(HERE, "line_model.py")).read().splitlines()
    out = []
    for no, line in enumerate(src, 1):
        if "[assumed" not in line or line.lstrip().startswith("#") or "=" not in line.split("#")[0]:
            continue
        code, com = line.split("#", 1)
        for key in re.findall(r"(\b[A-Z][A-Z0-9_]+)=", code):
            if key in M.L:
                out.append(dict(key=key, where=f"line_model.L (line {no})", value=M.L[key], note=com.strip(),
                                target=("L", key)))
    return out


def _extra_items():
    import hardware as H
    import safety as S
    out = [dict(key="F_LOW", where="hardware.F_LOW", value=H.F_LOW, note="low-energy threshold (N)",
                target=("H", "F_LOW")),
           dict(key="T_LOGIC", where="hardware.T_LOGIC", value=H.T_LOGIC, note="TwinSAFE reaction (s)",
                target=("H", "T_LOGIC")),
           dict(key="OP_YEAR", where="hardware.OP_YEAR", value=H.OP_YEAR["days"], note="production days / year",
                target=("HD", "OP_YEAR", "days")),
           dict(key="F_close", where="hardware.SAFE['airlock_door']", value=H.SAFE["airlock_door"]["F_close"],
                note="airlock door closing force (N)", target=("HD", "SAFE", "airlock_door", "F_close")),
           dict(key="residual", where="hardware.SAFE['brush']", value=H.SAFE["brush"]["residual"],
                note="opening left by the brush strip (mm)", target=("HD", "SAFE", "brush", "residual"))]
    for k, d in H.RELIAB.items():
        for f in ("B10d", "PL", "PFHd"):
            if f in d:
                out.append(dict(key=f, where=f"hardware.RELIAB['{k}']", value=d[f], note=d["src"],
                                target=("HD", "RELIAB", k, f)))
    for i, h in enumerate(S.HAZARDS):
        if h[3] is not None:
            out.append(dict(key="t_mech", where=f"safety.HAZARDS: {h[0]}", value=h[3],
                            note="run-down after the contactors drop (s)", target=("HZ", i)))
    return out


def _scale(v, f):
    if isinstance(v, float):
        return v * f
    if isinstance(v, tuple) and all(isinstance(x, float) for x in v):
        return tuple(x * f for x in v)
    return None


def _run(args):
    """Apply one perturbation in a fresh process and run every proof; return the first failure."""
    target, factor = args          # every job runs in a FRESH process (maxtasksperchild=1): no leftovers
    import hardware as H
    import line_model as M
    import safety as S
    import plc_io as P
    if target is None:
        pass                                     # the control run: nothing perturbed
    elif target[0] == "L":
        M.L[target[1]] = _scale(M.L[target[1]], factor)
    elif target[0] == "H":
        setattr(H, target[1], getattr(H, target[1]) * factor)
    elif target[0] == "HD":
        d = getattr(H, target[1])
        for k in target[2:-1]:
            d = d[k]
        d[target[-1]] = d[target[-1]] * factor
    elif target[0] == "HZ":
        h = list(S.HAZARDS[target[1]])
        h[3] = h[3] * factor
        S.HAZARDS = S.HAZARDS[:target[1]] + (tuple(h),) + S.HAZARDS[target[1] + 1:]
    try:
        f = M.check(verbose=False)
        if not f:
            f = P.check(verbose=False)
        if not f:
            sf, finds = S.check(verbose=False)
            f = sf + finds
    except Exception as e:                       # a value so far off that a proof cannot even be evaluated
        f = [f"ERROR {type(e).__name__}: {e}"]
    return f[0] if f else ""


def main():
    items = _l_items() + _extra_items()
    jobs = []
    for it in items:
        if _scale(it["value"], 1.0) is not None or isinstance(it["value"], int) and it["key"] in ("B10d", "OP_YEAR"):
            for fac in (1 - BAND, 1 + BAND):
                jobs.append((it["target"], fac))
    jobs = [(None, 1.0)] + jobs
    with Pool(os.cpu_count(), maxtasksperchild=1) as pool:
        res = dict(zip(jobs, pool.map(_run, jobs, chunksize=1)))
    if res[(None, 1.0)]:
        raise SystemExit(f"REFUSING: the unperturbed control run fails ({res[(None, 1.0)]})")
    rows = []
    for it in items:
        lo, hi = res.get((it["target"], 1 - BAND)), res.get((it["target"], 1 + BAND))
        breaks = " / ".join(f"{s}: {r[:110]}" for s, r in (("-20 %", lo), ("+20 %", hi)) if r)
        tested = lo is not None
        safety = it["where"].startswith(("hardware", "safety")) or it["key"] in ("FAN_RUNDOWN", "DOOR_T", "AMR_EXCH")
        prio = 1 if breaks else (2 if safety else 3)
        rows.append(dict(priority=prio, key=it["key"], where=it["where"], value=it["value"],
                         sensitivity=breaks or ("holds at +/-20 %" if tested else "not numeric - verify"),
                         method=METHOD.get(it["key"], "measure on the prototype; re-run the proofs with it"),
                         note=it["note"]))
    rows.sort(key=lambda r: (r["priority"], r["where"]))
    with open(os.path.join(HERE, "verification_plan.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    title = {1: "1 - MEASURE FIRST: a proof breaks within +/-20 %",
             2: "2 - safety-relevant (feeds safety.py)", 3: "3 - the rest"}
    md = ["# STF-2 verification plan (generated by verify_plan.py)", "",
          f"{len(rows)} values the proofs rest on that are assumed or typical. Each numeric one was moved "
          f"-{BAND:.0%} and +{BAND:.0%} and every proof (model, PLC, safety) re-run. Re-run the proofs with the "
          f"measured value; the design is released when they pass with it.", ""]
    for p in (1, 2, 3):
        sub = [r for r in rows if r["priority"] == p]
        md += [f"## {title[p]} ({len(sub)})", "", "| value | where | now | sensitivity | how to verify |",
               "|---|---|---|---|---|"]
        md += [f"| {r['key']} | {r['where']} | {r['value']} | {r['sensitivity']} | {r['method']} |" for r in sub]
        md.append("")
    open(os.path.join(HERE, "VERIFICATION_PLAN.md"), "w").write("\n".join(md))
    n1 = sum(1 for r in rows if r["priority"] == 1)
    print(f"verification plan: {len(rows)} values, {len(jobs) - 1} perturbed proof runs (+1 clean control); "
          f"{n1} break a proof "
          f"within +/-{BAND:.0%} -> VERIFICATION_PLAN.md")
    for r in rows[:n1]:
        print(f"  {r['key']:14s} {r['where']:40s} {r['sensitivity'][:120]}")


if __name__ == "__main__":
    main()
