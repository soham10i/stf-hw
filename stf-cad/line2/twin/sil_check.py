"""
DT-4a gate: the GENERATED PLC program, compiled by an independent IEC 61131-3 compiler, runs the oven and the
drives against the plant and does what the proven design (oven_ctrl.py) says.

    .venv-twin/bin/python -W ignore twin/sil_check.py        (from stf-cad/line2; ~5 min)

  C1 compiles      plc/*.st -> port.py -> MatIEC: 0 errors, 0 warnings; clang: a native library; the port's rules,
                   left-out units and STUBS listed (the stations without logic yet - DT-4b)
  C2 port only     every ported POU equals the generated one token for token, apart from the documented rules
  C3 PWM           steady state: each element conducts its zone's duty (time-proportioning, 2 s), the elements of a
                   zone in staggered slices (i / n of the period)
  C4 cold start    from 25 C: every zone within +-2 K in <= WARMUP_MAX, overshoot <= BAKE_MARGIN; oven_ctrl S1 for
                   comparison (the model's averaged PWM vs the real 2 s pulses and the 10 ms scan)
  C5 production    from a hot, empty oven: bReady after 60 s stable, the depositor couples, the band fills; FB_Band's
                   zone content = the band's true content at every second; every zone within the bake window
  C6 heater break  each of the 9 elements opens at full production: named correctly (and only it) within 30 s;
                   Z1 rides through inside the window; Z2 / Z3 (no N-1 capacity) hold: the depositor decouples and
                   stops (no row is cut after it), the zone comes back inside the window once the band has emptied
  C7 no nuisance   1 h of production, the transducer error against the proof (reads low): no phase alarm, nothing named
  C8 hot restart   the PLC restarts (power cycle) on a hot running oven: no zone leaves the bake window
  C9 determinism   two runs of 300 s: identical I/O traces
  C10 PLC = model  1 h of production with a dough outage (the hopper runs dry, the AMR refills it 10 min later): the
                   compiled PLC and oven_ctrl.ZoneLoop (the proven loop) on the same true band content agree within
                   C10_TOL at every step; FB_Band (from the rolls + the IOL1 level) = the true content at every second;
                   every zone in the bake window, no hold (finding 15: rows counted from turning rolls on an empty
                   hopper fed forward heat for dough that was not there: 12 K apart, a hold, a -4.4 K restart dip)
  It can fail      eight mutants of the generated program - the findings DT-4a fixed, put back - are each rejected
"""
import hashlib
import json
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
import oven_ctrl as OC                                     # noqa: E402
from twin.sil import build as B                            # noqa: E402
from twin.sil import port as P                             # noqa: E402
from twin.sil.plant import SilPlant                        # noqa: E402

L = M.L
LIB = os.path.join(HERE, "out", "sil", "libstf2plc.dylib")
WIN = L["BAKE_MARGIN"]
C10_TOL = 0.5                                              # K, PLC (10 ms, 2 s PWM) vs ZoneLoop (0.5 s, averaged)
C10_STOCK, C10_REFILL = 2.35, 1500.0                       # kg in the hopper (dry at ~14 min), the refill (s)
TAGS = ["E1T1", "E1T2", "E1T3", "E1B1", "E1B2", "E2T1", "E2B1", "E3T1", "E3B1"]   # FB_Oven's element order


def dev(s):
    return [y - t for y, t in zip(s.y, s.pl.Ts)]


def warm(lib=LIB, seconds=600.0):
    """A hot oven in full production (the band filled), the PLC running since power-up."""
    s = SilPlant(lib=lib)
    s.step(round(seconds / 0.01))
    return s


