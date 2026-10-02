"""
STF-2 moving twin: one timeline of every moving part, DERIVED from line_model (never animated by hand),
plus a sweep check of the whole motion.

  timeline   T = 40 s at dt = 0.1 s. The chain + pucks run continuously; the mesh band carries every row
             from the depositor (the wire cuts a row every 6 takts) through the oven (each cookie spreads
             and browns as oven.py says) to the pick window; delta C moves one cookie per takt from the
             band into a passing puck; every oven element switches with its zone's duty cycle (time-
             proportioning, 2 s) and the timeline carries the phase currents; the kicker fires twice; both
             deltas run real pick -> place cycles (delta_ik at
             every frame: an unreachable frame is a failure); the three sealers and stackers cycle; lane
             'weiss' runs a full cassette exchange through the out airlock (carrier out, inner door shut,
             outer door open, AMR swap, outer shut, inner open, carrier back).
  transforms every moving part's rigid placement relative to the CAD (rods rotate: the delta arms);
             piston rods EXTEND (re-shaped per frame); the screws / brackets of a moving body follow it.
  sweep      every frame: moving parts vs the static machine and vs each other (exact-ish geom, the
             declared joints / product contacts excepted). This replaces the 80-pose delta check with
             the whole motion.

Run: python3 motion.py   -> motion/timeline.json, motion/report.txt   (exit 1 if the sweep finds a hit)
Play: open STF2_Precise.FCStd in FreeCAD, then Macro -> play_motion.FCMacro
"""
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import geom as G
import line_model as M

L = M.L
OUT = os.path.join(HERE, "motion")
T_END, DT = 40.0, 0.1
FLAV = M.FLAV

# ------------------------------------------------------------------ schedule (one place, all in s)
KICKS = (6.0, 26.0)
SEALS = {"weiss": 10.0, "rot": 22.0, "blau": 34.0}
LIFTS = {f: t + 2.0 for f, t in SEALS.items()}
EXCH_LANE, EXCH_T0 = "weiss", 4.0
DELTA_PHASE = (0.0, 1.0)                      # A and B half a cycle apart


