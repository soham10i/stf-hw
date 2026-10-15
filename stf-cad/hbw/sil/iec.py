"""
Upgrade 13 - the PLC program as one complete IEC 61131-3 project (STF_VARIANT=up12).

Upgrade 4 (control.st_source) wrote the unit sequencers as text, and the
orchestrator only as comments. Fed to an IEC compiler (MatIEC) it does not
compile, and as written it could not have run:
  F1  the step variable is called `Step`, a reserved word of IEC 61131-3;
  F2  every positioning step waits for `AxisAt(Pos, Target[Arg])` - one target
      per job, never declared - while each step needs its own target;
  F3  `Done` is set and never cleared, so the orchestrator could not see the
      second job of a unit finish;
  F4  the orchestrator (MAIN) was the priority list as comments;
  F5  a multi-axis VGR move drives each axis until the step ends, so the
      axes that arrive first overrun their target;
  F6  the conditions `I3 AND RF1.valid`, `RF2.tag = record`, `count(I1) =
      N_eject`, `class = record flavour` and `I5 broken` are prose.
Running the compiled program against the plant (sil/run.py) found more, fixed here:
  F7  homing left the lift on its bottom reference switch; every crane job
      starts from transit height (HOMING_EXTRA);
  F8  the door (single-acting Q13) fell shut on the extended Ofenschieber
      between Upgrade 10's `present` and `place_oven`: it is now held open
      whenever the Ofenschieber is not inside;
  F9  the Drehtisch's 180 degree turn back (OVEN_CYCLE row 21) had the time
      of a 90 degree turn, so its watchdog tripped: turn times now follow
      from the angle (step_time);
  F10 a step's watchdog was the same for every binding, taken from the first:
      the sorting line's run to the blue ejector (8 s) was watched as if it
      went to the white one (2.4 s), and so was every crane leg to a far slot.
      Watchdogs that differ by binding are now tables (WD_<job>).
This module writes the program again from the same models, completely:

  UNITS     one FUNCTION_BLOCK per unit (control.UNITS), its steps those of
            control.job_steps(). Positioning is per axis: an axis is driven
            toward its own target and stops half a scan's travel before it
            (the brake lead of vc.py), so a three-axis VGR move ends with each
            axis inside its tolerance. Targets are constant tables, one row
            per binding (slot, bay, slot pair), taken from the same models.
            Done is a one-scan pulse; a job is taken from Cmd when READY.
  MAIN      the orchestrator of control.py translated statement for
            statement: the factory state (slots, moulds, belt ends, oven,
            bays, cookie stages, reservations), the completion effects of
            control.complete() and the dispatch loop of control.dispatch()
            in the same priority order. Production starts once every unit
            has homed.
  I/O       located variables: %IX inputs, %QX outputs, %IW the RFID tags and
            the colour sensor, %ID the encoder positions, %MW a monitor of
            every unit (state, job, binding) for the trace.
Only the Upgrade 12 program is generated (split oven loading, dual-command
crane, the "reuse" policy): the machine the twin shows.
"""
import math
import re

import control as C
import vc as V

SCAN_MS = 5                        # one task: the VGR's commissioned scan (vc.TASK)
UNIT_IX = {u: i + 1 for i, u in enumerate(C.UNIT_ORDER)}
MODULE = {u: C.UNITS[u][0] for u in C.UNIT_ORDER}

# unit -> axis -> (FB input, output that drives it negative, output that drives it positive, speed)
AXES = {
    "crane": {"travel": ("PosTravel", "Q3", "Q4", C.V_HBW), "lift": ("PosLift", "Q5", "Q6", C.V_HBW)},
    "arm": {"plunge": ("PosPlunge", "Q2", "Q1", C.V_MM), "reach": ("PosReach", "Q3", "Q4", C.V_MM),
            "swivel": ("PosSwivel", "Q6", "Q5", C.V_DEG)},
}
ENCODER = [("crane", "travel"), ("crane", "lift"), ("arm", "plunge"), ("arm", "reach"), ("arm", "swivel")]
_R_MAX = __import__("vgr_model").cup_radius(__import__("vgr_model").V["REACH"][1])
# the tolerance every positioning step must stop inside: the crane's as written in the
# program (control.TOL_MM), the VGR's from the geometry (vc.TOLERANCE: the cup on the cookie)
TOL = {"travel": C.TOL_MM, "lift": C.TOL_MM, "plunge": V.TOLERANCE["plunge"][0],
       "reach": V.TOLERANCE["reach"][0], "swivel": math.degrees(V.TOLERANCE["swivel"][0] / _R_MAX)}


def lead(unit, axis):
    """Switch off half a scan's travel before the target: the error left is +-v*scan/2."""
    return AXES[unit][axis][3] * SCAN_MS / 1000 / 2


# ------------------------------------------------------------ jobs
# MAIN's job codes, in the priority order of control._candidates (U12: split + dual, "reuse")
JOBS = ["sort", "ovenbelt", "saw_eject", "to_tt", "bake", "present", "place_oven", "belt_to_oven",
        "bay_to_belt", "belt_back", "store_retrieve", "belt_fwd", "store", "fetch_empty", "retrieve"]
JOB_IX = {j: i + 1 for i, j in enumerate(JOBS)}
# the units each job reserves (control._candidates), lead first
RESERVE = {"sort": ("line",), "ovenbelt": ("ovenbelt",), "saw_eject": ("turntable",),
           "to_tt": ("sauger", "door"), "bake": ("door",), "present": ("door",),
           "place_oven": ("arm", "door"), "belt_to_oven": ("arm", "belt"), "bay_to_belt": ("arm", "belt"),
           "belt_back": ("belt",), "store_retrieve": ("crane", "belt"), "belt_fwd": ("belt",),
           "store": ("crane", "belt"), "fetch_empty": ("crane", "belt"), "retrieve": ("crane", "belt")}
SLOTS = C.SLOTS
NS = len(SLOTS)
BAYS = list(C.BAYS)


def bindings(job):
    """Every binding the program can be given, as (FB argument, a control.py job tuple)."""
    c, m = "c00", "M01"
    if job in ("retrieve",):
        return [(i + 1, (job, (c, m, s))) for i, s in enumerate(SLOTS)]
    if job == "fetch_empty":
        return [(i + 1, (job, (m, s))) for i, s in enumerate(SLOTS)]
    if job == "store":
        return [(i + 1, (job, (m, c, s))) for i, s in enumerate(SLOTS)]
    if job == "store_retrieve":
        return [(i * NS + j + 1, (job, (m, c, a, "c01", "M02", b)))
                for i, a in enumerate(SLOTS) for j, b in enumerate(SLOTS) if a != b]
    if job in ("belt_fwd", "belt_back"):
        return [(1, (job, (m, c)))]
    if job == "belt_to_oven":
        return [(1, (job, (c, m)))]
    if job == "place_oven":
        return [(1, (job, (c, "belt")))]
    if job == "bay_to_belt":
        return [(k + 1, (job, (c, b, m))) for k, b in enumerate(BAYS)]
    if job == "sort":
        return [(k + 1, (job, (c, b))) for k, b in enumerate(BAYS)]
    return [(1, (job, (c,)))]