# ---------------------------------------------------------------------------------------------- the checks
def c3_pwm(lib=LIB):
    s = SilPlant(lib=lib)
    s.step(9000)                                          # 90 s: steady, empty band
    on = {t: [] for t in TAGS}
    duty = [s.plc.mon(f"fbOven.aDuty[{k}]") for k in range(3)]
    for _ in range(200):                                  # one PWM period
        s.step()
        for t in TAGS:
            on[t].append(s.plc[f"qE{t[1:]}"])
    frac = {t: sum(v) / 200 for t, v in on.items()}
    zone = {t: int(t[1]) - 1 for t in TAGS}
    bad = [t for t in TAGS if abs(frac[t] - duty[zone[t]]) > 0.011] + \
        [f"Z{k + 1} duty {duty[k]:.3f}" for k in range(3) if duty[k] < 0.01]    # a steady zone needs SOME power
    starts = {}
    for t in TAGS:                                        # where each element's slice begins in the period
        v = on[t]
        starts[t] = next((i for i in range(200) if v[i] and not v[i - 1]), None)
    stag = []
    for k in range(3):
        es = [t for t in TAGS if zone[t] == k]
        st = sorted(starts[t] for t in es if starts[t] is not None)
        stag.append(len(set(st)) == len(st))
    return frac, duty, bad, all(stag)


def c4_cold(lib=LIB):
    s = SilPlant(T0=[L["T_AMB"]] * 3, lib=lib)
    ys, ready_t = [], None
    for k in range(int(L["WARMUP_MAX"] + 600)):
        s.step(100)
        ys.append((s.t, list(s.y)))
        if ready_t is None and s.plc.mon("fbOven.bReady"):
            ready_t = s.t
            break
    Ts = s.pl.Ts
    inside = [all(abs(y[k] - Ts[k]) <= WIN for k in range(3)) for _, y in ys]
    first = next((i for i in range(len(inside)) if all(inside[i:])), None)
    settle = ys[first][0] if first is not None else float("inf")
    over = max(max(y[k] - Ts[k] for _, y in ys) for k in range(3))
    pl = OC.Plant()
    h = OC.run(pl, OC.tune(pl), 3600.0, lambda t: [0.0] * 3, T0=[L["T_AMB"]] * 3, ramp=True, record=5.0)
    ins = [all(abs(r[k] - pl.Ts[k]) <= 2.0 for k in range(3)) for r in h["y"]]
    f2 = next(i for i in range(len(ins)) if all(ins[i:]))
    return settle, over, ready_t, h["t"][f2], max(max(r[k] for r in h["y"]) - pl.Ts[k] for k in range(3))


def c5_production(lib=LIB):
    s = SilPlant(lib=lib)
    worst, mism, cont_max, t_ready = 0.0, 0, 0.0, None
    for k in range(1500):                                  # 25 min, sampled every second
        s.step(100)
        if t_ready is None and s.plc.mon("fbOven.bReady"):
            t_ready = s.t
        worst = max(worst, max(abs(d) for d in dev(s)))
        plc_c = [s.plc.mon(f"fbBand.aZoneContent[{j}]") for j in range(3)]
        true_c = s.content(s.band_in)                   # at the band position the PLC read
        cont_max = max(cont_max, max(true_c))
        if any(abs(a - b) > 1e-5 for a, b in zip(plc_c, true_c)):      # same rows (the PLC's constant has 6 decimals)
            mism += 1
    return worst, mism, cont_max, t_ready


def c6_break(tag, lib=LIB):
    s = warm(lib)
    k = int(tag[1]) - 1
    cuts0 = len(s.cuts)
    last_cut = s.cuts[-1] if s.cuts else None
    s.broken.add(tag)
    t0, named, others, alarm_t = s.t, None, set(), None
    rows_after_hold, hold_t, stop_v = 0, None, None
    worst_ride, back, cmis = 0.0, None, 0
    for i in range(1200):                                  # 20 min after the break, every second
        s.step(100)
        b = {TAGS[j] for j in range(9) if s.plc.mon(f"fbOven.aBroken[{j}]")}
        if named is None and tag in b:
            named = s.t - t0
        others |= b - {tag}
        if alarm_t is None and any(s.plc.mon(f"fbOven.aPhAlarm[{j}]") for j in range(3)):
            alarm_t = s.t - t0
        if hold_t is None and s.plc.mon("fbOven.bHold"):
            hold_t, last_cut = s.t, (s.cuts[-1] if s.cuts else None)
        if hold_t is not None and s.cuts and last_cut is not None and s.cuts[-1] > last_cut + 1e-9:
            rows_after_hold += 1
            last_cut = s.cuts[-1]
        if hold_t is not None and stop_v is None and s.t - hold_t >= 2.0:
            stop_v = abs(s.ax["axQ41"].vel)
        d = abs(dev(s)[k])
        worst_ride = max(worst_ride, d)
        cmis += any(abs(s.plc.mon(f"fbBand.aZoneContent[{j}]") - c) > 1e-5 for j, c in enumerate(s.content(s.band_in)))
        if back is None and hold_t is not None and d <= WIN and not s.content()[k]:
            back = s.t - t0
    return dict(tag=tag, named=named, others=sorted(others), alarm=alarm_t, hold=hold_t is not None,
                rows_after_hold=rows_after_hold, stop_v=stop_v, worst=worst_ride, back=back, cmis=cmis,
                cuts=len(s.cuts) - cuts0)


