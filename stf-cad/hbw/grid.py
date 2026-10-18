"""
Upgrade 9 - the cell as a microgrid (STF_VARIANT=up7; runs over month.py's month).

  ASSETS    mains (230 V AC) -> a hybrid inverter/charger (600 W, online
            UPS mode) with a 1 kWh LFP battery and 400 Wp of PV on the hall
            roof -> the 24 V PSU -> the four breaker channels (U3). The PSU,
            breaker and inverter report over Modbus (SunSpec models for the
            inverter and battery); a cabinet temperature sensor is added.
  LOAD      from the month itself, every 15 minutes: the standing load (PLC,
            nodes, switch, sensors, PSU and inverter losses) plus, while an
            order runs, each unit's motors at the share of time its state
            machine is RUN (U4), the oven lamp, the valves and the compressor
            at the order's measured air duty (month.py).
  OVEN      Upgrade 19's real oven (bake.py, web/public/bake/process.json):
            1 300 W of elements, preheated once a day before the early shift
            and held at 180 C through both shifts. It runs on its own 230 V
            circuit behind the same meter (the 600 W inverter cannot carry
            it): the battery and PV offset it behind the meter, but it is not
            on the UPS. A resized microgrid that carries it is compared.
  EMS       every day at midnight: a dynamic programme over the battery's
            state of charge (50 Wh steps, 15-minute steps) against the day-
            ahead forecast of PV and load, minimising import cost + a battery
            wear cost, with hard limits: a ride-through RESERVE, the demand-
            response windows' import cap, and a peak-shaving cap. The day is
            then played with the real PV and load; the grid takes the
            difference, the battery covers it inside a DR window.
  GRID      three OpenADR-style demand-response events; two mains outages
            and eight voltage sags (EN 50160 classes). The PSU holds up for
            20 ms on its own: longer, and without the inverter the 24 V
            collapses, the PLC restarts and the order in progress is redone.
  HEALTH    power assets with their own predictive maintenance: the PSU's
            electrolytic capacitors age by the Arrhenius 10 K rule with the
            cabinet temperature, which rises as the cabinet air filter clogs;
            PV soiling is seen as a falling performance ratio; the battery's
            state of health follows cycle and calendar ageing.
Scenarios compared: grid only, PV only, PV + battery with the EMS. Every
number that is not derived from the models is ASSUMED and listed.
"""
import json
import math
import os
import random

import month as M

OUT = os.path.expanduser("~/workspace/stf-hw/web/public/grid")
STEP_H = 0.25
N_DAY = 96
SEED = 90

# ---------------------------------------------------------------- assets (ASSUMED sizes)
PV_WP = 400.0
BATT_WH = 1000.0
SOC_MIN, SOC_MAX = 0.10, 1.00
RESERVE = 0.30                 # ride-through reserve: 30 % = ~3 h of production load
P_BATT = 500.0                 # W charge / discharge
ETA = 0.95                     # each way
INV_STANDBY = 8.0              # W
INV_W = 600.0                  # W: the inverter's AC rating
PEAK_CAP = 300.0               # W: the site's peak-shaving target - below the ~370 W of cell + held oven, so it shaves
PEAK_CAP_CELL = 70.0           # W: Upgrade 9's target for the cell alone (below its natural ~86 W peak)
DR_CAP = 15.0                  # W: import cap during a demand-response event
DR_FLOOR = {"soc": SOC_MIN}    # how low a DR window may take the battery (Upgrade 12 raises it to RESERVE)
DEG_EUR_KWH = 0.06             # battery wear per kWh throughput
PSU_EFF = 0.90

# ---------------------------------------------------------------- load model (ASSUMED ratings)
STANDBY_W = {"RevPi Core 3": 4.0, "4 remote I/O nodes": 12.0, "Ethernet switch": 3.0, "safety relay + contactors": 3.0,
             "sensors, light barriers, reeds": 5.0, "2 RFID heads": 4.0, "electronic breaker": 2.0}
MOTOR_W = 24 * 0.35             # an ft encoder / S-motor running
UNIT_MOTORS = {"crane": MOTOR_W, "belt": MOTOR_W, "arm": MOTOR_W, "door": MOTOR_W + 2.0, "sauger": MOTOR_W + 2.0,
               "turntable": MOTOR_W, "ovenbelt": MOTOR_W, "line": MOTOR_W}
LAMP_W = 5.0
COMPRESSOR_W = 24 * 1.5

