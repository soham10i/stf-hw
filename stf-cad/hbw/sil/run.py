"""
Upgrade 13 - software-in-the-loop: the compiled PLC program against the plant.

    STF_VARIANT=up12 python3 -m sil.run          (from stf-cad/hbw; needs Node and the tools of sil/build.py)

  BUILD     sil/iec.py writes the program, MatIEC compiles it, clang makes it
            WebAssembly (sil/build.py). The U4 source is compiled too: it is
            rejected, which is finding F1.
  RUN       Node scans the WebAssembly program against the plant
            (web/src/sil/plant.ts) every 5 ms, from power-up: homing, then the
            whole order, until the program reports it complete.
  PROOFS    (1) every decision the compiled program takes - which jobs start,
                with which binding, after every completion - is the decision
                control.py's proven dispatcher takes from the same state;
            (2) the plant ends as the order requires: every produced cookie in
                its flavour's bay, the returning cookies stored in the rack, 12
                moulds in 12 slots, nothing left on a belt, cup or tray, and the
                colour sensor confirmed every flavour (the program checked it);
            (3) no watchdog tripped and the plant flagged nothing: no crash, no
                drop, no motor driven both ways;
            (4) the order time matches control.simulate() within vc.TOL_MAKESPAN;
            (5) it can fail: three mutants of the program (MUTANTS) are each
                rejected - by a decision, by the colour check, by the RFID read.
Output: web/public/sil/sil.json (the run, its trace and the findings) for the twin.
"""
import json
import os
import subprocess

import control as C
import vc as V

from sil import build, iec, plant

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.expanduser("~/workspace/stf-hw/web")
RUNNER = os.path.join(HERE, "..", ".cache", "sil", "sil-run.mjs")
MAX_S = 3600

FINDINGS = [
    ("F1", "compile", "The U4 program used `Step` as a variable, a reserved word of IEC 61131-3: MatIEC rejected it."),
    ("F2", "compile", "Every positioning step waited for one undeclared `Target[Arg]`; each step needs its own target."),
    ("F3", "logic", "`Done` was set and never cleared, so the orchestrator could not see a unit's second job end."),
    ("F4", "logic", "The orchestrator (MAIN) existed only as comments."),
    ("F5", "logic", "A multi-axis VGR move drove every axis until the step ended: the axes that arrived first overran."),
    ("F6", "compile", "Several step conditions were prose (RF2.tag = record, count(I1) = N_eject, I5 broken)."),
    ("F7", "run", "Homing left the crane's lift at its bottom reference switch; every job starts at transit height."),
    ("F8", "run", "The oven door (single-acting) fell shut on the extended Ofenschieber between U10's present and place."),
    ("F9", "run", "The Drehtisch's 180 degree return had the time of a 90 degree turn: its watchdog tripped."),
    ("F10", "run", "Watchdogs were the same for every binding: the run to the blue ejector (8 s) was watched as 2.4 s."),
]


def old_program_rejected():
    """F1: the U4 source, compiled as it was."""
    src = C.st_source(C.sfc())
    text = "\n\n".join(src[k] for k in src if k != "MAIN.st") + "\n\n" + src["MAIN.st"]
    work = os.path.join(build.WORK, "u4")
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "u4.st"), "w") as f:
        f.write(text)
    r = subprocess.run([os.path.join(build.MATIEC, "iec2c"), "-I", os.path.join(build.MATIEC, "lib"), "u4.st"],
                       cwd=work, capture_output=True, text=True)
    errs = [ln for ln in (r.stdout + r.stderr).splitlines() if "error" in ln]
    return {"accepted": r.returncode == 0, "errors": len(errs), "first": errs[0] if errs else None}


