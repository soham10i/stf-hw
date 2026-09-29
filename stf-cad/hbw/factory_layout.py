"""
Factory-level placement, matched to the booklet's cover photo of 536634
(2026-09-27): the four plates packed as a 2 x 2 block.

    back row   :  VGR (left)            HBW (right)
    front row  :  Sortierstrecke (left) Brennofen (right)

Factory frame: the FRONT edge of the table is x = 0 (+X runs to the back),
"right" as seen from the front is -Y. Every module is placed by a rigid
transform, so each module's own clearance proof carries over unchanged; the
cross-module checks (check_cross, vgr_path) prove the rest.

HBW, oven and sorting line are all rotated +90 deg about Z:

    module (x, y, z)  ->  factory (-y + TX, x + TY, z)

  HBW   : the rack runs left-right along the back, its belt's VGR end at the left.
  oven  : the Ofenschieber points BACK at the VGR; the flow line runs to the
          FRONT and the belt ends against the sorting belt's rail (booklet
          photo: the oven box back-right, the belt coming forward on the left).
  sort  : belt runs right -> left from the inlet next to the oven; ejectors at
          the front edge, Lagerstellen at the back, facing the VGR.
The VGR stands unrotated between the three, where it can reach all of them.

Plate sizes are the models' own; they are NOT yet measured against the lab
machine - the photo fixes the arrangement, not millimetres.
"""
from hbw_model import P
from variant import UP1

# --- front row: the oven <-> sorting hand-over fixes both placements --------
SORT_ROT = 90.0
SORT_TX, SORT_TY = 650.0, 424.0
OVEN_ROT = 90.0
OVEN_TY = 10.0
# Solved, not guessed (module numbers from oven_model / sorting_model):
#   the oven belt's nose (oven y = BELT_Y[1]) reaches over the sorting belt's
#   back rail and ends above its centre line (sorting y = BELT[1] + BELT[3]/2):
#       OVEN_TX - BELT_Y[1] = SORT_TX - (BELT[1] + BELT[3] / 2)
#   and the sorting belt starts 30 mm beyond the oven's flow line (oven x 230),
#   so the workpiece lands on belt, not on its end drum:
#       SORT_TY + BELT[0] = OVEN_TY + X_LINE - 30
def _solve_oven_tx():
    import oven_model as OM, sorting_model as SM
    # the oven belt's NOSE tip ends right above the sorting belt's centre line
    return SORT_TX - (SM.S["BELT"][1] + SM.S["BELT"][3] / 2) + OM.O["BELT_Y"][1]


OVEN_TX = 1212.0
OVEN_AT = (OVEN_TX, OVEN_TY)          # the translation part of the oven's placement
# --- back row -------------------------------------------------------------
# 2x oven and sorting line (2026-09-27): the oven is 760 deep, so with its belt
# meeting the sorting inlet it reaches back into the back row. The VGR stands
# behind the sorting line, beside the oven; the HBW behind the oven. The corner
# in front of the oven holds the PLC cabinet (plc_model.py).
VGR_AT = (720.0, 760.0)
TX, TY = 1858.0, 150.0               # HBW
PLATE = (1870.0, 1510.0, 10.0)
ROTATE_DEG = 90.0


# PLC cabinet (plc_model.py) in the corner in front of the oven - translated only
PLC_AT = (60.0, 20.0)


def plc_rect():
    import plc_model as PM
    return [PLC_AT[0], PLC_AT[1], PM.C["PLATE"][0], PM.C["PLATE"][1]]


def to_factory_oven(x, y, z=0.0):
    return (-y + OVEN_TX, x + OVEN_TY, z)


def oven_box(a):
    """An oven-module AABB (x0,y0,z0,x1,y1,z1) in the factory frame."""
    c0, c1 = to_factory_oven(a[0], a[1]), to_factory_oven(a[3], a[4])
    return (min(c0[0], c1[0]), min(c0[1], c1[1]), a[2], max(c0[0], c1[0]), max(c0[1], c1[1]), a[5])


def to_factory(x, y, z=0.0):
    return (-y + TX, x + TY, z)


def module_rect():
    """The warehouse's footprint on the factory table."""
    mx, my = P["PLATE"][0], P["PLATE"][1]
    xs = [to_factory(x, y)[0] for x in (0, mx) for y in (0, my)]
    ys = [to_factory(x, y)[1] for x in (0, mx) for y in (0, my)]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


