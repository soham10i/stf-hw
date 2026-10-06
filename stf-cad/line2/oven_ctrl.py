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
Upgrade V-1 (the real oven is not the model):
  LEARNING feed-forward  calm at the set point on an empty band, the PI share of the duty is the base-load
                         error -> W0; on a full band the product-load error -> factor a1 (slow, persistent)
  HEATER BREAK           current transducers on L1-L3 of the element feed (hardware.CT_AC); the PLC knows which
                         element is in its PWM slice, so it knows each phase's current - a short phase is a
                         broken element, the slices name it; a named element leaves the zone model, and a zone
                         that cannot carry the full band on the rest holds the depositor
  Mismatch               the physics can run a different oven (Mismatch) from the one the PLC carries (Plant)
Tuning: an open-loop step on the model at the operating point -> first order + dead time (K, tau, theta) ->
SIMC (Skogestad): Kc = tau / (K (tau_c + theta)), Ti = min(tau, 4 (tau_c + theta)), tau_c = TAU_C_X theta.

Scenarios (proofs):
  S1 cold start, empty band           at set point (+-2 K) within WARMUP_MAX, overshoot <= DEV_MAX
  S2 production start                 the band fills with cold dough: deviation <= bake window
  S3 depositor stop 10 min + restart  the load falls away and comes back: deviation <= bake window
  S4 heater break, every element      seen within ALARM_MAX, named within IDENT_MAX; a zone with N-1 capacity
                                      rides through (back inside RECOVER_MAX), any other holds the depositor
  S5 SSR stuck on (Z1, all elements)  the STB trips at STB_T, the zone air stays below T_LIMIT
  S6 model mismatch, 32 corners       C, losses, product load +-20 %, power +-10 %, TC lag x2, gains fixed: after
                                      a warm-up + one production hour of learning, S3 holds the bake window,
                                      and no corner raises a false heater-break alarm
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
CTRL = dict(TC_TAU=15.0, ZONE_G=3.0, DT=0.5, TAU_C_X=1.5, DEV_MAX=L["BAKE_MARGIN"], ALARM_MAX=5.0, STB_T=250.0,
            STB_MARGIN=15.0, T_LIMIT=300.0, PWM=2.0, RAMP=10.0, RECOVER_MAX=900.0,
            HB_DT=0.05, HB_HOLD=0.2, HB_PROBE_AFTER=4.0, IDENT_MAX=30.0, U_MAX=0.95, LEARN_BAND=0.5, LEARN_HOLD=120.0, LEARN_TAU=600.0, A1_MIN=0.5, A1_MAX=1.6,
            MM=dict(cf=0.2, lb=0.2, lp=0.2, pf=0.1, tf=1.0))
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
        _, _, plan, _ = M.oven_power()
        self.phase = {tag: ph for ph, items in plan.items() for tag, _ in items}
        self.fans = {tag: w for items in plan.values() for tag, w in items if tag.startswith("QF")}
        # elements per zone in FB_Oven order: element i of n conducts in the PWM slice [i/n, i/n + duty)
        self.zel = [[e for e in self.els if e["zone"] == z["zone"]] for z in self.loads]
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


class Mismatch:
    """The REAL oven, unlike the model the PLC carries: heat capacity x cf, base losses (walls, mouths, band) x lb,
    product + vapour load x lp, element power x pf (supply voltage, element ageing), TC lag x tf (sheath)."""

    def __init__(self, pl, cf=1.0, lb=1.0, lp=1.0, pf=1.0, tf=1.0):
        self.n, self.Ts, self.els = pl.n, pl.Ts, pl.els
        self.C = [c * cf for c in pl.C]
        self.P = [p * pf for p in pl.P]
        self.tc_tau = CTRL["TC_TAU"] * tf
        self._pl, self.lb, self.lp = pl, lb, lp

    def load(self, k, T, f, band=True):
        b = self._pl.load(k, T, 0.0, band)
        return b * self.lb + (self._pl.load(k, T, f, band) - b) * self.lp


def adapt0(n):
    """Learned feed-forward corrections: W0 = extra base load (W), a1 = product-load factor."""
    return dict(W0=[0.0] * n, a1=[1.0] * n)


def ff_load(pl, ad, k, T, f):
    b = pl.load(k, T, 0.0)
    return b + ad["W0"][k] + ad["a1"][k] * (pl.load(k, T, f) - b)


