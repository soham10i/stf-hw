"""
Precise components and wiring for the complete setup - computed here, drawn by
the web view, so the picture cannot invent a connection the model doesn't have.

fit(part)    which precise FreeCAD component (components.py) a model part IS
             (parts_table._kind, i.e. decided by the Belegungsplan), and the
             axis permutation that lays the component's housing into the part's
             envelope - the component is drawn at its REAL size, never stretched.
wires()      one cable per I/O-tagged static part to its module's 24 V adapter
             PCB, routed on the table surface (Manhattan, like wiring in a real
             build), plus one 34-way ribbon from each PCB's ST3 to the PLC
             cabinet, run round the table edge.
"""
import itertools
import math
import json
import os
from types import SimpleNamespace

import factory_layout as FL
from variant import UP3, UP4, UP5

KIND_TO_COMP = {
    "encoder_motor_144643": "encoder_motor", "mini_switch_37783": "mini_switch",
    "phototransistor_36134": "phototransistor", "colour_sensor_128599": "colour_sensor",
    "s_motor_S-24V": "s_motor", "compressor_K-24V": "compressor",
    "pneumatic_cylinder_PZ": "pneumatic_cylinder", "ir_track_sensor_128598": "ir_track_sensor",
    "solenoid_valve_MV-3/2": "solenoid_valve",
}
_COMP = None


MANIFEST = os.path.expanduser("~/workspace/stf-hw/web/public/components/components.json")


def _components():
    """cid -> overall bbox of the built FreeCAD component (housing + everything
    that sticks out: gearbox, shaft, nipples, tabs), from components_cad.py."""
    global _COMP
    if _COMP is None:
        m = json.load(open(MANIFEST))["components"]
        _COMP = {cid: c["bbox_mm"] for cid, c in m.items()}
    return _COMP


def dims_of(d):
    if d["k"] == "box":
        return list(d["s"])
    ax, L, dia = d["s"]
    return [L if ax == "x" else dia, L if ax == "y" else dia, L if ax == "z" else dia]


def fit(d):
    """d: an exported part dict. Returns the fit block or None."""
    import parts_table as PT
    kind = PT._kind(SimpleNamespace(name=d["n"], tag=d.get("tag", ""), mech=d.get("mech", "")))
    cid = KIND_TO_COMP.get(kind)
    if not cid:
        return None
    bb = _components()[cid]
    hous = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
    box = dims_of(d)
    best = None
    for perm in itertools.permutations(range(3)):
        err = sum(abs(hous[i] - box[perm[i]]) for i in range(3))
        upright = 0 if perm[2] == 2 else 0.5            # prefer the housing's own "up"
        if best is None or err + upright < best[0]:
            best = (err + upright, perm)
    perm = best[1]
    parity = 1 if sum(1 for i in range(3) for j in range(i + 1, 3) if perm[i] > perm[j]) % 2 == 0 else -1
    sign = [1, 1, parity]                               # det(R) = +1: a rotation, never a mirror
    x0, y0, z0 = d["p"]
    if d["k"] == "box":
        c = [x0 + box[0] / 2, y0 + box[1] / 2, z0 + box[2] / 2]
    else:
        ax, L, _ = d["s"]
        c = [x0 + (L / 2 if ax == "x" else 0), y0 + (L / 2 if ax == "y" else 0), z0 + (L / 2 if ax == "z" else 0)]
    over = [round(hous[i] - box[perm[i]], 1) for i in range(3)]
    return {"comp": cid, "perm": list(perm), "sign": sign, "centre": [round(v, 3) for v in c],
            "origin": [round((bb[i] + bb[i + 3]) / 2, 3) for i in range(3)],
            "overall": [round(v, 3) for v in hous], "oversize_mm": over}


# ------------------------------------------------------------------ wiring
def _tf(module):
    if module == "hbw":
        return lambda x, y: FL.to_factory(x, y)[:2]
    if module == "vgr":
        return lambda x, y: (x + FL.VGR_AT[0], y + FL.VGR_AT[1])
    if module == "oven":
        return lambda x, y: FL.to_factory_oven(x, y)[:2]
    if module == "sorting":
        return lambda x, y: FL.to_factory_sort(x, y)[:2]
    raise KeyError(module)


def _box_f(d, tf):
    dx, dy, dz = dims_of(d)
    x0, y0, z0 = d["p"]
    if d["k"] == "cyl":
        ax = d["s"][0]
        x0 -= 0 if ax == "x" else dx / 2
        y0 -= 0 if ax == "y" else dy / 2
    xs, ys = zip(*[tf(x, y) for x in (x0, x0 + dx) for y in (y0, y0 + dy)])
    return [min(xs), min(ys), z0, max(xs), max(ys), z0 + dz]


# One colour per conductor ROLE, so the picture reads like a real panel:
#   IEC 60204-1 / 60445 for power, a fixed code for the signal classes.
ROLE = {
    "+24V": ("#d62828", "+24 V DC supply"),
    "0V": ("#1d4ed8", "0 V / GND"),
    "PE": ("PE", "protective earth (green-yellow)"),
    "L": ("#7a4a1f", "mains L (brown)"),
    "N": ("#4aa3df", "mains N (light blue)"),
    "DI": ("#e5e7eb", "digital input signal (sensor -> PLC)"),
    "DO": ("#f97316", "output to an actuator (PLC/relay -> load)"),
    "ENC": ("#eab308", "encoder / counter pulse"),
    "AI": ("#8b5cf6", "analogue signal (Farbsensor)"),
    "AIR": ("#7cc3f5", "pneumatic hose (PU, not a wire)"),
    "SAFE": ("#e11d48", "safety circuit channel (E-stop / door interlock, dual channel)"),
    "BUS": ("#10b981", "Ethernet / Modbus TCP to a remote I/O node (industrial 4-core)"),
    "IOL": ("#06b6d4", "IO-Link C/Q line to an RFID read head (M12, 3-core)"),
}
import re


