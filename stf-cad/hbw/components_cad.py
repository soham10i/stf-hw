"""
Build the nine ft components of the STF as precise FreeCAD solids: the four
with ft datasheets, and the five further parts of the booklet's
Bauteilbeschreibung (S-Motor, Kompressor, Pneumatikzylinder, IR-Spursensor,
3/2-Wege-Magnetventil).

    /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd components_cad.py

Reads components.py (the one parameter table) and writes, per component:
  ~/workspace/stf-factory/cad/components/<id>.FCStd  coloured, framed, sub-parts named
  ~/workspace/stf-factory/cad/components/<id>.step
  ~/workspace/stf-hw/web/public/components/<id>.glb   the same B-rep, tessellated
  ~/workspace/stf-hw/web/public/components/components.json   specs, dims, sources,
                                                              verification, where used

Accuracy is CHECKED, not claimed: every housing's exact bounding box must equal
its datasheet envelope within 0.01 mm, the shaft's across-flats must equal
4.0 - 2 x 0.7 within 0.01 mm, and the web mesh is tessellated with a 0.01 mm
chordal tolerance. Nothing is written if a check fails.
"""
import json, math, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App
import Part

import components as C

V = App.Vector
CAD_DIR = os.path.expanduser("~/workspace/stf-factory/cad/components")
WEB_DIR = os.path.expanduser("~/workspace/stf-hw/web/public/components")
TOL_MM = 0.01
COLOURS = {"ftred": "#d8261c", "black": "#2a2b2e", "ftyellow": "#f2c21b", "red": "#e0312a",
           "steel": "#b9bec4", "brass": "#c9a24a", "clear": "#d9eef7", "green": "#1f8a4c",
           "wire_red": "#d22b2b", "wire_green": "#25a244", "wire_black": "#1a1a1a",
           "wire_yellow": "#e8c21f", "led": "#f5f1e6", "sensor": "#141414",
           "blue": "#1f63c4", "grey": "#8f959b", "ir": "#3a1f4a", "pom": "#e9e6dc",
           "rubber": "#26282b", "spring_red": "#c8231b"}


# ----------------------------------------------------------------- helpers
def bevelled_box(L, W, H, e):
    b = Part.makeBox(L, W, H)
    return b.makeChamfer(e, b.Edges) if e > 0 else b


def dovetail_along_x(L, yc, top, mouth, inner, depth):
    """A dovetail groove prism running the full length along X, opening at z=top."""
    pts = [V(-1, yc - mouth / 2, top + 0.01), V(-1, yc + mouth / 2, top + 0.01),
           V(-1, yc + inner / 2, top - depth), V(-1, yc - inner / 2, top - depth),
           V(-1, yc - mouth / 2, top + 0.01)]
    return Part.Face(Part.makePolygon(pts)).extrude(V(L + 2, 0, 0))


def rot_about_x(shape, deg, yc, zc):
    s = shape.copy()
    s.rotate(V(0, yc, zc), V(1, 0, 0), deg)
    return s


def hole(d, depth, at, direction):
    """Blind hole of diameter d, `depth` deep, drilled from point `at` along `direction`."""
    return Part.makeCylinder(d / 2, depth + 0.01, at - direction * 0.01, direction)