class _HeaterBreak:
    """Heater-break detection (FB_Oven): AC current transducers on L1/L2/L3 of the element feed (after K3/K4, the
    fans on it too, the 24 V PSU before it). The PLC knows which element is in its PWM slice, so it knows the
    current each phase SHOULD carry; it lags that by the transducer's response and compares. A phase short by
    more than half its smallest element for HB_HOLD s is a broken element: the elements that were in their
    slice through every short interval name it (the slices are staggered, so a few periods separate them).
    Accuracy is applied against the proof: it lowers the reading when no element is broken (nuisance) and
    raises it when one is (detection)."""

    def __init__(self, pl, tp, fail, sign):
        ct = H.CT_AC
        self.pl, self.fail, self.tau = pl, fail, ct["t_resp"] / 3          # t_resp = 3 time constants (95 %)
        self.err = sign * ct["acc"] * ct["range"]
        self.rI = [math.sqrt(tp.P[k] / pl.P[k]) for k in range(pl.n)]       # resistive: I ~ sqrt(P)
        self.U = H.SUPPLY["U"]
        self.fail_tag = None
        if fail:
            self.fail_tag = fail[3] if len(fail) > 3 else next(e["tag"] for e in pl.zel[fail[0]] if e["P"] == fail[1])
        self.phases = sorted(set(pl.phase.values()))
        self.thr = {ph: 0.5 * min(e["P"] for e in pl.els if pl.phase[e["tag"]] == ph) / self.U for ph in self.phases}
        self.fan = {ph: sum(w for tag, w in pl.fans.items() if pl.phase[tag] == ph) / self.U for ph in self.phases}
        self.fe = {ph: self.fan[ph] for ph in self.phases}            # lagged expected / measured
        self.fm = dict(self.fe)
        self.short = {ph: 0.0 for ph in self.phases}
        self.cand = {ph: None for ph in self.phases}
        self.alarm = {ph: None for ph in self.phases}        # (t, candidates) once a phase has alarmed
        self.ident = {}                                      # tag -> t it was named alone
        self.probe = {ph: None for ph in self.phases}        # (tag, t0, worst short): candidate held off to test it
        self.last_on = {ph: set() for ph in self.phases}
        self.since = {ph: 0.0 for ph in self.phases}         # t the set of conducting elements last changed
        self.on_t = {}                                       # tag -> last t it was in its slice
        self.zone_of = {e["tag"]: k for k, z in enumerate(pl.zel) for e in z}
        self.h = CTRL["HB_DT"]

    def sample(self, t, duty, stb_open, dt):
        out = []
        steps = max(1, round(dt / self.h))
        for j in range(steps):
            tt = t - dt + (j + 1) * dt / steps
            ph_t = (tt / CTRL["PWM"]) % 1.0
            exp = dict(self.fan)
            mea = dict(self.fan)
            on = {ph: set() for ph in self.phases}
            for k, zel in enumerate(self.pl.zel):
                if stb_open[k]:
                    continue
                for i, e in enumerate(zel):
                    ph = self.pl.phase[e["tag"]]
                    if self.probe[ph] and self.probe[ph][0] == e["tag"]:
                        continue                                # the PLC holds the probed candidate off
                    if ((ph_t - i / len(zel)) % 1.0) < duty[k]:
                        on[ph].add(e["tag"])
                        exp[ph] += e["P"] / self.U
                        if not (self.fail and e["tag"] == self.fail_tag and tt >= self.fail[2]):
                            mea[ph] += e["P"] / self.U * self.rI[k]
            for ph in self.phases:
                for x in on[ph]:
                    self.on_t[x] = tt
            a = min(1.0, (dt / steps) / self.tau)
            for ph in self.phases:
                # active probe: a phase alarm the slices cannot resolve (the candidates conduct together, e.g. at
                # full duty) - each candidate is held off for HB_PROBE s in turn; the short vanishes -> it is the one
                pr = self.probe[ph]
                if pr and tt - pr[1] >= H.CT_AC["t_resp"]:          # worst short once the probe has settled
                    self.probe[ph] = pr = (pr[0], pr[1], max(pr[2], self.fe[ph] - (self.fm[ph] + self.err)))
                if pr and tt - pr[1] >= CTRL["PWM"] + H.CT_AC["t_resp"]:   # a full period: its slice came
                    gone = pr[2] < 0.5 * self.thr[ph]
                    c = self.alarm[ph][1]
                    c = {pr[0]} if gone else c - {pr[0]}
                    self.alarm[ph] = (self.alarm[ph][0], c)
                    self.probe[ph] = None
                    if len(c) == 1:
                        self.ident.setdefault(next(iter(c)), tt)
                elif (not pr and self.alarm[ph] and len(self.alarm[ph][1]) > 1
                      and tt - self.alarm[ph][0] >= CTRL["HB_PROBE_AFTER"]):
                    self.probe[ph] = (sorted(self.alarm[ph][1])[0], tt, -1e9)
                if on[ph] != self.last_on[ph]:
                    self.last_on[ph], self.since[ph] = on[ph], tt
                settled = abs(exp[ph] - self.fe[ph]) < 0.1 * self.thr[ph]
                self.fe[ph] += (exp[ph] - self.fe[ph]) * a
                self.fm[ph] += (mea[ph] - self.fm[ph]) * a
                if self.probe[ph]:
                    continue                                    # the probe decides; the slice logic waits
                if self.fe[ph] - (self.fm[ph] + self.err) > self.thr[ph]:
                    self.short[ph] += dt / steps
                    # the reading lags by t_resp: a short now comes from an element on at some time in that window
                    recent = {x for x in self.on_t if self.pl.phase[x] == ph and self.on_t[x] >= tt - H.CT_AC["t_resp"]}
                    self.cand[ph] = recent if self.cand[ph] is None else self.cand[ph] & recent
                    c = self.cand[ph] or set()
                    if self.short[ph] >= CTRL["HB_HOLD"] and c:
                        if self.alarm[ph] is None:
                            self.alarm[ph] = (tt, c)
                            out += [(k, "/".join(sorted(c))) for k in sorted({self.zone_of[x] for x in c})]
                        else:
                            c = self.alarm[ph][1] & c
                            if not c:                       # contradiction: start the diagnosis again
                                self.alarm[ph], self.cand[ph] = None, None
                                continue
                            self.alarm[ph] = (self.alarm[ph][0], c)
                        if len(c) == 1:
                            self.ident.setdefault(next(iter(c)), tt)
                else:
                    steady = tt - self.since[ph] >= H.CT_AC["t_resp"]  # the same elements on for t_resp
                    if settled and steady and self.fe[ph] - self.fm[ph] < 0.2 * self.thr[ph]:
                        if self.alarm[ph]:                  # conducted while the phase read right: not it
                            c = self.alarm[ph][1] - on[ph]
                            if not c:                       # nothing left (the element came back): re-arm
                                self.alarm[ph] = None
                                continue
                            self.alarm[ph] = (self.alarm[ph][0], c)
                            if len(c) == 1:
                                self.ident.setdefault(next(iter(c)), tt)
                    if self.short[ph] < CTRL["HB_HOLD"]:
                        self.cand[ph] = None
                    self.short[ph] = 0.0
        return out