# ---------------------------------------------------------------- the real oven (Upgrade 19, from bake.py)
BAKE_F = os.path.join(os.path.dirname(OUT), "bake", "process.json")
OVEN_SUPPLY = {"ups": False}   # False: its own 230 V circuit behind the meter; True: on the inverter's output
OVEN_ON = {"on": True}         # False: the cell alone, as Upgrade 9 first sized it
# a microgrid big enough to carry the oven on the UPS (ASSUMED sizes and prices)
RESIZED = {"INV_W": 2000.0, "BATT_WH": 3000.0, "P_BATT": 1500.0, "PV_WP": 1200.0}
RESIZED_CAPEX = {"hybrid inverter 2 kW": 900, "LFP battery 3 kWh": 1150, "PV 1.2 kWp + mounting": 1050,
                 "cabinet temp sensor": 25, "energy meter (SunSpec/Modbus)": 90}


def oven_params():
    """The oven as bake.py measured it: rated power, the preheat, the mean draw through a shift."""
    b = json.load(open(BAKE_F))
    p = {r["key"]: r["value"] for r in b["params"]}
    return {"rated_w": p["p_top"] + p["p_bot"], "preheat_kwh": b["heatup"]["preheat_kwh"],
            "preheat_s": b["heatup"]["t180"], "hold_w": b["heatup"]["hold_w"],
            "shift_w": round(1000 * b["energy"]["kwh_per_shift_h"], 1), "wh_per_cookie": b["energy"]["wh_per_cookie"],
            "useful_share": round((b["energy"]["ledger_kwh"]["cookie"] + b["energy"]["ledger_kwh"]["steam"])
                                  / b["energy"]["ledger_kwh"]["heater"], 3)}


def oven_profile(days):
    """W per 15 min: the preheat in the quarter before 06:00, then the mean draw of a shift
    (thermostat cycling and door openings, bake.py) until 22:00."""
    if not OVEN_ON["on"]:
        return [0.0] * (days * N_DAY)
    o = oven_params()
    h0, h1 = M.SHIFTS[0][0], M.SHIFTS[-1][1]
    day = [0.0] * N_DAY
    day[int(h0 / STEP_H) - 1] = o["preheat_kwh"] * 1000 / STEP_H
    for k in range(int(h0 / STEP_H), int(h1 / STEP_H)):
        day[k] = o["shift_w"]
    return day * days

# ---------------------------------------------------------------- tariff (ASSUMED, EU dynamic-tariff style)
FEED_IN = 0.08
DEMAND_EUR_KW = 12.0


def price(day, h, rnd_day):
    base = 0.22 if (h < 6 or h >= 22) else 0.42 if 17 <= h < 21 else 0.30
    return round(base * rnd_day * (1 + 0.08 * math.sin(2 * math.pi * (h - 3) / 24)), 4)


def co2(h):
    """g/kWh: sunny middays are cleaner, the evening peak dirtier (ASSUMED profile)."""
    return 300 - 90 * max(0.0, math.sin(math.pi * (h - 7) / 12)) + (110 if 17 <= h < 21 else 0)


# ---------------------------------------------------------------- weather and PV
def weather(rnd, days):
    out = []
    for d in range(days):
        kind = rnd.choices(["clear", "partly", "overcast", "rain"], [0.35, 0.35, 0.18, 0.12])[0]
        out.append({"day": d + 1, "kind": kind, "cloud": {"clear": 0.95, "partly": 0.62, "overcast": 0.28, "rain": 0.18}[kind]})
    return out


def irradiance(day, h, cloud, rnd):
    """W/m2 on the panel: mid-September at ~50 deg N, the day shortening over the month."""
    rise = 6.9 + 0.035 * day
    sett = 19.6 - 0.04 * day
    if not rise < h < sett:
        return 0.0
    g = 780 * math.sin(math.pi * (h - rise) / (sett - rise)) ** 1.2
    return max(0.0, g * cloud * (1 + rnd.gauss(0, 0.12 if cloud < 0.9 else 0.03)))


# ---------------------------------------------------------------- load from the month
def load_profile(m, days):
    unit_share = {u: M.FSM0[u]["RUN"] / M.T_MODEL for u in M.FSM0}
    prod_w = sum(UNIT_MOTORS[u] * unit_share[u] for u in UNIT_MOTORS)
    bake_share = sum(st.t for st in M.C.job_steps(("bake", ("c",), ("door",), (), ())) if st.key == "row5") * 9 / M.T_MODEL
    prod_w += LAMP_W * bake_share + 6.0            # the valves
    standby = sum(STANDBY_W.values())
    n = days * N_DAY
    load = [standby / PSU_EFF + INV_STANDBY] * n
    prod = [0.0] * n
    for i, o in enumerate(m.orders):
        t0, t1 = o["t"], o["t"] + o["dur"] / 3600
        duty = m.raw["air_duty"][i]
        p = (prod_w + COMPRESSOR_W * duty) / PSU_EFF
        k = int(t0 / STEP_H)
        while k * STEP_H < t1 and k < n:
            ov = min(t1, (k + 1) * STEP_H) - max(t0, k * STEP_H)
            load[k] += p * ov / STEP_H
            prod[k] += ov / STEP_H
            k += 1
    return load, prod, {"standby_w": round(standby, 1), "production_w": round(prod_w, 1), "compressor_w": COMPRESSOR_W,
                        "psu_eff": PSU_EFF, "inverter_standby_w": INV_STANDBY, "unit_run_share": {u: round(v, 3) for u, v in unit_share.items()}}


