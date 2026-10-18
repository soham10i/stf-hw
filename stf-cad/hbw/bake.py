"""
Upgrade 19 - the bake as a process (`make bake`; STF_VARIANT=up12).

Until now the oven waited a fixed time and every cookie came out right. A real bake is heat
and water: the elements heat the chamber, every door opening cools it, the cookie's surface
dries and browns while its centre is still heating, and how a cookie turns out depends on the
oven's state when it went in, on the dough, and on when the bake is ended. This module models
that, from the oven's own parts (oven_model.py: the chamber, its liner and insulation, the
four tubular elements, the thermocouple, the fan, the door) and the order's real door
openings (control.py), and asks what the PLC should do about it.

  OVEN     three thermal nodes - the top elements, the bottom elements, the liner and walls -
           and the chamber air (quasi-steady: its 9 J/K settle in under a second). Elements
           radiate (Stefan-Boltzmann) and convect; the walls lose through 10 mm of ceramic
           fibre; the door, the steam vent and an open mouth (buoyant two-way exchange) lose
           to the hall. A PI controller on the thermocouple (first-order lag) drives the
           solid-state relay Q9; the convection fan stops while the door is open.
  TRAY     the Ofenschieber: heated inside the oven, cooling outside while it is presented.
  COOKIE   a 45 mm disc, 1-D through its thickness: conduction, radiation from the top
           element and the liner, convection, contact with the tray underneath; water leaves
           each layer at a rate following water's vapour pressure (Clausius-Clapeyron), each
           kilogram taking its latent heat; the top surface browns (first-order Arrhenius
           kinetics) once it is dry enough.
  QUALITY  done = the centre has reached 95 C and the cookie is dry (<= 4.5 % water, wet
           basis); colour = the browning index in its band. Underbaked or burnt as the camera
           (Upgrade 15) would call it.
  CONTROL  three ways to end a bake, run over the same lots of dough and the same hall:
           timer       a fixed time, set on a nominal cookie (what the lamp dwell did);
           soft sensor the PLC runs the cookie model on the thermocouple and ends the bake
                       when the modelled cookie is done and brown enough;
           + camera    the soft sensor, its colour target corrected after every cookie
                       by the camera's measured colour (run-to-run control).

Every material value, coefficient and disturbance is ASSUMED and tagged as such in the
export; two constants are calibrated so a nominal 8 mm cookie bakes in about ten minutes at
180 C, as cookies of that size do, and the export says so. Replace them with a measured bake
(a thermocouple in a dough piece, a colour reading) before trusting the numbers.
"""
from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass, field

import oven_model as OM

SIG = 5.670e-8                 # W/(m2 K4)
R_GAS = 8.314                  # J/(mol K)
K0 = 273.15
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "bake")

# ------------------------------------------------------------------ parameters
# (value, unit, source). source: "model" = taken from oven_model.py; "assumed" = a typical
# value, to be measured; "calibrated" = chosen so the nominal bake matches typical practice.
q = OM.O
_ix0 = q["CH_X"][0] + q["WALL"]
IN_L = (q["CH_X"][1] - _ix0) / 1000                         # m, interior depth (back to mouth)
IN_W = (q["CH_Y"][1] - q["CH_Y"][0] - 2 * q["WALL"]) / 1000  # m, interior width
IN_H = (q["CH_Z"][1] - q["CH_Z"][0]) / 1000                  # m, interior height
MOUTH_W = IN_W
MOUTH_H = (q["MOUTH_TOP"] - q["CH_Z"][0]) / 1000
RUN = (q["HEAT_X"][1] - q["HEAT_X"][0]) / 1000               # m, one straight run of an element
L_TOP = 2 * RUN + (q["TOP_Y"][1] - q["TOP_Y"][0]) / 1000     # the grill hairpin
L_BOT = sum(2 * RUN + (b - a) / 1000 for a, b in q["BOT_Y"])  # two bottom hairpins
D_EL = q["HEATER_D"] / 1000

P = {
    # the oven (geometry from oven_model.py)
    "volume_l": (IN_L * IN_W * IN_H * 1000, "l", "model"),
    "liner_area": (2 * IN_L * IN_H + IN_W * IN_H + 2 * IN_L * IN_W, "m2", "model"),
    "mouth": (MOUTH_W * MOUTH_H, "m2", "model"),
    "p_top": (800.0, "W", "model"),             # one grill hairpin, 2 x 400 W (oven_model.py)
    "p_bot": (500.0, "W", "model"),             # two bottom hairpins, 250 W each
    "el_mass_per_m": (0.17, "kg/m", "assumed"),  # 8 mm sheathed element with MgO and coil
    "el_cp": (600.0, "J/(kg K)", "assumed"),
    "el_eps": (0.85, "", "assumed"),             # oxidised Incoloy sheath
    "liner_t": (q["LINER_T"] / 1000, "m", "model"),
    "steel_rho_cp": (7900 * 500.0, "J/(m3 K)", "assumed"),
    "liner_eps": (0.40, "", "assumed"),          # dull stainless
    "ins_t": (q["WALL"] / 1000, "m", "model"),   # 10 mm ceramic-fibre board
    "ins_k": (0.07, "W/(m K)", "assumed"),       # ceramic fibre at ~120 C mean
    "ins_rho_cp": (128 * 1070.0, "J/(m3 K)", "assumed"),
    "h_out": (10.0, "W/(m2 K)", "assumed"),      # casing to the hall: natural convection + radiation
    "h_fan": (25.0, "W/(m2 K)", "assumed"),      # inside, convection fan running
    "h_still": (8.0, "W/(m2 K)", "assumed"),     # inside, fan stopped (door open)
    "cd_mouth": (0.6, "", "assumed"),            # discharge coefficient of the mouth
    "vent_d": (q["VENT"][2] / 1000, "m", "model"),
    "tc_tau": (10.0, "s", "assumed"),            # K-type, 3 mm sheath, in moving air
    "setpoint": (180.0, "C", "model"),           # oven_model.py: "heats it to 180 C"
    "kp": (0.08, "1/K", "assumed"),              # PI on the thermocouple -> SSR duty 0..1
    "ti": (90.0, "s", "assumed"),
    "cutout": (250.0, "C", "model"),             # manual-reset over-temperature cutout
    "door_duty": (0.4, "", "assumed"),           # door open: the integral holds, the heat is capped
    # the tray (Ofenschieber, aluminium)
    "tray_dims": (tuple(v / 1000 for v in q["TRAY"]), "m", "model"),
    "tray_rho_cp": (2700 * 900.0, "J/(m3 K)", "assumed"),
    "h_contact": (120.0, "W/(m2 K)", "assumed"),  # dough on the tray
    "h_hall": (8.0, "W/(m2 K)", "assumed"),       # the tray outside, in the hall
    # the cookie
    "cookie_d": (q["WP_D"] / 1000, "m", "model"),
    "cookie_t": (0.008, "m", "assumed"),         # 8 mm of dough
    "rho_dough": (1150.0, "kg/m3", "assumed"),
    "x0": (0.20, "kg water / kg dry", "assumed"),  # ~17 % water, wet basis
    "x_eq": (0.015, "kg/kg", "assumed"),
    "cp_dry": (1600.0, "J/(kg K)", "assumed"),
    "cp_w": (4180.0, "J/(kg K)", "assumed"),
    "latent": (2.26e6, "J/kg", "assumed"),
    "k_dry": (0.15, "W/(m K)", "assumed"),       # conductivity: k = k_dry + k_w X
    "k_w": (1.0, "W/(m K)", "assumed"),
    "eps_cookie": (0.90, "", "assumed"),
    "evap_depth": (0.003, "m", "assumed"),       # vapour leaves the layers near the surface first
    "kd_ref": (1.137e-2, "1/s at 100 C", "calibrated"),
    "ea_brown": (90e3, "J/mol", "assumed"),      # Maillard browning, within the 20-160 kJ/mol reported
    "kb_ref": (5.365e-2, "1/s at 180 C", "calibrated"),
    "x_brown": (0.10, "kg/kg", "assumed"),       # the surface browns once below this moisture
    # quality
    "core_done": (95.0, "C", "assumed"),
    "x_done": (0.064, "kg/kg", "assumed"),       # 6 % water, wet basis: soft-baked to crisp cookies hold 3-6 %
    "b_band": ((0.35, 0.65), "", "assumed"),     # browning index: pale / right / burnt
    "b_target": (0.50, "", "assumed"),
    "n_layers": (16, "", "numerical"),
    "dt": (0.5, "s", "numerical"),
    "plc_layers": (8, "", "numerical"),          # the PLC's own cookie model: coarser, as a controller's would be
}
V = {k: v[0] for k, v in P.items()}