def run(pl, gains, t_end, content, T0=None, fail=None, stuck=None, ff=True, record=10.0, ramp=False, true=None,
        adapt=None, I0=None, learn=True):
    """Closed loop. content(t) -> [f per zone]; fail = (zone, W lost, t0); stuck = (zone, t0).
    pl is what the PLC knows (feed-forward, observer); true is the oven the physics runs (default: the model).
    adapt: the learned feed-forward state (adapt0), updated in place - the PLC keeps it in PERSISTENT memory.
    I0: the integrators to start from (hist["I"] of a previous run: the PLC runs on); learn=False freezes adapt.
    Returns dict(t, T, y, u, trip_t, alarm_t)."""
    G, dt = CTRL["ZONE_G"], CTRL["DT"]
    n = pl.n
    tp = true or pl
    tc_tau = getattr(tp, "tc_tau", CTRL["TC_TAU"])
    ad = adapt if adapt is not None else adapt0(n)
    calm = [0.0] * n                                      # s the zone has been inside +-LEARN_BAND
    T = list(T0 or pl.Ts)
    y = list(T)
    I = list(I0) if I0 else [0.0] * n
    stb_open = [False] * n
    trip_t, alarm_t, alarm_tag = [None] * n, [None] * n, [None] * n
    hb = _HeaterBreak(pl, tp, fail, +1.0 if fail else -1.0)
    lost = [0.0] * n                                      # W of named broken elements per zone
    hist = dict(t=[], T=[], y=[], u=[])
    t, nxt = 0.0, 0.0
    while t <= t_end + 1e-9:
        f = content(t)
        u_all = []
        for k in range(n):
            g = gains[k]
            sp = min(pl.Ts[k], (T0 or pl.Ts)[k] + CTRL["RAMP"] / 60.0 * t) if ramp else pl.Ts[k]
            ramping = sp < pl.Ts[k]
            e = sp - y[k]
            Pk = pl.P[k] - lost[k]
            u_ss = ff_load(pl, ad, k, sp, f[k]) / Pk
            u_ff = (u_ss + (pl.C[k] * CTRL["RAMP"] / 60.0 / Pk if ramping else 0.0)) if ff else 0.0
            u = u_ff + g["Kc"] * pl.P[k] / Pk * (e + I[k] / g["Ti"])
            if 0.0 < u < 1.0 or (u >= 1.0 and e < 0) or (u <= 0.0 and e > 0):
                I[k] += e * dt                                    # conditional integration (anti-windup)
            u = min(max(u, 0.0), 1.0)
            # LEARNING feed-forward: while the zone sits calm at its set point on an empty or a full band, the
            # PI share of the duty is the model error -> moved slowly into W0 (empty) or a1 (full); the
            # integrator gives back what the feed-forward takes over, so the duty does not jump
            calm[k] = calm[k] + dt if abs(e) < CTRL["LEARN_BAND"] and not ramping else 0.0
            if learn and ff and calm[k] > CTRL["LEARN_HOLD"] and not any(alarm_t) and (f[k] < 0.05 or f[k] > 0.95):
                dW = (u - u_ff) * pl.P[k] * dt / CTRL["LEARN_TAU"]
                if f[k] < 0.05:
                    ad["W0"][k] += dW
                else:
                    prod = pl.load(k, sp, f[k]) - pl.load(k, sp, 0.0)
                    a = min(max(ad["a1"][k] + dW / prod, CTRL["A1_MIN"]), CTRL["A1_MAX"])
                    dW = (a - ad["a1"][k]) * prod
                    ad["a1"][k] = a
                I[k] -= dW / pl.P[k] / g["Kc"] * g["Ti"]
            if stuck and stuck[0] == k and t >= stuck[1]:
                u = 1.0
            if stb_open[k]:
                u = 0.0
            u_all.append(u)
        for k, tag in hb.sample(t, u_all, stb_open, dt):           # heater-break: measured vs expected phase current
            if alarm_t[k] is None:
                alarm_t[k], alarm_tag[k] = t, tag
        for tag in hb.ident:                                      # named: the PLC takes it out of its zone model
            k = hb.zone_of[tag]
            lost[k] = sum(e["P"] for e in pl.zel[k] if e["tag"] in hb.ident)
        Tn = list(T)
        for k in range(n):
            P = tp.P[k] - (fail[1] * tp.P[k] / pl.P[k] if fail and fail[0] == k and t >= fail[2] else 0.0)
            nb = [j for j in (k - 1, k + 1) if 0 <= j < n]
            q = u_all[k] * P - tp.load(k, T[k], f[k]) + sum(G * (T[j] - T[k]) for j in nb)
            Tn[k] = T[k] + q * dt / tp.C[k]
        T = Tn
        for k in range(n):
            y[k] += (T[k] - y[k]) * dt / tc_tau
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
    hist.update(I=list(I), trip_t=trip_t, alarm_t=alarm_t, alarm_tag=alarm_tag, ident=dict(hb.ident), adapt=dict(W0=list(ad["W0"]), a1=list(ad["a1"])))
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