# ---------------------------------------------------------------- the EMS: a day-ahead dynamic programme
LEVELS = 100                     # 10 Wh steps: the smallest charge is 40 W - smooth, and under the peak cap
DWH = BATT_WH / LEVELS


def plan_day(load_f, pv_f, prices, dr, pv_on=True):
    """-> the battery energy change per step (Wh, + = charge) minimising cost."""
    INF = float("inf")
    lo = int(math.ceil(SOC_MIN * LEVELS))
    res = int(math.ceil(RESERVE * LEVELS))
    kmax = int(P_BATT * STEP_H / DWH)
    cost = [[INF] * (LEVELS + 1) for _ in range(N_DAY + 1)]
    act = [[0] * (LEVELS + 1) for _ in range(N_DAY)]
    for s in range(LEVELS + 1):
        cost[N_DAY][s] = 0.0 if s >= res else INF          # end the day with the reserve intact
    for t in range(N_DAY - 1, -1, -1):
        net = load_f[t] - (pv_f[t] if pv_on else 0.0)
        for s in range(max(lo, 0), LEVELS + 1):
            best, ba = INF, 0
            for d in range(-kmax, kmax + 1):
                s2 = s + d
                if s2 < lo or s2 > LEVELS or s2 < res and d < 0:
                    continue                                   # never discharge into the reserve
                e_b = d * DWH
                p_b = e_b / ETA / STEP_H if d > 0 else e_b * ETA / STEP_H
                g = net + p_b
                imp, exp_ = max(0.0, g), max(0.0, -g)
                c = (imp * prices[t] - exp_ * FEED_IN) * STEP_H / 1000 + abs(e_b) / 1000 * DEG_EUR_KWH
                if imp > PEAK_CAP:
                    c += (imp - PEAK_CAP) * 0.01               # peak shaving
                if dr[t] and imp > DR_CAP:
                    c += (imp - DR_CAP) * 1.0                  # a DR window is a hard promise
                c += cost[t + 1][s2]
                if c < best:
                    best, ba = c, d
            cost[t][s], act[t][s] = best, ba
    return act, lo


def simulate(m, scenario, weath, rnd_seed=SEED):
    rnd = random.Random(rnd_seed)
    days = M.DAYS
    cell, prod, lp = load_profile(m, days)
    oven = oven_profile(days)
    load = [c + v for c, v in zip(cell, oven, strict=True)]
    has_pv = scenario in ("pv", "pv+battery")
    has_batt = scenario == "pv+battery"
    soil, soil_log, cleanings, pending_clean = 0.0, [], [], False
    out = {k: [] for k in ("load", "cell", "oven", "pv", "grid", "batt", "soc", "price", "co2", "dr", "irr", "pv_expected")}
    soc = 0.6
    cycles_wh = 0.0
    dr_days = {8: (17, 19), 15: (17, 19), 22: (18, 20)}
    for d in range(days):
        w = weath[d]
        rday = 1 + rnd.gauss(0, 0.07)
        if pending_clean and has_pv:
            cleanings.append({"day": d + 1, "what": f"planned: PV panels cleaned before dawn (soiling {100 * soil:.1f} %)"})
            soil, pending_clean = 0.0, False
        if w["kind"] == "rain":
            soil *= 0.3                                         # rain washes most of it off
        else:
            soil = min(0.25, soil + (0.008 if d >= 12 else 0.0025))    # dust from building work after day 12
        if has_pv and soil > 0.06 and not pending_clean:
            # seen as the performance ratio against the irradiance sensor: work order for tomorrow morning
            cleanings.append({"day": d + 1, "what": f"PV performance ratio {100 * (1 - soil):.0f} % of clean: cleaning work order"})
            pending_clean = True
        irr = [irradiance(d, (i + 0.5) * STEP_H, w["cloud"], rnd) for i in range(N_DAY)]
        pv_exp = [PV_WP * g / 1000 * 0.85 for g in irr]
        pv = [p * (1 - soil) for p in pv_exp] if has_pv else [0.0] * N_DAY
        pv_f = [max(0.0, p * (1 + rnd.gauss(0, 0.18))) for p in pv]
        L = load[d * N_DAY:(d + 1) * N_DAY]
        pr = [price(d, (i + 0.5) * STEP_H, rday) for i in range(N_DAY)]
        dr = [1 if (d + 1) in dr_days and dr_days[d + 1][0] <= (i * STEP_H) < dr_days[d + 1][1] else 0 for i in range(N_DAY)]
        if has_batt:
            act, lo = plan_day(L, pv_f, pr, dr)
        for i in range(N_DAY):
            b = 0.0
            if has_batt:
                s_lvl = max(lo, min(LEVELS, int(round(soc * LEVELS))))
                e_b = act[i][s_lvl] * DWH
                # real time: inside a DR window the battery covers what the forecast missed
                net = L[i] - pv[i]
                p_b = e_b / ETA / STEP_H if e_b > 0 else e_b * ETA / STEP_H
                if dr[i] and net + p_b > DR_CAP:
                    p_b = max(-P_BATT, DR_CAP - net)
                room = (soc - RESERVE) * BATT_WH * ETA / STEP_H if not dr[i] else (soc - DR_FLOOR["soc"]) * BATT_WH * ETA / STEP_H
                p_b = max(p_b, -max(0.0, room))
                p_b = min(p_b, (SOC_MAX - soc) * BATT_WH / ETA / STEP_H, P_BATT)
                # real-time guard: the plan used a forecast; never let a charge (or a missing
                # sun) push the import over the peak cap if the battery can prevent it
                over = net + p_b - PEAK_CAP
                if over > 0:
                    p_b = max(p_b - over, -max(0.0, room))
                # and never discharge into the grid: feed-in pays 0.08, the site's own load is worth 0.22-0.42
                # (the oven behind the meter counts), and the inverter's AC output (PV + battery) stays within its rating
                if p_b < 0:
                    p_b = max(p_b, -max(0.0, net), -max(0.0, INV_W - pv[i]))
                e = p_b * ETA * STEP_H if p_b > 0 else p_b / ETA * STEP_H
                soc = min(SOC_MAX, max(SOC_MIN, soc + e / BATT_WH))
                cycles_wh += abs(e)
                b = p_b
            g = L[i] - pv[i] + b
            out["load"].append(round(L[i], 1)); out["cell"].append(round(cell[d * N_DAY + i], 1))
            out["oven"].append(round(oven[d * N_DAY + i], 1)); out["pv"].append(round(pv[i], 1)); out["grid"].append(round(g, 1))
            out["batt"].append(round(b, 1)); out["soc"].append(round(soc, 3)); out["price"].append(pr[i])
            out["co2"].append(round(co2((i + 0.5) * STEP_H), 1)); out["dr"].append(dr[i]); out["irr"].append(round(irr[i], 1))
            out["pv_expected"].append(round(pv_exp[i] if has_pv else 0.0, 1))
        soil_log.append(round(soil, 4))
    return out, lp, soil_log, cycles_wh, cleanings