def segments(job):
    """The units that run steps for a job, in order, with the steps of each."""
    steps = C.job_steps(bindings(job)[0][1])
    order = list(dict.fromkeys(st.unit for st in steps))
    return [(u, [st for st in steps if st.unit == u]) for u in order]


def unit_jobs(u):
    return [j for j in JOBS if any(su == u for su, _ in segments(j))]


# ------------------------------------------------------------ helpers
def r(x):
    s = f"{x:.3f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def ms(t):
    return f"T#{int(round(t * 1000))}MS"


HOMING_EXTRA = {
    # F7 (found by this upgrade's run): homing ends with the lift on its reference
    # switch at the BOTTOM, but every crane job starts from transit height.
    "crane": [C.Step("crane", "H:transit", "lift to transit height (the pose every job starts from)", ("Q6",),
                     f"|pos_lift - {C.TR:.0f}| <= 1 (B3/B4)", C.TR / C.V_HBW, True, ("B3", "B4"),
                     {"lift": C.TR}, dist={"lift": C.TR})],
}


# F9 (found by this upgrade's run): motion.OVEN_CYCLE gives the Drehtisch 1.5 s for each of
# its three turns, but row 21 turns 180 degrees, twice rows 16 and 18. At the speed those two
# rows give (90 deg in 1.5 s) it needs 3.0 s, and its watchdog (2.75 s) tripped. The step times
# of the turns come from their angle instead.
_TURN = {16: ("sauger", "saege"), 18: ("saege", "band"), 21: ("band", "sauger")}


def step_time(st):
    if st.unit == "turntable" and st.key.startswith("row") and int(st.key[3:]) in _TURN:
        stops = {"sauger": 0.0, "saege": -90.0, "band": -180.0}
        a, b = _TURN[int(st.key[3:])]
        return abs(stops[a] - stops[b]) / (90.0 / C.MO.OVEN_CYCLE[16][0])
    return st.t


def step_limit(st):
    if st.limit is None:
        return None
    return C.timeout(step_time(st)) if step_time(st) != st.t else st.limit


def homing(u):
    return list(C.HOMING[u]) + HOMING_EXTRA.get(u, [])


# ------------------------------------------------------------ unit FBs
def _cond(u, st, k_tbl, job):
    """The step's completion as ST."""
    d = st.done
    if st.target and u in AXES:
        ax = [a for a in AXES[u] if a in st.target]
        if job is None:                       # homing: a constant target
            return " AND ".join(f"ABS({AXES[u][a][0]} - {r(st.target[a])}) <= {r(TOL[a])}" for a in ax)
        return " AND ".join(f"ABS({AXES[u][a][0]} - TG_{job.upper()}_{a.upper()}[B1, {k_tbl}]) <= {r(TOL[a])}"
                            for a in ax)
    if d == "timer":
        return f"Tm.ET >= {ms(st.t)}"
    if d == "I3 AND RF1.valid" or d == "I2 AND RF1.valid":
        return f"{d.split()[0]} AND RfSeen"
    if d.startswith("RF2.valid"):
        return "RF2_Valid AND RF2_Tag = Tag"
    if d.startswith("record ="):
        return "(I2 = ExpI2) AND (I3 = ExpI3)"
    if d.startswith("class ="):
        return "Cls = B1"
    if d.startswith("count(I1)"):
        return "Pulses >= NEJECT[B1]"
    if "broken" in d:
        return "Bar"
    assert d.replace("NOT ", "").startswith("I") and " " not in d.replace("NOT ", ""), d
    return d