# Reserved footprints for the three modules that chain on. Positions follow the
# sketch; sizes are placeholders until each module is designed.
NEIGHBOURS = []       # every module is now a real model


def to_factory_sort(x, y, z=0.0):
    return (-y + SORT_TX, x + SORT_TY, z)


def sort_rect():
    import sorting_model as SM
    sx, sy = SM.S["PLATE"][0], SM.S["PLATE"][1]
    xs = [to_factory_sort(x, y)[0] for x in (0, sx) for y in (0, sy)]
    ys = [to_factory_sort(x, y)[1] for x in (0, sx) for y in (0, sy)]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def sort_handovers():
    """The three Lagerstellen, in factory coordinates."""
    import sorting_model as SM
    return {k: to_factory_sort(*v) for k, v in SM.handover_points().items()}


def vgr_rect():
    import vgr_model as VG
    vx, vy = VGR_AT
    return [vx, vy, VG.V["PLATE"][0], VG.V["PLATE"][1]]


def oven_rect():
    import oven_model as OM
    b = oven_box((0, 0, 0, OM.O["PLATE"][0], OM.O["PLATE"][1], 0))
    return [b[0], b[1], b[3] - b[0], b[4] - b[1]]


def oven_handover():
    """The oven's hand-over - the extended Ofenschieber - in factory coords."""
    import oven_model as OM
    h = OM.handover_point()
    return to_factory_oven(h[0], h[1], h[2])


def belt_handovers():
    """The two hand-over points on the HBW belt, in factory coordinates."""
    return {"hbw": to_factory(P["CV_X"], P["PICK_HBW"], P["CV_SURF"]),
            "vgr": to_factory(P["CV_X"], P["PICK_VGR"], P["CV_SURF"])}


def vgr_tower():
    import vgr_model as VG
    vx, vy = VGR_AT
    return (vx + VG.V["CX"], vy + VG.V["CY"])


def solve_station(target_xy):
    """Given a point on the factory table, return the VGR joint values that put
    the suction cup exactly there.

    At swivel 0 the arm points -Y, so a swivel of t aims it along
    (sin t, -cos t). This is the ONLY place a VGR station angle is computed;
    the export takes its stops from here rather than from typed-in numbers, so a
    station cannot drift away from the geometry that defines it.
    """
    import math, vgr_model as VG
    tx, ty = vgr_tower()
    dx, dy = target_xy[0] - tx, target_xy[1] - ty
    r = math.hypot(dx, dy)
    swivel = math.degrees(math.atan2(dx, -dy))
    reach = r - VG.cup_radius(0.0)
    s0, s1 = VG.V["SWIVEL"]; r0, r1 = VG.V["REACH"]
    ok = s0 <= swivel <= s1 and r0 <= reach <= r1
    return {"swivel": round(swivel, 3), "reach": round(reach, 3),
            "distance": round(r, 3), "in_envelope": ok}


def cup_at(swivel_deg, reach):
    """Where the cup actually lands, in factory coordinates."""
    import math, vgr_model as VG
    tx, ty = vgr_tower()
    r = VG.cup_radius(reach)
    t = math.radians(swivel_deg)
    return (tx + r * math.sin(t), ty - r * math.cos(t))


def stations():
    """Every point the VGR must serve, solved rather than asserted."""
    hv = belt_handovers()
    oh = oven_handover()
    out = {"belt": {"target": [hv["vgr"][0], hv["vgr"][1]], **solve_station(hv["vgr"][:2])},
           "oven": {"target": [oh[0], oh[1]], **solve_station(oh[:2])}}
    for col, pt in sort_handovers().items():
        out[f"bay_{col}"] = {"target": [pt[0], pt[1]], **solve_station(pt[:2])}
    if UP1:
        import upgrade as U
        for nm, pt in U.nests().items():
            out[nm] = {"target": [pt[0], pt[1]], **solve_station(pt)}
    for n in NEIGHBOURS:                       # centre of each reserved footprint
        x, y, w, h = n["rect"]
        c = (x + w / 2, y + h / 2)
        out[n["id"]] = {"target": [c[0], c[1]], **solve_station(c)}
    return out


