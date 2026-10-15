"""
Upgrade 6 - condition monitoring and predictive maintenance (STF_VARIANT=up6).

Upgrade 4 put a watchdog on every step and Upgrade 5 measured how close a
healthy step comes to it. A worn part does not fail at once: its steps get
slower (or its current, air use or colour margin drifts) cycle after cycle,
until the watchdog trips and the line stops. This module watches for that.

  SIGNALS   one health signal per component, from data the program already
            has: the step times it measures (U4), the reed, vacuum and
            pressure switches (U5), the A4 colour margin, and one new
            reading - the actuator current per module from the U3 electronic
            breaker's IO-Link channel.
  MODEL     r = observed / healthy baseline, smoothed by an EWMA.
            It fails when r reaches the tightest step's watchdog (or the
            breaker trips, or the compressor can no longer hold pressure, or
            a flavour crosses its band). Two warnings:
              soft limit  EWMA past SOFT of the way from healthy to failure;
              predictive  a trend fitted over the last WINDOW cycles gives
                          fewer than RUL_WARN cycles left.
            Health index HI = 100 x the margin left.
  PROOF     for every degradation injected into the twin, a warning comes at
            least one shift before the failure; and a healthy machine, run
            for HEALTHY_CYCLES cycles with its measured noise, raises none.
            A failure with no gradual precursor (a switch that just breaks) is
            listed as detect-only: the U4 watchdog and a preventive check
            cover it.
Assumed and flagged: every wear law and its life, the noise, the breaker
trip, and the air figures.
"""
import math
import random

import control as C
import vc as V

EWMA = 0.02            # smoothing per observation
SOFT = 0.50            # warn when half the margin to failure is used
WINDOW = 400           # trend window, observations
RUL_WARN_SHIFTS = 3.0  # warn when fewer than three shifts of cycles are left
SHIFT_H = 8.0
HEALTHY_CYCLES = 60000
NOISE = 0.02           # 2 % cycle-to-cycle spread of a physical step (ASSUMED)
ECB_TRIP = 1.5         # electronic breaker trips at 1.5 x the nominal current (ASSUMED)


def _uses():
    """How many times each (unit, done) step runs in one order, with the
    steps themselves: from the PLC's nominal run."""
    _, ev, T, _ = C.simulate(C.PLC_POLICY)
    out = {}
    for t, what, job in ev:
        if what != "start":
            continue
        for st in C.job_steps(job):
            out.setdefault((st.unit, st.done), []).append(st)
    return out, T


USES, ORDER_T = _uses()
ORDERS_PER_SHIFT = SHIFT_H * 3600 / V.results()[0].makespan


def _steps(pred):
    return [st for (u, d), sts in USES.items() for st in sts if pred(st)]


def _baseline(sts):
    """Per step: the healthy observed time (plant + both bus hops) and its
    watchdog. The tightest ratio limit/baseline is where the part fails."""
    base = [(V.phys(st) + 2 * V.BUS, st.limit) for st in sts if st.limit]
    r_fail = min(lim / b for b, lim in base)
    b_mean = sum(b for b, _ in base) / len(base)
    # the scan quantises every reading: that is noise too
    sig = math.sqrt(NOISE ** 2 + (V.SCAN["default"] / b_mean) ** 2 / 12)
    return r_fail, b_mean, sig


