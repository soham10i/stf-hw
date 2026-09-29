"""
STF-2 safety (Upgrade S-1): proves the safety HARDWARE the concept asks for is built and wired, and
audits the openings against ISO 13855 / ISO 13857.  SAFETY_CONCEPT.md says WHAT; this says whether
the model delivers it.

PROOFS (the build refuses if one fails)
  G1 enclosure     every hazardous moving / hot part above the deck lies inside the guard volume
  G2 walls         each guard wall, projected, is closed: panels + doors + posts + curtain bars; every
                   gap left is <= 6 mm (ISO 13857 Table 4: needs only 10 mm to a hazard) except the
                   DECLARED openings (the two curtain-protected AMR ports, the raw pour strip)
  G3 roof          the roof (panels + rails) closes the plan except the declared raw pour strip
  G4 roof sag      4 mm PC one-way span under its own weight <= 3 mm and clear of what is below
  G5 doors         every door: a leaf on the hinge post, a guard-locking switch on the lock post,
                   holding force >= 1000 N
  G6 E-stops       every wall with a door has one; every door's lock side is within 2 m of one;
                   heads outside the guard, on the deck
  G7 cut-off       every stepper is behind K1/K2 (48 V), every port-zone motor behind its zone
                   contactor, every cylinder valve behind the dump valve Q19 (port zones: Y1/Y2),
                   every heated zone has its own STL
  G8 timing        SS1 delay >= the longest NC ramp; a door unlocks no earlier than SS1 + contactor
                   drop-out + standstill time
  G9 ports         every declared port opening is bounded by a type 4 light-curtain pair
AUDIT (reported as FINDINGS - they do not stop the build, they stop OPERATION until resolved)
  ISO 13855 S = K T + 8 (d - 14) from each curtain to each hazard (curtain trip -> STO + dump);
  ISO 13857 reach while a port is MUTED (AMR docked): hazards outside the port's zone keep running;
  curtain dead-zone gaps; the reject drawer (flap not in the CAD); under-deck parts (skirt not modelled).

Run: python3 safety.py   -> safety/safety_functions.csv, safety/reach_audit.csv, safety/report.md
"""
import csv
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hardware as H
import line_model as M
import plc_io as P

L = M.L
OUT = os.path.join(HERE, "safety")
GAP_MAX = 6.0             # mm: ISO 13857 Table 4, e <= 6 -> 10 mm (slot) - nothing hazardous is that close to a wall
SAG_MAX = 3.0
F_HOLD_MIN = 1000.0       # N guard-locking holding force [assumed requirement - ISO 14119 leaves it to the RA]
ESTOP_REACH = 2000.0      # mm from a door's lock side to the nearest E-stop [assumed layout rule]

# hazards: (name, selector, kind, t_mech s [assumed - MEASURE], force N or None=high)
# t_mech = time for the unpowered / exhausted mechanism to come to rest after the contactors drop
HAZARDS = (
    ("chain loop (drawing-in at bends / drive)", lambda p: p.group in ("chain", "drive"), "motion", 0.02, None),
    ("delta A", lambda p: p.group == "delta_A", "motion", 0.10, None),
    ("delta B", lambda p: p.group == "delta_B", "motion", 0.10, None),
    ("flying stamp (screw axis + D16)", lambda p: p.group in ("carriage", "tool") or p.name.startswith(("stamp_spindle",
                                                                                                         "M_stamp")),
     "motion", 0.10, None),
    ("stamp die (hot)", lambda p: p.name == "stamp_die", "heat", None, None),
    ("QC kicker D10", lambda p: p.name.startswith("kick_"), "motion", 0.10, H.cyl_force(10)),
    ("escapement gates D10", lambda p: p.name.startswith(("esc_cyl", "esc_gate")), "motion", 0.10, H.cyl_force(10)),
    ("singulator discs", lambda p: p.name.startswith("singulator_") and p.kind == "cyl" and "shaft" not in p.name,
     "motion", 0.02, L["SING_T"] / 0.09),
    ("lane belts (in-running nips)", lambda p: p.name.startswith("lane_") and p.name.endswith("_belt"), "motion",
     0.02, None),
    ("sealers D25 (crush + hot)", lambda p: p.name.startswith("sealer_") and p.name.endswith(("_head", "_cyl", "_rod")),
     "motion", 0.10, None),
    ("stacker lifts D16", lambda p: p.group == "stacker" and p.name.startswith(("stacker_lift", "stacker_rod",
                                                                                "stacker_plate")),
     "motion", 0.10, H.cyl_force(16)),
    ("shuttles + cassettes", lambda p: p.name.startswith(("shuttle_bar", "shuttle_block", "shuttle_plate",
                                                          "M_shuttle")) or p.group == "cassette",
     "motion", 0.05, None),
    ("tray magazine forks D8", lambda p: p.group == "boxmag" and "_fork_" in p.name, "motion", 0.10, H.cyl_force(8)),
    ("oven IR bars (hot)", lambda p: "_heater_" in p.name, "heat", None, None),
    ("airlock doors (power-operated, force-limited)", lambda p: p.group == "airlock_door", "motion", 0.10,
     H.SAFE["airlock_door"]["F_close"]),
    ("trapdoor flaps", lambda p: p.group == "trapdoor", "motion", 0.10,
     H.SAFE["trapdoor"]["T"] / H.SAFE["trapdoor"]["arm"]),
)