# ------------------------------------------------------------- components
def encoder_motor():
    g = lambda k: C.get("encoder_motor", k)
    L, W, H = g("L"), g("W"), g("H")
    body = bevelled_box(L, W, H, g("edge"))
    m, i, dp = g("g_mouth"), g("g_inner"), g("g_depth")
    cuts = [dovetail_along_x(L, g("groove_top_y"), H, m, i, dp),
            dovetail_along_x(L, W - g("groove_top_y"), H, m, i, dp)]
    centre = dovetail_along_x(L, W / 2, H, m, i, dp)
    for deg in (90, -90, 180):                       # both sides + the bottom
        cuts.append(rot_about_x(centre, deg, W / 2, H / 2))
    # far end face (+X): two plug sockets in rectangular recesses, encoder header below
    for yc in (W / 2 - g("sock_pitch") / 2, W / 2 + g("sock_pitch") / 2):
        sw, sh, sd = g("slot_w"), g("slot_h"), g("slot_depth")
        cuts.append(Part.makeBox(sd + 0.01, sw, sh, V(L - sd, yc - sw / 2, H / 2 - sh / 2)))
        cuts.append(hole(g("sock_d"), g("sock_depth"), V(L - sd, yc, H / 2), V(-1, 0, 0)))
    hw, hh = g("hdr_w"), g("hdr_h")
    cuts.append(Part.makeBox(4.01, hw, hh, V(L - 4, W / 2 - hw / 2, 3.0)))
    for c in cuts:
        body = body.cut(c)
    body = body.removeSplitter()

    # output shaft on the -X face, two flats, and its bearing collar
    r = g("shaft_d") / 2
    shaft = Part.makeCylinder(r, g("shaft_l") + 1.0, V(1.0, W / 2, H / 2), V(-1, 0, 0))
    keep = r - g("flat")
    for s in (1, -1):
        slab = Part.makeBox(g("shaft_l") + 2, 2 * r + 2, r, V(-g("shaft_l") - 1, W / 2 - r - 1,
                            H / 2 + s * keep if s > 0 else H / 2 - keep - r))
        shaft = shaft.cut(slab)
    collar = Part.makeCylinder(g("collar_d") / 2, g("collar_h"), V(0, W / 2, H / 2), V(-1, 0, 0))
    pins = [Part.makeBox(1.5, 0.64, 0.64, V(L - 4 + 0.5, W / 2 - hw / 2 + 1.27 + k * 2.54 - 0.32,
                                             3.0 + hh / 2 - 0.32)) for k in range(4)]
    return [("housing", body, "ftred", "abs", True),
            ("output_shaft", shaft.removeSplitter(), "steel", "steel", False),
            ("bearing_collar", collar, "black", "abs", False),
            ("encoder_header_pins", Part.makeCompound(pins), "brass", "brass", True)]


def mini_switch():
    g = lambda k: C.get("mini_switch", k)
    L, W, H = g("L"), g("W"), g("H")
    body = bevelled_box(L, W, H, g("edge"))
    for zc in (g("contact_z"), g("contact_z") + 4.0, g("contact_z") + 8.0):
        body = body.cut(hole(g("contact_d"), g("contact_depth"), V(g("contact_x"), 0, zc), V(0, 1, 0)))
    body = body.removeSplitter()
    bl, bw, bh = g("btn_l"), g("btn_w"), g("btn_h")
    btn = Part.makeBox(bl, bw, bh + 1.0, V(g("btn_x"), W / 2 - bw / 2, H - 1.0))
    btn = btn.makeChamfer(0.4, [e for e in btn.Edges if abs(e.BoundBox.ZMax - (H + bh)) < 1e-6])
    tl, tw, th = g("tab_l"), g("tab_w"), g("tab_h")
    tabs = Part.makeCompound([Part.makeBox(tl, tw, th, V(-tl, W / 2 - tw / 2, 2.0)),
                              Part.makeBox(tl, tw, th, V(L, W / 2 - tw / 2, H - 2.0 - th))])
    return [("housing", body, "black", "abs", True),
            ("actuator", btn, "red", "abs", False),
            ("mounting_tabs", tabs, "black", "abs", False)]


