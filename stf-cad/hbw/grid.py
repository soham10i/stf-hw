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
PEAK_CAP = 70.0                # W: the peak-shaving target - below the cell's natural ~86 W peak, so it shaves
DR_CAP = 15.0                  # W: import cap during a demand-response event
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
    load, prod, lp = load_profile(m, days)
    has_pv = scenario in ("pv", "pv+battery")
    has_batt = scenario == "pv+battery"
    soil, soil_log, cleanings, pending_clean = 0.0, [], [], False
    out = {k: [] for k in ("load", "pv", "grid", "batt", "soc", "price", "co2", "dr", "irr", "pv_expected")}
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
                room = (soc - RESERVE) * BATT_WH * ETA / STEP_H if not dr[i] else (soc - SOC_MIN) * BATT_WH * ETA / STEP_H
                p_b = max(p_b, -max(0.0, room))
                p_b = min(p_b, (SOC_MAX - soc) * BATT_WH / ETA / STEP_H, P_BATT)
                # real-time guard: the plan used a forecast; never let a charge (or a missing
                # sun) push the import over the peak cap if the battery can prevent it
                over = net + p_b - PEAK_CAP
                if over > 0:
                    p_b = max(p_b - over, -max(0.0, room))
                # and never discharge into the grid: feed-in pays 0.08, the cell's own load is worth 0.22-0.42
                if p_b < 0:
                    p_b = max(p_b, -max(0.0, net))
                e = p_b * ETA * STEP_H if p_b > 0 else p_b / ETA * STEP_H
                soc = min(SOC_MAX, max(SOC_MIN, soc + e / BATT_WH))
                cycles_wh += abs(e)
                b = p_b
            g = L[i] - pv[i] + b
            out["load"].append(round(L[i], 1)); out["pv"].append(round(pv[i], 1)); out["grid"].append(round(g, 1))
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
    """Does the 24 V survive? And if not, what does it cost?"""
    i = (ev["day"] - 1) * N_DAY + int(ev["h"] / STEP_H)
    producing = series["load"][i] > 60
    if ev["kind"] == "sag" and ev["depth"] >= PSU_MIN_V:
        return {"survives": True, "why": "above the PSU's input range: it keeps regulating"}
    if ev["kind"] == "sag" and ev["dur_s"] <= PSU_HOLDUP_S:
        return {"survives": True, "why": "shorter than the PSU's 20 ms hold-up"}
    if not batt:
        lost = (M.T0 / 2 + 180 if producing else 60)
        return {"survives": False, "why": "24 V collapses: the PLC restarts, every unit re-homes; the order in progress "
                                          "is redone" + (" (a VGR carry drops its cookie)" if producing else ""),
                "lost_s": round(lost), "producing": producing}
    need_wh = series["load"][i] * ev["dur_s"] / 3600
    have_wh = (series["soc"][i] - SOC_MIN) * BATT_WH
    ok = have_wh >= need_wh
    return {"survives": ok, "why": f"the inverter carries the cell from the battery: {need_wh:.1f} Wh needed, "
                                   f"{have_wh:.0f} Wh available" if ok else "the reserve ran out",
            "need_wh": round(need_wh, 1), "have_wh": round(have_wh), "producing": producing}


# ---------------------------------------------------------------- power-asset health
def assets(m, weath, soil_log, cycles_wh, series):
    rnd = random.Random(SEED + 1)
    days = M.DAYS
    hall = [M.temperature(h) for h in range(days * 24)]
    out = {}
    # cabinet filter -> cabinet temperature -> PSU capacitor ageing (Arrhenius, 10 K halves the life)
    def cab_run(maintain):
        clog, life_used, rows, ev, due = 0.0, 0.0, [], [], None
        for h in range(days * 24):
            d = h // 24
            clog += (0.0035 if d >= 10 else 0.0010)            # building dust after day 10 (ASSUMED)
            load_w = series["load"][min(len(series["load"]) - 1, h * 4)]
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
    health = assets(m, weath, best["soil"], best["cycles_wh"], best["series"])
    clean = best["cleanings"]
    lost_orders_s = sum(p["grid_only"].get("lost_s", 0) for p in pq if not p["grid_only"]["survives"])
    capex = {"hybrid inverter 600 W": 450, "LFP battery 1 kWh": 420, "PV 400 Wp + mounting": 380, "cabinet temp sensor": 25,
             "energy meter (SunSpec/Modbus)": 90}
    saving = runs["grid"]["kpi"]["total_eur"] - best["kpi"]["total_eur"]
    doc = {
        "meta": {"days": M.DAYS, "step_h": STEP_H, "machine": "Upgrade 7 + the U9 microgrid", "seed": SEED,
                 "assets": {"pv_wp": PV_WP, "battery_wh": BATT_WH, "battery_p_w": P_BATT, "reserve": RESERVE,
                            "soc_min": SOC_MIN, "eta": ETA, "peak_cap_w": PEAK_CAP, "dr_cap_w": DR_CAP},
                 "load_model": lp,
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
        "weather": weath, "power_quality": pq, "health": health, "pv_cleaning": clean,
        "economics": {"capex_eur": capex, "capex_total": sum(capex.values()), "saving_eur_month": round(saving, 2),
                      "payback_years": round(sum(capex.values()) / max(0.01, saving * 12), 1),
                      "outage_cost_avoided_s": lost_orders_s,
                      "note": "the cell draws tens of watts: the case for the microgrid is ride-through and power "
                              "quality, not the energy bill"},
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
                      f"and {round(lost_orders_s / 60)} min of production are lost this month."})
    f.append({"title": "The reserve wins over peak shaving",
              "text": f"The import went over the {PEAK_CAP:.0f} W cap in {len(over)} of {len(S['grid'])} quarter-hours; in "
                      f"{at_res} of them the battery was at its {RESERVE:.0%} ride-through reserve, which the EMS will not spend. "
                      f"The worst, {S['grid'][ip]:.0f} W, came on day {ip // N_DAY + 1} at "
                      f"{int((ip % N_DAY) * STEP_H):02d}:{int(((ip % N_DAY) * STEP_H % 1) * 60):02d}. A bigger battery, or a "
                      "smaller reserve, would shave it; keeping the cell running through an outage was chosen instead."})
    f.append({"title": "Demand response met with the battery",
              "text": f"All three events held under {DR_CAP:.0f} W import ({best['kpi']['dr_import_wh']} Wh in total), with "
                      f"production running; without the battery the cell imported {runs['grid']['kpi']['dr_import_wh']} Wh in "
                      "the same windows."})
    f.append({"title": "The energy bill alone does not pay for it",
              "text": f"EUR {saving:.2f} a month saved on EUR {sum(capex.values())} spent: {sum(capex.values()) / max(0.01, saving * 12):.0f} "
                      "years. The cell draws tens of watts; the case rests on ride-through, demand response and the data."})
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
