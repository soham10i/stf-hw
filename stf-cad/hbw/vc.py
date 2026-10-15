"""
Upgrade 5 - virtual commissioning (STF_VARIANT=up5).

Upgrade 4's program is run against the twin before it touches hardware.

  COUPLING  the program talks to four Modbus TCP nodes. In commissioning, the
            same register map is served by the twin instead of the couplers,
            so not one address changes between the virtual and the real plant.
            The PLC task scans every 10 ms (5 ms for the VGR, see ACCURACY).
            An output reaches the plant one bus cycle later, and an input
            reaches the PLC one bus cycle later.
  PLANT     physics where it matters: motor ramps (trapezoid, a per axis),
            belt slip, cylinder travel, vacuum build-up, RFID read time. Each
            step's observed time is the plant's time plus both bus hops,
            quantised to the scan. This is equivalent to scanning every 10 ms,
            because between scans only timers change.
  PROOFS    (1) healthy run: no watchdog trips falsely, and the order time
            matches control.simulate() within TOL_MAKESPAN;
            (2) accuracy: every positioning axis stops inside its geometric
            tolerance at its task cycle;
            (3) the fault matrix: every fault is detected by the expected
            alarm within its bound, the faulted unit is safe (outputs off),
            and after the operator's recovery the order completes with 12
            cookies, 12 moulds and complete records;
            (4) recovery path: from every waypoint of every VGR tour, and from
            the middle of every leg, plunging straight up to transit height is
            clear - so re-homing the arm (plunge first) is safe anywhere.
Assumed and flagged: the accelerations, slip, cylinder and vacuum times, the
operator's repair time, and the node watchdog.
"""
import math

import control as C
import io_nodes as N
from variant import UP5, UP7

SCAN = {"default": 0.010}          # PLC task per unit, s (ACCURACY may shorten one)
BUS = 0.010                        # Modbus TCP poll per node, s
NODE_WD = 0.100                    # node watchdog: outputs to 0 when the master is silent
MB_TIMEOUT = 0.050                 # master declares a node lost
REPAIR = 30.0                      # operator: find, fix, acknowledge (ASSUMED)
RESET = 10.0                       # operator: release E-stop, reset S3 (ASSUMED)
TOL_MAKESPAN = 0.10                # the measured order time must be within 10 % of the model

# plant physics (ASSUMED unless a datasheet is named)
PHYS = {
    "a_mm": {"travel": 1500.0, "lift": 1500.0, "plunge": 1200.0, "reach": 1200.0},   # mm/s^2
    "a_deg": {"swivel": 600.0},                                                        # deg/s^2
    "v": {"travel": C.V_HBW, "lift": C.V_HBW, "plunge": C.V_MM, "reach": C.V_MM, "swivel": C.V_DEG},
    "spin_up": 0.08,          # s: a relay-switched motor to speed, for switch-ended moves
    "belt_slip": 0.03,        # the belts run 3 % slow under load
    "cyl": 0.8,               # a cylinder at 0.7 bar reaches its reed in 80 % of the booklet time
    "vac_on": 0.35, "vac_off": 0.15, "rfid": 0.12, "eject": 0.45,
}
# geometric tolerance each axis must stop inside (mm at the tool), from the models
TOLERANCE = {
    "travel": ((40.0 - 32.0) / 2, "the fork table (32 mm) in the shelf gap (40 mm)"),
    "lift": ((40.0 - 32.0) / 2, "the fork table in the shelf gap, vertically"),
    "plunge": (4.0, "the cup's spring stem takes 4 mm of over-travel"),
    "reach": None, "swivel": None,          # the cup seal: from the models, below
}
_CUP, _WP = __import__("vgr_model").V["CUP_D"], __import__("hbw_model").P["WP_D"]
if UP7:
    # U7's smaller cup buys margin for where the cookie sits (lifecycle T3/T4),
    # not for a slower task: the positioning allowance stays as commissioned
    _CUP = 40.0