def c7_nuisance(lib=LIB):
    s = SilPlant(ct_sign=-1.0, lib=lib)
    alarms, named = 0, 0
    for _ in range(3600):
        s.step(100)
        alarms += any(s.plc.mon(f"fbOven.aPhAlarm[{j}]") for j in range(3))
        named += any(s.plc.mon(f"fbOven.aBroken[{j}]") for j in range(9))
    return alarms, named


def c8_restart(lib=LIB):
    s = warm(lib)
    before = [s.plc.mon(f"fbBand.aZoneContent[{j}]") for j in range(3)]
    learned = [s.plc.mon(f"fbOven.a{v}[{j}]") for v in ("W0", "A1") for j in range(3)]
    s.plc.power_cycle()                                   # off / on: initial values, except the RETAIN variables
    s.step()
    kept = [s.plc.mon(f"fbBand.aZoneContent[{j}]") for j in range(3)] == before and \
        [s.plc.mon(f"fbOven.a{v}[{j}]") for v in ("W0", "A1") for j in range(3)] == learned
    worst, cmis = 0.0, 0
    for _ in range(600):
        s.step(100)
        worst = max(worst, max(abs(d) for d in dev(s)))
        cmis += any(abs(s.plc.mon(f"fbBand.aZoneContent[{j}]") - c) > 1e-5 for j, c in enumerate(s.content(s.band_in)))
    return worst, kept and cmis == 0


def c9_trace(lib=LIB):
    s = SilPlant(lib=lib)
    h = hashlib.sha256()
    outs = sorted(n for n in s.plc.var if n.startswith(("q", "sil_")))
    for _ in range(3000):
        s.step(10)
        h.update(json.dumps([s.plc[n] for n in outs] + [round(v, 9) for v in s.y]).encode())
    return h.hexdigest()


def c10_model(lib=LIB, T=3600.0):
    s = SilPlant(lib=lib, dough=C10_STOCK)
    pl = OC.Plant()
    zl = OC.ZoneLoop(pl, OC.tune(pl))
    n = round(OC.CTRL["DT"] / 0.01)
    worst, mism, hold, dry, wdev = [0.0] * 3, 0, 0, None, 0.0
    while s.t < T:
        if s.t >= C10_REFILL and s.stock < s.row_kg:
            s.refill()
        zl.step(s.content())                               # the model sees the same true content
        s.step(n)
        if dry is None and s.stock < s.row_kg:
            dry = s.t
        worst = [max(w, abs(a - b)) for w, a, b in zip(worst, s.y, zl.y)]
        wdev = max(wdev, max(abs(y - t) for y, t in zip(s.y, pl.Ts)))
        if round(s.t, 6) % 1.0 == 0:
            mism += any(abs(s.plc.mon(f"fbBand.aZoneContent[{j}]") - c) > 1e-5
                        for j, c in enumerate(s.content(s.band_in)))
            hold += bool(s.plc.mon("fbOven.bHold"))
    return worst, mism, hold, dry, wdev