def psat(t_c):
    """Water's vapour pressure, Pa (Magnus); it sets how fast a layer can give up its water."""
    return 610.94 * math.exp(17.625 * t_c / (t_c + 243.04))


PSAT100 = psat(100.0)


# ------------------------------------------------------------------ the oven and the cookie
@dataclass
class Dough:
    thick: float = 0.008       # m
    t0: float = 18.0           # C, as it goes in
    x0: float = 0.20           # kg/kg


@dataclass
class Oven:
    """The oven's state: element, wall and tray temperatures, the thermocouple, the
    controller's integral and the energy ledger."""
    amb: float = 21.0
    power: float = 1.0          # share of the elements' rated power left (ageing)
    t_top: float = 21.0
    t_bot: float = 21.0
    t_wall: float = 21.0
    t_tray: float = 21.0
    t_tc: float = 21.0
    t_air: float = 21.0
    integ: float = 0.0
    tray_in: bool = True
    door: bool = False
    tripped: bool = False
    ledger: dict = field(default_factory=lambda: {k: 0.0 for k in
                         ("heater", "walls", "door", "vent", "mouth", "tray_hall", "steam", "cookie")})
    peak_air: float = 21.0
    peak_el: float = 21.0

    def __post_init__(self):
        for k in ("t_top", "t_bot", "t_wall", "t_tray", "t_tc", "t_air", "peak_air", "peak_el"):
            setattr(self, k, self.amb)

    def stored(self):
        """Heat held, J above 0 C (a fixed reference: the hall's temperature moves)."""
        return sum(c * t for c, t in
                   ((C_TOP, self.t_top), (C_BOT, self.t_bot), (C_WALL, self.t_wall), (C_TRAY, self.t_tray)))


# capacities and fixed conductances, from the parameters above
A_TOP = math.pi * D_EL * L_TOP
A_BOT = math.pi * D_EL * L_BOT
C_TOP = V["el_mass_per_m"] * L_TOP * V["el_cp"]
C_BOT = V["el_mass_per_m"] * L_BOT * V["el_cp"]
_ins_area = V["liner_area"] + 0.5 * 4 * V["ins_t"] * (IN_L + IN_W + IN_H)     # mid-insulation
C_WALL = V["liner_area"] * V["liner_t"] * V["steel_rho_cp"] + 0.5 * _ins_area * V["ins_t"] * V["ins_rho_cp"]
UA_WALL = _ins_area / (V["ins_t"] / V["ins_k"] + 1 / V["h_out"])
_tl, _tw, _th = V["tray_dims"]
A_TRAY = _tl * _tw * 2 + 2 * _th * (_tl + _tw)
C_TRAY = _tl * _tw * _th * V["tray_rho_cp"]
A_COOKIE = math.pi * V["cookie_d"] ** 2 / 4
# the cookie's view of the grill element: two runs (radius a) at distance D from the cookie,
# a differential area facing up sees each as F = (a / D) cos(theta)
_cz = (q["Z_W"] + 8.0) / 1000
_dz = q["TOP_Z"] / 1000 - _cz
F_TOP = sum((D_EL / 2) / math.hypot(_dz, (yy - q["TRAY_Y"]) / 1000) * _dz / math.hypot(_dz, (yy - q["TRAY_Y"]) / 1000)
            for yy in q["TOP_Y"])


def mouth_g(t_air, amb):
    """W/K through the open mouth: buoyant two-way exchange (doorway flow)."""
    dt = max(t_air - amb, 0.0)
    if dt <= 0:
        return 0.0
    tm = (t_air + amb) / 2 + K0
    flow = V["cd_mouth"] / 3 * MOUTH_W * math.sqrt(9.81 * MOUTH_H ** 3 * dt / tm)    # m3/s
    rho = 353.0 / (amb + K0)
    return rho * 1006 * flow


def vent_g(t_air, amb):
    """W/K through the steam vent: stack flow over the chamber's height."""
    dt = max(t_air - amb, 0.0)
    a = math.pi * V["vent_d"] ** 2 / 4
    flow = V["cd_mouth"] * a * math.sqrt(2 * 9.81 * IN_H * dt / (amb + K0))
    return 353.0 / (amb + K0) * 1006 * flow


G_DOOR = MOUTH_W * MOUTH_H / (1 / V["h_fan"] + 1 / V["h_out"])   # the shut steel door, W/K


