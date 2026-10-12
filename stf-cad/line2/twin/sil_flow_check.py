"""
DT-4b gate: the GENERATED station logic (FB_Transfer, FB_QC, FB_DeltaPicker A / B, FB_Lane), compiled with the oven
and the drives, runs the product flow against the plant (twin/sil/line.py) and does what the proven flow model does.

    .venv-twin/bin/python -W ignore twin/sil_flow_check.py        (from stf-cad/line2; ~2 min)

Reference: line_sim.flow("nominal_1h", outcomes="keyed", ideal=True) - the stations alone (logistics unlimited:
DT-4b part 2), every random outcome keyed by its cookie. The plant draws the same keys: the PLC decides, the plant
says what happened.

  F1 event for event   1 h: every row cut (when line_sim deposits it), every load, failed grip, verdict, kick, pick, failed pick and pack of the model happens
                       in the plant, to the same puck / cookie / delta / lane, within one scan (10 ms) - and nothing
                       else; the same cookies fall off the nose
  F2 the PLC's counts  loaded, recirculated, empty pucks, lost, kicked, picks per delta, missed windows = the model's
  F3 physics           nothing the PLC asked was physically impossible (a grip outside the window or the reach, a
                       place into a moving lane, a kick at an empty puck, a closed valve on a held cookie); at the end
                       the PLC's puck table = the pucks; no tracking error, no taken-back booking used by a later pick
  F4 oven              every zone inside the bake window while the line runs
  It can fail          mutants of the generated program (findings 16, 17 and the rules line_sim proves), each rejected
  Not covered (yet)    the nominal hour has no recirculating puck (the model has none either): the I1 path (a full
                       puck passes the transfer) is exercised once delta availability is in (DT-4b part 2); nor
                       does the lane block ever bind (one flavour every 12 s at a delta > T_PICK + T_INDEX)
"""
import collections
import os
import re
import shutil
import sys
import tempfile
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(HERE)
sys.path.insert(0, LINE2)
import line_model as M                                     # noqa: E402
import line_sim as LS                                      # noqa: E402
from twin.sil import build as B                            # noqa: E402
from twin.sil import port as P                             # noqa: E402
from twin.sil.line import SilLine                          # noqa: E402

L = M.L
LIB = os.path.join(HERE, "out", "sil", "libstf2plc.dylib")
T_END = 3600.0
TOL = 0.011                                                # s: one 10 ms scan
WIN = L["BAKE_MARGIN"]
TIMED = ("deposit", "load", "grip_fail", "qc", "kick", "kick_fail", "pick", "pick_fail", "pack")


def reference():
    ev, g = [], LS.flow("nominal_1h", 7, outcomes="keyed", ideal=True)
    while True:
        try:
            ev.append(next(g))
        except StopIteration as e:
            k = e.value
            break
    ids = {}
    for t, kind, d in ev:
        if kind == "deposit":
            for c in d["cookies"]:
                ids[c["id"]] = (d["row"], c["col"])
    return ev, ids, k


def key(kind, d, ids=None):
    """What must be equal: the puck, the cookie, the delta, the lane, the verdict."""
    if kind == "deposit":
        return (kind, d["row"])
    if kind in ("load", "grip_fail"):
        rc = (d["row"], d["col"]) if "row" in d else ids[d["id"]]
        return (kind, d["pk"]) + rc
    if kind == "qc":
        return (kind, d["pk"], d["verdict"])
    if kind in ("kick", "kick_fail"):
        return (kind, d["pk"])
    if kind == "pick":
        return (kind, d["pk"], d["d"], d["lane"] if isinstance(d["lane"], int) else M.FLAV.index(d["lane"]))
    if kind == "pick_fail":
        return (kind, d["pk"], d["d"])
    if kind == "pack":
        return (kind, d["lane"] if isinstance(d["lane"], int) else M.FLAV.index(d["lane"]))


def compare(ref_ev, ids, log):
    """(matched, only in the model, only in the plant) of the timed events with t < T_END."""
    a = sorted((t, key(k, d, ids)) for t, k, d in ref_ev if k in TIMED and t < T_END)
    b = sorted((t, key(k, d)) for t, k, d in log if k in TIMED and t < T_END)
    pool = collections.defaultdict(list)
    for t, kk in b:
        pool[kk].append(t)
    miss, n = [], 0
    for t, kk in a:
        ts = pool.get(kk, [])
        j = next((i for i, x in enumerate(ts) if abs(x - t) <= TOL), None)
        if j is None:
            miss.append((round(t, 3), kk))
        else:
            ts.pop(j)
            n += 1
    extra = sorted((round(t, 3), kk) for kk, ts in pool.items() for t in ts if t < T_END - TOL)
    return n, miss, extra


