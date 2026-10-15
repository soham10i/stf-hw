"""
Upgrade 1 - utilities, buffer and a stiffer structure (STF_VARIANT=up1).

What it changes, and the check that proves each change:

  1. ONE central air station replaces the three module compressors (oven Q10,
     sorting Q2, VGR Q7). It stands in the back corner behind the warehouse -
     the 650 x 500 mm the 2x layout left empty - in the part of that corner the
     VGR can NOT reach (every point > 586 mm from the tower), so the arm never
     has to be proven clear of it. Air mains run to each module's valve group
     (wiring.py routes them round everything standing on the table).
  2. A 6-nest cookie BUFFER in the part of the same corner the VGR CAN reach.
     The first idea - the buffer in the spot the PLC would free - failed the
     reach check (1019 mm from the tower, the cup reaches 568), which is why the
     PLC cabinet stays at the front edge, where it is also easiest to service.
     Nests are at the Lagerstellen's height, so the cup meets a buffered cookie
     at exactly the plunge it already uses at the bays. Every nest is a solved
     VGR station (factory_layout.stations) and the pick/place tour to each one
     is swept by vgr_path.check_buffer().
  3. A beam SAG check on the oven's cantilevered and spanned members. The 2x
     rebuild doubled their spans but kept their sections, and a cantilever's
     tip deflection grows with L^3. Base: pusher beam 3.71 mm, door gantry
     1.30 mm, Sauger rail 0.29 mm fail 0.2 mm at the tool; the saw arm passes
     (0.035 mm) and is left alone. The three that fail become aluminium
     profile (oven_model PROFILE).

Sag model: Euler-Bernoulli, small deflection.
  cantilever, tip load at L:        d = F L^3 / (3 E I)
  simply supported, load at a (b):  d = F a^2 b^2 / (3 E I L)   (under the load)
Assumptions, all stated so they can be challenged:
  - ft building blocks / black members: PA6 solid rectangle, E = 2500 MPa
    (a hollow ft block is SOFTER, so the base numbers are optimistic)
  - 20x20 aluminium slot profile: E = 70000 MPa, I = 6900 mm^4
    (Misumi HFS5-2020 catalogue value); 15x15: I = 1900 mm^4 (HFS3-1515)
  - pneumatic force: 0.7 bar x the ft cylinder's 10 mm bore = 5.5 N
  - S-motor 60 g, x2 dynamic factor for start/stop
"""
import math
from dataclasses import dataclass

from variant import UP1, UP2

TABLE = (1870.0, 1510.0)
BUF_AT = (1235.0, 1025.0)       # buffer plate corner, factory frame (translated only)
AIR_AT = (1520.0, 1240.0)       # air station plate corner
BUF_PLATE = (210.0, 160.0, 10.0)
AIR_PLATE = (300.0, 230.0, 10.0)
NEST_X = (35.0, 105.0, 175.0)   # nest centres, buffer frame
NEST_Y = (40.0, 120.0)
NEST_TOP = 45.0                 # = sorting BELT_Z: the cookie's underside in a Lagerstelle
PAD_D, PIN_D, PIN_R = 55.0, 4.0, 27.5

E_PA, E_AL = 2500.0, 70000.0
I_PROFILE = {20.0: 6900.0, 15.0: 1900.0}
F_CYL = 0.07 * math.pi * 5.0 ** 2          # 0.7 bar on a 10 mm bore, N
F_MOTOR = 0.060 * 9.81 * 2.0
SAG_LIMIT = 0.2                             # mm at the tool


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
        if ax == "z":
            return (x - d / 2, y - d / 2, z, x + d / 2, y + d / 2, z + L)
        if ax == "x":
            return (x, y - d / 2, z - d / 2, x + L, y + d / 2, z + d / 2)
        return (x - d / 2, y, z - d / 2, x + d / 2, y + L, z + d / 2)


def nests():
    """Nest centres, factory frame, in pick order."""
    return {f"buf_{i + 1}": (BUF_AT[0] + x, BUF_AT[1] + y)
            for i, (y, x) in enumerate((y, x) for y in NEST_Y for x in NEST_X)}