TOLERANCE["reach"] = ((_WP - _CUP) / 2, f"the cup ({_CUP:.0f} mm) must sit fully on the cookie top ({_WP:.0f} mm)")
TOLERANCE["swivel"] = ((_WP - _CUP) / 2, "the same seal, across the arm at full reach")
PNEU = {"arm": {"Q8"}, "sauger": {"Q11", "Q12"}, "door": {"Q13"}, "turntable": {"Q14"},
        "line": {"Q3", "Q4", "Q5"}}


def _q(t, scan):
    """The first scan boundary at or after t."""
    return math.ceil(t / scan - 1e-9) * scan


def _trap(d, v, a):
    if d <= 0:
        return 0.0
    return d / v + v / a if d >= v * v / a else 2.0 * math.sqrt(d / a)


# ------------------------------------------------------------- accuracy
def accuracy():
    """Bang-bang positioning over Modbus: the PLC switches the relay off a
    brake lead before the target; the scan phase leaves +-v*scan/2."""
    rows, task = [], {}
    import vgr_model as VG
    r_max = VG.cup_radius(VG.V["REACH"][1])
    for ax, v in PHYS["v"].items():
        a = PHYS["a_deg"].get(ax) or PHYS["a_mm"][ax]
        tol, why = TOLERANCE[ax]
        for scan in (0.010, 0.005, 0.002):
            e = v * scan / 2
            e_mm = e * math.pi / 180 * r_max if ax == "swivel" else e
            if e_mm <= tol:
                break
        lead = v * 2 * BUS + v * v / (2 * a)
        no_lead = (lead + v * scan) * (math.pi / 180 * r_max if ax == "swivel" else 1)
        unit = "arm" if ax in ("plunge", "reach", "swivel") else "crane"
        task[unit] = min(task.get(unit, 0.010), scan)
        rows.append({"axis": ax, "unit": unit, "v": v, "a": a, "scan_ms": round(scan * 1000),
                     "lead": round(lead, 2), "error_mm": round(e_mm, 2), "tol_mm": round(tol, 2),
                     "why": why, "no_lead_mm": round(no_lead, 1), "ok": e_mm <= tol,
                     "at_10ms_mm": round(v * 0.005 * (math.pi / 180 * r_max if ax == "swivel" else 1), 2)})
    return rows, task


ACC, TASK = accuracy()


def scan_of(unit):
    return TASK.get(unit, SCAN["default"])


# ---------------------------------------------------------------- plant
def phys(st):
    """The plant's time for one step, from its outputs, its signal and its travel."""
    if st.dist:
        return max(_trap(d, PHYS["v"][ax], PHYS["a_deg"].get(ax) or PHYS["a_mm"][ax])
                   for ax, d in st.dist.items()) if any(st.dist.values()) else 0.0
    if st.done == "timer":
        return st.t
    if st.done.startswith("I4") or st.done == "NOT I4":
        return PHYS["vac_on"] if st.out else PHYS["vac_off"]
    if "RF2" in st.done:
        return PHYS["rfid"]
    if st.unit in ("belt", "ovenbelt") or (st.unit == "line" and st.key.startswith("run")):
        return st.t / (1 - PHYS["belt_slip"])
    if st.key == "eject":
        return PHYS["eject"]
    if st.done in C.U5_ROWS.values() or st.done in ("I10", "I11", "I12", "I13", "I14", "I15"):
        return st.t * PHYS["cyl"]
    if not st.motion:
        return st.t
    return st.t + PHYS["spin_up"]


def observed(st, t0):
    """When the PLC sees the step done: out one bus hop, the plant's time,
    in one bus hop, rounded up to the unit's scan."""
    return _q(t0 + BUS + phys(st) + BUS, scan_of(st.unit))


def pneumatic(st):
    return bool(set(st.out) & PNEU.get(st.unit, set()))


