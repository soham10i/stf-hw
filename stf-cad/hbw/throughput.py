"""
Upgrade 10 - throughput (STF_VARIANT=up10).

Upgrade 5 commissioned the 12-cookie order at 636 s with the VGR arm as the
busiest unit, yet no unit was busy even half the time (OEE 27 %). Nothing was
saturated: the order was limited by a CHAIN, not by a machine. This module
finds that chain, and measures four changes to the program and the paths:

  zero    a waypoint with nothing to move is one position check (50 ms), not
          the 0.4 s minimum of a relay-switched move
  blend   the VGR crosses between stations at the lowest height the SAT sweep
          proves clear (+ 20 mm), and swings while it climbs (vgr_path.blend)
  split   the VGR job is cut where the cookie has left the mould: the belt and
          the mould go back at once; the oven presents its tray while the arm
          picks; the arm may hold the next cookie while the tray is still busy
  dual    dual-command crane: the mould coming in is stored in the free slot
          nearest the next cookie, which is retrieved on the same trip

Every measure is proven before it is measured: the explorer covers every
completion order of the new jobs (no deadlock, 12 + 12 conserved), check_tours
sweeps every blended path, and virtual commissioning runs the fault matrix and
the recovery-path proof on the new program. The ablation switches each measure
off alone, in the same process, on the same plant model.

    STF_VARIANT=up10 python3 throughput.py      -> web/public/throughput/
"""
import json
import os
import statistics
import time

import control as C
import vc
from variant import UP10

OUT = os.path.expanduser("~/workspace/stf-hw/web/public/throughput")
MEASURES = ("zero", "blend", "split", "dual")
SAY = {"zero": "zero-length legs cost a position check",
       "blend": "blended VGR crossings at the lowest proven height",
       "split": "VGR job split at the pick; oven presents in parallel",
       "dual": "dual-command crane (store + retrieve in one trip)"}


def _set(on):
    for m in MEASURES:
        C.OPT[m] = m in on


def _run(on):
    _set(on)
    bars, events, T, _ = C.simulate(C.PLC_POLICY)
    r = vc.Run(C.PLC_POLICY).run()
    busy = {u: round(sum(s[3] - s[2] for b in r.bars for s in b["steps"] if s[0] == u), 1) for u in C.UNITS}
    sorts = sorted(b["t1"] for b in r.bars if b["job"] == "sort")
    gaps = [b - a for a, b in zip(sorts, sorts[1:])]
    return {"on": sorted(on), "model_s": T, "vc_s": round(r.makespan, 1), "busy": busy,
            "cycle_s": round(statistics.median(gaps), 1) if gaps else None,
            "per_hour": round(len(C.PRODUCE) * 3600 / r.makespan, 1)}, bars, r


def critical_path(bars):
    """Walk back from the last job: each job was started by the completion that
    freed it (dispatch runs on completions only). Returns the chain and the
    time on it per job type."""
    ends = {}
    for b in bars:
        ends.setdefault(round(b["t1"], 2), []).append(b)
    cur = max(bars, key=lambda b: b["t1"])
    chain = [cur]
    while cur["t0"] > 1e-9:
        cand = ends.get(round(cur["t0"], 2), [])
        if not cand:
            break
        # the enabling job: prefer one that shares a unit, then one on the same mould/cookie
        share = [b for b in cand if set(b["units"]) & set(cur["units"])]
        same = [b for b in cand if set(b["bind"]) & set(cur["bind"])]
        cur = (share or same or cand)[0]
        chain.append(cur)
    chain.reverse()
    by = {}
    for b in chain:
        by[b["job"]] = round(by.get(b["job"], 0.0) + b["t1"] - b["t0"], 1)
    return [{"job": b["job"], "t0": b["t0"], "t1": b["t1"]} for b in chain], dict(sorted(by.items(), key=lambda x: -x[1]))


def study(on):
    rows = []
    try:
        for bake in C.STUDY_BAKES:
            C.BAKE["s"] = bake
            _set(())
            before = C.simulate(C.PLC_POLICY)[2]
            _set(on)
            after = C.simulate(C.PLC_POLICY)[2]
            rows.append({"bake_s": bake, "before": before, "after": after, "gain": round(1 - after / before, 3)})
    finally:
        C.BAKE["s"] = C.BAKE_DEMO
    return rows