def check(verbose=True, write=True, quick=False):
    """quick: skip S6 (it is itself a +-20 % sweep of the plant) - for verify_plan's perturbed runs."""
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
    # S4 heater break: every element, open at t = 600 s in full production
    tz = M.bake_t() / n
    for k in range(n):
        worst = None
        for el in pl.zel[k]:
            fl = (k, el["P"], 600.0, el["tag"])
            ride = (pl.P[k] - el["P"]) * CTRL["U_MAX"] >= pl.load(k, pl.Ts[k], 1.0)
            h = run(pl, gains, 3000.0, full, fail=fl)
            named = h["ident"]
            t_id = named.get(el["tag"])
            if not ride and t_id is not None:          # the zone cannot carry the load: the depositor stops
                h = run(pl, gains, 3000.0 + t_id, content_fn((t_id, 1e9)), fail=fl)
            det = min([a_ for a_ in h["alarm_t"] if a_ is not None] + ([t_id] if t_id is not None else []), default=None)
            out = [t for t, r in zip(h["t"], h["T"]) if abs(r[k] - pl.Ts[k]) > lim]
            t_out = (out[-1] - out[0] + 10.0) if out else 0.0
            back = not out or out[-1] < h["t"][-1] - 60.0
            n_flag = math.ceil((t_out + tz) / M.takt()) if out else 0
            ok = (det is not None and det - 600.0 <= CTRL["ALARM_MAX"] and list(named) == [el["tag"]]
                  and t_id - 600.0 <= CTRL["IDENT_MAX"] and back and (not ride or t_out <= CTRL["RECOVER_MAX"]))
            r_ = dict(tag=el["tag"], P=el["P"], ride=ride, det=det, t_id=t_id, t_out=t_out, n_flag=n_flag,
                      dev=max(abs(r[k] - pl.Ts[k]) for r in h["T"]), ok=ok)
            if k == 0 and el is max(pl.zel[0], key=lambda e_: e_["P"]):
                res["S4 element open"] = h
            if worst is None or (not ok, r_["t_out"]) > (not worst["ok"], worst["t_out"]):
                worst = r_
        w = worst
        row(f"S4 heater break Z{k + 1} ({len(pl.zel[k])} el.)",
            f"worst {w['tag']}: seen {w['det'] - 600:.1f} s, named {w['t_id'] - 600:.1f} s, " if w["det"] and w["t_id"]
            else f"worst {w['tag']}: NOT detected / named, ",
            f"seen <= {CTRL['ALARM_MAX']:g} s, named <= {CTRL['IDENT_MAX']:g} s", w["ok"],
            (f"rides through on N-1 (dev {w['dev']:.1f} K, {w['t_out']:.0f} s outside), {w['n_flag']} cookies flagged"
             if w["ride"] else f"N-1 < load: the depositor stops when it is named; {w['n_flag']} cookies flagged") +
            "; phase-current check (CT_AC on L1-L3) against the PWM slices")
        rows[-1] = (rows[-1][0], rows[-1][1] + ("ride-through" if w["ride"] else "depositor stops"), *rows[-1][2:])
    # S6 the real oven is not the model: fixed gains, the feed-forward learns (warm-up -> W0, production -> a1)
    mm, worst6, day1, false6, a1s, w0s = CTRL["MM"], 0.0, 0.0, [], [], [1.0]
    import itertools
    for cf, lb, lp, pf, tf in [] if quick else itertools.product(*[(1 - mm[k_], 1 + mm[k_]) for k_ in ("cf", "lb", "lp", "pf")],
                                                (1.0, 1.0 + mm["tf"])):
        tp = Mismatch(pl, cf, lb, lp, pf, tf)
        ad = adapt0(n)
        h1 = run(pl, gains, 3600.0, empty, T0=[L["T_AMB"]] * n, ramp=True, true=tp, adapt=ad)
        h2 = run(pl, gains, 3600.0, content_fn(), T0=h1["T"][-1], true=tp, adapt=ad)
        h3 = run(pl, gains, 2400.0, content_fn((0.0, 600.0)), T0=h2["T"][-1], true=tp, adapt=ad, I0=h2["I"])
        worst6 = max(worst6, max(abs(r[k] - pl.Ts[k]) for r in h3["T"] for k in range(n)))
        day1 = max(day1, max(abs(r[k] - pl.Ts[k]) for r in h2["T"] for k in range(n)))
        if any(a_ for h_ in (h1, h2, h3) for a_ in h_["alarm_t"]) or any(h_["trip_t"][k] for h_ in (h1, h2, h3) for k in range(n)):
            false6.append(f"{cf:g}/{lb:g}/{lp:g}/{pf:g}/{tf:g}")
        a1s += ad["a1"]
        w0s += ad["W0"]
    a1s = a1s or [1.0]
    clamp = any(a_ <= CTRL["A1_MIN"] + 1e-6 or a_ >= CTRL["A1_MAX"] - 1e-6 for a_ in a1s)
    if not quick:
        row("S6 model mismatch (32 corners)", f"after learning {worst6:.1f} K; learned a1 {min(a1s):.2f}..{max(a1s):.2f}, "
            f"W0 {min(w0s):.0f}..{max(w0s):.0f} W", f"<= {lim:g} K, no false alarm", worst6 <= lim and not false6 and not clamp,
            f"C +-{mm['cf']:.0%}, losses +-{mm['lb']:.0%}, product +-{mm['lp']:.0%}, power +-{mm['pf']:.0%}, TC lag x"
            f"{1 + mm['tf']:g}; gains fixed. Day 1 before learning: up to {day1:.1f} K - the commissioning hour is "
            "flagged by its bake log" + (f"; FALSE ALARM in {', '.join(false6)}" if false6 else "") +
            ("; a1 at its clamp" if clamp else ""))
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
                                             "start, depositor stop, heater break, model mismatch, stuck SSR / STB, nuisance)")
    return rows, fails, gains


if __name__ == "__main__":
    sys.exit(1 if check()[1] else 0)