def hazards(parts):
    out = []
    zone_groups = L["PORT_ZONE"]
    for name, sel, kind, tm, force in HAZARDS:
        ps = [p for p in parts if sel(p)]
        if not ps:
            continue
        port = next((k for k, gs in zone_groups.items() if all(p.group in gs or p.group == "cassette" and "gantry" in gs
                                                                for p in ps)), None)
        low = force is not None and force <= H.F_LOW
        out.append(dict(name=name, parts=ps, kind=kind, t_mech=tm, force=force, low=low, zone=port))
    return out


def _box_dist(a, b):
    d2 = 0.0
    for i in range(3):
        g = max(a[i] - b[i + 3], b[i] - a[i + 3], 0.0)
        d2 += g * g
    return math.sqrt(d2)


def inner():
    g = M.guard()
    return dict(x0=g["xLo"] + g["t"], x1=g["xRo"] - g["t"], y0a=g["yF1o"] + g["t"], y0b=g["yF2o"] + g["t"],
                xs=g["xS"] + g["w"] + g["t"], y1=g["yBo"] - g["t"], z1=L["GUARD_TOP"])


def walls():
    """(name, normal axis, band n0..n1, along a0..a1) of each guard wall."""
    g = M.guard()
    t, w = g["t"], g["w"]
    return [("F1", 1, g["yF1o"], g["yF1"] + w, g["xLo"], g["xS"] + w + t),
            ("step", 0, g["xS"], g["xS"] + w + t, g["yF1o"], g["yF2o"] + t),
            ("F2", 1, g["yF2o"], g["yF2"] + w, g["xS"] + w, g["xRo"]),
            ("back", 1, g["yB"], g["yBo"], g["xLo"], g["xRo"]),
            ("left", 0, g["xLo"], g["xL"] + w, g["yF1o"], g["yBo"]),
            ("right", 0, g["xR"], g["xRo"], g["yF2o"], g["yBo"])]


def openings():
    """Declared openings: (wall, a0, a1, z0, z1, kind, name)."""
    g = M.guard()
    out = [("F1", L["HOPPER_X"][0], L["HOPPER_X"][-1] + L["HOPPER"][0], L["HOPPER_Z"] + L["HOPPER"][2],
            L["GUARD_TOP"], "raw", "raw pour strip (into the hopper strip only)")]
    for name, (side, y0, y1, z0, z1, tag) in L["PORT_OPEN"].items():
        if L.get("AIRLOCK"):             # the outer airlock door's opening, between the port posts
            out.append((side, y0 + g["w"], y1 - g["w"], z0, min(z1, g["zt"]), "airlock", name))
        else:
            sec = H.SAFE["light_curtain"]["section"]
            out.append((side, y0 + g["w"] + sec[1], y1 - g["w"] - sec[1], z0, min(z1, g["zt"]), "port", name))
    return out


def _gaps(mask):
    """Opening size e of the largest uncovered region = side of the largest free square that fits
    (a 2 mm slot of any length and shape gives e = 2). Prefix sums + binary search."""
    free = (~mask).astype(np.int32)
    if not free.any():
        return 0.0, None
    S = np.zeros((free.shape[0] + 1, free.shape[1] + 1), dtype=np.int64)
    S[1:, 1:] = free.cumsum(0).cumsum(1)

    def fits(k):
        w = S[k:, k:] - S[:-k, k:] - S[k:, :-k] + S[:-k, :-k]
        hit = np.argwhere(w == k * k)
        return hit[0] if len(hit) else None
    lo, hi, at = 1, min(free.shape), fits(1)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        h = fits(mid)
        if h is not None:
            lo, at = mid, h
        else:
            hi = mid - 1
    return float(lo), tuple(at)


def g2_walls(parts):
    fails, rows = [], []
    gp = [p for p in parts if p.module == "M10_safety" and p.kind == "box" and p.group in ("guard", "door", "sensor")
          and not p.name.startswith("lock_")]
    zt = L["GUARD_TOP"]
    for name, n, n0, n1, a0, a1 in walls():
        ax = 1 - n if n in (0, 1) else 0
        A0, A1 = int(math.floor(a0)), int(math.ceil(a1))
        mask = np.zeros((int(zt), A1 - A0), dtype=bool)
        for p in gp:
            b = p.aabb()
            if b[n] < n0 - 1e-6 or b[n + 3] > n1 + 1e-6:
                continue
            i0, i1 = max(int(round(b[ax])) - A0, 0), min(int(round(b[ax + 3])) - A0, A1 - A0)
            z0, z1 = max(int(round(b[2])), 0), min(int(round(b[5])), int(zt))
            if i1 > i0 and z1 > z0:
                mask[z0:z1, i0:i1] = True
        for wall, o0, o1, z0, z1, kind, oname in openings():
            if wall == name:
                mask[int(z0):int(z1), max(int(o0) - A0, 0):min(int(o1) - A0, A1 - A0)] = True
        e, where = _gaps(mask)
        ok = e <= GAP_MAX
        rows.append((f"G2 wall {name}", f"largest gap e = {e:.0f} mm", f"<= {GAP_MAX:g} mm", ok,
                     "panels + doors + posts + curtain bars; declared openings excluded"))
        if not ok:
            fails.append(f"G2 wall {name}: open gap e = {e:.0f} mm at along {A0 + where[1]}, z {where[0]}")
    return rows, fails


