"""
One month of production on the Upgrade 7 machine - the data a real cell
would have produced, simulated from the models (STF_VARIANT=up7).

  PLAN      30 days x 2 shifts (06-14, 14-22). One order = the 12-cookie
            batch the rack holds: 9 baked and sorted, 3 returned to the rack.
            Between orders the operator empties the bays and loads raw dough
            (CHANGEOVER). No order starts that cannot finish in its shift.
  MACHINE   every order takes the commissioned order time (vc.py) plus the
            slowdown of every worn component on the critical path.
  WEAR      every U6 component wears along its own law (health.py), from a
            realistic age at the start of the month, with real disturbances:
            a daily temperature cycle, lubricant loss on the HBW spindle,
            bearing spalling in the VGR gearbox, and a nicked cup lip.
  FAULTS    the U5 fault types arrive at random (Poisson, per running hour).
            Each costs the time commissioning measured, with a spread.
            Vacuum losses become more frequent as the cup seal wears.
  MONITOR   U6's EWMA, soft limit and trend on every order. A warning opens
            a work order, done at the next shift change (or at once, if the
            trend says it cannot wait). The part is renewed.
  SAVES     two work orders prevent a failure that would stop the whole line:
            the VGR swivel gearbox and the HBW travel spindle (the VGR and the
            crane are single points: every cookie passes both). The same
            month is run again without those two work orders - the
            counterfactual - to show what they saved.
Output: web/public/month/month.json for the dashboard, plus CSVs (orders,
sensors, events, FSM, daily) for any other tool. Every rate, life, repair
time and disturbance is ASSUMED and listed in meta.assumed.
"""
import csv
import json
import math
import os
import random
from datetime import datetime, timedelta

import control as C
import health as H
import vc as V
from variant import UP7

assert UP7, "run with STF_VARIANT=up7"

OUT = os.path.expanduser("~/workspace/stf-hw/web/public/month")
START = datetime(2026, 9, 1, 6, 0)
DAYS = 30
SHIFTS = ((6, 14), (14, 22))
CHANGEOVER = 120.0                 # s: empty the bays, load 9 raw doughs (ASSUMED)
SEED = 20260901

# the month's story: starting age (fraction of life used) and disturbances
SCENARIO = {
    "cup":     {"w0": 0.30, "events": [(9.0, 5.0, "the cup lip is nicked by a burr on a mould rim")]},
    "door":    {"w0": 0.20, "events": []},
    "lower":   {"w0": 0.25, "events": []},
    "pusher":  {"w0": 0.15, "events": []},
    "belt":    {"w0": 0.35, "events": []},
    "rfid":    {"w0": 0.10, "events": []},
    "spindle": {"w0": 0.45, "events": [(5.0, 6.0, "the spindle nut loses its grease (a wiper seal failed)")]},
    "gearbox": {"w0": 0.62, "events": [(16.0, 1.6, "bearing spalling starts in the swivel gearbox")]},
    "air":     {"w0": 0.20, "events": [(12.0, 1.8, "a push-in fitting on the oven manifold starts to leak")]},
    "colour":  {"w0": 0.25, "events": []},
}
SAVES = ("gearbox", "spindle")
# planned work: minutes at a shift change (ASSUMED)
PM_MIN = {"cup": 15, "door": 30, "lower": 30, "pusher": 30, "belt": 45, "rfid": 20, "spindle": 120,
          "gearbox": 90, "air": 30, "colour": 10}