# ---------------------------------------------------------------- power quality
def mains_events(rnd, days):
    """Two outages and eight sags (depth = remaining voltage, EN 50160 style)."""
    ev = [{"kind": "outage", "day": 6, "h": 10.2, "dur_s": 4 * 60}, {"kind": "outage", "day": 19, "h": 15.67, "dur_s": 47 * 60}]
    for _ in range(8):
        ev.append({"kind": "sag", "day": rnd.randint(1, days), "h": round(rnd.uniform(0, 24), 2),
                   "depth": round(rnd.choice([0.4, 0.55, 0.7, 0.8, 0.85]), 2), "dur_s": round(rnd.choice([0.05, 0.1, 0.2, 0.5, 1.0]), 2)})
    return sorted(ev, key=lambda e: (e["day"], e["h"]))


PSU_HOLDUP_S = 0.020
PSU_MIN_V = 0.80                 # the PSU keeps regulating down to 80 % input (ASSUMED)


def ride_through(ev, series, batt):
    """Does the 24 V survive? And if not, what does it cost? The oven's elements are resistive:
    a sag only slows the heat for a moment; an outage stops the bake unless it is on the UPS."""
    i = (ev["day"] - 1) * N_DAY + int(ev["h"] / STEP_H)
    producing = series["cell"][i] > 60
    oven_on = series["oven"][i] > 0
    ups_oven = batt and OVEN_SUPPLY["ups"]
    oven = None
    if oven_on and ev["kind"] == "outage" and not ups_oven:
        oven = ("the oven goes cold: the cookie in it is scrapped and it reheats for "
                f"{min(ev['dur_s'], oven_params()['preheat_s']) / 60:.0f} min")
    if ev["kind"] == "sag" and ev["depth"] >= PSU_MIN_V:
        return {"survives": True, "why": "above the PSU's input range: it keeps regulating", "oven": oven}
    if ev["kind"] == "sag" and ev["dur_s"] <= PSU_HOLDUP_S:
        return {"survives": True, "why": "shorter than the PSU's 20 ms hold-up", "oven": oven}
    if not batt:
        lost = (M.T0 / 2 + 180 if producing else 60)
        return {"survives": False, "why": "24 V collapses: the PLC restarts, every unit re-homes; the order in progress "
                                          "is redone" + (" (a VGR carry drops its cookie)" if producing else ""),
                "lost_s": round(lost), "producing": producing, "oven": oven}
    carried = series["load"][i] if ups_oven else series["cell"][i]
    need_wh = carried * ev["dur_s"] / 3600
    have_wh = (series["soc"][i] - SOC_MIN) * BATT_WH
    ok = have_wh >= need_wh
    if ups_oven and oven_on and ev["kind"] == "outage" and not ok:
        oven = "the battery ran out: the oven goes cold, the cookie in it is scrapped"
    return {"survives": ok, "why": f"the inverter carries the {'cell and the oven' if ups_oven else 'cell'} from the battery: "
                                   f"{need_wh:.1f} Wh needed, {have_wh:.0f} Wh available" if ok else "the reserve ran out",
            "need_wh": round(need_wh, 1), "have_wh": round(have_wh), "producing": producing, "oven": oven}