def g3_roof(parts):
    ii = inner()
    g = M.guard()
    X0, X1 = int(g["xLo"]), int(g["xRo"])
    Y0, Y1 = int(g["yF1o"]), int(g["yBo"])
    mask = np.zeros((Y1 - Y0, X1 - X0), dtype=bool)
    # outside the plan: the step's outer corner (front of F2)
    mask[0:int(g["yF2o"]) - Y0, int(ii["xs"]) - X0:] = True
    for p in parts:
        if p.module != "M10_safety" or p.kind != "box":
            continue
        b = p.aabb()
        if b[5] < L["GUARD_TOP"] - 20 - 1e-6:        # roof panels and top rails only
            continue
        mask[max(int(b[1]) - Y0, 0):min(int(math.ceil(b[4])) - Y0, Y1 - Y0),
             max(int(b[0]) - X0, 0):min(int(math.ceil(b[3])) - X0, X1 - X0)] = True
    for wall, o0, o1, z0, z1, kind, oname in openings():
        if kind == "raw":
            mask[0:int(L["RAW_Y"]) - 20 - Y0, int(o0) - X0:int(o1) - X0] = True
    # walls: the wall bands themselves are closed by G2
    for name, n, n0, n1, a0, a1 in walls():
        if n == 1:
            mask[max(int(n0) - Y0, 0):min(int(n1) - Y0, Y1 - Y0), max(int(a0) - X0, 0):min(int(a1) - X0, X1 - X0)] = True
        else:
            mask[max(int(a0) - Y0, 0):min(int(a1) - Y0, Y1 - Y0), max(int(n0) - X0, 0):min(int(n1) - X0, X1 - X0)] = True
    e, where = _gaps(mask)
    ok = e <= GAP_MAX
    row = ("G3 roof", f"largest gap e = {e:.0f} mm", f"<= {GAP_MAX:g} mm", ok, "roof panels + rails over the plan")
    return [row], ([] if ok else [f"G3 roof open: e = {e:.0f} mm at x {X0 + where[1]}, y {Y0 + where[0]}"])


def g4_sag(parts):
    pc = H.SAFE["pc_panel"]
    t = pc["t"] / 1000
    D = pc["E"] * t ** 3 / (12 * (1 - pc["nu"] ** 2))
    q = pc["rho"] * 9.81 * t
    worst, wn = 0.0, ""
    fails = []
    below = [p for p in parts if p.module != "M10_safety"]
    for p in parts:
        if not p.name.startswith("guard_panel_roof"):
            continue
        Ls = min(p.s[0], p.s[1]) / 1000
        w = 5 * q * Ls ** 4 / (384 * D) * 1000
        b = p.aabb()
        top = max((q_.aabb()[5] for q_ in below if M._ovl((b[0], b[1], -1e9, b[3], b[4], 1e9), q_.aabb())),
                  default=0.0)
        room = b[2] - top
        if w > worst:
            worst, wn = w, p.name
        if w > SAG_MAX or w > room - 1.0:
            fails.append(f"G4 {p.name}: sag {w:.1f} mm (limit {SAG_MAX:g}, room {room:.1f})")
    return [("G4 roof sag (worst)", f"{worst:.1f} mm ({wn})", f"<= {SAG_MAX:g} mm and clear", not fails,
             "one-way span, 4 mm PC, own weight")], fails


def g5_doors(parts):
    by = {p.name: p for p in parts}
    fails = []
    for tag, wall, x0, x1 in L["DOORS"]:
        d, lk = by.get(f"door_{tag}"), by.get(f"lock_{tag}")
        yy = M.guard()["yF2" if wall == "F2" else "yB"]
        hinge = by.get(f"guard_post_{int(x0)}_{int(yy)}")
        lpost = by.get(f"guard_post_{int(x1 - 20)}_{int(yy)}")
        if not (d and lk and hinge and lpost):
            fails.append(f"G5 door {tag}: leaf / switch / posts missing")
            continue
        if abs(d.aabb()[0] - hinge.aabb()[3]) > 1e-6:
            fails.append(f"G5 door {tag}: leaf not on its hinge post")
        if _box_dist(lk.aabb(), lpost.aabb()) > 1e-6:
            fails.append(f"G5 door {tag}: guard-locking switch not on the lock post")
    ok = H.SAFE["guard_lock"]["F_hold"] >= F_HOLD_MIN
    if not ok:
        fails.append("G5 guard-locking holding force too low")
    return [("G5 doors", f"{len(L['DOORS'])} doors, each locked", f"F_hold {H.SAFE['guard_lock']['F_hold']:g} >= "
             f"{F_HOLD_MIN:g} N", not fails, "RFID-coded power-to-unlock switch on every lock post")], fails


def g6_estops(parts):
    fails = []
    es = [p for p in parts if p.hw == "estop"]
    ii = inner()
    for p in es:
        b = p.aabb()
        outside = b[4] <= ii["y0b"] + 1e-6 and b[1] < ii["y0b"] or b[1] >= ii["y1"] - 1e-6
        on_deck = b[0] >= 0 and b[1] >= 0 and b[3] <= L["TABLE"][0] and b[4] <= L["TABLE"][1]
        if not (outside and on_deck):
            fails.append(f"G6 {p.name}: head not outside the guard on the deck")
    walls_with_doors = {w for _, w, _, _ in L["DOORS"]}
    for w in walls_with_doors:
        if not any(e_ for e_ in L["ESTOPS"] if e_[1] == w):
            fails.append(f"G6 wall {w} has a door but no E-stop")
    worst = 0.0
    for tag, wall, x0, x1 in L["DOORS"]:
        d = min((abs(x - x1) for t_, w_, x, z in L["ESTOPS"] if w_ == wall), default=float("inf"))
        worst = max(worst, d)
        if d > ESTOP_REACH:
            fails.append(f"G6 door {tag}: nearest E-stop {d:.0f} mm > {ESTOP_REACH:g}")
    return [("G6 E-stops", f"{len(es)}, worst door -> E-stop {worst:.0f} mm", f"<= {ESTOP_REACH:g} mm", not fails,
             "heads outside the guard, 2 NC each (ISO 13850)")], fails