def run_line(lib=LIB):
    s = SilLine(lib=lib)
    worst = 0.0
    while s.tl(s.ax["axMasterEnc"].pos) < T_END:
        s.step(100)
        worst = max(worst, max(abs(y - t) for y, t in zip(s.y, s.pl.Ts)))
    mon = {n: s.plc.mon(n) for n in s.plc.mon_index if not n.startswith(("fbOven", "fbBand", "fbSafety"))}
    # the PLC's table vs the pucks, apart from pucks in a transition the PLC cannot know yet: a kick not yet
    # confirmed at I1, a grip whose vacuum is still being judged (the job in progress)
    busy = {j["puck"] for d in s.jobs for j in s.jobs[d]}
    diff = [k for k in range(L["N"]) if k not in busy and not mon[f"aPuck[{k}].bKicked"]
            and bool(mon[f"aPuck[{k}].bFull"]) != (s.puck[k] is not None)]
    return dict(log=s.log, errors=s.errors, mon=mon, table_ok=not diff, diff=diff, worst=worst,
                lost=sorted((d["row"], d["col"]) for t, k, d in s.log if k == "band_lost"))


def lost_ref(ref_ev, ids):
    return sorted(ids[d["id"]] for t, k, d in ref_ev if k == "band_lost" and t < T_END)


# ---------------------------------------------------------------------------------------------- mutants
MUTANTS = {
    "N1 the band ratio rounded to 0.001 mm/s (finding 17)": (
        "FB_Band.st", r"RatioNumerator := [0-9.]+,\s*RatioDenominator := \d+\)",
        f"RatioNumerator := {round(M.band_v() * 1000):.1f}, RatioDenominator := {round(L['V'] * 1000)})"),
    "N2 the puck loop taken as N x P (finding 16)": (
        "FB_Arrivals.st", r"\b" + re.escape(f"{M.loop_len():.9f}") + r"\b", f"{L['N'] * L['PITCH']:.9f}"),
    "N3 the kicker fires at the passed cookies": (
        "FB_QC.st", r"aPuck\[pk\]\.nVerdict = 2 THEN", "aPuck[pk].nVerdict = 1 THEN"),
    "N4 a failed pick not taken back (the tray fill)": (
        "FB_DeltaPicker.st", r"aFill\[f\] := aFill\[f\] - 1;", "aFill[f] := aFill[f];"),
    "N5 a tray closed one cookie early": (
        "FB_DeltaPicker.st", r"IF aFill\[f\] >= \d+ THEN", f"IF aFill[f] >= {L['PACK'] - 1} THEN"),
}


def run_mutant(name, ref):
    f, pat, rep = MUTANTS[name]
    work = tempfile.mkdtemp(prefix="stf2fmut_")
    plc = os.path.join(work, "plc")
    shutil.copytree(P.PLC, plc)
    src = open(os.path.join(plc, f)).read()
    new, n = re.subn(pat, rep, src, flags=re.M)
    if n == 0:
        return name, False, "the mutation did not apply"
    open(os.path.join(plc, f), "w").write(new)
    out = os.path.join(work, "sil")
    try:
        B.build(out, plc)
    except SystemExit as e:
        return name, True, f"does not compile: {str(e)[:60]}"
    r = run_line(os.path.join(out, "libstf2plc.dylib"))
    shutil.rmtree(work, ignore_errors=True)
    ref_ev, ids, _ = ref
    n_ok, miss, extra = compare(ref_ev, ids, r["log"])
    caught = bool(miss or extra or r["errors"] or not r["table_ok"])
    return name, caught, (f"{len(miss)} model events missing, {len(extra)} extra, {len(r['errors'])} physics errors"
                          + (f" (first: {r['errors'][0][1]})" if r["errors"] else ""))


def _mut(args):
    return run_mutant(*args)


