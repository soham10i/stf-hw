"""
STF-2 band oven - the bake, the cooling and the heater power, from physics.

Why (2026-10-02): the v4 tunnel put the puck chain through a 180 C tunnel for 24 s. Checked against
heat transfer it baked nothing (top 68 C, core 20 C) and ran a POM chain, a UHMW-PE track and an NFC tag
far above their limits. STF-2 now bakes for real: plain dough is deposited onto its own stainless mesh
band, baked in three heated zones, cooled on the same band, and only a cold, finished base cookie goes
onto a puck. The flavour is a topping deposited on the loop.

Everything here is a pure function of the parameter table (line_model.L) and the catalogue (hardware.py);
line_model sizes the band from bake_time() / cool_time(), plc_io / elec_draw take the elements and the
phase plan from elements() / phase_plan(), motion.py colours the cookies from profile().

Models (all [typ] textbook physics, the food data [assumed] - MEASURE on the first bake):
  product   1-D through the cookie thickness, explicit finite volumes. Heat in from the top (forced
            convection + radiation from the zone's top elements), the bottom (convection through the open
            mesh + contact with the band) and the rim (convection, folded into an effective top/bottom
            area). Water: a node holds at 100 C while it still holds water; the surplus heat evaporates
            it (evaporation-front model). Colour: a Maillard browning index, Arrhenius in the surface
            temperature, 1.0 = the target golden colour.
  band      lumped stainless mesh, heated by the zone air on both faces; it returns OUTSIDE the chamber
            (under the oven floor) and enters cold.
  losses    walls/roof/floor: series resistance (inner skin, mineral wool, outer skin film); band mouths:
            black-body radiation through the opening + buoyant doorway exchange flow; vapour exhaust:
            the air needed to carry the evaporated water out at X_EXHAUST.
  warm-up   lumped chamber (inner skins, band inside, elements, inner half of the insulation).
  supply    every element 230 V between a phase and N of a 400 V 3N~ supply; elements placed on the
            phases largest-first onto the least loaded phase.
"""
import math
from functools import lru_cache

import hardware as H

SIGMA = 5.670e-8
G = 9.81
CP_W, LV = 4180.0, 2.257e6          # water: J/kg K, latent heat J/kg
CP_AIR, RHO_AIR = 1010.0, 1.0       # hot air (~ 80 C mean between ambient and the zones)


# ------------------------------------------------------------- product model
def _props(L):
    d, h = L["COOKIE"]
    D = L["DOUGH"]
    return dict(d=d / 1000, h=h / 1000, m=L["DOUGH_M"], w0=D["w0"], cp_d=D["cp_dry"], k0=D["k_wet"],
                k1=D["k_dry"])