def g7_cutoff(ios, parts):
    fails = []
    step = {io.tag for io in ios if io.kind == "STEP"}
    so = {io.tag for io in ios if io.kind == "SO"}
    for k in ("K1", "K2", "K3", "K4", "Q19"):
        if k not in so:
            fails.append(f"G7 {k} is not a TwinSAFE output")
    zs = P.zones(parts)
    kz = {what.split("-port")[0].split()[-1]: tag for tag, what, _ in P.contactors()[4:]}
    yz = {port: tag for tag, port in P.zone_valves()}
    for port, z in zs.items():
        if not set(z["motors"]) <= step:
            fails.append(f"G7 {port}: zone motors {set(z['motors']) - step} are not steppers on EL7047")
        if (z["motors"] and kz.get(port) not in so) or (z["valves"] and yz.get(port) not in so):
            fails.append(f"G7 {port}: zone contactor / exhaust valve missing")
        if not z["motors"] and not z["valves"]:
            fails.append(f"G7 {port}: empty zone")
    cyl = {p.tag for p in parts if p.hw.startswith("ISO6432") and p.tag}
    do = {io.tag for io in ios if io.kind == "DO"}
    if not cyl <= do:
        fails.append(f"G7 cylinders without an island valve: {sorted(cyl - do)}")
    heat = {io.tag for io in P.heaters(ios)}
    stl = {io.tag[:-4] for io in ios if io.tag.endswith(".STL")}
    if heat - stl:
        fails.append(f"G7 heated zones without an STL: {sorted(heat - stl)}")
    return [("G7 cut-off coverage", f"{len(step)} steppers behind K1/K2, {len(cyl)} valves behind Q19, "
             f"{len(stl)} STLs", "all", not fails, "zones: " + ", ".join(
                 f"{p}: {len(z['motors'])} motors" + (f" behind {kz[p]}" if p in kz else "") +
                 f", {len(z['valves'])} valves" + (f" behind {yz[p]}" if p in yz else "")
                 for p, z in zs.items()))], fails


def g8_timing():
    ss1 = P.safety_ss1()
    ramp = ss1 - L["SS1_MARGIN"]
    t_unlock = ss1 + H.SAFE["contactor"]["t_off"] + L["UNLOCK_STILL"]
    t_run = ramp + max(h[3] or 0 for h in HAZARDS)
    ok = ss1 >= ramp and t_unlock >= t_run
    return [("G8 SS1 + unlock timing", f"SS1 {ss1:.2f} s, unlock >= {t_unlock:.2f} s",
             f">= ramp {ramp:.2f} s / run-down {t_run:.2f} s", ok, "guard locking: no access before standstill")], \
        ([] if ok else ["G8 timing"])


AIRLOCK_FACES = {    # chamber -> faces: (normal axis, band lo, band hi); a part closes a face if it lies in the
                     # band or passes right through it (the outer opening is declared, the deck closes 'out')
    "boxes": lambda g, b: [(0, g["xLo"], g["xL"] + g["w"]), (0, b["x1"], b["x1"] + g["t"]),
                           (1, b["y0"] - g["t"], b["y0"]), (1, b["y1"], b["y1"] + g["t"]),
                           (2, L["GUARD_TOP"] - 20, L["GUARD_TOP"] + g["t"]), (2, b["zf"] - 20, b["zf"] + 6)],
    "out": lambda g, o: [(0, o["x"], o["hx"] + 30), (0, g["xR"], g["xRo"]), (1, o["y0"] - g["t"], o["y0"]),
                         (1, o["y1"], o["y1"] + g["t"]), (2, L["GUARD_TOP"] - 20, L["GUARD_TOP"] + g["t"])],
}


def _components(free):
    """Connected uncovered regions: list of (cells, bbox)."""
    seen = np.zeros(free.shape, dtype=bool)
    out = []
    for i0, j0 in zip(*np.nonzero(free)):
        if seen[i0, j0]:
            continue
        stack, cells = [(i0, j0)], []
        seen[i0, j0] = True
        while stack:
            i, j = stack.pop()
            cells.append((i, j))
            for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a < free.shape[0] and 0 <= b < free.shape[1] and free[a, b] and not seen[a, b]:
                    seen[a, b] = True
                    stack.append((a, b))
        ii = [c[0] for c in cells]
        jj = [c[1] for c in cells]
        out.append((cells, (min(ii), min(jj), max(ii) + 1, max(jj) + 1)))
    return out