def simulate_node(out):
    subprocess.run(["npx", "esbuild", "scripts/sil-run.ts", "--bundle", "--platform=node", "--format=esm",
                    f"--outfile={RUNNER}", "--log-level=warning"], cwd=WEB, check=True)
    r = subprocess.run(["node", RUNNER, out, str(MAX_S)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


# ------------------------------------------------------------- decoding
_MOULD = {v: k for k, v in iec.MIX.items()}


def decode(job, b):
    """A traced binding (indices) as control.py's job binding (names)."""
    out = []
    for kind, v in zip(iec.LAYOUT[job], b, strict=False):
        if kind == "c":
            out.append(C.CIDS[v - 1] if v else ("next" if job == "present" else None))
        elif kind == "m":
            out.append(_MOULD[v] if v else None)
        elif kind == "slot":
            out.append(C.SLOTS[v - 1])
        elif kind == "bay":
            out.append(C.BAYS[v - 1])
        elif kind == "src":
            out.append("belt" if v == 1 else f"buf_{v - 1}")
    return (job, tuple(out))


def check_decisions(events):
    """(1): replay the program's completions through control.py; its starts must match."""
    pol = C.PLC_POLICY
    s = C.dispatch(C.initial(), pol)
    by_scan = {}
    for e in events:
        by_scan.setdefault(e["scan"], []).append(e)
    fails, n = [], 0
    first = True
    for scan in sorted(by_scan):
        evs = by_scan[scan]
        ends = sorted((e for e in evs if e["kind"] == "end"), key=lambda e: C.UNIT_ORDER.index(e["unit"]))
        starts = {decode(e["job"], e["b"]) for e in evs if e["kind"] == "start"}
        if first:
            want = {(j[0], j[1]) for j in s["run"]}
            first = False
        else:
            before = set(s["run"])
            for e in ends:
                key = decode(e["job"], e["b"])
                job = next((j for j in s["run"] if (j[0], j[1]) == key), None)
                if job is None:
                    fails.append(f"t={e['t']}: the program ended {key}, which control.py is not running")
                    return fails, n
                s = C.dispatch(C.complete(s, job, pol), pol)
            want = {(j[0], j[1]) for j in set(s["run"]) - before}
        n += len(starts)
        if starts != want:
            fails.append(f"t={evs[0]['t']}: the program started {sorted(starts)}, control.py {sorted(want)}")
            return fails, n
    if not C.goal(s):
        fails.append("control.py's replay did not reach the goal")
    return fails, n


def check_plant(fin, cookies):
    """(2): the physical end state."""
    fails = []
    for c in C.PRODUCE:
        i = iec.CIX[c]
        want = C.BAYS.index(C.PL.BIN_OF[C.FLAV[c]])
        where = [b for b, bay in enumerate(fin["bays"]) if i in bay]
        if where != [want]:
            fails.append(f"{c} ({C.FLAV[c]}) is in bay {[C.BAYS[b] for b in where]}, not {C.BAYS[want]}")
        if not fin["baked"].get(str(i)):
            fails.append(f"{c} was never baked")
    stored = {m[1] for m in fin["slots"].values() if m}
    for c in C.RETURN:
        if iec.CIX[c] not in stored:
            fails.append(f"{c} did not go back into the rack")
    moulds = [m for m in fin["slots"].values() if m]
    if len(moulds) != len(C.SLOTS):
        fails.append(f"{len(moulds)} moulds in the rack, not {len(C.SLOTS)}")
    for k in ("belt", "line"):
        if fin[k]:
            fails.append(f"left on the {k}: {fin[k]}")
    for k in ("cup", "tray", "nest", "fork"):
        if fin[k]:
            fails.append(f"left in the {k}: {fin[k]}")
    return fails


def run(verbose=True, write=True):
    out_dir = build.OUT if write else os.path.join(build.WORK, "mutant")    # a mutant never reaches the twin
    meta = build.build(out_dir)
    params = plant.export(out_dir)
    u4 = old_program_rejected()
    tr = simulate_node(out_dir)
    fails = []
    if u4["accepted"]:
        fails.append("the U4 program now compiles: F1 is stale")
    if tr["done_at"] is None:
        fails.append(f"the order did not complete in {MAX_S} s (states {tr['states']})")
    fails += [f"FAULT {f['unit']}: watchdog of state {f['state']} at t={f['t']}" for f in tr["faults"]]
    fails += [f"PLANT {x}" for x in tr["flags"]]
    dec_fails, n_dec = check_decisions(tr["events"])
    fails += dec_fails
    fails += check_plant(tr["final"], params["cookies"])
    _, _, model_t, _ = C.simulate(C.PLC_POLICY)
    plc_t = round(tr["done_at"] - tr["homed_at"], 2) if tr["done_at"] else None
    if plc_t is not None and abs(plc_t - model_t) / model_t > V.TOL_MAKESPAN:
        fails.append(f"order time {plc_t} s against the model's {model_t} s: beyond {V.TOL_MAKESPAN:.0%}")
    out = {
        "variant": "up12", "compiler": meta["compiler"], "wasm_sha": meta["wasm_sha"], "st_lines": meta["st_lines"],
        "scan_ms": meta["scan_ms"], "u4": u4, "findings": [dict(zip(("id", "kind", "text"), f, strict=False)) for f in FINDINGS],
        "homed_at": tr["homed_at"], "done_at": tr["done_at"], "order_s": plc_t, "model_s": model_t,
        "scans": tr["scans"], "wall_ms": tr["wall_ms"], "decisions": n_dec, "jobs": sum(1 for e in tr["events"] if e["kind"] == "end"),
        "events": tr["events"], "plant_log": [{"t": round(e["t"], 2), "text": e["text"]} for e in tr["plant_log"]],
        "final": {"bays": {C.BAYS[i]: [C.CIDS[c - 1] for c in b] for i, b in enumerate(tr["final"]["bays"])},
                  "slots": {s: ([_MOULD[m[0]], C.CIDS[m[1] - 1] if m[1] else None] if m else None)
                            for s, m in tr["final"]["slots"].items()}},
        "checks": {"decisions": not dec_fails, "plant": not check_plant(tr["final"], params["cookies"]),
                   "faults": not tr["faults"] and not tr["flags"], "timing": plc_t is not None
                   and abs(plc_t - model_t) / model_t <= V.TOL_MAKESPAN},
        "fails": fails,
    }
    if write:
        with open(os.path.join(out_dir, "sil.json"), "w") as f:
            json.dump(out, f, indent=1)
    if verbose:
        print(f"U4 program: {'accepted' if u4['accepted'] else 'REJECTED'} by MatIEC ({u4['errors']} errors; {u4['first']})")
        print(f"U13 program: {meta['st_lines']} lines, compiled by {meta['compiler']} -> plc.wasm {meta['wasm_sha']}")
        print(f"run: homed {tr['homed_at']} s, order complete {tr['done_at']} s ({tr['scans']} scans, {tr['wall_ms']} ms wall)")
        print(f"decisions matching control.py: {n_dec}; order {plc_t} s vs model {model_t} s")
        for f in fails:
            print("  FAIL", f)
        print("SIL OK" if not fails else f"SIL FAILED ({len(fails)})")
    return fails


# ---------------------------------------------------------- mutation tests
# Each mutant breaks the program in one way; the proof must reject every one. (A mutant that
# makes the crane store in the farthest free slot instead of the nearest is NOT here: with 12
# moulds and 12 slots there is never more than one free slot to choose, so it is equivalent.)
def _patch_main(old, new):
    def apply():
        f = iec.main_program
        iec.main_program = lambda: f().replace(old, new)
        return lambda: setattr(iec, "main_program", f)
    return apply


def _patch_classify():
    f = iec.CLASSIFY
    iec.CLASSIFY = f.replace("Cls := 3", "Cls := 9").replace("Cls := 2", "Cls := 3").replace("Cls := 9", "Cls := 2")
    return lambda: setattr(iec, "CLASSIFY", f)


def _patch_target():
    f = iec.fb

    def g(u):
        src, st = f(u)
        if u == "crane":
            src = src.replace("TG_RETRIEVE_TRAVEL : ARRAY[1..12, 1..12] OF REAL := [120.0,",
                              "TG_RETRIEVE_TRAVEL : ARRAY[1..12, 1..12] OF REAL := [240.0,")
        return src, st
    iec.fb = g
    return lambda: setattr(iec, "fb", f)


MUTANTS = [
    ("SM1", "the production order's first two cookies swapped in MAIN",
     _patch_main("PROD : ARRAY[1..9] OF INT := [1, 2,", "PROD : ARRAY[1..9] OF INT := [2, 1,")),
    ("SM2", "the colour bands of red and blue swapped", _patch_classify),
    ("SM3", "slot A1's travel target set to the next column", _patch_target),
]


def mutants(verbose=True):
    res = []
    for mid, what, patch in MUTANTS:
        undo = patch()
        try:
            f = run(verbose=False, write=False)
        finally:
            undo()
        res.append({"id": mid, "what": what, "caught": bool(f), "by": f[0] if f else None})
        if verbose:
            print(f"  {mid} {what}: {'caught - ' + f[0][:110] if f else 'SURVIVED'}")
    return res


def check(verbose=True):
    ms = mutants(verbose)
    fails = run(verbose)
    fails += [f"mutant {m['id']} survived: {m['what']}" for m in ms if not m["caught"]]
    path = os.path.join(build.OUT, "sil.json")
    d = json.load(open(path))
    d["mutants"] = ms
    with open(path, "w") as f:
        json.dump(d, f, indent=1)
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if check() else 0)
