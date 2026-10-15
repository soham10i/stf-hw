"""
Precise B-rep geometry for every part - runs INSIDE FreeCAD (freecadcmd).

The models (hbw_model, vgr_model, oven_model, sorting_model) describe each part
as a box or a cylinder: that is the ENVELOPE every clearance proof, the swept
path check and the pipeline were run against. This module turns each envelope
into the real shape:

  box            ft building block: all edges rounded (r <= 1 mm)
  plain cylinder chamfered ends
  thread:*       spindle with a true helical 4 mm-lead thread (core + V ridge)
  spring         guide rod inside a helical compression spring
  suction_cup    rubber cone with a neck, not a drum
  belt:loop      toothed drive belt wrapped round its two pulleys
  wp_* cookies   rounded top edge

The one rule that keeps every proof valid: A PRECISE SHAPE NEVER LEAVES ITS
ENVELOPE. precise() asserts it for every part, so detail can only ever remove
material relative to what was checked - it cannot introduce a collision.
"""
import math

import FreeCAD as App
import Part

V = App.Vector
TOL = 0.02          # mm a detailed shape may exceed its envelope (kernel noise)
_thread_cache = {}


def envelope(p):
    x, y, z = p.p
    if p.kind == "box":
        dx, dy, dz = p.s
        return (x, y, z, x + dx, y + dy, z + dz)
    ax, L, d = p.s
    r = d / 2.0
    if ax == "x":
        return (x, y - r, z - r, x + L, y + r, z + r)
    if ax == "y":
        return (x - r, y, z - r, x + r, y + L, z + r)
    return (x - r, y - r, z, x + r, y + r, z + L)


def _axis_placement(p):
    """Placement that maps a local Z-cylinder from the origin onto the part."""
    ax = p.s[0]
    rot = {"z": App.Rotation(),
           "x": App.Rotation(V(0, 1, 0), 90),
           "y": App.Rotation(V(1, 0, 0), -90)}[ax]
    return App.Placement(V(*p.p), rot)


# ------------------------------------------------------------------ blocks
def rounded_box(dx, dy, dz, origin):
    """ft block with bevelled edges. A chamfer, not a fillet: it reads the same
    at this scale, and its faces are planar - ~50 triangles per block instead
    of ~9000 for a filleted one, which is what keeps the web model loadable."""
    b = Part.makeBox(dx, dy, dz, V(*origin))
    c = min(0.8, 0.2 * min(dx, dy, dz))
    if c < 0.25:
        return b
    try:
        return b.makeChamfer(c, b.Edges)
    except Exception:
        return b


def chamfered_cyl(r, L, c=0.6):
    s = Part.makeCylinder(r, L)
    c = min(c, 0.15 * r, 0.2 * L)
    if c < 0.15:
        return s
    try:
        return s.makeChamfer(c, [e for e in s.Edges if e.Curve.TypeId == "Part::GeomCircle"])
    except Exception:
        return s


# ----------------------------------------------------------------- threads
def _thread_segment(d, pitch, turns):
    """One `turns`-long ridge of a 60-degree V thread on a core of radius rc."""
    key = (d, pitch, turns)
    if key in _thread_cache:
        return _thread_cache[key]
    depth = 0.30 * pitch if d >= 10 else 0.22 * pitch
    rc = d / 2.0 - depth
    h = pitch * 0.40
    helix = Part.makeHelix(pitch, pitch * turns, rc)
    prof = Part.makePolygon([V(rc - 0.05, 0, -h), V(rc + depth, 0, -0.07),
                             V(rc + depth, 0, 0.07), V(rc - 0.05, 0, h),
                             V(rc - 0.05, 0, -h)])
    seg = Part.Wire(helix).makePipeShell([prof], True, True)
    _thread_cache[key] = (seg, rc)
    return seg, rc