# ------------------------------------------------------------- components
def components():
    """(id, name, part, unit, signal kind, source signals, the steps it watches)."""
    return [
        dict(id="cup", name="VGR suction cup seal", part="suction_cup", unit="arm", kind="time",
             source=["vgr.Q8", "vgr.I4"], metric="vacuum build-up time (Q8 on -> I4 made)",
             steps=lambda st: st.unit == "arm" and st.done == "I4", life=150_000, p=3, wear=True),
        dict(id="door", name="oven door cylinder", part="Q13_door_cylinder", unit="door", kind="time",
             source=["oven.Q13", "oven.I10", "oven.I11"], metric="reed-to-reed travel time",
             steps=lambda st: st.unit == "door" and st.done in ("I10", "I11"), life=400_000, p=2, wear=True),
        dict(id="lower", name="Sauger lowering cylinder", part="Q12_lower_cylinder", unit="sauger", kind="time",
             source=["oven.Q12", "oven.I12", "oven.I13"], metric="reed-to-reed travel time",
             steps=lambda st: st.unit == "sauger" and st.done in ("I12", "I13"), life=400_000, p=2, wear=True),
        dict(id="pusher", name="Auswerfer cylinder", part="Q14_pusher_cylinder", unit="turntable", kind="time",
             source=["oven.Q14", "oven.I14", "oven.I15"], metric="reed-to-reed travel time",
             steps=lambda st: st.unit == "turntable" and st.done in ("I14", "I15"), life=400_000, p=2, wear=True),
        dict(id="belt", name="HBW belt", part="cv_belt_L", unit="belt", kind="time",
             source=["hbw.Q1", "hbw.Q2", "hbw.I2", "hbw.I3"], metric="I2 <-> I3 transit time (slip)",
             steps=lambda st: st.unit == "belt" and st.key.startswith("run"), life=60_000, p=2, wear=True),
        dict(id="rfid", name="RFID read heads", part="rfid_rp2_head", unit="belt", kind="time",
             source=["hbw.RF2"], metric="read time incl. retries",
             steps=lambda st: st.unit == "belt" and "RF2" in st.done, life=500_000, p=4, wear=False),
        dict(id="spindle", name="HBW travel spindle + nut", part="travel_spindle", unit="crane", kind="current",
             source=["cabinet.ecb_4ch.ch1.current", "hbw.B1/B2"],
             metric="actuator current on the HBW feed, and move time",
             steps=lambda st: st.unit == "crane" and st.key.startswith("travel"), life=300_000, p=2, wear=True),
        dict(id="gearbox", name="VGR swivel gearbox (sudden-onset wear)", part="M3_swivel_motor", unit="arm",
             kind="time", source=["vgr.Q5", "vgr.Q6", "vgr.B5/B6"], metric="swivel move time per degree",
             steps=lambda st: st.unit == "arm" and st.dist.get("swivel", 0) > 0, life=200_000, p=10, wear=True),
        dict(id="air", name="air supply (leaks)", part="air_manifold", unit="system", kind="duty",
             source=["vgr.I5"], metric="compressor duty cycle (pressure-switch on-time)",
             steps=None, life=2_000, p=1.5, wear=False),
        dict(id="colour", name="colour sensor A4 (LED ageing)", part="colour_sensor", unit="line", kind="margin",
             source=["sorting.A4"], metric="margin of each flavour's reading to its band edge",
             steps=lambda st: st.unit == "line" and st.key == "classify", life=40_000, p=1, wear=False),
    ]


def _per_cycle(c):
    """Observations of this component per order."""
    if c["kind"] == "duty":
        return 1                                    # one duty figure per order
    return len(_steps(c["steps"]))


# --------------------------------------------------------------- air model
def air_duty0():
    """Healthy compressor duty over one order: every cylinder stroke and every
    second of vacuum, against the compressor's free-air delivery (ASSUMED
    figures: 10 mm bore x 30 mm stroke at 0.7 bar = 4 cm3 free air per stroke;
    the vacuum ejector 0.3 l/min while on; the pump 1.0 l/min)."""
    strokes = len(_steps(lambda st: st.unit in ("door", "sauger", "turntable", "line") and V.pneumatic(st)))
    vac_s = sum(st.t for st in _steps(lambda st: st.unit == "arm" and "Q8" in st.out))
    use_l = strokes * 0.004 + vac_s / 60 * 0.3
    return use_l / (ORDER_T / 60 * 1.0)


def colour_margin():
    """mV between each flavour's nominal reading and the band edge its reading
    drifts towards (an ageing LED reads darker: down)."""
    out = []
    for fl, v in C.PL.FLAVOURS.items():
        lo, _ = C.BAND[v["bin"]]
        if lo > 0:
            out.append(v["mV"] - lo)
    return min(out)