def buffer_parts():
    """Buffer frame parts; add BUF_AT for the factory frame."""
    out = []; A = out.append
    w, d, t = BUF_PLATE
    A(Part("buffer_plate", "frame", "box", (0, 0, -t), BUF_PLATE, "slate", "table"))
    top = NEST_TOP - 8.0
    for nm, (x, y) in {"FL": (5, 5), "FR": (w - 25, 5), "BL": (5, d - 25), "BR": (w - 25, d - 25)}.items():
        A(Part(f"buffer_leg_{nm}", "buffer", "box", (x, y, 0), (20, 20, top - 10), "alu", "plate",
               mech="profile:20", note="20x20 aluminium profile leg"))
    A(Part("buffer_deck", "buffer", "box", (0, 0, top - 10), (w, d, 10), "ftred", "buffer_leg_FL",
           note="6-nest cookie buffer: the VGR parks a baked cookie here instead of waiting "
                "for a Lagerstelle or the oven"))
    for i, (nm, (fx, fy)) in enumerate(nests().items()):
        x, y = fx - BUF_AT[0], fy - BUF_AT[1]
        A(Part(f"{nm}_pad", "buffer", "cyl", (x, y, top), ("z", NEST_TOP - top, PAD_D), "black",
               "buffer_deck", note=f"nest {i + 1}: the cookie's underside sits at z={NEST_TOP:.0f}, "
                                  "the same as in a Lagerstelle"))
        # on the axes: the swept check treats round parts as boxes, and a pin
        # on a diagonal would touch the cookie's box corner (real gap 3 mm)
        for k, ang in enumerate((0.0, 90.0, 180.0, 270.0)):
            a = math.radians(ang)
            A(Part(f"{nm}_pin_{k}", "buffer", "cyl",
                   (x + PIN_R * math.cos(a), y + PIN_R * math.sin(a), NEST_TOP), ("z", 6, PIN_D),
                   "steel", f"{nm}_pad", note="locating pin: centres the cookie to +-2.5 mm"))
    return out


def air_parts():
    """Central air station parts; add AIR_AT for the factory frame."""
    out = []; A = out.append
    A(Part("air_plate", "frame", "box", (0, 0, -AIR_PLATE[2]), AIR_PLATE, "slate", "table"))
    A(Part("Q10_central_compressor", "air", "box", (15, 20, 0), (110, 70, 75), "blue", "plate",
           tag="Q10", note="ONE 24 V diaphragm compressor for the whole line - replaces the "
                           "oven's Q10, the sorting line's Q2 and the VGR's Q7"))
    for nm, x in (("L", 150), ("R", 250)):
        A(Part(f"air_tank_foot_{nm}", "air", "box", (x, 30, 0), (15, 60, 20), "black", "plate"))
    A(Part("air_tank", "air", "cyl", (140, 60, 55), ("x", 140, 70), "steel", "air_tank_foot_L",
           note="0.5 l receiver: smooths the pump's pulses, so three valves firing "
                "together don't starve each other"))
    A(Part("air_pressure_switch", "air", "cyl", (270, 60, 90), ("z", 22, 22), "grey", "air_tank",
           note="pressure switch: runs the pump between 0.6 and 0.8 bar instead of continuously"))
    A(Part("air_frl", "air", "box", (40, 130, 0), (40, 40, 100), "alu", "plate",
           note="filter-regulator: water trap + 0.7 bar set point for every consumer"))
    A(Part("air_frl_gauge", "air", "cyl", (60, 126, 80), ("y", 4, 30), "white", "air_frl"))
    A(Part("air_lockout_valve", "air", "box", (95, 140, 0), (30, 25, 30), "amber", "plate",
           note="lockable shut-off + exhaust: the line is made pressure-free before service"))
    if UP2:
        A(Part("air_safe_exhaust", "air", "box", (95, 178, 0), (40, 40, 55), "yellow", "plate",
               tag="Y1", note="Upgrade 2: 2-channel monitored safe exhaust valve between the "
                              "filter-regulator and the manifold - de-energised by the safety relay, "
                              "it cuts supply AND vents every cylinder downstream"))
    A(Part("air_manifold", "air", "box", (140, 140, 0), (140, 25, 25), "alu", "plate",
           note="distribution block: one outlet per module (oven, sorting, VGR) + a spare"))
    for k in range(4):
        A(Part(f"air_outlet_{k + 1}", "air", "cyl", (160 + k * 33, 152.5, 25), ("z", 8, 8), "blue",
               "air_manifold"))
    return out