def _gantt(r):
    return [{"job": b["job"], "bind": b["bind"], "units": b["units"], "t0": b["t0"], "t1": b["t1"],
             "steps": [[s[0], round(s[2], 2), round(s[3], 2)] for s in b["steps"]]} for b in r.bars]


def main():
    assert UP10, "run with STF_VARIANT=up10"
    t0 = time.time()
    full = set(MEASURES)
    # --- proofs first: nothing is written unless all pass
    _set(full)
    fails = C.check(verbose=False)
    fails += vc.check(verbose=False)
    if fails:
        print("\n".join(fails[:20]))
        raise SystemExit("throughput: proofs failed - nothing written")
    explored = {p: C.explore(p)[0] for p in C.POLICIES if not (C.POLICIES[p]["buffer"] and not C.NEST_N)}
    healthy, rows = vc.results()
    perf = vc.performance(healthy, rows)
    # --- ablation
    configs = [("before (Upgrade 7)", ())] + [(f"only {m}", (m,)) for m in MEASURES] + \
              [(f"all but {m}", tuple(x for x in MEASURES if x != m)) for m in MEASURES] + [("Upgrade 10", MEASURES)]
    abl, keep = [], {}
    for name, on in configs:
        row, bars, r = _run(set(on))
        abl.append({"name": name, **row})
        if name in ("before (Upgrade 7)", "Upgrade 10"):
            keep[name] = (bars, r)
        print(f"  {name:22s} model {row['model_s']:6.1f} s  VC {row['vc_s']:6.1f} s  cycle {row['cycle_s']} s")
    base, up = abl[0], abl[-1]
    marg = {m: round(next(a for a in abl if a["name"] == f"all but {m}")["vc_s"] - up["vc_s"], 1) for m in MEASURES}
    alone = {m: round(base["vc_s"] - next(a for a in abl if a["name"] == f"only {m}")["vc_s"], 1) for m in MEASURES}
    cp_before = critical_path(keep["before (Upgrade 7)"][0])
    cp_after = critical_path(keep["Upgrade 10"][0])
    _set(full)
    st = study(full)
    # the VGR arm: time per tour before and after
    tours = {}
    for nm, on in (("before", ()), ("after", full)):
        _set(on)
        tours[nm] = {"belt_to_oven": round(sum(s.t for s in C.job_steps(("belt_to_oven", ("c", "M")))) +
                                           (sum(s.t for s in C.job_steps(("place_oven", ("c", "belt")))) if "split" in on else 0), 2),
                     "bay_to_belt": round(sum(s.t for s in C.job_steps(("bay_to_belt", ("c", "rot", "M")))), 2)}
    _set(full)
    # OEE before, on the same shift definition (the order + every fault once)
    _set(())
    hb = vc.Run(C.PLC_POLICY).run()
    perf_b = vc.performance(hb, vc.run_matrix(hb))
    _set(full)
    bott_b = max(base["busy"], key=base["busy"].get)
    bott_a = max(up["busy"], key=up["busy"].get)
    findings = [
        {"title": f"The order is {round(100 * (1 - up['vc_s'] / base['vc_s']))} % shorter: {base['vc_s']} s -> {up['vc_s']} s",
         "text": f"Commissioned against the plant model, not only the nominal schedule ({base['model_s']} -> {up['model_s']} s "
                 f"nominal). {base['per_hour']} -> {up['per_hour']} cookies an hour; one cookie every {base['cycle_s']} s -> "
                 f"{up['cycle_s']} s in steady state."},
        {"title": "No machine was the bottleneck - a loop was",
         "text": f"Before, the busiest unit ({bott_b}, {base['busy'][bott_b]} s) was idle {round(100 * (1 - base['busy'][bott_b] / base['vc_s']))} % "
                 f"of the order. The critical path ran round the mould loop - crane, belt, VGR pick, belt back, crane - because one "
                 f"mould shuttles the belt and the VGR held it for its whole tour to the oven. The largest share of the path: "
                 + ", ".join(f"{k} {v} s" for k, v in list(cp_before[1].items())[:3]) + "."},
        {"title": f"What each measure is worth (removed from the full set): " + ", ".join(f"{m} {marg[m]} s" for m in MEASURES),
         "text": "Alone against the old program: " + ", ".join(f"{m} {alone[m]} s" for m in MEASURES) +
                 f". {max(marg, key=marg.get)} is worth most. The sum of the parts alone ({round(sum(alone.values()), 1)} s) "
                 f"differs from the whole ({round(base['vc_s'] - up['vc_s'], 1)} s) because they share the loop. "
                 + ("'zero' only corrects the nominal schedule: the commissioned plant never waited on a leg that moves "
                    "nothing, so it is worth nothing there. " if abs(marg["zero"]) < 0.5 and abs(alone["zero"]) < 0.5 else "")},
        {"title": f"The bottleneck moved to the {bott_a}",
         "text": f"After: {bott_a} busy {up['busy'][bott_a]} s of {up['vc_s']} s ({round(100 * up['busy'][bott_a] / up['vc_s'])} %). "
                 "The critical path is now: " + ", ".join(f"{k} {v} s" for k, v in list(cp_after[1].items())[:3]) +
                 ". The next step is on the warehouse side (a second fork, or retrieving to a staging position), not the VGR."},
        {"title": f"With a real bake the gain shrinks to {round(100 * st[-1]['gain'])} %",
         "text": f"At the booklet's {C.BAKE_DEMO:.0f} s demo bake the loop limits the order; at {st[-1]['bake_s']:.0f} s the oven does "
                 f"({st[-1]['before']} -> {st[-1]['after']} s). The split still helps there: the VGR waits holding the next cookie, "
                 "so the tray is refilled the moment it frees."},
        {"title": "Safety and recovery are unchanged",
         "text": f"Every fault of the matrix is still caught by the expected alarm and recovered ({sum(r['pass'] for r in rows)}/{len(rows)}); "
                 f"from every waypoint of the blended tours the arm can still plunge straight up ({vc.check_recovery_paths()[1]} poses). "
                 "One new rule: a cookie dropped after the pick has no mould to go back to, so the operator lays it on the presented tray."},
    ]
    doc = {
        "meta": {"variant": "up10", "policy": C.PLC_POLICY, "cookies": len(C.PRODUCE), "orders_note":
                 "the 12-cookie order: 9 produced, 3 returned to the rack", "bake_demo_s": C.BAKE_DEMO,
                 "margin_mm": __import__("vgr_path").MARGIN, "t_zero_s": C.T_ZERO, "t_min_s": C.T_MIN,
                 "assumed": "as Upgrades 4 and 5: axis speeds and ramps, belt slip, cylinder, vacuum and RFID times, "
                            "the operator's repair and reset times"},
        "measures": [{"id": m, "say": SAY[m], "alone_s": alone[m], "marginal_s": marg[m]} for m in MEASURES],
        "ablation": abl,
        "critical_path": {"before": {"chain": cp_before[0], "by_job": cp_before[1]},
                          "after": {"chain": cp_after[0], "by_job": cp_after[1]}},
        "tours": tours,
        "study": st,
        "proofs": {"explored_states": explored, "fault_matrix": [{k: r[k] for k in ("id", "fault", "expected", "observed",
                                                                                    "latency_s", "lost_s", "pass")} for r in rows],
                   "recovery_poses": vc.check_recovery_paths()[1], "vc_vs_model": round(healthy.makespan / C.simulate(C.PLC_POLICY)[2] - 1, 4)},
        "oee": {nm: {k: p[k] for k in ("availability", "performance", "quality", "oee", "bottleneck", "makespan", "shift_s")}
                for nm, p in (("before", perf_b), ("after", perf))},
        "gantt": {"before": _gantt(keep["before (Upgrade 7)"][1]), "after": _gantt(keep["Upgrade 10"][1])},
        "main_st": C.st_source(C.sfc())["MAIN.st"],
        "findings": findings,
    }
    _set(full)
    os.makedirs(OUT, exist_ok=True)
    json.dump(doc, open(os.path.join(OUT, "throughput.json"), "w"), separators=(",", ":"))
    print(f"wrote {OUT}/throughput.json in {time.time() - t0:.0f} s")
    for f in findings:
        print(" -", f["title"])


if __name__ == "__main__":
    main()