def phototransistor():
    g = lambda k: C.get("phototransistor", k)
    L, W, H = g("L"), g("W"), g("H")
    body = bevelled_box(L, W, H, g("edge"))
    wl, ww, wd = g("win_l"), g("win_w"), g("win_depth")
    body = body.cut(Part.makeBox(wl, ww, wd + 0.01, V(L / 2 - wl / 2, W / 2 - ww / 2, H - wd)))
    for x in (g("sock_x"), L - g("sock_x")):
        body = body.cut(hole(g("sock_d"), g("sock_depth"), V(x, 0, H / 2), V(0, 1, 0)))
    mk = g("mark")
    body = body.cut(Part.makeBox(mk, mk, 0.21, V(L - mk - 1.2, W - mk - 1.2, H - 0.2)))
    body = body.removeSplitter()
    lens = Part.makeCylinder(g("lens_d") / 2, 0.8, V(L / 2, W / 2, H - wd))
    mark = Part.makeBox(mk, mk, 0.2, V(L - mk - 1.2, W - mk - 1.2, H - 0.2))
    return [("housing", body, "ftyellow", "abs", True),
            ("lens_window", lens, "clear", "clear", True),
            ("plus_marking", mark, "red", "paint", True)]


def colour_sensor():
    g = lambda k: C.get("colour_sensor", k)
    L, W, H = g("L"), g("W"), g("H")
    body = bevelled_box(L, W, H, g("edge"))
    body = body.cut(dovetail_along_x(L, W / 2, H, g("g_mouth"), g("g_inner"), g("g_depth")))
    xs = (g("hole_x"), g("hole_x") + 4.5)
    for x in xs:
        body = body.cut(hole(g("hole_d"), g("hole_depth"), V(x, 0, H / 2), V(0, 1, 0)))
    for yc in (W / 3, 2 * W / 3):                     # vertical fin slots on the +X end
        fw, fd = g("fin_w"), g("fin_depth")
        body = body.cut(Part.makeBox(fd + 0.01, fw, H - 2.0, V(L - fd, yc - fw / 2, 1.0)))
    body = body.removeSplitter()
    led = Part.makeCylinder(g("hole_d") / 2 - 0.2, 0.6, V(xs[0], g("hole_depth"), H / 2), V(0, -1, 0))
    rx = Part.makeCylinder(g("hole_d") / 2 - 0.2, 0.6, V(xs[1], g("hole_depth"), H / 2), V(0, -1, 0))
    wd, wl = g("wire_d"), g("wire_l")
    wires = [(f"wire_{c}", Part.makeCylinder(wd / 2, wl, V(5.0 + 2.0 * k, W / 2, 0), V(0, 0, -1)),
              f"wire_{c}", "pvc", False) for k, c in enumerate(("red", "green", "black"))]
    return [("housing", body, "black", "abs", True),
            ("emitter_led", led, "led", "clear", True),
            ("receiver", rx, "sensor", "glass", True)] + wires


def coil_spring(r, wire_r, L, turns):
    """A compression spring along +Z from z=0 to z=L."""
    pitch = (L - 2 * wire_r) / turns
    helix = Part.makeHelix(pitch, L - 2 * wire_r, r)
    helix.translate(V(0, 0, wire_r))
    ring = Part.Wire(Part.makeCircle(wire_r, V(r, 0, wire_r), V(0, 1, 0)))
    return Part.Wire(helix).makePipeShell([ring], True, True)


def along_x(shape, at):
    """Turn a +Z-built shape to run along +X, then place its origin at `at`."""
    s = shape.copy()
    s.rotate(V(0, 0, 0), V(0, 1, 0), 90)
    s.translate(at)
    return s


def shell(L, W, H, e, wall):
    body = bevelled_box(L, W, H, e)
    return body.cut(Part.makeBox(L - 2 * wall, W - 2 * wall, H - 2 * wall, V(wall, wall, wall)))


def gear(d, t, teeth, at, axis):
    """A spur/worm wheel: disc with `teeth` notches, so its rotation reads."""
    g = Part.makeCylinder(d / 2, t)
    for k in range(teeth):
        a = 2 * math.pi * k / teeth
        n = Part.makeBox(1.2, 1.2, t + 0.2, V(-0.6, -0.6, -0.1))
        n.rotate(V(0, 0, 0), V(0, 0, 1), math.degrees(a))
        n.translate(V((d / 2) * math.cos(a), (d / 2) * math.sin(a), 0))
        g = g.cut(n)
    if axis == "y":
        g.rotate(V(0, 0, 0), V(1, 0, 0), -90)
    g.translate(at)
    return g.removeSplitter()


