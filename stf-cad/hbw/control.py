"""
Upgrade 4 - the control program, the orchestrator and traceability
(STF_VARIANT=up4).

The factory is run by a PLC program generated from the same models that prove
the machine, not by a demo timeline.

  UNITS    eight sequencers - crane, belt, arm, door, sauger, turntable,
           ovenbelt, line - each a state machine INIT -> HOMING -> READY ->
           job steps -> READY, with FAULT and ESTOP reachable from every
           state. A unit only ever drives its own outputs.
  STEPS    every job is a list of steps taken from motion the models already
           prove: the HBW legs of hbw_model.cycle(), the VGR waypoints of
           vgr_path.plan() (each tour swept clear), and the oven rows of
           motion.OVEN_CYCLE (every frame passes the door interlock). Each step
           has its outputs, its completion signal and a nominal time. If it
           moves anything it also has a timeout and an alarm.
  MOULDS   the 12 Werkstuecktraeger are modelled and tagged. The base schedule
           let the empty mould vanish at the VGR hand-over; here it has to go
           back into the rack, or be refilled with a cookie that is going in.
  ORCHESTRATOR  a PLC-style scan. After every job completion the units are
           offered jobs in one fixed priority order.
  PROOFS   (1) every unit state reaches READY and ESTOP; outputs are off in
           INIT/READY/FAULT/ESTOP; no motor is driven both ways; every signal is
           in the Belegungsplan; every motion has a timeout.
           (2) the orchestrator, explored EXHAUSTIVELY over every completion
           order - every possible timing - never deadlocks, conserves 12
           cookies and 12 moulds, and ends with every cookie in its bin.
           (3) every cookie's trace record is complete, and its flavour is
           confirmed by the colour sensor.

Assumed, and flagged wherever shown: axis speeds as motion.py (HBW 150 mm/s,
VGR 60 deg/s and 120 mm/s), belts 50 mm/s, an RFID read 0.3 s, vacuum 0.5 s,
and the booklet's demo bake (2 s). A real bake only scales the oven's share.
"""
import math
from dataclasses import dataclass, field

import controller as CT
import hbw_model as HM
import motion as MO
import oven_model as OM
import pipeline as PL
import sorting_model as SM
from variant import UP1, UP5, UP6, UP10, UP11

V_HBW, V_DEG, V_MM, V_BELT = 150.0, 60.0, 120.0, 50.0
T_MIN, T_RFID, T_VAC, T_REL = 0.4, 0.3, 0.5, 0.3
TOL_MM = 1.0
T_ZERO = 0.05             # Upgrade 10: a waypoint with nothing to move is one position check, not T_MIN

# Upgrade 10 (throughput.py): each measure can be switched off alone to measure it
OPT = {"blend": UP10,     # VGR transit legs lowered and blended (vgr_path.blend)
       "split": UP10,     # the VGR hands the mould back when the cookie leaves it; the oven presents in parallel
       "dual": UP10,      # dual-command crane: store the mould coming in, retrieve the next on the same trip
       "zero": UP10}      # a leg with nothing to move costs a position check, not T_MIN


def t_move(d):
    """Nominal time of a move whose slowest axis needs d seconds."""
    return T_ZERO if OPT["zero"] and d <= 1e-9 else max(d, T_MIN)


def timeout(t):
    """A step's watchdog: 1.5 x its nominal time plus 0.5 s."""
    return round(1.5 * t + 0.5, 1)