# ------------------------------------------------------------------ run
class Run:
    """The orchestrator of control.py driven step by step against the plant."""

    def __init__(self, pol="reuse", fault=None):
        self.pol, self.fault = pol, fault or {}
        self.s = C.dispatch(C.initial(), pol)
        self.t = 0.0
        self.jobs = {}                  # job -> {"steps", "pc", "t0", "t1"}
        self.hold = 0.0                 # no step starts before this
        self.pneu_hold = 0.0            # no pneumatic step starts before this
        self.alarms, self.bars, self.events, self.notes = [], [], [], []
        self.count = {}                 # job name -> starts, for "the n-th such job"
        self.fired = False
        self.unsafe = []
        self.lost = 0.0

    # --- a step begins
    def _begin(self, job, t):
        J = self.jobs[job]
        st = J["steps"][J["pc"]]
        t0 = max(t, self.hold, self.pneu_hold if pneumatic(st) else 0.0)
        t0 = _q(t0, scan_of(st.unit))
        J["t0"], J["t1"] = t0, observed(st, t0)
        f = self.fault
        if f and not self.fired and f["kind"] in ("never", "vac") and job[0] == f["job"] \
                and J["n"] == f.get("n", 1) and self._match(J, st, f):
            self._inject(job, J, st, t0)
        J["bars"].append([st.unit, st.key, round(J["t0"], 3), round(J["t1"], 3), st.limit])

    def _match(self, J, st, f):
        if f["kind"] == "vac":
            return st.unit == "arm" and "Q8" in st.out and st.key.endswith(":pos") and \
                   J["steps"][J["pc"] - 1].key.endswith(":vac")
        return st.unit == f["unit"] and (f.get("key") is None or st.key == f["key"]) and \
            (f.get("out") is None or f["out"] in st.out)

    def _alarm(self, code, t, unit, why):
        self.alarms.append({"code": code, "t": round(t, 3), "unit": unit, "why": why})

    def _inject(self, job, J, st, t0):
        self.fired = True
        f = self.fault
        units = C.sfc()
        if f["kind"] == "never":
            trip = _q(t0 + st.limit, scan_of(st.unit))
            code = _code_for(units, job, J, st)
            self._alarm(code, trip, st.unit, f"watchdog: {st.done} not reached in {st.limit} s")
            ack = trip + REPAIR
            self.hold = max(self.hold, ack)
            self.fault_at, self.trip, self.ack = t0, trip, ack
            # the faulted step is retried after the repair, now healthy
            J["t1"] = observed(st, ack)
            self.lost += J["t1"] - observed(st, t0)
        else:                                  # vac: the seal breaks half-way along this carry leg
            drop = t0 + phys(st) / 2
            trip = _q(drop + BUS, scan_of("arm"))
            self._alarm("VGR-V01", trip, "arm", "vacuum switch I4 dropped while carrying")
            ack = trip + REPAIR
            # retrace the tour to transit height, re-home the arm, restart the arm segment
            done_arm = [x for x in J["steps"][:J["pc"] + 1] if x.unit == "arm"]
            retrace = sum(phys(x) for x in done_arm) / 2 + sum(phys(h) for h in C.HOMING["arm"])
            self.fault_at, self.trip, self.ack = drop, trip, ack
            self.hold = max(self.hold, ack)
            J["restart"] = _arm_restart(job, J, ack + retrace)
            J["t1"] = trip
            self.lost += ack + retrace - trip

    # --- time-based faults
    def _timed_fault(self):
        f = self.fault
        if not f or self.fired or f["kind"] not in ("air", "node", "estop"):
            return
        T0, D = f["at"], f["for"]
        self.fired = True
        self.fault_at = T0
        if f["kind"] == "estop":
            trip = _q(T0 + BUS, SCAN["default"])
            self._alarm("SYS-01", trip, "system", "E-stop: K0 drops K1/K2, Y1 vents")
            ack = T0 + D + RESET
            for job, J in self.jobs.items():
                st = J["steps"][J["pc"]]
                if J["t0"] <= T0 < J["t1"]:
                    if st.unit == "arm" and "Q8" in st.out:          # Y1 vents the vacuum too
                        self._alarm("VGR-V01", _q(T0 + BUS, scan_of("arm")), "arm",
                                    "E-stop vented the vacuum: the cookie dropped")
                        self.notes.append("E-stop during a VGR carry drops the cookie (Y1 vents the ejector)")
                        J["restart"] = _arm_restart(job, J, ack + REPAIR)
                        J["t1"] = T0
                    else:
                        J["t1"] = observed(st, ack)                  # positions kept: redo the step
            self.hold = max(self.hold, ack)
            self.trip, self.ack = trip, ack
            self.lost += ack - T0
        elif f["kind"] == "node":
            m = f["module"]
            trip = _q(T0 + MB_TIMEOUT, SCAN["default"])
            self._alarm("SYS-04", trip, "system", f"{m} node lost (Modbus timeout)")
            mods = {u for u, (mm, _, _) in C.UNITS.items() if mm == m}
            rehome = max(sum(phys(h) for h in C.HOMING[u]) for u in mods)
            ack = T0 + D + RESET
            for job, J in self.jobs.items():
                st = J["steps"][J["pc"]]
                if st.unit in mods and J["t0"] <= T0 < J["t1"]:
                    J["t1"] = observed(st, ack + rehome)
            self.hold = max(self.hold, ack + rehome)
            self.trip, self.ack = trip, ack
            self.node_mods, self.node_off = mods, (T0 + NODE_WD, ack)
            self.lost += ack + rehome - T0
        elif f["kind"] == "air":
            trip = _q(T0 + BUS, scan_of("arm"))
            self._alarm("SYS-05", trip, "system", "air pressure low (vgr I5)")
            ack = T0 + D + RESET
            for job, J in self.jobs.items():
                st = J["steps"][J["pc"]]
                if J["t0"] <= T0 < J["t1"] and pneumatic(st):
                    if st.unit == "arm" and "Q8" in st.out:
                        self._alarm("VGR-V01", trip, "arm", "air lost: the ejector's vacuum collapsed")
                        J["restart"] = _arm_restart(job, J, ack + REPAIR)
                        J["t1"] = T0
                    else:
                        J["t1"] = observed(st, ack)
            self.pneu_hold = max(self.pneu_hold, ack)
            self.trip, self.ack = trip, ack
            self.lost += D + RESET

    # --- the loop
    def run(self):
        for job in self.s["run"]:
            self._start_job(job)
        while self.s["run"]:
            f = self.fault
            if f and not self.fired and f["kind"] in ("air", "node", "estop"):
                nxt = min(self.jobs[j]["t1"] for j in self.jobs)
                if f["at"] <= nxt:
                    self.t = f["at"]
                    self._timed_fault()
                    continue
            job = min(self.jobs, key=lambda j: (self.jobs[j]["t1"], C.UNIT_ORDER.index(j[2][0])))
            J = self.jobs[job]
            self.t = J["t1"]
            if "restart" in J:
                J["pc"], t_re = J.pop("restart")
                self._begin(job, t_re)
                continue
            J["pc"] += 1
            if J["pc"] < len(J["steps"]):
                self._begin(job, self.t)
                continue
            self.events.append((round(self.t, 2), "end", job))
            self.bars.append({"job": job[0], "bind": [str(x) for x in job[1]], "units": list(job[2]),
                              "t0": J["start"], "t1": round(self.t, 2), "steps": J["bars"]})
            del self.jobs[job]
            self.s = C.dispatch(C.complete(self.s, job, self.pol), self.pol)
            bad = C.invariants(self.s)
            if bad:
                raise AssertionError("; ".join(bad))
            for j in self.s["run"]:
                if j not in self.jobs:
                    self._start_job(j)
        if not C.goal(self.s):
            raise AssertionError("the order did not complete")
        return self

    def _start_job(self, job):
        self.count[job[0]] = self.count.get(job[0], 0) + 1
        self.jobs[job] = {"steps": C.job_steps(job), "pc": 0, "n": self.count[job[0]],
                          "start": round(max(self.t, self.hold), 2), "bars": []}
        self.events.append((round(max(self.t, self.hold), 2), "start", job))
        self._begin(job, self.t)

    @property
    def makespan(self):
        return round(self.t, 2)