# ---------------------------------------------------------------------------------------------- C2
def _norm(text):
    text = re.sub(r"\(\*.*?\*\)", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text.split()


def c2_identity(src):
    gen_dir = P.PLC
    bad = []
    for f in sorted(os.listdir(gen_dir)):
        if not f.endswith(".st") or f in P.EXCLUDED or f in ("GVL_IO.st", "DUT_PhysicalAI.st"):
            continue
        g = open(os.path.join(gen_dir, f)).read()
        name = re.search(r"^(?:FUNCTION_BLOCK|FUNCTION|PROGRAM)\s+(\w+)", g, re.M).group(1)
        m = re.search(rf"^(?:FUNCTION_BLOCK|FUNCTION|PROGRAM)\s+{name}\b.*?^END_(?:FUNCTION_BLOCK|FUNCTION|PROGRAM)",
                      src, re.M | re.S)
        ported = m.group(0)
        ported = re.sub(r"^VAR_EXTERNAL .*?END_VAR$", "", ported, flags=re.M)          # R2
        ported = re.sub(r"^VAR sil_stub : BOOL; END_VAR.*$|^sil_stub := FALSE;$", "", ported, flags=re.M)   # R12
        ported = re.sub(r"^END_(FUNCTION_BLOCK|FUNCTION|PROGRAM)$", "", ported, flags=re.M)   # R9
        g2 = re.sub(r"\{attribute[^}]*\}", "", g).replace("GVL_IO.", "")                   # R1, R2
        g2 = re.sub(r"\bVAR PERSISTENT\b", "VAR RETAIN", g2)                               # R6
        for mm in re.finditer(r"(\w+)\s*:\s*ARRAY\[(\d+)\.\.(\d+)\]\s+OF\s+(FB_\w+)\s*;", g2):   # R13
            nm, lo, hi, fb = mm.group(1), int(mm.group(2)), int(mm.group(3)), mm.group(4)
            g2 = g2.replace(mm.group(0), ", ".join(f"{nm}_{k}" for k in range(lo, hi + 1)) + f" : {fb};")
        if _norm(ported) != _norm(g2):
            a, b = _norm(ported), _norm(g2)
            i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            bad.append(f"{f}: token {i} {a[i:i + 4]} vs {b[i:i + 4]}")
    return bad


# ---------------------------------------------------------------------------------------------- mutants
MUTANTS = {
    "M1 the task clock never advances (fNow_s)": ("FB_Oven.st", r"^fNow_s := fNow_s \+ 0\.01;[^\n]*$", "", "C3"),
    "M2 no power-up ramp start (aSp from 0)": ("FB_Oven.st", r"^IF NOT bInit THEN.*?^END_IF;\n", "", "C8"),
    "M3 the rolls are never decoupled (MC_GearIn only)": ("FB_Band.st", r"^fbGearOutRolls\([^\n]*\n^fbHaltRolls\([^\n]*$", "",
                                                          "C6"),
    "M4 the original naming logic (re-names, adds the power again)": ("FB_Oven.st", [
        (r"IF NOT aBroken\[m\] THEN (aLost\[aElZone\[m\]\] := aLost\[aElZone\[m\]\] \+ aElW\[m\];) END_IF;", r"\1"),
        (r" AND NOT aBroken\[i\]; END_IF;", "; END_IF;"),
        (r" AND fNow_s - aNamedT\[j\] >= [0-9.]+ THEN", " THEN")], None, "C6"),
    "M5 the band memory is not RETAIN": ("FB_Band.st", r"^VAR RETAIN([^\n]*)$", r"VAR\1", "C8"),
    "M6 rows counted from the command, not the rolls' motion": (
        "FB_Band.st", r"IF ABS\(axRolls\.NcToPlc\.ActVelo\) > 0\.0 AND", "IF bOvenReady AND", "C8"),
    "M7 rows counted from turning rolls on an empty hopper (finding 15)": (
        "FB_Band.st", r" AND fDoughRow >= [0-9.]+ THEN aCut", " THEN aCut", "C10"),
    "M8 the row judged on the level after its slug left": (
        "FB_Band.st", r"^fDoughRow := MAX\(fDoughRow, fDough\);", "fDoughRow := fDough;", "C10"),
}


def run_mutant(name):
    f, pat, rep, test = MUTANTS[name]
    work = tempfile.mkdtemp(prefix="stf2mut_")
    plc = os.path.join(work, "plc")
    shutil.copytree(P.PLC if not os.environ.get("STF_SIL_PLC") else os.environ["STF_SIL_PLC"], plc)
    new = open(os.path.join(plc, f)).read()
    for p_, r_ in (pat if isinstance(pat, list) else [(pat, rep)]):   # every part of the fix is reverted
        new, n = re.subn(p_, r_, new, flags=re.M | re.S)
        if n == 0:
            return name, test, False, f"the mutation did not apply ({p_[:30]})"
    open(os.path.join(plc, f), "w").write(new)
    out = os.path.join(work, "sil")
    try:
        B.build(out, plc)
    except SystemExit as e:
        return name, test, True, f"does not compile: {str(e)[:60]}"
    lib = os.path.join(out, "libstf2plc.dylib")
    if test == "C3":
        frac, duty, bad, stag = c3_pwm(lib)
        caught, why = bool(bad) or not stag, f"{len(bad)} elements off their duty"
    elif test == "C10":
        w, mism, hold, dry, wdev = c10_model(lib)
        caught = max(w) > C10_TOL or mism > 0 or hold > 0 or wdev > WIN
        why = f"PLC vs model {max(w):.2f} K, content wrong {mism} s, hold {hold} s, worst zone {wdev:.2f} K"
    elif test == "C8":
        w, kept = c8_restart(lib)
        caught, why = w > WIN or not kept, f"restart dip {w:.1f} K, memory {'kept' if kept else 'lost or wrong'}"
    else:
        r = c6_break("E2T1", lib)
        caught = r["rows_after_hold"] > 0 or r["back"] is None or (r["stop_v"] or 0) > 1e-6
        why = f"rows cut after the hold {r['rows_after_hold']}, back in window {r['back']}"
    shutil.rmtree(work, ignore_errors=True)
    return name, test, caught, why


def check(verbose=True):
    rows, fails = [], []

    def row(name, value, limit, ok, note=""):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"SIL {name}: {value} vs {limit} {note}".strip())

    meta = B.build()
    row("C1 compiles", f"{meta['st_lines']} lines -> MatIEC 0 errors, {len(meta['warnings'])} warnings -> native lib "
        f"{meta['lib_sha']}; {meta['located']} located", "0 warnings", not meta["warnings"],
        f"stubs: {', '.join(meta['stubs'])}; left out: {', '.join(meta['excluded'])}")
    src = open(os.path.join(HERE, "out", "sil", "stf2_plc.st")).read()
    bad = c2_identity(src)
    row("C2 bodies = generated", f"{len(meta['pous'])} POUs, {len(bad)} differ beyond the port rules", "0", not bad,
        "; ".join(bad[:2]))

    with Pool(min(os.cpu_count() or 4, 12)) as pool:
        jobs = {"c3": pool.apply_async(c3_pwm), "c4": pool.apply_async(c4_cold), "c5": pool.apply_async(c5_production),
                "c7": pool.apply_async(c7_nuisance), "c8": pool.apply_async(c8_restart),
                "c9a": pool.apply_async(c9_trace), "c9b": pool.apply_async(c9_trace),
                "c10": pool.apply_async(c10_model)}
        brk = [pool.apply_async(c6_break, (t,)) for t in TAGS]
        muts = [pool.apply_async(run_mutant, (m,)) for m in MUTANTS]
        res = {k: v.get() for k, v in jobs.items()}
        brk = [b.get() for b in brk]
        muts = [m_.get() for m_ in muts]

    frac, duty, bad3, stag = res["c3"]
    row("C3 PWM = duty, staggered", f"9 elements: on-fraction vs zone duty within 0.011 for {9 - len(bad3)}; slices "
        f"{'staggered' if stag else 'NOT staggered'}", "9; staggered", not bad3 and stag,
        f"duty {[round(d, 3) for d in duty]}")
    settle, over, ready_t, py_settle, py_over = res["c4"]
    row("C4 cold start", f"within +-{WIN:g} K after {settle / 60:.1f} min (oven_ctrl S1 {py_settle / 60:.1f} min), "
        f"overshoot {over:.2f} K (S1 {py_over:.2f} K), ready at {ready_t / 60:.1f} min" if ready_t else
        "never ready", f"<= {L['WARMUP_MAX'] / 60:.0f} min, <= {WIN:g} K", ready_t is not None and
        settle <= L["WARMUP_MAX"] and over <= WIN)
    worst5, mism, cmax, t_ready = res["c5"]
    row("C5 production start", f"ready at {t_ready:.0f} s, band content up to {cmax:.2f}; FB_Band = true content at "
        f"{1500 - mism}/1500 s; worst zone {worst5:.2f} K", f"= at all; <= {WIN:g} K",
        mism == 0 and worst5 <= WIN and cmax >= 0.8)
    for r in brk:
        z = int(r["tag"][1])
        ride = z == 1
        ok = r["named"] is not None and r["named"] <= 30 and not r["others"] and r["cmis"] == 0
        if ride:
            ok = ok and r["worst"] <= WIN and not r["hold"]
            note = f"rides through, worst {r['worst']:.2f} K"
        else:
            ok = ok and r["hold"] and r["rows_after_hold"] == 0 and (r["stop_v"] or 0) <= 1e-9 and r["back"] is not None
            note = (f"hold: depositor stopped, {r['rows_after_hold']} rows cut after it, back in the window "
                    f"{r['back'] / 60:.1f} min after the break" if r["back"] else "NEVER back in the window")
        row(f"C6 heater break {r['tag']}", f"named after {r['named']:.1f} s" if r["named"] is not None else "NOT named",
            "<= 30 s, only it", ok, note + (f"; also named {r['others']}" if r["others"] else "") +
            (f"; FB_Band content wrong for {r['cmis']} s" if r["cmis"] else ""))
    alarms, named = res["c7"]
    row("C7 no nuisance (1 h)", f"{alarms} s with a phase alarm, {named} s with an element named", "0, 0",
        alarms == 0 and named == 0, "transducer error against the proof (reads low)")
    w8, kept = res["c8"]
    row("C8 hot restart", f"power cycle on a hot running oven: band rows + learned feed-forward "
        f"{'kept (RETAIN)' if kept else 'LOST'}; worst zone {w8:.2f} K", f"kept; <= {WIN:g} K", kept and w8 <= WIN)
    row("C9 determinism", f"300 s of outputs + TCs: {'identical' if res['c9a'] == res['c9b'] else 'DIFFERENT'}",
        "identical", res["c9a"] == res["c9b"], res["c9a"][:12])
    w10, mism10, hold10, dry10, wdev10 = res["c10"]
    row("C10 PLC = model, dough outage", f"1 h, hopper dry at {dry10 / 60:.1f} min, refilled at {C10_REFILL / 60:.0f} "
        f"min: |PLC - ZoneLoop| {max(w10):.2f} K (zones {', '.join(f'{x:.2f}' for x in w10)}); FB_Band = true content "
        f"at {3600 - mism10}/3600 s; worst zone {wdev10:.2f} K; hold {hold10} s" if dry10 else "the hopper never ran dry",
        f"<= {C10_TOL:g} K; all; <= {WIN:g} K; 0", dry10 is not None and max(w10) <= C10_TOL and mism10 == 0 and
        wdev10 <= WIN and hold10 == 0)
    for name, test, caught, why in muts:
        row(f"mutant {name}", f"{'caught by ' + test if caught else 'NOT caught'}: {why}", "caught", caught)

    if verbose:
        for name, val, lim, ok, note in rows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:52s} {val:90s} {lim:22s} {note}")
        print("\n".join(fails) if fails else "ALL SIL PROOFS PASS (compiles, port only, PWM, cold start, production, "
                                             "heater break x9, no nuisance, hot restart, determinism, PLC = model "
                                             "through a dough outage, 8 mutants caught)")
    return rows, fails


if __name__ == "__main__":
    sys.exit(1 if check()[1] else 0)