# ------------------------------------------------------------------ units
UNITS = {
    "crane":     ("hbw", ("Q3", "Q4", "Q5", "Q6", "Q7", "Q8"), "HBW crane: travel, lift, Ausleger"),
    "belt":      ("hbw", ("Q1", "Q2"), "HBW belt and the two RFID read points"),
    "arm":       ("vgr", ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q8"), "VGR arm and vacuum"),
    "door":      ("oven", ("Q5", "Q6", "Q9", "Q13"), "oven door, Ofenschieber and lamp"),
    "sauger":    ("oven", ("Q7", "Q8", "Q11", "Q12"), "oven Sauggreifer"),
    "turntable": ("oven", ("Q1", "Q2", "Q4", "Q14"), "Drehtisch, Saege and Auswerfer"),
    "ovenbelt":  ("oven", ("Q3",), "oven belt"),
    "line":      ("sorting", ("Q1", "Q3", "Q4", "Q5"), "sorting line and ejectors"),
}
UNIT_ORDER = list(UNITS)
# Upgrade 1's central air station replaced the three module compressors.
RETIRED = {"vgr": ("Q7",), "oven": ("Q10",), "sorting": ("Q2",)}
# Upgrade 4 adds two RFID heads on an IO-Link master slice of the HBW node.
RFID = {"RF1": "RFID read point RP1: belt, crane end (IO-Link port 1)",
        "RF2": "RFID read point RP2: belt, VGR hand-over (IO-Link port 2)"}


# Upgrade 5: the sensors virtual commissioning showed were missing (vc.py).
# module -> signal -> (the part it sits on, what it reports)
U5_SENSORS = {
    "oven": {"I10": ("Q13_door_cylinder", "reed switch: oven door open"),
             "I11": ("Q13_door_cylinder", "reed switch: oven door shut"),
             "I12": ("Q12_lower_cylinder", "reed switch: Sauger lowered"),
             "I13": ("Q12_lower_cylinder", "reed switch: Sauger up"),
             "I14": ("Q14_pusher_cylinder", "reed switch: Auswerfer out"),
             "I15": ("Q14_pusher_cylinder", "reed switch: Auswerfer home")},
    "vgr": {"I4": ("vacuum_valve", "vacuum switch: the cup is sealed on a part (-0.3 bar)"),
            "I5": ("air_pressure_switch", "air pressure OK: second contact of the air station's switch")},
} if UP5 else {}


def _sigdesc():
    d = {}
    for m, spec in CT.MODULES.items():
        for pin in spec["st1"] + spec["st2"]:
            if pin[2] and pin[2][0] in "IQAB":
                d[(m, pin[2])] = pin[3]
    for s, t in RFID.items():
        d[("hbw", s)] = t
    for m, sensors in U5_SENSORS.items():
        for s, (_, t) in sensors.items():
            d[(m, s)] = t
    return d


SIG = _sigdesc()


def signals(module):
    s = set(CT.MODULES[module]["st3"].values())
    if module == "hbw":
        s |= set(RFID)
    s |= set(U5_SENSORS.get(module, {}))
    return s


@dataclass
class Step:
    unit: str
    key: str                  # structural id: the same for every binding of a job
    say: str
    out: tuple                # outputs ON during the step, the unit's module
    done: str                 # completion condition, as PLC text
    t: float                  # nominal seconds
    motion: bool
    sig: tuple = ()           # input signals the condition reads
    target: dict = field(default_factory=dict)
    supervised: bool = True   # False: a timed move with no feedback signal
    dist: dict = field(default_factory=dict)   # axis -> travel (mm / deg), for vc.py's ramps

    @property
    def limit(self):
        # Upgrade 6 found the RFID reads had no timeout: a tag that never reads
        # would hold the belt forever. TRC-01 now has a watchdog behind it.
        if self.motion or (UP6 and self.done.startswith("RF2")):
            return timeout(self.t)
        return None


# ------------------------------------------------------------ HBW crane
CV, TR = HM.P["CV_X"], 260.0
FORK_OUT = HM.P["FORK"][1]
ROWS = dict(zip("ABC", HM.P["ROW_Z"]))
# The legs of hbw_model.cycle(), symbolically: every slot uses the same list.
RETRIEVE = [("cv", "tr", 0), ("col", "tr", 0), ("col", "row-20", 0), ("col", "row-20", 1),
            ("col", "row", 1), ("col", "row", 0), ("col", "tr", 0), ("cv", "tr", 0),
            ("cv", "100", 0), ("cv", "100", 1), ("cv", "80", 1), ("cv", "80", 0), ("cv", "tr", 0)]
STORE = [("cv", "tr", 0), ("cv", "80", 0), ("cv", "80", 1), ("cv", "100", 1), ("cv", "100", 0),
         ("cv", "tr", 0), ("col", "tr", 0), ("col", "row", 0), ("col", "row", 1),
         ("col", "row-20", 1), ("col", "row-20", 0), ("col", "tr", 0), ("cv", "tr", 0)]


def _hbw_pose(sym, slot):
    col = HM.P["BAY_X"][int(slot[1]) - 1]
    row = ROWS[slot[0]]
    tv = CV if sym[0] == "cv" else col
    lf = {"tr": TR, "row": row, "row-20": row - 20.0, "100": 100.0, "80": 80.0}[sym[1]]
    return (tv, lf, FORK_OUT if sym[2] else 0.0)


def crane_steps(job, slot):
    sym = RETRIEVE if job == "retrieve" else STORE
    out = []
    for a, b in zip(sym, sym[1:]):
        pa, pb = _hbw_pose(a, slot), _hbw_pose(b, slot)
        moved = [i for i in range(3) if a[i] != b[i]]
        assert len(moved) == 1, "the HBW cycle moves one axis per leg"
        i = moved[0]
        d = pb[i] - pa[i]
        if i == 0:
            out.append(Step("crane", f"travel->{b[0]}", f"travel to the {'conveyor' if b[0] == 'cv' else 'slot column'}",
                            ("Q3",) if d < 0 else ("Q4",), f"|pos_travel - {pb[0]:.0f}| <= {TOL_MM:.0f} (B1/B2)",
                            max(abs(d) / V_HBW, T_MIN), True, ("B1", "B2"), {"travel": pb[0]},
                            dist={"travel": abs(d)}))
        elif i == 1:
            out.append(Step("crane", f"lift->{b[1]}", f"lift to {b[1] if b[1] != 'tr' else 'transit'}",
                            ("Q5",) if d < 0 else ("Q6",), f"|pos_lift - {pb[1]:.0f}| <= {TOL_MM:.0f} (B3/B4)",
                            max(abs(d) / V_HBW, T_MIN), True, ("B3", "B4"), {"lift": pb[1]},
                            dist={"lift": abs(d)}))
        else:
            fwd = d > 0
            out.append(Step("crane", "fork->out" if fwd else "fork->back",
                            "Ausleger out to its front stop" if fwd else "Ausleger back to its rear stop",
                            ("Q7",) if fwd else ("Q8",), "I5" if fwd else "I6",
                            max(abs(d) / V_HBW, T_MIN), True, ("I5",) if fwd else ("I6",)))
    return out


def crane_dual(slot_in, slot_out):
    """Upgrade 10, dual command: the mould coming in is stored and the next
    one retrieved on one trip - the crane goes rack to rack instead of back to
    the conveyor and out again (the classic AS/RS dual-command cycle)."""
    poses = [_hbw_pose(x, slot_in) for x in STORE[:-1]] + [_hbw_pose(x, slot_out) for x in RETRIEVE[1:]]
    names = [x for x in STORE[:-1]] + [x for x in RETRIEVE[1:]]
    out = []
    for (pa, pb, b) in zip(poses, poses[1:], names[1:]):
        moved = [i for i in range(3) if abs(pa[i] - pb[i]) > 1e-9]
        if not moved:                 # the next slot is in the same column: nothing to travel
            out.append(Step("crane", "travel->col", "travel to the next slot's column (same column)", (),
                            f"|pos_travel - {pb[0]:.0f}| <= {TOL_MM:.0f} (B1/B2)", t_move(0.0), True,
                            ("B1", "B2"), {"travel": pb[0]}, dist={"travel": 0.0}))
            continue
        i = moved[0]
        d = pb[i] - pa[i]
        if i == 0:
            out.append(Step("crane", f"travel->{b[0]}", "travel to the next slot's column" if pa[0] != CV and pb[0] != CV
                            else f"travel to the {'conveyor' if b[0] == 'cv' else 'slot column'}",
                            ("Q3",) if d < 0 else ("Q4",), f"|pos_travel - {pb[0]:.0f}| <= {TOL_MM:.0f} (B1/B2)",
                            t_move(abs(d) / V_HBW), True, ("B1", "B2"), {"travel": pb[0]}, dist={"travel": abs(d)}))
        elif i == 1:
            out.append(Step("crane", f"lift->{b[1]}", f"lift to {b[1] if b[1] != 'tr' else 'transit'}",
                            ("Q5",) if d < 0 else ("Q6",), f"|pos_lift - {pb[1]:.0f}| <= {TOL_MM:.0f} (B3/B4)",
                            t_move(abs(d) / V_HBW), True, ("B3", "B4"), {"lift": pb[1]}, dist={"lift": abs(d)}))
        else:
            fwd = d > 0
            out.append(Step("crane", "fork->out" if fwd else "fork->back",
                            "Ausleger out to its front stop" if fwd else "Ausleger back to its rear stop",
                            ("Q7",) if fwd else ("Q8",), "I5" if fwd else "I6",
                            max(abs(d) / V_HBW, T_MIN), True, ("I5",) if fwd else ("I6",)))
    return out


def nearest_free(s, near):
    """The free slot closest in crane time to slot `near` (dual command), or
    the first free one."""
    free = [i for i in range(len(SLOTS)) if _free(s, ("slot", i))]
    if not free or near is None:
        return free[0] if free else None
    return min(free, key=lambda i: (_dual_t(i, near), i))


_DUAL_T = {}


def _dual_t(i, j):
    if (i, j) not in _DUAL_T:
        _DUAL_T[(i, j)] = sum(st.t for st in crane_dual(SLOTS[i], SLOTS[j]))
    return _DUAL_T[(i, j)]


# ------------------------------------------------------------- HBW belt
BELT_RUN = (HM.P["PICK_VGR"] - HM.P["PICK_HBW"]) / V_BELT
RP1_Y, RP2_Y = HM.RFID_Y             # read-head centres along the belt, HBW frame
RP1_FRAC = (RP1_Y - HM.P["PICK_HBW"]) / (HM.P["PICK_VGR"] - HM.P["PICK_HBW"])


def belt_steps(job):
    if job == "belt_fwd":
        return [Step("belt", "run->I3", "belt out to the VGR hand-over; RP1 reads the tag on the fly",
                     ("Q1",), "I3 AND RF1.valid", BELT_RUN, True, ("I3", "RF1")),
                Step("belt", "RP2", "RP2 reads the tag at rest and compares it with the record",
                     (), "RF2.valid AND RF2.tag = record", T_RFID, False, ("RF2",))]
    return [Step("belt", "RP2", "RP2 reads the tag of the mould going in",
                 (), "RF2.valid AND RF2.tag = record", T_RFID, False, ("RF2",)),
            Step("belt", "run->I2", "belt back to the crane; RP1 reads the tag on the fly",
                 ("Q2",), "I2 AND RF1.valid", BELT_RUN, True, ("I2", "RF1"))]


# ------------------------------------------------------------------ VGR
_TOURS = {}


def _tour_keys(tour):
    import vgr_path as VP
    VP.BLEND["on"] = OPT["blend"]
    k = (tour, OPT["blend"])
    if k not in _TOURS:
        _TOURS[k] = VP.plan(list(tour))
    return _TOURS[k]


def vgr_tour(job, a, b):
    """The (station, action, carry, label) tour of a VGR job; labels are
    generic so every binding of the job gives the same step structure."""
    carry = "baked" if job == "bay_to_belt" else "raw"
    return ((a, "pick", carry, "source"), (b, "place", None, "target"))


def arm_steps(job, a, b):
    keys = _tour_keys(vgr_tour(job, a, b))
    out = []
    for i, (p, q) in enumerate(zip(keys, keys[1:]), 1):
        if p["cup"] != q["cup"]:
            on = q["cup"]
            if UP5:     # the vacuum switch I4 supervises both edges
                out.append(Step("arm", f"k{i}:vac", "Q8 vacuum on: the cup seals on the cookie (I4 made)" if on else
                                "Q8 off: the cookie is released (I4 drops)", ("Q8",) if on else (),
                                "I4" if on else "NOT I4", T_VAC if on else T_REL, True, ("I4",)))
            else:
                out.append(Step("arm", f"k{i}:vac", "Q8 vacuum on: the cup seals on the cookie" if on else
                                "Q8 off: the cookie is released", ("Q8",) if on else (), "timer",
                                T_VAC if on else T_REL, False))
            continue
        d = {ax: q[k] - p[k] for ax, k in (("swivel", "sw"), ("plunge", "pz"), ("reach", "rr"))}
        o = []
        if abs(d["plunge"]) > 1e-9:
            o.append("Q1" if d["plunge"] > 0 else "Q2")
        if abs(d["reach"]) > 1e-9:
            o.append("Q4" if d["reach"] > 0 else "Q3")
        if abs(d["swivel"]) > 1e-9:
            o.append("Q5" if d["swivel"] > 0 else "Q6")
        if p["cup"]:
            o.append("Q8")
        t = t_move(max(abs(d["swivel"]) / V_DEG, abs(d["reach"]) / V_MM, abs(d["plunge"]) / V_MM))
        tgt = {"swivel": q["sw"], "plunge": q["pz"], "reach": q["rr"]}
        out.append(Step("arm", f"k{i}:pos", q["say"], tuple(sorted(o)),
                        "|pos - target| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4)",
                        t, True, ("B1", "B2", "B3", "B4", "B5", "B6"), tgt,
                        dist={ax: abs(v) for ax, v in d.items()}))
    return out


def arm_part(job, a, b, part):
    """Upgrade 10: a tour cut where the arm has left its source at the crossing
    height. 'pick' is the source half (the belt is free again after it),
    'place' the rest, home included."""
    steps = arm_steps(job, a, b)
    n_src = 11                  # home + the source visit's ten waypoints (vgr_path.plan)
    cut = next(i for i, st in enumerate(steps) if int(st.key[1:].split(":")[0]) > n_src - 1)
    return steps[:cut] if part == "pick" else steps[cut:]


# ----------------------------------------------------------------- oven
# motion.OVEN_CYCLE row -> (unit, outputs ON, completion, input, supervised).
# Q13 energised = door open (single-acting: it must stay on to hold it open).
OVEN_ROWS = {
    1: ("door", ("Q13",), "timer", (), False),
    2: ("door", ("Q13", "Q6"), "I7", ("I7",), True),
    3: ("door", ("Q13", "Q5"), "I6", ("I6",), True),
    4: ("door", (), "timer", (), False),
    5: ("door", ("Q9",), "timer", (), True),
    6: ("door", ("Q13",), "timer", (), False),
    7: ("door", ("Q13", "Q6"), "I7", ("I7",), True),
    8: ("sauger", ("Q7",), "I8", ("I8",), True),
    9: ("sauger", ("Q11", "Q12"), "timer", (), False),
    10: ("sauger", ("Q11",), "timer", (), False),
    11: ("sauger", ("Q11", "Q8"), "I5", ("I5",), True),
    12: ("sauger", ("Q12",), "timer", (), False),
    13: ("sauger", (), "timer", (), False),
    14: ("door", ("Q13", "Q5"), "I6", ("I6",), True),
    15: ("door", (), "timer", (), False),
    16: ("turntable", ("Q1",), "I4", ("I4",), True),
    17: ("turntable", ("Q4",), "timer", (), True),
    18: ("turntable", ("Q1",), "I2", ("I2",), True),
    19: ("turntable", ("Q14",), "timer", (), False),
    20: ("turntable", (), "timer", (), False),
    21: ("turntable", ("Q2",), "I1", ("I1",), True),
}
PROCESS_ROWS = {5, 17}          # the bake and the saw: dwell, not motion
# Upgrade 5: the reed switches turn every timed pneumatic move into a supervised one
U5_ROWS = {1: "I10", 4: "I11", 6: "I10", 15: "I11", 9: "I12", 10: "I13", 12: "I12", 13: "I13",
           19: "I14", 20: "I15"}
if UP5:
    for _r, _sg in U5_ROWS.items():
        _u, _o, _d, _s, _ = OVEN_ROWS[_r]
        OVEN_ROWS[_r] = (_u, _o, _sg, (_sg,), True)
OVEN_JOBS = {"present": [1, 2], "bake": [3, 4, 5, 6, 7], "to_tt": [8, 9, 10, 11, 12, 13, 14, 15],
             "saw_eject": [16, 17, 18, 19, 20, 21]}


BAKE_DEMO = MO.OVEN_CYCLE[5][0]
BAKE = {"s": BAKE_DEMO}          # the lamp dwell; the throughput study varies it


def oven_steps(job):
    out = []
    for r in OVEN_JOBS[job]:
        dur, _, say = MO.OVEN_CYCLE[r]
        if r == 5:
            dur = BAKE["s"]
        unit, o, done, sig, sup = OVEN_ROWS[r]
        out.append(Step(unit, f"row{r}", say, o, done, dur, r not in PROCESS_ROWS, sig, supervised=sup))
    return out


def ovenbelt_steps():
    return [Step("ovenbelt", "run->I3", "Q3 carries the cookie to I3 and onto the sorting inlet",
                 ("Q3",), "I3", (OM.O["BELT_Y"][1] - OM.O["BELT_Y"][0]) / V_BELT, True, ("I3",))]


# -------------------------------------------------------------- sorting
BAND = {"blau": (0, 645), "rot": (645, 1305), "weiss": (1305, 5000)}   # mV, between the nominal readings


def classify(mv):
    return next(b for b, (lo, hi) in BAND.items() if lo <= mv < hi)


def line_steps(bin_):
    i = SM.COLOURS.index(bin_)
    q = ("Q3", "Q4", "Q5")[i]
    lb = ("I5", "I6", "I7")[i]
    S = SM.S
    return [Step("line", "run->I3", "belt runs the cookie past the colour sensor; A4 sampled until I3",
                 ("Q1",), "I3", (S["AFTER_X"] - S["INLET_X"]) / V_BELT, True, ("I3", "A4")),
            Step("line", "classify", "min(A4) over the pass -> flavour class; compared with the record",
                 ("Q1",), "class = record flavour", 0.1, False, ("A4",)),
            Step("line", "run->eject", "belt runs on; I1 pulses counted to the ejector",
                 ("Q1",), "count(I1) = N_eject", (S["EJECT_X"][i] - S["AFTER_X"]) / V_BELT, True, ("I1",),
                 {"eject_x": S["EJECT_X"][i]}),
            Step("line", "eject", "belt stops; the ejector pushes the cookie into its bay",
                 (q,), f"{lb} broken (the bay's light barrier)", 0.5, True, ("I5", "I6", "I7")),
            Step("line", "eject_back", "ejector back", (), "timer", 0.5, False)]


# --------------------------------------------------------------- homing
HOMING = {
    "crane": [Step("crane", "H:fork", "Ausleger back to its rear stop", ("Q8",), "I6", 115 / V_HBW, True, ("I6",)),
              Step("crane", "H:lift", "lift to the reference switch (direction ASSUMED: down)", ("Q5",), "I4",
                   280 / V_HBW, True, ("I4",)),
              Step("crane", "H:travel", "travel to the reference switch (direction ASSUMED: to the belt)", ("Q4",),
                   "I1", 545 / V_HBW, True, ("I1",))],
    "belt": [Step("belt", "H:check", "occupancy check: I2/I3 against the record", (), "record = I2, I3", 0.1,
                  False, ("I2", "I3"))],
    "arm": [Step("arm", "H:plunge", "plunge up to the reference switch", ("Q1",), "I1", 456 / V_MM, True, ("I1",)),
            Step("arm", "H:reach", "reach back to the reference switch", ("Q3",), "I2", 400 / V_MM, True, ("I2",)),
            Step("arm", "H:swivel", "swivel to the reference switch", ("Q6",), "I3", 260 / V_DEG, True, ("I3",))],
    "door": [Step("door", "H:open", "door open", ("Q13",), "I10" if UP5 else "timer", 1.0, True,
                  ("I10",) if UP5 else (), supervised=UP5),
             Step("door", "H:slider", "Ofenschieber in", ("Q13", "Q5"), "I6", 2.0, True, ("I6",)),
             Step("door", "H:shut", "door shut", (), "I11" if UP5 else "timer", 1.0, True,
                  ("I11",) if UP5 else (), supervised=UP5)],
    "sauger": [Step("sauger", "H:up", "Sauger up, vacuum off", (), "I13" if UP5 else "timer", 0.6, True,
                    ("I13",) if UP5 else (), supervised=UP5),
               Step("sauger", "H:tt", "Sauger to the Drehtisch", ("Q8",), "I5", 2.0, True, ("I5",))],
    "turntable": [Step("turntable", "H:push", "Auswerfer home", (), "I15" if UP5 else "timer", 0.6, True,
                       ("I15",) if UP5 else (), supervised=UP5),
                  Step("turntable", "H:turn", "Drehtisch to the vacuum position", ("Q2",), "I1", 1.5, True, ("I1",))],
    "ovenbelt": [],
    "line": [],
}


# ------------------------------------------------------ the factory state
SLOTS = PL.RACK_SLOTS                                  # A1..C4
MOULD = {s: f"M{i + 1:02d}" for i, s in enumerate(SLOTS)}
INV = PL.initial_inventory()
FLAV = {c: fl for c, (fl, _) in INV.items()}
PRODUCE = [c for c, (_, loc) in INV.items() if loc[0] == "rack"]     # production order
RETURN = [c for c, (_, loc) in INV.items() if loc[0] == "bay"]
NEST_N = 6 if UP1 else 0
BAYS = SM.COLOURS
BAY_CAP = PL.PER_PLACE["bay"]

POLICIES = {
    "prefetch": dict(belt="prefetch", reuse=False, buffer=False,
                     say="the crane fetches the next mould as soon as the crane end of the belt is free"),
    "single":   dict(belt="single", reuse=False, buffer=False,
                     say="one mould on the belt at a time; empty moulds go back into the rack"),
    "reuse":    dict(belt="single", reuse=True, buffer=False,
                     say="+ an empty mould at the hand-over is refilled with a cookie going into the rack"),
    "buffer":   dict(belt="single", reuse=True, buffer=True,
                     say="+ the VGR parks raw cookies in Upgrade 1's buffer while the oven is busy"),
}
# Measured, not assumed (study()): the buffer never shortens the order. With the
# demo bake the single-mould belt channel is the bottleneck; with a long bake
# the oven is, and a raw cookie is already waiting at the hand-over whenever the
# tray frees - parking it costs the VGR a second tour. So production runs
# "reuse"; "buffer" is the proven-safe degraded mode for a held oven.
PLC_POLICY = "reuse"


def initial():
    slots = []
    for s in SLOTS:
        c = next((c for c, (_, loc) in INV.items() if loc == ("rack", s)), None)
        slots.append((MOULD[s], c))
    bays = tuple(tuple(c for c, (_, loc) in INV.items() if loc == ("bay", b)) for b in BAYS)
    stage = tuple("raw" if c in PRODUCE else "return" for c in sorted(INV))
    s = dict(slots=tuple(slots), bin=None, bout=None, nests=(None,) * NEST_N, tray=None, tt=None,
             ovb=None, sin=None, bays=bays, stage=stage, res=(), leave=(), busy=(), run=())
    if OPT["split"]:
        s.update(cup=None, tout=False)     # the cookie on the VGR cup; the oven tray presented
    return s


CIDS = sorted(INV)
CIX = {c: i for i, c in enumerate(CIDS)}
_KEYS = ("slots", "bin", "bout", "nests", "tray", "tt", "ovb", "sin", "bays", "stage", "res", "leave", "busy", "run")


def _keys():
    return _KEYS + (("cup", "tout") if OPT["split"] else ())


def _freeze(s):
    return tuple(s[k] for k in _keys())


def _thaw(t):
    return dict(zip(_keys(), t))


def _stage(s, c):
    return s["stage"][CIX[c]]


def _set_stage(s, c, v):
    st = list(s["stage"]); st[CIX[c]] = v; s["stage"] = tuple(st)


def _free(s, place):
    """Empty and not reserved as a destination."""
    if place in s["res"]:
        return False
    if place == ("tray",) and s.get("cup"):
        return False                  # the cookie on the cup is going there
    k = place[0]
    if k == "slot":
        return s["slots"][place[1]] is None
    if k == "nest":
        return s["nests"][place[1]] is None
    return s[k] is None


def _pending_fill(s):
    """Cookies still to go into the rack, minus moulds already earmarked for them."""
    need = sum(1 for c in RETURN if _stage(s, c) == "return")
    have = sum(1 for m in (s["bin"], s["bout"]) if m and m[2] == "fill")
    have += sum(1 for j in s["run"] if j[0] == "fetch_empty")
    return need - have


# Job tuples: (name, binding, units, src places, dst places)
def _candidates(s, pol):
    """Every job the scan may start, in THE fixed priority order."""
    P = POLICIES[pol]
    L = s["leave"]
    # 1 sort
    if s["sin"] and ("sin",) not in L:
        c = s["sin"]; b = PL.BIN_OF[FLAV[c]]
        room = len(s["bays"][BAYS.index(b)]) + sum(1 for r in s["res"] if r == ("bay", b))
        if room < BAY_CAP:
            yield ("sort", (c, b), ("line",), (("sin",),), (("bay", b),))
    # 2 oven belt -> sorting inlet
    if s["ovb"] and ("ovb",) not in L and _free(s, ("sin",)):
        yield ("ovenbelt", (s["ovb"],), ("ovenbelt",), (("ovb",),), (("sin",),))
    # 3 saw and eject
    if s["tt"] and ("tt",) not in L and _stage(s, s["tt"]) == "baked" and _free(s, ("ovb",)):
        yield ("saw_eject", (s["tt"],), ("turntable",), (("tt",),), (("ovb",),))
    # 4 Sauger: tray -> turntable
    if s["tray"] and ("tray",) not in L and _stage(s, s["tray"]) == "baked" and _free(s, ("tt",)):
        yield ("to_tt", (s["tray"],), ("sauger", "door"), (("tray",),), (("tt",),))
    # 5 bake
    if s["tray"] and ("tray",) not in L and _stage(s, s["tray"]) == "raw":
        yield ("bake", (s["tray"],), ("door",), (("tray",),), ())
    split = OPT["split"]
    cup = s.get("cup")
    if split:
        # 5a the oven presents its tray while the cookie for it is on its way (Upgrade 10)
        coming = cup or ("tray",) in s["res"]
        if s["tray"] is None and not s["tout"] and coming and ("tray",) not in L:
            yield ("present", (cup[0] if cup else "next",), ("door",), (), ())
        # 5b the VGR lays the cookie on the presented tray
        if cup and s["tout"] and s["tray"] is None:
            yield ("place_oven", cup, ("arm", "door"), (), ())
    raw_nests = [(PRODUCE.index(c), i) for i, c in enumerate(s["nests"]) if c and ("nest", i) not in L]
    # with the split the oven only has to be free of a COMMITTED cookie: the VGR may
    # pick the next one while the tray is still busy, and hold it
    oven_free = (not cup and ("tray",) not in s["res"]) if split else _free(s, ("tray",))
    arm_free = not cup
    oven_units = ("arm",) if split else ("arm", "door")
    # 6 buffer -> oven (the buffer is FIFO: it goes before the belt)
    if raw_nests and oven_free and arm_free:
        _, i = min(raw_nests)
        yield ("buf_to_oven", (s["nests"][i], i), oven_units, (("nest", i),), (("tray",),))
    bo = s["bout"]
    raw_out = bo and bo[1] and bo[2] == "out" and ("bout",) not in L
    # 7 belt -> oven
    if raw_out and oven_free and not raw_nests and arm_free:
        yield ("belt_to_oven", (bo[1], bo[0]), ("arm", "belt") if split else ("arm", "belt", "door"),
               (("bout",),), (("tray",),))
    # 8 belt -> buffer, when the oven cannot take it now
    if P["buffer"] and raw_out and not (oven_free and not raw_nests) and arm_free:
        free = [i for i in range(NEST_N) if _free(s, ("nest", i))]
        if free:
            yield ("belt_to_buf", (bo[1], bo[0], free[0]), ("arm", "belt"), (("bout",),), (("nest", free[0]),))
    # 9 bay -> empty mould at the hand-over
    if bo and bo[1] is None and bo[2] == "fill" and ("bout",) not in L and arm_free:
        for bi, b in enumerate(BAYS):
            c = next((c for c in s["bays"][bi] if _stage(s, c) == "return"), None)
            if c:
                yield ("bay_to_belt", (c, b, bo[0]), ("arm", "belt"), (("bay", b),), ())
                break
    # 10 belt back
    if bo and bo[2] == "in" and ("bout",) not in L and _free(s, ("bin",)):
        yield ("belt_back", (bo[0], bo[1]), ("belt",), (("bout",),), (("bin",),))
    bi_ = s["bin"]
    belt_ok = _free(s, ("bin",)) and (P["belt"] == "prefetch" or _free(s, ("bout",)))
    to_make = [c for c in PRODUCE if _stage(s, c) == "raw"
               and any(sl and sl[1] == c for sl in s["slots"])]
    # 10a dual command (Upgrade 10): store the mould coming in, then retrieve the next cookie
    if OPT["dual"] and bi_ and bi_[2] == "in" and ("bin",) not in L and to_make and \
            (P["belt"] == "prefetch" or _free(s, ("bout",))):
        c = to_make[0]
        j = next(i for i, sl in enumerate(s["slots"]) if sl and sl[1] == c)
        i = nearest_free(s, j)
        if i is not None and ("slot", j) not in L:
            yield ("store_retrieve", (bi_[0], bi_[1], SLOTS[i], c, s["slots"][j][0], SLOTS[j]), ("crane", "belt"),
                   (("bin",), ("slot", j)), (("slot", i), ("bin",)))
    # 11 belt forward
    if bi_ and bi_[2] in ("out", "fill") and ("bin",) not in L and _free(s, ("bout",)):
        yield ("belt_fwd", (bi_[0], bi_[1]), ("belt",), (("bin",),), (("bout",),))
    # 12 store
    if bi_ and bi_[2] == "in" and ("bin",) not in L:
        free = [i for i in range(len(SLOTS)) if _free(s, ("slot", i))]
        if free:
            yield ("store", (bi_[0], bi_[1], SLOTS[free[0]]), ("crane", "belt"), (("bin",),), (("slot", free[0]),))
    # 13 fetch an empty mould for a cookie going in
    fetch_ok = not (P["reuse"] and to_make)       # with reuse, a returning mould will serve
    if belt_ok and fetch_ok and _pending_fill(s) > 0:
        i = next((i for i, sl in enumerate(s["slots"]) if sl and sl[1] is None and ("slot", i) not in L), None)
        if i is not None:
            yield ("fetch_empty", (s["slots"][i][0], SLOTS[i]), ("crane", "belt"), (("slot", i),), (("bin",),))
    # 14 retrieve the next cookie in production order
    if belt_ok and to_make:
        c = to_make[0]
        i = next(i for i, sl in enumerate(s["slots"]) if sl and sl[1] == c)
        if ("slot", i) not in L:
            yield ("retrieve", (c, s["slots"][i][0], SLOTS[i]), ("crane", "belt"), (("slot", i),), (("bin",),))


def dispatch(s, pol):
    """One PLC scan: start every job whose units are idle, in priority order,
    until nothing more can start."""
    s = dict(s)
    while True:
        started = False
        for job in _candidates(s, pol):
            if any(u in s["busy"] for u in job[2]):
                continue
            s["busy"] = tuple(sorted(s["busy"] + job[2]))
            s["res"] = tuple(sorted(s["res"] + job[4]))
            s["leave"] = tuple(sorted(s["leave"] + job[3]))
            s["run"] = tuple(sorted(s["run"] + (job,), key=repr))
            started = True
            break
        if not started:
            return s


def _rm(t, xs):
    t = list(t)
    for x in xs:
        t.remove(x)
    return tuple(t)


def complete(s, job, pol):
    """Apply a finished job's effect and release its units."""
    s = dict(s)
    name, b = job[0], job[1]
    P = POLICIES[pol]
    s["busy"] = _rm(s["busy"], job[2])
    s["res"] = _rm(s["res"], job[4])
    s["leave"] = _rm(s["leave"], job[3])
    s["run"] = _rm(s["run"], (job,))

    def mould_after_pick(m):
        s_ = dict(s)
        return (m, None, "fill" if P["reuse"] and _pending_fill(s_) > 0 else "in")

    if name == "retrieve":
        c, m, slot = b
        sl = list(s["slots"]); sl[SLOTS.index(slot)] = None; s["slots"] = tuple(sl)
        s["bin"] = (m, c, "out")
    elif name == "fetch_empty":
        m, slot = b
        sl = list(s["slots"]); sl[SLOTS.index(slot)] = None; s["slots"] = tuple(sl)
        s["bin"] = (m, None, "fill")
    elif name == "belt_fwd":
        s["bout"], s["bin"] = s["bin"], None
    elif name == "belt_back":
        s["bin"], s["bout"] = s["bout"], None
    elif name == "store":
        m, c, slot = b
        sl = list(s["slots"]); sl[SLOTS.index(slot)] = (m, c); s["slots"] = tuple(sl)
        s["bin"] = None
        if c:
            _set_stage(s, c, "stored")
    elif name == "store_retrieve":
        m, c, slot, c2, m2, slot2 = b
        sl = list(s["slots"]); sl[SLOTS.index(slot)] = (m, c); sl[SLOTS.index(slot2)] = None
        s["slots"] = tuple(sl)
        if c:
            _set_stage(s, c, "stored")
        s["bin"] = (m2, c2, "out")
    elif name in ("belt_to_oven", "belt_to_buf"):
        c, m = b[0], b[1]
        s["bout"] = mould_after_pick(m)
        if name == "belt_to_oven":
            if OPT["split"]:
                s["cup"] = (c, "belt")
            else:
                s["tray"] = c
        else:
            n = list(s["nests"]); n[b[2]] = c; s["nests"] = tuple(n)
    elif name == "buf_to_oven":
        c, i = b
        n = list(s["nests"]); n[i] = None; s["nests"] = tuple(n)
        if OPT["split"]:
            s["cup"] = (c, f"buf_{i + 1}")
        else:
            s["tray"] = c
    elif name == "present":
        s["tout"] = True
    elif name == "place_oven":
        s["tray"], s["cup"] = s["cup"][0], None
    elif name == "bay_to_belt":
        c, bay, m = b
        bays = list(s["bays"]); k = BAYS.index(bay)
        bays[k] = tuple(x for x in bays[k] if x != c); s["bays"] = tuple(bays)
        s["bout"] = (m, c, "in")
        _set_stage(s, c, "returning")
    elif name == "bake":
        _set_stage(s, b[0], "baked")
    elif name == "to_tt":
        s["tt"], s["tray"] = s["tray"], None
        if "tout" in s:
            s["tout"] = False           # rows 14-15: slider in, door shut
    elif name == "saw_eject":
        s["ovb"], s["tt"] = s["tt"], None
        _set_stage(s, b[0], "baked")
    elif name == "ovenbelt":
        s["sin"], s["ovb"] = s["ovb"], None
    elif name == "sort":
        c, bay = b
        bays = list(s["bays"]); k = BAYS.index(bay)
        bays[k] = bays[k] + (c,); s["bays"] = tuple(bays)
        s["sin"] = None
        _set_stage(s, c, "done")
    else:
        raise ValueError(name)
    return s


def _where(s):
    """cookie -> place, mould -> place: each must be in exactly one."""
    cw, mw = {}, {}

    def put(d, k, v):
        if k in d:
            raise AssertionError(f"{k} is in two places: {d[k]} and {v}")
        d[k] = v
    for i, sl in enumerate(s["slots"]):
        if sl:
            put(mw, sl[0], ("slot", SLOTS[i]))
            if sl[1]:
                put(cw, sl[1], ("slot", SLOTS[i]))
    for k in ("bin", "bout"):
        if s[k]:
            put(mw, s[k][0], (k,))
            if s[k][1]:
                put(cw, s[k][1], (k,))
    for i, c in enumerate(s["nests"]):
        if c:
            put(cw, c, ("nest", i))
    for k in ("tray", "tt", "ovb", "sin"):
        if s[k]:
            put(cw, s[k], (k,))
    if s.get("cup"):
        put(cw, s["cup"][0], ("cup",))
    for bi, b in enumerate(BAYS):
        for c in s["bays"][bi]:
            put(cw, c, ("bay", b))
    return cw, mw


def invariants(s):
    cw, mw = _where(s)
    bad = []
    if len(cw) != PL.N_COOKIES:
        bad.append(f"{len(cw)} cookies, must be {PL.N_COOKIES}")
    if len(mw) != len(SLOTS):
        bad.append(f"{len(mw)} moulds, must be {len(SLOTS)}")
    for bi, b in enumerate(BAYS):
        if len(s["bays"][bi]) > BAY_CAP:
            bad.append(f"bay {b} holds {len(s['bays'][bi])} > {BAY_CAP}")
    return bad


def goal(s):
    if s["run"] or s["bin"] or s["bout"] or any(s["nests"]) or s["tray"] or s["tt"] or s["ovb"] or s["sin"] or \
            s.get("cup"):
        return False
    for c in PRODUCE:
        if _stage(s, c) != "done" or c not in s["bays"][BAYS.index(PL.BIN_OF[FLAV[c]])]:
            return False
    return all(_stage(s, c) == "stored" for c in RETURN)


def explore(pol, limit=2_000_000):
    """EVERY completion order - i.e. every possible timing of every job - from
    the start state. Returns (states, fails, deadlock trace or None)."""
    s0 = dispatch(initial(), pol)
    f0 = _freeze(s0)
    parent = {f0: None}
    stack, fails, n = [f0], [], 0
    while stack:
        f = stack.pop()
        n += 1
        if n > limit:
            fails.append(f"state limit {limit} reached")
            break
        s = _thaw(f)
        bad = invariants(s)
        if bad:
            fails.append(f"{pol}: " + "; ".join(bad))
            return n, fails, _trace(parent, f)
        if not s["run"]:
            if not goal(s):
                fails.append(f"{pol}: DEADLOCK - {describe(s)}")
                return n, fails, _trace(parent, f)
            continue
        for job in s["run"]:
            g = _freeze(dispatch(complete(s, job, pol), pol))
            if g not in parent:
                parent[g] = (f, job)
                stack.append(g)
    return n, fails, None


def describe(s):
    """A stuck state in words: what stands where on the belt."""
    def m(x):
        if not x:
            return "empty"
        what = f"with {x[1]}" if x[1] else "empty"
        return f"mould {x[0]} {what}, going {'out' if x[2] == 'out' else 'back in'}"
    return (f"crane end of the belt: {m(s['bin'])}; VGR hand-over: {m(s['bout'])}. The belt can only "
            "move one way at a time and each move needs the other end free - a circular wait on one belt")


def _trace(parent, f):
    out = []
    while parent.get(f):
        f, job = parent[f]
        out.append(f"{job[0]}{job[1]}")
    return list(reversed(out))[-14:]


# ------------------------------------------------------------ job steps
def job_steps(job):
    """The steps of one job instance, in execution order (segments of several
    units run one after another)."""
    name, b = job[0], job[1]
    if name == "retrieve":
        return crane_steps("retrieve", b[2])
    if name == "fetch_empty":
        return crane_steps("retrieve", b[1])
    if name == "store":
        return crane_steps("store", b[2])
    if name == "store_retrieve":
        return crane_dual(b[2], b[5])
    if name in ("belt_fwd", "belt_back"):
        return belt_steps(name)
    if OPT["split"]:
        if name == "belt_to_oven":
            return arm_part(name, "belt", "oven", "pick")
        if name == "buf_to_oven":
            return arm_part(name, f"buf_{b[1] + 1}", "oven", "pick")
        if name == "present":
            return oven_steps("present")
        if name == "place_oven":
            return arm_part("belt_to_oven" if b[1] == "belt" else "buf_to_oven", b[1], "oven", "place")
    if name == "belt_to_oven":
        return oven_steps("present") + arm_steps(name, "belt", "oven")
    if name == "buf_to_oven":
        return oven_steps("present") + arm_steps(name, f"buf_{b[1] + 1}", "oven")
    if name == "belt_to_buf":
        return arm_steps(name, "belt", f"buf_{b[2] + 1}")
    if name == "bay_to_belt":
        return arm_steps(name, f"bay_{b[1]}", "belt")
    if name in ("bake", "to_tt", "saw_eject"):
        return oven_steps(name)
    if name == "ovenbelt":
        return ovenbelt_steps()
    if name == "sort":
        return line_steps(b[1])
    raise ValueError(name)


def _dur(job):
    return sum(st.t for st in job_steps(job))


def simulate(pol):
    """Nominal timing: the same dispatcher, jobs finishing at their step-sum time.
    Returns the Gantt bars, the event log for traceability and the makespan."""
    s = dispatch(initial(), pol)
    t, bars, events, ends = 0.0, [], [], {}

    def start_new(s, t):
        for job in s["run"]:
            if job not in ends:
                d = _dur(job)
                ends[job] = t + d
                steps, tt = [], t
                for st in job_steps(job):
                    steps.append([st.unit, st.key, round(tt, 2), round(tt + st.t, 2)])
                    tt += st.t
                bars.append({"job": job[0], "bind": [str(x) for x in job[1]], "units": list(job[2]),
                             "t0": round(t, 2), "t1": round(t + d, 2), "steps": steps})
                events.append((round(t, 2), "start", job))
    start_new(s, t)
    while s["run"]:
        job = min(s["run"], key=lambda j: (ends[j], UNIT_ORDER.index(j[2][0])))
        t = ends.pop(job)
        events.append((round(t, 2), "end", job))
        s = dispatch(complete(s, job, pol), pol)
        start_new(s, t)
    if not goal(s):
        raise AssertionError(f"{pol}: the timed run did not finish the order")
    return bars, events, round(t, 1), s


# ---------------------------------------------------------- traceability
def trace(events):
    """Per cookie: its record, built from the read points and the job events
    exactly as the PLC would write it."""
    rec = {c: {"id": c, "flavour": FLAV[c], "kind": "production" if c in PRODUCE else "return",
               "mould": None, "slot_from": None, "slot_to": None, "reads": [], "t": {}}
           for c in CIDS}
    for i, sl in enumerate(initial()["slots"]):
        if sl[1]:
            rec[sl[1]]["mould"], rec[sl[1]]["slot_from"] = sl[0], SLOTS[i]
    mould_of = {}
    for t, what, job in events:
        name, b = job[0], job[1]
        if name == "retrieve" and what == "end":
            c, m, slot = b
            mould_of[m] = c
            rec[c]["t"]["retrieved"] = t
        if name == "belt_fwd":
            c = b[1]
            if c and what == "end":
                rec[c]["reads"] += [["RP1", b[0], round(t - T_RFID - (1 - RP1_FRAC) * BELT_RUN, 2)],
                                    ["RP2", b[0], t]]
        if name in ("belt_to_oven", "belt_to_buf") and what == "end":
            rec[b[0]]["t"]["off_mould"] = t
        if name == "belt_to_buf" and what == "end":
            rec[b[0]]["t"]["buffered"] = t
            rec[b[0]]["nest"] = b[2] + 1
        if name == "bake":
            rec[b[0]]["t"]["bake_start" if what == "start" else "bake_end"] = t
        if name == "sort" and what == "end":
            c, bay = b
            mv = PL.FLAVOURS[FLAV[c]]["mV"]
            rec[c]["colour_mV"] = mv
            rec[c]["class"] = classify(mv)
            rec[c]["bin"] = bay
            rec[c]["verified"] = classify(mv) == PL.BIN_OF[FLAV[c]] == bay
            rec[c]["t"]["sorted"] = t
        if name == "bay_to_belt" and what == "end":
            c, bay, m = b
            rec[c]["mould"] = m
            rec[c]["t"]["picked_from_bay"] = t
        if name == "belt_back" and what == "end" and b[1]:
            rec[b[1]]["reads"] += [["RP2", b[0], round(t - BELT_RUN, 2)],
                                   ["RP1", b[0], round(t - (1 - RP1_FRAC) * BELT_RUN, 2)]]
        if name == "store" and what == "end" and b[1]:
            rec[b[1]]["slot_to"] = b[2]
            rec[b[1]]["t"]["stored"] = t
        if name == "store_retrieve" and what == "end":
            m, c, slot, c2, m2, slot2 = b
            legs = crane_dual(slot, slot2)
            if c:                            # stored when the store half of the trip is done
                rec[c]["slot_to"] = slot
                rec[c]["t"]["stored"] = round(t - sum(st.t for st in legs[len(STORE) - 2:]), 2)
            mould_of[m2] = c2
            rec[c2]["t"]["retrieved"] = t
    for r in rec.values():
        if "bake_start" in r["t"]:
            r["bake_s"] = BAKE["s"]            # the lamp dwell inside the bake job
    return rec


def check_trace(rec):
    fails = []
    for c, r in rec.items():
        if r["kind"] == "production":
            need = ("retrieved", "off_mould", "bake_start", "bake_end", "sorted")
            miss = [k for k in need if k not in r["t"]]
            if miss:
                fails.append(f"TRACE {c}: missing {miss}")
            if [x[0] for x in r["reads"]] != ["RP1", "RP2"] or any(x[1] != r["mould"] for x in r["reads"]):
                fails.append(f"TRACE {c}: read points {r['reads']} do not match mould {r['mould']}")
            if not r.get("verified"):
                fails.append(f"TRACE {c}: colour check failed ({r.get('colour_mV')} mV -> {r.get('class')})")
            ts = [r["t"][k] for k in need if k in r["t"]]
            if ts != sorted(ts):
                fails.append(f"TRACE {c}: events out of order {r['t']}")
        else:
            if "stored" not in r["t"] or not r["slot_to"]:
                fails.append(f"TRACE {c}: never stored")
            if [x[0] for x in r["reads"]] != ["RP2", "RP1"]:
                fails.append(f"TRACE {c}: read points {r['reads']} (want RP2 then RP1)")
    return fails


# ------------------------------------------------------ state machines
JOB_UNITS = {}          # job name -> the units whose segments it has, in order


def _representatives():
    """One binding per job type, plus every binding the orchestrator can use
    (to prove they all share one step structure)."""
    reps = {"retrieve": [("retrieve", ("c", "M", s)) for s in SLOTS],
            "fetch_empty": [("fetch_empty", ("M", s)) for s in SLOTS],
            "store": [("store", ("M", "c", s)) for s in SLOTS],
            "belt_fwd": [("belt_fwd", ("M", "c"))], "belt_back": [("belt_back", ("M", "c"))],
            "belt_to_oven": [("belt_to_oven", ("c", "M"))],
            "bay_to_belt": [("bay_to_belt", ("c", b, "M")) for b in BAYS],
            "bake": [("bake", ("c",))], "to_tt": [("to_tt", ("c",))], "saw_eject": [("saw_eject", ("c",))],
            "ovenbelt": [("ovenbelt", ("c",))], "sort": [("sort", ("c", b)) for b in BAYS]}
    if NEST_N:
        reps["belt_to_buf"] = [("belt_to_buf", ("c", "M", i)) for i in range(NEST_N)]
        reps["buf_to_oven"] = [("buf_to_oven", ("c", i)) for i in range(NEST_N)]
    if OPT["split"]:
        reps["present"] = [("present", ("c",))]
        reps["place_oven"] = [("place_oven", ("c", "belt"))] + [("place_oven", ("c", f"buf_{i + 1}"))
                                                                  for i in range(NEST_N)]
    if OPT["dual"]:
        reps["store_retrieve"] = [("store_retrieve", ("M", "c", a, "c2", "M2", b)) for a in SLOTS for b in SLOTS
                                  if a != b]
    return reps


def sfc():
    """Per unit: its states (homing, READY, every job segment's steps, FAULT,
    ESTOP) and its transitions."""
    units = {u: {"states": [], "edges": [], "jobs": []} for u in UNITS}
    for u in UNITS:
        S = units[u]["states"]
        S.append({"id": "INIT", "say": "power-up: all outputs off", "out": []})
        prev = "INIT"
        for st in HOMING[u]:
            sid = st.key
            S.append(_sdict(sid, st))
            units[u]["edges"].append([prev, sid, "Enable" if prev == "INIT" else "done"])
            prev = sid
        S.append({"id": "READY", "say": "homed, waiting for a job", "out": []})
        units[u]["edges"].append([prev, "READY", "Enable" if prev == "INIT" else "done"])
    for name, binds in _representatives().items():
        steps = job_steps(binds[0])
        for u in dict.fromkeys(st.unit for st in steps):
            seg = [st for st in steps if st.unit == u]
            units[u]["jobs"].append(name)
            prev = "READY"
            for k, st in enumerate(seg):
                sid = f"{name}.{k + 1:02d}"
                units[u]["states"].append(_sdict(sid, st, job=name))
                units[u]["edges"].append([prev, sid, f"Job = {name}" if prev == "READY" else "done"])
                prev = sid
            units[u]["edges"].append([prev, "READY", "done"])
    for u, d in units.items():
        d["states"] += [{"id": "FAULT", "say": "a step timed out: outputs off, alarm raised", "out": []},
                        {"id": "ESTOP", "say": "safety relay dropped: outputs off (K1/K2 open)", "out": []}]
        for st in d["states"]:
            if st.get("limit"):
                d["edges"].append([st["id"], "FAULT", f"T > {st['limit']} s"])
            if st["id"] != "ESTOP":
                d["edges"].append([st["id"], "ESTOP", "NOT Enable"])
        first = HOMING[u][0].key if HOMING[u] else "READY"
        d["edges"] += [["FAULT", first, "Ack AND Enable"], ["ESTOP", "INIT", "Reset (S3) AND Enable"]]
    return units


def _sdict(sid, st, job=None):
    return {"id": sid, "say": st.say, "out": list(st.out), "done": st.done, "t": round(st.t, 2),
            "limit": st.limit, "supervised": st.supervised, "motion": st.motion, "job": job,
            "sig": list(st.sig)}


def check_sfc(units):
    fails = []
    pairs = {}
    for m, spec in CT.MODULES.items():
        pairs[m] = [(r[1], r[2]) for r in spec["relays"].values() if r]
    owned = {}
    for u, (m, outs, _) in UNITS.items():
        for q in outs:
            if (m, q) in owned:
                fails.append(f"OUTPUT {m}.{q} owned by both {owned[(m, q)]} and {u}")
            owned[(m, q)] = u
    for u, d in units.items():
        m, outs, _ = UNITS[u]
        ids = [s["id"] for s in d["states"]]
        if len(ids) != len(set(ids)):
            fails.append(f"SFC {u}: duplicate state ids")
        adj = {}
        for a, b, _ in d["edges"]:
            adj.setdefault(a, set()).add(b)
        for sid in ids:
            seen, stack = set(), [sid]
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                stack += list(adj.get(x, ()))
            if "READY" not in seen:
                fails.append(f"SFC {u}: state {sid} has no path to READY")
            if sid != "ESTOP" and "ESTOP" not in adj.get(sid, ()):
                fails.append(f"SFC {u}: state {sid} has no E-stop transition")
        for s in d["states"]:
            if s["id"] in ("INIT", "READY", "FAULT", "ESTOP") and s["out"]:
                fails.append(f"SFC {u}: outputs on in {s['id']}")
            if s.get("motion") and not s.get("limit"):
                fails.append(f"SFC {u}: motion step {s['id']} has no timeout")
    # every concrete binding: own outputs only, never both directions, known signals
    for name, binds in _representatives().items():
        shape = None
        for job in binds:
            steps = job_steps(job)
            sh = [(st.unit, st.key) for st in steps]
            if shape is None:
                shape = sh
            elif sh != shape:
                fails.append(f"JOB {name}: binding {job[1]} has a different step structure")
            for st in steps:
                m = UNITS[st.unit][0]
                for q in st.out:
                    if q not in UNITS[st.unit][1]:
                        fails.append(f"JOB {name}: {st.unit} drives {m}.{q}, not its own")
                    if q in RETIRED.get(m, ()):
                        fails.append(f"JOB {name}: drives retired {m}.{q}")
                for a, b in pairs[m]:
                    if a in st.out and b in st.out:
                        fails.append(f"JOB {name} '{st.say}': {m}.{a} and {m}.{b} both on")
                for sg in st.sig:
                    if sg not in signals(m):
                        fails.append(f"JOB {name}: {m}.{sg} is not in the Belegungsplan")
                if st.motion and st.limit is None:
                    fails.append(f"JOB {name}: motion '{st.say}' has no timeout")
    return fails


# ----------------------------------------------------------------- alarms
def alarms(units):
    """Every supervised motion's watchdog becomes one alarm per (unit, signal),
    plus the system and traceability alarms."""
    out, seen = [], {}
    pre = {"crane": "HBW-C", "belt": "HBW-B", "arm": "VGR-A", "door": "OVN-D", "sauger": "OVN-S",
           "turntable": "OVN-T", "ovenbelt": "OVN-B", "line": "SRT-L"}
    for u, d in units.items():
        m = UNITS[u][0]
        for s in d["states"]:
            if not s.get("limit") or not s.get("supervised"):
                continue
            key = (u, s["done"] if not s["done"].startswith("|pos") else s["done"].split("(")[-1])
            if key in seen:
                seen[key]["steps"].append(s["id"])
                if UP10:
                    # Upgrade 10's zero-length legs have a 0.6 s watchdog; the alarm's
                    # limit is the longest of its steps, not the first one's
                    seen[key]["limit"] = max(seen[key]["limit"], s["limit"])
                continue
            sig = [x for x in s["sig"] if x[0] in "IB"]
            desc = "; ".join(f"{x} {SIG.get((m, x), '')}" for x in sig)
            enc = s["done"].startswith("|pos")
            a = {"code": f"{pre[u]}{len([k for k in seen if k[0] == u]) + 1:02d}", "unit": u,
                 "text": f"{UNITS[u][2]}: target not reached in time" if enc else
                         f"{UNITS[u][2]}: {s['done']} not reached in time",
                 "cause": (f"counter {desc} stopped short: motor or its relay, the encoder, or a jam"
                           if enc else f"{desc}: the drive did not arrive, or the switch/barrier failed"),
                 "reaction": "the unit drops its outputs and goes to FAULT; no new job is given to it; "
                             "the other units finish their current step and hold",
                 "recovery": "clear the cause; acknowledge on the HMI; the unit re-homes, and the job "
                             "restarts from its first step (the place records say where the cookie is)",
                 "limit": s["limit"], "steps": [s["id"]]}
            seen[key] = a
            out.append(a)
    sysal = [
        ("SYS-01", "E-stop pressed (ES1, ES2 or ES3)", "a person pressed it, or a channel fault",
         "K0 drops K1/K2: actuator 24 V off, Y1 vents the air; every unit to ESTOP",
         "release the E-stop, reset with S3, then every unit re-homes"),
        ("SYS-02", "guard door open (SA, SB or SC)", "door opened while the cell was running",
         "as SYS-01; the door stays unlocked only at standstill", "close the door, reset with S3, re-home"),
        ("SYS-03", "safety relay feedback fault (EDM)", "K1 or K2 contact welded, or wiring",
         "K0 will not re-enable", "replace the contactor; test the E-stop chain before production"),
        ("SYS-04", "remote I/O node lost (Modbus TCP watchdog)", "Ethernet cable, switch port or node supply",
         "the node sets its outputs to 0 (its watchdog); the orchestrator holds every unit",
         "restore the link; acknowledge; the units on that node re-home"),
        ("SYS-05", "air pressure low at the air station" + (" (vgr I5)" if UP5 else " (NO SENSOR before Upgrade 5)"),
         "compressor fault or a leak",
         "hold every pneumatic step before it starts", "restore pressure; acknowledge"),
        ("TRC-01", "RP1/RP2: no tag read", "tag missing or damaged, head fault, mould misplaced",
         "belt stops; the job holds", "check the mould; re-read, or enter the ID by hand with the operator's name logged"),
        ("TRC-02", "RP2: tag differs from the record", "wrong mould on the belt: the record and the rack disagree",
         "the VGR does not pick; the belt holds", "inspect; correct the record at the HMI (logged) or remove the mould"),
        ("TRC-03", "A4: flavour class differs from the record", "wrong cookie, or the sensor drifted",
         "the ejector does not fire; the line stops with the cookie before the bays",
         "remove the cookie by hand; its record is closed as 'rejected'; recalibrate A4 if it repeats"),
        ("ORD-01", "bay full (4 cookies)", "the bay was not emptied", "sorting holds; the oven belt stops upstream",
         "empty the bay and confirm on the HMI"),
    ]
    if UP5:
        sysal.append(("VGR-V01", "vacuum lost while carrying (vgr I4 dropped)", "cup seal broke, hose off, or air lost",
                      "the arm stops where it is; Q8 stays on; the cookie is down somewhere under the arm",
                      "the operator puts the cookie back at the job's source and confirms; the arm retraces its "
                      "tour to transit height, re-homes, and the job restarts"))
    if UP11:
        sysal += [
            ("SEC-01", "output read-back differs from the program's image", "a write the program did not make "
             "(rogue client, spoofed master) or a node fault", "every unit holds; the node's outputs are forced off; "
             "the firewall log is pulled", "find the source in the firewall log; acknowledge with the security role"),
            ("SEC-02", "a sensor arrived faster than the plant can move", "a spoofed reply, or a sensor wired wrong",
             "the unit goes to FAULT at once, before it acts on the signal", "inspect the sensor and the node; acknowledge"),
            ("SEC-03", "the running program's hash differs from the signed manifest", "an unauthorised download",
             "the PLC does not leave INIT", "reload the signed program from the engineering station (maintenance mode)"),
            ("SEC-04", "the cell firewall dropped a packet on a conduit", "a device outside its allow-list: scan, "
             "misconfiguration or an attack", "none on the machine: logged and shown", "review the log entry"),
        ]
    for code, text, cause, react, rec in sysal:
        out.append({"code": code, "unit": "system", "text": text, "cause": cause, "reaction": react,
                    "recovery": rec, "limit": None, "steps": []})
    return out


def unsupervised(units):
    """Timed moves with no feedback signal in the Belegungsplan."""
    out = []
    for u, d in units.items():
        for s in d["states"]:
            if s.get("motion") and not s.get("supervised"):
                out.append({"unit": u, "state": s["id"], "say": s["say"], "out": s["out"]})
    return out


# ------------------------------------------------------------- jogging
JOG = [
    ("crane", "travel", "Q3/Q4", "Ausleger at its rear stop (I6)", "hbw_model.pose_allowed"),
    ("crane", "lift", "Q5/Q6", "Ausleger back, or at a column inside the slot band", "hbw_model.fork_allowed"),
    ("crane", "Ausleger", "Q7/Q8", "only at a rack column or the conveyor, at a slot height", "hbw_model.fork_allowed"),
    ("belt", "belt", "Q1/Q2", "crane Ausleger back (I6), VGR cup not at the belt", "vgr_path plunge band 'belt'"),
    ("arm", "swivel", "Q5/Q6", "plunge at transit height (500 mm) - swing only up high", "vgr_path.plan legs"),
    ("arm", "plunge", "Q1/Q2", "inside the station's plunge band", "factory_layout.vgr_plunge_allowed"),
    ("arm", "reach", "Q3/Q4", "descent reach of the station below transit", "vgr_path.descent_reach"),
    ("door", "Ofenschieber", "Q5/Q6", "door open (Q13 on)", "oven_model.pose_allowed (door/slider)"),
    ("door", "door", "Q13", "Ofenschieber fully in (I6) or fully out (I7)", "oven_model.pose_allowed"),
    ("sauger", "Sauger travel", "Q7/Q8", "Sauger up (Q12 off)", "oven_model.pose_allowed (Q12 at a stop)"),
    ("sauger", "lower", "Q12", "Sauger at a stop (I8 or I5)", "oven_model.pose_allowed (Q12 at a stop)"),
    ("turntable", "turn", "Q1/Q2", "Auswerfer home, Sauger up", "oven_model.pose_allowed"),
    ("turntable", "Auswerfer", "Q14", "Drehtisch at the belt (I2)", "oven_model.pose_allowed (Auswerfer at the belt)"),
    ("ovenbelt", "belt", "Q3", "Auswerfer home", "-"),
    ("line", "belt", "Q1", "no ejector out", "sorting_model.pose_allowed"),
    ("line", "ejectors", "Q3/Q4/Q5", "belt stopped, one ejector at a time", "sorting_model.pose_allowed"),
]


def check_jog():
    fails = []
    for u, (m, outs, _) in UNITS.items():
        for q in outs:
            if q in ("Q8",) and u == "arm":
                continue                      # vacuum, not an axis
            if q in ("Q9", "Q4", "Q11") and u in ("door", "turntable", "sauger"):
                continue                      # lamp, saw, vacuum: not jogged
            if not any(j[0] == u and q in j[2].split("/") for j in JOG) and \
               not any(j[0] == u and q == j[2] for j in JOG):
                fails.append(f"JOG {u}.{q}: no jog rule")
    return fails


# ----------------------------------------------------- IEC 61131-3 source
def st_source(units):
    """One FUNCTION_BLOCK per unit plus the orchestrator PROGRAM, as text.
    Positioning targets are table lookups, so one program serves every slot,
    station and bay; the watchdog is one TON restarted on every step change."""
    files = {}
    for u, d in units.items():
        m, outs, label = UNITS[u]
        ins = sorted({x for s in d["states"] for x in s.get("sig", [])})
        num = {}
        n = 10
        for s in d["states"]:
            if s["id"] == "INIT":
                num[s["id"]] = 0
            elif s["id"] == "READY":
                num[s["id"]] = 100
            elif s["id"] == "FAULT":
                num[s["id"]] = 910
            elif s["id"] == "ESTOP":
                num[s["id"]] = 900
            elif s["id"].startswith("H:"):
                num[s["id"]] = n; n += 1
        base = 1000
        for j in d["jobs"]:
            k = 0
            for s in d["states"]:
                if s.get("job") == j:
                    num[s["id"]] = base + k; k += 1
            base += 1000
        nxt = {a: b for a, b, c in d["edges"] if c in ("done", "Enable") and b not in ("FAULT", "ESTOP")}
        L = [f"(* {label} - generated by stf-cad/hbw/control.py from the proven motion; do not edit *)",
             f"FUNCTION_BLOCK FB_{u.capitalize()}",
             "VAR_INPUT",
             "    Enable : BOOL;          (* K0 safety relay OK AND mode = AUTO *)",
             "    Ack    : BOOL;          (* HMI acknowledge, rising edge *)",
             "    Reset  : BOOL;          (* S3, falling edge, via the safety relay *)",
             "    Job    : INT;           (* 0 = none; see the job table below *)",
             "    Arg    : INT;           (* slot / station / bay index *)"]
        for x in ins:
            if x.startswith("B"):
                continue
            L.append(f"    {x:6s} : BOOL;          (* {SIG.get((m, x), '')} *)")
        if any(x.startswith("B") for x in ins):
            L.append("    Pos    : ARRAY[1..3] OF REAL;  (* axis positions from the encoder counters *)")
        L += ["END_VAR", "VAR_OUTPUT"]
        for q in outs:
            L.append(f"    {q:6s} : BOOL;          (* {SIG.get((m, q), '')} *)")
        L += ["    Busy, Done, Fault : BOOL;", "    Alarm  : INT;", "END_VAR", "VAR",
              "    Step, Prev : INT := 0;", "    Wd : TON;               (* step watchdog *)",
              "    Limit : TIME;", "END_VAR", ""]
        L.append("(* every scan: outputs off unless the active step sets them *)")
        L.append(" ".join(f"{q} := FALSE;" for q in outs))
        L += ["IF NOT Enable AND Step <> 900 THEN Step := 900; END_IF", "",
              "Wd(IN := (Step = Prev), PT := Limit);", "Prev := Step;",
              "IF Wd.Q AND Limit > T#0MS THEN Alarm := Step; Step := 910; END_IF", "",
              "CASE Step OF"]
        jobno = {j: i + 1 for i, j in enumerate(d["jobs"])}
        for s in d["states"]:
            sid = s["id"]
            L.append(f"  {num[sid]}: (* {sid}: {s['say']} *)")
            if sid == "INIT":
                L.append(f"      Limit := T#0MS; IF Enable THEN Step := {num[nxt['INIT']]}; END_IF")
            elif sid == "READY":
                L.append("      Limit := T#0MS; Busy := FALSE;")
                for j in d["jobs"]:
                    first = next(x["id"] for x in d["states"] if x.get("job") == j)
                    L.append(f"      IF Job = {jobno[j]} THEN Busy := TRUE; Step := {num[first]}; END_IF  (* {j} *)")
            elif sid == "FAULT":
                L.append(f"      Limit := T#0MS; Fault := TRUE; IF Ack AND Enable THEN Fault := FALSE; "
                         f"Step := {num[next(b for a, b, c in d['edges'] if a == 'FAULT')]}; END_IF")
            elif sid == "ESTOP":
                L.append("      Limit := T#0MS; IF Reset AND Enable THEN Step := 0; END_IF")
            else:
                lim = f"T#{int(round(s['limit'] * 1000))}MS" if s.get("limit") else "T#0MS"
                outs_on = " ".join(f"{q} := TRUE;" for q in s["out"])
                cond = s["done"]
                if cond == "timer":
                    cond = f"Wd.ET >= T#{int(round(s['t'] * 1000))}MS"
                elif cond.startswith("|pos"):
                    cond = "AxisAt(Pos, Target[Arg])"
                to = nxt.get(sid, "READY")
                tgt = num[to]
                done = " Done := TRUE;" if to == "READY" else ""
                L.append(f"      Limit := {lim}; {outs_on}".rstrip())
                L.append(f"      IF {cond} THEN{done} Step := {tgt}; END_IF")
        L += ["END_CASE", "END_FUNCTION_BLOCK", ""]
        L.append("(* job table: " + ", ".join(f"{v} = {k}" for k, v in jobno.items()) + " *)")
        files[f"FB_{u.capitalize()}.st"] = "\n".join(L)
    pr = ["(* The orchestrator: one scan = the dispatcher of control.py, in the same priority order *)",
          "PROGRAM MAIN", "VAR", "    Crane : FB_Crane; Belt : FB_Belt; Arm : FB_Arm; Door : FB_Door;",
          "    Sauger : FB_Sauger; Turntable : FB_Turntable; Ovenbelt : FB_Ovenbelt; Line : FB_Line;",
          "    Places : ST_Places;    (* slots, belt ends, nests, tray, turntable, belts, bays *)",
          "    Records : ARRAY[0..11] OF ST_Cookie;", "END_VAR", "",
          "(* 1. finish: every unit that reports Done applies its job's effect to Places *)",
          "(* 2. dispatch, highest priority first; a job starts only if all its units are READY *)"]
    rules = [
            ("sort", "sort inlet has a cookie AND its bay has room"),
            ("ovenbelt", "oven belt has a cookie AND sort inlet free"),
            ("saw_eject", "turntable has a baked cookie AND oven belt free"),
            ("to_tt", "tray has a baked cookie AND turntable free"),
            ("bake", "tray has a raw cookie"),
            ("buf_to_oven", "a nest holds a raw cookie AND tray free (FIFO)"),
            ("belt_to_oven", "hand-over mould holds a raw cookie AND tray free AND buffer empty"),
            ("belt_to_buf", "hand-over mould holds a raw cookie AND the oven cannot take it AND a nest is free"),
            ("bay_to_belt", "hand-over mould is empty and earmarked AND a bay holds a cookie going in"),
            ("belt_back", "hand-over mould goes in AND crane end free"),
            ("belt_fwd", "crane-end mould goes out AND hand-over free"),
            ("store", "crane-end mould goes in AND a slot is free"),
            ("fetch_empty", "belt empty AND a cookie still needs a mould AND nothing to retrieve"),
            ("retrieve", "belt empty (BOTH ends) AND the order has a cookie in the rack")]
    if OPT["split"]:
        k = [r[0] for r in rules].index("buf_to_oven")
        rules[k:k] = [("present", "tray empty AND not presented AND a cookie is committed to it (on the cup or being picked)"),
                      ("place_oven", "a cookie on the cup AND the tray presented")]
        rules = [(n, t.replace("AND tray free", "AND no cookie committed to the tray AND the cup empty")) for n, t in rules]
    if OPT["dual"]:
        k = [r[0] for r in rules].index("belt_fwd")
        rules[k:k] = [("store_retrieve", "crane-end mould goes in AND hand-over free AND the order has a cookie in "
                                         "the rack: store into the free slot nearest it, retrieve it on the same trip")]
    for i, (nm, text) in enumerate(rules, 1):
        pr.append(f"(* {i:2d} {nm:13s} IF {text} *)")
    pr += ["", "END_PROGRAM"]
    files["MAIN.st"] = "\n".join(pr)
    return files


# ------------------------------------------------------------------ check
def check(verbose=True):
    fails = []
    units = sfc()
    fails += check_sfc(units)
    fails += check_jog()
    found = {}
    for pol in POLICIES:
        if POLICIES[pol]["buffer"] and not NEST_N:
            continue
        n, f, tr = explore(pol)
        found[pol] = (n, f, tr)
        if pol != "prefetch":
            fails += f
    if not found["prefetch"][1]:
        fails.append("the prefetch policy was expected to deadlock and did not: the explorer is suspect")
    bars, events, T, _ = simulate(PLC_POLICY)
    fails += check_trace(trace(events))
    fails += check_tours()
    if verbose:
        for pol, (n, f, tr) in found.items():
            print(f"  {pol:9s} {n:7d} states  {'OK' if not f else f[0]}")
            if tr:
                print("            ... " + " -> ".join(tr[-6:]))
        print(f"  PLC policy '{PLC_POLICY}': makespan {T} s")
        print("\n".join(fails) if fails else
              "CONTROL OK (every state reaches READY and ESTOP, no motor both ways, every motion has a "
              "timeout, no deadlock under ANY timing, 12 cookies and 12 moulds conserved, every record complete)")
    return fails


def check_tours():
    """Every VGR tour the orchestrator can command, swept clear by vgr_path."""
    import vgr_path as VP
    tours = {vgr_tour("belt_to_oven", "belt", "oven")}
    tours |= {vgr_tour("bay_to_belt", f"bay_{b}", "belt") for b in BAYS}
    for i in range(NEST_N):
        tours |= {vgr_tour("belt_to_buf", "belt", f"buf_{i + 1}"), vgr_tour("buf_to_oven", f"buf_{i + 1}", "oven")}
    fails = []
    for t in sorted(tours):
        f = VP.check(verbose=False, tour=list(t))
        fails += [f"TOUR {t[0][0]}->{t[1][0]}: {x}" for x in f[:3]]
    return fails


STUDY_BAKES = (BAKE_DEMO, 30.0, 60.0, 120.0)


def study():
    """Makespan of the 12-cookie order per policy and bake time. The deadlock
    proof covers every timing, so only the numbers change here."""
    rows = []
    try:
        for b in STUDY_BAKES:
            BAKE["s"] = b
            row = {"bake_s": b}
            for pol in POLICIES:
                if pol == "prefetch" or (POLICIES[pol]["buffer"] and not NEST_N):
                    continue
                row[pol] = simulate(pol)[2]
            rows.append(row)
    finally:
        BAKE["s"] = BAKE_DEMO
    return rows


def export():
    units = sfc()
    runs = {}
    for pol in POLICIES:
        if POLICIES[pol]["buffer"] and not NEST_N:
            continue
        if pol == "prefetch":
            n, f, tr = explore(pol)
            runs[pol] = {"say": POLICIES[pol]["say"], "deadlock": True, "states": n, "trace": tr,
                         "why": f[0].split("DEADLOCK - ", 1)[-1] if f else ""}
            continue
        bars, events, T, _ = simulate(pol)
        n, f, _ = explore(pol)
        busy = {u: round(sum(st[3] - st[2] for b in bars for st in b["steps"] if st[0] == u), 1) for u in UNITS}
        if pol != PLC_POLICY:
            bars = [{k: v for k, v in b.items() if k != "steps"} for b in bars]
        runs[pol] = {"say": POLICIES[pol]["say"], "deadlock": False, "states": n, "makespan": T,
                     "busy": busy, "bars": bars}
    _, events, T, _ = simulate(PLC_POLICY)
    rec = trace(events)
    return {
        "policy": PLC_POLICY, "policies": runs, "study": study(), "bake_demo": BAKE_DEMO,
        "units": {u: {"module": m, "outputs": list(o), "label": l, "states": units[u]["states"],
                      "edges": units[u]["edges"], "jobs": units[u]["jobs"]} for u, (m, o, l) in UNITS.items()},
        "retired": {m: list(q) for m, q in RETIRED.items()},
        "alarms": alarms(units), "unsupervised": unsupervised(units),
        "trace": [rec[c] for c in CIDS], "moulds": MOULD,
        "rfid": {"y": list(HM.RFID_Y), "pick_hbw": HM.P["PICK_HBW"], "pick_vgr": HM.P["PICK_VGR"],
                 "reach_y": round(max(p.aabb()[4] for p in HM.build(CV, 80.0, FORK_OUT) if p.joint == "fork"), 1),
                 "belt_speed": V_BELT},
        "read_points": RFID, "bands": BAND,
        "jog": [{"unit": u, "axis": a, "out": q, "when": w, "model": f} for u, a, q, w, f in JOG],
        "st": st_source(units),
        "assumed": "speeds as motion.py (HBW 150 mm/s, VGR 60 deg/s, 120 mm/s); belts 50 mm/s; "
                   "RFID read 0.3 s; vacuum 0.5 s; the booklet's 2 s demo bake; reference-switch directions",
    }


if __name__ == "__main__":
    import sys
    sys.exit(1 if check() else 0)