def simulate(L, segments, n=10, dt=0.25, record=1.0):
    """Run one cookie through `segments` = [(name, seconds, env)], env = dict(T_air, h_top, h_bot, T_rad,
    eps, T_band or None). Returns (trace, summary). trace rows: t, segment, T_top, T_core, T_bot, moisture
    (wet basis), colour, q_in (W into the cookie)."""
    P = _props(L)
    A_top = math.pi * (P["d"] / 2) ** 2
    A_rim = math.pi * P["d"] * P["h"]
    dx = P["h"] / n
    m_dry = P["m"] * (1 - P["w0"]) / n                    # per node (the cookie's dry mass split evenly)
    w = [P["m"] * P["w0"] / n] * n                        # water per node (kg)
    w_cap = w[0]
    T = [L["T_AMB"]] * n
    D = L["DOUGH"]
    col, core_hold = 0.0, 0.0
    t, trace, nxt = 0.0, [], 0.0
    for name, dur, env in segments:
        t_end = t + dur
        rim_top = A_rim / 2                               # the rim: half to each face's film
        while t < t_end - 1e-9:
            h = min(dt, t_end - t)
            k = [P["k1"] + (P["k0"] - P["k1"]) * (w[i] / w_cap) for i in range(n)]
            q = [0.0] * n
            Ttop, Tbot = T[0], T[-1]
            rad = env["eps"] * SIGMA * ((env["T_rad"] + 273.15) ** 4 - (Ttop + 273.15) ** 4)
            q_top = (env["h_top"] * (env["T_air"] - Ttop) + rad) * (A_top + rim_top)
            tb = env.get("T_band")
            q_bot = env["h_bot"] * (env["T_air"] - Tbot) * (A_top + A_rim / 2)
            if tb is not None:
                q_bot += D["h_contact"] * (tb - Tbot) * A_top * D["contact_frac"]
            q[0] += q_top
            q[-1] += q_bot
            for i in range(n - 1):
                kk = 2 * k[i] * k[i + 1] / (k[i] + k[i + 1])
                f = kk * A_top * (T[i] - T[i + 1]) / dx
                q[i] -= f
                q[i + 1] += f
            for i in range(n):
                C = m_dry * P["cp_d"] + w[i] * CP_W
                Tn = T[i] + q[i] * h / C
                if w[i] > 0 and Tn > 100.0:               # evaporation front: hold 100 C, boil the surplus
                    e = (Tn - 100.0) * C
                    ev = min(w[i], e / LV)
                    w[i] -= ev
                    Tn = 100.0 + (e - ev * LV) / (m_dry * P["cp_d"] + w[i] * CP_W)
                T[i] = Tn
            # Maillard browning of the top surface (Arrhenius, normalised at T_REF)
            Ts = T[0] + 273.15
            col += h / D["brown_t"] * math.exp(-D["brown_Ea"] / 8.314 * (1 / Ts - 1 / (D["brown_Tref"] + 273.15)))
            core = T[n // 2]
            core_hold = core_hold + h if core >= L["BAKE_Q"]["core_min"] else core_hold
            t += h
            if t >= nxt - 1e-9:
                mo = sum(w) / (sum(w) + m_dry * n)
                trace.append((round(t, 3), name, T[0], core, T[-1], mo, col, q_top + q_bot))
                nxt += record
    mo = sum(w) / (sum(w) + m_dry * n)
    return trace, dict(T_top=T[0], T_core=T[n // 2], T_bot=T[-1], T_max=max(T), T_mean=sum(T) / n,
                       moisture=mo, colour=col, core_hold=core_hold, mass=sum(w) + m_dry * n)


def zone_env(L, k, T_set=None):
    Z = L["OVEN_ZONES"][k]
    T = Z["T"] if T_set is None else T_set
    return dict(T_air=T, h_top=L["OVEN_H"]["top"], h_bot=L["OVEN_H"]["bot"], T_rad=T + Z["dT_rad"],
                eps=L["DOUGH"]["eps"], T_band=None)


def band_temps(L, t_zone):
    """Mesh band temperature entering / leaving each zone (lumped, both faces in the zone air). It enters
    the first zone at ambient (the return run is outside the chamber)."""
    m_a = L["BAND"]["m_area"]
    c = H.BAND_MESH["cp"]
    Tb, out = L["T_AMB"], []
    for k, Z in enumerate(L["OVEN_ZONES"]):
        tau = m_a * c / (2 * L["OVEN_H"]["bot"])
        T1 = Z["T"] - (Z["T"] - Tb) * math.exp(-t_zone / tau)
        out.append((Tb, T1))
        Tb = T1
    return out


def bake_segments(L, t_bake):
    tz = t_bake / len(L["OVEN_ZONES"])
    bt = band_temps(L, tz)
    segs = []
    for k in range(len(L["OVEN_ZONES"])):
        e = zone_env(L, k)
        e["T_band"] = 0.5 * (bt[k][0] + bt[k][1])
        segs.append((f"Z{k + 1}", tz, e))
    return segs


def cool_env(L, where):
    C = L["COOLING"][where]
    return dict(T_air=L["T_AMB"] if C.get("T_air") is None else C["T_air"], h_top=C["h_top"], h_bot=C["h_bot"],
                T_rad=L["T_AMB"], eps=L["DOUGH"]["eps"], T_band=None)


def baked_ok(L, s):
    Q = L["BAKE_Q"]
    return (s["core_hold"] >= Q["core_hold"] and s["moisture"] <= Q["w_end"]
            and Q["colour"][0] <= s["colour"] <= Q["colour"][1] and s["T_max"] <= Q["T_burn"])


def _key(L):
    keys = ("COOKIE", "DOUGH", "DOUGH_M", "BAKE_Q", "OVEN_ZONES", "OVEN_H", "BAND", "T_AMB", "COOLING", "T_TRANSFER")
    return repr([L[k] for k in keys])


_cache = {}


def bake_time(L):
    """Shortest residence (s, 5 s steps) that bakes the cookie at the zone set points, or None."""
    k = ("bake", _key(L))
    if k in _cache:
        return _cache[k]
    best = None
    for tb in range(60, 1801, 5):
        _, s = simulate(L, bake_segments(L, tb), record=1e9)
        if baked_ok(L, s):
            best = float(tb)
            break
        if s["colour"] > L["BAKE_Q"]["colour"][1] or s["T_max"] > L["BAKE_Q"]["T_burn"]:
            break                                     # burns before it is baked: these set points cannot work
    _cache[k] = best
    return best


def cool_time(L, t_bake, t_gap=0.0, t_nose=0.0):
    """Band cooling time (s, 5 s steps) in the impingement hood until the cookie is <= T_TRANSFER everywhere
    at the pick window. t_gap: still air from the last zone to the hood (outlet wall + gap), t_nose: still
    air from the hood to the pick window."""
    k = ("cool", _key(L), t_bake, round(t_gap, 3), round(t_nose, 3))
    if k in _cache:
        return _cache[k]
    best = None
    for tc in range(20, 1201, 5):
        _, s = simulate(L, band_segments(L, t_bake, tc, t_gap, t_nose), record=1e9)
        if s["T_max"] <= L["T_TRANSFER"]:
            best = float(tc)
            break
    _cache[k] = best
    return best


def band_segments(L, t_bake, t_cool, t_gap=0.0, t_nose=0.0):
    """Zones, the still-air gap to the hood, the hood, the still-air run to the pick window."""
    segs = bake_segments(L, t_bake)
    if t_gap > 0:
        segs.append(("exit", t_gap, cool_env(L, "loop")))
    segs.append(("band cooling", t_cool, cool_env(L, "band")))
    if t_nose > 0:
        segs.append(("to pick", t_nose, cool_env(L, "loop")))
    return segs


def profile(L, t_bake, t_cool, t_loop=(), record=1.0, t_gap=0.0, t_nose=0.0):
    """Full product history: bake zones, band (gap, hood, run to the pick), then the loop segments
    [(name, s, where)]."""
    segs = band_segments(L, t_bake, t_cool, t_gap, t_nose)
    segs += [(n, s, cool_env(L, w)) for n, s, w in t_loop]
    return simulate(L, segs, record=record)


def colour_hex(L, colour, moisture):
    """Product colour for the twin: dough colour -> golden at colour index 1.0 -> darker above."""
    a = L["DOUGH"]["rgb_raw"]
    b = L["DOUGH"]["rgb_baked"]
    c = L["DOUGH"]["rgb_dark"]
    if colour <= 1.0:
        f = max(0.0, colour)
        rgb = [a[i] + (b[i] - a[i]) * f for i in range(3)]
    else:
        f = min(1.0, colour - 1.0)
        rgb = [b[i] + (c[i] - b[i]) * f for i in range(3)]
    return "#" + "".join(f"{int(round(v)):02x}" for v in rgb)


# ------------------------------------------------------------- chamber + power
def chamber(L, band_w, zone_len):
    """Inner / outer box of one zone (m) and its areas."""
    C = L["CHAMBER"]
    wi = (band_w + 2 * C["side_gap"]) / 1000
    hi = C["h_inner"] / 1000
    li = zone_len / 1000
    t = C["insul"] / 1000
    return dict(wi=wi, hi=hi, li=li, t=t, A_wall=2 * hi * li + 2 * wi * li,      # sides + roof + floor
                A_out=2 * (hi + 2 * t) * li + 2 * (wi + 2 * t) * li)


def wall_loss(L, T_in, A_in, A_out):
    """W through an insulated wall; returns (W, outer skin temperature)."""
    C = L["CHAMBER"]
    k = H.INSULATION[C["insul_mat"]]["k"](0.5 * (T_in + L["T_AMB"]))
    t = C["insul"] / 1000
    ho = C["h_out"]
    # area-weighted: conduction on the inner area, skin film on the outer area
    R = t / (k * A_in) + 1 / (ho * A_out)
    q = (T_in - L["T_AMB"]) / R
    return q, L["T_AMB"] + q / (ho * A_out)


def mouth_loss(L, T_in, w, h):
    """W through one open band mouth (w x h m): radiation of the opening + buoyant doorway exchange."""
    Ti, Ta = T_in + 273.15, L["T_AMB"] + 273.15
    rad = L["CHAMBER"]["mouth_F"] * SIGMA * (Ti ** 4 - Ta ** 4) * w * h
    # doorway exchange flow (Brown & Solvason): V = Cd/3 * w * sqrt(g h^3 dT / T_mean)
    V = L["CHAMBER"]["mouth_Cd"] / 3 * w * math.sqrt(G * h ** 3 * (Ti - Ta) / (0.5 * (Ti + Ta)))
    conv = RHO_AIR * V * CP_AIR * (T_in - L["T_AMB"])
    return rad + conv, V


def zone_loads(L, t_bake, band_w, band_v, rate):
    """Steady load of every zone (W) by item, at the production rate (cookies/s)."""
    n = len(L["OVEN_ZONES"])
    tz = t_bake / n
    zl = band_v * tz                                        # mm
    ch = chamber(L, band_w, zl)
    # product: heat into one cookie in each zone (incl. the latent heat it took), x rate
    trace, _ = simulate(L, bake_segments(L, t_bake), record=0.25)
    e_zone = [0.0] * n
    prev = None
    for row in trace:
        t, seg = row[0], row[1]
        k = int(seg[1:]) - 1
        dt_ = t - prev if prev is not None else t
        e_zone[k] += row[7] * dt_
        prev = t
    bt = band_temps(L, tz)
    m_band = L["BAND"]["m_area"] * band_w / 1000 * band_v / 1000            # kg/s of mesh
    evap = L["DOUGH_M"] * (L["DOUGH"]["w0"] - _final_moisture(L, t_bake)) * rate   # kg/s water
    out = []
    mouth_w = band_w / 1000
    mouth_h = L["CHAMBER"]["mouth_h"] / 1000
    for k, Z in enumerate(L["OVEN_ZONES"]):
        T = Z["T"]
        walls, skin = wall_loss(L, T, ch["A_wall"], ch["A_out"])
        mouth, V = mouth_loss(L, T, mouth_w, mouth_h) if k in (0, n - 1) else (0.0, 0.0)
        band = m_band * H.BAND_MESH["cp"] * (bt[k][1] - bt[k][0])
        # exhaust: evaporated water leaves in air at X_EXHAUST kg/kg; this zone's share by its product heat
        share = e_zone[k] / sum(e_zone)
        m_air = evap * share / L["X_EXHAUST"]
        exh = m_air * CP_AIR * (T - L["T_AMB"])
        prod = e_zone[k] * rate
        out.append(dict(zone=f"Z{k + 1}", T=T, product=prod, band=band, walls=walls, mouth=mouth, exhaust=exh,
                        total=prod + band + walls + mouth + exh, skin=skin, len_mm=zl, m_air=m_air,
                        e_cookie=e_zone[k]))
    return out


def _final_moisture(L, t_bake):
    """Water lost per kg of dough = w0 - final water per kg of dough."""
    _, s = simulate(L, bake_segments(L, t_bake), record=1e9)
    return 1 - (1 - L["DOUGH"]["w0"]) / (1 - s["moisture"]) if s["moisture"] < 1 else 0.0


def elements(L, loads, inner_w):
    """The catalogue elements of every zone and face: installed >= steady / HEADROOM, split TOP_SHARE,
    heated length within the chamber width, sheath load <= TUBULAR_WCM2, fewest elements, then least power.
    Returns [dict(zone, face, tag, P, n, L_heated, load_Wcm2, cat)] - one row per element."""
    out = []
    fit = [c for c in H.TUBULAR if c["L_heated"] <= inner_w - 20]
    lh = max(c["L_heated"] for c in fit)
    fit = [c for c in fit if c["L_heated"] == lh]
    for k, z in enumerate(loads):
        need = z["total"] / L["HEADROOM"]
        for face, share in (("top", L["TOP_SHARE"]), ("bot", 1 - L["TOP_SHARE"])):
            want = need * share
            best = None
            for n in (1, 2, 3, 4):
                for c in fit:
                    load = c["P"] / (math.pi * c["d"] / 10 * c["L_heated"] / 10)
                    if n * c["P"] >= want and load <= H.TUBULAR_WCM2:
                        if best is None or (n, n * c["P"]) < (best[0], best[0] * best[1]["P"]):
                            best = (n, c, load)
                if best:
                    break
            if best is None:
                c = max(fit, key=lambda c: c["P"])
                best = (3, c, c["P"] / (math.pi * c["d"] / 10 * c["L_heated"] / 10))
            n, c, load = best
            for j in range(n):
                out.append(dict(zone=z["zone"], face=face, tag=f"E{k + 1}{'T' if face == 'top' else 'B'}{j + 1}",
                                P=c["P"], want=want / n, n=n, L_heated=c["L_heated"], load_Wcm2=load, cat=c))
    return out


def phase_plan(L, elems, other=()):
    """Elements (+ other single-phase loads [(tag, W)]) onto L1/L2/L3: largest first onto the least loaded
    phase. Returns {phase: [(tag, W)]}."""
    ph = {"L1": [], "L2": [], "L3": []}
    items = sorted([(e["tag"], e["P"]) for e in elems] + list(other), key=lambda x: -x[1])
    for tag, W in items:
        p = min(ph, key=lambda q: sum(w for _, w in ph[q]))
        ph[p].append((tag, W))
    return ph


def warmup(L, loads, elems, band_w, curves=False):
    """Seconds from ambient to every zone at set point (lumped chamber, all elements on). curves=True also
    returns each zone's (t, T) samples every 30 s."""
    C = L["CHAMBER"]
    res = []
    for z in loads:
        ch = chamber(L, band_w, z["len_mm"])
        P = sum(e["P"] for e in elems if e["zone"] == z["zone"])
        m_skin = ch["A_wall"] * C["skin_t"] / 1000 * H.STEEL_RHO
        m_ins = ch["A_wall"] * C["insul"] / 1000 * H.INSULATION[C["insul_mat"]]["rho"] * 0.5
        m_band = L["BAND"]["m_area"] * band_w / 1000 * z["len_mm"] / 1000 * 2       # carry + return
        Cth = (m_skin + m_band) * 500.0 + m_ins * H.INSULATION[C["insul_mat"]]["cp"] + C["m_fixed"] * 500.0
        T, t = L["T_AMB"], 0.0
        cur = [(0.0, T)]
        while T < z["T"] - 1.0 and t < 7200:
            walls, _ = wall_loss(L, T, ch["A_wall"], ch["A_out"])
            mouth = mouth_loss(L, T, band_w / 1000, C["mouth_h"] / 1000)[0] if z["zone"] in ("Z1", f"Z{len(loads)}") else 0
            T += (P - walls - mouth) * 5.0 / Cth
            t += 5.0
            if t % 30 < 1e-9:
                cur.append((t, T))
        cur.append((t, T))
        res.append((z["zone"], t, P, cur) if curves else (z["zone"], t, P))
    return res