def threaded_rod(d, L, pitch=4.0):
    """Core + stacked exact copies of a 10-turn ridge, trimmed to [0, L].
    (A single sweep over 100+ turns fails inside OpenCASCADE's pipe shell; the
    thread is periodic in z, so copies placed n*10*pitch apart are seamless.)"""
    turns = 10
    seg, rc = _thread_segment(d, pitch, turns)
    step = pitch * turns
    parts = [Part.makeCylinder(rc + 0.02, L)]
    n = int(math.ceil(L / step)) + 1
    clip = Part.makeCylinder(d / 2.0 + 1.0, L)
    for i in range(-1, n):
        z0 = i * step
        c = seg.copy()
        c.translate(V(0, 0, z0 + pitch / 2.0))
        if z0 + pitch / 2.0 - pitch < 0 or z0 + step + pitch > L:
            c = c.common(clip)                         # trim at the rod ends
            if c.isNull() or not c.Solids:
                continue
        parts.append(c)
    return Part.makeCompound(parts)


# ---------------------------------------------------------------- VGR tool
def spring_stem(L, d_env):
    """Guide rod on the axis inside a closed-end compression spring."""
    rod = Part.makeCylinder(2.6, L)
    wire_r, coil_r, turns = 0.9, min(7.0, d_env / 2.0 - 1.2), 7
    top = L - 2.0                                      # spring from z=2 (cup top) up
    helix = Part.makeHelix((top - 2.0 - 2 * wire_r) / turns, top - 2.0 - 2 * wire_r, coil_r)
    helix.translate(V(0, 0, 2.0 + wire_r))
    ring = Part.Wire(Part.makeCircle(wire_r, V(coil_r, 0, 2.0 + wire_r), V(0, 1, 0)))
    coil = Part.Wire(helix).makePipeShell([ring], True, True)
    return Part.makeCompound([rod, coil])


def suction_cup(d, h):
    """Rubber cup: flared lip at the bottom, neck at the top."""
    lip = Part.makeCone(d / 2.0, d / 2.0 * 0.45, h - 2.0)
    neck = Part.makeCylinder(d / 2.0 * 0.45, 2.0, V(0, 0, h - 2.0))
    cavity = Part.makeCone(d / 2.0 - 1.6, d / 2.0 * 0.45 - 1.6, h - 3.5)
    return lip.cut(cavity).fuse(neck).removeSplitter()