def _conductors(d):
    """What a part's cable carries, from its tag and what the part is."""
    n, tag = d["n"], d.get("tag", "")
    if n.endswith("_tx"):                                   # light-barrier LED: power only
        return ["+24V", "0V"]
    if tag.startswith("A4") or "colour_sensor" in n:
        return ["+24V", "AI", "0V"]
    if tag.startswith(("I", "A", "AUX")) or n.startswith(("LB", "CS")):
        return ["+24V", "DI"]
    if "/" in tag and "motor" in n:                         # bidirectional: both leads switched
        return ["DO", "DO"] + (["ENC", "ENC", "+24V", "0V"] if re.search(r"\bB\d", tag) else [])
    return ["DO", "0V"]


def _dedupe(pts):
    out = []
    for p in pts:
        if not out or max(abs(p[i] - out[-1][i]) for i in range(3)) > 0.05:
            out.append(p)
    return out


def _valve_tag(d):
    m = re.search(r"for (Q\d+)", d.get("note", ""))
    return m.group(1) if m else None


# ------------------------------------------------------------------ router
CELL = 5.0            # grid pitch, mm
Z = 1.2               # cables lie on the table


class Grid:
    """Occupancy of the table surface: every solid that STANDS on the table
    (underside below 3 mm), inflated so a cable's outer conductor cannot clip
    it. Cables go round these, never under them - under is where they vanished."""

    def __init__(self, boxes, inflate):
        W, H = FL.PLATE[0], FL.PLATE[1]
        self.nx, self.ny = int(W // CELL) + 1, int(H // CELL) + 1
        self.block = bytearray(self.nx * self.ny)
        self.used = {}
        for b in boxes:
            i0, j0 = self.cell(b[0] - inflate, b[1] - inflate)
            i1, j1 = self.cell(b[3] + inflate, b[4] + inflate)
            for i in range(max(0, i0), min(self.nx, i1 + 1)):
                for j in range(max(0, j0), min(self.ny, j1 + 1)):
                    self.block[i * self.ny + j] = 1

    def cell(self, x, y):
        return int(round(x / CELL)), int(round(y / CELL))

    def free(self, i, j):
        return 0 <= i < self.nx and 0 <= j < self.ny and not self.block[i * self.ny + j]

    def nearest_free(self, x, y, toward=None):
        i0, j0 = self.cell(x, y)
        best = None
        for r in range(0, 80):
            for di in range(-r, r + 1):
                for dj in (-r, r) if abs(di) != r else range(-r, r + 1):
                    i, j = i0 + di, j0 + dj
                    if self.free(i, j):
                        d = 0 if toward is None else abs(i - toward[0]) + abs(j - toward[1])
                        if best is None or d < best[0]:
                            best = (d, (i, j))
            if best:
                return best[1]
        return (i0, j0)

    def route(self, a, b, key, margin=None):
        """A* on the 4-neighbour grid. Turns cost extra (tidy, Manhattan-looking
        runs) and cells already carrying a cable of the same bundle are cheaper,
        so cables gather into looms the way a real build is wired."""
        import heapq
        used = self.used.setdefault(key, set())
        start, goal = (a[0], a[1], -1), (b[0], b[1])
        g = {start: 0.0}
        prev = {}
        pq = [(0.0, start)]
        dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
        if margin is None:
            lo_i, hi_i, lo_j, hi_j = 0, self.nx - 1, 0, self.ny - 1
        else:
            m_ = int(margin / CELL)
            lo_i, hi_i = min(a[0], b[0]) - m_, max(a[0], b[0]) + m_
            lo_j, hi_j = min(a[1], b[1]) - m_, max(a[1], b[1]) + m_
        while pq:
            f, cur = heapq.heappop(pq)
            if (cur[0], cur[1]) == goal:
                path = [cur]
                while cur in prev:
                    cur = prev[cur]
                    path.append(cur)
                cells = [(p[0], p[1]) for p in reversed(path)]
                used.update(cells)
                return cells
            gc = g[cur]
            if f - (abs(cur[0] - goal[0]) + abs(cur[1] - goal[1])) * 0.9 > gc + 1e-9:
                continue
            for k, (di, dj) in enumerate(dirs):
                i, j = cur[0] + di, cur[1] + dj
                if not (lo_i <= i <= hi_i and lo_j <= j <= hi_j):
                    continue
                if not (0 <= i < self.nx and 0 <= j < self.ny):
                    continue
                step = 0.6 if (i, j) in used else 1.0
                if self.block[i * self.ny + j] and (i, j) != goal:
                    step += 40.0                      # only when boxed in: cross as little as possible
                if cur[2] not in (-1, k):
                    step += 4.0
                nxt = (i, j, k)
                ng = gc + step
                if ng < g.get(nxt, 1e18):
                    g[nxt] = ng
                    prev[nxt] = cur
                    heapq.heappush(pq, (ng + (abs(i - goal[0]) + abs(j - goal[1])) * 0.9, nxt))
        if margin is not None and margin < 2000:
            return self.route(a, b, key, margin * 3)     # widen the window and retry
        print(f"  wiring: no route {a} -> {b} ({key})")
        return [a, b]


def _simplify(pts):
    """Drop collinear interior points."""
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[i], pts[i + 1]
        if (b[0] - a[0]) * (c[1] - b[1]) == (b[1] - a[1]) * (c[0] - b[0]):
            continue
        out.append(b)
    out.append(pts[-1])
    return out


def _floor_boxes(doc, mods):
    boxes = []
    for m, parts in mods.items():
        tf = _tf(m)
        for d in parts:
            if d["g"] == "frame":
                continue
            b = _box_f(d, tf)
            if b[2] < 3.0:
                boxes.append(b)
    import plc_model as PM
    for p in PM.build():
        if p.group == "frame":
            continue
        a = p.local_aabb()
        boxes.append((a[0] + FL.PLC_AT[0], a[1] + FL.PLC_AT[1], a[2], a[3] + FL.PLC_AT[0],
                      a[4] + FL.PLC_AT[1], a[5]))
    if FL.UP1:
        import upgrade as U
        boxes += [a for _, _, a in U.factory_parts() if a[2] < 3.0]
    return boxes


def _anchor(b, cell):
    """Where a cable leaves a part: the point of its footprint nearest the free
    cell it drops to, at a height it can actually be plugged in."""
    cx, cy = cell[0] * CELL, cell[1] * CELL
    x = min(max(cx, b[0]), b[3]); y = min(max(cy, b[1]), b[4])
    z = min(b[5], b[2] + 8.0) if b[2] < 3 else b[2] + min(6.0, (b[5] - b[2]) / 2)
    return (x, y, z)


def _keep_clear(parts, tf):
    """Where a workpiece actually SITS: the tray/disc/nest surfaces it rests
    on, not the rails or belts that merely guide those surfaces (those are
    long and would swallow half the module). A hose or cable rising through
    one of these boxes would visually skewer the cookie sitting there.

    A carrier (group "slider"/"turn"/etc.) only sits at ONE exported pose, but
    it travels the whole length of its rail (group name + "_fix", e.g.
    "slider"/"slider_fix" - the convention this codebase already uses); union
    the two so the keep-clear box covers the full sweep, not just today's
    pose. Margin covers the workpiece overhanging its carrier."""
    fix_box = {}
    for d in parts:
        if not d["g"].endswith("_fix"):
            continue
        fix_box.setdefault(d["g"][:-4], []).append(_box_f(d, tf))
    boxes = []
    m = 30.0
    for d in parts:
        if d["g"] not in ("slider", "turn", "load"):
            continue
        b = list(_box_f(d, tf))
        for fb in fix_box.get(d["g"], []):
            b[0], b[1] = min(b[0], fb[0]), min(b[1], fb[1])
            b[3], b[4] = max(b[3], fb[3]), max(b[4], fb[4])
        boxes.append((b[0] - m, b[1] - m, b[3] + m, b[4] + m))
    return boxes


HAZARD_Z = (25.0, 100.0)   # workpiece + carrier-top height band, any module


def _sweep3(parts, tf):
    """The keep-clear boxes as SOLIDS: the xy of _keep_clear, and in z the
    carrier's underside up to a cookie standing on its top (+ 5 mm). Nothing
    may pass through these - the cookie rides through them."""
    zs = [_box_f(d, tf) for d in parts if d["g"] in ("slider", "turn", "load")]
    if not zs:
        return []
    z0 = min(b[2] for b in zs)
    z1 = max(b[5] for b in zs) + 20.0 + 5.0          # workpiece 20 mm tall
    return [(b[0], b[1], z0, b[2], b[3], z1) for b in _keep_clear(parts, tf)]


def _crosses(pts, boxes, n=40):
    """First sampled point of a polyline inside any box, else None."""
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        for k in range(n + 1):
            t = k / n
            x, y, z = (p[j] + (q[j] - p[j]) * t for j in range(3))
            for b in boxes:
                if b[0] <= x <= b[3] and b[1] <= y <= b[4] and b[2] <= z <= b[5]:
                    return (round(x, 1), round(y, 1), round(z, 1))
    return None


def _drop_cell(grid, ub, sweep, tcell):
    """A free table cell hugging an upright's footprint, OUTSIDE every sweep
    box, nearest the cable's terminal - where the cable comes down."""
    best = None
    for off in (5.0, 10.0, 15.0, 20.0):
        x0, y0, x1, y1 = ub[0] - off, ub[1] - off, ub[3] + off, ub[4] + off
        ring = [(x, y0) for x in _frange(x0, x1)] + [(x, y1) for x in _frange(x0, x1)] + \
               [(x0, y) for y in _frange(y0, y1)] + [(x1, y) for y in _frange(y0, y1)]
        for x, y in ring:
            i, j = grid.cell(x, y)
            if not grid.free(i, j) or any(b[0] <= x <= b[3] and b[1] <= y <= b[4] for b in sweep):
                continue
            d = math.hypot(i - tcell[0], j - tcell[1])
            if best is None or d < best[0]:
                best = (d, (i, j))
        if best:
            return best[1]
    return None


def _frange(a, b, step=CELL):
    n = max(1, int((b - a) // step))
    return [a + k * (b - a) / n for k in range(n + 1)]


def _uprights(parts, tf, d, anc_z):
    """Where a cable from a part mounted UP on a structure can come down: the
    floor-standing uprights of that same structure (its group), tall enough to
    reach the part. A cable follows its own mounting, as it would be tied."""
    own = [e for e in parts if e["g"] == d["g"] and e["f"] == "world" and e["n"] != d["n"]]
    out = []
    for e in own or parts:
        b = _box_f(e, tf)
        if b[2] < 3.0 and b[5] >= anc_z - 20.0 and e["g"] != "frame":
            out.append(b)
    return out


def _rise(x, y, z0, z1, clears, safe_h=140.0):
    """A vertical run from z0 to z1 at (x, y), rerouted round any box in
    `clears` (keep-out boxes in x, y - see _keep_clear) if it would cross
    HAZARD_Z there. A short drop that never reaches that band (a sensor a few
    mm off the floor) is left alone - it runs under the carrier's overhang,
    same as any other floor cable. Above safe_h the air is clear (gantries and
    doors live up there, not cookies)."""
    lo, hi = min(z0, z1), max(z0, z1)
    crosses = lo < HAZARD_Z[1] and hi > HAZARD_Z[0]
    hit = next((c for c in (clears or []) if crosses and c[0] <= x <= c[2] and c[1] <= y <= c[3]),
               None)
    if hit:
        # step out to the nearest edge of the keep-clear box, at floor height,
        # rise there, then come back in above safe_h
        dl, dr = x - hit[0], hit[2] - x
        db, dt = y - hit[1], hit[3] - y
        edge = min(dl, dr, db, dt)
        if edge == dl:
            sx, sy = hit[0] - 5, y
        elif edge == dr:
            sx, sy = hit[2] + 5, y
        elif edge == db:
            sx, sy = x, hit[1] - 5
        else:
            sx, sy = x, hit[3] + 5
        top = max(z0, safe_h, z1)
        return [(x, y, z0), (sx, sy, z0), (sx, sy, top), (x, y, top), (x, y, z1)]
    return [(x, y, z0), (x, y, z1)]


def _central_air(doc, mods, grid, hoses, cables, duct):
    """Upgrade 1: one air main per module, manifold outlet -> the module's valve
    group, routed on the table round everything standing on it, then a short
    branch up into each valve's P port. Plus the central compressor's cable."""
    import upgrade as U
    outs = U.outlets()
    for k, m in enumerate(("oven", "sorting", "vgr")):
        tf = _tf(m)
        valves = [d for d in mods[m] if "valve" in d["n"] and d["f"] == "world"]
        vb = [_box_f(d, tf) for d in valves]
        gx = (min(b[0] for b in vb) + max(b[3] for b in vb)) / 2
        gy = (min(b[1] for b in vb) + max(b[4] for b in vb)) / 2
        o = outs[k]
        a_cell = grid.nearest_free(o[0], o[1] + 20)
        b_cell = grid.nearest_free(gx, gy, toward=a_cell)
        run = [(i * CELL, j * CELL) for i, j in _simplify(grid.route(a_cell, b_cell, f"air_{m}"))]
        main = [o, (o[0], o[1], o[2] + 10), (run[0][0], run[0][1], o[2] + 10),
                (run[0][0], run[0][1], Z + 3)] + [(x, y, Z + 3) for x, y in run[1:]]
        hoses.append({"module": m, "from": "air_manifold", "to": f"{m} valve group", "main": True,
                      "points": [[round(v, 1) for v in p] for p in _dedupe(main)]})
        end = main[-1]
        for d, b in zip(valves, vb):
            vt = ((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, b[5])
            hoses.append({"module": m, "from": f"{m} air main", "to": d["n"],
                          "points": [[round(v, 1) for v in p] for p in
                                     _dedupe([end, (vt[0], end[1], Z + 3), (vt[0], vt[1], Z + 3),
                                              (vt[0], vt[1], vt[2])])]})
    # the central compressor: one DO + 0 V from the cabinet
    comp = next(a for _, p, a in U.factory_parts() if p.name == "Q10_central_compressor")
    c = ((comp[0] + comp[3]) / 2, (comp[1] + comp[4]) / 2)
    s_cell = grid.nearest_free(c[0], c[1])
    t_cell = grid.nearest_free(duct[0] + 45, duct[1])
    run = [(i * CELL, j * CELL) for i, j in _simplify(grid.route(s_cell, t_cell, "air_q10"))]
    anc = _anchor(comp, s_cell)
    pts = [anc, (run[0][0], run[0][1], anc[2]), (run[0][0], run[0][1], Z)]
    pts += [(x, y, Z) for x, y in run[1:]] + [(duct[0], duct[1], Z), (duct[0], duct[1], duct[2] + 4)]
    cables.append({"module": "air", "part": "Q10_central_compressor", "tag": "Q10",
                   "conductors": ["DO", "0V"],
                   "points": [[round(v, 1) for v in p] for p in _dedupe(pts)]})


def _safety(doc, grid, cables, plc_pt, Z):
    """Upgrade 2: every E-stop, door switch and the reset in a duct along the
    OUTSIDE of the guard's bottom rail, through one gland into the free corridor
    between the PLC plate and the sorting line, into the cabinet duct and down
    to the safety relay. The safe exhaust valve Y1 is routed on the table."""
    import safety as SF
    sd = doc["safety"]
    x0, y0, x1, y1 = sd["outline"]
    P = sd["post"]
    X0, Y0, X1, Y1 = x0 - P - 12, y0 - P - 12, x1 + P + 12, y1 + P + 12   # outer duct line
    ZD = -10.0                                                             # on the rail's outer face
    per = [(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)]
    L = [0.0]
    for i in range(4):
        a, b = per[i], per[(i + 1) % 4]
        L.append(L[-1] + math.dist(a, b))

    def proj(x, y):
        best = None
        for i in range(4):
            a, b = per[i], per[(i + 1) % 4]
            ab = (b[0] - a[0], b[1] - a[1]); l2 = ab[0] ** 2 + ab[1] ** 2
            t = max(0.0, min(1.0, ((x - a[0]) * ab[0] + (y - a[1]) * ab[1]) / l2))
            q = (a[0] + t * ab[0], a[1] + t * ab[1])
            d = math.dist(q, (x, y))
            if best is None or d < best[0]:
                best = (d, L[i] + t * math.sqrt(l2), q)
        return best[1], best[2]

    def walk(s0, s1):
        """The perimeter corners passed going from arc s0 to s1, the shorter way."""
        T = L[-1]
        fwd = (s1 - s0) % T
        up = fwd <= T - fwd
        dist = fwd if up else T - fwd
        hit = []
        for i in range(4):
            d = (L[i] - s0) % T if up else (s0 - L[i]) % T
            if 1e-6 < d < dist:
                hit.append((d, per[i]))
        return [p for _, p in sorted(hit)]

    relay = plc_pt("safety_relay_K0")
    duct = plc_pt("cable_duct", 0.5, 1.0)
    gy = 412.0                                    # corridor between PLC plate (y<400) and sorting (y>424)
    s_in, q_in = proj(X0, gy)
    tail = [(q_in[0], q_in[1], ZD), (0.0, gy, ZD), (0.0, gy, Z), (duct[0], gy, Z),
            (duct[0], duct[1] + 5, Z), (duct[0], duct[1] - 5, duct[2] + 4),
            (relay[0], relay[1], relay[2] + 18), (relay[0], relay[1], relay[2])]
    cond = {"estop": ["SAFE"] * 4, "door": ["SAFE"] * 4 + ["DO", "0V", "DI"], "reset": ["+24V", "DI"]}
    for q in sd["parts"]:
        if not q["tag"] or q["n"].endswith("_button") or q["tag"] == "Y1":
            continue
        kind = "estop" if q["n"].startswith("ES") else "door" if q["n"].startswith("DS") else "reset"
        b = (q["p"][0], q["p"][1], q["p"][2], q["p"][0] + q["s"][0], q["p"][1] + q["s"][1], q["p"][2] + q["s"][2])
        cx, cy = (b[0] + b[3]) / 2, (b[1] + b[4]) / 2
        s_dev, q_dev = proj(cx, cy)
        pts = [(q_dev[0], q_dev[1], b[2] + 5), (q_dev[0], q_dev[1], ZD)]
        pts += [(x, y, ZD) for x, y in walk(s_dev, s_in)]
        pts += tail
        cables.append({"module": "safety", "part": q["n"], "tag": q["tag"], "conductors": cond[kind],
                       "points": [[round(v, 1) for v in p] for p in _dedupe(pts)]})
    import upgrade as U
    for mod, p, a in U.factory_parts():
        if p.name != "air_safe_exhaust":
            continue
        c = ((a[0] + a[3]) / 2, (a[1] + a[4]) / 2)
        s_cell = grid.nearest_free(c[0], c[1])
        t_cell = grid.nearest_free(duct[0] + 45, duct[1] - 40)
        run = [(i * CELL, j * CELL) for i, j in _simplify(grid.route(s_cell, t_cell, "safe_y1"))]
        anc = _anchor(a, s_cell)
        pts = [anc, (run[0][0], run[0][1], anc[2]), (run[0][0], run[0][1], Z)]
        pts += [(x, y, Z) for x, y in run[1:]] + [(relay[0], relay[1] + 10, Z + 60), (relay[0], relay[1], relay[2])]
        cables.append({"module": "safety", "part": "air_safe_exhaust", "tag": "Y1",
                       "conductors": ["SAFE", "SAFE", "0V"],
                       "points": [[round(v, 1) for v in q] for q in _dedupe(pts)]})


def _node_links(m, pb, pc, cond, grid, bundles, plc_pt, Z):
    """Upgrade 3: the module's ST3 ribbon now ends at its remote I/O node a
    few cm away; only an Ethernet line (signal duct -> switch) and the fused
    24 V feed (power duct -> electronic breaker) run to the cabinet."""
    import io_nodes as N
    parts = {p.name: p.local_aabb() for p in N.parts(m)}
    cp = parts[f"io_{m}_coupler"]
    sl = [a for n, a in parts.items() if n.startswith(f"io_{m}_") and n[len(f"io_{m}_"):][:2] in ("DI", "DO", "AI", "CN")]
    tgt = sl[len(sl) // 2] if sl else cp
    tc = ((tgt[0] + tgt[3]) / 2, (tgt[1] + tgt[4]) / 2)
    cc = ((cp[0] + cp[3]) / 2, (cp[1] + cp[4]) / 2)

    def floor_run(a, b, key):
        s_cell, t_cell = grid.nearest_free(a[0], a[1]), grid.nearest_free(b[0], b[1], toward=grid.cell(a[0], a[1]))
        return [(i * CELL, j * CELL) for i, j in _simplify(grid.route(s_cell, t_cell, key))]

    run = floor_run(pc, tc, f"st3_{m}")
    pts = [(pc[0], pc[1], pb[5]), (run[0][0], run[0][1], pb[5]), (run[0][0], run[0][1], Z + 2)]
    pts += [(x, y, Z + 2) for x, y in run[1:]] + [(tc[0], tc[1], Z + 2), (tc[0], tc[1], tgt[5])]
    bundles.append({"module": f"{m}:st3", "conductors": cond, "local": True,
                    "points": [[round(v, 1) for v in p] for p in _dedupe(pts)]})
    for key, end, duct_name, conds in (
            ("bus", "eth_switch", "cable_duct", ["BUS"] * 4),
            ("feed", "ecb_4ch", "duct_power", ["+24V", "+24V", "0V", "0V"])):
        d = plc_pt(duct_name, 0.5, 1.0)
        e = plc_pt(end)
        run = floor_run(cc, (d[0], d[1] + 25), f"{key}_{m}")
        pts = [(cc[0], cc[1], cp[5]), (run[0][0], run[0][1], cp[5]), (run[0][0], run[0][1], Z + 3)]
        pts += [(x, y, Z + 3) for x, y in run[1:]]
        pts += [(d[0], d[1] + 5, Z + 3), (d[0], d[1] - 5, d[2] + 4), (d[0], e[1], d[2] + 4),
                (e[0], e[1], e[2] + 16), (e[0], e[1], e[2])]
        bundles.append({"module": f"{m}:{key}", "conductors": conds,
                        "points": [[round(v, 1) for v in p] for p in _dedupe(pts)]})


def _chain_harness(grid, cables, boards, Z):
    """Upgrade 3: the moving devices' cables leave their chains at the fixed
    end (HBW travel chain) / the swivel axis (VGR tower duct) and run on the
    table to the module's PCB, like every static device's cable."""
    import chains as CH
    t = CH.HBW["travel"]
    fx, fy, _ = FL.to_factory(t["F"][0], t["F"][1])
    starts = {"hbw": ((fx, fy), 9.0, t["devices"]),
              "vgr": (FL.vgr_tower(), 14.0,
                      CH.VGR["plunge"]["devices"] + ["M1_plunge_motor", "I1_ref_plunge"])}
    for m, ((sx, sy), z0, devs) in starts.items():
        pb = boards[m]["box"]
        tx, ty = (pb[0] + pb[3]) / 2, pb[4] - 3
        s_cell = grid.nearest_free(sx, sy, toward=grid.cell(tx, ty))
        t_cell = grid.nearest_free(tx, ty)
        run = [(i * CELL, j * CELL) for i, j in _simplify(grid.route(s_cell, t_cell, f"chain_{m}"))]
        pts = [(sx, sy, z0), (run[0][0], run[0][1], z0), (run[0][0], run[0][1], Z)]
        pts += [(x, y, Z) for x, y in run[1:]] + [(tx, ty, Z), (tx, ty, pb[5] - 4)]
        cond = []
        for d in devs:
            cond += ["DO", "DO", "ENC", "ENC", "+24V", "0V"] if CH.COND.get(d, 2) == 6 else \
                    (["DO", "0V"] if d.startswith(("M", "suction")) else ["+24V", "DI"])
        cables.append({"module": m, "part": f"chain_harness_{m}", "tag": "moving axes",
                       "conductors": cond, "points": [[round(v, 1) for v in p] for p in _dedupe(pts)]})


def _rfid_cables(grid, cables, Z):
    """Upgrade 4: each RFID head's M12 cable drops between the belt legs to
    the table and runs to the IO-Link slice of the HBW node."""
    import hbw_model as HM
    import io_nodes as N
    sl = next(p.local_aabb() for p in N.parts("hbw") if p.name == "io_hbw_IOL1")
    tx, ty = (sl[0] + sl[3]) / 2, (sl[1] + sl[4]) / 2
    for k, (rp, tag) in enumerate((("rp1", "RF1"), ("rp2", "RF2"))):
        yd = HM.RFID_Y[k] + 16                       # the head's cable end (past the belt motor at RP2)
        hx, hy, _ = FL.to_factory(HM.P["CV_X"], yd)
        s_cell = grid.nearest_free(hx, hy, toward=grid.cell(tx, ty))
        t_cell = grid.nearest_free(tx, ty)
        run = [(i * CELL, j * CELL) for i, j in _simplify(grid.route(s_cell, t_cell, f"rfid_{rp}"))]
        z0 = HM.P["CV_LEG_H"] + 6
        pts = [(hx, hy, z0), (hx, hy, Z + 4), (run[0][0], run[0][1], Z + 4)]
        pts += [(x, y, Z + 4) for x, y in run[1:]] + [(tx, ty, Z + 4), (tx, ty, sl[5])]
        cables.append({"module": "hbw", "part": f"rfid_{rp}_head", "tag": tag,
                       "conductors": ["+24V", "IOL", "0V"],
                       "points": [[round(v, 1) for v in p] for p in _dedupe(pts)]})


def _u5_sensor_cables(mods, grid, cables, Z):
    """Upgrade 5: the reed, vacuum and pressure switches virtual commissioning
    asked for. Each runs from the part it is clamped on to its node's DI slice."""
    import control as C
    import io_nodes as N
    import upgrade as U
    air = {p.name: a for _, p, a in U.factory_parts(include_io=False)}
    for m, sensors in C.U5_SENSORS.items():
        nparts = {p.name: p.local_aabb() for p in N.parts(m)}
        for sg, (part, what) in sensors.items():
            sid = next(i for i, t, ch in N.slices(m) if sg in ch)
            sl = nparts[f"io_{m}_{sid}"]
            tx, ty = (sl[0] + sl[3]) / 2, (sl[1] + sl[4]) / 2
            if part in air:
                b = air[part]
            else:
                d = next(d for d in mods[m] if d["n"] == part)
                b = _box_f(d, _tf(m))
            sx, sy = (b[0] + b[3]) / 2, (b[1] + b[4]) / 2
            s_cell = grid.nearest_free(sx, sy, toward=grid.cell(tx, ty))
            t_cell = grid.nearest_free(tx, ty)
            run = [(i * CELL, j * CELL) for i, j in _simplify(grid.route(s_cell, t_cell, f"u5_{m}_{sg}"))]
            z0 = min(b[5], b[2] + 8.0)
            pts = [(sx, sy, z0), (run[0][0], run[0][1], z0), (run[0][0], run[0][1], Z + 5)]
            pts += [(x, y, Z + 5) for x, y in run[1:]] + [(tx, ty, Z + 5), (tx, ty, sl[5])]
            cables.append({"module": m, "part": f"{part}:{sg}", "tag": sg, "conductors": ["+24V", "DI"],
                           "points": [[round(v, 1) for v in q] for q in _dedupe(pts)]})


def wires(doc):
    Z = 1.2                                             # cables lie on the table
    mods = {"hbw": doc["parts"], "vgr": doc["vgr"]["parts"], "oven": doc["oven"]["parts"],
            "sorting": doc["sorting"]["parts"]}
    cables, hoses, bundles, power, boards = [], [], [], [], {}
    import plc_model as PM
    pa = {p.name: p for p in PM.build()}
    P0 = FL.PLC_AT

    def plc_pt(name, dx=0.5, dy=0.5, top=True):
        p = pa[name]
        return (P0[0] + p.p[0] + p.s[0] * dx, P0[1] + p.p[1] + p.s[1] * dy, p.p[2] + (p.s[2] if top else 0))

    duct = plc_pt("cable_duct", 0.5, 0.5)
    ctl = json.load(open(os.path.expanduser("~/workspace/stf-hw/web/public/controller.json")))["modules"]
    floor = _floor_boxes(doc, mods)
    grid = Grid(floor, 3.0)
    # the PCB->PLC bundles are ~50 mm wide: route them on a grid inflated to match
    wide = Grid([b for b in floor if not (b[0] >= FL.PLC_AT[0] and b[1] >= FL.PLC_AT[1]
                                          and b[3] <= FL.PLC_AT[0] + 300 and b[4] <= FL.PLC_AT[1] + 380)], 26.0)
    dio_of = {"hbw": "revpi_dio_1", "oven": "revpi_dio_2", "vgr": "revpi_dio_3", "sorting": "revpi_dio_3"}
    for m, parts in mods.items():
        tf = _tf(m)
        pcb = next(d for d in parts if "pcb" in d["n"].lower())
        pb = _box_f(pcb, tf)
        boards[m] = {"part": pcb["n"], "box": [round(v, 2) for v in pb]}
        pc = ((pb[0] + pb[3]) / 2, (pb[1] + pb[4]) / 2)
        io = []
        for d in parts:
            if d["f"] != "world" or "pcb" in d["n"].lower():
                continue
            if "valve" in d["n"]:
                io.append(d)
            elif d.get("tag") and "cylinder" not in d["n"] and "door" not in d["n"] \
                    and not d["n"].startswith("rfid_"):      # U4: the heads go to IO-Link, not the PCB
                io.append(d)
        io.sort(key=lambda d: (d.get("tag") or _valve_tag(d) or "", d["n"]))
        long_x = (pb[3] - pb[0]) >= (pb[4] - pb[1])
        # only the oven has cookie CARRIERS (tray, turntable); the VGR's swivel
        # ring shares the group name "turn" but carries no cookie
        sweep = _sweep3(parts, tf) if m == "oven" else []
        for k, d in enumerate(io):
            b = _box_f(d, tf)
            c = ((b[0] + b[3]) / 2, (b[1] + b[4]) / 2)
            u = (k + 1) / (len(io) + 1)
            # terminal on the PCB edge that faces the part (the terminal strip)
            if long_x:
                tx = pb[0] + u * (pb[3] - pb[0])
                ty = pb[4] - 3 if c[1] > pc[1] else pb[1] + 3
            else:
                ty = pb[1] + u * (pb[4] - pb[1])
                tx = pb[3] - 3 if c[0] > pc[0] else pb[0] + 3
            tcell = grid.nearest_free(tx, ty)
            scell = grid.nearest_free(c[0], c[1], toward=tcell)
            cells = grid.route(scell, tcell, m, margin=120)
            anc = _anchor(b, scell)
            run = [(i * CELL, j * CELL) for i, j in _simplify(cells)]
            pts = [anc, (run[0][0], run[0][1], anc[2]), (run[0][0], run[0][1], Z)]
            pts += [(x, y, Z) for x, y in run[1:]]
            pts += [(tx, ty, Z), (tx, ty, pb[5] - 4)]
            if _crosses(pts, sweep):
                # it would come down through the cookie's path: run it along its
                # own structure to the nearest upright and down beside that
                for ub in sorted(_uprights(parts, tf, d, anc[2]),
                                 key=lambda u: math.hypot((u[0] + u[3]) / 2 - anc[0], (u[1] + u[4]) / 2 - anc[1])):
                    dcell = _drop_cell(grid, ub, sweep, tcell)
                    if dcell is None:
                        continue
                    dx, dy = dcell[0] * CELL, dcell[1] * CELL
                    alt = [anc, (anc[0], anc[1], anc[2] + 4), (dx, dy, anc[2] + 4), (dx, dy, Z)]
                    run = [(i * CELL, j * CELL) for i, j in _simplify(grid.route(dcell, tcell, m, margin=120))]
                    alt += [(x, y, Z) for x, y in run[1:]] + [(tx, ty, Z), (tx, ty, pb[5] - 4)]
                    if not _crosses(alt, sweep):
                        pts = alt
                        break
            cables.append({"module": m, "part": d["n"], "tag": d.get("tag") or _valve_tag(d) or "",
                           "conductors": _conductors(d),
                           "points": [[round(v, 1) for v in p] for p in _dedupe(pts)]})
        for c in cables + hoses:
            if c["module"] == m:
                hit = _crosses(c["points"], sweep)
                if hit:
                    raise RuntimeError(f"{m}: {c.get('part') or c.get('to')} runs through the "
                                       f"cookie's path at {hit} - reroute it")
        # pneumatics: compressor -> every valve (P), each valve -> its cylinder (A)
        clear = _keep_clear(parts, tf)
        comp = next((d for d in parts if "compressor" in d["n"] and d["f"] == "world"), None)
        for d in parts:
            if "valve" not in d["n"] or d["f"] != "world":
                continue
            vb = _box_f(d, tf)
            vt = ((vb[0] + vb[3]) / 2, (vb[1] + vb[4]) / 2, vb[5])
            if comp:
                cb = _box_f(comp, tf)
                cc = ((cb[0] + cb[3]) / 2, (cb[1] + cb[4]) / 2, cb[5])
                hoses.append({"module": m, "from": comp["n"], "to": d["n"],
                              "points": [[round(v, 1) for v in p] for p in
                                         (cc, (cc[0], cc[1], cc[2] + 12), (vt[0], vt[1], vt[2] + 12), vt)]})
            tag = _valve_tag(d)
            cyl = next((q for q in parts if q.get("tag") == tag and "cylinder" in q["n"]
                        and q["f"] == "world"), None)
            if cyl:
                yb = _box_f(cyl, tf)
                yt = ((yb[0] + yb[3]) / 2, (yb[1] + yb[4]) / 2, yb[5])
                floor_leg = [(vt[0], vt[1], Z + 3), (yt[0], vt[1], Z + 3), (yt[0], yt[1], Z + 3)]
                rise = _rise(yt[0], yt[1], Z + 3, yt[2], clear)
                hoses.append({"module": m, "from": d["n"], "to": cyl["n"],
                              "points": [[round(v, 1) for v in p] for p in
                                         _dedupe([vt] + floor_leg + rise)]})
        # PCB <-> PLC: one bundle of single wires - every ST3 signal of this
        # module plus its supply (+24 V actuators, +24 V sensors, 2x 0 V)
        sig = []
        for _, t in sorted(ctl[m]["st3"].items(), key=lambda kv: int(kv[0])):
            sig.append("DI" if t.startswith("I") else "ENC" if t.startswith("B")
                       else "AI" if t.startswith("A") else "DO")
        cond = ["+24V", "+24V"] + sig + ["0V", "0V"]
        if UP3:
            _node_links(m, pb, pc, cond, grid, bundles, plc_pt, Z)
            continue
        a_cell = wide.nearest_free(pc[0], pc[1], toward=wide.cell(duct[0], duct[1]))
        d_cell = wide.nearest_free(duct[0] + 45, duct[1])
        run = [(i * CELL, j * CELL) for i, j in _simplify(wide.route(a_cell, d_cell, "plc"))]
        path = [(pc[0], pc[1], pb[5]), (pc[0], pc[1], Z + 2), (run[0][0], run[0][1], Z + 2)]
        path += [(x, y, Z + 2) for x, y in run[1:]]
        path += [(duct[0], duct[1], Z + 2), (duct[0], duct[1], duct[2] + 4)]
        path = _dedupe(path)
        bundles.append({"module": m, "conductors": cond,
                        "points": [[round(v, 1) for v in p] for p in path]})
        # inside the cabinet: signals from the duct to this module's DIO, supply to the terminals
        dio = plc_pt(dio_of[m])
        power.append({"name": f"{m}: signals -> {dio_of[m]}", "conductors": sig[:8],
                      "points": [[round(v, 1) for v in p] for p in
                                 (duct, (duct[0], duct[1], duct[2] + 25), (dio[0] + 30, dio[1], dio[2] + 25),
                                  (dio[0] + 30, dio[1], dio[2]))]})
    if FL.UP1:
        _central_air(doc, mods, grid, hoses, cables, duct)
    if doc.get("safety"):
        _safety(doc, grid, cables, plc_pt, Z)
    if UP3:
        _chain_harness(grid, cables, boards, Z)
    if UP4:
        _rfid_cables(grid, cables, Z)
    if UP5:
        _u5_sensor_cables(mods, grid, cables, Z)
    # the power supply: mains in (L, N, PE), 24 V out to the feed terminals, PE to the DIN rail
    psu = plc_pt("psu_wdr120")
    t1, t4 = plc_pt("terminal_1"), plc_pt("terminal_4")
    rail = plc_pt("pe_busbar", 0.5, 0.1) if UP3 else plc_pt("din_rail", 0.5, 0.05)
    power.append({"name": "mains -> PSU (L, N, PE)", "conductors": ["L", "N", "PE"],
                  "points": [[round(v, 1) for v in p] for p in
                             ((0.0, psu[1], Z + 2), (psu[0] - 50, psu[1], Z + 2),
                              (psu[0] - 50, psu[1], psu[2] + 10), (psu[0] - 30, psu[1], psu[2]))]})
    power.append({"name": "PSU +24 V -> terminal 1", "conductors": ["+24V"],
                  "points": [[round(v, 1) for v in p] for p in
                             ((psu[0] + 30, psu[1] - 5, psu[2]), (psu[0] + 30, psu[1] - 5, psu[2] + 20),
                              (t1[0] + 20, t1[1], psu[2] + 20), (t1[0] + 20, t1[1], t1[2]))]})
    power.append({"name": "PSU 0 V -> terminal 4", "conductors": ["0V"],
                  "points": [[round(v, 1) for v in p] for p in
                             ((psu[0] + 30, psu[1] + 5, psu[2]), (psu[0] + 30, psu[1] + 5, psu[2] + 14),
                              (t4[0] + 20, t4[1], psu[2] + 14), (t4[0] + 20, t4[1], t4[2]))]})
    power.append({"name": "PE -> PE busbar" if UP3 else "PE -> DIN rail", "conductors": ["PE"],
                  "points": [[round(v, 1) for v in p] for p in
                             ((psu[0] - 30, psu[1] + 8, psu[2]), (psu[0] - 55, psu[1] + 8, psu[2] + 5),
                              (rail[0] - 25, rail[1], Z + 8), (rail[0] - 12, rail[1], rail[2]))]})
    power.append({"name": "terminals -> duct (24 V to the PCBs)", "conductors": ["+24V", "+24V", "0V", "0V"],
                  "points": [[round(v, 1) for v in p] for p in
                             ((t1[0] - 20, t1[1] + 6, t1[2]), (t1[0] - 20, t1[1] + 6, t1[2] + 15),
                              (duct[0], t1[1] + 6, t1[2] + 15), (duct[0], duct[1], duct[2] + 4))]})
    return {"roles": {k: {"colour": v[0], "label": v[1]} for k, v in ROLE.items()
                      if (k != "SAFE" or doc.get("safety")) and (k != "BUS" or UP3)
                      and (k != "IOL" or UP4)},
            "cables": cables, "hoses": hoses, "bundles": bundles, "power": power, "boards": boards}
