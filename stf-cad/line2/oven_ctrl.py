"""
STF-2 oven control (upgrade O-2): the zones in TIME - a dynamic model of the three zones, PI controllers tuned
from it, and the scenarios a real oven must survive, each a proof.

Zone model (one lumped node per zone, oven.py supplies every coefficient):
    C dT/dt = u P_inst - walls(T) - mouths(T) - band(T) - f (product + exhaust)(T) + G (T_nbr - T)
  C          oven.capacity (skins, band inside, elements, half the wool)
  walls      oven.wall_loss, mouths oven.mouth_loss (end zones)
  band       the nominal band load, linear in (T - T_AMB)
  product    the nominal product + vapour load (oven.zone_loads), linear in (T - mean product temperature in the
             zone, from oven.profile), times f = how full the zone is (the band fills / empties row by row)
  G          zone-to-zone air exchange through the open chamber [assumed]
  sensor     the TC is a first-order lag TC_TAU (3 mm sheath in forced air) [typ]
Controller (FB_Oven): PI on the TC with conditional-integration anti-windup, plus FEED-FORWARD of the product
load from the band content the PLC already tracks (the depositor knows every row it cut) - output u in
[0, 1] goes to the 2 s time-proportioning of the element SSRs.
Tuning: an open-loop step on the model at the operating point -> first order + dead time (K, tau, theta) ->
SIMC (Skogestad): Kc = tau / (K (tau_c + theta)), Ti = min(tau, 4 (tau_c + theta)), tau_c = TAU_C_X theta.

Scenarios (proofs):
  S1 cold start, empty band           at set point (+-2 K) within WARMUP_MAX, overshoot <= DEV_MAX
  S2 production start                 the band fills with cold dough: deviation <= bake window
  S3 depositor stop 10 min + restart  the load falls away and comes back: deviation <= bake window
  S4 one element open (Z1 top)        held within the window, the duty observer alarms within ALARM_MAX
  S5 SSR stuck on (Z1, all elements)  the STB trips at STB_T, the zone air stays below T_LIMIT
  nuisance                            no normal scenario brings a TC within STB_MARGIN of STB_T, no false alarm
  bake window                         the largest zone offset (all zones, + and -) at which oven.simulate
                                      still says baked - control deviation must stay inside it
Run: python3 oven_ctrl.py   (writes oven/control.json for FB_Oven, the drawing and the twin)
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hardware as H
import line_model as M
import oven as OV

L = M.L
OUT = os.path.join(HERE, "oven")
CTRL = dict(TC_TAU=15.0, ZONE_G=3.0, DT=0.5, TAU_C_X=1.5, DEV_MAX=L["BAKE_MARGIN"], ALARM_MAX=300.0, STB_T=250.0,
            STB_MARGIN=15.0, T_LIMIT=300.0, PWM=2.0, RAMP=10.0, RECOVER_MAX=900.0)
# RAMP: K/min set-point ramp at a cold start; RECOVER_MAX: s a zone may stay outside the window after a fault
# TC_TAU [typ], ZONE_G [assumed W/K], STB_T set on the STB, T_LIMIT: element glands / seals / no flour-dust
# ignition margin [assumed], DEV_MAX: the PLC's own band alarm


class Plant:
    """The three zones: state T (air/chamber) and y (TC reading)."""

    def __init__(self):
        self.loads, self.els, _, _ = M.oven_power()
        self.n = len(self.loads)
        self.C = [OV.capacity(L, z["len_mm"], M.band_w()) for z in self.loads]
        self.P = [sum(e["P"] for e in self.els if e["zone"] == z["zone"]) for z in self.loads]
        self.Ts = [z["T"] for z in self.loads]
        self.Tp = self._product_temps()
        cz = L["CHAMBER"]
        self.mouth = lambda k, T: OV.mouth_loss(L, T, M.band_w() / 1000, cz["mouth_h"] / 1000)[0] \
            if k in (0, self.n - 1) else 0.0
        zl = M.zone_len()
        ch = OV.chamber(L, M.band_w(), zl)
        self.walls = lambda T: OV.wall_loss(L, T, ch["A_wall"], ch["A_out"])[0]

    def _product_temps(self):
        tr, _ = OV.simulate(L, OV.bake_segments(L, M.bake_t()), record=1.0)
        out = []
        for k in range(len(L["OVEN_ZONES"])):
            rows = [r for r in tr if r[1] == f"Z{k + 1}"]
            out.append(sum((r[2] + r[3] + r[4]) / 3 for r in rows) / len(rows))
        return out

    def load(self, k, T, f, band=True):
        z = self.loads[k]
        prod = (z["product"] + z["exhaust"]) * f * (T - self.Tp[k]) / (self.Ts[k] - self.Tp[k])
        bnd = z["band"] * (T - L["T_AMB"]) / (self.Ts[k] - L["T_AMB"]) if band else 0.0
        return self.walls(T) + self.mouth(k, T) + bnd + max(prod, 0.0)

    def u_ff(self, k, f):
        """Feed-forward: the duty that holds the set point at band content f (what FB_Oven precomputes)."""
        return min(1.0, self.load(k, self.Ts[k], f) / self.P[k])


def step_identify(pl, k, u0=None, du=0.1):
    """Open-loop step at the operating point (full band): (K C per unit duty, tau s, theta s)."""
    G, dt = CTRL["ZONE_G"], CTRL["DT"]
    u0 = pl.u_ff(k, 1.0) if u0 is None else u0
    T = list(pl.Ts)
    y = T[k]
    rows = []
    t = 0.0
    while t < 4 * 3600:
        u = u0 + (du if t > 0 else 0.0)
        q = u * pl.P[k] - pl.load(k, T[k], 1.0)
        T[k] += q * dt / pl.C[k]
        y += (T[k] - y) * dt / CTRL["TC_TAU"]
        rows.append((t, y))
        t += dt
    y0, y1 = rows[0][1], rows[-1][1]
    K = (y1 - y0) / du
    t28 = next(t for t, v in rows if v - y0 >= 0.283 * (y1 - y0))
    t63 = next(t for t, v in rows if v - y0 >= 0.632 * (y1 - y0))
    tau = 1.5 * (t63 - t28)                                     # two-point method (Smith)
    theta = max(t63 - tau, dt)
    return K, tau, theta


def tune(pl):
    out = []
    for k in range(pl.n):
        K, tau, theta = step_identify(pl, k)
        tc = CTRL["TAU_C_X"] * theta
        Kc = tau / (K * (tc + theta))
        Ti = min(tau, 4 * (tc + theta))
        out.append(dict(zone=f"Z{k + 1}", K=K, tau=tau, theta=theta, Kc=Kc, Ti=Ti))
    return out


def run(pl, gains, t_end, content, T0=None, fail=None, stuck=None, ff=True, record=10.0, ramp=False):
    """Closed loop. content(t) -> [f per zone]; fail = (zone, W lost, t0); stuck = (zone, t0).
    Returns dict(t, T, y, u, trip_t, alarm_t)."""
    G, dt = CTRL["ZONE_G"], CTRL["DT"]
    n = pl.n
    T = list(T0 or pl.Ts)
    y = list(T)
    I = [0.0] * n
    stb_open = [False] * n
    trip_t, alarm_t = [None] * n, [None] * n
    obs = [0.0] * n
    settled = [0.0] * n                                   # the observer runs 5 min after the set point is reached
    hist = dict(t=[], T=[], y=[], u=[])
    t, nxt = 0.0, 0.0
    while t <= t_end + 1e-9:
        f = content(t)
        u_all = []
        for k in range(n):
            g = gains[k]
            sp = min(pl.Ts[k], (T0 or pl.Ts)[k] + CTRL["RAMP"] / 60.0 * t) if ramp else pl.Ts[k]
            ramping = sp < pl.Ts[k]
            if ramping:
                settled[k] = t
            e = sp - y[k]
            u_ff = (pl.load(k, sp, f[k]) + (pl.C[k] * CTRL["RAMP"] / 60.0 if ramping else 0.0)) / pl.P[k] if ff else 0.0
            u = u_ff + g["Kc"] * (e + I[k] / g["Ti"])
            if 0.0 < u < 1.0 or (u >= 1.0 and e < 0) or (u <= 0.0 and e > 0):
                I[k] += e * dt                                    # conditional integration (anti-windup)
            u = min(max(u, 0.0), 1.0)
            if stuck and stuck[0] == k and t >= stuck[1]:
                u = 1.0
            if stb_open[k]:
                u = 0.0
            u_all.append(u)
            # duty observer: the measured duty vs the feed-forward model (a lost element raises the duty)
            r = u - pl.u_ff(k, f[k])
            obs[k] += (r - obs[k]) * dt / 60.0
            el = min(e_["P"] for e_ in pl.els if e_["zone"] == f"Z{k + 1}")
            if alarm_t[k] is None and obs[k] > 0.5 * el / pl.P[k] and t - settled[k] > 300:
                alarm_t[k] = t
        Tn = list(T)
        for k in range(n):
            P = pl.P[k] - (fail[1] if fail and fail[0] == k and t >= fail[2] else 0.0)
            nb = [j for j in (k - 1, k + 1) if 0 <= j < n]
            q = u_all[k] * P - pl.load(k, T[k], f[k]) + sum(G * (T[j] - T[k]) for j in nb)
            Tn[k] = T[k] + q * dt / pl.C[k]
        T = Tn
        for k in range(n):
            y[k] += (T[k] - y[k]) * dt / CTRL["TC_TAU"]
            if y[k] >= CTRL["STB_T"] and not stb_open[k]:      # the STB's own element: same lag
                stb_open[k] = True
                trip_t[k] = t
        if t >= nxt - 1e-9:
            hist["t"].append(round(t, 2))
            hist["T"].append([round(v, 2) for v in T])
            hist["y"].append([round(v, 2) for v in y])
            hist["u"].append([round(v, 3) for v in u_all])
            nxt += record
        t += dt
    hist.update(trip_t=trip_t, alarm_t=alarm_t)
    return hist


def bake_window():
    """Largest symmetric offset (K, 1 K steps) of every zone set point at which the cookie still bakes."""
    zones0 = [dict(z) for z in L["OVEN_ZONES"]]
    tb = M.bake_t()
    w = 0
    try:
        for d in range(1, 31):
            ok = True
            for sgn in (1, -1):
                for k, z in enumerate(L["OVEN_ZONES"]):
                    z["T"] = zones0[k]["T"] + sgn * d
                _, s = OV.simulate(L, OV.bake_segments(L, tb), record=1e9)
                ok = ok and OV.baked_ok(L, s)
            if not ok:
                break
            w = d
    finally:
        for k, z in enumerate(L["OVEN_ZONES"]):
            z["T"] = zones0[k]["T"]
    return w


def content_fn(stop=None):
    """f per zone vs t for a band that starts filling at t = 0 (or is full and stops depositing at stop[0] for
    stop[1] s): each zone fills / empties linearly over one zone residence."""
    n = len(L["OVEN_ZONES"])
    tz = M.bake_t() / n
    t_in = (M.stations()["zones"][0] - M.stations()["dep"]) / M.band_v()     # die -> zone 1

    def fill(t, k):
        a = t - t_in - k * tz
        return min(max(a / tz, 0.0), 1.0)

    if stop is None:
        return lambda t: [fill(t, k) for k in range(n)]
    t0, dur = stop

    def f(t):
        return [1.0 - fill(t - t0, k) + fill(t - t0 - dur, k) for k in range(n)]
    return f


def check(verbose=True, write=True):
    rows, fails = [], []

    def row(name, value, limit, ok, note):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"CONTROL {name}: {value} vs {limit} - {note}")

    pl = Plant()
    gains = tune(pl)
    for g in gains:
        rows.append((f"{g['zone']} model + tuning", f"K {g['K']:.0f} C/duty, tau {g['tau']:.0f} s, theta {g['theta']:.0f} s",
                     f"Kc {g['Kc']:.4f} /K, Ti {g['Ti']:.0f} s", True, "SIMC on an open-loop step at full band"))
    win = bake_window()
    lim = min(win, CTRL["DEV_MAX"])
    row("bake window", f"+-{win} K on every zone still bakes", f">= DEV_MAX {CTRL['DEV_MAX']:g} K", win >= CTRL["DEV_MAX"],
        "oven.simulate with all set points shifted")
    n = pl.n
    full = lambda t: [1.0] * n
    empty = lambda t: [0.0] * n
    res = {}
    # S1 cold start
    h = run(pl, gains, 3600.0, empty, T0=[L["T_AMB"]] * n, ramp=True)
    res["S1 cold start"] = h
    t_ok = []
    for k in range(n):
        inside = [abs(r[k] - pl.Ts[k]) <= 2.0 for r in h["y"]]
        first = next((i for i in range(len(inside)) if all(inside[i:])), None)
        t_ok.append(h["t"][first] if first is not None else math.inf)
    over = max(max(r[k] for r in h["y"]) - pl.Ts[k] for k in range(n))
    row("S1 cold start: settled +-2 K", f"{max(t_ok) / 60:.1f} min, overshoot {over:.1f} K",
        f"<= {L['WARMUP_MAX'] / 60:.0f} min, <= {CTRL['DEV_MAX']:g} K", max(t_ok) <= L["WARMUP_MAX"] and over <= CTRL["DEV_MAX"],
        f"empty band; set point ramped at {CTRL['RAMP']:g} K/min (FB_Oven), anti-windup")
    # S2 production start, S3 depositor stop
    for name, cont, tend in (("S2 production start", content_fn(), 1500.0),
                             ("S3 depositor stop 10 min", content_fn((0.0, 600.0)), 2400.0)):
        h = run(pl, gains, tend, cont, T0=list(pl.Ts) if name.startswith("S2") else None)
        h0 = run(pl, gains, tend, cont, T0=list(pl.Ts), ff=False)
        res[name] = h
        dev = max(abs(r[k] - pl.Ts[k]) for r in h["T"] for k in range(n))
        dev0 = max(abs(r[k] - pl.Ts[k]) for r in h0["T"] for k in range(n))
        row(name, f"max deviation {dev:.1f} K (PI alone {dev0:.1f} K)", f"<= {lim:g} K", dev <= lim,
            "feed-forward of the band content the PLC tracks + PI")
    # S4 one element open
    big = max((e for e in pl.els if e["zone"] == "Z1"), key=lambda e: e["P"])
    h = run(pl, gains, 3000.0, full, fail=(0, big["P"], 600.0))
    res["S4 element open"] = h
    dev = max(abs(r[0] - pl.Ts[0]) for r in h["T"])
    at = h["alarm_t"][0]
    out = [t for t, r in zip(h["t"], h["T"]) if abs(r[0] - pl.Ts[0]) > lim]
    t_out = (out[-1] - out[0] + 10.0) if out else 0.0
    # every cookie that was in zone 1 while it was out of the window carries the deviation in its NFC bake log
    # and is rejected at QC: (window time + one zone residence) x rate
    n_flag = math.ceil((t_out + M.bake_t() / n) / M.takt()) if out else 0
    row(f"S4 {big['tag']} open ({big['P']:.0f} W)", f"dev {dev:.1f} K, {t_out:.0f} s outside +-{lim:g} K, alarm after "
        + (f"{at - 600:.0f} s" if at else "never") + f"; {n_flag} cookies flagged",
        f"back in <= {CTRL['RECOVER_MAX']:g} s, alarm <= {CTRL['ALARM_MAX']:g} s", at is not None and
        at - 600 <= CTRL["ALARM_MAX"] and t_out <= CTRL["RECOVER_MAX"],
        "duty observer alarms; the out-of-window cookies are rejected by their bake log (QC), never sold")
    # S5 stuck SSR
    h = run(pl, gains, 1800.0, full, stuck=(0, 300.0))
    res["S5 SSR stuck on"] = h
    tmax = max(r[0] for r in h["T"])
    tt = h["trip_t"][0]
    row("S5 Z1 SSRs stuck on", f"STB trips {tt - 300:.0f} s later, air max {tmax:.0f} C" if tt else "STB never trips",
        f"trip at {CTRL['STB_T']:g} C, air <= {CTRL['T_LIMIT']:g} C", tt is not None and tmax <= CTRL["T_LIMIT"],
        "SF4: the STB (own TC element) drops KH1 - independent of the PLC")
    # nuisance: no normal scenario near the STB, no false alarm
    ymax = max(max(max(r) for r in res[k]["y"]) for k in ("S1 cold start", "S2 production start", "S3 depositor stop 10 min"))
    false = [k for k in ("S1 cold start", "S2 production start", "S3 depositor stop 10 min") if any(res[k]["alarm_t"])]
    row("no nuisance trip / false alarm", f"TC max {ymax:.0f} C, false alarms: {', '.join(false) or 'none'}",
        f"<= STB {CTRL['STB_T']:g} - {CTRL['STB_MARGIN']:g} C", ymax <= CTRL["STB_T"] - CTRL["STB_MARGIN"] and not false, "")
    if write:
        os.makedirs(OUT, exist_ok=True)
        json.dump(dict(ctrl=CTRL, gains=gains, window=win, scenarios=res, setpoints=pl.Ts,
                       P=pl.P, C=pl.C, Tp=pl.Tp), open(os.path.join(OUT, "control.json"), "w"))
    if verbose:
        for name, v, lim_, ok, note in rows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:34s} {v:52s} {lim_:34s} {note}")
        print("\n".join(fails) if fails else "ALL CONTROL PROOFS PASS (tuning, bake window, cold start, production "
                                             "start, depositor stop, element failure, stuck SSR / STB, nuisance)")
    return rows, fails, gains


if __name__ == "__main__":
    sys.exit(1 if check()[1] else 0)