def s_motor():
    g = lambda k: C.get("s_motor", k)
    L, W, H = g("L"), g("W"), g("H")
    body = bevelled_box(L, W, H, g("edge"))
    m, i, dp = g("g_mouth"), g("g_inner"), g("g_depth")
    for yc in (7.5, W - 7.5):
        body = body.cut(dovetail_along_x(L, yc, H, m, i, dp))
    for yc in (10.0, 20.0):
        body = body.cut(hole(g("sock_d"), 6.0, V(0, yc, H / 2), V(1, 0, 0)))
    body = body.removeSplitter()
    import detail
    worm = along_x(detail.threaded_rod(g("worm_d"), g("worm_l") - 2, 1.5), V(L + 2, W / 2, H / 2))
    shaft = Part.makeCylinder(g("shaft_d") / 2, g("worm_l"), V(L, W / 2, H / 2), V(1, 0, 0))
    worm_shaft = Part.makeCompound([shaft, worm])
    gl, gw, gh = g("gb_l"), g("gb_w"), g("gb_h")
    gb = shell(gl, gw, gh, 0.5, 1.5)
    gb.translate(V(L, 0, 0))
    gb = gb.cut(Part.makeCylinder(g("worm_d") / 2 + 0.6, 3, V(L - 0.5, W / 2, H / 2), V(1, 0, 0)))
    wx, wz = L + 12.0, H / 2 + g("worm_d") / 2 + g("wheel_d") / 2 - 0.5
    wheel = gear(g("wheel_d"), 4.0, 20, V(wx, W / 2 - 2.0, wz), "y")
    gb = gb.cut(Part.makeCylinder(g("axle_d") / 2 + 0.3, 3, V(wx, -0.5, wz), V(0, 1, 0)))
    axle = Part.makeCylinder(g("axle_d") / 2, W / 2 - 2.0 + g("axle_l"), V(wx, W / 2 - 2.0, wz),
                             V(0, -1, 0))
    return [("housing", body, "black", "abs", True),
            ("worm_shaft", worm_shaft, "steel", "steel", False),
            ("u_gearbox", gb.removeSplitter(), "black", "abs", False),
            ("worm_wheel", wheel, "pom", "pom", False),
            ("output_axle", axle, "steel", "steel", False)]