def reach_coverage():
    """Which reserved footprints the VGR can actually touch.

    A footprint CENTRE being out of reach does not mean the station is
    unreachable - what matters is whether any part of it falls inside the
    annulus the cup can sweep. Reported per footprint so that when the oven and
    sorting stations are designed, their hand-over ports can be put somewhere the
    arm can get to instead of being discovered unreachable afterwards.
    """
    import math, vgr_model as VG
    tx, ty = vgr_tower()
    r0, r1 = VG.cup_radius(VG.V["REACH"][0]), VG.cup_radius(VG.V["REACH"][1])
    out = []
    for n in NEIGHBOURS:
        x, y, w, h = n["rect"]
        near_x = min(max(tx, x), x + w)
        near_y = min(max(ty, y), y + h)
        near = math.hypot(near_x - tx, near_y - ty)
        far = max(math.hypot(cx_ - tx, cy_ - ty)
                  for cx_ in (x, x + w) for cy_ in (y, y + h))
        out.append({"id": n["id"], "n": n["n"], "near": round(near, 1),
                    "far": round(far, 1), "annulus": [round(r0, 1), round(r1, 1)],
                    "any_reachable": near <= r1 and far >= r0})
    return out


# Stations that actually exist and therefore gate the export. The oven and the
# sorting line are still placeholder footprints, so their reachability is
# REPORTED (see reach_coverage) but does not fail the build - blocking on the
# centre of a rectangle nobody has designed yet would be noise, not a check.
BUILT_STATIONS = {"belt", "oven", "bay_weiss", "bay_rot", "bay_blau"}
if UP1:
    BUILT_STATIONS |= {f"buf_{i}" for i in range(1, 7)}


def check_stations(tol=0.01):
    """A solved station must put the cup on its target, and say so when it cannot
    be reached at all."""
    bad = []
    for name, st in stations().items():
        if name not in BUILT_STATIONS:
            continue
        cx_, cy_ = cup_at(st["swivel"], st["reach"])
        err = max(abs(cx_ - st["target"][0]), abs(cy_ - st["target"][1]))
        if err > tol:
            bad.append(f"{name}: solved pose lands {err:.3f} mm off target")
        if not st["in_envelope"]:
            import vgr_model as _V
            s0, s1 = _V.V["SWIVEL"]; r0, r1 = _V.V["REACH"]
            why = []
            if not s0 <= st["swivel"] <= s1:
                why.append(f"swivel {st['swivel']:.1f} outside {s0:.0f}..{s1:.0f}")
            if not r0 <= st["reach"] <= r1:
                why.append(f"reach {st['reach']:.0f} outside {r0:.0f}..{r1:.0f}")
            bad.append(f"{name}: OUT OF ENVELOPE ({'; '.join(why)})")
    return bad


def _obb_hit(ca, ha, ang, cb, hb, tol):
    """2D separating-axis test between a ROTATED box and an axis-aligned one.

    The conservative enclosing-box test is fine inside a module, but across
    modules a long arm at 45 degrees has an enormous axis-aligned box and reports
    hits that are not there. This is the real test.
    """
    import math
    c, s_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    axes = [(1.0, 0.0), (0.0, 1.0), (c, s_), (-s_, c)]
    d = (cb[0] - ca[0], cb[1] - ca[1])
    best = 1e9
    for ax in axes:
        # projection radius of the rotated box
        ra = abs(ha[0] * (ax[0] * c + ax[1] * s_)) + abs(ha[1] * (ax[0] * -s_ + ax[1] * c))
        rb = abs(hb[0] * ax[0]) + abs(hb[1] * ax[1])
        sep = abs(d[0] * ax[0] + d[1] * ax[1]) - (ra + rb)
        best = min(best, -sep)
        if sep > tol:
            return 0.0
    return best