# ---------------------------------------------------------------- power-asset health
def assets(m, weath, soil_log, cycles_wh, series):
    days = M.DAYS
    hall = [M.temperature(h) for h in range(days * 24)]
    out = {}
    # cabinet filter -> cabinet temperature -> PSU capacitor ageing (Arrhenius, 10 K halves the life)
    def cab_run(maintain):
        clog, life_used, rows, ev, due = 0.0, 0.0, [], [], None
        for h in range(days * 24):
            d = h // 24
            clog += (0.0035 if d >= 10 else 0.0010)            # building dust after day 10 (ASSUMED)
            load_w = series["cell"][min(len(series["cell"]) - 1, h * 4)]     # the oven is not in the cabinet
            t_cab = hall[h] + 6.0 + 9.0 * clog + 0.04 * load_w
            t_cap = t_cab + 12.0                                # inside the PSU
            life_h = 8000 * 2 ** ((105 - t_cap) / 10)          # 8 000 h at 105 C (ASSUMED capacitor rating)
            life_used += 1 / life_h
            rows.append(round(t_cab, 2))
            if maintain and due is None and t_cab - hall[h] > 14.0:
                ev.append({"h": h, "what": f"cabinet {t_cab - hall[h]:.1f} K above the hall: the air filter is clogging - work order"})
                due = h + (22 - (h % 24)) % 24 or h + 24        # tonight, 22:00
            if maintain and due is not None and h >= due:
                ev.append({"h": h, "what": "planned: cabinet air filter changed (15 min, night gap)"})
                clog, due = 0.0, None
        return rows, life_used, ev
    t_cab, used, ev_cab = cab_run(True)
    t_cab_cf, used_cf, _ = cab_run(False)
    out["cabinet"] = {"t_cab": t_cab[::2], "t_cab_cf": t_cab_cf[::2], "life_used_month": round(used, 5),
                      "life_used_month_cf": round(used_cf, 5),
                      "life_years": round(1 / used / 12, 1), "life_years_cf": round(1 / used_cf / 12, 1), "events": ev_cab}
    # PV soiling: seen as a falling performance ratio against the irradiance sensor
    pr_days = []
    for d in range(days):
        e = sum(series["pv"][d * N_DAY:(d + 1) * N_DAY])
        x = sum(series["pv_expected"][d * N_DAY:(d + 1) * N_DAY])
        pr_days.append(round(e / x, 4) if x > 50 else None)
    out["pv"] = {"performance_ratio": pr_days, "soiling": soil_log}
    # battery state of health: cycle + calendar ageing (LFP, ASSUMED 6 000 full cycles to 80 %)
    efc = cycles_wh / 2 / BATT_WH
    soh_loss = efc * (0.20 / 6000) + (days / 365) * 0.015
    out["battery"] = {"equivalent_full_cycles": round(efc, 1), "soh_start": 0.97, "soh_end": round(0.97 - soh_loss, 4),
                      "years_to_80pct": round((0.97 - 0.80) / (soh_loss * 12), 1)}
    # contactors K1/K2: operations this month (each E-stop and each morning start)
    estops = sum(1 for e in m.events if e.get("code") == "SYS-01")
    ops = 2 * (estops + days)
    out["contactors"] = {"operations_month": ops, "electrical_life_ops": 1_000_000,
                         "years_to_life": round(1_000_000 / (ops * 12), 0)}
    return out


# ---------------------------------------------------------------- run
class assets_as:
    """Run with other asset sizes (module globals, as plan_day and simulate read them)."""

    def __init__(self, **kw):
        self.kw, self.old = kw, {}

    def __enter__(self):
        global DWH
        g = globals()
        for k, v in self.kw.items():
            self.old[k] = g[k]
            g[k] = v
        DWH = BATT_WH / LEVELS
        return self

    def __exit__(self, *exc):
        global DWH
        globals().update(self.old)
        DWH = BATT_WH / LEVELS


