"""
FreeCAD solids for the control and power devices (devices.py), built like the ft components
(components_cad.py imports DEVICE_BUILDERS and checks, writes and exports them the same way).

Each builder returns [(name, shape, colour, material, inside_envelope)], with the part named
"housing" the one whose exact bounding box must equal the device's documented envelope to 0.01 mm.
Front features sit in pockets with their faces flush, so the envelope is the device's own.

Every device carries an identification plate ("id_plate"): the place for its IEC 61406
identification link (the QR code that resolves to its Asset Administration Shell, aas/build.py).
"""
import Part
import FreeCAD as App

import components as C
import devices as DV

V = App.Vector


def box(x, y, z, dx, dy, dz):
    return Part.makeBox(dx, dy, dz, V(x, y, z))


def cyl(r, h, at, d=(0, 0, 1)):
    return Part.makeCylinder(r, h, V(*at), V(*d))


def din_profile(cid, L, W, H, base_t=None, nose_h=None):
    """A DIN-rail housing: a full-height base on the rail and a narrower front nose, extruded
    along the rail (Y), with the TS35 channel cut into its back."""
    if base_t is None:
        sol = box(0, 0, 0, L, W, H)
    else:
        a = (L - nose_h) / 2
        pts = [V(0, 0, 0), V(L, 0, 0), V(L, 0, base_t), V(a + nose_h, 0, base_t), V(a + nose_h, 0, H),
               V(a, 0, H), V(a, 0, base_t), V(0, 0, base_t), V(0, 0, 0)]
        sol = Part.Face(Part.makePolygon(pts)).extrude(V(0, W, 0))
    rw, rd = C.get(cid, "rail_w"), C.get(cid, "rail_d")
    return sol.cut(box((L - rw) / 2, -1, -1, rw, W + 2, rd + 1))


def pocket(sol, x, y, z, dx, dy, dz):
    return sol.cut(box(x, y, z, dx, dy, dz))


def id_plate(x, y, z, dx, dy, t=0.3, normal="z"):
    """The identification plate, flush in a recess: dx x dy on the face, t deep."""
    if normal == "z":
        return box(x, y, z - t, dx, dy, t)
    if normal == "y+":
        return box(x, y - t, z, dx, t, dy)
    raise ValueError(normal)


def spring_plug(x0, y0, z_top, poles, pitch, w, h, along="x"):
    """A spring-clamp plug: a body with a wire entry and a release slot per pole, its top at z_top."""
    n = int(poles)
    length = n * pitch
    if along == "x":
        body = box(x0, y0, z_top - h, length, w, h)
        for i in range(n):
            cx = x0 + pitch * (i + 0.5)
            body = body.cut(cyl(0.8, 6, (cx, y0 + w * 0.32, z_top - 5.9)))
            body = body.cut(box(cx - 0.6, y0 + w * 0.6, z_top - 3, 1.2, w * 0.28, 3.1))
    else:
        body = box(x0, y0, z_top - h, w, length, h)
        for i in range(n):
            cy = y0 + pitch * (i + 0.5)
            body = body.cut(cyl(0.8, 6, (x0 + w * 0.32, cy, z_top - 5.9)))
            body = body.cut(box(x0 + w * 0.6, cy - 0.6, z_top - 3, w * 0.28, 1.2, 3.1))
    return body


def screw_terminal(x0, y0, z_top, poles, pitch, d, h, along="y"):
    """A screw terminal block: a body, a slotted screw head per pole flush with its top."""
    n = int(poles)
    if along == "y":
        body = box(x0, y0, z_top - h, d, n * pitch, h)
        heads = []
        for i in range(n):
            c = (x0 + d * 0.35, y0 + pitch * (i + 0.5), z_top - 1.2)
            body = body.cut(cyl(pitch * 0.36, 1.3, c))
            head = cyl(pitch * 0.32, 1.2, c).cut(box(c[0] - pitch * 0.32, c[1] - 0.3, c[2] + 0.6, pitch * 0.64, 0.6, 0.7))
            heads.append(head)
        return body, Part.makeCompound(heads)
    raise ValueError(along)