def _arm_restart(job, J, t):
    """Where a job restarts after its cookie dropped: from its first arm step -
    unless it is Upgrade 10's place_oven, whose source (the cup) is gone: the
    operator lays the cookie on the presented tray, and the arm only retraces
    and goes home (its last step)."""
    if job[0] == "place_oven":
        return (len(J["steps"]) - 1, t)
    return (next(i for i, x in enumerate(J["steps"]) if x.unit == "arm"), t)


def _code_for(units, job, J, st):
    """The alarm the PLC raises for this step: the one whose steps list its SFC state."""
    k = [x for x in J["steps"][:J["pc"] + 1] if x.unit == st.unit]
    sid = st.key if st.key.startswith("H:") else f"{job[0]}.{len(k):02d}"
    for a in C.alarms(units):
        if a["unit"] == st.unit and sid in a["steps"]:     # state ids repeat across units
            return a["code"]
    return "?"


# ----------------------------------------------------------- fault matrix
def matrix():
    """(id, fault, what the plant does, the injection, the expected alarm, the detection bound)."""
    return [
        ("F1", "stuck switch", "crane I6 (Ausleger back) never makes",
         {"kind": "never", "job": "store_retrieve" if C.OPT["dual"] else "retrieve", "n": 1 if C.OPT["dual"] else 2,
          "unit": "crane", "key": "fork->back"}, ("crane", "I6")),
        ("F2", "motor stall", "VGR swivel motor stalls: B5/B6 stop counting",
         {"kind": "never", "job": "belt_to_oven", "n": 2, "unit": "arm", "out": "Q5"}, ("arm", "B5")),
        ("F3", "cylinder never arrives", "oven door cylinder sticks shut (I10 never)",
         {"kind": "never", "job": "present" if C.OPT["split"] else "belt_to_oven", "n": 3, "unit": "door",
          "key": "row1"}, ("door", "I10")),
        ("F4", "lost vacuum", "cup seal breaks while carrying a raw cookie", {"kind": "vac", "job": "belt_to_oven", "n": 4},
         ("system", "VGR-V01")),
        ("F5", "air pressure drop", "air station loses pressure for 60 s", {"kind": "air", "at": 250.0, "for": 60.0},
         ("system", "SYS-05")),
        ("F6", "lost bus node", "the oven node drops off the network for 20 s",
         {"kind": "node", "module": "oven", "at": 330.0, "for": 20.0}, ("system", "SYS-04")),
        ("F7", "E-stop", "ES1 pressed for 15 s", {"kind": "estop", "at": 410.0, "for": 15.0}, ("system", "SYS-01")),
    ]