def fb(u):
    m, outs, label = C.UNITS[u]
    hs = homing(u)
    jobs = unit_jobs(u)
    segs = {j: dict(segments(j))[u] for j in jobs}
    # the steps every binding gives must share their structure; only targets (and the
    # sorting line's ejector) differ
    tables, limits = {}, {}
    for j in jobs:
        rows = bindings(j)
        per = [dict(segments_of(b))[u] for _, b in rows]
        n = len(per[0])
        assert all(len(p) == n for p in per), f"{j}: bindings differ in step count"
        for k in range(n):
            if j != "sort":
                assert all(p[k].done.split("|")[0] == per[0][k].done.split("|")[0] for p in per), (j, k)
        size = max(a for a, _ in rows)
        lims = [[None] * n for _ in range(size)]
        for (ix, _), p in zip(rows, per, strict=True):
            for k, st in enumerate(p):
                lims[ix - 1][k] = step_limit(st)
        for k in range(n):                     # rows no binding uses (a slot pair a == b): the longest
            col = [x[k] for x in lims if x[k] is not None]
            for x in lims:
                if x[k] is None and col:
                    x[k] = max(col)
        limits[j] = lims
        if u in AXES:
            for a in AXES[u]:
                vals = [[0.0] * n for _ in range(size)]
                for (ix, _), p in zip(rows, per, strict=True):
                    for k, st in enumerate(p):
                        if a in st.target:
                            vals[ix - 1][k] = st.target[a]
                tables[(j, a)] = (size, n, vals)
    sigs = set()
    for st in hs + [st for j in jobs for st in segs[j]]:
        for x in st.sig:
            if x[0] == "I":
                sigs.add(x)
        if st.done.startswith("record ="):
            sigs |= {"I2", "I3"}
    if u == "line":
        sigs |= {"I1", "I3", "I5", "I6", "I7"}
    if u == "arm":
        sigs.add("I4")
    sigs = sorted(sigs, key=lambda x: int(x[1:]))
    L = [f"(* {label}. Generated by stf-cad/hbw/sil/iec.py from the proven motion (control.py); do not edit. *)",
         f"FUNCTION_BLOCK FB_{u.capitalize()}",
         "VAR_INPUT",
         "    Enable : BOOL;        (* K0 safety relay OK AND mode = AUTO *)",
         "    Ack : BOOL;           (* HMI acknowledge *)",
         "    Reset : BOOL;         (* S3 reset, via the safety relay *)",
         "    Cmd : INT;            (* job to start (0 = none), taken when READY *)",
         "    Arg1 : INT;           (* binding: slot / bay / slot pair index *)"]
    for x in sigs:
        L.append(f"    {x} : BOOL;           (* {C.SIG.get((m, x), '')} *)")
    for a, (name, *_ ) in AXES.get(u, {}).items():
        L.append(f"    {name} : REAL;     (* {a}, from the encoder counter *)")
    if u == "belt":
        L += ["    Tag : INT;            (* the mould the record expects at RP2 *)",
              "    ExpI2, ExpI3 : BOOL;  (* the belt's occupancy the record expects *)",
              "    RF1_Valid, RF2_Valid : BOOL;", "    RF2_Tag : INT;"]
    if u == "line":
        L += ["    A4 : INT;             (* colour sensor, mV *)"]
    L += ["END_VAR", "VAR_OUTPUT"]
    for q in outs:
        L.append(f"    {q} : BOOL;           (* {C.SIG.get((m, q), '')} *)")
    L += ["    Ready, Busy, Done, Fault : BOOL;   (* Done: one scan, when a job ends *)",
          "    Alarm : INT;          (* the state whose watchdog tripped *)",
          "    Sn : INT;             (* the active state *)",
          "END_VAR",
          "VAR",
          "    Prev : INT := -1;",
          "    Job, B1 : INT;",
          "    Wd : TON;             (* step watchdog *)",
          "    Tm : TON;             (* step timer *)",
          "    WdTime : TIME;        (* the active state's watchdog; 0 = none *)"]
    if u == "belt":
        L.append("    RfSeen : BOOL;")
    if u == "line":
        L += ["    MinMv : INT := 32767;", "    Cls : INT;", "    Pulses : INT;", "    Edge : R_TRIG;", "    Bar : BOOL;"]
    L.append("END_VAR")
    if tables or u == "line" or any(len({x[k] for x in lm}) > 1 for lm in limits.values() for k in range(len(lm[0]))):
        L.append("VAR CONSTANT")
        for (j, a), (size, n, vals) in tables.items():
            flat = ", ".join(r(v) for row in vals for v in row)
            L.append(f"    TG_{j.upper()}_{a.upper()} : ARRAY[1..{size}, 1..{n}] OF REAL := [{flat}];")
        for j, lims in limits.items():
            for k in range(len(lims[0])):
                if len({x[k] for x in lims}) > 1:
                    L.append(f"    WD_{j.upper()} : ARRAY[1..{len(lims)}, 1..{len(lims[0])}] OF TIME := "
                             f"[{', '.join(ms(x[c]) if x[c] else 'T#0MS' for x in lims for c in range(len(lims[0])))}];")
                    break
        if u == "line":
            pitch = PULSE_MM
            n_ej = [round((C.SM.S["EJECT_X"][k] - C.SM.S["AFTER_X"]) / pitch) for k in range(len(BAYS))]
            L.append(f"    NEJECT : ARRAY[1..{len(BAYS)}] OF INT := [{', '.join(map(str, n_ej))}];  "
                     f"(* I1 pulses from I3 to each ejector, {PULSE_MM:g} mm per pulse (ASSUMED) *)")
        L.append("END_VAR")
    L += ["", "(* every scan: outputs off unless the active state sets them; Done is a pulse *)",
          " ".join(f"{q} := FALSE;" for q in outs) + " Done := FALSE;",
          "IF NOT Enable AND Sn <> 900 THEN Sn := 900; END_IF",
          "Wd(IN := (Sn = Prev) AND (WdTime > T#0MS), PT := WdTime);",
          "Tm(IN := (Sn = Prev), PT := T#1H);"]
    if u == "belt":
        L.append("IF Sn <> Prev THEN RfSeen := FALSE; END_IF")
        L.append("RfSeen := RfSeen OR RF1_Valid;")
    if u == "line":
        L += ["Edge(CLK := I1);",
              "IF Sn <> Prev THEN Pulses := 0; END_IF",
              "IF Edge.Q THEN Pulses := Pulses + 1; END_IF",
              "IF A4 < MinMv THEN MinMv := A4; END_IF",
              "CASE B1 OF 1: Bar := I5; 2: Bar := I6; 3: Bar := I7; ELSE Bar := FALSE; END_CASE;"]
    L += ["Prev := Sn;",
          "IF Wd.Q THEN Alarm := Sn; Sn := 910; END_IF", "", "CASE Sn OF"]
    first_home = 10 if hs else 100
    L.append("  0: (* INIT: power-up, all outputs off *)")
    L.append(f"      WdTime := T#0MS; IF Enable THEN Sn := {first_home}; END_IF;")
    for i, st in enumerate(hs):
        code = 10 + i
        nxt = code + 1 if i + 1 < len(hs) else 100
        L += _state(u, code, f"{st.key}: {st.say}", st, _cond(u, st, None, None), nxt, None, None)
    L.append("  100: (* READY: homed, waiting for a job *)")
    L.append("      WdTime := T#0MS; Ready := TRUE; Busy := FALSE;")
    L.append("      IF Cmd <> 0 THEN Job := Cmd; B1 := Arg1; Busy := TRUE; Ready := FALSE;")
    first = {j: 1000 * (k + 1) for k, j in enumerate(jobs)}
    L.append("          CASE Cmd OF " + " ".join(f"{JOB_IX[j]}: Sn := {first[j]};" for j in jobs) +
             " ELSE Sn := 910; Alarm := -Cmd; END_CASE;")
    if u == "line":
        L.append("          MinMv := 32767;")
    L.append("      END_IF;")
    for j in jobs:
        steps = segs[j]
        for k, st in enumerate(steps):
            code = first[j] + k
            last = k + 1 == len(steps)
            nxt = 100 if last else code + 1
            varies = len({x[k] for x in limits[j]}) > 1
            L += _state(u, code, f"{j}.{k + 1:02d} {st.key}: {st.say}", st, _cond(u, st, k + 1, j), nxt, j, k + 1,
                        done=last, wd=f"WD_{j.upper()}[B1, {k + 1}]" if varies else None)
    L.append("  900: (* ESTOP: the safety relay dropped, outputs off *)")
    L.append("      WdTime := T#0MS; Busy := FALSE; Ready := FALSE; IF Reset AND Enable THEN Sn := 0; END_IF;")
    L.append("  910: (* FAULT: a step timed out, outputs off, alarm raised *)")
    L.append("      WdTime := T#0MS; Fault := TRUE; Busy := FALSE; Ready := FALSE;")
    L.append(f"      IF Ack AND Enable THEN Fault := FALSE; Sn := {first_home}; END_IF;")
    L.append("END_CASE;")
    if u == "door":
        # F8 (found by this upgrade's run): Q13 is single-acting - the door is open only while it
        # is energised. Between U10's `present` and `place_oven` (and between `bake` and `to_tt`)
        # the unit is READY with every output off, so the door fell shut on the extended
        # Ofenschieber. The door is now held open whenever the Ofenschieber is not inside.
        L.append("IF NOT I6 AND Sn <> 900 AND Sn <> 910 THEN Q13 := TRUE; END_IF;   (* F8: never shut on the Ofenschieber *)")
    L += ["END_FUNCTION_BLOCK", ""]
    return "\n".join(L), {j: (first[j], len(segs[j])) for j in jobs}