def kpis(s, days):
    imp = sum(max(0.0, g) for g in s["grid"]) * STEP_H / 1000
    exp_ = sum(max(0.0, -g) for g in s["grid"]) * STEP_H / 1000
    cost = sum(max(0.0, g) * p - max(0.0, -g) * FEED_IN for g, p in zip(s["grid"], s["price"])) * STEP_H / 1000
    peak = max(max(0.0, g) for g in s["grid"])
    load = sum(s["load"]) * STEP_H / 1000
    pv = sum(s["pv"]) * STEP_H / 1000
    co2_kg = sum(max(0.0, g) * c for g, c in zip(s["grid"], s["co2"])) * STEP_H / 1e6
    dr_ok = all(max(0.0, g) <= DR_CAP + 0.5 for g, d in zip(s["grid"], s["dr"]) if d)
    dr_import = sum(max(0.0, g) for g, d in zip(s["grid"], s["dr"]) if d) * STEP_H
    return {"load_kwh": round(load, 2), "pv_kwh": round(pv, 2), "import_kwh": round(imp, 2), "export_kwh": round(exp_, 2),
            "energy_cost_eur": round(cost, 2), "peak_w": round(peak, 1), "demand_charge_eur": round(peak / 1000 * DEMAND_EUR_KW, 2),
            "total_eur": round(cost + peak / 1000 * DEMAND_EUR_KW, 2), "co2_kg": round(co2_kg, 2),
            "self_sufficiency": round(1 - imp / load, 3) if load else 0, "self_consumption": round(1 - exp_ / pv, 3) if pv else None,
            "dr_met": dr_ok, "dr_import_wh": round(dr_import, 1)}