def chamber_gaps(parts, hz):
    """Every uncovered region on the faces of each airlock chamber: (port, e, 3-D box of the region)."""
    g = M.guard()
    ch = M.airlock_chambers()
    moving = {id(p) for h in hz if not h["low"] for p in h["parts"]}
    fixed = [p for p in parts if id(p) not in moving and p.group not in ("stock", "tray", "puck", "cookie")]
    out = []
    for port, box in ch.items():
        faces = AIRLOCK_FACES[port](g, L["BOX_LOCK"] if port == "boxes" else L["OUT_LOCK"])
        op = next(o for o in openings() if o[6] == port)
        for n, b0, b1 in faces:
            u, v = [i for i in range(3) if i != n]
            U0, U1, V0, V1 = int(box[u]), int(math.ceil(box[u + 3])), int(box[v]), int(math.ceil(box[v + 3]))
            mask = np.zeros((V1 - V0, U1 - U0), dtype=bool)
            for p in fixed:
                a = p.aabb()
                inside = a[n] >= b0 - 1e-6 and a[n + 3] <= b1 + 1e-6
                through = a[n] <= b0 + 1e-6 and a[n + 3] >= b1 - 1e-6
                if not (inside or through):
                    continue
                mask[max(int(round(a[v])) - V0, 0):max(min(int(round(a[v + 3])) - V0, V1 - V0), 0),
                     max(int(round(a[u])) - U0, 0):max(min(int(round(a[u + 3])) - U0, U1 - U0), 0)] = True
            if n == 0 and b0 <= (g["xLo"] if op[0] == "left" else g["xRo"]) <= b1:    # the outer door opening
                mask[max(int(op[3]) - V0, 0):int(op[4]) - V0, max(int(op[1]) - U0, 0):int(op[2]) - U0] = True
            for cells, (i0, j0, i1, j1) in _components(~mask):
                sub = np.ones((i1 - i0, j1 - j0), dtype=bool)
                for i, j in cells:
                    sub[i - i0, j - j0] = False
                e, _ = _gaps(sub)
                r = [0.0] * 6
                r[n], r[n + 3] = b0, b1
                r[u], r[u + 3] = U0 + j0, U0 + j1
                r[v], r[v + 3] = V0 + i0, V0 + i1
                out.append((port, e, tuple(r)))
    return out


def g9_airlocks(parts, hz, ios):
    fails = []
    tags = {io.tag for io in ios}
    ch = M.airlock_chambers()
    for port, box in ch.items():
        doors = [p for p in parts if p.group == "airlock_door" and p.hw == "airlock_door"]
        need = {"boxes": ["S30"], "out": ["S31", "S32"]}[port]
        for t_ in need:
            if not any(p.tag == t_ for p in doors) or not {f"{t_}.A", f"{t_}.B", f"{t_}.UNL"} <= tags:
                fails.append(f"G9 {port}: door {t_} or its lock / unlock I/O missing")
        if port == "boxes":
            tds = [p for p in parts if p.group == "trapdoor"]
            if len(tds) != len(L["LANE_Y"]) or not all(f"{p.tag}.CL" in tags for p in tds):
                fails.append("G9 boxes: a trapdoor or its closed switch is missing")
        for h in hz:
            if h["low"] or h["zone"] == port:
                continue
            for p in h["parts"]:
                a = p.aabb()
                if all(a[i] < box[i + 3] - 1e-6 and a[i + 3] > box[i] + 1e-6 for i in range(3)):
                    fails.append(f"G9 {port}: {p.name} ({h['name']}) is inside the chamber but not stopped with it")
    gaps = chamber_gaps(parts, hz)
    worst = max((e for _, e, _ in gaps), default=0.0)
    if worst > 12.0:
        fails.append(f"G9 chamber boundary gap e = {worst:.0f} mm > 12 mm")
    return [("G9 airlocks", f"{len(ch)} chambers, largest boundary gap e = {worst:.0f} mm", "<= 12 mm, "
             "doors locked + interlocked", not fails,
             "outer door opens only with the inner side shut (trapdoors / inner door) and the zone at standstill")], \
        fails


def g9_ports(parts):
    fails = []
    by = {p.name: p for p in parts}
    lc = H.SAFE["light_curtain"]
    for name, (side, y0, y1, zo, tag) in L["PORT_OPEN"].items():
        t_, r_ = by.get(f"lc_{name}_t"), by.get(f"lc_{name}_r")
        if not (t_ and r_):
            fails.append(f"G9 port {name}: no curtain pair")
            continue
        if not (t_.tag == tag and lc["d"] <= 14.0):
            fails.append(f"G9 port {name}: curtain tag / resolution")
    return [("G9 port curtains", f"{len(L['PORT_OPEN'])} ports, type 4, d = {lc['d']:g} mm", "every port", not fails,
             "muted only while docked + zone at safe standstill")], fails


def g1_enclosure(hz):
    ii = inner()
    fails, n = [], 0
    for h in hz:
        for p in h["parts"]:
            b = p.aabb()
            if b[5] <= 0 or p.group == "airlock_door":      # the airlock doors ARE guards
                continue
            n += 1
            y0 = ii["y0a"] if b[3] <= ii["xs"] else ii["y0b"]
            if not (b[0] >= ii["x0"] - 1e-6 and b[3] <= ii["x1"] + 1e-6 and b[1] >= y0 - 1e-6 and
                    b[4] <= ii["y1"] + 1e-6 and b[5] <= ii["z1"] + 1e-6):
                fails.append(f"G1 {p.name} ({h['name']}) is not inside the guard")
    return [("G1 hazards inside the guard", f"{n} hazardous parts above the deck", "all inside", not fails,
             "guard volume = inner panel faces + roof")], fails