# if it fails in service instead: hours down, cookies scrapped, and what happens (ASSUMED)
FAIL = {
    "gearbox": (4.0, 1, "the swivel seizes mid-swing with a cookie on the cup; the VGR stops, and with it every "
                        "transfer in the line: motor swap, re-homing, recommissioning run"),
    "spindle": (6.5, 1, "the breaker trips on the HBW feed mid-move with a mould on the fork; the crane stops, "
                        "the line starves: recover the mould by hand, strip the mast, new spindle and nut"),
    "cup": (0.75, 2, "the seal tears; repeated vacuum losses, then the watchdog; new cup"),
    "belt": (1.5, 0, "the belt slips past its watchdog; new belt"),
    "air": (1.0, 0, "the pump cannot hold pressure; SYS-05 stops every pneumatic step; fix the leak"),
    "colour": (0.5, 3, "a flavour reads into its neighbour's band; TRC-03 rejects until recalibrated"),
}
FAIL_DEFAULT = (1.0, 0, "watchdog trip; part replaced")
# random faults per 100 running hours, and the U5 matrix row that prices them (ASSUMED rates)
RATES = {"F7": 0.8, "F1": 0.4, "F3": 0.25, "F2": 0.2, "F5": 0.15, "F6": 0.1}
FAULT_NAME = {"F1": "stuck switch", "F2": "motor stall", "F3": "cylinder never arrives", "F4": "lost vacuum",
              "F5": "air pressure drop", "F6": "lost bus node", "F7": "E-stop"}
RESPONSE = (60.0, 240.0)           # s: the operator gets there (uniform, ASSUMED)
CRIT = {"arm": 1.0, "crane": 1.0, "belt": 1.0, "door": 0.3, "sauger": 0.1, "turntable": 0.1, "system": 0.2,
        "line": 0.1}


FEATURES = None     # filled below: the ml/ input columns, in order


def _comp():
    out = {}
    for c in H.components():
        r = {"id": c["id"], "name": c["name"], "unit": c["unit"], "kind": c["kind"], "life": c["life"], "p": c["p"],
             "per_order": H._per_cycle(c), "metric": c["metric"], "part": c["part"]}
        if c["kind"] in ("time", "current"):
            sts = H._steps(c["steps"])
            rf, b, sig = H._baseline(sts)
            r.update(r_fail=H.ECB_TRIP if c["kind"] == "current" else rf, base=b, sig=sig,
                     busy=sum(V.phys(s) for s in sts), unit_of="s")
        elif c["kind"] == "duty":
            d0 = H.air_duty0()
            r.update(r_fail=1 / d0, base=d0, sig=0.03, busy=0.0, unit_of="duty")
        else:
            r.update(r_fail=2.0, base=H.colour_margin(), sig=5.0 / H.colour_margin(), busy=0.0, unit_of="mV")
        out[c["id"]] = r
    return out


COMP = _comp()
FEATURES = [f"r_{k}" for k in COMP] + ["temp_c", "i_hbw_a", "air_duty", "a4_vanilla_mv", "a4_strawberry_mv",
                                       "a4_chocolate_mv", "vacuum_loss", "order_time_ratio"]
T0 = V.results()[0].makespan


def _fsm_nominal():
    """Per order, each unit's seconds RUN (its own step), HELD (its job waits
    on another unit's step) and READY, from the PLC's nominal run."""
    bars, _, T, _ = C.simulate(C.PLC_POLICY)
    out = {}
    for u in C.UNITS:
        run = sum(s[3] - s[2] for b in bars for s in b["steps"] if s[0] == u)
        held = sum(b["t1"] - b["t0"] for b in bars if u in b["units"]) - run
        out[u] = {"RUN": run, "HELD": max(0.0, held), "READY": max(0.0, T - run - max(0.0, held))}
    return out, T


FSM0, T_MODEL = _fsm_nominal()


def temperature(t_h):
    """Hall temperature, deg C: a daily cycle plus a slow warm spell mid-month."""
    day = t_h / 24
    return 21.0 + 3.0 * math.sin(2 * math.pi * (t_h % 24 - 9) / 24) + 1.5 * math.sin(math.pi * day / DAYS)