class Cookie:
    """A dough disc in layers through its thickness: temperatures, moisture, browning."""

    def __init__(self, d: Dough, n: int | None = None):
        self.n = n or V["n_layers"]
        self.dx = d.thick / self.n
        self.mdry = V["rho_dough"] * A_COOKIE * self.dx / (1 + d.x0)
        self.t = [d.t0] * self.n           # 0 = bottom (on the tray), n-1 = top
        self.x = [d.x0] * self.n
        self.b = 0.0
        self.core_peak = d.t0
        self.x0 = d.x0

    def cap(self, i):
        return self.mdry * (V["cp_dry"] + self.x[i] * V["cp_w"])

    @property
    def core(self):
        n = self.n
        return (self.t[(n - 1) // 2] + self.t[n // 2]) / 2

    @property
    def xmean(self):
        return sum(self.x) / self.n

    def energy(self):
        """Heat held, J above 0 C."""
        return sum(self.cap(i) * self.t[i] for i in range(self.n))


def step(ov: Oven, ck: Cookie | None, dt: float, setpoint: float | None, duty: float | None = None):
    """Advance the oven (and the cookie on its tray, if any) by dt seconds. `duty` given: the
    elements run at it (the PLC's own model of the oven is fed the duty it commanded)."""
    amb = ov.amb
    fan = not ov.door
    h_in = V["h_fan"] if fan else V["h_still"]
    # the controller: PI on the thermocouple, SSR duty 0..1; the cutout latches the heat off
    if duty is not None:
        pass
    elif setpoint is None or ov.tripped:
        duty = 0.0
    else:
        e = setpoint - ov.t_tc
        u = V["kp"] * (e + ov.integ / V["ti"])
        if not ov.door and (0.0 < u < 1.0 or (u >= 1.0 and e < 0) or (u <= 0.0 and e > 0)):
            ov.integ += e * dt              # conditional integration: no wind-up
        duty = min(V["door_duty"] if ov.door else 1.0, max(0.0, u))
    p_top = duty * V["p_top"] * ov.power
    p_bot = duty * V["p_bot"] * ov.power
    tk = lambda t: t + K0  # noqa: E731
    # radiation from the elements: to the cookie (top element only) and to the walls
    ts = ck.t[-1] if (ck and ov.tray_in) else None
    q_top_ck = 0.0
    if ts is not None:
        q_top_ck = V["eps_cookie"] * V["el_eps"] * SIG * A_COOKIE * F_TOP * (tk(ov.t_top) ** 4 - tk(ts) ** 4)
    q_top_w = V["el_eps"] * SIG * A_TOP * (tk(ov.t_top) ** 4 - tk(ov.t_wall) ** 4) * 0.9   # 0.9: what it does not see of the door
    q_bot_w = V["el_eps"] * SIG * A_BOT * (tk(ov.t_bot) ** 4 - tk(ov.t_wall) ** 4)
    # the air, quasi-steady: every surface's convection and the losses to the hall balance
    g = {"top": h_in * A_TOP, "bot": h_in * A_BOT, "wall": h_in * V["liner_area"]}
    t_s = {"top": ov.t_top, "bot": ov.t_bot, "wall": ov.t_wall}
    if ov.tray_in:
        g["tray"], t_s["tray"] = h_in * (A_TRAY - A_COOKIE if ck else A_TRAY), ov.t_tray
        if ck:
            g["ck"], t_s["ck"] = h_in * A_COOKIE, ck.t[-1]
    g_vent = vent_g(ov.t_air, amb)
    g_out = g_vent + (mouth_g(ov.t_air, amb) if ov.door else G_DOOR)
    t_air = (sum(g[k] * t_s[k] for k in g) + g_out * amb) / (sum(g.values()) + g_out)
    ov.t_air = t_air
    conv = {k: g[k] * (t_s[k] - t_air) for k in g}       # W from each surface into the air
    # the walls: radiation in from the elements, convection, the insulation out; the tray
    # (inside) sees the walls by radiation over its sides and bottom
    q_wall_tray = 0.0
    if ov.tray_in:
        q_wall_tray = V["liner_eps"] * SIG * (A_TRAY - A_COOKIE) * (tk(ov.t_wall) ** 4 - tk(ov.t_tray) ** 4)
    q_ck_wall = 0.0
    if ts is not None:
        q_ck_wall = V["eps_cookie"] * V["liner_eps"] * SIG * A_COOKIE * (1 - F_TOP) * (tk(ov.t_wall) ** 4 - tk(ts) ** 4)
    q_walls = UA_WALL * (ov.t_wall - amb)
    ov.t_top += dt * (p_top - q_top_ck - q_top_w - conv["top"]) / C_TOP
    ov.t_bot += dt * (p_bot - q_bot_w - conv["bot"]) / C_BOT
    ov.t_wall += dt * (q_top_w + q_bot_w - conv["wall"] - q_wall_tray - q_ck_wall - q_walls) / C_WALL
    # the tray: inside it trades with the air, the walls and the cookie; outside, with the hall
    q_contact = 0.0
    if ck:
        q_contact = V["h_contact"] * A_COOKIE * (ov.t_tray - ck.t[0])
    if ov.tray_in:
        q_tray = q_wall_tray - conv.get("tray", 0.0) - q_contact
    else:
        q_hall = V["h_hall"] * (A_TRAY - (A_COOKIE if ck else 0)) * (ov.t_tray - amb)
        q_tray = -q_hall - q_contact
        ov.ledger["tray_hall"] += q_hall * dt
    ov.t_tray += dt * q_tray / C_TRAY
    # the cookie: the top takes radiation and convection (inside) or the hall (outside), the
    # bottom the tray; conduction between layers; each layer dries and takes its latent heat
    if ck:
        if ov.tray_in:
            q_in_top = q_top_ck + q_ck_wall - conv["ck"]
        else:
            q_in_top = V["h_hall"] * A_COOKIE * (amb - ck.t[-1])
            ov.ledger["tray_hall"] -= q_in_top * dt
        n = ck.n
        flux = [0.0] * (n + 1)                      # W between layer i-1 and i (positive up)
        flux[0] = q_contact
        for i in range(1, n):
            k = V["k_dry"] + V["k_w"] * (ck.x[i - 1] + ck.x[i]) / 2
            flux[i] = k * A_COOKIE * (ck.t[i - 1] - ck.t[i]) / ck.dx
        flux[n] = -q_in_top
        for i in range(n):
            z0, de = (n - 1 - i) * ck.dx, V["evap_depth"]          # the layer's depth below the top
            depth_f = de / ck.dx * (math.exp(-z0 / de) - math.exp(-(z0 + ck.dx) / de))   # its mean
            t_old, x_old, q_net = ck.t[i], ck.x[i], dt * (flux[i] - flux[i + 1])
            room = max(0.0, x_old - V["x_eq"])
            kd0 = V["kd_ref"] / PSAT100 * depth_f

            def dxw_at(t_new):
                return min(room, kd0 * psat(t_new) * room * dt)

            def resid(t_new):
                # the layer's balance with the water leaving at its NEW temperature (implicit:
                # evaporation cools the layer, which slows the evaporation)
                w = dxw_at(t_new)
                return ck.mdry * (V["cp_dry"] + (x_old - w) * V["cp_w"]) * (t_new - t_old) - q_net + w * ck.mdry * V["latent"]

            # resid rises with the temperature: a bracketed Newton (bisection when a step
            # would leave the bracket) - plain Newton can jump to where psat is undefined
            lo, hi = t_old - 150.0, t_old + 150.0
            tn = t_old
            for _ in range(40):
                r = resid(tn)
                if abs(r) < 1e-9:
                    break
                if r > 0:
                    hi = tn
                else:
                    lo = tn
                d = (resid(tn + 1e-3) - r) / 1e-3
                nxt = tn - r / d if d > 0 else (lo + hi) / 2
                tn = nxt if lo < nxt < hi else (lo + hi) / 2
                if hi - lo < 1e-7:
                    break
            dxw = dxw_at(tn)
            ck.x[i] = x_old - dxw
            latent = dxw * ck.mdry * V["latent"]
            # the steam leaves with its latent heat and its warmth above the hall
            ov.ledger["steam"] += latent + dxw * ck.mdry * V["cp_w"] * t_old
            ck.t[i] = t_old + (q_net - latent) / ck.cap(i)
        if ov.tray_in:
            ov.ledger["cookie"] += (q_top_ck + q_ck_wall - conv["ck"] + q_contact) * dt
        else:
            ov.ledger["cookie"] += q_contact * dt
        if ck.x[-1] < V["x_brown"]:
            kb = V["kb_ref"] * math.exp(-V["ea_brown"] / R_GAS * (1 / tk(ck.t[-1]) - 1 / tk(180.0)))
            ck.b += dt * kb * (1 - ck.b)
        ck.core_peak = max(ck.core_peak, ck.core)
    # the thermocouple lags the air
    ov.t_tc += dt * (t_air - ov.t_tc) / V["tc_tau"]
    if ov.t_air >= V["cutout"]:
        ov.tripped = True
    ov.peak_air = max(ov.peak_air, ov.t_air)
    ov.peak_el = max(ov.peak_el, ov.t_top, ov.t_bot)
    L = ov.ledger
    L["heater"] += (p_top + p_bot) * dt
    L["walls"] += q_walls * dt
    L["vent"] += g_vent * (t_air - amb) * dt
    L["door" if not ov.door else "mouth"] += (g_out - g_vent) * (t_air - amb) * dt
    return duty


def done(ck: Cookie) -> bool:
    return ck.core_peak >= V["core_done"] and ck.xmean <= V["x_done"]


def verdict(ck: Cookie) -> str:
    lo, hi = V["b_band"]
    if ck.b > hi:
        return "burnt"
    if not done(ck) or ck.b < lo:
        return "underbaked"
    return "ok"


def wet_pct(x):
    return 100 * x / (1 + x)


# ------------------------------------------------------------------ the cycle around a bake
def cycle(wait: float):
    """The segments around one bake, from the oven's step table (motion.OVEN_CYCLE): (seconds,
    door open, tray inside, cookie on the tray). `wait` is how long the presented tray waits
    for the robot to lay the next cookie on it."""
    import motion as MO
    d = [r[0] for r in MO.OVEN_CYCLE]
    before = [(d[1], True, True, False), (d[2], True, False, False), (wait, True, False, False),
              (d[3], True, False, True), (d[4], True, True, True)]
    after = [(d[6], True, True, True), (d[7], True, False, True), (d[8] + d[9] + d[10], True, False, True),
             (d[11] + d[12] + d[13], True, False, False), (d[14], True, False, False), (d[15], True, True, False)]
    return before, after


@dataclass
class Lot:
    thick: float
    x0: float
    t0: float
    fridge: bool


def lots(rng: random.Random, n: int) -> list[Lot]:
    """Dough lots: a lot is mixed, portioned and either baked from the bench or from the
    fridge (ASSUMED spreads)."""
    out = []
    for _ in range(n):
        fridge = rng.random() < 0.3
        out.append(Lot(min(0.0092, max(0.0070, rng.gauss(0.0080, 0.00035))), rng.gauss(0.20, 0.010),
                       rng.gauss(6.0, 1.5) if fridge else rng.gauss(20.0, 1.5), fridge))
    return out


def dough(rng: random.Random, lot: Lot) -> Dough:
    return Dough(thick=lot.thick + rng.gauss(0, 0.00012), t0=lot.t0 + rng.gauss(0, 0.8),
                 x0=lot.x0 + rng.gauss(0, 0.004))


POLICIES = ("timer", "soft", "camera", "ir")
POLICY_NAME = {"timer": "fixed timer", "soft": "soft sensor", "camera": "soft sensor + camera",
               "ir": "+ dough sensors"}
IR_SIGMA = 0.5         # C: an infrared thermometer over the presented tray reads the dough (ASSUMED)
LASER_SIGMA = 0.00005  # m: a laser distance sensor beside it reads the dough's height (ASSUMED)
LOT_SIZE = 12          # cookies per lot: one order
MAX_BAKE = 1500.0      # s: a bake never runs past this
CAM_SIGMA = 0.03       # the camera's colour reading, browning index (ASSUMED)
CAM_GAIN = 0.5         # run-to-run correction of the colour target per cookie


def preheat(amb: float, power: float, dt: float) -> tuple[Oven, float]:
    """An oven heated from the hall's temperature until the thermocouple settles; returns it
    and the time the thermocouple first read 180 C."""
    ov = Oven(amb=amb, power=power)
    t, t180 = 0.0, None
    while t < 2400:
        step(ov, None, dt, V["setpoint"])
        t += dt
        if t180 is None and ov.t_tc >= V["setpoint"] - 0.5:
            t180 = t
    return ov, t180


def hall(t_h: float) -> float:
    import month as MN
    return MN.temperature(t_h)


def run(policy: str, seed: int, n_lots: int = 4, dt: float | None = None, trace: bool = False,
        timer_s: float = 600.0, power: float | None = None) -> dict:
    """One shift of bakes: n_lots lots of LOT_SIZE cookies, back to back, ended by `policy`.
    The hall's temperature, the elements' ageing, the dough and the robot's waits are drawn
    from `seed`; the same seed gives every policy the same shift."""
    dt = dt or V["dt"]
    rng = random.Random(seed)
    start_h = rng.uniform(6, 14)
    power = power if power is not None else rng.uniform(0.88, 1.0)
    batch = lots(rng, n_lots)
    doughs = [(li, dough(rng, lot)) for li, lot in enumerate(batch) for _ in range(LOT_SIZE)]
    waits = [8.9 + rng.expovariate(1 / 6.0) for _ in doughs]
    cam = [rng.gauss(0, CAM_SIGMA) for _ in doughs]
    irn = [rng.gauss(0, IR_SIGMA) for _ in doughs]
    lzn = [rng.gauss(0, LASER_SIGMA) for _ in doughs]
    ov, _ = preheat(hall(start_h), power, dt)
    ov.ledger = {k: 0.0 for k in ov.ledger}      # the shift's ledger starts with a hot oven
    e0 = ov.stored()
    # the PLC's own model of the oven: nominal elements, the hall as its sensor reads it
    sh = Oven(amb=ov.amb + 0.5, power=1.0)
    for k in ("t_top", "t_bot", "t_wall", "t_tray", "t_tc", "t_air", "integ"):
        setattr(sh, k, getattr(ov, k))
    t, target, out, tr = 0.0, V["b_target"], [], []
    ck_energy_out = ck_energy_in = 0.0

    def tick(ck, shck, seg_door, seg_tray, sp=True):
        nonlocal t
        ov.door = sh.door = seg_door
        ov.tray_in = sh.tray_in = seg_tray
        ov.amb = hall(start_h + t / 3600)
        duty = step(ov, ck, dt, V["setpoint"] if sp else None)
        step(sh, shck, dt, None, duty=duty)
        # the observer: the thermocouple's error pulls the model's walls and air toward the
        # oven's (it learns the elements' ageing and the hall without measuring them)
        e = ov.t_tc - sh.t_tc
        sh.t_wall += 0.02 * e * dt
        sh.t_tc += 0.10 * e * dt
        sh.power = min(1.2, max(0.6, sh.power + 2e-5 * e * dt))   # the elements' output, learnt
        t += dt
        if trace and int(round(t / dt)) % int(round(10 / dt)) == 0:
            tr.append((round(t, 1), round(ov.t_air, 1), round(ov.t_tc, 1), round(duty, 3),
                       None if ck is None else round(ck.t[-1], 1), None if ck is None else round(ck.core, 1),
                       None if ck is None else round(wet_pct(ck.xmean), 2), None if ck is None else round(ck.b, 3),
                       int(seg_door)))
        return duty

    for i, (li, d) in enumerate(doughs):
        before, after = cycle(waits[i])
        if i and li != doughs[i - 1][0]:
            target = V["b_target"]          # a new lot: what the camera learnt was about the last one
        nominal = Dough()
        ck = shck = None
        for dur, door, tray, on in before:
            for _ in range(max(1, round(dur / dt))):
                if on and ck is None:
                    ck = Cookie(d)
                    # the PLC's model cookie: nominal dough, or the dough as measured
                    t0 = d.t0 + irn[i] if policy == "ir" else nominal.t0
                    th = d.thick + lzn[i] if policy == "ir" else nominal.thick
                    shck = Cookie(Dough(thick=th, t0=t0, x0=nominal.x0), V["plc_layers"])
                    ck_energy_in += ck.energy()
                tick(ck if on else None, shck if on else None, door, tray)
        # the bake: door shut, tray in, until the policy ends it
        tb = 0.0
        while tb < MAX_BAKE:
            tick(ck, shck, False, True)
            tb += dt
            if policy == "timer":
                if tb >= timer_s:
                    break
            elif done(shck) and shck.b >= target:
                break
        for dur, door, tray, on in after:
            for _ in range(max(1, round(dur / dt))):
                tick(ck if on else None, shck if on else None, door, tray)
        ck_energy_out += ck.energy()
        v = verdict(ck)
        seen = ck.b + cam[i]
        if policy in ("camera", "ir"):
            # run-to-run: the next cookie's colour target moves against the colour just seen
            target = min(0.70, max(0.30, target - CAM_GAIN * (seen - V["b_target"])))
        out.append({"lot": li, "fridge": batch[li].fridge, "thick_mm": round(d.thick * 1000, 2),
                    "t0": round(d.t0, 1), "x0": round(d.x0, 3), "bake_s": round(tb, 1), "b": round(ck.b, 3),
                    "water_pct": round(wet_pct(ck.xmean), 2), "core_peak": round(ck.core_peak, 1),
                    "verdict": v, "camera_b": round(seen, 3), "target": round(target, 3)})
    L = ov.ledger
    losses = sum(L[k] for k in ("walls", "door", "vent", "mouth", "tray_hall", "steam"))
    closure = (L["heater"] - (ov.stored() - e0) - losses - (ck_energy_out - ck_energy_in)) / L["heater"]
    return {"policy": policy, "seed": seed, "power": round(power, 3), "cookies": out, "t_s": round(t, 1),
            "heater_kwh": L["heater"] / 3.6e6, "ledger_kwh": {k: round(v / 3.6e6, 4) for k, v in L.items()},
            "closure": closure, "peak_air": ov.peak_air, "peak_el": ov.peak_el, "tripped": ov.tripped,
            "power_learnt": round(sh.power, 3), "trace": tr}


# ------------------------------------------------------------------ a nominal bake, and the checks
def nominal(n: int | None = None, dt: float | None = None, d: Dough | None = None, power: float = 1.0,
            setpoint: float | None = None, amb: float = 21.0, trace: bool = False) -> dict:
    """One cookie in a settled oven, door shut, no disturbance: when it is done, when its
    colour passes the target, and (with trace) its curves."""
    dt = dt or V["dt"]
    sp = setpoint or V["setpoint"]
    ov = Oven(amb=amb, power=power)
    for _ in range(int(2400 / dt)):
        step(ov, None, dt, sp)
    ck = Cookie(d or Dough(), n)
    t, t_done, t_b, plateau, tr = 0.0, None, None, [], []
    while t < MAX_BAKE:
        step(ov, ck, dt, sp)
        t += dt
        if ck.xmean > 0.12:
            plateau.append(ck.core)
        if t_done is None and done(ck):
            t_done = t
        if t_b is None and ck.b >= V["b_target"]:
            t_b = t
        if trace and abs(t / 10 - round(t / 10)) < 1e-9:
            tr.append({"t": round(t), "surface": round(ck.t[-1], 1), "core": round(ck.core, 1), "bottom": round(ck.t[0], 1),
                       "water": round(wet_pct(ck.xmean), 2), "b": round(ck.b, 3), "air": round(ov.t_air, 1)})
        if t_b is not None and t_done is not None and (not trace or t > t_b + 240):
            break
    return {"t_done": t_done, "t_b": t_b, "plateau": (min(plateau), max(plateau)) if plateau else None, "trace": tr}


def heatup(dt: float = 1.0) -> dict:
    """From the hall's 21 C to the setpoint and on until settled: the PI controller's first
    heating, the elements' peak, the overshoot and the hold power."""
    ov = Oven(amb=21.0)
    t, t180, duty, tr = 0.0, None, [], []
    while t < 3600:
        u = step(ov, None, dt, V["setpoint"])
        t += dt
        duty.append(u)
        if t180 is None and ov.t_tc >= V["setpoint"] - 0.5:
            t180 = t
        if abs(t / 10 - round(t / 10)) < 1e-9:
            tr.append({"t": round(t), "air": round(ov.t_air, 1), "tc": round(ov.t_tc, 1), "top": round(ov.t_top, 1),
                       "bot": round(ov.t_bot, 1), "wall": round(ov.t_wall, 1), "duty": round(u, 3)})
    hold = sum(duty[-600:]) / 600 * (V["p_top"] + V["p_bot"])
    return {"t180": t180, "peak_air": ov.peak_air, "peak_el": ov.peak_el, "hold_w": hold,
            "preheat_kwh": sum(duty[: int((t180 or 0) / dt)]) * dt * (V["p_top"] + V["p_bot"]) / 3.6e6,
            "trace": tr, "tripped": ov.tripped}


def checks(runs: dict | None = None, verbose: bool = True) -> list[str]:
    """The model's proofs: energy, the oven against its CAD note and its controller's limits,
    numerical convergence and stability, the calibration, the physics' directions, and the
    control policies' ranking on the same shifts."""
    fails = []
    # 0 stability of the explicit steps: the cookie's layers and the elements
    dx = V["cookie_t"] / V["n_layers"]
    k_max = V["k_dry"] + V["k_w"] * V["x0"]
    c_min = V["rho_dough"] / (1 + V["x0"]) * (V["cp_dry"] + V["x_eq"] * V["cp_w"])
    fo = k_max / c_min * V["dt"] / dx ** 2
    tau_el = C_TOP / (4 * V["el_eps"] * SIG * A_TOP * (800 + K0) ** 3 + V["h_fan"] * A_TOP)
    if fo > 0.5 or V["dt"] > tau_el / 2:
        fails.append(f"STABILITY Fourier {fo:.2f} (<= 0.5), dt {V['dt']} s vs element tau {tau_el:.0f} s")
        return fails                      # an unstable step is refused before anything runs on it
    # 1 energy: every shift's ledger closes
    for pol, rs in (runs or {}).items():
        worst = max(abs(r["closure"]) for r in rs)
        if worst > 1e-6:
            fails.append(f"ENERGY {pol}: the ledger misses {worst:.2%} of the heat")
    # 2 the oven: heat-up as oven_model.py says (~6 min), elements and air within their limits
    h = heatup()
    if not (h["t180"] and 240 <= h["t180"] <= 480):
        fails.append(f"HEATUP {h['t180']} s to 180 C: oven_model.py says about 6 min")
    if h["peak_el"] > 800:
        fails.append(f"ELEMENT {h['peak_el']:.0f} C: above an Incoloy sheath's 800 C")
    if h["tripped"] or h["peak_air"] >= V["cutout"] or h["peak_air"] > V["setpoint"] + 5:
        fails.append(f"OVERSHOOT {h['peak_air']:.1f} C on heat-up (limit setpoint + 5 K)")
    for pol, rs in (runs or {}).items():
        pk = max(r["peak_air"] for r in rs)
        if pk >= V["cutout"] - 25 or any(r["tripped"] for r in rs):
            fails.append(f"CUTOUT {pol}: the air reached {pk:.0f} C, within 25 K of the cutout")
    # 3 the hold power lies within the losses' bounds: walls at most at the air's temperature
    amb, sp = 21.0, V["setpoint"]
    ub = (UA_WALL + G_DOOR + vent_g(sp, amb)) * (sp - amb)
    if not (0.85 * ub <= h["hold_w"] <= 1.01 * ub):
        fails.append(f"HOLD {h['hold_w']:.0f} W outside the loss bounds {0.85 * ub:.0f}-{ub:.0f} W")
    # 4 convergence: the model's layers and step against twice the layers at a fifth of the step
    a, b = nominal(), nominal(n=2 * V["n_layers"], dt=V["dt"] / 5)
    if abs(a["t_b"] - b["t_b"]) / b["t_b"] > 0.02 or abs(a["t_done"] - b["t_done"]) / b["t_done"] > 0.02:
        fails.append(f"CONVERGENCE colour at {a['t_b']} vs {b['t_b']} s, done at {a['t_done']} vs {b['t_done']} s")
    # 6 calibration and physics: the nominal cookie's colour at ~600 s, done before it, its
    # centre held near 100 C while the water boils off
    if not (a["t_b"] and 570 <= a["t_b"] <= 630) or not (a["t_done"] and a["t_done"] <= a["t_b"]):
        fails.append(f"CALIBRATION colour 0.5 at {a['t_b']} s, done at {a['t_done']} s (want ~600, done first)")
    if a["plateau"] and not (a["plateau"][1] <= 112):
        fails.append(f"PLATEAU the centre reached {a['plateau'][1]:.0f} C while still wet (water boils at 100)")
    # 7 directions: thicker or colder dough -> later; a hotter oven -> sooner. Weaker elements
    # do not slow a bake once the oven has settled (the controller raises the duty): they
    # slow the heat-up, and the recovery after every door opening
    ov85, t = Oven(amb=21.0, power=0.85), 0.0
    while ov85.t_tc < V["setpoint"] - 0.5 and t < 3600:
        step(ov85, None, 1.0, V["setpoint"])
        t += 1.0
    if h["t180"] and t <= h["t180"]:
        fails.append(f"DIRECTION elements at 85 %: heat-up {t:.0f} s, not slower than {h['t180']:.0f} s")
    for what, kw, later in (("9 mm dough", {"d": Dough(thick=0.009)}, True), ("fridge dough", {"d": Dough(t0=6.0)}, True),
                            ("190 C", {"setpoint": 190.0}, False)):
        r = nominal(**kw)
        if r["t_b"] is None or (r["t_b"] > a["t_b"]) != later:
            fails.append(f"DIRECTION {what}: colour at {r['t_b']} s against {a['t_b']} s nominal")
    # 8 the policies, on the same shifts: each step at least as good as the one before, the
    # best at 97 %
    if runs and set(POLICIES) <= set(runs):
        ok = {p: sum(c["verdict"] == "ok" for r in rs for c in r["cookies"]) / sum(len(r["cookies"]) for r in rs)
              for p, rs in runs.items()}
        if not (ok["ir"] >= ok["camera"] >= ok["soft"] >= ok["timer"]) or ok["ir"] < 0.97:
            fails.append(f"POLICIES ok rates {ok}: want each policy >= the one before, the best >= 97 %")
    if runs:
        # 9 doors cost heat: the open mouth is on the ledger of every shift
        if any(r["ledger_kwh"]["mouth"] <= 0 for rs in runs.values() for r in rs):
            fails.append("DOORS an open door cost no heat")
    if verbose:
        print("\n".join(fails) if fails else "BAKE OK (energy, oven, convergence, stability, calibration, directions, policies)")
    return fails


def mutations(runs_small: dict) -> list[tuple[str, bool]]:
    """Each check must catch the fault it is there for: break the model, rerun, expect a fail."""
    import copy
    out = []

    def caught(name, fn):
        saved = copy.deepcopy(V)
        try:
            out.append((name, bool(fn())))
        finally:
            V.clear()
            V.update(saved)

    def no_steam():
        rs = {"timer": [run("timer", 0, n_lots=1)]}
        for r in rs["timer"]:
            r["closure"] = (r["ledger_kwh"]["steam"] * 3.6e6) / (r["heater_kwh"] * 3.6e6) + r["closure"]
        return [f for f in checks(rs, verbose=False) if f.startswith("ENERGY")]

    def big_step():
        V["dt"] = 8.0
        return [f for f in checks(None, verbose=False) if f.startswith(("STABILITY", "CONVERGENCE"))]

    def no_browning_heat():
        V["ea_brown"] = -V["ea_brown"]
        return [f for f in checks(None, verbose=False) if f.startswith(("DIRECTION", "CALIBRATION"))]

    def no_door_loss():
        rs = copy.deepcopy(runs_small)
        for r in rs["timer"]:
            r["ledger_kwh"]["mouth"] = 0.0
        return [f for f in checks(rs, verbose=False) if f.startswith("DOORS")]

    caught("the steam left off the energy ledger", no_steam)
    caught("an 8 s step", big_step)
    caught("browning that slows with heat", no_browning_heat)
    caught("doors that lose no heat", no_door_loss)
    return out


# ------------------------------------------------------------------ what it means for the cell
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def throughput(bake_s: float) -> dict:
    """The 12-cookie order through the PLC's own schedule (control.py) with the booklet's 2 s
    demo bake and with the real bake; the oven's own limit; how many ovens the rest of the
    cell could feed."""
    import control as C
    rows = []
    try:
        for label, b in (("demo bake (lamp, 2 s)", C.BAKE_DEMO), ("real bake", bake_s)):
            C.BAKE["s"] = b
            _, ev, T, _ = C.simulate(C.PLC_POLICY)
            baked = sum(1 for _, w, j in ev if w == "end" and j[0] == "bake")
            rows.append({"case": label, "bake_s": round(b, 1), "order_s": T, "baked": baked,
                         "cookies_h": round(baked * 3600 / T, 1)})
    finally:
        C.BAKE["s"] = C.BAKE_DEMO
    before, after = cycle(8.9)
    handling = sum(x[0] for x in before + after)
    per_cookie_rest = rows[0]["order_s"] / rows[0]["baked"]     # what the rest of the cell needs per cookie
    oven_cycle = bake_s + handling
    return {"rows": rows, "oven_handling_s": round(handling, 1), "oven_cycle_s": round(oven_cycle, 1),
            "oven_limit_h": round(3600 / oven_cycle, 1), "rest_s_per_cookie": round(per_cookie_rest, 1),
            "ovens_to_match": math.ceil(oven_cycle / per_cookie_rest)}


def policy_table(runs: dict) -> list[dict]:
    out = []
    for p, rs in runs.items():
        cs = [c for r in rs for c in r["cookies"]]
        bt = [c["bake_s"] for c in cs]
        mean = sum(bt) / len(bt)
        row = {"policy": p, "name": POLICY_NAME[p], "cookies": len(cs)}
        for v in ("ok", "underbaked", "burnt"):
            row[v] = sum(c["verdict"] == v for c in cs)
        row["ok_pct"] = round(100 * row["ok"] / len(cs), 1)
        for grp, sel in (("fridge", True), ("bench", False)):
            g = [c for c in cs if c["fridge"] == sel]
            row[f"ok_pct_{grp}"] = round(100 * sum(c["verdict"] == "ok" for c in g) / max(1, len(g)), 1)
        row.update(bake_mean=round(mean, 1), bake_sd=round((sum((b - mean) ** 2 for b in bt) / len(bt)) ** 0.5, 1),
                   bake_min=min(bt), bake_max=max(bt),
                   wh_per_cookie=round(1000 * sum(r["heater_kwh"] for r in rs) / len(cs), 1),
                   peak_air=round(max(r["peak_air"] for r in rs), 1))
        out.append(row)
    return out


def cell_month_kwh() -> float | None:
    try:
        g = json.load(open(os.path.join(ROOT, "web", "public", "grid", "grid.json")))
        return g["scenarios"]["pv+battery"]["load_kwh"]
    except (OSError, KeyError, ValueError):
        return None


SHIFTS = 20         # shifts per policy in the comparison (each 4 lots of 12 cookies)


def main() -> int:
    import time
    t0 = time.time()
    runs = {p: [run(p, s, trace=(s == 0)) for s in range(SHIFTS)] for p in POLICIES}
    fails = checks(runs)
    muts = mutations({"timer": runs["timer"][:1]})
    for name, ok in muts:
        if not ok:
            fails.append(f"MUTATION not caught: {name}")
    h = heatup(1.0)
    nom = nominal(trace=True)
    pol = policy_table(runs)
    best = next(r for r in pol if r["policy"] == "ir")
    tp = throughput(best["bake_mean"])
    shift_h = runs["ir"][0]["t_s"] / 3600
    kwh_shift = sum(r["heater_kwh"] for r in runs["ir"]) / SHIFTS
    per_h = kwh_shift / shift_h
    month = cell_month_kwh()
    oven_month = per_h * 16 * 30 + h["preheat_kwh"] * 30           # two 8 h shifts a day, one preheat
    rest = tp["rows"][0]
    real = tp["rows"][1]
    findings = [
        f"With a real bake the oven is the cell's bottleneck by far: the 12-cookie order takes {real['order_s'] / 60:.0f} min "
        f"instead of {rest['order_s'] / 60:.1f} min, {real['cookies_h']} cookies an hour instead of {rest['cookies_h']}. "
        f"The rest of the cell could feed {tp['ovens_to_match']} ovens like this one.",
        f"A fixed timer leaves {100 - next(r for r in pol if r['policy'] == 'timer')['ok_pct']:.1f} % of cookies wrong, most of "
        f"them underbaked dough from the fridge ({next(r for r in pol if r['policy'] == 'timer')['ok_pct_fridge']} % right). "
        f"Ending the bake on the PLC's model of the cookie gets {next(r for r in pol if r['policy'] == 'soft')['ok_pct']} %; "
        f"correcting its colour target from the camera after every cookie gets "
        f"{next(r for r in pol if r['policy'] == 'camera')['ok_pct']} %: the camera sees a lot's colour after its first "
        f"cookie, but not the water left in a thick cookie's centre. Measuring each piece of dough before it goes in - its temperature (an infrared "
        f"thermometer) and its height (a laser distance sensor) over the presented tray - gets "
        f"{best['ok_pct']} %: the hardware this upgrade asks for.",
        f"Each cookie costs about {best['wh_per_cookie']:.0f} Wh of heat; the oven holds 180 C on {h['hold_w']:.0f} W and "
        f"preheats in {h['t180'] / 60:.1f} min ({h['preheat_kwh'] * 1000:.0f} Wh). Two shifts a day come to about "
        f"{oven_month:.0f} kWh a month" + (f", {oven_month / month:.1f} times the rest of the cell's {month:.0f} kWh." if month else "."),
        f"The cell's microgrid was sized for a 5 W lamp: its 600 W inverter cannot run the "
        f"{(V['p_top'] + V['p_bot']):.0f} W of elements. The oven needs its own 230 V supply, or the microgrid resizing.",
        f"After every door opening the air overshoots to at most {max(r['peak_air'] for r in pol):.0f} C, "
        f"{V['cutout'] - max(r['peak_air'] for r in pol):.0f} K below the over-temperature cutout.",
    ]
    out = {
        "upgrade": 19, "title": "The bake as a process",
        "params": [{"key": k, "value": (list(v[0]) if isinstance(v[0], tuple) else v[0]), "unit": v[1], "source": v[2]}
                   for k, v in P.items()],
        "derived": {"c_top": round(C_TOP, 1), "c_bot": round(C_BOT, 1), "c_wall": round(C_WALL), "c_tray": round(C_TRAY, 1),
                    "ua_wall": round(UA_WALL, 3), "g_door": round(G_DOOR, 3), "g_mouth_180": round(mouth_g(180, 21), 2),
                    "g_vent_180": round(vent_g(180, 21), 3), "f_top": round(F_TOP, 3), "a_cookie_cm2": round(A_COOKIE * 1e4, 2),
                    "cookie_g": round(V["rho_dough"] * A_COOKIE * V["cookie_t"] * 1000, 1)},
        "heatup": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in h.items()},
        "nominal": {"t_done": nom["t_done"], "t_b": nom["t_b"], "plateau": [round(x, 1) for x in nom["plateau"]],
                    "trace": nom["trace"]},
        "shift": {"policy": "ir", "seed": 0, "power": runs["ir"][0]["power"],
                  "power_learnt": runs["ir"][0]["power_learnt"],
                  "trace": [dict(zip(("t", "air", "tc", "duty", "surface", "core", "water", "b", "door"), x))
                            for x in runs["ir"][0]["trace"]]},
        "cookies": {p: runs[p][0]["cookies"] for p in POLICIES},
        "policies": pol, "shifts": SHIFTS, "lot_size": LOT_SIZE,
        "throughput": tp,
        "energy": {"wh_per_cookie": best["wh_per_cookie"], "hold_w": round(h["hold_w"]), "preheat_kwh": round(h["preheat_kwh"], 3),
                   "kwh_per_shift_h": round(per_h, 3), "oven_month_kwh": round(oven_month), "cell_month_kwh": month,
                   "ledger_kwh": runs["ir"][0]["ledger_kwh"]},
        "checks": {"fails": fails, "mutations": [{"name": n, "caught": ok} for n, ok in muts]},
        "findings": findings,
        "assumed": "every material value, coefficient and disturbance (tagged 'assumed'); kd_ref and kb_ref "
                   "calibrated so a nominal 8 mm cookie browns to the target at about 600 s at 180 C",
    }
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "process.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    write_doc(out)
    print(f"wrote web/public/bake/process.json and docs/process/README.md in {time.time() - t0:.0f} s")
    for r in pol:
        print(f"  {r['name']:22s} ok {r['ok_pct']:5.1f} %  (fridge {r['ok_pct_fridge']} %)  bake {r['bake_mean']:.0f} +- {r['bake_sd']:.0f} s")
    for f in findings:
        print("  -", f)
    return 1 if fails else 0


# ------------------------------------------------------------------ the chapter
def _line(pattern: str, path: str = "stf-cad/hbw/bake.py") -> str:
    import re
    for i, text in enumerate(open(os.path.join(ROOT, path), encoding="utf-8"), 1):
        if re.search(pattern, text):
            return f"`{path}:{i}`"
    raise SystemExit(f"bake.py: '{pattern}' is no longer in {path}")


def write_doc(o: dict) -> None:
    """docs/process/README.md: the model, its equations with their lines, the results."""
    h, n, tp, e = o["heatup"], o["nominal"], o["throughput"], o["energy"]
    d = o["derived"]
    pol = {r["policy"]: r for r in o["policies"]}
    prow = "\n".join(
        f"| {r['name']} | {r['ok_pct']} % | {r['underbaked']} | {r['burnt']} | {r['ok_pct_fridge']} % | "
        f"{r['bake_mean']:.0f} ± {r['bake_sd']:.0f} s ({r['bake_min']:.0f}-{r['bake_max']:.0f}) | {r['wh_per_cookie']:.0f} Wh |"
        for r in o["policies"])
    trow = "\n".join(f"| {r['case']} | {r['bake_s']} s | {r['order_s'] / 60:.1f} min | {r['cookies_h']} |" for r in tp["rows"])
    def val(v):
        return f"{v:.4g}" if isinstance(v, float) else v

    params = "\n".join(f"| `{p['key']}` | {val(p['value'])} | {p['unit']} | {p['source']} |" for p in o["params"])
    checks_txt = "all pass" if not o["checks"]["fails"] else "; ".join(o["checks"]["fails"])
    muts = "; ".join(m["name"] + (" (caught)" if m["caught"] else " (NOT caught)") for m in o["checks"]["mutations"])
    md = f"""# The bake as a process (Upgrade 19)

Until Upgrade 19 the oven waited a fixed time and every cookie came out right. A real bake is
heat and water: the elements heat the chamber, every door opening cools it, the cookie's surface
dries and browns while its centre is still heating, and how a cookie turns out depends on the
oven's state when it went in, on the dough, and on when the bake is ended. This chapter is the
model of that process, built from the oven's own parts and the order's real door openings, and
what it says about quality, capacity and energy. Everything is simulated; every material value
is assumed and listed below, and two constants are calibrated so a nominal cookie bakes as
cookies of its size do. Replace them with one measured bake before trusting the numbers.

## What it found

{chr(10).join("- " + f for f in o["findings"])}

## The oven

Three thermal nodes - the grill element ($T_t$), the bottom elements ($T_b$), the liner and
walls ($T_w$) - the tray ($T_p$), and the chamber air ($T_a$), which holds 9 J/K and settles in
under a second, so it is solved as a balance at every step. From `oven_model.py`: a
{o['params'][0]['value']:.1f} l chamber, an 800 W grill hairpin and two 250 W bottom hairpins,
a 1.5 mm stainless liner over 10 mm of ceramic fibre, a K-type thermocouple, a convection fan,
the door and the steam vent.

$$C_t \\frac{{dT_t}}{{dt}} = u\\,P_t - \\varepsilon\\sigma A_t\\left(T_t^4 - T_w^4\\right) - h A_t (T_t - T_a) - \\dot Q_{{t\\to c}}$$

$$C_w \\frac{{dT_w}}{{dt}} = \\dot Q_{{rad}} - h A_w (T_w - T_a) - UA_{{ins}} (T_w - T_\\infty)$$

$$\\sum_k h A_k (T_k - T_a) = \\left(G_{{door}} + G_{{vent}}\\right)(T_a - T_\\infty)$$

| Quantity | Value |
|---|---|
| Element capacities $C_t$, $C_b$ | {d['c_top']} J/K, {d['c_bot']} J/K |
| Liner and walls $C_w$ | {d['c_wall']} J/K |
| Insulation $UA_{{ins}}$ | {d['ua_wall']} W/K |
| Shut door, steam vent at 180 C | {d['g_door']} W/K, {d['g_vent_180']} W/K |
| Open mouth at 180 C (buoyant exchange) | {d['g_mouth_180']} W/K |
| The cookie's view of the grill element $F$ | {d['f_top']} |

With the door open the convection fan stops and the mouth exchanges air both ways, driven by the
temperature difference (doorway flow):

$$\\dot V = \\frac{{C_d}}{{3}}\\, W \\sqrt{{g H^3 \\frac{{T_a - T_\\infty}}{{\\bar T}}}}$$

A PI controller on the thermocouple (first-order lag, $\\tau = {o['params'][[p['key'] for p in o['params']].index('tc_tau')]['value']:.0f}$ s)
drives the solid-state relay Q9. While the door is open its integral holds and the heat is
capped at {o['params'][[p['key'] for p in o['params']].index('door_duty')]['value']:.0%}; even so the elements, hot from the open-door
minutes, push the air to at most {max(r['peak_air'] for r in o['policies']):.0f} C once the door shuts, against the
{o['params'][[p['key'] for p in o['params']].index('cutout')]['value']:.0f} C cutout. *Source: {_line(r"def step")}.*

| Heat-up from 21 C | |
|---|---|
| To 180 C | {h['t180']:.0f} s (oven_model.py: about 6 min) |
| Elements' peak | {h['peak_el']:.0f} C (sheath limit 800 C) |
| Air overshoot | {h['peak_air']:.1f} C |
| Holding 180 C | {h['hold_w']:.0f} W |
| Preheat energy | {h['preheat_kwh'] * 1000:.0f} Wh |

## The cookie

A {d['cookie_g']} g disc of dough, 45 mm across and 8 mm thick, in {o['params'][[p['key'] for p in o['params']].index('n_layers')]['value']}
layers through its thickness. The top takes radiation from the grill element and the liner and
convection from the air; the bottom sits on the tray:

$$\\rho c_p \\frac{{\\partial T}}{{\\partial t}} = \\frac{{\\partial}}{{\\partial z}}\\left(k(X)\\,\\frac{{\\partial T}}{{\\partial z}}\\right) - \\rho_d \\lambda \\frac{{\\partial X}}{{\\partial t}}$$

Each layer gives up its water at a rate that follows water's vapour pressure (Clausius-Clapeyron,
the same 40 kJ/mol as boiling), faster near the surface where the vapour can leave:

$$\\frac{{dX_i}}{{dt}} = -k_d\\, \\frac{{p_{{sat}}(T_i)}}{{p_{{sat}}(100\\,^\\circ\\mathrm{{C}})}}\\, e^{{-z_i/\\delta}}\\,(X_i - X_e)$$

Each kilogram takes its latent heat with it, so the centre holds near 100 C while the dough is
wet ({n['plateau'][0]:.0f}-{n['plateau'][1]:.0f} C in the nominal bake) - the plateau a probe in
real dough shows. The evaporation is solved implicitly in each layer: it cools the layer, which
slows it. Once the surface is below 10 % water it browns (Maillard), first order with an
Arrhenius rate:

$$\\frac{{dB}}{{dt}} = k_B\\, e^{{-\\frac{{E_a}}{{R}}\\left(\\frac{{1}}{{T_s}} - \\frac{{1}}{{T_{{ref}}}}\\right)}} (1 - B)$$

*Source: {_line(r"class Cookie")}, {_line(r"def resid")}.*

**Quality.** A cookie is *done* when its centre has reached {o['params'][[p['key'] for p in o['params']].index('core_done')]['value']:.0f} C
and it holds at most 6 % water (wet basis); its colour is right when the browning index lies
between 0.35 and 0.65. Not done, or too pale: *underbaked*; too dark: *burnt* - the classes the
camera (Upgrade 15) reports. The nominal cookie is done at {n['t_done']:.0f} s and reaches the
colour target 0.5 at {n['t_b']:.0f} s.

## Ending the bake: three policies on the same shifts

{o['shifts']} shifts per policy, each four lots of {o['lot_size']} cookies, back to back, with the
order's real door openings between bakes and the same disturbances for every policy: the hall's
daily temperature, elements aged to 88-100 % of their power, the robot's waits, and dough lots
that differ in thickness and water and come from the bench or, three in ten, from the fridge.

- **Fixed timer**: 600 s, the nominal cookie's bake - what the lamp dwell did.
- **Soft sensor**: the PLC runs its own model of the oven and an 8-layer model of a nominal
  cookie, fed the duty it commanded and corrected by the thermocouple. The correction also
  learns the elements' ageing. The bake ends when the modelled cookie is done and brown enough.
- **Soft sensor + camera**: after every cookie the camera's colour reading (σ = 0.03) moves the
  next cookie's colour target against the error. This is run-to-run control: it learns a lot that
  bakes differently within a few cookies.
- **+ dough sensors**: the same, and two sensors over the presented tray read each piece of
  dough before it goes in: an infrared thermometer (σ = 0.5 C) and a laser distance sensor for
  its height (σ = 0.05 mm). The PLC's model cookie then starts at the dough's real temperature
  and thickness. This is new hardware: two sensors, two analogue inputs.

The colour correction starts again at every new lot: what the camera learnt was about the last
one.

| Policy | Right | Underbaked | Burnt | Right, fridge dough | Bake time | Heat per cookie |
|---|---|---|---|---|---|---|
{prow}

The soft sensor follows the oven but not the dough: it cannot see that a lot came from the
fridge, or that it was rolled thicker. The camera sees the colour, after the first cookie of the
lot, but not the water left in a thick cookie's centre. The dough sensors see both before the
first cookie goes in. This is the physical-AI loop in its
plainest form: the camera sees, the model decides, the oven does it, and the next cookie is
better for it.

## What it means for capacity

| Case | Bake | 12-cookie order | Cookies an hour |
|---|---|---|---|
{trow}

One cookie occupies the oven for {tp['oven_cycle_s']:.0f} s: the bake plus {tp['oven_handling_s']:.0f} s
of door, slider and handover. That caps the oven at {tp['oven_limit_h']} cookies an hour, whatever the
rest of the cell does. The rest of the cell needs {tp['rest_s_per_cookie']:.0f} s per cookie, so it
could feed {tp['ovens_to_match']} ovens like this one. A real line bakes many cookies at once, in a tunnel
oven - the STF-2 redesign.

## What it means for energy

About {e['wh_per_cookie']:.0f} Wh of heat per cookie and {e['hold_w']} W to hold 180 C; two shifts a
day come to about {e['oven_month_kwh']} kWh a month. The rest of the cell uses
{e['cell_month_kwh']} kWh a month. The cell's microgrid was sized for the 5 W lamp; its 600 W
inverter cannot run 1 300 W of elements.

## Checks

{checks_txt}. Each check catches the fault it is there for: {muts}.

- **Energy:** every shift's ledger closes. The heat from the elements equals the change in
  stored heat, plus the losses through the walls, the shut door, the vent and the open mouth,
  plus the steam and the heat the cookies took.
- **The oven:** the heat-up matches oven_model.py's note; the elements stay below their
  sheath's 800 C; the air stays within 5 K of the setpoint on heat-up and 25 K short of the
  cutout after door openings. The holding power lies within the bounds of its losses.
- **Numerics:** 16 layers at 0.5 s against 32 layers at 0.1 s agree within 2 %; the explicit
  steps are stable (Fourier number ≤ 0.5), and an unstable step is refused before it runs.
- **Physics:** thicker or colder dough bakes longer, a hotter oven shorter, and weaker elements
  heat up more slowly. The wet centre stays near 100 C.
- **Policies:** on the same shifts each policy is at least as good as the one before it, and
  the best gets at least 97 % of cookies right.

## Parameters

| Name | Value | Unit | Source |
|---|---|---|---|
{params}

*Generated by `stf-cad/hbw/bake.py` (`make bake`); edit the model, not this file.*
"""
    path = os.path.join(ROOT, "docs", "process", "README.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    md = md.replace("{,}", ",")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)


if __name__ == "__main__":
    import sys
    sys.exit(main())