def compressor():
    g = lambda k: C.get("compressor", k)
    L, W, H = g("L"), g("W"), g("H")
    body = shell(L, W, H, g("edge"), 1.5)
    m, i, dp = g("g_mouth"), g("g_inner"), g("g_depth")
    for yc in (7.5, W - 7.5):
        body = body.cut(dovetail_along_x(L, yc, H, m, i, dp))
    body = body.cut(Part.makeCylinder(1.2, 3, V(L - 2, W / 2, H / 2), V(1, 0, 0)))
    body = body.removeSplitter()
    nip = Part.makeCylinder(g("nip_d") / 2, g("nip_l"), V(L, W / 2, H / 2), V(1, 0, 0))
    nip = nip.cut(Part.makeCylinder(0.9, g("nip_l") + 1, V(L - 0.5, W / 2, H / 2), V(1, 0, 0)))
    cx, cz = 30.0, H / 2
    motor = Part.makeCylinder(7.0, 12.0, V(cx, 1.5, cz), V(0, 1, 0))
    crank = Part.makeCylinder(5.0, 3.0, V(cx, 13.5, cz), V(0, 1, 0))
    r = g("crank_r")
    pin = Part.makeCylinder(1.0, 2.5, V(cx + r, 16.5, cz), V(0, 1, 0))
    rod = Part.makeBox(10.0, 2.0, 2.0, V(cx + r, 16.8, cz - 1.0))
    pis = Part.makeCylinder(g("piston_d") / 2, 4.0, V(cx + r + 10.0, W / 2, cz), V(1, 0, 0))
    bore = Part.makeCylinder(5.5, 7.0, V(41.0, W / 2, cz), V(1, 0, 0)).cut(
        Part.makeCylinder(g("piston_d") / 2 + 0.2, 7.2, V(40.9, W / 2, cz), V(1, 0, 0)))
    mem = Part.makeCylinder(g("mem_d") / 2, 0.8, V(50.0, W / 2, cz), V(1, 0, 0))
    cover = Part.makeCone(11.0, 6.0, 6.0, V(51.0, W / 2, cz), V(1, 0, 0)).cut(
        Part.makeCone(10.0, 5.0, 5.0, V(51.0, W / 2, cz), V(1, 0, 0)))
    v_in = Part.makeBox(1.5, 3.0, 2.0, V(56.5, W / 2 - 1.5, cz - 4.0))
    v_out = Part.makeBox(1.5, 3.0, 2.0, V(56.5, W / 2 - 1.5, cz + 2.0))
    return [("housing", body, "blue", "abs", True),
            ("outlet_nipple", nip, "pom", "pom", False),
            ("motor", motor, "steel", "steel", True),
            ("crank", crank, "steel", "steel", True),
            ("crank_pin", pin, "steel", "steel", True),
            ("conrod", rod, "steel", "steel", True),
            ("piston", pis, "grey", "abs", True),
            ("piston_bore", bore, "grey", "abs", True),
            ("membrane", mem, "rubber", "rubber", True),
            ("cover_deckel", cover, "grey", "abs", True),
            ("inlet_valve", v_in, "spring_red", "rubber", True),
            ("outlet_valve", v_out, "spring_red", "rubber", True)]


def pneumatic_cylinder():
    g = lambda k: C.get("pneumatic_cylinder", k)
    L, W, H = g("L"), g("W"), g("H")
    fc, rc = g("cap_front"), g("cap_rear")
    yc, zc = W / 2, H / 2
    front = bevelled_box(fc, W, H, 0.4).cut(
        Part.makeCylinder(g("rod_d") / 2 + 0.3, fc + 1, V(-0.5, yc, zc), V(1, 0, 0)))
    rear = bevelled_box(rc, W, H, 0.4)
    rear.translate(V(L - rc, 0, 0))
    housing = Part.makeCompound([front.removeSplitter(), rear])
    bd = g("barrel_d")
    barrel = Part.makeCylinder(bd / 2, L - rc - fc, V(fc, yc, zc), V(1, 0, 0)).cut(
        Part.makeCylinder(bd / 2 - 1.0, L - rc - fc + 1, V(fc - 0.5, yc, zc), V(1, 0, 0)))
    t = g("tie_d") / 2
    ties = Part.makeCompound([Part.makeCylinder(t, L, V(0, y, z), V(1, 0, 0))
                              for y, z in ((1.8, 1.8), (W - 1.8, H - 1.8))])
    px = L - rc - 3.0
    piston = Part.makeCylinder(bd / 2 - 1.1, 3.0, V(px - 3.0, yc, zc), V(1, 0, 0))
    ro = g("rod_out")
    rod = Part.makeCylinder(g("rod_d") / 2, px - 3.0 + ro, V(-ro, yc, zc), V(1, 0, 0))
    rod_end = Part.makeCylinder(3.0, 4.0, V(-ro - 4.0, yc, zc), V(1, 0, 0))
    spring = along_x(coil_spring(3.2, 0.5, px - 3.0 - fc, 9), V(fc, yc, zc))
    nip = Part.makeCylinder(g("nip_d") / 2, 5.0, V(L - rc / 2, yc, H), V(0, 0, 1))
    return [("housing", housing, "black", "abs", True),
            ("barrel", barrel, "clear", "clear", True),
            ("tie_rods", ties, "steel", "steel", True),
            ("piston", piston, "black", "rubber", True),
            ("piston_rod", rod, "steel", "steel", False),
            ("rod_end", rod_end, "red", "abs", False),
            ("spring", spring, "spring_red", "steel", True),
            ("air_nipple", nip, "pom", "pom", False)]