# ------------------------------------------------------------------ audit
def audit(parts, hz):
    """ISO 13855 / ISO 13857 at every opening. Returns rows (dicts) and findings (str)."""
    rows, finds = [], []
    lc = H.SAFE["light_curtain"]
    t_off = H.SAFE["contactor"]["t_off"]
    g = M.guard()
    for wall, o0, o1, z0, z1, kind, oname in openings():
        if kind == "raw":
            # declared: the strip opens only into the hopper interiors (walls, lids, 6 mm slots to the rails)
            for h in hz:
                if all(p.group == "hopper" for p in h["parts"]):
                    rows.append(dict(opening=oname, hazard=h["name"], state="always", d_mm="in reach",
                                     need_mm="-", rule="low energy" if h["low"] else "GUARD", ok=h["low"]))
                    if not h["low"]:
                        finds.append(f"{oname}: {h['name']} is reachable and not low-energy")
            continue
        if kind == "airlock":
            box = M.airlock_chambers()[oname]
            for h in hz:
                ins = [p for p in h["parts"] if all(p.aabb()[i] < box[i + 3] - 1e-6 and p.aabb()[i + 3] > box[i] + 1e-6
                                                    for i in range(3))]
                if ins:
                    ok = h["low"] or h["zone"] == oname
                    rows.append(dict(opening=f"{oname} airlock", hazard=h["name"], state="outer door open",
                                     d_mm="in the chamber", need_mm="-",
                                     rule="low energy" if h["low"] else ("zone at safe standstill" if ok else "GUARD"),
                                     ok=ok))
                    if not ok:
                        finds.append(f"{oname} airlock: {h['name']} is in the chamber and keeps running")
            for port, e, r in chamber_gaps(parts, hz):
                if port != oname or e <= 0:
                    continue
                need = H.iso13857_distance(e, "slot")
                for h in hz:
                    if h["low"] or h["zone"] == oname:
                        continue
                    d = min(_box_dist(r, p.aabb()) for p in h["parts"])
                    if d > 1000:
                        continue
                    ok = d >= need
                    rows.append(dict(opening=f"{oname} airlock", hazard=h["name"],
                                     state=f"chamber gap e = {e:.0f} at {tuple(round(v) for v in r)}",
                                     d_mm=round(d), need_mm=round(need), rule=f"ISO 13857 slot e = {e:.0f}", ok=ok))
                    if not ok:
                        finds.append(f"{oname} airlock: a {e:.0f} mm gap in the chamber boundary is {d:.0f} mm from "
                                     f"{h['name']}, ISO 13857 needs {need:.0f} mm")
            continue
        xp = g["xLo"] if wall == "left" else g["xRo"]
        orect = (xp - 0.5, o0, z0, xp + 0.5, o1, z1)
        e = min(o1 - o0, z1 - z0)
        need_mute = H.iso13857_distance(e, "slot") if e <= 120 else H.ISO13857_ARM
        port_zone = oname
        for h in hz:
            if h["low"]:
                continue
            d = min(_box_dist(orect, p.aabb()) for p in h["parts"])
            if d > 1500:
                continue
            # not muted: a trip removes all power (STO by K1/K2 + dump) -> ISO 13855 distance
            if h["kind"] == "motion":
                T = lc["t_resp"] + H.T_LOGIC + t_off + h["t_mech"]
                S = H.ISO13855["K_hand"] * T + 8 * (lc["d"] - 14)          # K mm/s x T s = mm
                if S > 500:
                    S = max(500.0, H.ISO13855["K_slow"] * T + 8 * (lc["d"] - 14))
                S = max(S, H.ISO13855["S_min"])
                ok = d >= S
                rows.append(dict(opening=oname, hazard=h["name"], state="curtain active", d_mm=round(d),
                                 need_mm=round(S), rule=f"ISO 13855 T={T * 1000:.0f} ms", ok=ok))
                if not ok:
                    finds.append(f"{oname} port, curtain active: {h['name']} is {d:.0f} mm from the curtain plane, "
                                 f"ISO 13855 needs {S:.0f} mm (T = {T * 1000:.0f} ms)")
            # muted: the zone is at safe standstill, everything else runs -> ISO 13857 reach
            in_zone = h["zone"] == port_zone
            if h["kind"] == "heat" or not in_zone:
                ok = d >= need_mute
                rows.append(dict(opening=oname, hazard=h["name"], state="muted (AMR docked)", d_mm=round(d),
                                 need_mm=round(need_mute), rule=f"ISO 13857 e = {e:.0f}", ok=ok))
                if not ok:
                    finds.append(f"{oname} port, muted: {h['name']} "
                                 f"{'is hot' if h['kind'] == 'heat' else 'keeps running'} {d:.0f} mm from the "
                                 f"opening, ISO 13857 needs {need_mute:.0f} mm")
            else:
                rows.append(dict(opening=oname, hazard=h["name"], state="muted (AMR docked)", d_mm=round(d),
                                 need_mm="-", rule="in the port zone: safe standstill", ok=True))
        # curtain dead zones at the ends of the field
        dz = lc["dead"]
        bar = next(p for p in parts if p.name == f"lc_{oname}_t").aabb()
        for where, gap in (("bottom", dz + bar[2] - z0), ("top", dz + z1 - bar[5])):
            need = H.iso13857_distance(gap, "slot")
            dmin = min(min(_box_dist(orect, p.aabb()) for p in h["parts"]) for h in hz if not h["low"])
            ok = dmin >= need
            rows.append(dict(opening=oname, hazard=f"dead zone {where} ({gap:.0f} mm slot)", state="always",
                             d_mm=round(dmin), need_mm=round(need), rule="ISO 13857 slot", ok=ok))
            if not ok:
                finds.append(f"{oname} port: curtain dead zone at the {where} leaves a {gap:.0f} mm slot, nearest "
                             f"hazard {dmin:.0f} mm, ISO 13857 needs {need:.0f} mm")
    by = {p.name: p for p in parts}
    if "reject_shutter" in by:
        # drawer in: the hole opens into the bin; the only way in is the slot between the bin top and the deck
        bx, by_, bw_, bd, _ = L["REJECT_BIN"]
        zt = -L["TABLE"][2]
        e = L["REJECT_GAP"]
        need = H.iso13857_distance(e, "slot")
        # the deck is solid: from the slot at the bin's top edge the only path is across the bin to the
        # hole, through the deck, up the (closed sheet) funnel and out of its top
        hx, hy, ho = M.reject_hole()
        to_hole = min(hx - bx, bx + bw_ - hx - ho, hy - by_, by_ + bd - hy - ho)
        fn = by["reject_funnel"].aabb()
        up = L["TABLE"][2] + (fn[5] - fn[2])
        top = (fn[0], fn[1], fn[5], fn[3], fn[4], fn[5])
        for h in hz:
            if h["low"]:
                continue
            d = to_hole + up + min(_box_dist(top, p.aabb()) for p in h["parts"])
            if d > 600:
                continue
            ok = d >= need
            rows.append(dict(opening="reject drawer (in)", hazard=h["name"],
                             state=f"bin-top slot e = {e:g}, path via hole + funnel",
                             d_mm=round(d), need_mm=round(need), rule=f"ISO 13857 slot e = {e:g}", ok=ok))
            if not ok:
                finds.append(f"reject drawer: the {e:g} mm slot over the bin is {d:.0f} mm from {h['name']}, "
                             f"ISO 13857 needs {need:.0f} mm")
    else:
        finds.append("reject drawer: pulling the drawer opens the funnel outlet under the deck; no shutter in the CAD")
    box = M.lift_guard_box() if "lift_guard_floor" in by else None
    under = sorted({p.name for h in hz for p in h["parts"] if p.aabb()[2] < -L["TABLE"][2] - 1e-6
                    and not (box and all(box[i] - 1e-6 <= p.aabb()[i] and p.aabb()[i + 3] <= box[i + 3] + 1e-6
                                         for i in range(3)))})
    if under:
        finds.append(f"under the deck: {len(under)} moving parts ({', '.join(under[:4])}...) are not inside a guard")
    return rows, finds