# -------------------------------------------------------------- belt drive
def belt_loop(env, a, b, width, pitch_r, thick=1.6, tooth=1.2, tpitch=5.0):
    """A closed toothed belt in the y-z plane round two pulley centres a, b,
    extruded `width` along +x from env x0. Teeth on the INSIDE face."""
    (ya, za), (yb, zb) = a, b
    x0 = env[0] + 1.0
    A, B = V(x0, ya, za), V(x0, yb, zb)
    dvec = B - A
    L1 = dvec.Length
    dn = V(0, dvec.y / L1, dvec.z / L1)
    nn = V(0, -dn.z, dn.y)

    def loop(r):
        p1, p2 = A + nn * r, B + nn * r
        p3, p4 = B - nn * r, A - nn * r
        e1 = Part.LineSegment(p1, p2).toShape()
        e2 = Part.Arc(p2, B + dn * r, p3).toShape()
        e3 = Part.LineSegment(p3, p4).toShape()
        e4 = Part.Arc(p4, A - dn * r, p1).toShape()
        return Part.Face(Part.Wire([e1, e2, e3, e4]))

    band = loop(pitch_r + thick).cut(loop(pitch_r)).extrude(V(width, 0, 0))
    # teeth on the INSIDE face of the two straight runs (the wraps sit on the
    # pulleys). Local frame of a tooth: y along the run, z along the normal.
    rot = App.Rotation(V(1, 0, 0), math.degrees(math.atan2(dn.z, dn.y)))
    teeth = []
    n = int(L1 // tpitch)
    for side in (1, -1):
        off = (pitch_r - tooth) if side == 1 else -pitch_r
        for i in range(2, n - 1):
            t = Part.makeBox(width, tpitch * 0.45, tooth)
            t.Placement = App.Placement(A + dn * (i * tpitch) + nn * off, rot)
            teeth.append(t)
    return Part.makeCompound([band] + teeth)


# --------------------------------------------------------------- dispatch
def slotted_profile(p):
    """Aluminium profile along its long axis: square section with a T-slot in
    each face and a centre bore (ft-style 15 mm profile; slot sizes scale with
    the section and are 'assumed' - the ft groove mouth 3.2 / inner 4.4 / depth
    3.6 at 15 mm, as in components.py)."""
    dims = list(p.s)
    ax = max(range(3), key=lambda i: dims[i])
    w = min(d for i, d in enumerate(dims) if i != ax)
    L = dims[ax]
    k = w / 15.0
    mouth, inner, depth, neck, bore = 3.2 * k, 4.4 * k, 3.6 * k, 1.2 * k, 4.2 * k
    s = Part.makeBox(w, w, L)
    cut = [Part.makeCylinder(bore / 2, L, V(w / 2, w / 2, 0))]
    for f in range(4):
        # slot on face f: neck (mouth wide) then the wider inner chamber
        n = Part.makeBox(mouth, neck + 0.01, L, V((w - mouth) / 2, -0.01, 0))
        i = Part.makeBox(inner, depth - neck, L, V((w - inner) / 2, neck, 0))
        sl = n.fuse(i)
        sl.rotate(V(w / 2, w / 2, 0), V(0, 0, 1), 90 * f)
        cut.append(sl)
    s = s.cut(Part.makeCompound(cut))
    try:
        s = s.makeChamfer(min(0.5, 0.05 * w), [e for e in s.Edges if
                                               abs(e.Curve.Direction.z) > 0.99 and
                                               e.Length > L - 1e-6
                                               and (abs(e.Vertexes[0].X) < 1e-6 or abs(e.Vertexes[0].X - w) < 1e-6)
                                               and (abs(e.Vertexes[0].Y) < 1e-6 or abs(e.Vertexes[0].Y - w) < 1e-6)])
    except Exception:
        pass
    # local z -> the long axis, then to the part's origin
    rot = {2: App.Rotation(), 0: App.Rotation(V(0, 1, 0), 90), 1: App.Rotation(V(1, 0, 0), -90)}[ax]
    s.Placement = App.Placement(V(), rot)
    s = s.copy()
    bb = s.BoundBox
    s.translate(V(p.p[0] - bb.XMin, p.p[1] - bb.YMin, p.p[2] - bb.ZMin))
    return s


def precise(p, siblings=None):
    """The detailed shape for part p, guaranteed inside envelope(p)."""
    env = envelope(p)
    s = _precise(p, siblings or {})
    # EXACT extent: BoundBox includes spline control points and overstates
    # swept threads and fillets by millimetres
    bb = s.optimalBoundingBox(True, False)
    lo = (bb.XMin, bb.YMin, bb.ZMin)
    hi = (bb.XMax, bb.YMax, bb.ZMax)
    if any(lo[i] < env[i] - TOL or hi[i] > env[i + 3] + TOL for i in range(3)):
        # detail must only ever REMOVE material from the proven envelope
        raise AssertionError(f"{p.name}: detail leaves its checked envelope "
                             f"({[round(v, 2) for v in lo + hi]} vs {env})")
    return s


def _precise(p, sib):
    if p.kind == "box" and p.mech.startswith("profile:"):
        return slotted_profile(p)
    if p.kind == "box":
        if p.mech == "belt:loop":
            a, b = sib.get("M1_drive_pulley"), sib.get("M1_drum_pulley")
            if a and b:
                return belt_loop(envelope(p), (a.p[1], a.p[2]), (b.p[1], b.p[2]),
                                 p.s[0] - 2.0, a.s[2] / 2.0)
        dx, dy, dz = p.s
        return rounded_box(dx, dy, dz, p.p)

    ax, L, d = p.s
    pl = _axis_placement(p)
    if p.mech.startswith("thread:"):
        s = threaded_rod(d, L)
    elif p.mech == "spring":
        s = spring_stem(L, d)
    elif p.name.endswith("suction_cup") and ax == "z":
        s = suction_cup(d, L)
    elif p.name.startswith("wp_") and ax == "z" and L > 6:
        s = Part.makeCylinder(d / 2.0, L)
        try:
            s = s.makeFillet(min(1.5, L / 4), [e for e in s.Edges
                                                if abs(e.BoundBox.ZMin - L) < 1e-6])
        except Exception:
            pass
    else:
        s = chamfered_cyl(d / 2.0, L)
    s = s.copy()
    s.Placement = pl.multiply(s.Placement)
    return s