def ir_track_sensor():
    g = lambda k: C.get("ir_track_sensor", k)
    L, W, H = g("L"), g("W"), g("H")
    body = bevelled_box(L, W, H, g("edge"))
    body = body.cut(dovetail_along_x(L, W / 2, H, 3.2, 4.4, 3.6))
    xs = (g("win_x"), L - g("win_x"))
    for x in xs:
        body = body.cut(hole(g("win_d"), 4.0, V(x, 0, H / 2), V(0, 1, 0)))
    for yy in (W / 3, 2 * W / 3):
        body = body.cut(Part.makeBox(1.51, g("fin_w"), H - 2.0, V(L - 1.5, yy - 0.6, 1.0)))
    body = body.removeSplitter()
    parts = [("housing", body, "grey", "abs", True)]
    for k, x in enumerate(xs):
        parts.append((f"emitter_{k + 1}", Part.makeCylinder(0.8, 0.6, V(x - 0.9, 4.0, H / 2),
                                                             V(0, -1, 0)), "ir", "glass", True))
        parts.append((f"receiver_{k + 1}", Part.makeCylinder(0.8, 0.6, V(x + 0.9, 4.0, H / 2),
                                                              V(0, -1, 0)), "sensor", "glass", True))
    for k, c in enumerate(("red", "green", "black", "yellow")):
        parts.append((f"wire_{c}", Part.makeCylinder(g("wire_d") / 2, g("wire_l"),
                                                     V(10.0 + 2.5 * k, W / 2, 0), V(0, 0, -1)),
                      f"wire_{c}", "pvc", False))
    return parts


def solenoid_valve():
    g = lambda k: C.get("solenoid_valve", k)
    L, W, H = g("L"), g("W"), g("H")
    t = g("plate_t")
    bracket = Part.makeCompound([Part.makeBox(L, W, t), Part.makeBox(L, W, t, V(0, 0, H - t)),
                                 Part.makeBox(t, W, H)])
    cw = g("coil_w"); cd = g("core_d")
    x0, yc = L / 2 - cw / 2, W / 2
    coil = Part.makeBox(cw, W - 2, H - 2 * t - 0.2, V(x0, 1, t + 0.1)).cut(
        Part.makeCylinder(cd / 2 + 0.3, H, V(L / 2, yc, 0), V(0, 0, 1)))
    plunger = Part.makeCylinder(cd / 2, 14.0, V(L / 2, yc, 4.0))
    spring = coil_spring(1.5, 0.35, H - t - 18.0, 4)
    spring.translate(V(L / 2, yc, 18.0))
    pP = Part.makeCylinder(g("nip_d") / 2, g("nip_l"), V(L / 2, yc, H)).cut(
        Part.makeCylinder(0.9, g("nip_l") + 1, V(L / 2, yc, H - 0.5)))
    pA = Part.makeCylinder(g("nip_d") / 2, g("nip_l"), V(L, yc, 17.0), V(1, 0, 0)).cut(
        Part.makeCylinder(0.9, g("nip_l") + 1, V(L - 0.5, yc, 17.0), V(1, 0, 0)))
    wires = [(f"wire_{c}", Part.makeCylinder(0.6, 12.0, V(0, yc, z), V(-1, 0, 0)),
              f"wire_{c}", "pvc", False) for c, z in (("red", 6.0), ("black", 9.0))]
    return [("housing", bracket, "grey", "steel", True),
            ("coil", coil.removeSplitter(), "blue", "abs", True),
            ("plunger", plunger, "steel", "steel", True),
            ("spring", spring, "steel", "steel", True),
            ("port_1_P", pP, "pom", "pom", False),
            ("port_2_A", pA, "pom", "pom", False)] + wires