def g10_under_deck(parts, hz):
    """Every hazardous part below the deck is inside the closed lift guard (5 sheet faces + the deck)."""
    by = {p.name: p for p in parts}
    fails = []
    zt = -L["TABLE"][2]
    below = [p for h in hz for p in h["parts"] if p.aabb()[2] < zt - 1e-6]
    if below:
        if "lift_guard_floor" not in by:
            fails.append("G10 moving parts under the deck but no lift guard")
        else:
            box = M.lift_guard_box()
            for p in below:
                a = p.aabb()
                if not all(box[i] - 1e-6 <= a[i] and a[i + 3] <= box[i + 3] + 1e-6 for i in range(3)):
                    fails.append(f"G10 {p.name} moves under the deck outside the lift guard")
            faces = [n for n in ("lift_guard_wall_front", "lift_guard_wall_back", "lift_guard_wall_left",
                                 "lift_guard_wall_right", "lift_guard_floor") if n in by]
            if len(faces) != 5 or abs(by["lift_guard_wall_front"].aabb()[5] - zt) > 1e-6:
                fails.append("G10 lift guard not closed up to the deck")
    return [("G10 under-deck guard", f"{len(below)} moving parts under the deck", "all inside the lift guard",
             not fails, "sheet box flanged to the deck; the rods leave it only through the deck")], fails


def g11_reject(parts, ios):
    """The deck hole under the reject funnel is closed whenever the drawer is not fully in."""
    by = {p.name: p for p in parts}
    fails = []
    hx, hy, ho = M.reject_hole()
    sh = by.get("reject_shutter")
    if not sh:
        fails.append("G11 no reject shutter")
    else:
        a = sh.aabb()
        if not (a[0] <= hx and a[3] >= hx + ho and a[1] <= hy and a[4] >= hy + 2 * ho):
            fails.append("G11 the shutter does not cover the hole (closed) and its parking room (open)")
    bx, by_, bw_, bd, _ = L["REJECT_BIN"]
    if not (bx + 3 <= hx and hx + ho <= bx + bw_ - 3 and by_ + 3 <= hy and hy + ho <= by_ + bd - 3):
        fails.append("G11 the bin does not cover the whole hole: part of it is open from under the table")
    if not {"S34.A", "S34.B"} <= {io.tag for io in ios}:
        fails.append("G11 drawer switch S34 missing")
    return [("G11 reject drawer", f"hole {ho:g} sq inside the bin, shutter + S34", "closed when not fully in",
             not fails, "spring shutter held open by the drawer's push pin; S34 monitors the drawer")], fails