# The oven carries its own Sauger portal directly ABOVE its hand-over tray, so a
# VGR arm reaching that tray has to be under the rail. Rail underside 250, arm
# top = plunge + 32 -> plunge must be at or below 210 before extending in. This
# is the same shape of constraint as the HBW's identification tunnel: a fixed
# structure over a hand-over point, and the approach has to duck under it.
# ...and each hand-over also has a FLOOR: below it the arm itself is down at the
# level of the surface it is serving. So every station is a plunge BAND, not a
# single stop.
VGR_PLUNGE_BAND = {
    "belt": (140.0, 320.0),   # floor: above the belt strips and their drums
    # The rebuilt oven has NOTHING over its tray (its Sauger rail is behind the
    # flow line), so the old 210 ceiling is gone. Floor: cup on the cookie top.
    "oven": (100.0, 320.0),
    # the Lagerstellen: the cup meets the workpiece top at z=80, i.e. plunge 108
    "bay_weiss": (110.0, 320.0),
    "bay_rot": (110.0, 320.0),
    "bay_blau": (110.0, 320.0),
}
if UP1:     # buffer nests hold the cookie at the Lagerstellen's height
    VGR_PLUNGE_BAND.update({f"buf_{i}": (110.0, 320.0) for i in range(1, 7)})


def vgr_plunge_allowed(station, plunge):
    lo, hi = VGR_PLUNGE_BAND.get(station, (-1e9, 1e9))
    return lo <= plunge <= hi


def check_cross(tol=0.05):
    """Cross-module interference. Each module passes its own proof; this is the
    pairs. The VGR is checked at BOTH its stations against the module it is
    reaching into and against the other one it might sweep past."""
    import vgr_model as VG, oven_model as OM
    from hbw_model import build as hbw_build
    vx, vy = VGR_AT
    assert abs(_solve_oven_tx() - OVEN_TX) < 1e-6, "oven belt no longer meets the sorting rail"

    hbw = []
    for p in hbw_build(P["CV_X"], 260.0, 0.0):       # crane parked clear, at transit
        if p.group == "frame":
            continue
        a = p.aabb()
        c0, c1 = to_factory(a[0], a[1]), to_factory(a[3], a[4])
        hbw.append((f"HBW {p.name}", (min(c0[0], c1[0]), min(c0[1], c1[1]), a[2],
                                      max(c0[0], c1[0]), max(c0[1], c1[1]), a[5])))
    # In the CHAINED configuration (booklet p.15) the VGR serves the oven, so the
    # station's OWN Sauger must be parked at the turntable - both grippers want
    # the same spot over the extended tray otherwise. That is a coordination rule
    # between two modules, and this is where it gets enforced.
    oven = []
    for p in OM.build(sauger=OM.O["SAUGER"][1]):      # slider out, door open
        if p.group == "frame":
            continue
        a = p.local_aabb()
        oven.append((f"OVEN {p.name}", oven_box(a)))

    import sorting_model as SM
    sort = []
    for p in SM.build():
        if p.group == "frame":
            continue
        a = p.local_aabb()
        c0, c1 = to_factory_sort(a[0], a[1]), to_factory_sort(a[3], a[4])
        sort.append((f"SORT {p.name}", (min(c0[0], c1[0]), min(c0[1], c1[1]), a[2],
                                        max(c0[0], c1[0]), max(c0[1], c1[1]), a[5])))

    bad = []
    import plc_model as PM
    plc = []
    for p in PM.build():
        if p.group == "frame":
            continue
        a = p.local_aabb()
        plc.append((f"PLC {p.name}", (a[0] + PLC_AT[0], a[1] + PLC_AT[1], a[2],
                                      a[3] + PLC_AT[0], a[4] + PLC_AT[1], a[5])))
    ups = []
    if UP1:
        import upgrade as U
        ups = [(f"UP1 {p.name}", a) for _, p, a in U.factory_parts()]
        vgr_world = []
        for p in VG.build():
            if p.group == "frame" or p.frame != "world":
                continue
            a = p.local_aabb()
            vgr_world.append((f"VGR {p.name}", (a[0] + vx, a[1] + vy, a[2], a[3] + vx, a[4] + vy, a[5])))
        for un, ua in ups:
            for on, oa in hbw + oven + sort + plc + vgr_world:
                d = [min(ua[i + 3], oa[i + 3]) - max(ua[i], oa[i]) for i in range(3)]
                if min(d) > tol:
                    bad.append(f"{un} x {on} = {min(d):.1f} mm")
    for pn, pa in plc:
        for on, oa in oven + sort:
            d = [min(pa[i + 3], oa[i + 3]) - max(pa[i], oa[i]) for i in range(3)]
            if min(d) > tol:
                bad.append(f"{pn} x {on} = {min(d):.1f} mm")
    # the front row: the oven's belt end reaches the sorting belt's rail, so
    # the two modules' parts are checked against each other too
    for on, oa in oven:
        for sn, sa in sort:
            d = [min(oa[i + 3], sa[i + 3]) - max(oa[i], sa[i]) for i in range(3)]
            if min(d) > tol:
                bad.append(f"{on} x {sn} = {min(d):.1f} mm (front row)")
    for station, st in stations().items():
        if station not in BUILT_STATIONS:
            continue
        for pl in (VG.V["PLUNGE"][1], 220.0, 190.0, 158.0, VG.V["PLUNGE"][0]):
            if not vgr_plunge_allowed(station, pl):
                continue
            vparts = VG.build(st["swivel"], pl, st["reach"])
            if VG.carry_allowed(pl):
                vparts = vparts + VG.held_cookie(st["swivel"], pl, st["reach"])
            for p in vparts:
                if p.group == "frame":
                    continue
                a = VG.world_aabb(p, st["swivel"])
                va = (a[0] + vx, a[1] + vy, a[2], a[3] + vx, a[4] + vy, a[5])
                # the part's own (unrotated) box, then where its centre lands
                la = p.local_aabb()
                lc = ((la[0] + la[3]) / 2, (la[1] + la[4]) / 2)
                import math as _m
                t = _m.radians(st["swivel"]); ct, stt = _m.cos(t), _m.sin(t)
                dxp, dyp = lc[0] - VG.V["CX"], lc[1] - VG.V["CY"]
                vc = (vx + VG.V["CX"] + dxp * ct - dyp * stt,
                      vy + VG.V["CY"] + dxp * stt + dyp * ct)
                vh = ((la[3] - la[0]) / 2, (la[4] - la[1]) / 2)
                ang = 0.0 if p.frame == "world" else st["swivel"]
                if p.frame == "world":
                    vc = ((la[0] + la[3]) / 2 + vx, (la[1] + la[4]) / 2 + vy)
                for nm, oa in hbw + oven + sort + ups:
                    dz = min(va[5], oa[5]) - max(va[2], oa[2])
                    if dz <= tol:
                        continue
                    hit = _obb_hit(vc, vh, ang,
                                   ((oa[0] + oa[3]) / 2, (oa[1] + oa[4]) / 2),
                                   ((oa[3] - oa[0]) / 2, (oa[4] - oa[1]) / 2), tol)
                    if hit:
                        bad.append(f"VGR {p.name} x {nm} = {min(hit, dz):.1f} mm "
                                   f"@ station={station} plunge={pl}")
    return bad