def outlets():
    """Factory-frame tops of the manifold outlets, oven / sorting / VGR / spare."""
    return [(AIR_AT[0] + 160 + k * 33, AIR_AT[1] + 152.5, 33.0) for k in range(4)]


def factory_parts(include_io=True):
    """(module, part, factory AABB) for every upgrade part - the obstacle list.
    Upgrade 3's remote I/O nodes join it, so every proof that reads this list
    (check_cross, the VGR tours, the wiring router) sees them too."""
    out = []
    for mod, at, parts in (("buffer", BUF_AT, buffer_parts()), ("air", AIR_AT, air_parts())):
        for p in parts:
            if p.group == "frame":
                continue
            a = p.local_aabb()
            out.append((mod, p, (a[0] + at[0], a[1] + at[1], a[2], a[3] + at[0], a[4] + at[1], a[5])))
    if include_io:
        import io_nodes
        out += io_nodes.factory_parts()
    return out


def rects():
    return {"buffer": [BUF_AT[0], BUF_AT[1], BUF_PLATE[0], BUF_PLATE[1]],
            "air": [AIR_AT[0], AIR_AT[1], AIR_PLATE[0], AIR_PLATE[1]]}


# ---------------------------------------------------------------- beam sag
def _section(p, bend_axis):
    """(E, I, label) of a member about the axis it bends in. bend_axis is the
    load direction; the member's long axis is its largest box dimension, and
    the section is the other two - `along` the load and `across` it."""
    dims = {"x": p.s[0], "y": p.s[1], "z": p.s[2]}
    long_ax = max(dims, key=dims.get)
    across_ax = next(a for a in "xyz" if a not in (long_ax, bend_axis))
    along, across = dims[bend_axis], dims[across_ax]
    if p.colour == "alu":
        edge = min(along, across)
        return E_AL, I_PROFILE[round(edge)], f"aluminium profile {edge:.0f}x{edge:.0f}"
    return E_PA, across * along ** 3 / 12.0, f"PA6 solid {across:.0f}x{along:.0f}"


def sag_report():
    """Deflection at the tool of every oven member that carries a load off its
    support. Reads the member sizes from the model, so base and Upgrade 1 are
    both measured, never typed in."""
    import oven_model as OM
    q = OM.O
    parts = {p.name: p for p in OM.build()}
    XL = q["X_LINE"]
    sx, _ = OM.nest(OM.STATIONS["saege"])
    motor_cx = sx - 45 + q["S_MOTOR"][1] / 2
    rows = []

    def add(name, what, case, F, L, a=None, axis="z"):
        p = parts[name]
        E, I, sec = _section(p, axis)
        if case == "cantilever":
            d = F * L ** 3 / (3 * E * I)
        else:
            b = L - a
            d = F * a ** 2 * b ** 2 / (3 * E * I * L)
        rows.append({"member": name, "carries": what, "case": case, "F_N": round(F, 2),
                     "L_mm": round(L, 1), "section": sec, "E_MPa": E, "I_mm4": round(I, 1),
                     "sag_mm": round(d, 4), "limit_mm": SAG_LIMIT, "ok": d <= SAG_LIMIT})

    add("pusher_beam", "Q14 Auswerfer cylinder, push reaction", "cantilever", F_CYL, XL - 310, axis="y")
    add("saw_arm", "M3 saw motor (x2 dynamic)", "cantilever", F_MOTOR, motor_cx - 310)
    cy0, cy1 = q["CH_Y"]
    span = (cy1 - 6) - (cy0 + 6)
    add("door_gantry", "Q13 door cylinder, lift reaction", "simply supported", F_CYL, span,
        a=q["TRAY_Y"] - (cy0 + 6))
    rspan = 347.5 - 7.5
    worst = max(q["SAUGER"], key=lambda s: min(s - 7.5, 347.5 - s))
    add("sauger_rail", "Sauger carriage + Q12 press (5.5 + 0.5 N)", "simply supported",
        F_CYL + 0.5, rspan, a=worst - 7.5)
    return rows


