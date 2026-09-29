"""
Upgrade 2 - machine safety (STF_VARIANT=up2, on top of Upgrade 1).

  1. RISK ASSESSMENT (ISO 12100 / ISO 13849-1 risk graph). Every hazard is a
     ZONE computed from the models - the swept envelope of the moving parts over
     their full joint ranges, never a guessed box - graded S/F/P -> PLr.
  2. GUARD. A closed enclosure round the table: 30x30 aluminium profile frame,
     4 mm polycarbonate panels, a polycarbonate roof, three hinged doors with
     interlock switches WITH GUARD LOCKING. Locking is the design choice that
     matters: a door cannot open until the machine has stopped, so no stopping
     time has to be measured to place the guard (ISO 14119). A light curtain
     would need S = K*T + C from a measured stop time T; that is noted, not used.
  3. SAFETY CIRCUIT. Three E-stops and three door switches, all dual-channel, in
     series into a safety relay (monitored manual reset, EDM feedback). Its two
     outputs drive force-guided contactors K1/K2 that switch the ACTUATOR 24 V
     (motors, valves) and the safe exhaust valve Y1 that cuts and vents the air.
     Sensors stay powered, so the PLC still sees where everything stopped.
  4. PROOFS.
     reach   every moving part's swept envelope lies inside the guard, with
             clearance to every panel (the VGR sampled over its whole range)
     fit     no guard part touches any machine part
     logic   exhaustive over every input state: motion is enabled ONLY with all
             E-stops released, all doors closed and locked, and a reset given
             after the last trip; a door unlocks ONLY at standstill; any single
             channel fault (the two channels of one device disagreeing) blocks
             enable - Category 3 single-fault tolerance
     air     every cylinder's supply path passes through Y1 (graph reachability)

Dimensions of ft-scale safety devices are assumed; the PL achieved needs the
devices' MTTFd / DC data and is reported as a target, not a claim.
"""
import itertools
import math
from dataclasses import dataclass

from variant import UP2

GAP = 25.0            # guard inner face to table edge
POST = 30.0           # 30x30 slotted aluminium profile
PANEL_T = 4.0         # polycarbonate
Z_BOT = -30.0         # the frame clamps to the table frame, below its top
H = 900.0             # guard height above the plate tops (z = 0)
CLEAR_MIN = 20.0      # a swept envelope must stay this far inside a panel

# ISO 13849-1 risk graph: (S, F, P) -> PLr
RISK_GRAPH = {("S1", "F1", "P1"): "a", ("S1", "F1", "P2"): "b", ("S1", "F2", "P1"): "b",
              ("S1", "F2", "P2"): "c", ("S2", "F1", "P1"): "c", ("S2", "F1", "P2"): "d",
              ("S2", "F2", "P1"): "d", ("S2", "F2", "P2"): "e"}


@dataclass
class Part:
    name: str
    group: str
    kind: str
    p: tuple
    s: tuple
    colour: str = "grey"
    support: str = "plate"
    frame: str = "world"
    tag: str = ""
    mech: str = ""
    note: str = ""

    def local_aabb(self):
        x, y, z = self.p
        if self.kind == "box":
            dx, dy, dz = self.s
            return (x, y, z, x + dx, y + dy, z + dz)
        ax, L, d = self.s
        return (x - d / 2, y - d / 2, z, x + d / 2, y + d / 2, z + L)


def table():
    import factory_layout as FL
    return FL.PLATE[0], FL.PLATE[1]


def outline():
    """Guard inner rectangle (x0, y0, x1, y1): the table edge + GAP."""
    TX, TY = table()
    return (-GAP, -GAP, TX + GAP, TY + GAP)