def _expected_code(units, exp):
    unit, sig = exp
    if unit == "system":
        return sig
    for a in C.alarms(units):
        if a["unit"] == unit and sig in a["cause"] + a["text"]:
            return a["code"]
    return "?"


def run_matrix(healthy):
    units = C.sfc()
    rows = []
    for fid, name, what, inj, exp in matrix():
        want = _expected_code(units, exp)
        r = Run(C.PLC_POLICY, dict(inj)).run()
        fails = []
        got = r.alarms[0]["code"] if r.alarms else None
        if got != want:
            fails.append(f"first alarm {got}, expected {want}")
        if not r.fired:
            fails.append("the fault was never injected")
        latency = round(r.trip - r.fault_at, 3) if r.fired else None
        bound = None
        if inj["kind"] == "never":
            st_limit = max(a["limit"] or 0 for a in C.alarms(units) if a["code"] == want) if want != "?" else 0
            bound = st_limit + 2 * BUS + 0.02
        else:
            bound = 0.1
        if latency is None or latency > bound:
            fails.append(f"detected after {latency} s, bound {bound} s")
        rec = C.trace(r.events)
        tf = C.check_trace(rec)
        if tf:
            fails.append(f"records after recovery: {tf[0]}")
        rows.append({"id": fid, "fault": name, "what": what, "expected": want,
                     "observed": [a["code"] for a in r.alarms], "latency_s": latency, "bound_s": round(bound, 3),
                     "reaction": _reaction(inj), "recovery": _recovery(inj),
                     "makespan": r.makespan, "lost_s": round(r.makespan - healthy.makespan, 1),
                     "notes": r.notes, "pass": not fails, "fails": fails})
    return rows