def smooth(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def ramp(t, t0, dur):
    """0 before t0, smooth 0 -> 1 over dur."""
    return smooth((t - t0) / dur) if dur > 0 else float(t >= t0)


def pulse(t, t0, up, hold, down):
    """0 -> 1 over up, hold, 1 -> 0 over down."""
    return ramp(t, t0, up) - ramp(t, t0 + up + hold, down)


def exchange():
    """Phases of the airlock exchange: (name, start, duration)."""
    mv = (L["CASS_X"][1] - L["CASS_X"][0]) / L["SHUTTLE_V"]
    d = L["DOOR_T"]
    seq = [("carrier out", mv), ("inner door shut", d), ("outer door open", d), ("AMR swap", L["AMR_EXCH"]),
           ("outer door shut", d), ("inner door open", d), ("carrier back", mv)]
    out, t = [], EXCH_T0
    for n, dur in seq:
        out.append((n, t, dur))
        t += dur
    return out


PWM = 2.0                                     # s, time-proportioning period of the element SSRs (FB_Oven)


def duty():
    """Zone duty = steady load / installed (oven.py) - what the PID settles to in production."""
    loads, els, _, _ = M.oven_power()
    return {z["zone"]: z["total"] / sum(e["P"] for e in els if e["zone"] == z["zone"]) for z in loads}


def element_on(e, i, t, d):
    """Element i of its zone conducts in a staggered slice of the 2 s period (spreads the phase current)."""
    n = sum(1 for x in M.oven_power()[1] if x["zone"] == e["zone"])
    u = ((t / PWM) + i / n) % 1.0
    return u < d[e["zone"]]


def power_at(t, d):
    """(W total, {phase: A}) of the oven elements + fans at time t."""
    _, els, plan, _ = M.oven_power()
    ph = {tg: p for p, items in plan.items() for tg, _ in items}
    amps = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
    W = 0.0
    idx = defaultdict(int)
    for e in els:
        i = idx[e["zone"]]
        idx[e["zone"]] += 1
        if element_on(e, i, t, d):
            W += e["P"]
            amps[ph[e["tag"]]] += e["P"] / 230.0
    for k in range(len(L["OVEN_ZONES"])):
        W += M.H.OVEN_FAN["P"]
        amps[ph[f"QF{k + 1}"]] += M.H.OVEN_FAN["P"] / 230.0
    return W, amps


def wire_dx(t):
    """The cutting wire sweeps across the die once per row (cam on the roll drive)."""
    period = L["BAND"]["spacing"] / M.band_v()
    u = t % period
    return (L["DOUGH_SLUG"][0] + 10.0) * (pulse(u, 0.0, 0.3, 0.0, 0.3) - 0.5)


def delta_c_pose(t):
    """Delta C: pick cookie k of the row in the window at t_pick, place it 1 s later into the puck at s_place
    (tracking the puck along the bend), back to travel height. Returns (pose, carrying, (row, k))."""
    T = M.takt()
    t_enter, s_pl = M.transfer_times()
    period = L["BAND"]["rows"] * T
    st = M.stations()
    v = M.band_v()
    xc = L["DELTA_C"]["x"]
    zt, zb, zp = M.travel_z(xc), M.band_pick_z(), M.pick_z()
    # the pick this cycle belongs to: t_pick = r * period + t_enter + (k+1) T, with u in [-0.5, 3.5) around it
    n = math.floor((t - t_enter + 0.5) / T)                # picks since the row r = 0 ... in takt counts
    t_pick = t_enter + n * T
    r, kk = divmod(n - 1, L["BAND"]["rows"])
    u = t - t_pick
    xp = st["dep"] + v * (t_pick - r * period)              # the cookie's x at the pick moment
    yp = M.row_y(kk)
    sp = lambda tt: (s_pl + L["V"] * (tt - (t_pick + 1.0)))
    def at_s(tt, z):
        (x, y), _ = M.pos(sp(tt))
        return (x, y, z)
    way = [(-0.5, (xp, yp, zt)), (-0.2, (xp, yp, zb)), (0.0, (xp, yp, zb)), (0.25, (xp + v * 0.25, yp, zt)),
           (0.75, at_s(t_pick + 0.75, zt)), (1.0, at_s(t_pick + 1.0, zp)), (1.1, at_s(t_pick + 1.1, zp)),
           (1.35, at_s(t_pick + 1.35, zt)), (2.0, (xp + v * T, M.row_y((kk + 1) % L["BAND"]["rows"]), zt)),
           (3.5, (xp + v * T, M.row_y((kk + 1) % L["BAND"]["rows"]), zt))]
    for (ta, a), (tb, b) in zip(way, way[1:]):
        if ta <= u <= tb:
            f = smooth((u - ta) / (tb - ta))
            return tuple(a[j] + (b[j] - a[j]) * f for j in range(3)), (0.0 <= u <= 1.05), (r, kk)
    return way[-1][1], False, (r, kk)


def delta_pose(i, t):
    """Effector pose of delta i at time t (pick on the moving belt -> pocket of a lane -> back)."""
    xd = L["DELTA_X"][i]
    c, _ = M.delta_window(xd)
    yb, zt, zp, zl = M.y_back(), L["TRAVEL_Z"], M.pick_z(), M.place_z()
    tc = L["T_PICK"]
    k = int((t + DELTA_PHASE[i] * 1.0) // tc)
    u = (t + DELTA_PHASE[i]) % tc
    x0 = xd + c / 2 - 15                               # pick starts upstream (the back run flows -x)
    belt = lambda uu: x0 - L["V"] * min(uu, 1.0)        # the cookie under the cup moves with the belt
    lane = L["LANE_Y"][k % 3]
    px = xd + (-L["POCKET_PITCH"], 0.0, L["POCKET_PITCH"])[(k // 3) % 3]
    nxt_lane = L["LANE_Y"][(k + 1) % 3]
    way = [(0.0, (x0, yb, zt)), (0.30, (belt(0.30), yb, zp)), (0.80, (belt(0.80), yb, zp)),
           (1.00, (belt(1.00), yb, zt)), (1.40, (px, lane, zt)), (1.60, (px, lane, zl)), (1.70, (px, lane, zl)),
           (1.85, (px, lane, zt)), (2.00, (x0, yb, zt))]
    for (ta, a), (tb, b) in zip(way, way[1:]):
        if ta <= u <= tb:
            s = smooth((u - ta) / (tb - ta))
            return tuple(a[j] + (b[j] - a[j]) * s for j in range(3)), (0.30 <= u <= 1.60)
    return way[-1][1], False


# ------------------------------------------------------------------ transforms
def _rot_between(a, b):
    """Rotation matrix taking unit vector a onto unit vector b (Rodrigues)."""
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    a = [x / na for x in a]
    b = [x / nb for x in b]
    v = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    c = sum(x * y for x, y in zip(a, b))
    s = math.sqrt(sum(x * x for x in v))
    if s < 1e-12:
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]] if c > 0 else [[-1, 0, 0], [0, -1, 0], [0, 0, 1]]
    k = [x / s for x in v]
    K = [[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]]
    K2 = [[sum(K[i][m] * K[m][j] for m in range(3)) for j in range(3)] for i in range(3)]
    return [[(1 if i == j else 0) + s * K[i][j] + (1 - c) * K2[i][j] for j in range(3)] for i in range(3)]


def _quat(R):
    tr = R[0][0] + R[1][1] + R[2][2]
    if tr > 0:
        S = math.sqrt(tr + 1.0) * 2
        return ((R[2][1] - R[1][2]) / S, (R[0][2] - R[2][0]) / S, (R[1][0] - R[0][1]) / S, 0.25 * S)
    if R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        S = math.sqrt(1.0 + R[0][0] - R[1][1] - R[2][2]) * 2
        return (0.25 * S, (R[0][1] + R[1][0]) / S, (R[0][2] + R[2][0]) / S, (R[2][1] - R[1][2]) / S)
    if R[1][1] > R[2][2]:
        S = math.sqrt(1.0 + R[1][1] - R[0][0] - R[2][2]) * 2
        return ((R[0][1] + R[1][0]) / S, 0.25 * S, (R[1][2] + R[2][1]) / S, (R[0][2] - R[2][0]) / S)
    S = math.sqrt(1.0 + R[2][2] - R[0][0] - R[1][1]) * 2
    return ((R[0][2] + R[2][0]) / S, (R[1][2] + R[2][1]) / S, 0.25 * S, (R[1][0] - R[0][1]) / S)


def rod_ends(p):
    if p.kind == "rod":
        return p.p, p.s[:3]
    ax, ln, _ = p.s
    i = "xyz".index(ax)
    e = list(p.p)
    e[i] += ln
    return p.p, tuple(e)


def rigid(base, now):
    """(quaternion, translation) with x_now = R x_base + t for a part that moved rigidly."""
    if base.kind == "rod" and now.kind == "rod":
        a0, a1 = rod_ends(base)
        b0, b1 = rod_ends(now)
        R = _rot_between([a1[i] - a0[i] for i in range(3)], [b1[i] - b0[i] for i in range(3)])
        t = [b0[i] - sum(R[i][j] * a0[j] for j in range(3)) for i in range(3)]
        return _quat(R), t
    return (0.0, 0.0, 0.0, 1.0), [now.p[i] - base.p[i] for i in range(3)]


def shifted(p, d):
    q = M.Part(p.name, p.module, p.group, p.kind, tuple(p.p[i] + d[i] for i in range(3)), p.s, p.colour,
               joint=p.joint, tag=p.tag, mech=p.mech, hw=p.hw)
    if p.kind == "rod":
        q.s = tuple(p.s[i] + d[i] for i in range(3)) + (p.s[3],)
    return q


def cyl(p, start, axis, length):
    return M.Part(p.name, p.module, p.group, "cyl", tuple(start), (axis, length, p.s[2]), p.colour, joint=p.joint,
                  hw=p.hw)


# ------------------------------------------------------------------ one frame
def frame(t, base):
    """{part name: Part at time t} for every moving part, + {name: visible}."""
    now, vis = {}, {}
    # chain: pucks + their cookies (a cookie exists on every puck; shown while the puck is loaded)
    loop = []
    M._pucks(loop.append, t)
    shown = {p.name for p in loop}
    for k in range(L["N"]):
        pk = next(p for p in loop if p.name == f"puck_{k:02d}")
        now[pk.name] = pk
        ck = M.Part(f"cookie_{k:02d}", pk.module, "cookie", "cyl", (pk.p[0], pk.p[1], M.z_seat()),
                    ("z", L["COOKIE"][1], L["COOKIE"][0]), M.cookie_hex(), joint="loop")
        now[ck.name] = ck
        vis[ck.name] = ck.name in shown
        tp = M.Part(f"cookie_{k:02d}_top", pk.module, "cookie", "cyl", (pk.p[0], pk.p[1], M.z_cookie_top()),
                    ("z", L["TOPPING"]["h"], L["TOPPING"]["d"]), L["BAKED"][k % 3], joint="loop")
        now[tp.name] = tp
        vis[tp.name] = tp.name in shown
    # band: every row of the window [0, T_END] - re-shaped per frame (the slug spreads, the colour browns)
    for n in BAND_NAMES:
        now[n], vis[n] = band_pose(n, t)
    # cutting wire
    now["dep_wire"] = shifted(base["dep_wire"], (wire_dx(t), 0, 0))
    # kicker
    ky = -L["KICK_STROKE"] * sum(pulse(t, t0, L["KICK_T"], 0.1, L["KICK_T"]) for t0 in KICKS)
    now["kick_paddle"] = shifted(base["kick_paddle"], (0, ky, 0))
    r = base["kick_rod"]
    now["kick_rod"] = cyl(r, (r.p[0], r.p[1] + ky, r.p[2]), "y", r.s[1] - ky)
    # sealers + stackers
    for f in FLAV:
        sd = -L["SEAL_GAP"] * pulse(t, SEALS[f], 0.25, L["SEAL_T"], 0.25)
        now[f"sealer_{f}_head"] = shifted(base[f"sealer_{f}_head"], (0, 0, sd))
        r = base[f"sealer_{f}_rod"]
        now[r.name] = cyl(r, (r.p[0], r.p[1], r.p[2] + sd), "z", r.s[1] - sd)
        lz = (L["PAWL"] + L["BOX"][2]) * pulse(t, LIFTS[f], 0.4, 0.2, 0.4)
        now[f"stacker_plate_{f}"] = shifted(base[f"stacker_plate_{f}"], (0, 0, lz))
        r = base[f"stacker_rod_{f}"]
        now[r.name] = cyl(r, r.p, "z", r.s[1] + lz)
    # airlock exchange (lane EXCH_LANE): carrier + cassette, inner / outer door leaves
    ph = {n: (t0, d) for n, t0, d in exchange()}
    stroke = L["CASS_X"][1] - L["CASS_X"][0]
    cx = stroke * (ramp(t, *ph["carrier out"]) - ramp(t, *ph["carrier back"]))
    for p in base.values():
        if p.joint == f"shuttle_{EXCH_LANE}":
            now[p.name] = shifted(p, (cx, 0, 0))
    sw = ph["AMR swap"]
    vis[f"cassette_{EXCH_LANE}_active_stack"] = t < sw[0] + sw[1] / 2      # the AMR brings an EMPTY one
    inner = M.door_stroke("S32") * (1 - ramp(t, *ph["inner door shut"]) + ramp(t, *ph["inner door open"]))
    outer = M.door_stroke("S31") * (ramp(t, *ph["outer door open"]) - ramp(t, *ph["outer door shut"]))
    now["aldoor_inner"] = shifted(base["aldoor_inner"], (0, inner, 0))
    now["aldoor_out"] = shifted(base["aldoor_out"], (0, outer, 0))
    # delta C: band -> puck
    bad = []
    pose, carrying, _ = delta_c_pose(t)
    arms = []
    try:
        M._delta(arms.append, "delta_C", L["DELTA_C"]["x"], pose, static=False, module="transfer")
        for p in arms:
            p.module = "M4_transfer"
            now[p.name] = p
        cup = now["delta_C_cup_a"]
        held = M.Part("held_C", "M4_transfer", "cookie", "cyl", (pose[0], pose[1], cup.p[2] - L["COOKIE"][1]),
                      ("z", L["COOKIE"][1], L["COOKIE"][0]), M.cookie_hex(), joint="held")
        now[held.name] = held
        vis[held.name] = carrying
    except ValueError:
        bad.append(f"delta_C cannot reach {tuple(round(v) for v in pose)} at t={t:.1f}")
    # deltas
    for i, xd in enumerate(L["DELTA_X"]):
        pose, carrying = delta_pose(i, t)
        arms = []
        try:
            M._delta(arms.append, f"delta_{'AB'[i]}", xd, pose, static=False)
        except ValueError:
            bad.append(f"delta_{'AB'[i]} cannot reach {tuple(round(v) for v in pose)} at t={t:.1f}")
            continue
        for p in arms:
            p.module = "M6_pick"
            now[p.name] = p
        cup = now[f"delta_{'AB'[i]}_cup_a"]
        held = M.Part(f"held_{'AB'[i]}", "M6_pick", "cookie", "cyl", (pose[0], pose[1], cup.p[2] - L["COOKIE"][1]),
                      ("z", L["COOKIE"][1], L["COOKIE"][0]), L["BAKED"][i], joint="held")
        now[held.name] = held
        vis[held.name] = carrying
    return now, vis, bad


# ------------------------------------------------------------------ sweep check
SKIP_GROUPS = {("puck", "chain"), ("puck", "guide"), ("cookie", "puck"), ("cookie", "chain")}


def _exempt(a, b):
    """Contacts the motion makes on purpose (or declared joints)."""
    ga, gb = a.group, b.group
    if (ga, gb) in SKIP_GROUPS or (gb, ga) in SKIP_GROUPS:
        return True
    names = (a.name, b.name)
    if any("_cup_" in n for n in names) and {ga, gb} & {"cookie", "puck", "tray", "stock"}:
        return True                                    # the cup takes the cookie / sets it in the pocket
    if any(n.startswith("held_") for n in names):
        other = b if a.name.startswith("held_") else a
        return other.group in ("tray", "stock", "cookie", "puck") or "_cup_" in other.name or \
            other.name.endswith("_effector")
    if {ga, gb} == {"cookie", "band"} or (ga == gb == "cookie" and a.name.split("_top")[0] == b.name.split("_top")[0]):
        return True                                    # the product lies on the band / its drop on it
    if "dep_wire" in names and {ga, gb} & {"cookie"}:
        return True                                    # the wire cuts the slug free (that is the process)
    if "kick_paddle" in names and {ga, gb} & {"cookie"}:
        return True                                    # the kicker pushes a cookie off (that is the process)
    if "stacker_plate" in a.name + b.name and {ga, gb} & {"stock"}:
        return True                                    # the lift plate pushes the pack up
    if "sealer" in a.name + b.name and {ga, gb} & {"tray", "stock"}:
        return True                                    # the head seals onto the tray flange
    if a.joint and a.joint == b.joint and not a.joint.startswith(("delta", "loop")):
        return True                                    # one rigid body
    if M.allowed(a, b):
        return True
    return False


class Grid:
    def __init__(self, parts, cell=100.0):
        self.c, self.cells = cell, defaultdict(list)
        for p in parts:
            for key in self._keys(p.aabb()):
                self.cells[key].append(p)

    def _keys(self, b):
        c = self.c
        for i in range(int(b[0] // c), int(b[3] // c) + 1):
            for j in range(int(b[1] // c), int(b[4] // c) + 1):
                for k in range(int(b[2] // c), int(b[5] // c) + 1):
                    yield i, j, k

    def near(self, b):
        seen = {}
        for key in self._keys(b):
            for p in self.cells.get(key, ()):
                seen[id(p)] = p
        return seen.values()


def sweep(times, base, moving_names):
    static = [p for n, p in base.items() if n not in moving_names]
    grid = Grid(static)
    hits, bad, pairs = defaultdict(list), [], 0
    for t in times:
        now, vis, b_ = frame(t, base)
        bad += b_
        live = [p for n, p in now.items() if vis.get(n, True)]
        for p in live:
            if p.name.startswith("band_r"):
                continue                                   # band product vs the machine: line_model.band_clearance
            pa = p.aabb()
            for q in grid.near(pa):
                if not M._ovl(pa, q.aabb()) or _exempt(p, q):
                    continue
                pairs += 1
                if G.interfere(p, q):
                    hits[(p.name, q.name)].append(t)
        lg = Grid(live, 150.0)
        for p in live:
            for q in lg.near(p.aabb()):
                if id(q) <= id(p) or not M._ovl(p.aabb(), q.aabb()) or _exempt(p, q):
                    continue
                if p.group == q.group and p.group in ("puck", "cookie"):
                    continue
                pairs += 1
                if G.interfere(p, q):
                    hits[tuple(sorted((p.name, q.name)))].append(t)
    return hits, bad, pairs


def band_pose(n, t):
    """(Part, visible) of band product n ('band_r<r+100>_<k>[_top]') at time t, in closed form: the row was
    deposited at r * period; before that it waits (hidden) at the die, after the pick it rests (hidden)
    where delta C took it."""
    top = n.endswith("_top")
    r, k = n[len("band_r"):].split("_")[:2]
    r, k = int(r) - 100, int(k)
    st = M.stations()
    v = M.band_v()
    T = M.takt()
    period = L["BAND"]["rows"] * T
    t_enter = M.transfer_times()[0]
    t_in = t - r * period
    t_gone = t_enter + (k + 1) * T                      # delta C has it
    vis = 0.0 <= t_in < t_gone
    ti = min(max(t_in, 0.0), t_gone)
    d, h, col, topped = M.band_state(ti)
    x = M.g1(st["dep"] + v * ti)
    zb = L["BAND"]["z"]
    if top:
        Tp = L["TOPPING"]
        p = M.Part(n, "M3_oven", "cookie", "cyl", (x, M.row_y(k), zb + round(h, 2)), ("z", Tp["h"], Tp["d"]),
                   L["BAKED"][M.row_flavour(k)], joint="band")
        return p, vis and topped
    p = M.Part(n, "M3_oven", "cookie", "cyl", (x, M.row_y(k), zb), ("z", round(h, 2), round(d, 2)), col, joint="band")
    return p, vis


def _band_names():
    out = []
    for t in (0.0, T_END / 2, T_END):
        ps = []
        M._band_product(ps.append, t)
        out += [p.name for p in ps]
    seen = []
    for t in [k * DT for k in range(int(T_END / DT) + 1)][::10]:
        ps = []
        M._band_product(ps.append, t)
        seen += [p.name for p in ps]
    return sorted(set(out) | set(seen))


BAND_NAMES = _band_names()


def _sweep_chunk(times):
    base = {p.name: p for p in M.build()}
    f0, _, _ = frame(0.0, base)
    h, b, p = sweep(times, base, set(f0))
    return dict(h), b, p


# ------------------------------------------------------------------ export
def main():
    base = {p.name: p for p in M.build()}
    times = [round(k * DT, 3) for k in range(int(T_END / DT) + 1)]
    f0, _, _ = frame(0.0, base)
    moving = set(f0)
    # cookies the CAD does not have (pucks not loaded at t = 0) are SPAWNED by the player
    spawn = []
    for n, p in f0.items():
        if n not in base:
            spawn.append(dict(name=n, kind="cyl", p=p.p, s=list(p.s), colour=p.colour))
    for n in BAND_NAMES:                                 # rows deposited later in the window
        if n not in base and n not in f0:
            raise SystemExit(f"band row {n} has no first pose")
    from multiprocessing import Pool
    n = os.cpu_count() or 4
    chunks = [times[i::n] for i in range(n)]
    with Pool(n) as pool:
        parts_ = pool.map(_sweep_chunk, chunks)
    hits, bad, pairs = defaultdict(list), [], 0
    for h, b_, p_ in parts_:
        for k, v in h.items():
            hits[k] += v
        bad += b_
        pairs += p_
    for k in hits:
        hits[k].sort()
    # transforms per frame (rigid) and re-shapes (extending rods)
    reshape = {"kick_rod"} | {f"sealer_{f}_rod" for f in FLAV} | {f"stacker_rod_{f}" for f in FLAV} | \
        {n for n in BAND_NAMES if not n.endswith("_top")}
    ref = dict(base)
    for s in spawn:
        ref[s["name"]] = f0[s["name"]]
    track = defaultdict(list)
    for t in times:
        now, vis, _ = frame(t, base)
        for n, p in now.items():
            if n in reshape:
                e = dict(c=[p.p[0], p.p[1], p.p[2]], ax=p.s[0], len=round(p.s[1], 3), dia=p.s[2])
                if n.startswith("band_r"):
                    e["col"] = p.colour
                    e["vis"] = 1 if vis.get(n, True) else 0
                track[n].append(e)
            else:
                q, tr = rigid(ref[n], p)
                track[n].append([round(v, 3) for v in tr] + [round(v, 6) for v in q] + [1 if vis.get(n, True) else 0])
    # screws + brackets ride with the moving body they belong to
    import joints as J
    _, B = J.check(verbose=False)
    follow, split = {}, []
    same = lambda u, v: all(x[:7] == y[:7] for x, y in zip(track[u], track[v]))
    for k, f in enumerate(B.fasteners):
        a, b = f.joint.split("~")[:2]
        mv = [x for x in (a, b) if x in moving]
        if not mv:
            continue
        body = next((x for x in mv if x not in reshape), mv[0])
        if len(mv) == 1 or not same(a, b):            # a screw may never join two differently moving parts
            split.append(f"SCREW F{k:04d} ({f.joint}) joins parts that move differently")
            continue
        follow[f"F{k:04d}_"] = body
    for br in B.brackets:
        j = getattr(br, "_joint", "")
        parts_ = j.split("~")[:2]
        mv = [x for x in parts_ if x in moving and x not in reshape]
        if mv and all(x in moving for x in parts_ if x in base):
            follow[br.name] = mv[0]
    d = duty()
    glow, power = {}, []
    idx = defaultdict(int)
    for e in M.oven_power()[1]:
        i = idx[e["zone"]]
        idx[e["zone"]] += 1
        glow[f"oven_heater_{e['tag']}"] = dict(on="#ff6a1a", off="#5a2a1c",
                                               bits="".join("1" if element_on(e, i, t, d) else "0" for t in times))
    for t in times:
        W, amps = power_at(t, d)
        power.append([round(W), round(amps["L1"], 2), round(amps["L2"], 2), round(amps["L3"], 2)])
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "timeline.json"), "w") as fh:
        json.dump(dict(dt=DT, frames=len(times), t_end=T_END, track=track, spawn=spawn, follow=follow,
                       glow=glow, power=power, duty={k: round(v, 3) for k, v in d.items()},
                       zones=[dict(T=Z["T"]) for Z in L["OVEN_ZONES"]],
                       phases=dict(exchange=exchange(), kicks=KICKS, seals=SEALS, lifts=LIFTS)), fh)
    rep = [f"moving twin: {len(times)} frames x {DT:g} s = {T_END:g} s, {len(moving)} moving parts "
           f"({len(spawn)} spawned cookies), {len(follow)} screws/brackets follow their body, {pairs} exact pair "
           f"tests", f"exchange of lane '{EXCH_LANE}': " + ", ".join(f"{n} {t0:.1f}+{d:.1f} s" for n, t0, d in exchange())]
    fails = [f"HIT {a} x {b} at t = {ts[0]:.1f} .. {ts[-1]:.1f} s ({len(ts)} frames)" for (a, b), ts in sorted(hits.items())]
    fails += sorted(set(bad)) + split
    rep += fails if fails else ["SWEEP PASSES: no moving part hits the machine or another moving part at any frame; "
                                "every delta pose is reachable"]
    open(os.path.join(OUT, "report.txt"), "w").write("\n".join(rep) + "\n")
    cad = os.path.expanduser("~/workspace/stf-factory/cad/line2_precise/motion")
    if not fails and os.path.isdir(os.path.dirname(cad)):          # the player looks for it beside the CAD
        import shutil
        os.makedirs(cad, exist_ok=True)
        for fn in ("timeline.json", "motion_player.py", "play_motion.FCMacro"):
            shutil.copy(os.path.join(OUT, fn), os.path.join(cad, fn))
    print("\n".join(rep[:60]))
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