# ------------------------------------------------------------ hazard zones
def _hbw_zone():
    import factory_layout as FL, hbw_model as HM
    lo, hi = [1e9] * 3, [-1e9] * 3
    t0, t1 = HM.P["TRAVEL"]; l0, l1 = HM.P["LIFT"]; f0, f1 = HM.P["FORK"]
    for tv, lz, fk in itertools.product((t0, t1), (l0, l1), (f0, f1)):
        for p in HM.build(tv, lz, fk):
            if not p.joint:
                continue
            a = p.aabb()
            c0, c1 = FL.to_factory(a[0], a[1]), FL.to_factory(a[3], a[4])
            for i, v in enumerate((min(c0[0], c1[0]), min(c0[1], c1[1]), a[2])):
                lo[i] = min(lo[i], v)
            for i, v in enumerate((max(c0[0], c1[0]), max(c0[1], c1[1]), a[5])):
                hi[i] = max(hi[i], v)
    return lo + hi


def _vgr_zone(step=5.0):
    """The VGR arm swept over swivel x reach x plunge: a cylinder about the
    tower (the rear of the retracted arm reaches ~550 mm behind it)."""
    import factory_layout as FL, vgr_model as VG, vgr_path as VP
    tx, ty = FL.vgr_tower()
    s0, s1 = VG.V["SWIVEL"]; r0, r1 = VG.V["REACH"]; p0, p1 = VG.V["PLUNGE"]
    rmax, z0, z1, pts = 0.0, 1e9, -1e9, []
    sw = s0
    while sw <= s1 + 1e-6:
        for rr in (r0, r1):
            for pz in (p0, p1):
                for name, c, h, ang, za, zb in VP.moving_parts(sw, pz, rr, carrying=True):
                    t = math.radians(ang)
                    for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                        x = c[0] + sx * h[0] * math.cos(t) - sy * h[1] * math.sin(t)
                        y = c[1] + sx * h[0] * math.sin(t) + sy * h[1] * math.cos(t)
                        pts.append((x, y))
                        rmax = max(rmax, math.hypot(x - tx, y - ty))
                    z0, z1 = min(z0, za), max(z1, zb)
        sw += step
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    # the swept outline: the farthest point in every 5 deg bin round the tower
    # (the head reaches further forward than the retracted arm's rear does)
    rb = [0.0] * 72
    for x, y in pts:
        k = int((math.degrees(math.atan2(y - ty, x - tx)) % 360) // 5)
        rb[k] = max(rb[k], math.hypot(x - tx, y - ty))
    poly = []
    for k, r in enumerate(rb):
        for a in (k * 5.0, k * 5.0 + 5.0):          # hold the bin radius across the bin
            t = math.radians(a)
            poly.append([round(tx + r * math.cos(t), 1), round(ty + r * math.sin(t), 1)])
    return {"centre": [tx, ty], "r": rmax, "z": [z0, z1], "poly": poly,
            "swept_box": [min(xs), min(ys), z0, max(xs), max(ys), z1]}


def _oven_zones():
    import factory_layout as FL, oven_model as OM
    q = OM.O
    groups = {"slider": "Ofenschieber + tray", "door": "Ofentuer", "turn": "Drehtisch + Saege",
              "sauger": "Sauger", "lower": "Sauger", "push": "Auswerfer"}
    boxes = {}
    for sl in q["SLIDER"]:
        for dr in q["DOOR_Z"]:
            for tn in (0.0, -90.0, -180.0):
                for sa in q["SAUGER"]:
                    for lw in q["LOWER"]:
                        for pu in q["PUSH"]:
                            for p in OM.build(sl, dr, tn, sa, lw, pu):
                                if p.frame == "world" and p.group not in ("saw",):
                                    continue
                                key = groups.get(p.frame, "Drehtisch + Saege")
                                b = FL.oven_box(p.local_aabb())
                                o = boxes.setdefault(key, list(b))
                                for i in range(3):
                                    o[i] = min(o[i], b[i]); o[i + 3] = max(o[i + 3], b[i + 3])
    return boxes


def _sorting_zone():
    import factory_layout as FL, sorting_model as SM
    lo, hi = [1e9] * 3, [-1e9] * 3
    e1 = SM.S["EJECT"][1]
    for push in ((0, 0, 0), (e1, 0, 0), (0, e1, 0), (0, 0, e1)):
        for p in SM.build(push):
            if not p.frame.startswith("push"):
                continue
            a = p.local_aabb()
            c0, c1 = FL.to_factory_sort(a[0], a[1]), FL.to_factory_sort(a[3], a[4])
            for i, v in enumerate((min(c0[0], c1[0]), min(c0[1], c1[1]), a[2])):
                lo[i] = min(lo[i], v)
            for i, v in enumerate((max(c0[0], c1[0]), max(c0[1], c1[1]), a[5])):
                hi[i] = max(hi[i], v)
    return lo + hi


def hazards():
    """Every hazard: where (a zone from the models), what, and its PLr."""
    vz = _vgr_zone()
    ov = _oven_zones()
    rows = [
        {"id": "H1", "name": "HBW stacker crane", "what": "crushing / shearing between the moving "
         "mast, carriage and fork and the rack", "zone": _hbw_zone(), "S": "S2", "F": "F1", "P": "P2"},
        {"id": "H2", "name": "VGR swivel arm", "what": "impact / crushing by the swinging arm (260 deg, "
         f"r {vz['r']:.0f} mm incl. the rear of the retracted arm)", "zone": vz["swept_box"],
         "cyl": {"centre": vz["centre"], "r": vz["r"], "z": vz["z"], "poly": vz["poly"]},
         "S": "S2", "F": "F1", "P": "P2"},
        {"id": "H3", "name": "Oven: Ofenschieber, door", "what": "pinch at the door and the tray mouth",
         "zone": _merge(ov.get("Ofenschieber + tray"), ov.get("Ofentuer")), "S": "S1", "F": "F2", "P": "P1"},
        {"id": "H4", "name": "Oven: Drehtisch, Saege, Sauger", "what": "entanglement at the turntable, "
         "cut at the saw, crushing under the Sauger stroke",
         "zone": _merge(ov.get("Drehtisch + Saege"), ov.get("Sauger")), "S": "S2", "F": "F1", "P": "P1"},
        {"id": "H5", "name": "Oven: Auswerfer", "what": "impact of the pneumatic pusher",
         "zone": ov.get("Auswerfer"), "S": "S1", "F": "F2", "P": "P1"},
        {"id": "H6", "name": "Sorting ejectors", "what": "impact of three pneumatic ejectors",
         "zone": _sorting_zone(), "S": "S1", "F": "F2", "P": "P1"},
        {"id": "H7", "name": "Stored air", "what": "unexpected cylinder motion from residual pressure "
         "after a stop", "zone": None, "S": "S1", "F": "F1", "P": "P2"},
    ]
    for r in rows:
        r["PLr"] = RISK_GRAPH[(r["S"], r["F"], r["P"])]
        if r["zone"]:
            r["zone"] = [round(v, 1) for v in r["zone"]]
    return rows


def _merge(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return [min(a[i], b[i]) for i in range(3)] + [max(a[i + 3], b[i + 3]) for i in range(3)]


# ------------------------------------------------------------------- guard
DOORS = {
    # wall, span along the wall (y for the front/back walls), what it gives access to
    "A": ("front", (60.0, 700.0), "oven + PLC cabinet"),
    "B": ("front", (780.0, 1440.0), "sorting line"),
    "C": ("back", (200.0, 960.0), "HBW service"),
}


def _posts_along(a, b, doors, P=POST, span=800.0):
    """Post positions (low edge) on a wall running a..b: both ends, both jambs
    of every door, and enough in between that no bay is wider than `span`.
    Returns (posts, bays) - bays are (lo, hi, door_id or None)."""
    fixed = {a, b - P}
    for nm, (lo, hi) in doors.items():
        fixed |= {lo - P, hi}
    pts = sorted(fixed)
    posts = []
    for k, q in enumerate(pts):
        posts.append(q)
        if k + 1 < len(pts):
            lo, hi = q + P, pts[k + 1]
            if any(abs(lo - d[0]) < 1e-6 and abs(hi - d[1]) < 1e-6 for d in doors.values()):
                continue
            n = math.ceil((hi - lo) / span)
            for m in range(1, n):
                posts.append(lo + m * (hi - lo + P) / n - P / 2)
    posts = sorted(posts)
    bays = []
    for k in range(len(posts) - 1):
        lo, hi = posts[k] + P, posts[k + 1]
        door = next((nm for nm, d in doors.items() if abs(lo - d[0]) < 1e-6 and abs(hi - d[1]) < 1e-6), None)
        if hi - lo > 1:
            bays.append((lo, hi, door))
    return posts, bays


def guard_parts():
    """The enclosure in FACTORY coordinates. Front wall = the table's front
    edge (x < 0), back wall behind the HBW (x > table), right wall y < 0,
    left wall y > table."""
    out = []; A = out.append
    x0, y0, x1, y1 = outline()
    P = POST
    xo0, yo0, xo1, yo1 = x0 - P, y0 - P, x1 + P, y1 + P
    z0, z1 = Z_BOT, H
    mid = P / 2 - PANEL_T / 2
    zp0, zp1 = z0 + P, z1
    walls = {
        "front": ("x", xo0, {nm: d[1] for nm, d in DOORS.items() if d[0] == "front"}),
        "back": ("x", x1, {nm: d[1] for nm, d in DOORS.items() if d[0] == "back"}),
    }
    k = 0
    for wall, (_, xw, doors) in walls.items():
        posts, bays = _posts_along(yo0, yo1, doors)
        for y in posts:
            k += 1
            A(Part(f"guard_post_{k}", "guard", "box", (xw, y, z0), (P, P, z1 - z0 + P), "alu", "table",
                   mech="profile:30", note=f"30x30 slotted aluminium profile, {wall} wall"))
        for i, (lo, hi, door) in enumerate(bays):
            if door:
                continue
            A(Part(f"guard_panel_{wall}_{i + 1}", "guard", "box", (xw + mid, lo, zp0),
                   (PANEL_T, hi - lo, zp1 - zp0), "polycarb", f"guard_post_{k}", mech="panel",
                   note="4 mm polycarbonate, no openings - nothing to reach through (ISO 13857)"))
    for wall, yw in (("right", yo0), ("left", y1)):
        posts, bays = _posts_along(xo0 + P, x1, {})
        for x in posts[1:-1] if len(posts) > 2 else []:
            k += 1
            A(Part(f"guard_post_{k}", "guard", "box", (x, yw, z0), (P, P, z1 - z0 + P), "alu", "table",
                   mech="profile:30", note=f"30x30 slotted aluminium profile, {wall} wall"))
        for i, (lo, hi, _) in enumerate(bays):
            A(Part(f"guard_panel_{wall}_{i + 1}", "guard", "box", (lo, yw + mid, zp0),
                   (hi - lo, PANEL_T, zp1 - zp0), "polycarb", "guard_post_1", mech="panel",
                   note="4 mm polycarbonate, no openings"))
    for nm, zz in (("bot", z0), ("top", z1)):
        A(Part(f"guard_rail_{nm}_front", "guard", "box", (xo0, yo0 + P, zz), (P, yo1 - yo0 - 2 * P, P),
               "alu", "guard_post_1", mech="profile:30"))
        A(Part(f"guard_rail_{nm}_back", "guard", "box", (x1, yo0 + P, zz), (P, yo1 - yo0 - 2 * P, P),
               "alu", "guard_post_1", mech="profile:30"))
        A(Part(f"guard_rail_{nm}_right", "guard", "box", (xo0 + P, yo0, zz), (xo1 - xo0 - 2 * P, P, P),
               "alu", "guard_post_1", mech="profile:30"))
        A(Part(f"guard_rail_{nm}_left", "guard", "box", (xo0 + P, y1, zz), (xo1 - xo0 - 2 * P, P, P),
               "alu", "guard_post_1", mech="profile:30"))
    A(Part("guard_roof", "guard", "box", (xo0, yo0, z1 + P), (xo1 - xo0, yo1 - yo0, PANEL_T),
           "polycarb", "guard_rail_top_front", mech="panel",
           note="polycarbonate roof: closes the top, so there is no reach-over"))
    for nm, (wall, (a, b), what) in DOORS.items():
        xw = xo0 if wall == "front" else x1
        out_x = xw - 22 if wall == "front" else xw + P          # handle / switch sit OUTSIDE
        A(Part(f"door_{nm}_panel", "guard", "box", (xw + mid, a + 2, zp0 + 5), (PANEL_T, b - a - 4, zp1 - zp0 - 10),
               "polycarb", f"guard_rail_bot_{wall}", mech="panel", note=f"hinged door {nm}: {what}"))
        A(Part(f"door_{nm}_handle", "guard", "box", (out_x, b - 70, 420), (22, 20, 120), "black",
               f"door_{nm}_panel", note="door handle"))
        A(Part(f"DS{nm}_door_switch", "guard", "box", (xw - 36 if wall == "front" else xw + P, b + 2, 520),
               (36, 26, 90), "yellow", "guard_post_1", tag=f"S{nm}",
               note=f"door {nm}: interlock switch WITH GUARD LOCKING (solenoid), 2 NC channels + lock "
                    "monitoring - the door stays locked until standstill"))
    estops = (("ES1", "front", 15.0, "front right corner"), ("ES2", "front", 1470.0, "front left corner"),
              ("ES3", "back", 1000.0, "back, beside the HBW service door"))
    for nm, wall, y, where in estops:
        xw = xo0 - 40 if wall == "front" else x1 + P
        A(Part(f"{nm}_estop_box", "guard", "box", (xw, y - 25, 560), (40, 50, 50), "yellow",
               "guard_post_1", tag=nm, note=f"E-stop ({where}): ISO 13850, 2 NC channels, positive opening"))
        bx = xw - 14 if wall == "front" else xw + 40
        A(Part(f"{nm}_estop_button", "guard", "cyl", (bx, y, 585), ("x", 14, 40), "estop",
               f"{nm}_estop_box", note="red mushroom head on yellow"))
    A(Part("S3_reset", "guard", "box", (xo0 - 30, 740.0, 560), (30, 30, 30), "blue", "guard_post_1",
           tag="S3", note="blue reset button outside the guard, with a view of the whole cell "
                          "(monitored: acts on the falling edge)"))
    return out


# ------------------------------------------------------------------ circuit
def circuit():
    """The safety circuit as a netlist the blueprint draws and the logic proof
    reads. Devices are dual-channel; the chain is in series per channel."""
    devs = [("ES1", "E-stop front right"), ("ES2", "E-stop front left"), ("ES3", "E-stop back"),
            ("SA", "door A (oven + PLC)"), ("SB", "door B (sorting)"), ("SC", "door C (HBW)")]
    return {
        "inputs": [{"id": d, "label": l, "channels": ["CH1", "CH2"], "kind": "estop" if d.startswith("ES") else "door"}
                   for d, l in devs],
        "reset": {"id": "S3", "label": "reset (monitored, falling edge)"},
        "relay": {"id": "K0", "label": "safety relay: 2-channel, cross-monitoring, EDM"},
        "outputs": [{"id": "K1", "label": "contactor K1: actuator +24 V, channel 1"},
                    {"id": "K2", "label": "contactor K2: actuator +24 V, channel 2"},
                    {"id": "Y1", "label": "safe exhaust valve: air supply + vent"}],
        "edm": "NC mirror contacts of K1 and K2 in series into the relay's feedback loop",
        "locking": "door locks released only by the PLC's standstill signal (all axes stopped, 0 V on the actuator bus)",
        "switched": "actuator 24 V: all motor relays and all solenoid valves; sensors stay powered",
    }


def enable(state):
    """The safety relay's truth: may the actuator supply be ON?
    state: estop_ok[ch][dev], door_closed[ch][dev], locked[dev], reset_since_trip."""
    for ch in (0, 1):
        if not all(state["estop_ok"][ch]) or not all(state["door_closed"][ch]):
            return False
    for d in range(len(state["door_closed"][0])):
        if state["door_closed"][0][d] != state["door_closed"][1][d]:
            return False                  # cross-monitoring: channels must agree
    for e in range(len(state["estop_ok"][0])):
        if state["estop_ok"][0][e] != state["estop_ok"][1][e]:
            return False
    return all(state["locked"]) and state["reset_since_trip"] and state["edm_closed"]


def unlock_allowed(state):
    return state["standstill"]


def check_logic():
    """Exhaustive: every combination of E-stop, door, lock, reset, EDM states."""
    fails, n = [], 0
    ne, nd = 3, 3
    bools = (False, True)
    for es in itertools.product(bools, repeat=ne):
        for dc in itertools.product(bools, repeat=nd):
            for lk in itertools.product(bools, repeat=nd):
                for rs, edm in itertools.product(bools, bools):
                    # healthy channels agree
                    st = {"estop_ok": [list(es), list(es)], "door_closed": [list(dc), list(dc)],
                          "locked": list(lk), "reset_since_trip": rs, "edm_closed": edm}
                    n += 1
                    on = enable(st)
                    must = all(es) and all(dc) and all(lk) and rs and edm
                    if on != must:
                        fails.append(f"LOGIC enable={on} for {st}")
                    # every single-channel fault: one channel of one device flipped
                    for kind, cnt in (("estop_ok", ne), ("door_closed", nd)):
                        for i in range(cnt):
                            for ch in (0, 1):
                                f = {k: ([row[:] for row in v] if k in ("estop_ok", "door_closed") else v)
                                     for k, v in st.items()}
                                f[kind][ch][i] = not f[kind][ch][i]
                                n += 1
                                if enable(f):
                                    fails.append(f"SINGLE FAULT {kind}[{ch}][{i}] still enables")
    for ss in (False, True):
        n += 1
        if unlock_allowed({"standstill": ss}) != ss:
            fails.append("a door may unlock while the machine moves")
    return fails, n


def pneumatic_graph():
    """Directed air network: source -> ... -> every cylinder."""
    import oven_model as OM, sorting_model as SM
    g = {"Q10_central_compressor": ["air_tank"], "air_tank": ["air_frl"], "air_frl": ["air_safe_exhaust"],
         "air_safe_exhaust": ["air_lockout_valve"], "air_lockout_valve": ["air_manifold"],
         "air_manifold": ["oven_valves", "sorting_valves", "vgr_valves"]}
    g["oven_valves"] = [p.name for p in OM.build() if "cylinder" in p.name and "vacuum" not in p.name]
    g["oven_valves"] += ["vacuum_cylinder_a", "vacuum_cylinder_b"]
    g["sorting_valves"] = [p.name for p in SM.build() if "cylinder" in p.name]
    g["vgr_valves"] = ["vgr_vacuum_valve"]
    return g


def check_air():
    g = pneumatic_graph()
    leaves = [c for v in g.values() for c in v if c not in g]
    fails = []

    def paths(node, target, seen=()):
        if node == target:
            return [[node]]
        out = []
        for n in g.get(node, []):
            if n not in seen:
                out += [[node] + p for p in paths(n, target, seen + (node,))]
        return out
    for leaf in leaves:
        ps = paths("Q10_central_compressor", leaf)
        if not ps:
            fails.append(f"AIR {leaf} not fed from the central supply")
        for p in ps:
            if "air_safe_exhaust" not in p:
                fails.append(f"AIR {leaf} fed around the safe exhaust valve: {' > '.join(p)}")
    return fails, leaves


# ------------------------------------------------------------------ checks
def _inside(zone, clr):
    x0, y0, x1, y1 = outline()
    return (zone[0] >= x0 + clr and zone[1] >= y0 + clr and zone[3] <= x1 - clr and zone[4] <= y1 - clr
            and zone[5] <= H - clr)


def check(verbose=True):
    import factory_layout as FL, upgrade as U, plc_model as PM
    fails = []
    hz = hazards()
    for h in hz:
        if h["zone"] and not _inside(h["zone"], CLEAR_MIN):
            fails.append(f"REACH {h['id']} {h['name']}: swept zone {h['zone']} is not {CLEAR_MIN} mm inside the guard")
        cyl = h.get("cyl")
        if cyl:
            cx, cy = cyl["centre"]; r = cyl["r"]
            x0, y0, x1, y1 = outline()
            # the swept POINTS (not the full circle - the arm never swings through +Y)
            if not _inside(h["zone"], CLEAR_MIN):
                fails.append(f"REACH {h['id']}: arm sweep leaves the guard")
    # fit: nothing of the guard touches the machine
    guard = [(p, p.local_aabb()) for p in guard_parts()]
    machine = []
    for rect in (FL.module_rect(), FL.vgr_rect(), FL.oven_rect(), FL.sort_rect(), FL.plc_rect(),
                 *U.rects().values()):
        x, y, w, d = rect
        machine.append((x, y, -10.0, x + w, y + d, 800.0))
    for p, a in guard:
        for m in machine:
            d = [min(a[i + 3], m[i + 3]) - max(a[i], m[i]) for i in range(3)]
            if min(d) > 0.05:
                fails.append(f"FIT {p.name} intrudes into a module footprint")
    # every safety device is on the guard or in the cabinet
    names = {p.name for p in PM.build()}
    for need in ("safety_relay_K0", "contactor_K1", "contactor_K2"):
        if need not in names:
            fails.append(f"CABINET: {need} missing")
    lf, n_states = check_logic()
    af, leaves = check_air()
    fails += lf + af
    if verbose:
        print(f"safety: {len(hz)} hazards, {len(guard)} guard parts, {n_states} logic states, "
              f"{len(leaves)} cylinders on the air graph")
        print("\n".join(fails[:30]) if fails else
              "ALL CHECKS PASS (every swept zone inside the guard, guard clear of the machine, "
              "logic exhaustive incl. single faults, all air through Y1)")
    return fails


def export():
    """The block the web reads (doc['safety'])."""
    lf, n_states = check_logic()
    _, leaves = check_air()
    hz = hazards()
    plr = max(h["PLr"] for h in hz)
    return {
        "name": "Upgrade 2 - machine safety",
        "outline": list(outline()), "height": H, "post": POST, "gap": GAP, "z_bot": Z_BOT,
        "hazards": hz,
        "functions": [
            {"id": "SF1", "name": "Emergency stop", "devices": "ES1-ES3 -> K0 -> K1/K2 + Y1",
             "PLr": plr, "category": "3", "stop": "stop category 0 (actuator supply removed)"},
            {"id": "SF2", "name": "Guard interlock with locking", "devices": "SA-SC -> K0 -> K1/K2 + Y1",
             "PLr": plr, "category": "3", "stop": "door locked until standstill (ISO 14119)"},
            {"id": "SF3", "name": "Safe exhaust", "devices": "K0 -> Y1 (monitored)",
             "PLr": max(h["PLr"] for h in hz if h["id"] in ("H5", "H6", "H7")), "category": "3",
             "stop": "supply cut, cylinders vented"},
            {"id": "SF4", "name": "Monitored reset", "devices": "S3 -> K0", "PLr": "c", "category": "2",
             "stop": "no restart without a deliberate reset"},
        ],
        "circuit": circuit(),
        "air_graph": pneumatic_graph(),
        "cylinders_vented": leaves,
        "logic_states": n_states,
        "parts": [{"n": p.name, "f": "world", "g": p.group, "k": p.kind, "p": [round(v, 3) for v in p.p],
                   "s": list(p.s), "c": p.colour, "tag": p.tag, "mech": p.mech, "note": p.note}
                  for p in guard_parts()],
        "notes": [
            "Guard locking removes the need for a measured stopping time. A light curtain instead "
            "would sit at S = K*T + C (ISO 13855: K 2000 mm/s, C = 8*(d-14)) with T measured.",
            "PL achieved needs the devices' MTTFd, DCavg and CCF (ISO 13849-1). Category 3 with "
            "cross-monitoring is the architecture; the numbers are to be taken from the datasheets.",
            "Device dimensions are assumed (ft scale); positions follow the guard.",
        ],
    }