def _reaction(inj):
    return {"never": "the unit's outputs drop (FAULT); the others finish their step and hold",
            "vac": "the arm stops where it is; every other unit holds",
            "air": "no pneumatic step starts; the HBW crane and belts carry on",
            "node": "the node's watchdog drops its outputs; every unit holds",
            "estop": "K1/K2 open, Y1 vents: every actuator off at once"}[inj["kind"]]


def _recovery(inj):
    return {"never": f"repair + acknowledge ({REPAIR:.0f} s); the step is retried; the order completes",
            "vac": "the cookie back at the source, acknowledge; the arm retraces and re-homes; the job restarts",
            "air": f"pressure back, acknowledge ({RESET:.0f} s); pneumatic steps resume",
            "node": "link back, acknowledge; the node's units re-home (counts were lost) and resume",
            "estop": f"release, reset S3 ({RESET:.0f} s); interrupted steps are redone (positions kept)"}[inj["kind"]]


def before_sensors(healthy):
    """What the same two faults did on Upgrade 4's hardware (no reeds, no
    vacuum switch), computed from the healthy run's timeline."""
    bars = healthy.bars
    out = []
    # F3 without the door reed: row1 is only timed, so the slider (row2, I7) drives into the shut door
    b = [x for x in bars if x["job"] == ("present" if C.OPT["split"] else "belt_to_oven")][2]
    r1 = next(s for s in b["steps"] if s[1] == "row1")
    lim2 = next(s for s in C.oven_steps("present") if s.key == "row2").limit
    out.append({"id": "F3", "detected": "OVN-D watchdog on I7 (the slider)", "after_s": round(r1[3] - r1[2] + lim2, 2),
                "harm": "the Ofenschieber drives into the shut door for its whole watchdog time"})
    # F4 without the vacuum switch: nothing notices until that cookie's oven-belt I3 never comes
    b = [x for x in bars if x["job"] == "belt_to_oven"][3]
    c = b["bind"][0]
    ob = next(x for x in bars if x["job"] == "ovenbelt" and x["bind"][0] == c)
    lim = C.ovenbelt_steps()[0].limit
    out.append({"id": "F4", "detected": "OVN-B watchdog on I3 (oven belt end)", "after_s": round(ob["t0"] + lim - b["t0"], 1),
                "harm": "a bake, a Sauger transfer and a saw cycle run empty; the record says 'baked'"})
    return out


# ---------------------------------------------------------- signal map
IP = {"hbw": "192.168.10.11", "vgr": "192.168.10.12", "oven": "192.168.10.13", "sorting": "192.168.10.14"}
TABLE = {"DO": ("coil", 0), "DI": ("discrete input", 10000), "AI": ("input register", 30000),
         "CNT": ("input register", 30000), "IOL": ("holding register", 40000)}