# ------------------------------------------------------------------ RevPi
def _revpi(cid):
    g = lambda k: C.get(cid, k)
    L, W, H = g("L"), g("W"), g("H")
    base_t, nose_h = g("base_t"), g("nose_h")
    a = (L - nose_h) / 2
    housing = din_profile(cid, L, W, H, base_t, nose_h)
    parts = []
    # the supply plug(s) on the shoulders: X4 on the lower shoulder, X2 on the upper (DIO)
    pp, pitch = g("pwr_poles"), g("pwr_pitch")
    plen = pp * pitch
    shoulders = [(a / 2 - 4.5, "x4")] + ([(L - a / 2 - 4.5, "x2")] if cid == "revpi_dio" else [])
    for x, name in shoulders:
        plug = spring_plug(x, (W - plen) / 2 - 2.5, base_t + 12, pp, pitch, 9, 12, along="y")
        parts.append((f"supply_plug_{name}", plug, "green", "PA plug, screw clamps", True))
    # status LEDs on the upper shoulder: beside the X2 plug on the DIO, centred on the Core
    for i in range(3):
        ledx, ledy = L - a + 4 + i * 6, (W - 3 if cid == "revpi_dio" else W / 2)
        housing = housing.cut(cyl(g("led_d") / 2 + 0.1, 1.2, (ledx, ledy, base_t - 1.0)))
        parts.append((f"led_{i + 1}", cyl(g("led_d") / 2, 1.0, (ledx, ledy, base_t - 1.0)),
                      "led_green" if i != 1 else "led_amber", "LED", True))
    if cid == "revpi_dio":
        # two 14-pole spring-clamp I/O plugs on the nose front, side by side across the rail axis
        poles, ip = g("io_poles"), g("io_pitch")
        w = g("plug_w")
        x0 = a + (nose_h - poles * ip) / 2
        for k, y0 in enumerate(((W - 2 * w - 1) / 2, (W - 2 * w - 1) / 2 + w + 1)):
            housing = pocket(housing, x0 - 0.2, y0 - 0.2, H - g("plug_h"), poles * ip + 0.4, w + 0.4, g("plug_h") + 1)
            parts.append((f"io_plug_{k + 1}", spring_plug(x0, y0, H, poles, ip, w, g("plug_h")), "green",
                          "PA plug, spring clamps (Wieland 27.630.4453.0)", True))
        plate = id_plate(a + 6, W, base_t + 8, 24, 14, normal="y+")
    else:
        # the Core's front: RJ45 at the bottom, two USB A, micro-HDMI, micro-USB above
        y_mid = W / 2
        feats = [("rj45", g("rj45_w"), g("rj45_h"), 18.0, "black"), ("usb_a_1", g("usb_w"), g("usb_h"), 15.0, "steel"),
                 ("usb_a_2", g("usb_w"), g("usb_h"), 15.0, "steel"), ("micro_hdmi", 7.5, 3.5, 7.0, "steel"),
                 ("micro_usb", 8.0, 3.0, 6.0, "steel")]
        x = a + 3.0
        for name, fw, fh, depth, col in feats:
            housing = pocket(housing, x, y_mid - fw / 2, H - depth, fh, fw, depth + 1)
            body = box(x, y_mid - fw / 2, H - depth, fh, fw, depth)
            body = body.cut(box(x + fh * 0.18, y_mid - fw / 2 + fw * 0.12, H - depth * 0.85, fh * 0.64, fw * 0.76, depth))
            parts.append((name, body, col, "connector", True))
            x += fh + 2.2
        plate = id_plate(a + 4, W, base_t + 6, 26, 12, normal="y+")
    # PiBridge sockets on both sides of the base
    for side, y in (("left", 0.0), ("right", W - 1.5)):
        housing = pocket(housing, L / 2 - 8, y - (0.01 if side == "left" else -0.01), 18, 16, 1.5, 9)
        parts.append((f"pibridge_{side}", box(L / 2 - 7.5, y + (0.3 if side == "left" else 0.0), 18.5, 15, 1.2, 8),
                      "gold", "gold-plated contacts", True))
    housing = housing.cut(box(plate.BoundBox.XMin, plate.BoundBox.YMin, plate.BoundBox.ZMin,
                              plate.BoundBox.XLength, plate.BoundBox.YLength + 0.01, plate.BoundBox.ZLength))
    return [("housing", housing, "grey", "plastic (datasheet), PC/ABS (assumed)", True)] + parts + \
        [("id_plate", plate, "label", "IEC 61406 identification plate", True)]


