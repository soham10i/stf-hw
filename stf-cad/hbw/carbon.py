"""
Upgrade 18 - the carbon footprint of a cookie, and the levers that cut it.

    STF_VARIANT=up7 python3 carbon.py        (from stf-cad/hbw; or `make carbon`)

U9 simulated a month of the cell on its microgrid (grid.py): every 15 minutes the load,
the PV, the battery and the grid import, with the grid's carbon intensity at that hour.
This module turns that into grams of CO2e per good cookie and per order, says where they
come from, and re-runs the same month through the same energy manager with each lever:

  ALLOCATION  each 15-min step's emissions (grid import x that hour's intensity) are shared
              between what drew the power in that step: standing load (controller, I/O,
              switch, sensors, inverter), the motors by unit, the lamp and valves, the
              compressor. Whole-month totals divided by the good cookies.
  LEVERS      grid only (no PV, no battery) | as built (PV + battery + EMS) | + SLEEP: the
              I/O nodes, RFID heads and sensors switched off when the cell is idle for more
              than SLEEP_AFTER_H | + CARBON-AWARE: the EMS plans the battery against the
              grid's carbon intensity instead of the price | + U10: the faster program
              makes more cookies in the same shifts, so the standing load is shared by more
Operational (scope 2, location-based) emissions only, no credit for exported PV; the
intensity profile, the ratings and the sleep figures are ASSUMED (grid.py lists them).
Writes web/public/carbon/carbon.json.
"""
import json
import os
import random

import grid as G
import month as M

PUB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web", "public"))
OUT = os.path.join(PUB, "carbon", "carbon.json")
SLEEP_AFTER_H = 0.5
AWAKE_W = {"RevPi Core 3": 4.0, "Ethernet switch": 3.0, "safety relay + contactors": 3.0, "electronic breaker": 2.0}
U10_GAIN = None          # filled from throughput.json: cookies per hour, U10 / U7


def breakdown(m, s, lp):
    """Emissions per component (g) for one simulated month."""
    standby = sum(G.STANDBY_W.values()) / G.PSU_EFF
    inv = G.INV_STANDBY
    share = lp["unit_run_share"]
    motors = {u: G.UNIT_MOTORS[u] * share[u] for u in G.UNIT_MOTORS}
    lamp_valves = lp["production_w"] - sum(motors.values())
    duty = sum(m.raw["air_duty"]) / len(m.raw["air_duty"])
    comp = G.COMPRESSOR_W * duty
    prod_parts = {**{f"motor: {u}": w for u, w in motors.items()}, "lamp and valves": lamp_valves, "compressor": comp}
    prod_tot = sum(prod_parts.values())
    out = {"controller, I/O and sensors (standing)": 0.0, "inverter (standing)": 0.0, **{k: 0.0 for k in prod_parts}}
    for L, g, c in zip(s["load"], s["grid"], s["co2"], strict=True):
        e = max(0.0, g) * G.STEP_H / 1000 * c                     # g CO2e in this step
        if e <= 0 or L <= 0:
            continue
        stand = min(L, standby + inv)
        prod = max(0.0, L - stand)
        out["controller, I/O and sensors (standing)"] += e * min(standby, stand) / L
        out["inverter (standing)"] += e * max(0.0, stand - standby) / L
        for k, w in prod_parts.items():
            out[k] += e * prod * (w / prod_tot) / L
    return out


def sleep_profile(orig):
    """The load profile with the cell asleep whenever it has been idle SLEEP_AFTER_H."""
    def lp(m, days):
        load, prod, info = orig(m, days)
        awake = sum(G.STANDBY_W.values()) / G.PSU_EFF
        asleep = sum(AWAKE_W.values()) / G.PSU_EFF
        k_after = int(SLEEP_AFTER_H / G.STEP_H)
        idle = 0
        load = list(load)
        for k in range(len(load)):
            idle = idle + 1 if prod[k] == 0 else 0
            if idle > k_after:
                load[k] -= awake - asleep
        return load, prod, info
    return lp


def run(m, weath, scenario, sleep=False, carbon=False):
    orig_lp, orig_price = G.load_profile, G.price
    try:
        if sleep:
            G.load_profile = sleep_profile(orig_lp)
        if carbon:                                  # plan the battery against carbon, not money
            G.price = lambda day, h, rnd_day: G.co2(h) / 1000
        s, lp, *_ = G.simulate(m, scenario, weath)
    finally:
        G.load_profile, G.price = orig_lp, orig_price
    return s, lp