def segments_of(b):
    steps = C.job_steps(b)
    order = list(dict.fromkeys(st.unit for st in steps))
    return [(u, [st for st in steps if st.unit == u]) for u in order]


# control.BAND as ST: the bay index (BAYS order) of the class the darkest reading falls in
CLASSIFY = " ELS".join(f"IF MinMv < {hi} THEN Cls := {BAYS.index(b) + 1}; "
                       for b, (lo, hi) in sorted(C.BAND.items(), key=lambda x: x[1][0])).replace(
    "ELSIF MinMv < 5000 THEN", "ELSE") + "END_IF;"
PULSE_MM = 5.0          # the Impulstaster: one pulse per 5 mm of sorting belt (ASSUMED)


def _state(u, code, say, st, cond, nxt, job, k, done=False, wd=None):
    say = say.replace("(*", "(").replace("*)", ")")
    lim = wd or (ms(step_limit(st)) if st.limit else "T#0MS")
    body = [f"  {code}: (* {say} *)", f"      WdTime := {lim};"]
    axes = [a for a in AXES.get(u, {}) if a in st.target]
    drive_outs = {o for a in axes for o in AXES[u][a][1:3]}
    static = [q for q in st.out if q not in drive_outs]
    if u == "line" and job == "sort" and st.key == "eject":
        body.append("      CASE B1 OF 1: Q3 := TRUE; 2: Q4 := TRUE; 3: Q5 := TRUE; END_CASE;")
        static = []
    if static:
        body.append("      " + " ".join(f"{q} := TRUE;" for q in static))
    for a in axes:
        name, neg, pos, _ = AXES[u][a]
        tgt = r(st.target[a]) if job is None else f"TG_{job.upper()}_{a.upper()}[B1, {k}]"
        body.append(f"      CASE Drive({name}, {tgt}, {r(lead(u, a))}) OF -1: {neg} := TRUE; 1: {pos} := TRUE; END_CASE;")
    if u == "line" and job == "sort" and st.key == "classify":
        body.append("      " + CLASSIFY)
    fin = " Done := TRUE; Busy := FALSE;" if done else ""
    body.append(f"      IF {cond} THEN{fin} Sn := {nxt}; END_IF;")
    return body


DRIVE = """(* -1 / 0 / +1: which way to drive an axis toward its target; 0 inside the brake lead *)
FUNCTION Drive : INT
VAR_INPUT
    Pos, Tgt, Lead : REAL;
END_VAR
IF Tgt - Pos > Lead THEN Drive := 1; ELSIF Pos - Tgt > Lead THEN Drive := -1; ELSE Drive := 0; END_IF;
END_FUNCTION
"""


# ------------------------------------------------------------ the I/O image
def io_map():
    """Every located variable: the plant reads %QX and writes %IX/%IW/%ID; %MW is the monitor."""
    ins, outs = [], []
    for u in C.UNIT_ORDER:
        m = MODULE[u]
        src, _ = fb(u)
        decl = src.split("VAR_INPUT")[1].split("END_VAR")[0]
        for x in sorted({ln.split(":")[0].strip() for ln in decl.splitlines() if ln.strip().startswith("I")
                         and ln.split(":")[0].strip()[1:].isdigit()}, key=lambda x: int(x[1:])):
            if (m, x) not in ins:
                ins.append((m, x))
        for q in C.UNITS[u][1]:
            outs.append((m, q))
    ins += [("hbw", "RF1_Valid"), ("hbw", "RF2_Valid"), ("cell", "SafetyOK")]
    ix = [{"name": f"{m}_{s}", "module": m, "signal": s, "addr": f"%IX{i // 8}.{i % 8}", "bit": i,
           "desc": C.SIG.get((m, s), "safety relay K0: OK" if s == "SafetyOK" else C.SIG.get((m, s[:3]), ""))}
          for i, (m, s) in enumerate(ins)]
    qx = [{"name": f"{m}_{q}", "module": m, "signal": q, "addr": f"%QX{i // 8}.{i % 8}", "bit": i,
           "desc": C.SIG.get((m, q), "")} for i, (m, q) in enumerate(outs)]
    iw = [{"name": "hbw_RF2_Tag", "addr": "%IW0", "word": 0, "desc": "RFID RP2: the tag read (mould number)"},
          {"name": "sorting_A4", "addr": "%IW1", "word": 1, "desc": "colour sensor, mV"}]
    idd = [{"name": f"{'hbw' if u == 'crane' else 'vgr'}_{AXES[u][a][0]}", "unit": u, "axis": a,
            "addr": f"%ID{i}", "word": i, "desc": f"{u} {a} encoder position"} for i, (u, a) in enumerate(ENCODER)]
    mw = [{"name": "mon_phase", "addr": "%MW0", "word": 0, "desc": "0 homing, 1 production, 2 order complete"},
          {"name": "mon_jobs", "addr": "%MW1", "word": 1, "desc": "jobs completed"}]
    for u in C.UNIT_ORDER:
        b = 10 * UNIT_IX[u]
        mw += [{"name": f"mon_{u}_sn", "addr": f"%MW{b}", "word": b, "desc": f"{u}: active state"},
               {"name": f"mon_{u}_job", "addr": f"%MW{b + 1}", "word": b + 1, "desc": f"{u}: job it leads (MAIN code)"}]
        mw += [{"name": f"mon_{u}_b{k}", "addr": f"%MW{b + 1 + k}", "word": b + 1 + k, "desc": f"{u}: binding {k}"}
               for k in range(1, 7)]
        mw += [{"name": f"mon_{u}_alarm", "addr": f"%MW{b + 8}", "word": b + 8, "desc": f"{u}: alarm state"},
               {"name": f"mon_{u}_seg", "addr": f"%MW{b + 9}", "word": b + 9, "desc": f"{u}: unit running its segment"},
               {"name": f"mon_{u}_n", "addr": f"%MW{100 + UNIT_IX[u]}", "word": 100 + UNIT_IX[u],
                "desc": f"{u}: jobs it has started (a job ending and the next starting in one scan)"}]
    return {"ix": ix, "qx": qx, "iw": iw, "id": idd, "mw": mw}