def signal_map():
    rows = []
    for m in N.MODULES:
        nxt = {"DO": 0, "DI": 0, "AI": 0, "CNT": 100, "IOL": 0}
        for sid, t, chans in N.slices(m):
            for k, sg in enumerate(chans):
                tbl, base = TABLE[t]
                width = {"CNT": 2, "IOL": 8}.get(t, 1)
                addr = base + nxt[t]
                nxt[t] += width
                if not sg:
                    continue
                rows.append({"tag": f"{m.upper()}_{sg.replace('/', '_')}", "module": m, "signal": sg, "type": t,
                             "node": IP[m], "slice": sid, "ch": k + 1, "table": tbl, "addr": addr, "regs": width,
                             "twin": f"{m}.{sg}", "desc": C.SIG.get((m, sg.split("/")[0]), "")})
    return rows


def check_map(rows):
    fails = []
    seen = set()
    for r in rows:
        key = (r["node"], r["table"], r["addr"])
        if key in seen:
            fails.append(f"MAP {r['tag']}: address {key} used twice")
        seen.add(key)
    mapped = {(r["module"], s) for r in rows for s in r["signal"].split("/")}
    for u, d in C.sfc().items():
        m = C.UNITS[u][0]
        for st in d["states"]:
            for q in st["out"]:
                if (m, q) not in mapped:
                    fails.append(f"MAP {m}.{q}: written by {u} but not on any register")
            for sg in st.get("sig", []):
                if (m, sg) not in mapped:
                    fails.append(f"MAP {m}.{sg}: read by {u} but not on any register")
    if UP5 and ("vgr", "I5") not in mapped:
        fails.append("MAP the air-pressure switch is not mapped")
    return fails


# ------------------------------------------------------ recovery paths
def check_recovery_paths():
    """From every waypoint of every VGR tour, and the middle of every leg,
    plunging straight up to transit height is clear."""
    import vgr_path as VP
    T = VP.V["TRANSIT"]
    tours = {C.vgr_tour("belt_to_oven", "belt", "oven")}
    tours |= {C.vgr_tour("bay_to_belt", f"bay_{b}", "belt") for b in C.BAYS}
    for i in range(C.NEST_N):
        tours |= {C.vgr_tour("belt_to_buf", "belt", f"buf_{i + 1}"), C.vgr_tour("buf_to_oven", f"buf_{i + 1}", "oven")}
    fails, n = [], 0
    for t in sorted(tours):
        keys = C._tour_keys(t)
        poses = list(keys)
        for a, b in zip(keys, keys[1:]):
            poses.append({**a, **{x: (a[x] + b[x]) / 2 for x in ("sw", "rr", "pz", "compress")},
                          "station": a["station"] or b["station"]})
        for k in poses:
            if k["pz"] >= T - 1e-6:
                continue
            n += 1
            if not VP._leg_clear(k, {**k, "pz": T, "compress": 0.0}):
                fails.append(f"RECOVERY {t[0][0]}->{t[1][0]}: plunging up from sw={k['sw']:.1f} "
                             f"rr={k['rr']:.0f} pz={k['pz']:.0f} hits something")
    return fails, n


# ---------------------------------------------------------- performance
def performance(healthy, rows):
    busy = {u: round(sum(s[3] - s[2] for b in healthy.bars for s in b["steps"] if s[0] == u), 1) for u in C.UNITS}
    bott = max(busy, key=busy.get)
    T = healthy.makespan
    lost = sum(r["lost_s"] for r in rows)
    good = sum(1 for r in C.trace(healthy.events).values() if r.get("verified"))
    A = T / (T + lost)
    P = busy[bott] / T
    Q = good / len(C.PRODUCE)
    buf = Run("buffer").run().makespan if C.NEST_N else None
    return {"makespan": T, "model": C.simulate(C.PLC_POLICY)[2], "busy": busy, "bottleneck": bott,
            "availability": round(A, 3), "performance": round(P, 3), "quality": round(Q, 3),
            "oee": round(A * P * Q, 3), "shift_s": round(T + lost, 1), "buffer_makespan": buf,
            "oee_note": "a shift = the 12-cookie order with every fault of the matrix once; "
                        "performance = the bottleneck's busy time / the order time; quality = A4-verified / made"}