# ------------------------------------------------------------ simulation
def simulate(c, degrade=True, n_max=None, seed=1):
    """Run one component cycle by cycle (one cycle = one use of its step).
    Returns the curve sampled for the dashboard, the warning cycle and the
    failure cycle."""
    rnd = random.Random(seed)
    life = c["life"]
    if c["kind"] == "time":
        r_fail, _, sig = _baseline(_steps(c["steps"]))
    elif c["kind"] == "current":
        _, _, sig = _baseline(_steps(c["steps"]))
        r_fail = ECB_TRIP
    elif c["kind"] == "duty":
        d0 = air_duty0()
        r_fail, sig = 1.0 / d0, 0.03            # duty 1.0 = the pump can no longer keep up
    else:
        # colour margin: r = 1 + drift / the smallest reading-to-band-edge margin,
        # so r = 2 is the first flavour crossing into its neighbour's band
        m = colour_margin()
        r_fail, sig = 2.0, 5.0 / m              # A4 reads +-5 mV cycle to cycle (ASSUMED)
    n_max = n_max or int(life * 1.2)
    ew, hist, warn, fail = 1.0, [], None, None
    curve, stride = [], max(1, n_max // 240)
    soft = 1 + SOFT * (r_fail - 1)
    per_shift = _per_cycle(c) * ORDERS_PER_SHIFT
    rul_warn = RUL_WARN_SHIFTS * per_shift
    for n in range(n_max):
        u = n / life
        wear = (r_fail - 1) * u ** c["p"] if degrade else 0.0
        r_true = 1 + wear
        obs = r_true * (1 + rnd.gauss(0, sig))
        ew = obs if n == 0 else ew + EWMA * (obs - ew)
        hist.append(ew)
        rul = None
        if len(hist) >= WINDOW and n % 50 == 0:
            y0, y1 = hist[-WINDOW], hist[-1]
            slope = (y1 - y0) / WINDOW
            rul = (r_fail - y1) / slope if slope > 1e-12 else float("inf")
        if warn is None and n > WINDOW and (ew >= soft or (rul is not None and rul < rul_warn)):
            warn = (n, "soft limit" if ew >= soft else "trend: RUL below 3 shifts")
        if fail is None and r_true >= r_fail:
            fail = n
        if n % stride == 0:
            hi = max(0.0, min(1.0, (r_fail - ew) / (r_fail - 1)))
            curve.append([n, round(ew, 4), round(100 * hi, 1), None if rul is None or rul == float("inf") else round(rul)])
        if fail is not None and n > fail + stride:
            break
    return {"r_fail": round(r_fail, 3), "soft": round(soft, 3), "warn": warn, "fail": fail, "curve": curve,
            "per_order": _per_cycle(c), "per_shift": round(per_shift, 1)}


def run():
    rows = []
    for c in components():
        deg = simulate(c, True)
        ok = simulate(c, False, n_max=HEALTHY_CYCLES, seed=7)
        lead = None if not deg["warn"] or deg["fail"] is None else deg["fail"] - deg["warn"][0]
        lead_sh = None if lead is None else round(lead / deg["per_shift"], 1)
        rows.append({"id": c["id"], "name": c["name"], "part": c["part"], "unit": c["unit"], "kind": c["kind"],
                     "metric": c["metric"], "source": c["source"], "life": c["life"], "wear_part": c["wear"],
                     "r_fail": deg["r_fail"], "soft": deg["soft"], "per_order": deg["per_order"],
                     "per_shift": deg["per_shift"],
                     "warn": deg["warn"][0] if deg["warn"] else None, "warn_by": deg["warn"][1] if deg["warn"] else None,
                     "fail": deg["fail"], "lead_cycles": lead, "lead_shifts": lead_sh,
                     "false_warnings": 1 if ok["warn"] else 0, "healthy_cycles": HEALTHY_CYCLES,
                     "curve": deg["curve"],
                     "pm_interval": int(0.7 * c["life"]), "pm_shifts": round(0.7 * c["life"] / deg["per_shift"], 1)})
    return rows


DETECT_ONLY = [
    ("reed / reference switch breaks", "no precursor: the U4 watchdog trips on the next step",
     "preventive: switch test at every PM visit"),
    ("light barrier dirty", "no trend in a step time until it misses", "preventive: clean at every PM visit"),
    ("encoder cable breaks in a drag chain", "sudden: counter stops (watchdog)",
     "the U3 chain rows give the bend count; replace at chain life"),
]


# ------------------------------------------------------------ data path
def topics(rows):
    """What the PLC publishes (MQTT, JSON) for the dashboard and the historian."""
    out = []
    for r in rows:
        out.append({"topic": f"stf/health/{r['id']}", "rate": f"per use ({r['per_order']} per order)",
                    "fields": "t, observed_s, baseline_s, r, ewma, hi, rul_cycles, cycle_count",
                    "sources": r["source"]})
    out += [{"topic": "stf/state/<unit>", "rate": "on change", "fields": "state, job, step, t",
             "sources": ["PLC SFC states (U4)"]},
            {"topic": "stf/alarm", "rate": "on change", "fields": "code, text, t_raised, t_acked, t_cleared",
             "sources": ["U4 alarm list"]},
            {"topic": "stf/trace/<cookie>", "rate": "per record event", "fields": "the ST_Cookie record (U4)",
             "sources": ["hbw.RF1", "hbw.RF2", "sorting.A4"]},
            {"topic": "stf/oee", "rate": "per order", "fields": "availability, performance, quality, order_s",
             "sources": ["PLC order log"]}]
    return out


def check_topics(rows):
    """Every health signal comes from a signal on the U5 register map, or from
    the one new reading this upgrade adds (the breaker's current)."""
    mapped = {r["twin"] for r in V.signal_map()}
    fails = []
    for r in rows:
        for s in r["source"]:
            if s.startswith("cabinet."):
                continue
            if s not in mapped:
                fails.append(f"TOPIC {r['id']}: source {s} is not on the register map")
    return fails


def check(verbose=True):
    rows = run()
    fails = []
    for r in rows:
        if r["false_warnings"]:
            fails.append(f"FALSE WARNING {r['id']}: a healthy machine warned within {HEALTHY_CYCLES} cycles")
        if r["warn"] is None:
            fails.append(f"MISSED {r['id']}: failure at cycle {r['fail']} with no warning")
        elif r["lead_shifts"] is None or r["lead_shifts"] < 1.0:
            fails.append(f"LATE {r['id']}: warning only {r['lead_shifts']} shifts before failure (need 1)")
    fails += check_topics(rows)
    if verbose:
        for r in rows:
            print(f"  {r['id']:8s} warn {r['warn']} ({r['warn_by']})  fail {r['fail']}  lead {r['lead_shifts']} shifts")
        print("\n".join(fails) if fails else "HEALTH OK (every degradation warned >= 1 shift ahead, no false warnings)")
    _CACHE["rows"] = rows
    return fails


_CACHE = {}


def export():
    rows = _CACHE.get("rows") or run()
    return {"components": rows, "detect_only": [{"mode": a, "why": b, "cover": c} for a, b, c in DETECT_ONLY],
            "topics": topics(rows), "orders_per_shift": round(ORDERS_PER_SHIFT, 1), "shift_h": SHIFT_H,
            "air_duty0": round(air_duty0(), 3),
            "rules": {"ewma": EWMA, "soft": SOFT, "window": WINDOW, "rul_warn_shifts": RUL_WARN_SHIFTS,
                      "noise": NOISE, "ecb_trip": ECB_TRIP},
            "new_hardware": "actuator current per module: the U3 electronic breaker's IO-Link channel "
                            "(4 readings, 100 ms) into the RevPi",
            "assumed": "wear laws and lives, 2 % step noise, breaker trip 1.5 x, compressor 1 l/min, "
                       "4 cm3 per stroke, ejector 0.3 l/min, LED drift"}


if __name__ == "__main__":
    import sys
    sys.exit(1 if check() else 0)
