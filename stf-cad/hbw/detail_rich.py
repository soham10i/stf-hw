"""
Rich, multi-colour detail for the parts the booklet photos show in detail
(536634 Abb. 9 / fischertechnik doku-24v 536632 p.1): the oven station.

rich(p) returns [(sub_name, shape, hex_colour), ...] or None. Same rule as
detail.py: EVERY sub-shape stays inside the part's proven envelope (asserted),
so the clearance proofs, the swept path and the pipeline still hold for exactly
this geometry. Only the look changes - and it changes towards the photo:

  kiln walls / pedestal   red / black ft building blocks: 30 x 15 bond seams
  oven_roof               black ft plates, seams, a row of flush red caps (photo)
  Q13_oven_door           red panel with plate seams and black guide shoes
  Q9_oven_lamp            black socket + warm lens (ft lens-tip lamp)
  slider_rail             steel axle between two red end blocks (photo: silver rod)
  ofenschieber_tray       red tray with a nest for the 45 mm workpiece
  sauger_rail             slotted aluminium profile
  door_guide_L/R          round steel guide rods
  saw_column / saw_arm    black perforated struts (ft Statik), 15 mm hole pitch
  saw_blade               toothed steel disc, 24 teeth
  drehtisch_disc          red turntable with a tooth rim (driven by M1)
  belt_web                ribbed rubber belt

Dimensions of the ft features (seam 1.0 x 0.8, strut hole 4.1, 15/30 mm pitch)
are ft-standard grid values; the rest is assumed - MEASURE.
Runs inside FreeCAD.
"""
import math

import FreeCAD as App
import Part

import detail

V = App.Vector
RED, BLACK, STEEL, ALU = "#d8261c", "#26272b", "#b9bec4", "#d6d9da"
LENS, RUBBER = "#ffd27a", "#1f2023"
TOL = 0.02


def _box(p):
    x, y, z = p.p
    dx, dy, dz = p.s
    return x, y, z, dx, dy, dz