def main():
    m = M.Month().run()
    weath = G.weather(random.Random(G.SEED), M.DAYS)
    good = sum(o["good"] for o in m.orders)
    orders = len(m.orders)
    tp = json.load(open(os.path.join(PUB, "throughput", "throughput.json")))
    gain = tp["ablation"][-1]["per_hour"] / tp["ablation"][0]["per_hour"]
    cases = [("grid only", dict(scenario="grid")), ("as built: PV + battery", dict(scenario="pv+battery")),
             ("+ sleep when idle", dict(scenario="pv+battery", sleep=True)),
             ("+ carbon-aware battery", dict(scenario="pv+battery", sleep=True, carbon=True))]
    res, series = {}, {}
    for name, kw in cases:
        s, lp = run(m, weath, **kw)
        k = G.kpis(s, M.DAYS)
        res[name] = {"co2_kg": k["co2_kg"], "g_per_cookie": round(1000 * k["co2_kg"] / good, 3),
                     "load_kwh": k["load_kwh"], "import_kwh": k["import_kwh"], "cost_eur": k["total_eur"],
                     "wh_per_cookie": round(1000 * k["load_kwh"] / good, 2)}
        series[name] = (s, lp)
    last = res["+ carbon-aware battery"]
    # U10: the same shifts make gain x the cookies; the standing load is shared by more (the
    # motion per cookie is unchanged). Applied to the last case's split, stated as an estimate.
    s_last, lp_last = series["+ carbon-aware battery"]
    b_last = breakdown(m, s_last, lp_last)
    stand_last = sum(v for k, v in b_last.items() if "standing" in k)
    u10 = (last["co2_kg"] * 1000 - stand_last + stand_last / gain) / good
    res["+ U10 throughput (estimate)"] = {"co2_kg": None, "g_per_cookie": round(u10, 3), "estimate": True,
                                         "note": f"standing load shared by {gain:.2f}x the cookies in the same shifts"}
    s0, lp0 = series["as built: PV + battery"]
    b0 = breakdown(m, s0, lp0)
    # the hour of the day: intensity, the cell's import and when it produces
    hours = []
    sg = series["grid only"][0]
    per_day = int(24 / G.STEP_H)
    for h in range(24):
        idx = [d * per_day + h * 4 + q for d in range(M.DAYS) for q in range(4)]
        hours.append({"h": h, "intensity": round(sum(s0["co2"][i] for i in idx) / len(idx), 1),
                      "import_w": round(sum(max(0.0, s0["grid"][i]) for i in idx) / len(idx), 1),
                      "grid_only_w": round(sum(max(0.0, sg["grid"][i]) for i in idx) / len(idx), 1),
                      "pv_w": round(sum(s0["pv"][i] for i in idx) / len(idx), 1),
                      "load_w": round(sum(s0["load"][i] for i in idx) / len(idx), 1)})
    # per day: g per cookie as built
    daily = []
    for d in range(M.DAYS):
        idx = range(d * per_day, (d + 1) * per_day)
        e = sum(max(0.0, s0["grid"][i]) * G.STEP_H / 1000 * s0["co2"][i] for i in idx)
        g_d = sum(o["good"] for o in m.orders if o["day"] == d + 1)
        daily.append({"day": d + 1, "g_per_cookie": round(e / g_d, 3) if g_d else None, "weather": weath[d]["kind"]})
    tot = sum(b0.values())
    out = {"meta": {"days": M.DAYS, "good_cookies": good, "orders": orders, "cookies_per_order": round(good / orders, 2),
                    "sleep_after_h": SLEEP_AFTER_H, "sleep_w": round(sum(AWAKE_W.values()) / G.PSU_EFF, 1),
                    "awake_w": round(sum(G.STANDBY_W.values()) / G.PSU_EFF, 1), "inverter_w": G.INV_STANDBY,
                    "u10_gain": round(gain, 3), "scope": "operational, location-based (scope 2); no credit for exported PV",
                    "assumed": "the grid's carbon-intensity profile, every power rating, the sleep figures; U10 as an estimate"},
           "levers": res,
           "breakdown_g_per_cookie": {k: round(v / good, 4) for k, v in sorted(b0.items(), key=lambda kv: -kv[1])},
           "standing_share": round(sum(v for k, v in b0.items() if "standing" in k) / tot, 3),
           "hours": hours, "daily": daily}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    for k, v in res.items():
        print(f"  {k:30s} {v['g_per_cookie']:.3f} g CO2e per cookie")
    print(f"  standing load: {out['standing_share']:.0%} of the as-built footprint")
    for k, v in out["breakdown_g_per_cookie"].items():
        print(f"    {k:42s} {v:.4f} g")
    fails = []
    if abs(res["as built: PV + battery"]["co2_kg"] - json.load(open(os.path.join(PUB, "grid", "grid.json")))["scenarios"]["pv+battery"]["co2_kg"]) > 0.01:
        fails.append("CONSISTENCY: the as-built month differs from grid.json")
    if abs(tot / 1000 - res["as built: PV + battery"]["co2_kg"]) > 0.01:
        fails.append("ALLOCATION: the parts do not add up to the total")
    print("\n".join(fails) if fails else "CARBON OK (the month matches grid.json; the parts add up)")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if main() else 0)