def main():
    m = M.Month().run()
    weath = weather(random.Random(SEED), M.DAYS)
    runs = {}
    for sc in ("grid", "pv", "pv+battery"):
        s, lp, soil, cyc, cl = simulate(m, sc, weath)
        runs[sc] = {"series": s, "kpi": kpis(s, M.DAYS), "soil": soil, "cycles_wh": cyc, "cleanings": cl}
    best = runs["pv+battery"]
    ev_mains = mains_events(random.Random(SEED + 2), M.DAYS)
    pq = []
    for e in ev_mains:
        pq.append({**e, "with_ups": ride_through(e, best["series"], True), "grid_only": ride_through(e, runs["grid"]["series"], False)})
    # the oven's supply: the cell alone (Upgrade 9 as first sized), and a microgrid resized to carry the oven
    ov = oven_params()
    OVEN_ON["on"] = False
    with assets_as(PEAK_CAP=PEAK_CAP_CELL):
        cell_only = kpis(simulate(m, "pv+battery", weath)[0], M.DAYS)
    OVEN_ON["on"] = True
    OVEN_SUPPLY["ups"] = True
    with assets_as(**RESIZED):
        rs = simulate(m, "pv+battery", weath)[0]
        rk = kpis(rs, M.DAYS)
        r_pq = [ride_through(e, rs, True) for e in ev_mains]
    OVEN_SUPPLY["ups"] = False
    r_saving = runs["grid"]["kpi"]["total_eur"] - rk["total_eur"]
    oven_kwh = sum(best["series"]["oven"]) * STEP_H / 1000
    outages = [p for p in pq if p["kind"] == "outage"]
    supply = {
        "oven": {**ov, "month_kwh": round(oven_kwh, 1), "share_of_load": round(oven_kwh / best["kpi"]["load_kwh"], 3)},
        "options": [
            {"name": "as built: the cell on the 600 W microgrid, the oven on its own 230 V circuit",
             "inverter_w": INV_W, "battery_wh": BATT_WH, "pv_wp": PV_WP, "carries_oven": False,
             "inverter_ok": INV_W >= max(best["series"]["cell"]), "kpi": best["kpi"],
             "capex_total": None, "ride_through": sum(p["with_ups"]["survives"] for p in pq),
             "oven_kept_hot": sum(1 for p in outages if not p["with_ups"]["oven"])},
            {"name": f"resized: {RESIZED['INV_W'] / 1000:.0f} kW inverter, {RESIZED['BATT_WH'] / 1000:.0f} kWh battery, "
                     f"{RESIZED['PV_WP'] / 1000:.1f} kWp PV, the oven on the UPS",
             "inverter_w": RESIZED["INV_W"], "battery_wh": RESIZED["BATT_WH"], "pv_wp": RESIZED["PV_WP"], "carries_oven": True,
             "inverter_ok": RESIZED["INV_W"] >= ov["rated_w"] + max(rs["cell"]), "kpi": rk,
             "capex_eur": RESIZED_CAPEX, "capex_total": sum(RESIZED_CAPEX.values()),
             "saving_eur_month": round(r_saving, 2),
             "payback_years": round(sum(RESIZED_CAPEX.values()) / max(0.01, r_saving * 12), 1),
             "ride_through": sum(r["survives"] for r in r_pq),
             "oven_kept_hot": sum(1 for p, r in zip(pq, r_pq, strict=True) if p["kind"] == "outage" and not r["oven"])},
        ],
        "cell_only": cell_only,
        "outages": len(outages),
    }
    health = assets(m, weath, best["soil"], best["cycles_wh"], best["series"])
    clean = best["cleanings"]
    lost_orders_s = sum(p["grid_only"].get("lost_s", 0) for p in pq if not p["grid_only"]["survives"])
    capex = {"hybrid inverter 600 W": 450, "LFP battery 1 kWh": 420, "PV 400 Wp + mounting": 380, "cabinet temp sensor": 25,
             "energy meter (SunSpec/Modbus)": 90}
    saving = runs["grid"]["kpi"]["total_eur"] - best["kpi"]["total_eur"]
    doc = {
        "meta": {"days": M.DAYS, "step_h": STEP_H, "machine": "Upgrade 7 + the U9 microgrid + the U19 oven", "seed": SEED,
                 "assets": {"pv_wp": PV_WP, "battery_wh": BATT_WH, "battery_p_w": P_BATT, "inverter_w": INV_W, "reserve": RESERVE,
                            "soc_min": SOC_MIN, "eta": ETA, "peak_cap_w": PEAK_CAP, "dr_cap_w": DR_CAP},
                 "load_model": {**lp, "oven_shift_w": ov["shift_w"], "oven_rated_w": ov["rated_w"],
                                "oven_preheat_kwh": ov["preheat_kwh"]},
                 "tariff": "time of use: 0.22 EUR/kWh 22-06, 0.30 06-17 and 21-22, 0.42 17-21, a day-ahead spread; "
                           "feed-in 0.08; demand charge 12 EUR/kW-month",
                 "standards": ["EN 50160 (voltage characteristics: the sag and outage classes)",
                               "IEC 61000-4-30 class S (how the power-quality meter measures them)",
                               "OpenADR 2.0b (the demand-response signal)", "IEEE 1547-2018 (the inverter's grid-support and ride-through settings)",
                               "SunSpec Modbus models 1/103/124 (inverter and battery data into the PLC)",
                               "ISO 50001 (the energy review this page is)"],
                 "assumed": "every asset size and rating, the tariff and CO2 profiles, the weather draw, the soiling and "
                            "filter-clogging rates, the capacitor rating (8 000 h at 105 C), LFP ageing, the PSU's "
                            "20 ms hold-up and 80 % input limit, the mains events"},
        "scenarios": {k: v["kpi"] for k, v in runs.items()},
        "series": {"t_h": [round(i * STEP_H, 2) for i in range(M.DAYS * N_DAY)], **best["series"],
                   "grid_only": runs["grid"]["series"]["grid"]},
        "weather": weath, "power_quality": pq, "health": health, "pv_cleaning": clean, "oven_supply": supply,
        "economics": {"capex_eur": capex, "capex_total": sum(capex.values()), "saving_eur_month": round(saving, 2),
                      "payback_years": round(sum(capex.values()) / max(0.01, saving * 12), 1),
                      "outage_cost_avoided_s": lost_orders_s,
                      "note": f"the oven is {100 * oven_kwh / best['kpi']['load_kwh']:.0f} % of the site's energy and the "
                              "cell itself draws tens of watts: the microgrid's case is ride-through, demand response "
                              "and power quality more than the bill"},
    }
    # findings, computed from the month - not narrated
    S = best["series"]
    ip = max(range(len(S["grid"])), key=lambda i: S["grid"][i])
    over = [i for i, g_ in enumerate(S["grid"]) if g_ > PEAK_CAP + 0.5]
    at_res = sum(1 for i in over if S["soc"][i] <= RESERVE + 0.02)
    f = []
    f.append({"title": "Ride-through is the real value",
              "text": f"{sum(1 for p in pq if p['with_ups']['survives'])} of {len(pq)} mains events ridden through with the inverter in UPS "
                      f"mode, against {sum(1 for p in pq if p['grid_only']['survives'])} without it: without it the 24 V collapses "
                      f"and {round(lost_orders_s / 60)} min of production are lost this month. The oven is not on the UPS."})
    f.append({"title": "The reserve wins over peak shaving",
              "text": f"The import went over the {PEAK_CAP:.0f} W cap in {len(over)} of {len(S['grid'])} quarter-hours; in "
                      f"{at_res} of them the battery was at its {RESERVE:.0%} ride-through reserve, which the EMS will not spend. "
                      f"The worst, {S['grid'][ip]:.0f} W, came on day {ip // N_DAY + 1} at "
                      f"{int((ip % N_DAY) * STEP_H):02d}:{int(((ip % N_DAY) * STEP_H % 1) * 60):02d}. A bigger battery, or a "
                      "smaller reserve, would shave it; keeping the cell running through an outage was chosen instead."})
    miss = [i for i, (g_, d_) in enumerate(zip(S["grid"], S["dr"], strict=True)) if d_ and g_ > DR_CAP + 0.5]
    if not miss:
        f.append({"title": "Demand response met with the battery",
                  "text": f"All three events held under {DR_CAP:.0f} W import ({best['kpi']['dr_import_wh']} Wh in total), with "
                          f"production and the oven running; without the battery the site imported "
                          f"{runs['grid']['kpi']['dr_import_wh']} Wh in the same windows."})
    else:
        j = miss[0]
        f.append({"title": "The held oven empties the battery before a demand-response window ends",
                  "text": f"The oven draws {ov['shift_w']:.0f} W through the evening windows. On day {j // N_DAY + 1} the battery "
                          f"reached its floor at {int((j % N_DAY) * STEP_H):02d}:{int(((j % N_DAY) * STEP_H % 1) * 60):02d} and the "
                          f"site imported {best['kpi']['dr_import_wh']} Wh over the {DR_CAP:.0f} W cap "
                          f"({len(miss)} quarter-hour{'s' if len(miss) > 1 else ''}), "
                          f"against {runs['grid']['kpi']['dr_import_wh']} Wh without the battery. The cell alone met every event "
                          f"({cell_only['dr_import_wh']} Wh)."})
    r = supply["options"][1]
    f.append({"title": f"The real oven is {100 * oven_kwh / best['kpi']['load_kwh']:.0f} % of the energy",
              "text": f"Held at 180 C through both shifts it uses {oven_kwh:.0f} kWh a month, against {cell_only['load_kwh']:.0f} kWh "
                      f"for the rest of the cell; {100 * ov['useful_share']:.0f} % of its heat goes into the cookies, the rest is "
                      f"lost through the walls, the vent and the door. Its {ov['rated_w']:,.0f} W of elements are more than twice "
                      f"the {INV_W:.0f} W inverter, so it runs on its own 230 V circuit: the battery and PV offset it behind the "
                      f"meter, but in each of the {len(outages)} outages it goes cold and the cookie in it is scrapped."})
    f.append({"title": "Carrying the oven through outages costs a resized microgrid",
              "text": f"A {r['inverter_w'] / 1000:.0f} kW inverter, a {r['battery_wh'] / 1000:.0f} kWh battery and "
                      f"{r['pv_wp'] / 1000:.1f} kWp of PV keep the oven hot through {r['oven_kept_hot']} of {len(outages)} outages, "
                      f"cover {100 * r['kpi']['self_sufficiency']:.0f} % of the site's energy (against "
                      f"{100 * best['kpi']['self_sufficiency']:.0f} %), {'meet' if r['kpi']['dr_met'] else 'miss'} demand response "
                      f"and cut the bill to EUR {r['kpi']['total_eur']}: EUR {r['capex_total']:,} for {r['payback_years']} years' "
                      f"payback. With a 10-minute bake an outage costs one cookie, so the case is the same as the cell's: "
                      "ride-through and demand response, not the bill."})
    f.append({"title": "The energy bill alone does not pay for it",
              "text": f"EUR {saving:.2f} a month saved on EUR {sum(capex.values())} spent: {sum(capex.values()) / max(0.01, saving * 12):.0f} "
                      "years. The case rests on ride-through, demand response and the data."})
    c_ = health["cabinet"]
    f.append({"title": f"A clogged cabinet filter costs the PSU {100 * (1 - c_['life_years_cf'] / c_['life_years']):.0f} % of its life",
              "text": f"At this month's temperatures the PSU's capacitors last {c_['life_years']} years with the filter work orders "
                      f"and {c_['life_years_cf']} years without: {len([e for e in c_['events'] if e['what'].startswith('planned')])} "
                      "filter changes, all in the night gap."})
    doc["findings"] = f
    os.makedirs(OUT, exist_ok=True)
    json.dump(doc, open(os.path.join(OUT, "grid.json"), "w"), separators=(",", ":"))
    import csv
    with open(os.path.join(OUT, "grid_15min.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        cols = ["t_h", "load", "pv", "grid", "batt", "soc", "price", "co2", "dr", "irr"]
        w.writerow(["t_h", "load_w", "pv_w", "grid_w", "battery_w", "soc", "price_eur_kwh", "co2_g_kwh", "dr_event", "irradiance_w_m2"])
        for i in range(len(doc["series"]["t_h"])):
            w.writerow([doc["series"][c][i] for c in cols])
    for k, v in runs.items():
        print(f"{k:11s} {v['kpi']}")
    print("economics", doc["economics"])
    for p in pq:
        print(f"  day {p['day']:2d} {p['kind']:6s} {p.get('depth', '')} {p['dur_s']} s: UPS {p['with_ups']['survives']}, grid-only {p['grid_only']['survives']}")
    print("health", {k: {kk: vv for kk, vv in v.items() if not isinstance(vv, list)} for k, v in health.items()})
    print("pv cleaning", clean)


if __name__ == "__main__":
    main()