def check(verbose=True):
    rows, fails = [], []

    def row(name, value, limit, ok, note=""):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"SIL flow {name}: {value} vs {limit} {note}".strip())

    if not os.path.exists(LIB):
        B.build()
    ref = reference()
    ref_ev, ids, k = ref
    with Pool(min(os.cpu_count() or 4, len(MUTANTS) + 1)) as pool:
        main = pool.apply_async(run_line)
        muts = pool.map_async(_mut, [(m, ref) for m in MUTANTS])
        r = main.get()
        muts = muts.get()

    n_ok, miss, extra = compare(ref_ev, ids, r["log"])
    by = collections.Counter(kk[0] for t, kk in
                             [(t, key(kd, d, ids)) for t, kd, d in ref_ev if kd in TIMED and t < T_END])
    lost_a = lost_ref(ref_ev, ids)
    t_last = T_END - 60.0                                    # cookies that fell off before the last minute
    exp = {rc for rc in lost_a if rc[0] * LS_T_ROW() + travel_t() + window_t() < t_last}
    got = {rc for rc in r["lost"] if rc[0] * LS_T_ROW() + travel_t() + window_t() < t_last}
    row("F1 event for event (1 h)", f"{n_ok} of {sum(by.values())} model events in the plant within 10 ms "
        f"({', '.join(f'{kk} {v}' for kk, v in sorted(by.items()))}); {len(miss)} missing, {len(extra)} extra; "
        f"fallen off the nose: {len(got)} = model {len(exp)}", "all; 0; 0; same cookies",
        not miss and not extra and got == exp,
        f"first missing {miss[:2]} extra {extra[:2]}" if miss or extra else "")
    mon = r["mon"]
    pairs = [("loaded", mon["fbTransfer.nLoaded"], k["loaded"]),
             ("recirculated", mon["fbTransfer.nRecirc"], k["recirc"]),
             ("empty pucks", mon["fbTransfer.nEmpty"], k["empty_slots"]),
             ("lost", mon["fbTransfer.nLost"], k["band_lost"]),
             ("picks A", mon["fbPickA.nPicks"], k["picks"][0]), ("picks B", mon["fbPickB.nPicks"], k["picks"][1]),
             ("missed", mon["fbPickB.nMissed"], k["missed_pick_windows"]),
             ("kicked", mon["fbQC.nKicks"], sum(1 for t, kd, d in ref_ev if kd in ("kick", "kick_fail") and t < T_END)),
             ("packs", sum(mon[f"fbLane[{j}].nPacks"] for j in range(3)),
              sum(1 for t, kd, d in ref_ev if kd == "pack" and t < T_END))]
    bad = [f"{n} {int(a)} vs {b}" for n, a, b in pairs if int(a) != b]
    row("F2 the PLC's counts = the model's", ", ".join(f"{n} {int(a)}" for n, a, b in pairs), "all equal", not bad,
        "; ".join(bad))
    trk = int(mon["fbTransfer.nTrackErr"])
    rb = int(mon["fbPickA.nRollback"] + mon["fbPickB.nRollback"])
    row("F3 physics", f"{len(r['errors'])} impossible commands; puck table {'= the pucks' if r['table_ok'] else 'WRONG'}; "
        f"{trk} tracking errors; {rb} taken-back bookings used", "0; =; 0; 0",
        not r["errors"] and r["table_ok"] and trk == 0 and rb == 0, "; ".join(e[1] for e in r["errors"][:2]))
    row("F4 oven", f"worst zone {r['worst']:.2f} K while the line runs", f"<= {WIN:g} K", r["worst"] <= WIN)
    for name, caught, why in muts:
        row(f"mutant {name}", f"{'caught' if caught else 'NOT caught'}: {why}", "caught", caught)
    if verbose:
        for name, val, lim, ok, note in rows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:56s} {val:110s} {lim:18s} {note}")
        print("\n".join(fails) if fails else
              f"ALL SIL FLOW PROOFS PASS (the compiled stations = line_sim event for event for 1 h, the PLC's counts, "
              f"physics, oven, {len(MUTANTS)} mutants caught)")
    return rows, fails


def LS_T_ROW():
    return L["BAND"]["rows"] * M.takt()


def travel_t():
    sb = M.stations()
    return (sb["pick"][0] - sb["dep"]) / M.band_v()


def window_t():
    return L["PICK_W"] / M.band_v()


if __name__ == "__main__":
    sys.exit(1 if check()[1] else 0)