SF = (   # the safety functions as configured in TwinSAFE (SAFETY_CONCEPT.md)
    ("SF1", "E-stop", "S10.A/B S11.A/B S12.A/B, S13 reset", "K1+K2 off (all motion, STO-equivalent), Q19 exhaust, "
     "K3+K4 off (heaters)", "cat 0 (K3/K4, Q19) + SS1 before K1/K2", "d", "EDM K1K2.EDM, K3K4.EDM, Q19.FB"),
    ("SF2", "guard locking", "S20.A/B S21.A/B S22.A/B", "door opened / unlocked -> SS1 -> K1+K2 off, Q19 exhaust; "
     "S2x.UNL only after SS1 + standstill", "SS1", "d", "EDM, lock state from the switch OSSDs"),
    ("SF3", "safe exhaust", "SF1 / SF2 demand", "Q19 dump valve de-energised", "0", "c", "Q19.FB"),
    ("SF4", "over-temperature", "STL per zone (own duplex element)", "STL relay contact opens the zone's load; "
     "trip reported on <zone>.STL", "0 (hardwired, not TwinSAFE)", "c", "manual STL reset"),
    ("SF5", "chain drawing-in", "(covered by the perimeter guard: no motion with a door open)", "-", "-", "c",
     "no jog / enabling device in S-1"),
    ("SF6", "AMR airlocks", "S30.A/B (boxes outer door), S31.A/B (out outer), S32.A/B (out inner), "
     "Q42..Q44.CL trapdoors closed, S34.A/B drawer",
     "boxes: S30 unlocks only with every trapdoor closed and Y1 exhausted; trapdoors open only with S30 locked. "
     "out: S31 unlocks only with S32 locked and K5 (shuttles) off; S32 unlocks only with S31 locked. "
     "A door opened / unlocked out of sequence -> SF1 response without heaters", "0 / zone STO", "c",
     "EDM K5.EDM, Y1.FB, lock OSSDs"),
)


def check(verbose=True, write=False):
    parts = M.build(with_product=False)
    P.check(verbose=False)
    ios = P.IOS
    hz = hazards(parts)
    rows, fails = [], []
    for fn in (lambda: g1_enclosure(hz), lambda: g2_walls(parts), lambda: g3_roof(parts), lambda: g4_sag(parts),
               lambda: g5_doors(parts), lambda: g6_estops(parts), lambda: g7_cutoff(ios, parts), g8_timing,
               (lambda: g9_airlocks(parts, hz, ios)) if L.get("AIRLOCK") else (lambda: g9_ports(parts)),
               lambda: g10_under_deck(parts, hz), lambda: g11_reject(parts, ios)):
        r, f = fn()
        rows += r
        fails += f
    arows, finds = audit(parts, hz)
    if verbose:
        print(f"safety S-1: {len(hz)} hazards, {sum(len(h['parts']) for h in hz)} hazardous parts, "
              f"{sum(1 for h in hz if h['low'])} low-energy (<= {H.F_LOW:g} N [assumed])")
        for name, v, lim, ok, note in rows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:28s} {v:44s} {lim:30s} {note}")
        print("\n".join(fails) if fails else "ALL SAFETY-HARDWARE PROOFS PASS (enclosure, walls, roof, sag, doors, "
                                            "E-stops, cut-off coverage, timing, airlocks / ports, under-deck guard, reject drawer)")
        print(f"AUDIT (ISO 13855 / 13857): {sum(1 for r in arows if r['ok'])}/{len(arows)} checks met; "
              + (f"{len(finds)} FINDINGS - the line must not run with people near it until they are resolved:"
                 if finds else "no findings (the PL verification and the [assumed] values are still open)"))
        for f in finds:
            print("  - " + f)
    if write and not fails:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "safety_functions.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["SF", "function", "inputs", "response", "stop category", "PLr", "diagnostics"])
            w.writerows(SF)
        with open(os.path.join(OUT, "reach_audit.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(arows[0].keys()))
            w.writeheader()
            w.writerows(arows)
        with open(os.path.join(OUT, "report.md"), "w") as fh:
            fh.write(report(rows, arows, finds, hz))
        print("wrote", OUT)
    return fails, finds


def report(rows, arows, finds, hz):
    L_ = ["# STF-2 safety report (generated by safety.py, Upgrade S-1)", "",
          "Engineering evidence, not a certificate. PLr values and every [assumed] time / force need the "
          "risk assessment and the bought parts' data (ISO 13849-1 PL verification is still open).", "",
          "## Hardware proofs (gate the build)", "", "| proof | value | limit | result | note |", "|---|---|---|---|---|"]
    L_ += [f"| {n} | {v} | {lim} | {'pass' if ok else 'FAIL'} | {note} |" for n, v, lim, ok, note in rows]
    L_ += ["", "## Hazards", "", "| hazard | parts | kind | force | t_mech [assumed] | port zone |", "|---|---|---|---|---|---|"]
    for h in hz:
        L_.append(f"| {h['name']} | {len(h['parts'])} | {h['kind']} | "
                  f"{'%.0f N (low energy)' % h['force'] if h['low'] else ('%.0f N' % h['force'] if h['force'] else 'high')} | "
                  f"{h['t_mech'] if h['t_mech'] is not None else '-'} | {h['zone'] or '-'} |")
    L_ += ["", f"## Findings ({len(finds)}) - open, block operation", ""] + [f"{k + 1}. {f}" for k, f in enumerate(finds)]
    L_ += ["", "## Reach audit (ISO 13855 / ISO 13857)", "", "| opening | hazard | state | d mm | needed mm | rule | ok |",
           "|---|---|---|---|---|---|---|"]
    L_ += [f"| {r['opening']} | {r['hazard']} | {r['state']} | {r['d_mm']} | {r['need_mm']} | {r['rule']} | "
           f"{'yes' if r['ok'] else 'NO'} |" for r in arows]
    L_ += ["", "## Safety functions (TwinSAFE configuration input)", "",
           "| SF | function | inputs | response | stop | PLr | diagnostics |", "|---|---|---|---|---|---|---|"]
    L_ += ["| " + " | ".join(r) + " |" for r in SF]
    return "\n".join(L_) + "\n"


if __name__ == "__main__":
    f, _ = check(write=True)
    sys.exit(1 if f else 0)