def vgr_reach_check():
    """The VGR tower must be inside cup reach of the belt's VGR hand-over."""
    import math, vgr_model as VG
    vx, vy = VGR_AT
    tower = (vx + VG.V["CX"], vy + VG.V["CY"])
    tgt = belt_handovers()["vgr"]
    d = math.hypot(tgt[0] - tower[0], tgt[1] - tower[1])
    rmin, rmax = VG.cup_radius(VG.V["REACH"][0]), VG.cup_radius(VG.V["REACH"][1])
    return d, rmin, rmax, rmin <= d <= rmax


def doc():
    return {
        "plate": list(PLATE),
        "placement": {"rotate_deg": ROTATE_DEG, "translate": [TX, TY]},
        "hbw_rect": module_rect(),
        "vgr_at": list(VGR_AT),
        "vgr_rect": vgr_rect(),
        "oven_at": list(OVEN_AT),
        "oven_placement": {"rotate_deg": OVEN_ROT, "translate": [OVEN_TX, OVEN_TY]},
        "plc_at": list(PLC_AT),
        "plc_rect": plc_rect(),
        "oven_rect": oven_rect(),
        "sort_placement": {"rotate_deg": SORT_ROT, "translate": [SORT_TX, SORT_TY]},
        "sort_rect": sort_rect(),
        "neighbours": NEIGHBOURS,
        "handovers": {k: list(v) for k, v in belt_handovers().items()},
        "stations": stations(),
        "vgr_plunge_band": VGR_PLUNGE_BAND,
        "reach_coverage": reach_coverage(),
        **({"variant": __import__("variant").VARIANT, "upgrade_rects": __import__("upgrade").rects()} if UP1 else {}),
        "sketch": "top view supplied 2026-09-06: 1 PCB, 2 rack, 3 conveyor, "
                  "4 picker, 5 VGR, 6 oven, 7 sorting",
    }