def revpi_dio():
    return _revpi("revpi_dio")


def revpi_core():
    return _revpi("revpi_core")


# ------------------------------------------------------------------ PSU
def psu_wdr120():
    cid = "psu_wdr120"
    g = lambda k: C.get(cid, k)
    L, W, H = g("L"), g("W"), g("H")
    case = din_profile(cid, L, W, H)
    parts = []
    pitch, d = g("tb_pitch"), g("tb_w")
    # TB1 (input, 3-pole) at the bottom of the front, TB2 (output and DC OK, 4-pole) at the top
    for name, poles, x in (("tb1_input", 3, 6.0), ("tb2_output", 4, L - 6.0 - d)):
        y0 = (W - poles * pitch) / 2
        case = pocket(case, x - 0.2, y0 - 0.2, H - 14, d + 0.4, poles * pitch + 0.4, 15)
        body, heads = screw_terminal(x, y0, H, poles, pitch, d, 14)
        parts.append((name, body, "black", "PA terminal block", True))
        parts.append((name + "_screws", heads, "steel", "steel screws", True))
    # DC OK LED and the +V ADJ potentiometer between them
    case = case.cut(cyl(1.6, 1.5, (L - 32, W / 2 - 6, H - 1.4)))
    parts.append(("led_dc_ok", cyl(1.5, 1.4, (L - 32, W / 2 - 6, H - 1.4)), "led_green", "LED", True))
    case = case.cut(cyl(2.6, 2.0, (L - 32, W / 2 + 6, H - 1.9)))
    pot = cyl(2.4, 1.9, (L - 32, W / 2 + 6, H - 1.9)).cut(box(L - 32 - 2.4, W / 2 + 6 - 0.35, H - 0.9, 4.8, 0.7, 1))
    parts.append(("v_adj", pot, "white", "trimmer", True))
    # ventilation slots in both sides, upper and lower band (convection: input down, output up)
    sw, sl = g("slot_w"), g("slot_l")
    for z0 in (30.0, 70.0):
        for i in range(8):
            x = 14 + i * 13.2
            for y in (-0.01, W - 1.2):
                case = case.cut(box(x, y, z0, sw, 1.21, sl))
    plate = id_plate(40, W / 2 - 12, H, 34, 24)
    case = case.cut(box(40, W / 2 - 12, H - 0.3, 34, 24, 0.31))
    return [("housing", case, "steel", "metal case (datasheet)", True)] + parts + \
        [("id_plate", plate, "label", "IEC 61406 identification plate", True)]