BUILDERS = {"encoder_motor": encoder_motor, "mini_switch": mini_switch,
            "phototransistor": phototransistor, "colour_sensor": colour_sensor,
            "s_motor": s_motor, "compressor": compressor,
            "pneumatic_cylinder": pneumatic_cylinder, "ir_track_sensor": ir_track_sensor,
            "solenoid_valve": solenoid_valve}


# ----------------------------------------------------------- verification
def verify(cid, parts):
    """Exact geometry against the datasheet, to 0.01 mm."""
    comp = C.COMPONENTS[cid]
    res, fails = [], []
    L, W, H = C.get(cid, "L"), C.get(cid, "W"), C.get(cid, "H")
    housing = next(s for n, s, *_ in parts if n == "housing")
    bb = housing.optimalBoundingBox(True, False)
    got = (bb.XLength, bb.YLength, bb.ZLength)
    for lbl, want, have in zip(("length", "depth", "height"), (L, W, H), got):
        ok = abs(want - have) <= TOL_MM
        src = next(d["source"] for d in comp["dims"] if d["key"] == {"length": "L", "depth": "W",
                                                                     "height": "H"}[lbl])
        res.append({"check": f"housing {lbl}", "datasheet_mm": want, "model_mm": round(have, 4),
                    "ok": ok, "source": src})
        if not ok:
            fails.append(f"{cid}: housing {lbl} {have:.4f} != {want}")
    for n, s, *_ in parts:
        if not all(sol.isValid() for sol in s.Solids) or not s.Solids:
            fails.append(f"{cid}: {n} is not a valid solid")
    if cid == "encoder_motor":
        shaft = next(s for n, s, *_ in parts if n == "output_shaft")
        sb = shaft.optimalBoundingBox(True, False)
        want = C.get(cid, "shaft_d") - 2 * C.get(cid, "flat")
        for lbl, want_, have in (("shaft across flats", want, sb.ZLength),
                                 ("shaft diameter", C.get(cid, "shaft_d"), sb.YLength),
                                 ("shaft protrusion", C.get(cid, "shaft_l"), -sb.XMin)):
            ok = abs(want_ - have) <= TOL_MM
            res.append({"check": lbl, "datasheet_mm": round(want_, 3), "model_mm": round(have, 4),
                        "ok": ok})
            if not ok:
                fails.append(f"{cid}: {lbl} {have:.4f} != {want_}")
    return res, fails


# ---------------------------------------------------------------- output
def write_cad(cid, parts):
    import fcstd_colour
    for d in list(App.listDocuments()):
        App.closeDocument(d)
    doc = App.newDocument(cid)
    colour_of = {}
    cont = doc.addObject("App::Part", f"ft_{C.COMPONENTS[cid]['ft']}_{cid}")
    for n, s, col, mat, inside in parts:
        o = doc.addObject("Part::Feature", n)
        o.Shape = s
        o.addProperty("App::PropertyString", "Material", "STF").Material = mat
        o.addProperty("App::PropertyString", "Envelope", "STF").Envelope = \
            "inside datasheet envelope" if inside else "protrudes beyond datasheet envelope"
        cont.addObject(o)
        colour_of[o.Name] = COLOURS[col]
    doc.recompute()
    os.makedirs(CAD_DIR, exist_ok=True)
    fc = os.path.join(CAD_DIR, f"{cid}.FCStd")
    st = os.path.join(CAD_DIR, f"{cid}.step")
    import Import
    Import.export([cont], st)
    doc.saveAs(fc)
    bb = App.BoundBox()
    for _, s, *_ in parts:
        bb.add(s.BoundBox)
    fcstd_colour.colourise(fc, colour_of, camera=fcstd_colour.iso_camera(
        (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)))
    App.closeDocument(doc.Name)
    return fc, st