# ------------------------------------------------------------ MAIN
RAW, RETURN, RETURNING, STORED, BAKED, DONE = 1, 2, 3, 4, 5, 6
STAGE = {"raw": RAW, "return": RETURN, "returning": RETURNING, "stored": STORED, "baked": BAKED, "done": DONE}
OUT_, FILL, IN_ = 1, 2, 3
CIX = {c: i + 1 for i, c in enumerate(C.CIDS)}
MIX = {C.MOULD[s]: i + 1 for i, s in enumerate(SLOTS)}
# what each job's binding holds in RB[lead, 1..6] (control.py's job tuple, as indices)
LAYOUT = {"sort": ("c", "bay"), "ovenbelt": ("c",), "saw_eject": ("c",), "to_tt": ("c",), "bake": ("c",),
          "present": ("c",), "place_oven": ("c", "src"), "belt_to_oven": ("c", "m"), "bay_to_belt": ("c", "bay", "m"),
          "belt_back": ("m", "c"), "store_retrieve": ("m", "c", "slot", "c", "m", "slot"), "belt_fwd": ("m", "c"),
          "store": ("m", "c", "slot"), "fetch_empty": ("m", "slot"), "retrieve": ("c", "m", "slot")}


def _arr(vals):
    return "[" + ", ".join(str(v).upper() if isinstance(v, bool) else str(v) for v in vals) + "]"


def main_program():
    s0 = C.initial()
    assert C.OPT["split"] and C.OPT["dual"] and C.PLC_POLICY == "reuse", "U13 generates the Upgrade 12 program"
    io = io_map()
    U = {u: UNIT_IX[u] for u in C.UNIT_ORDER}
    slot_m = [MIX[sl[0]] if sl else 0 for sl in s0["slots"]]
    slot_c = [CIX[sl[1]] if sl and sl[1] else 0 for sl in s0["slots"]]
    cap = C.BAY_CAP
    bay0 = []
    for b in range(len(BAYS)):
        row = [CIX[c] for c in s0["bays"][b]]
        bay0 += row + [0] * (cap - len(row))
    stage0 = [STAGE[x] for x in s0["stage"]]
    flv = [BAYS.index(C.PL.BIN_OF[C.FLAV[c]]) + 1 for c in C.CIDS]
    prod = [CIX[c] for c in C.PRODUCE]
    isret = [c in C.RETURN for c in C.CIDS]
    dual = [round(C._dual_t(i, j), 3) if i != j else 0.0 for i in range(NS) for j in range(NS)]

    L = ["(* The orchestrator: control.py's dispatcher, statement for statement. Generated by sil/iec.py. *)",
         "PROGRAM MAIN", "VAR"]
    for x in io["ix"]:
        L.append(f"    {x['name']} AT {x['addr']} : BOOL;")
    for x in io["iw"]:
        L.append(f"    {x['name']} AT {x['addr']} : INT;")
    for x in io["id"]:
        L.append(f"    {x['name']} AT {x['addr']} : REAL;")
    for x in io["qx"]:
        L.append(f"    {x['name']} AT {x['addr']} : BOOL;")
    for x in io["mw"]:
        L.append(f"    {x['name']} AT {x['addr']} : INT;")
    L += ["END_VAR", "VAR"]
    for u in C.UNIT_ORDER:
        L.append(f"    {u.capitalize()} : FB_{u.capitalize()};")
    nu = len(C.UNIT_ORDER)
    L += [f"    Cmd, Arg, RJ, Seg, Nst : ARRAY[1..{nu}] OF INT;   (* per unit: command; per lead: job, segment, starts *)",
          f"    RB : ARRAY[1..{nu}, 1..6] OF INT;                  (* per lead: the job's binding *)",
          f"    UBusy, Dn, Rdy : ARRAY[1..{nu}] OF BOOL;",
          "    BeltTag : INT;",
          "    Phase, Jobs : INT;",
          "    (* the factory, as control.py keeps it *)",
          f"    SlotM : ARRAY[1..{NS}] OF INT := {_arr(slot_m)};   (* mould in each slot, 0 = free *)",
          f"    SlotC : ARRAY[1..{NS}] OF INT := {_arr(slot_c)};   (* cookie in that mould *)",
          "    BinM, BinC, BinMode, BoutM, BoutC, BoutMode : INT;   (* belt ends: mould, cookie, 1 out 2 fill 3 in *)",
          "    Tray, Tt, Ovb, Inlet, CupC, CupSrc : INT;",
          "    Tout : BOOL;",
          f"    Bay : ARRAY[1..{len(BAYS)}, 1..{cap}] OF INT := {_arr(bay0)};",
          f"    BayN : ARRAY[1..{len(BAYS)}] OF INT := {_arr([len(x) for x in s0['bays']])};",
          f"    Stage : ARRAY[1..{len(C.CIDS)}] OF INT := {_arr(stage0)};   (* 1 raw 2 return 3 returning 4 stored 5 baked 6 done *)",
          "    (* reservations (destinations) and departures (sources) *)",
          f"    ResSlot, LvSlot : ARRAY[1..{NS}] OF BOOL;",
          f"    ResBay : ARRAY[1..{len(BAYS)}] OF INT;",
          f"    LvBay : ARRAY[1..{len(BAYS)}] OF BOOL;",
          "    ResBin, LvBin, ResBout, LvBout, ResTray, LvTray, ResTt, LvTt, ResOvb, LvOvb, ResSin, LvSin : BOOL;",
          "    Started, Found : BOOL;",
          "    i, j, k, n, c, b, m, tm, ts, Pend, jb : INT;",
          "    x1, x2, x3, x4, x5, x6 : INT;",
          "    BestT : REAL;",
          "END_VAR",
          "VAR CONSTANT",
          f"    FLV : ARRAY[1..{len(C.CIDS)}] OF INT := {_arr(flv)};   (* cookie -> the bay of its flavour *)",
          f"    PROD : ARRAY[1..{len(prod)}] OF INT := {_arr(prod)};   (* production order *)",
          f"    ISRET : ARRAY[1..{len(C.CIDS)}] OF BOOL := {_arr(isret)};   (* a cookie that goes into the rack *)",
          f"    DUALT : ARRAY[1..{NS}, 1..{NS}] OF REAL := [{', '.join(r(x) for x in dual)}];   (* dual-command trip, s *)",
          f"    BAYCAP : INT := {cap};",
          "END_VAR", ""]
    # 1. the sequencers
    L.append("(* 1. the unit sequencers, then their outputs *)")
    for u in C.UNIT_ORDER:
        m = MODULE[u]
        src, _ = fb(u)
        decl = src.split("VAR_INPUT")[1].split("END_VAR")[0]
        names = [ln.split(":")[0].strip() for ln in decl.splitlines() if ":" in ln and not ln.strip().startswith("(*")]
        args = []
        for n_ in names:
            for nm in n_.split(","):
                nm = nm.strip()
                if nm in ("Enable",):
                    args.append("Enable := cell_SafetyOK")
                elif nm in ("Ack", "Reset", "ExpI2", "ExpI3"):
                    args.append(f"{nm} := FALSE")
                elif nm == "Cmd":
                    args.append(f"Cmd := Cmd[{U[u]}]")
                elif nm == "Arg1":
                    args.append(f"Arg1 := Arg[{U[u]}]")
                elif nm == "Tag":
                    args.append("Tag := BeltTag")
                elif nm.startswith("Pos"):
                    args.append(f"{nm} := {'hbw' if u == 'crane' else 'vgr'}_{nm}")
                elif nm in ("RF1_Valid", "RF2_Valid", "RF2_Tag"):
                    args.append(f"{nm} := hbw_{nm}")
                elif nm == "A4":
                    args.append("A4 := sorting_A4")
                else:
                    args.append(f"{nm} := {m}_{nm}")
        L.append(f"{u.capitalize()}({', '.join(args)});")
        L.append(f"IF {u.capitalize()}.Busy THEN Cmd[{U[u]}] := 0; END_IF;")
        L.append(f"Dn[{U[u]}] := {u.capitalize()}.Done; Rdy[{U[u]}] := {u.capitalize()}.Ready;")
        L.append(" ".join(f"{m}_{q} := {u.capitalize()}.{q};" for q in C.UNITS[u][1]))
    L.append("")
    dispatch = _dispatch(U)
    L += ["(* 2. production starts once every unit has homed *)",
          "IF Phase = 0 THEN",
          "    Found := TRUE;",
          f"    FOR k := 1 TO {nu} DO Found := Found AND Rdy[k]; END_FOR;",
          "    IF Found THEN",
          "        Phase := 1;"] + ["        " + x for x in dispatch] + ["    END_IF;", "END_IF;", ""]
    L += ["(* 3. completions, leads in unit order (control.simulate's tie order); each is followed by a dispatch *)",
          "IF Phase = 1 THEN",
          f"    FOR k := 1 TO {nu} DO",
          "        IF RJ[k] <> 0 AND Seg[k] <> 0 THEN",
          "            IF Dn[Seg[k]] THEN"]
    multi = [j for j in JOBS if len(segments(j)) > 1]
    for j in multi:
        segs = [U[u] for u, _ in segments(j)]
        for a, b_ in zip(segs, segs[1:], strict=False):
            L += [f"                IF RJ[k] = {JOB_IX[j]} AND Seg[k] = {a} THEN   (* {j}: next segment *)",
                  f"                    Seg[k] := {b_}; Cmd[{b_}] := {JOB_IX[j]}; Arg[{b_}] := Arg[{a}]; Dn[{a}] := FALSE;",
                  "                END_IF;"]
    L += ["            END_IF;",
          "            IF Dn[Seg[k]] THEN"]
    L += ["                " + x for x in _complete(U)]
    L += ["                " + x for x in dispatch]
    L += ["            END_IF;", "        END_IF;", "    END_FOR;"]
    # goal
    L += ["    (* the order is complete: nothing running, nothing in transit, every cookie done or stored *)",
          "    Found := (BinM = 0) AND (BoutM = 0) AND (Tray = 0) AND (Tt = 0) AND (Ovb = 0) AND (Inlet = 0) AND (CupC = 0);",
          f"    FOR k := 1 TO {nu} DO Found := Found AND (RJ[k] = 0); END_FOR;",
          f"    FOR k := 1 TO {len(prod)} DO Found := Found AND (Stage[PROD[k]] = {DONE}); END_FOR;",
          "    IF Found THEN Phase := 2; END_IF;",
          "END_IF;", ""]
    # monitor
    L.append("(* 4. the monitor *)")
    L.append("mon_phase := Phase; mon_jobs := Jobs;")
    for u in C.UNIT_ORDER:
        k = U[u]
        L.append(f"mon_{u}_sn := {u.capitalize()}.Sn; mon_{u}_job := RJ[{k}]; mon_{u}_alarm := {u.capitalize()}.Alarm; "
                 f"mon_{u}_seg := Seg[{k}]; mon_{u}_n := Nst[{k}];")
        L.append(" ".join(f"mon_{u}_b{i} := RB[{k}, {i}];" for i in range(1, 7)))
    L += ["END_PROGRAM", ""]
    return "\n".join(L)