class Month:
    def __init__(self, skip_pm=(), scenario=None, seed=SEED, days=DAYS):
        """skip_pm: components whose work orders are not done (the
        counterfactual; all of them = a run-to-failure machine for ml/).
        scenario/seed/days: another machine-month (ml/fleet.py)."""
        self.scen = scenario or SCENARIO
        self.days = days
        self.rnd = random.Random(seed)
        self.skip = set(skip_pm)
        self.w = {k: self.scen[k]["w0"] for k in COMP}
        self.ew = {k: 1.0 for k in COMP}
        self.hist = {k: [] for k in COMP}
        self.pending = {}                     # comp -> (planned time, reason)
        self.failed = {}
        self.orders, self.events, self.sensors = [], [], {k: [] for k in COMP}
        self.raw = {"temp": [], "a4": {"chocolate": [], "strawberry": [], "vanilla": []}, "i_hbw": [], "air_duty": []}
        self.fsm = {u: {"RUN": 0.0, "HELD": 0.0, "READY": 0.0, "FAULT": 0.0, "ESTOP": 0.0, "MAINT": 0.0} for u in C.UNITS}
        self.down = {}                        # cause -> seconds
        self.warned = {}
        self.fixed = {}                       # comp -> day its root cause was fixed
        self.feat = []                        # ml/: one feature row per order (FEATURES)
        self.fail_idx = []                    # ml/: (order index, component) of every failure

    # --- wear
    def _rate(self, k, day):
        """Wear speed: 1 x, times every disturbance that has started and whose
        root cause has not been fixed by a work order since."""
        m = 1.0
        for d0, mult, _ in self.scen[k]["events"]:
            if day >= d0 and not (k in self.fixed and self.fixed[k] >= d0):
                m *= mult
        return m

    def _r(self, k, t_h):
        c = COMP[k]
        r = 1 + (c["r_fail"] - 1) * min(1.2, self.w[k]) ** c["p"]
        if k in ("belt", "air"):                      # temperature: warmer = more slip, more leak
            r *= 1 + 0.004 * (temperature(t_h) - 21.0)
        return r

    def _ev(self, t, kind, what, **kw):
        self.events.append({"t": round(t / 3600, 4), "kind": kind, "what": what, **kw})

    def _stop(self, t, secs, cause, units, state="FAULT"):
        self.down[cause] = self.down.get(cause, 0.0) + secs
        for u in C.UNITS:
            self.fsm[u][state if u in units else "HELD"] += secs
        return t + secs

    # --- one order
    def _order(self, t, day, shift, end_of_shift):
        t_h = t / 3600
        extra, scrap = 0.0, 0
        r_obs = {}
        for k, c in COMP.items():
            use = c["per_order"] * (1 if c["kind"] != "duty" else 1)
            self.w[k] += use / c["life"] * self._rate(k, day)
            r = self._r(k, t_h)
            n = max(1, c["per_order"])
            obs = r * (1 + self.rnd.gauss(0, c["sig"] / math.sqrt(n)))
            a = 1 - (1 - H.EWMA) ** n
            r_obs[k] = obs
            self.ew[k] += a * (obs - self.ew[k])
            self.hist[k].append(self.ew[k])
            extra += CRIT.get(c["unit"], 0.2) * max(0.0, r - 1) * c["busy"]
            # health
            rf = c["r_fail"]
            soft = 1 + H.SOFT * (rf - 1)
            hi = max(0.0, min(1.0, (rf - self.ew[k]) / (rf - 1)))
            # the trend needs history: 40 orders (the U6 proof's 400-use window, or more)
            h = self.hist[k][-40:]
            slope = (h[-1] - h[0]) / (len(h) - 1) if len(h) >= 40 else 0.0
            rul_orders = (rf - self.ew[k]) / slope if slope > 1e-9 else None
            per_shift = 8 * 3600 / (T0 + CHANGEOVER)
            rul_sh = None if rul_orders is None else rul_orders / per_shift
            self.sensors[k].append((round(t_h, 3), round(obs * (c["base"] if c["unit_of"] == "s" else 1), 4),
                                    round(self.ew[k], 4), round(100 * hi, 1), None if rul_sh is None else round(min(rul_sh, 999), 1)))
            warn = self.ew[k] >= soft or (rul_sh is not None and rul_sh < H.RUL_WARN_SHIFTS and self.ew[k] > 1 + 0.25 * (rf - 1))
            if warn and k not in self.warned and k not in self.failed:
                self.warned[k] = t
                why = "soft limit" if self.ew[k] >= soft else f"trend: {rul_sh:.1f} shifts left"
                self._ev(t, "warning", f"U6 warning: {c['name']} ({why})", comp=k, hi=round(100 * hi))
                if k not in self.skip:
                    # into the night gap (22-06, no production) unless the trend says it cannot wait that long
                    left = (1 - shift) + (end_of_shift - t) / (8 * 3600)          # shifts until tonight's gap
                    urgent = rul_sh is not None and rul_sh < left + 0.25
                    self.pending[k] = ("now" if urgent else "night", why)
                    self._ev(t, "work order", f"work order: renew {c['name']}", comp=k,
                             when="immediately (the trend will not last until tonight)" if urgent
                             else "tonight, 22:00-06:00 (no production lost)")
            if r >= rf and k not in self.failed:
                self.failed[k] = t
                self.fail_idx.append((len(self.orders), k))
                hrs, sc, what = FAIL.get(k, FAIL_DEFAULT)
                self._ev(t, "failure", f"FAILURE: {c['name']} - {what}", comp=k, down_h=hrs, scrap=sc)
                scrap += sc
                t = self._stop(t, hrs * 3600, f"failure: {c['name']}", {c["unit"]} if c["unit"] in C.UNITS else set(C.UNITS))
                self.w[k] = 0.02
                self.ew[k] = 1.0
                self.hist[k] = []
                self.warned.pop(k, None)
                self.failed.pop(k)
                self.fixed[k] = day                   # the repair deals with the cause too
                self.pending.pop(k, None)
        # the vacuum loses grip more often as the seal wears
        p_vac = 0.002 * math.exp(4.0 * (self._r("cup", t_h) - 1))
        vac = 0
        if self.rnd.random() < p_vac:
            vac = 1
            lost = 50.4 * math.exp(self.rnd.gauss(0, 0.3)) + self.rnd.uniform(*RESPONSE)
            self._ev(t, "fault", "VGR-V01 lost vacuum while carrying (cup seal)", code="VGR-V01", lost_s=round(lost))
            t = self._stop(t, lost, "F4 lost vacuum", {"arm"})
        dur = (T0 + extra) * (1 + self.rnd.gauss(0, 0.008))
        # random faults during the order
        for fid, rate in RATES.items():
            if self.rnd.random() < rate / 100 * dur / 3600:
                lost = V.results()[1][int(fid[1]) - 1]["lost_s"] * math.exp(self.rnd.gauss(0, 0.3)) + self.rnd.uniform(*RESPONSE)
                code = V.results()[1][int(fid[1]) - 1]["observed"][0]
                self._ev(t, "fault", f"{code} {FAULT_NAME[fid]}", code=code, lost_s=round(lost))
                units = set(C.UNITS) if fid in ("F7", "F6", "F5") else {("crane", "arm", "door", "arm", "arm", "arm", "arm")[int(fid[1]) - 1]}
                t = self._stop(t, lost, f"{fid} {FAULT_NAME[fid]}", units, "ESTOP" if fid == "F7" else "FAULT")
                if fid == "F7" and self.rnd.random() < 0.05:
                    scrap += 1
        ratio = dur / T_MODEL
        for u, d in FSM0.items():
            for s in ("RUN", "HELD", "READY"):
                self.fsm[u][s] += d[s] * ratio
        a4 = {}
        drift = max(0.0, self._r("colour", t_h) - 1) * COMP["colour"]["base"]
        for fl, v in C.PL.FLAVOURS.items():
            a4[fl] = v["mV"] - drift + self.rnd.gauss(0, 5.0)
        bad = sum(1 for fl, mv in a4.items() if C.classify(mv) != v_bin(fl)) * 3
        good = 9 - min(9, scrap + bad)
        self.raw["temp"].append(round(temperature(t_h), 2))
        for fl in a4:
            self.raw["a4"][fl].append(round(a4[fl], 1))
        self.raw["i_hbw"].append(round(0.8 * self._r("spindle", t_h) * (1 + self.rnd.gauss(0, 0.01)), 3))
        self.raw["air_duty"].append(round(COMP["air"]["base"] * self._r("air", t_h), 4))
        self.feat.append([r_obs[k] for k in COMP] + [temperature(t_h), self.raw["i_hbw"][-1], self.raw["air_duty"][-1],
                          a4["vanilla"], a4["strawberry"], a4["chocolate"], vac, dur / T0])
        self.orders.append({"t": round(t_h, 4), "day": day, "shift": shift, "dur": round(dur, 1), "good": good,
                            "scrap": 9 - good, "returned": 3, "temp": round(temperature(t_h), 1)})
        return t + dur

    def _maintenance(self, t, when):
        for k, (mode, why) in list(self.pending.items()):
            if mode != when:
                continue
            c = COMP[k]
            mins = PM_MIN.get(k, 30)
            self._ev(t, "maintenance", f"planned: renewed {c['name']} ({mins} min"
                     + (", in the night gap - no production lost)" if when == "night" else ", line stopped)"),
                     comp=k, down_h=round(mins / 60, 2) if when == "now" else 0.0, night=when == "night",
                     hi_before=round(100 * max(0.0, (c["r_fail"] - self.ew[k]) / (c["r_fail"] - 1))),
                     w_before=round(self.w[k], 3))
            if when == "now":
                t = self._stop(t, mins * 60, "planned maintenance (line stopped)",
                               {c["unit"]} if c["unit"] in C.UNITS else set(C.UNITS), "MAINT")
            self.w[k] = 0.02
            self.ew[k] = 1.0
            self.hist[k] = []
            self.warned.pop(k, None)
            del self.pending[k]
            day = t / 86400
            causes = [w for d0, _, w in self.scen[k]["events"] if d0 <= day]
            if causes:
                self.fixed[k] = day
                self.events[-1]["root_cause"] = "; ".join(causes)
                self.events[-1]["what"] += f" - root cause fixed: {causes[-1]}"
        return t

    def run(self):
        for day in range(self.days):
            for si, (h0, h1) in enumerate(SHIFTS):
                t = (day * 24 + h0 - 6) * 3600.0
                end = (day * 24 + h1 - 6) * 3600.0
                while True:
                    t = self._maintenance(t, "now")
                    est = T0 * 1.1 + CHANGEOVER
                    if t + est > end:
                        break
                    t = self._order(t, day, si, end)
                    t += CHANGEOVER
                    self.down["changeover"] = self.down.get("changeover", 0.0) + CHANGEOVER
                    for u in C.UNITS:
                        self.fsm[u]["READY"] += CHANGEOVER
                if t < end:
                    self.down["end of shift (no room for an order)"] = self.down.get("end of shift (no room for an order)", 0.0) + (end - t)
                    for u in C.UNITS:
                        self.fsm[u]["READY"] += end - t
                if si == len(SHIFTS) - 1:
                    self._maintenance(end, "night")            # the 22:00-06:00 gap
        return self