# ------------------------------------------------------------------- check
def check(verbose=True):
    """Upgrade 1's own proof: plates on the table and clear of every module,
    upgrade parts clear of each other, every nest inside the VGR envelope, the
    air station outside it, every member within its sag limit."""
    import factory_layout as FL, vgr_model as VG
    fails = []
    mod_rects = {"hbw": FL.module_rect(), "vgr": FL.vgr_rect(), "oven": FL.oven_rect(),
                 "sorting": FL.sort_rect(), "plc": FL.plc_rect()}
    for nm, (x, y, w, h) in rects().items():
        if x < 0 or y < 0 or x + w > TABLE[0] or y + h > TABLE[1]:
            fails.append(f"OFF-TABLE {nm}")
        for mn, (mx, my, mw, mh) in mod_rects.items():
            if x < mx + mw and x + w > mx and y < my + mh and y + h > my:
                fails.append(f"PLATE OVERLAP {nm} x {mn}")
    ups = factory_parts()
    for i, (ma, pa, a) in enumerate(ups):
        for mb, pb, b in ups[i + 1:]:
            if ma != mb:
                continue
            if pb.support == pa.name or pa.support == pb.name:
                continue            # a part and what it is mounted on touch by design
            d = [min(a[k + 3], b[k + 3]) - max(a[k], b[k]) for k in range(3)]
            if min(d) > 0.05:
                fails.append(f"INTERFERENCE {pa.name} x {pb.name} = {min(d):.1f} mm")
    st = FL.stations()
    for nm in nests():
        if not st[nm]["in_envelope"]:
            fails.append(f"{nm}: outside the VGR envelope")
    tx, ty = FL.vgr_tower()
    rmax = VG.cup_radius(VG.V["REACH"][1]) + VG.V["HEAD"][0] / 2
    ax, ay = AIR_AT
    near = math.hypot(min(max(tx, ax), ax + AIR_PLATE[0]) - tx, min(max(ty, ay), ay + AIR_PLATE[1]) - ty)
    if near <= rmax:
        fails.append(f"air station inside the VGR's sweep ({near:.0f} <= {rmax:.0f} mm)")
    for r in sag_report():
        if not r["ok"]:
            fails.append(f"SAG {r['member']}: {r['sag_mm']:.3f} mm > {r['limit_mm']} mm")
    if verbose:
        print(f"upgrade 1: {len(ups)} parts, {len(nests())} nests")
        print("\n".join(fails) if fails else "ALL CHECKS PASS (plates clear, nests reachable, "
                                               "air station out of the arm's sweep, sag within 0.2 mm)")
    return fails


def report(doc):
    """Before/after numbers for the viewer, computed from the two exports."""
    import factory_layout as FL, vgr_model as VG
    st = FL.stations()
    tx, ty = FL.vgr_tower()
    nest_rows = []
    for nm, (x, y) in nests().items():
        s = st[nm]
        nest_rows.append({"nest": nm, "at": [round(x, 1), round(y, 1)], "swivel": s["swivel"],
                          "reach": s["reach"], "reach_margin_mm": round(VG.V["REACH"][1] - s["reach"], 1),
                          "swivel_margin_deg": round(VG.V["SWIVEL"][1] - s["swivel"], 1)})
    corner = (FL.module_rect()[0], FL.module_rect()[1] + FL.module_rect()[3])
    corner_area = (TABLE[0] - corner[0]) * (TABLE[1] - corner[1])
    used = BUF_PLATE[0] * BUF_PLATE[1] + AIR_PLATE[0] * AIR_PLATE[1]
    return {"sag": sag_report(), "nests": nest_rows,
            "corner": {"rect": [corner[0], corner[1], TABLE[0] - corner[0], TABLE[1] - corner[1]],
                       "area_m2": round(corner_area / 1e6, 3), "used_m2": round(used / 1e6, 3)},
            "rects": rects(), "outlets": outlets()}