def _start(U, job, binding, extra, arg="1"):
    """ST that starts a job: reserve its units, record its binding, command its first segment."""
    lead = U[RESERVE[job][0]]
    first = U[segments(job)[0][0]]
    out = [f"(* start {job} *)"]
    out.append(" ".join(f"UBusy[{U[u]}] := TRUE;" for u in RESERVE[job]))
    out.append(f"RJ[{lead}] := {JOB_IX[job]}; Seg[{lead}] := {first}; Nst[{lead}] := Nst[{lead}] + 1;")
    out.append(" ".join(f"RB[{lead}, {i + 1}] := {v};" for i, v in enumerate(binding)) +
               "".join(f" RB[{lead}, {i + 1}] := 0;" for i in range(len(binding), 6)))
    out.append(f"Cmd[{first}] := {JOB_IX[job]}; Arg[{first}] := {arg};")
    out += extra
    out.append("Started := TRUE;")
    return out


def _free_units(U, job):
    return " AND ".join(f"NOT UBusy[{U[u]}]" for u in RESERVE[job])


def _pending():
    """control._pending_fill: cookies still to go into the rack, minus moulds earmarked for them."""
    out = ["Pend := 0;", f"FOR i := 1 TO {len(C.CIDS)} DO IF ISRET[i] AND Stage[i] = {RETURN} THEN Pend := Pend + 1; END_IF; END_FOR;",
           f"IF BinM <> 0 AND BinMode = {FILL} THEN Pend := Pend - 1; END_IF;",
           f"IF BoutM <> 0 AND BoutMode = {FILL} THEN Pend := Pend - 1; END_IF;",
           f"IF RJ[1] = {JOB_IX['fetch_empty']} THEN Pend := Pend - 1; END_IF;"]
    return out