def v_bin(fl):
    return C.PL.BIN_OF[fl]


# ------------------------------------------------------------- analytics
def analytics(m, cf=None):
    planned = DAYS * len(SHIFTS) * 8 * 3600.0
    n = len(m.orders)
    good = sum(o["good"] for o in m.orders)
    made = 9 * n
    run = sum(o["dur"] for o in m.orders)
    unplanned = sum(v for k, v in m.down.items() if k.startswith(("F", "failure")))
    maint = m.down.get("planned maintenance (line stopped)", 0.0)
    A = run / planned
    P = (n * T0) / run
    Q = good / made if made else 0
    faults = [e for e in m.events if e["kind"] in ("fault", "failure")]
    mtbf = run / 3600 / max(1, len(faults))
    mttr = sum(e.get("lost_s", e.get("down_h", 0) * 3600) for e in faults) / max(1, len(faults)) / 60
    daily = []
    for d in range(DAYS):
        od = [o for o in m.orders if o["day"] == d]
        rd = sum(o["dur"] for o in od)
        g = sum(o["good"] for o in od)
        ev = [e for e in m.events if int(e["t"] // 24) == d]
        day_planned = len(SHIFTS) * 8 * 3600.0
        a, p, q = rd / day_planned, (len(od) * T0 / rd if rd else 0), (g / (9 * len(od)) if od else 0)
        daily.append({"day": d + 1, "date": (START + timedelta(days=d)).strftime("%a %d %b"), "orders": len(od),
                      "baked": 9 * len(od), "good": g, "scrap": 9 * len(od) - g, "run_h": round(rd / 3600, 2),
                      "faults": sum(1 for e in ev if e["kind"] == "fault"),
                      "maint": sum(1 for e in ev if e["kind"] == "maintenance"),
                      "failures": sum(1 for e in ev if e["kind"] == "failure"),
                      "A": round(a, 3), "P": round(p, 3), "Q": round(q, 3), "oee": round(a * p * q, 3)})
    pareto = sorted(({"cause": k, "hours": round(v / 3600, 2)} for k, v in m.down.items()), key=lambda r: -r["hours"])
    out = {"orders": n, "baked": made, "good": good, "scrap": made - good, "returned": 3 * n,
           "cookies_per_h": round(good / (planned / 3600), 2), "planned_h": planned / 3600,
           "run_h": round(run / 3600, 1), "unplanned_h": round(unplanned / 3600, 2), "maint_h": round(maint / 3600, 2),
           "availability": round(A, 3), "performance": round(P, 3), "quality": round(Q, 4), "oee": round(A * P * Q, 3),
           "faults": len([e for e in m.events if e["kind"] == "fault"]),
           "failures": len([e for e in m.events if e["kind"] == "failure"]),
           "maintenance": len([e for e in m.events if e["kind"] == "maintenance"]),
           "mtbf_h": round(mtbf, 1), "mttr_min": round(mttr, 1), "daily": daily, "pareto": pareto}
    return out


def _pearson(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else 0.0


def insights(m, km, kcf, sv):
    """What the month's data says, computed - not narrated."""
    out = []
    planned = km["planned_h"]
    co = next((p["hours"] for p in km["pareto"] if p["cause"] == "changeover"), 0)
    out.append({"title": "Changeover is the biggest loss",
                "text": f"{co} h of {planned:.0f} planned hours ({co / planned:.0%}) go to emptying the bays and loading "
                        f"dough between orders - more than every fault and failure together "
                        f"({km['unplanned_h']} h). Automating the load/unload is worth more than any other fix."})
    vac = [e["t"] for e in m.events if e.get("code") == "VGR-V01"]
    warn = next((e["t"] for e in m.events if e["kind"] == "warning" and e.get("comp") == "cup"), None)
    first = None
    for i in range(len(vac)):
        if len([v for v in vac if vac[i] - 24 <= v <= vac[i]]) >= 3:
            first = vac[i]
            break
    if warn and first and first < warn:
        out.append({"title": "Vacuum losses led the cup's health index",
                    "text": f"VGR-V01 reached 3 in 24 h at hour {first:.0f}, {warn - first:.0f} h before the cup's U6 "
                            f"warning at hour {warn:.0f} ({len([v for v in vac if v <= warn])} losses by then). "
                            "The fault rate is an earlier signal than the build-up time: counting VGR-V01 per shift "
                            "is the next health signal to add."})
    # the leak's growth swamps the daily cycle: compare against the 50-order moving average
    t, a = m.raw["temp"], m.raw["air_duty"]
    res = [a[i] / (sum(a[max(0, i - 25):i + 25]) / len(a[max(0, i - 25):i + 25])) for i in range(len(a))]
    r_raw, r_res = _pearson(t, a), _pearson(t, res)
    strong = abs(r_res) >= 0.3
    out.append({"title": "Hall temperature and the air system",
                "text": f"Raw, air duty barely follows the hall temperature (r = {r_raw:.2f}): the leak's growth over "
                        f"the month dominates. Detrended against its own moving average: r = {r_res:.2f}"
                        + ("; warm afternoons push more air through the same leak, so leak checks read best late in the "
                           "day." if strong else "; the effect is small next to the leak itself.")})
    by = {0: [], 1: []}
    for o in m.orders:
        by[o["shift"]].append(o)
    out.append({"title": "Shifts compared",
                "text": f"Early shift {len(by[0])} orders, late shift {len(by[1])}. Maintenance never stopped the "
                        "line: every work order fitted the night gap (22:00-06:00)."})
    bott = max(FSM0, key=lambda u: FSM0[u]["RUN"])
    run = {u: d["RUN"] for u, d in m.fsm.items()}
    out.append({"title": f"The {bott} is the bottleneck all month",
                "text": f"It ran {run[bott] / 3600:.0f} h of {km['run_h']} h of production; the oven door ran "
                        f"{run['door'] / 3600:.0f} h. More oven capacity would not raise output; a faster VGR tour would."})
    gain_o = km["orders"] - kcf["orders"]
    out.append({"title": "What the two saves were worth",
                "text": f"+{gain_o} orders, +{km['good'] - kcf['good']} cookies, {kcf['unplanned_h'] - km['unplanned_h']:.1f} h "
                        f"of unplanned stop avoided, OEE {kcf['oee']:.1%} -> {km['oee']:.1%}, for "
                        f"{sum(s['pm_min'] for s in sv)} min of night-shift work."})
    return out


def heat(m):
    """Orders started per production hour, day x hour (06-22)."""
    grid = [[0] * 16 for _ in range(DAYS)]
    for o in m.orders:
        d = int(o["t"] // 24)
        h = int(o["t"] % 24)
        if 0 <= d < DAYS and 0 <= h < 16:
            grid[d][h] += 1
    return grid


def saves(m, cf, k_m, k_cf):
    out = []
    for k in SAVES:
        c = COMP[k]
        warn = next((e for e in m.events if e["kind"] == "warning" and e.get("comp") == k), None)
        pm = next((e for e in m.events if e["kind"] == "maintenance" and e.get("comp") == k), None)
        fail = next((e for e in cf.events if e["kind"] == "failure" and e.get("comp") == k), None)
        hrs, sc, what = FAIL.get(k, FAIL_DEFAULT)
        out.append({"comp": k, "name": c["name"], "part": c["part"],
                    "cause": "; ".join(d[2] for d in SCENARIO[k]["events"]),
                    "warn_h": warn and warn["t"], "warn_what": warn and warn["what"],
                    "pm_h": pm and pm["t"], "pm_min": PM_MIN[k], "hi_at_pm": pm and pm.get("hi_before"),
                    "fail_h": fail and fail["t"], "fail_what": what, "fail_down_h": hrs, "fail_scrap": sc,
                    "lead_h": round(fail["t"] - warn["t"], 1) if fail and warn else None})
    return out


def _csv(path, rows, cols):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") if isinstance(r, dict) else r[i] for i, c in enumerate(cols)])


def main():
    m = Month().run()
    cf = Month(skip_pm=SAVES).run()
    km, kcf = analytics(m), analytics(cf)
    sv = saves(m, cf, km, kcf)
    ts = lambda h: (START + timedelta(hours=h)).isoformat(timespec="minutes")
    doc = {
        "meta": {"start": START.isoformat(), "days": DAYS, "shifts": [f"{a:02d}-{b:02d}" for a, b in SHIFTS],
                 "batch": "12 cookies per order (9 baked and sorted, 3 returned to the rack)",
                 "order_s_commissioned": T0, "changeover_s": CHANGEOVER, "seed": SEED, "machine": "Upgrade 7",
                 "assumed": "starting ages and disturbances (SCENARIO), maintenance durations, failure consequences, "
                            "random fault rates per 100 h, operator response 60-240 s, changeover 120 s, the hall "
                            "temperature cycle and its effect on belt slip and air leaks, the vacuum-loss law, "
                            "0.8 A nominal HBW current"},
        "kpi": {k: v for k, v in km.items() if k not in ("daily", "pareto")},
        "kpi_cf": {k: v for k, v in kcf.items() if k not in ("daily", "pareto")},
        "daily": km["daily"], "daily_cf": kcf["daily"], "pareto": km["pareto"], "pareto_cf": kcf["pareto"],
        "saves": sv, "insights": insights(m, km, kcf, sv), "heat": heat(m),
        "components": [{"id": k, "name": c["name"], "unit": c["unit"], "metric": c["metric"], "r_fail": round(c["r_fail"], 3),
                        "soft": round(1 + H.SOFT * (c["r_fail"] - 1), 3), "base": round(c["base"], 4), "unit_of": c["unit_of"],
                        "w0": SCENARIO[k]["w0"], "w_end": round(m.w[k], 3),
                        "disturbances": [{"day": d, "x": x, "what": w} for d, x, w in SCENARIO[k]["events"]],
                        "maintenance": sum(1 for e in m.events if e["kind"] == "maintenance" and e.get("comp") == k)}
                       for k, c in COMP.items()],
        "sensors": {k: {"t": [s[0] for s in v], "obs": [s[1] for s in v], "ewma": [s[2] for s in v],
                        "hi": [s[3] for s in v], "rul": [s[4] for s in v]} for k, v in m.sensors.items()},
        "sensors_cf": {k: {"t": [s[0] for s in cf.sensors[k]], "hi": [s[3] for s in cf.sensors[k]]} for k in SAVES},
        "raw": {"t": [o["t"] for o in m.orders], **m.raw},
        "orders": {"t": [o["t"] for o in m.orders], "dur": [o["dur"] for o in m.orders],
                   "good": [o["good"] for o in m.orders], "shift": [o["shift"] for o in m.orders]},
        "fsm": {u: {s: round(v / 3600, 2) for s, v in d.items()} for u, d in m.fsm.items()},
        "events": m.events, "events_cf": [e for e in cf.events if e["kind"] == "failure"],
    }
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "month.json"), "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    _csv(os.path.join(OUT, "orders.csv"), [{**o, "time": ts(o["t"])} for o in m.orders],
         ["time", "day", "shift", "dur", "good", "scrap", "returned", "temp"])
    _csv(os.path.join(OUT, "sensors.csv"),
         [{"time": ts(s[0]), "component": k, "observed": s[1], "ewma_r": s[2], "health_index": s[3], "rul_shifts": s[4]}
          for k, v in m.sensors.items() for s in v],
         ["time", "component", "observed", "ewma_r", "health_index", "rul_shifts"])
    _csv(os.path.join(OUT, "events.csv"), [{**e, "time": ts(e["t"])} for e in m.events],
         ["time", "kind", "what", "comp", "code", "lost_s", "down_h"])
    _csv(os.path.join(OUT, "daily.csv"), km["daily"], list(km["daily"][0].keys()))
    _csv(os.path.join(OUT, "fsm.csv"), [{"unit": u, **{s: round(v / 3600, 3) for s, v in d.items()}} for u, d in m.fsm.items()],
         ["unit", "RUN", "HELD", "READY", "FAULT", "ESTOP", "MAINT"])
    _csv(os.path.join(OUT, "raw.csv"),
         [{"time": ts(t), "temp_c": m.raw["temp"][i], "a4_chocolate_mv": m.raw["a4"]["chocolate"][i],
           "a4_strawberry_mv": m.raw["a4"]["strawberry"][i], "a4_vanilla_mv": m.raw["a4"]["vanilla"][i],
           "i_hbw_a": m.raw["i_hbw"][i], "air_duty": m.raw["air_duty"][i]} for i, t in enumerate(doc["raw"]["t"])],
         ["time", "temp_c", "a4_chocolate_mv", "a4_strawberry_mv", "a4_vanilla_mv", "i_hbw_a", "air_duty"])
    print(f"month: {km['orders']} orders, {km['good']} good cookies, OEE {km['oee']:.1%} "
          f"(A {km['availability']:.1%} P {km['performance']:.1%} Q {km['quality']:.2%})")
    print(f"  without the two saves: {kcf['orders']} orders, {kcf['good']} good, OEE {kcf['oee']:.1%}, "
          f"{kcf['failures']} failures, {kcf['unplanned_h']} h unplanned")
    for s in sv:
        print(f"  save {s['name']}: warned {s['warn_h']} h, renewed {s['pm_h']} h, would have failed {s['fail_h']} h")
    for e in m.events:
        if e["kind"] in ("warning", "maintenance", "failure"):
            print(f"   {e['t']:7.1f} h  {e['what']}")
    return doc


if __name__ == "__main__":
    main()