# ------------------------------------------------------------------ the adaptor PCB
def adaptor_pcb():
    cid = "adaptor_pcb"
    g = lambda k: C.get(cid, k)
    s, X = DV.PCB_MM_PER_PX, DV.PCB_PX
    bx0, by0, bx1, by1 = X["board"]
    mx = lambda px: (px - bx0) * s
    my = lambda py: (by1 - py) * s                  # drawing y runs down; the terminal strip at -Y
    L, W, T = g("L"), g("W"), g("H")
    board = box(0, 0, 0, L, W, T)
    for hx, hy in X["holes"]:
        board = board.cut(cyl(g("hole_d") / 2, T + 2, (mx(hx), my(hy), -1)))
    parts = []
    # standoffs under the holes (below the board: outside its envelope)
    so = []
    for hx, hy in X["holes"]:
        so.append(cyl(3.0, g("standoff"), (mx(hx), my(hy), -g("standoff"))).cut(cyl(g("hole_d") / 2, g("standoff") + 1, (mx(hx), my(hy), -g("standoff") - 0.5))))
    parts.append(("standoffs", Part.makeCompound(so), "steel", "brass standoffs (assumed)", False))
    # relays R1-R8
    ry0, ry1 = X["relay_y"]
    for i, (a, b) in enumerate(X["relays"], 1):
        parts.append((f"relay_R{i}", box(mx(a), my(ry1), T, (b - a) * s, (ry1 - ry0) * s, g("relay_h")), "black",
                      "changeover relay", True))
    # shrouded headers: ST1 and ST2 (20-pole) to the model, ST3 (34-pole) to the PLC
    hw, hh = g("hdr_w"), g("hdr_h")
    for name, poles in (("st1", 20), ("st2", 20), ("st3", 34)):
        a, ya, b, yb = X[name]
        length = DV.BOX_HEADER(poles)
        x0, y0 = mx(a), my(yb) + ((yb - ya) * s - hw) / 2
        shroud = box(x0, y0, T, length, hw, hh).cut(box(x0 + 1.2, y0 + 1.2, T + 1.5, length - 2.4, hw - 2.4, hh))
        shroud = shroud.cut(box(x0 + length / 2 - 2.25, y0 - 0.1, T + 4, 4.5, 1.4, hh))   # the polarising key
        pins = []
        for i in range(poles // 2):
            for r in (0, 1):
                px_ = x0 + (length - (poles // 2 - 1) * 2.54) / 2 + i * 2.54
                py_ = y0 + hw / 2 + (r - 0.5) * 2.54
                pins.append(box(px_ - 0.32, py_ - 0.32, T + 1.5, 0.64, 0.64, 6.0))
        parts.append((name, shroud, "black", f"{poles}-pole shrouded header, 2.54 mm", True))
        parts.append((name + "_pins", Part.makeCompound(pins), "gold", "gold-plated pins", True))
    # V1-V4: 2-pole valve terminals along the left edge
    vx0, vx1, vy0, vy1 = X["valves"]
    step = (vy1 - vy0) / 4
    for i in range(4):
        y_top = vy0 + i * step
        y_lo = my(y_top + step)                       # the block's low-Y edge, mm
        body = box(mx(vx0), y_lo, T, (vx1 - vx0) * s, step * s - 0.3, g("term_h"))
        for k in range(2):                            # a screw over each of its two poles
            body = body.cut(cyl(1.1, 3, (mx(vx0) + (vx1 - vx0) * s * 0.55, y_lo + step * s * (0.25 + 0.5 * k), T + g("term_h") - 2.9)))
        parts.append((f"valve_V{i + 1}", body, "green", "2-pole terminal", True))
    # terminals 1-30: fifteen 2-pole pluggable blocks along the PLC edge, wire entries facing -Y
    tx0, tx1, ty0, ty1 = X["terminals"]
    pitch = (tx1 - tx0) * s / 30
    blocks = []
    for k in range(15):
        x0 = mx(tx0) + 2 * k * pitch
        b = box(x0 + 0.15, my(ty1), T, 2 * pitch - 0.3, (ty1 - ty0) * s, g("term_h"))
        for j in range(2):
            cx = x0 + (j + 0.5) * pitch
            b = b.cut(box(cx - 1.0, my(ty1) - 0.1, T + 2.0, 2.0, 3.5, 3.0))     # wire entry
            b = b.cut(cyl(1.0, 3, (cx, my(ty1) + (ty1 - ty0) * s * 0.65, T + g("term_h") - 2.9)))  # screw
        blocks.append(b)
    parts.append(("terminals_1_30", Part.makeCompound(blocks), "green", "pluggable terminal blocks", True))
    # the documented envelope is the board alone: everything on it stands out of it
    parts = [(n, sh, col, mat, False) for n, sh, col, mat, _ in parts]
    return [("housing", board, "pcb_green", "FR-4, 1.6 mm (standard)", True)] + parts + \
        [("id_plate", id_plate(mx(860), my(140), T + 0.35, 14, 10), "label", "IEC 61406 identification plate", False)]


# ------------------------------------------------------------------ remote I/O
def io_coupler():
    cid = "io_coupler"
    g = lambda k: C.get(cid, k)
    L, W, H = g("L"), g("W"), g("H")
    hous = din_profile(cid, L, W, H)
    parts = []
    for k in range(2):
        x = 12 + k * (g("rj45_h") + 3)
        hous = pocket(hous, x, 4, H - 18, g("rj45_h"), g("rj45_w"), 19)
        jack = box(x, 4, H - 18, g("rj45_h"), g("rj45_w"), 18).cut(box(x + 2, 6, H - 15, g("rj45_h") - 4, g("rj45_w") - 4, 16))
        parts.append((f"rj45_{k + 1}", jack, "black", "RJ45 jack", True))
    for i in range(4):
        hous = hous.cut(cyl(1.1, 1.2, (L - 10 - i * 5, 12, H - 1.1)))
        parts.append((f"led_{i + 1}", cyl(1.0, 1.1, (L - 10 - i * 5, 12, H - 1.1)), "led_green", "LED", True))
    # supply push-in terminals: 4 rows of 2 on the right of the front
    for r in range(4):
        for c in range(2):
            x, y = 14 + r * 12, 30 + c * 9
            hous = hous.cut(box(x, y, H - 6, 3.0, 3.0, 6.1))
            parts.append((f"pushin_{r}{c}", box(x + 3.2, y, H - 2.0, 2.4, 3.0, 2.0), "orange", "release tab", True))
    plate = id_plate(L - 40, 30, H, 26, 18)
    hous = hous.cut(box(L - 40, 30, H - 0.3, 26, 18, 0.31))
    return [("housing", hous, "grey", "plastic (assumed)", True)] + parts + \
        [("id_plate", plate, "label", "IEC 61406 identification plate", True)]


def io_slice():
    cid = "io_slice"
    g = lambda k: C.get(cid, k)
    L, W, H = g("L"), g("W"), g("H")
    hous = din_profile(cid, L, W, H)
    parts = []
    for i in range(8):
        x = L - 8 - i * 3.2
        hous = hous.cut(cyl(0.8, 1.0, (x, W / 2, H - 0.9)))
        parts.append((f"led_{i + 1}", cyl(0.75, 0.9, (x, W / 2, H - 0.9)), "led_green", "LED", True))
    for i in range(8):
        x = 10 + (i // 2) * 12 + 2
        y = 2.0 + (i % 2) * 4.2
        hous = hous.cut(box(x, y, H - 6, 2.6, 3.4, 6.1))
        parts.append((f"pushin_{i + 1}", box(x + 2.8, y, H - 1.8, 2.0, 3.4, 1.8), "orange", "release tab", True))
    plate = id_plate(60, 1.5, H, 8.5, 9.0)
    hous = hous.cut(box(60, 1.5, H - 0.3, 8.5, 9.0, 0.31))
    return [("housing", hous, "grey", "plastic (assumed)", True)] + parts + \
        [("id_plate", plate, "label", "IEC 61406 identification plate", True)]


DEVICE_BUILDERS = {"revpi_dio": revpi_dio, "revpi_core": revpi_core, "psu_wdr120": psu_wdr120,
                   "adaptor_pcb": adaptor_pcb, "io_coupler": io_coupler, "io_slice": io_slice}