def _dispatch(U):
    """control.dispatch(): start the first startable job in priority order, again, until none."""
    nb = len(BAYS)
    D = ["REPEAT", "    Started := FALSE;"]

    def rule(title, cond, body):
        D.append(f"    (* {title} *)")
        D.append(f"    IF NOT Started AND {cond} THEN")
        D.extend("        " + x for x in body)
        D.append("    END_IF;")

    rule("1 sort: the cookie at the sorting inlet, if its bay has room", "Inlet <> 0 AND NOT LvSin",
         ["b := FLV[Inlet];",
          f"IF BayN[b] + ResBay[b] < BAYCAP AND {_free_units(U, 'sort')} THEN"] +
         ["    " + x for x in _start(U, "sort", ["Inlet", "b"], ["LvSin := TRUE; ResBay[b] := ResBay[b] + 1;"], "b")] +
         ["END_IF;"])
    rule("2 oven belt -> sorting inlet", f"Ovb <> 0 AND NOT LvOvb AND NOT ResSin AND Inlet = 0 AND {_free_units(U, 'ovenbelt')}",
         _start(U, "ovenbelt", ["Ovb"], ["LvOvb := TRUE; ResSin := TRUE;"]))
    rule("3 saw and eject", f"Tt <> 0 AND NOT LvTt AND Stage[Tt] = {BAKED} AND NOT ResOvb AND Ovb = 0 AND {_free_units(U, 'saw_eject')}",
         _start(U, "saw_eject", ["Tt"], ["LvTt := TRUE; ResOvb := TRUE;"]))
    rule("4 Sauger: tray -> turntable", f"Tray <> 0 AND NOT LvTray AND Stage[Tray] = {BAKED} AND NOT ResTt AND Tt = 0 AND {_free_units(U, 'to_tt')}",
         _start(U, "to_tt", ["Tray"], ["LvTray := TRUE; ResTt := TRUE;"]))
    rule("5 bake", f"Tray <> 0 AND NOT LvTray AND Stage[Tray] = {RAW} AND {_free_units(U, 'bake')}",
         _start(U, "bake", ["Tray"], ["LvTray := TRUE;"]))
    rule("5a the oven presents its tray while the cookie for it is on its way",
         f"Tray = 0 AND NOT Tout AND (CupC <> 0 OR ResTray) AND NOT LvTray AND {_free_units(U, 'present')}",
         _start(U, "present", ["CupC"], []))
    rule("5b the VGR lays the cookie on the presented tray", f"CupC <> 0 AND Tout AND Tray = 0 AND {_free_units(U, 'place_oven')}",
         _start(U, "place_oven", ["CupC", "CupSrc"], []))
    rule("7 belt -> oven (the pick half): the oven is free of a committed cookie, the cup is empty",
         f"BoutM <> 0 AND BoutC <> 0 AND BoutMode = {OUT_} AND NOT LvBout AND CupC = 0 AND NOT ResTray AND {_free_units(U, 'belt_to_oven')}",
         _start(U, "belt_to_oven", ["BoutC", "BoutM"], ["LvBout := TRUE; ResTray := TRUE;"]))
    rule("9 bay -> the empty mould at the hand-over (the first bay holding a cookie that goes in)",
         f"BoutM <> 0 AND BoutC = 0 AND BoutMode = {FILL} AND NOT LvBout AND CupC = 0",
         ["Found := FALSE;",
          f"FOR i := 1 TO {nb} DO",
          "    IF NOT Found THEN",
          "        FOR j := 1 TO BayN[i] DO",
          f"            IF NOT Found AND Stage[Bay[i, j]] = {RETURN} THEN Found := TRUE; c := Bay[i, j]; b := i; END_IF;",
          "        END_FOR;",
          "    END_IF;",
          "END_FOR;",
          f"IF Found AND {_free_units(U, 'bay_to_belt')} THEN"] +
         ["    " + x for x in _start(U, "bay_to_belt", ["c", "b", "BoutM"], ["LvBay[b] := TRUE;"], "b")] +
         ["END_IF;"])
    rule("10 belt back", f"BoutM <> 0 AND BoutMode = {IN_} AND NOT LvBout AND NOT ResBin AND BinM = 0 AND {_free_units(U, 'belt_back')}",
         _start(U, "belt_back", ["BoutM", "BoutC"], ["LvBout := TRUE; ResBin := TRUE; BeltTag := BoutM;"]))
    # to_make: the next cookie of the production order still raw in the rack
    D += ["    (* the next cookie of the production order that is still raw in the rack, and its slot *)",
          "    tm := 0; ts := 0;",
          f"    FOR i := 1 TO {len(C.PRODUCE)} DO",
          f"        IF tm = 0 AND Stage[PROD[i]] = {RAW} THEN",
          f"            FOR j := 1 TO {NS} DO IF SlotM[j] <> 0 AND SlotC[j] = PROD[i] THEN tm := PROD[i]; ts := j; END_IF; END_FOR;",
          "        END_IF;",
          "    END_FOR;"]
    rule("10a dual command: store the mould coming in in the free slot nearest the next cookie, retrieve that cookie",
         f"BinM <> 0 AND BinMode = {IN_} AND NOT LvBin AND tm <> 0 AND NOT ResBout AND BoutM = 0",
         ["n := 0; BestT := 1.0E9;",
          f"FOR i := 1 TO {NS} DO",
          "    IF NOT ResSlot[i] AND SlotM[i] = 0 THEN",
          "        IF DUALT[i, ts] < BestT THEN BestT := DUALT[i, ts]; n := i; END_IF;",
          "    END_IF;",
          "END_FOR;",
          f"IF n <> 0 AND NOT LvSlot[ts] AND {_free_units(U, 'store_retrieve')} THEN"] +
         ["    " + x for x in _start(U, "store_retrieve", ["BinM", "BinC", "n", "tm", "SlotM[ts]", "ts"],
                                   ["LvBin := TRUE; LvSlot[ts] := TRUE; ResSlot[n] := TRUE; ResBin := TRUE;"],
                                   f"(n - 1) * {NS} + ts")] +
         ["END_IF;"])
    rule("11 belt forward", f"BinM <> 0 AND (BinMode = {OUT_} OR BinMode = {FILL}) AND NOT LvBin AND NOT ResBout AND BoutM = 0 "
         f"AND {_free_units(U, 'belt_fwd')}",
         _start(U, "belt_fwd", ["BinM", "BinC"], ["LvBin := TRUE; ResBout := TRUE; BeltTag := BinM;"]))
    rule("12 store in the first free slot", f"BinM <> 0 AND BinMode = {IN_} AND NOT LvBin",
         ["n := 0;",
          f"FOR i := {NS} TO 1 BY -1 DO IF NOT ResSlot[i] AND SlotM[i] = 0 THEN n := i; END_IF; END_FOR;",
          f"IF n <> 0 AND {_free_units(U, 'store')} THEN"] +
         ["    " + x for x in _start(U, "store", ["BinM", "BinC", "n"], ["LvBin := TRUE; ResSlot[n] := TRUE;"], "n")] +
         ["END_IF;"])
    rule("13 fetch an empty mould for a cookie going in (with reuse: only when nothing is left to retrieve)",
         "NOT ResBin AND BinM = 0 AND NOT ResBout AND BoutM = 0 AND tm = 0",
         _pending() +
         ["IF Pend > 0 THEN",
          "    n := 0;",
          f"    FOR i := {NS} TO 1 BY -1 DO IF SlotM[i] <> 0 AND SlotC[i] = 0 AND NOT LvSlot[i] THEN n := i; END_IF; END_FOR;",
          f"    IF n <> 0 AND {_free_units(U, 'fetch_empty')} THEN"] +
         ["        " + x for x in _start(U, "fetch_empty", ["SlotM[n]", "n"], ["LvSlot[n] := TRUE; ResBin := TRUE;"], "n")] +
         ["    END_IF;", "END_IF;"])
    rule("14 retrieve the next cookie in production order", "NOT ResBin AND BinM = 0 AND NOT ResBout AND BoutM = 0 AND tm <> 0",
         [f"IF NOT LvSlot[ts] AND {_free_units(U, 'retrieve')} THEN"] +
         ["    " + x for x in _start(U, "retrieve", ["tm", "SlotM[ts]", "ts"], ["LvSlot[ts] := TRUE; ResBin := TRUE;"], "ts")] +
         ["END_IF;"])
    D.append("UNTIL NOT Started")
    D.append("END_REPEAT;")
    return D