# ---------------------------------------------------------------- check
_CACHE = {}


def results():
    if "r" in _CACHE:
        return _CACHE["r"]
    healthy = Run(C.PLC_POLICY).run()
    rows = run_matrix(healthy)
    _CACHE["r"] = (healthy, rows)
    return _CACHE["r"]


def check(verbose=True):
    fails = []
    healthy, rows = results()
    model = C.simulate(C.PLC_POLICY)[2]
    dev = abs(healthy.makespan - model) / model
    if dev > TOL_MAKESPAN:
        fails.append(f"TIME the commissioned order took {healthy.makespan} s, the model {model} s ({dev:.1%})")
    if healthy.alarms:
        fails.append(f"FALSE TRIP in the healthy run: {healthy.alarms[0]}")
    # with real physics and both bus hops, no step of the healthy run may reach its watchdog
    worst = 0.0
    for b in healthy.bars:
        for u, key, t0, t1, lim in b["steps"]:
            if lim:
                worst = max(worst, (t1 - t0) / lim)
                if t1 - t0 >= lim:
                    fails.append(f"WATCHDOG {b['job']} {key}: {t1 - t0:.2f} s >= {lim} s")
    _CACHE["worst"] = round(worst, 3)
    fails += [f"ACCURACY {r['axis']}: {r['error_mm']} mm > {r['tol_mm']} mm" for r in ACC if not r["ok"]]
    for r in rows:
        if not r["pass"]:
            fails.append(f"MATRIX {r['id']} {r['fault']}: {'; '.join(r['fails'])}")
    fails += check_map(signal_map())
    rf, n = check_recovery_paths()
    fails += rf
    if verbose:
        print(f"  healthy: {healthy.makespan} s vs model {model} s ({(healthy.makespan - model) / model:+.1%}); tasks {TASK}")
        for r in rows:
            print(f"  {r['id']} {r['fault']:22s} {'PASS' if r['pass'] else 'FAIL'}  {r['observed']}  "
                  f"latency {r['latency_s']} s  +{r['lost_s']} s")
        print(f"  recovery paths: {n} poses checked")
        print("\n".join(fails) if fails else "VC OK (no false trips, accuracy inside tolerance, every fault "
                                             "detected, safe and recovered, every signal mapped once)")
    return fails


def export():
    healthy, rows = results()
    return {
        "scan_ms": {u: round(scan_of(u) * 1000) for u in C.UNITS}, "bus_ms": BUS * 1000,
        "node_wd_ms": NODE_WD * 1000, "mb_timeout_ms": MB_TIMEOUT * 1000, "repair_s": REPAIR, "reset_s": RESET,
        "phys": PHYS, "accuracy": ACC, "tol_makespan": TOL_MAKESPAN,
        "healthy": {"makespan": healthy.makespan, "worst_watchdog": _CACHE.get("worst"), "bars": [{k: v for k, v in b.items() if k != "steps"} for b in healthy.bars]},
        "matrix": rows, "before": before_sensors(healthy),
        "sensors": {m: {s: {"part": p, "what": w} for s, (p, w) in d.items()} for m, d in C.U5_SENSORS.items()},
        "map": signal_map(), "performance": performance(healthy, rows), "ip": IP,
        "assumed": "accelerations, belt slip, cylinder/vacuum/RFID times, the operator's repair (30 s) and reset (10 s), "
                   "the node watchdog (100 ms) and the Modbus timeout (50 ms)",
    }


if __name__ == "__main__":
    import sys
    sys.exit(1 if check() else 0)