if __name__ == "__main__":
    import json
    d = doc()
    print(json.dumps(d, indent=1))
    hx, hy, hw, hh = d["hbw_rect"]
    print(f"\nwarehouse occupies X {hx:.0f}..{hx+hw:.0f}  Y {hy:.0f}..{hy+hh:.0f}")
    for n in NEIGHBOURS:
        x, y, w, h = n["rect"]
        ov = (x < hx + hw and x + w > hx) and (y < hy + hh and y + h > hy)
        print(f"  {n['n']} {n['label']:22s} X {x:.0f}..{x+w:.0f}  Y {y:.0f}..{y+h:.0f}"
              f"   {'OVERLAPS WAREHOUSE' if ov else 'clear'}")
    rects = {"2/3/4 warehouse": [hx, hy, hw, hh], "5 VGR": d["vgr_rect"],
             "6 oven": d["oven_rect"], "7 sorting": d["sort_rect"]}
    for n in NEIGHBOURS:
        rects[f"{n['n']} {n['id']}"] = n["rect"]
    names = list(rects)
    for i, a_ in enumerate(names):
        for b_ in names[i + 1:]:
            A_, B_ = rects[a_], rects[b_]
            if (A_[0] < B_[0] + B_[2] and A_[0] + A_[2] > B_[0]
                    and A_[1] < B_[1] + B_[3] and A_[1] + A_[3] > B_[1]):
                print(f"  PLATE OVERLAP: {a_} x {b_}")
    for nm, r in rects.items():
        print(f"  {nm:18s} X {r[0]:6.0f}..{r[0]+r[2]:6.0f}  Y {r[1]:6.0f}..{r[1]+r[3]:6.0f}")
    print("\n  VGR stations (solved from the geometry, not typed in):")
    for nm, st in stations().items():
        print(f"    {nm:8s} target ({st['target'][0]:6.0f},{st['target'][1]:6.0f})  "
              f"swivel {st['swivel']:7.2f} deg  reach {st['reach']:7.1f}  "
              f"{'OK' if st['in_envelope'] else 'OUT OF ENVELOPE'}")
    print("\n  reach coverage of any remaining reserved footprints "
          f"(annulus {__import__('vgr_model').cup_radius(0):.0f}.."
          f"{__import__('vgr_model').cup_radius(__import__('vgr_model').V['REACH'][1]):.0f} mm):")
    for c in reach_coverage():
        print(f"    {c['n']} {c['id']:8s} nearest {c['near']:6.0f}  farthest {c['far']:6.0f}  "
              f"{'partly reachable' if c['any_reachable'] else 'NOT REACHABLE AT ALL'}")
    sb = check_stations()
    print("  station solve:", "; ".join(sb) if sb else "every solved pose lands on its target")
    cb = check_cross()
    print("  cross-module :", "; ".join(cb[:3]) if cb else
          "VGR at the belt hand-over does not touch the warehouse")
    dd, r0, r1, okr = vgr_reach_check()
    print(f"  VGR tower -> belt hand-over: {dd:.0f} mm; cup reach {r0:.0f}..{r1:.0f} -> "
          f"{'IN REACH' if okr else 'OUT OF REACH'}")
    for k, mm in (("rack", (45, P["RACK_Y0"], 555, P["RACK_Y0"] + P["RACK_DEPTH"])),
                  ("rail", (0, P["RAIL_Y"] - 30, P["PLATE"][0], P["RAIL_Y"] + 30)),
                  ("belt", (610, P["CV_Y"][0], 720, P["CV_Y"][1])),
                  ("pcb", (20, 20, 130, 95))):
        a = to_factory(mm[0], mm[1]); b = to_factory(mm[2], mm[3])
        print(f"  {k:5s} -> X {min(a[0],b[0]):.0f}..{max(a[0],b[0]):.0f}"
              f"  Y {min(a[1],b[1]):.0f}..{max(a[1],b[1]):.0f}")