def _complete(U):
    """control.complete(): release the job's units and places, then apply its effect."""
    out = ["(* complete the job lead k runs: control.complete() *)",
           "jb := RJ[k]; x1 := RB[k, 1]; x2 := RB[k, 2]; x3 := RB[k, 3]; x4 := RB[k, 4]; x5 := RB[k, 5]; x6 := RB[k, 6];",
           "RJ[k] := 0; Seg[k] := 0; Jobs := Jobs + 1;",
           "CASE jb OF"]
    rel = {
        "sort": ["LvSin := FALSE; ResBay[x2] := ResBay[x2] - 1;"],
        "ovenbelt": ["LvOvb := FALSE; ResSin := FALSE;"],
        "saw_eject": ["LvTt := FALSE; ResOvb := FALSE;"],
        "to_tt": ["LvTray := FALSE; ResTt := FALSE;"],
        "bake": ["LvTray := FALSE;"],
        "present": [], "place_oven": [],
        "belt_to_oven": ["LvBout := FALSE; ResTray := FALSE;"],
        "bay_to_belt": ["LvBay[x2] := FALSE;"],
        "belt_back": ["LvBout := FALSE; ResBin := FALSE;"],
        "store_retrieve": ["LvBin := FALSE; LvSlot[x6] := FALSE; ResSlot[x3] := FALSE; ResBin := FALSE;"],
        "belt_fwd": ["LvBin := FALSE; ResBout := FALSE;"],
        "store": ["LvBin := FALSE; ResSlot[x3] := FALSE;"],
        "fetch_empty": ["LvSlot[x2] := FALSE; ResBin := FALSE;"],
        "retrieve": ["LvSlot[x3] := FALSE; ResBin := FALSE;"],
    }
    eff = {
        "retrieve": [f"SlotM[x3] := 0; SlotC[x3] := 0; BinM := x2; BinC := x1; BinMode := {OUT_};"],
        "fetch_empty": [f"SlotM[x2] := 0; SlotC[x2] := 0; BinM := x1; BinC := 0; BinMode := {FILL};"],
        "belt_fwd": ["BoutM := BinM; BoutC := BinC; BoutMode := BinMode; BinM := 0; BinC := 0; BinMode := 0;"],
        "belt_back": ["BinM := BoutM; BinC := BoutC; BinMode := BoutMode; BoutM := 0; BoutC := 0; BoutMode := 0;"],
        "store": ["SlotM[x3] := x1; SlotC[x3] := x2; BinM := 0; BinC := 0; BinMode := 0;",
                  f"IF x2 <> 0 THEN Stage[x2] := {STORED}; END_IF;"],
        "store_retrieve": ["SlotM[x3] := x1; SlotC[x3] := x2; SlotM[x6] := 0; SlotC[x6] := 0;",
                           f"IF x2 <> 0 THEN Stage[x2] := {STORED}; END_IF;",
                           f"BinM := x5; BinC := x4; BinMode := {OUT_};"],
        "belt_to_oven": _pending() + [f"BoutC := 0; IF Pend > 0 THEN BoutMode := {FILL}; ELSE BoutMode := {IN_}; END_IF;",
                                      "CupC := x1; CupSrc := 1;"],
        "place_oven": ["Tray := CupC; CupC := 0; CupSrc := 0;"],
        "present": ["Tout := TRUE;"],
        "bay_to_belt": ["n := 0;",
                        "FOR j := 1 TO BayN[x2] DO IF Bay[x2, j] <> x1 THEN n := n + 1; Bay[x2, n] := Bay[x2, j]; END_IF; END_FOR;",
                        "FOR j := n + 1 TO BAYCAP DO Bay[x2, j] := 0; END_FOR;",
                        f"BayN[x2] := n; BoutM := x3; BoutC := x1; BoutMode := {IN_}; Stage[x1] := {RETURNING};"],
        "bake": [f"Stage[x1] := {BAKED};"],
        "to_tt": ["Tt := Tray; Tray := 0; Tout := FALSE;"],
        "saw_eject": [f"Ovb := Tt; Tt := 0; Stage[x1] := {BAKED};"],
        "ovenbelt": ["Inlet := Ovb; Ovb := 0;"],
        "sort": [f"BayN[x2] := BayN[x2] + 1; Bay[x2, BayN[x2]] := x1; Inlet := 0; Stage[x1] := {DONE};"],
    }
    for j in JOBS:
        out.append(f"  {JOB_IX[j]}: (* {j} *)")
        out.append("      " + " ".join(f"UBusy[{U[u]}] := FALSE;" for u in RESERVE[j]))
        out += ["      " + x for x in rel[j] + eff[j]]
    out.append("END_CASE;")
    return out


def project():
    """The whole program as one IEC 61131-3 source, with its configuration."""
    parts = ["(* STF Upgrade 12 - PLC program, IEC 61131-3 Structured Text. Generated by stf-cad/hbw/sil/iec.py *)",
             f"(* from the proven models; compile with MatIEC (iec2c). Task: {SCAN_MS} ms. *)", "", DRIVE]
    starts = {}
    for u in C.UNIT_ORDER:
        src, st = fb(u)
        parts.append(src)
        starts[u] = st
    parts.append(main_program())
    parts += ["CONFIGURATION Cell", "    RESOURCE Plc ON PLC",
              f"        TASK Scan(INTERVAL := T#{SCAN_MS}MS, PRIORITY := 0);",
              "        PROGRAM Run WITH Scan : MAIN;", "    END_RESOURCE", "END_CONFIGURATION", ""]
    src = re.sub(r"\b(END_IF|END_CASE|END_FOR|END_WHILE|END_REPEAT)\b(?!;)", r"\1;", "\n".join(parts))
    return src, starts