def _seams(solid, env, faces, ph=30.0, pv=15.0, w=1.0, d=0.8, bond=True):
    """Cut ft-block seams into the given faces ('x-','x+','y-','y+','z+').
    Horizontal seams every pv, vertical seams every ph, staggered (bond)."""
    x0, y0, z0, x1, y1, z1 = env
    tools = []
    for f in faces:
        ax = "xyz".index(f[0])
        hi = f[1] == "+"
        # the face plane and its two in-plane axes
        if ax == 2:                      # top face: a plate grid
            for k in range(1, int((x1 - x0) // ph) + 1):
                x = x0 + k * ph
                if x < x1 - 1:
                    tools.append(Part.makeBox(w, y1 - y0, d, V(x - w / 2, y0, z1 - d)))
            for k in range(1, int((y1 - y0) // ph) + 1):
                y = y0 + k * ph
                if y < y1 - 1:
                    tools.append(Part.makeBox(x1 - x0, w, d, V(x0, y - w / 2, z1 - d)))
            continue
        u = 1 - ax                        # in-plane horizontal axis (x<->y)
        lo = [x0, y0, z0]; hi_ = [x1, y1, z1]
        depth_lo = hi_[ax] - d if hi else lo[ax]
        # horizontal seams
        z = z0 + pv
        row = 0
        while z < z1 - 1:
            o = [0, 0, 0]; s = [0, 0, 0]
            o[ax], s[ax] = depth_lo, d
            o[u], s[u] = lo[u], hi_[u] - lo[u]
            o[2], s[2] = z - w / 2, w
            tools.append(Part.makeBox(s[0], s[1], s[2], V(*o)))
            z += pv
        # vertical (butt) seams, staggered per course
        zc, row = z0, 0
        while zc < z1 - 1:
            off = (ph / 2 if (bond and row % 2) else 0.0)
            t = lo[u] + ph - off
            while t < hi_[u] - 1:
                o = [0, 0, 0]; s = [0, 0, 0]
                o[ax], s[ax] = depth_lo, d
                o[u], s[u] = t - w / 2, w
                o[2], s[2] = zc, min(pv, z1 - zc)
                tools.append(Part.makeBox(s[0], s[1], s[2], V(*o)))
                t += ph
            zc += pv
            row += 1
    if not tools:
        return solid
    return solid.cut(Part.makeCompound(tools))


def _plain(p):
    x, y, z, dx, dy, dz = _box(p)
    return Part.makeBox(dx, dy, dz, V(x, y, z))


def _env(p):
    return detail.envelope(p)


# --------------------------------------------------------------- builders
def kiln_wall(p):
    env = _env(p)
    x, y, z, dx, dy, dz = _box(p)
    # the seams go on the two large faces
    thin = min(range(3), key=lambda i: p.s[i])
    faces = [("xyz"[thin]) + "-", ("xyz"[thin]) + "+"]
    return [("blocks", _seams(_plain(p), env, faces), RED)]


def pedestal(p):
    env = _env(p)
    return [("blocks", _seams(_plain(p), env, ["x-", "x+", "y-", "y+"], pv=15.0), BLACK)]


def roof(p):
    env = _env(p)
    x, y, z, dx, dy, dz = _box(p)
    body = _seams(_plain(p), env, ["z+"], ph=30.0)
    caps, pockets = [], []
    cs, ch = 6.0, 3.0                      # red cap 6 x 6, 3 deep, flush with the top
    for yy in (y + 7.5, y + dy - 7.5):
        k = x + 15.0
        while k < x + dx - 10:
            b = Part.makeBox(cs, cs, ch, V(k - cs / 2, yy - cs / 2, z + dz - ch))
            pockets.append(b)
            caps.append(b.copy())
            k += 30.0
    body = body.cut(Part.makeCompound(pockets))
    return [("plates", body, BLACK), ("red_caps", Part.makeCompound(caps), RED)]


def door(p):
    env = _env(p)
    x, y, z, dx, dy, dz = _box(p)
    thin = min(range(3), key=lambda i: p.s[i])
    body = _seams(_plain(p), env, [("xyz"[thin]) + "+"], ph=30.0, pv=30.0, bond=False)
    # black guide shoes at both ends of the long horizontal edge, inside the panel
    long = max((i for i in range(3) if i != 2), key=lambda i: p.s[i])
    shoes = []
    for end in (0, 1):
        o = [x, y, z]
        s = [dx, dy, 20.0]
        s[long] = 8.0
        o[long] = (x, y, z)[long] + (0 if end == 0 else p.s[long] - 8.0)
        o[2] = z + dz / 2 - 10.0
        shoes.append(Part.makeBox(*s, V(*o)))
    body = body.cut(Part.makeCompound(shoes))
    return [("panel", body, RED), ("guide_shoes", Part.makeCompound([sh.copy() for sh in shoes]), BLACK)]


def lamp(p):
    x, y, z, dx, dy, dz = _box(p)
    sock_h = dz / 2
    sock = detail.rounded_box(dx, dy, sock_h, (x, y, z + dz - sock_h))
    r = min(dx, dy) / 2 - 1.0
    lens_h = dz - sock_h
    lens = Part.makeCylinder(min(r, lens_h * 0.9), lens_h, V(x + dx / 2, y + dy / 2, z))
    try:
        lens = lens.makeFillet(min(r, lens_h * 0.9) * 0.6,
                               [e for e in lens.Edges if abs(e.BoundBox.ZMin - z) < 1e-6])
    except Exception:
        pass
    return [("socket", sock, BLACK), ("lens", lens, LENS)]


def axle_rail(p):
    """Box envelope -> steel axle along the long axis + two red end blocks."""
    x, y, z, dx, dy, dz = _box(p)
    ax = max(range(3), key=lambda i: p.s[i])
    w = min(d for i, d in enumerate(p.s) if i != ax)
    L = p.s[ax]
    end = min(15.0, L / 6)
    c = [x + dx / 2, y + dy / 2, z + dz / 2]
    o = list(c); o[ax] = (x, y, z)[ax] + end
    dirv = V(*[1.0 if i == ax else 0.0 for i in range(3)])
    rod = Part.makeCylinder(w * 0.4, L - 2 * end, V(*o), dirv)
    blocks = []
    for k in (0, 1):
        bo = [x, y, z]
        bs = [dx, dy, dz]
        bs[ax] = end
        bo[ax] = (x, y, z)[ax] + (0 if k == 0 else L - end)
        blocks.append(detail.rounded_box(bs[0], bs[1], bs[2], tuple(bo)))
    return [("axle", rod, STEEL), ("end_blocks", Part.makeCompound(blocks), RED)]


def tray(p):
    x, y, z, dx, dy, dz = _box(p)
    body = detail.rounded_box(dx, dy, dz, (x, y, z))
    nest_r = min(dx, dy) / 2 - 1.5
    nest = Part.makeCylinder(nest_r, 2.0, V(x + dx / 2, y + dy / 2, z + dz - 2.0))
    return [("tray", body.cut(nest), RED)]


def profile(p):
    from types import SimpleNamespace
    q = SimpleNamespace(**{**p.__dict__, "mech": "profile:15"})
    return [("profile", detail.slotted_profile(q), ALU)]


def round_rod(p):
    x, y, z, dx, dy, dz = _box(p)
    ax = max(range(3), key=lambda i: p.s[i])
    w = min(d for i, d in enumerate(p.s) if i != ax)
    o = [x + dx / 2, y + dy / 2, z + dz / 2]
    o[ax] = (x, y, z)[ax]
    dirv = V(*[1.0 if i == ax else 0.0 for i in range(3)])
    return [("rod", detail.chamfered_cyl(w / 2, p.s[ax]).transformGeometry(
        App.Placement(V(*o), App.Rotation(V(0, 0, 1), dirv)).toMatrix()), STEEL)]


def strut(p):
    """ft Statik strut: black, a row of 4.1 mm holes at 15 mm pitch through the
    thinnest direction, along the longest."""
    x, y, z, dx, dy, dz = _box(p)
    body = _plain(p)
    thin = min(range(3), key=lambda i: p.s[i])
    long = max(range(3), key=lambda i: p.s[i])
    mid = 3 - thin - long
    n_rows = max(1, int(p.s[mid] // 15.0))
    holes = []
    for r in range(n_rows):
        cm = (x, y, z)[mid] + (p.s[mid] - (n_rows - 1) * 15.0) / 2 + r * 15.0
        t = (x, y, z)[long] + 7.5
        while t < (x, y, z)[long] + p.s[long] - 5:
            o = [0.0, 0.0, 0.0]
            o[thin] = (x, y, z)[thin] - 0.1
            o[long] = t
            o[mid] = cm
            dirv = V(*[1.0 if i == thin else 0.0 for i in range(3)])
            holes.append(Part.makeCylinder(2.05, p.s[thin] + 0.2, V(*o), dirv))
            t += 15.0
    return [("strut", body.cut(Part.makeCompound(holes)), BLACK)]


def blade(p):
    ax, L, d = p.s
    r = d / 2
    disc = Part.makeCylinder(r, L)
    n, depth = 24, max(1.0, 0.1 * r)
    teeth = []
    for k in range(n):
        a = 2 * math.pi * k / n
        b = 2 * math.pi * (k + 0.55) / n
        pts = [V(r * 1.2 * math.cos(a), r * 1.2 * math.sin(a), -0.1),
               V((r - depth) * math.cos(a), (r - depth) * math.sin(a), -0.1),
               V(r * 1.2 * math.cos(b), r * 1.2 * math.sin(b), -0.1)]
        f = Part.Face(Part.makePolygon(pts + [pts[0]]))
        teeth.append(f.extrude(V(0, 0, L + 0.2)))
    disc = disc.cut(Part.makeCompound(teeth))
    disc = disc.cut(Part.makeCylinder(min(2.0, r / 4), L + 0.2, V(0, 0, -0.1)))
    disc.Placement = detail._axis_placement(p).multiply(disc.Placement)
    return [("blade", disc.copy(), STEEL)]


def gear_disc(p):
    ax, L, d = p.s
    r = d / 2
    disc = Part.makeCylinder(r, L)
    n, depth, rim_h = 96, 2.0, min(6.0, L / 2)
    teeth = []
    for k in range(n):
        a = 2 * math.pi * (k + 0.5) / n
        w = 2 * math.pi * r / n * 0.45
        b = Part.makeBox(depth + 0.2, w, rim_h + 0.1, V(r - depth, -w / 2, -0.1))
        b.rotate(V(0, 0, 0), V(0, 0, 1), math.degrees(a))
        teeth.append(b)
    disc = disc.cut(Part.makeCompound(teeth))
    disc.Placement = detail._axis_placement(p).multiply(disc.Placement)
    return [("disc", disc.copy(), RED)]


def ribbed_belt(p):
    x, y, z, dx, dy, dz = _box(p)
    body = _plain(p)
    long = max(range(2), key=lambda i: p.s[i])
    ribs, t = [], (x, y)[long] + 5.0
    while t < (x, y)[long] + p.s[long] - 3:
        o = [x, y, z + dz - 0.6]
        s = [dx, dy, 0.7]
        o[long], s[long] = t, 1.5
        ribs.append(Part.makeBox(*s, V(*o)))
        t += 8.0
    return [("belt", body.cut(Part.makeCompound(ribs)), RUBBER)]


RICH = {
    "oven_wall_back": kiln_wall, "oven_wall_L": kiln_wall, "oven_wall_R": kiln_wall,
    "oven_front_lintel": kiln_wall, "oven_pedestal": pedestal, "oven_roof": roof,
    "Q13_oven_door": door, "Q9_oven_lamp": lamp, "slider_rail": axle_rail,
    "ofenschieber_tray": tray, "sauger_rail": profile,
    "door_guide_L": round_rod, "door_guide_R": round_rod,
    "saw_column": strut, "saw_arm": strut, "saw_blade": blade,
    "drehtisch_disc": gear_disc, "belt_web": ribbed_belt,
}
MODULES = {"oven"}


def rich(p, module):
    """Sub-solids for part p, or None. Asserts every sub-shape is inside p's envelope."""
    if module not in MODULES or p.name not in RICH:
        return None
    subs = RICH[p.name](p)
    env = detail.envelope(p)
    for nm, s, col in subs:
        bb = s.optimalBoundingBox(True, False)
        lo, hi = (bb.XMin, bb.YMin, bb.ZMin), (bb.XMax, bb.YMax, bb.ZMax)
        if any(lo[i] < env[i] - TOL or hi[i] > env[i + 3] + TOL for i in range(3)):
            raise AssertionError(f"{p.name}.{nm}: rich detail leaves its envelope "
                                 f"{[round(v, 2) for v in lo + hi]} vs {env}")
        if s.Volume <= 0:
            raise AssertionError(f"{p.name}.{nm}: empty shape")
    return subs