def write_glb(cid, parts):
    import stf_gltf as SG, stf_web_glb as WG
    g = WG.WebGltf()
    kids = []
    for n, s, col, mat, inside in parts:
        # 0.01 mm chord everywhere except swept helices (springs, worms), whose
        # thousands of tiny faces would otherwise weigh megabytes
        swept = n in ("spring", "worm_shaft")
        pos, nrm, idx = WG.face_mesh(s, (0.05, 0.35) if swept else (0.01, 0.1))
        g._cls = "metal" if mat in ("steel", "brass") else "plastic"
        m = g.mesh(n, pos, nrm, idx, COLOURS[col])
        kids.append(g.node(n, mesh=m, extras={"part": n, "material": mat, "colour": COLOURS[col],
                                              "inside_envelope": inside}))
    blob = g.glb(kids)
    os.makedirs(WEB_DIR, exist_ok=True)
    path = os.path.join(WEB_DIR, f"{cid}.glb")
    open(path, "wb").write(blob)
    ntri = sum(a["count"] for a in g.acc if a["type"] == "SCALAR") // 3
    return path, ntri


def main():
    manifest, all_fail = {}, []
    built = {}
    for cid, fn in BUILDERS.items():
        parts = fn()
        res, fails = verify(cid, parts)
        all_fail += fails
        built[cid] = (parts, res)
    if all_fail:
        print("REFUSING to write - components fail their accuracy checks:")
        print("\n".join(all_fail)); sys.exit(1)
    uses = C.used_in()
    for cid, (parts, res) in built.items():
        fc, st = write_cad(cid, parts)
        glb, ntri = write_glb(cid, parts)
        shutil.copy(st, os.path.join(WEB_DIR, f"{cid}.step"))
        comp = C.COMPONENTS[cid]
        bb = App.BoundBox()
        for _, s, *_ in parts:
            bb.add(s.optimalBoundingBox(True, False))
        manifest[cid] = {
            **{k: comp[k] for k in ("ft", "name", "name_de", "datasheet", "material")},
            "facts": [{"label": a, "value": b, "source": c} for a, b, c in comp["facts"]],
            "dims": comp["dims"],
            "parts": [{"name": n, "material": mat, "colour": COLOURS[col],
                       "inside_envelope": inside} for n, s, col, mat, inside in parts],
            "verification": res,
            "overall_mm": [round(bb.XLength, 3), round(bb.YLength, 3), round(bb.ZLength, 3)],
            "bbox_mm": [round(v, 3) for v in (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)],
            "mesh": {"triangles": ntri, "chordal_tolerance_mm": 0.01},
            "files": {"glb": f"{cid}.glb", "step": f"{cid}.step",
                      "fcstd": os.path.relpath(fc, os.path.expanduser("~/workspace"))},
            "used_in": uses[cid],
            "motion": comp.get("motion", []),
            "operate": comp.get("operate"),
            "xray": comp.get("xray", False),
        }
        print(f"{cid:16s} ft {comp['ft']:>6s}  housing "
              + " x ".join(f"{r['model_mm']:.2f}" for r in res[:3])
              + f" mm  checks {sum(r['ok'] for r in res)}/{len(res)}  {ntri} tris  "
              f"used {len(uses[cid])}x in the factory")
    json.dump({"components": manifest,
               "sources": {"datasheet": "printed in the ft datasheet",
                           "photo": "read off the datasheet photo - size estimated",
                           "ft-std": "fischertechnik system convention",
                           "assumed": "not documented - measure with calipers",
                           "booklet": "536634 booklet, Bauteilbeschreibung p.8-11"}},
              open(os.path.join(WEB_DIR, "components.json"), "w"), indent=1)
    print(f"wrote {CAD_DIR}/*.FCStd + *.step and {WEB_DIR}/*.glb + components.json")


if __name__ == "__main__" or sys.argv[-1].endswith("components_cad.py"):
    main()
