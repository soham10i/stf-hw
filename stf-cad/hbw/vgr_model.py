"""
Vacuum Gripper Robot (Vakuum-Sauggreifer, ft 536632) - from-scratch model.

Module frame: origin at the front-left corner of the VGR's own plate, top face.
  +X right, +Y back, +Z up, mm.

Kinematics are CYLINDRICAL (R-P-P), not cartesian - the Belegungsplan gives
three encoders and an explicit "Motor drehen im/gegen Uhrzeigersinn":

  swivel  Q5/Q6 (M3) + B5/B6, ref I3   rotate about Z on the Drehkranz
  reach   Q3/Q4 (M2) + B3/B4, ref I2   arm slides radially
  plunge  Q1/Q2 (M1) + B1/B2, ref I1   carriage rides the tower
  Q7 compressor, Q8 vacuum valve       the suction cup itself

Frames: world -> swivel(Rz) -> plunge(+Z) -> reach(-Y).
The swivel is a ROTATION, so interference is checked by rotating each part's
eight corners and taking the enclosing box - conservative, never optimistic.

Source: occupancyPlanSuctionGripper.ods (all 24 terminals), booklet p.18 photo
(twin-column tower, Drehkranz gear ring at the base, telescoping arm through a
clamp carriage, spring stem + suction cup), motor 60x30x30 from 144643.
"""
from variant import UP1, UP3, UP7
import math
from dataclasses import dataclass
from itertools import combinations

# Scaled up so the tower stands comparable to the 420 mm rack and the arm can
# serve all three stations, not just the belt. Cup radius = 168 + reach, i.e.
# 168..368 mm - see factory_layout.reach_coverage().
V = dict(
    # base plate enlarged to fill the bay between the sorting line and the HBW
    # (2026-09-27); the tower still stands at (CX, CY) from its front-left corner
    PLATE=(495.0, 740.0, 10.0),
    CX=180.0, CY=200.0,                    # tower / swivel centre
    RING_D=180.0, RING_Z=(14.0, 26.0),     # Drehkranz gear ring
    BASE_D=160.0, BASE_H=14.0,
    DISC_Z=(26.0, 38.0),
    # 600 mm columns: the arm must CROSS the oven (door guides 330 mm) and the
    # sorting line at a transit height with the cookie hanging below it, and
    # only then descend at a station. At 380 it could not clear the oven at all.
    # Four 15 x 15 slotted aluminium profiles in a square, as in the 536630
    # photos (fischertechnik doku-24v, booklet Abb. 6) - not two round posts.
    COL=15.0, COL_DX=50.0, COL_DY=15.0, COL_Z=(38.0, 600.0),
    TOP=(140.0, 50.0, 14.0),
    SPINDLE_D=12.0, PITCH_MM=4.0,
    CARR=(140.0, 54.0, 46.0),
    PLUNGE=(84.0, 540.0),                  # carriage bottom; top = 586 < 600. Floor 84: the
                                           # lowered sorting bays need contact 93 - 4 over-travel
    TRANSIT=500.0,                         # swing height: held cookie bottom 452 > rack cap
    # 500 long with a 280 stroke: the arm must still be gripped by the carriage
    # at full reach (back end CY+70 vs carriage CY+27), and it has to serve the
    # oven as well as the belt. Cup radius = 168..448.
    # 640 long with a 400 stroke: at full reach the back end is still CY+90,
    # behind the carriage (CY+27), so the arm is always gripped. Cup radius
    # = 168..568 mm.
    ARM=(30.0, 640.0, 26.0), ARM_FRONT=150.0,   # arm front face = CY - 150 - reach
    # the arm is two 12 x 12 profile rails joined by a front and a rear end
    # block (536630 photo), inside the ARM envelope
    ARM_RAIL=12.0, ARM_END=14.0,
    REACH=(0.0, 400.0),
    REACH_SPINDLE_D=10.0,
    SPRING=6.0,                             # spring stem travel before the cup is rigid
    # Upgrade 7: a 35 mm cup - the tolerance chain showed a 40 mm cup on a 45 mm
    # cookie cannot seal in the worst case (lifecycle.chains T3/T4)
    HEAD=(36.0, 36.0, 32.0), CUP_D=35.0 if UP7 else 40.0, CUP_H=14.0, STEM_D=18.0,
    # -125 rather than -95: the sorting line's Lagerstellen sit at -94..-113 deg,
    # and the station solver said so rather than anyone guessing.
    SWIVEL=(-125.0, 135.0), CARRY_FLOOR=100.0,
    MOTOR=(60.0, 30.0, 30.0), SWITCH=(30.0, 15.0, 7.5),
)

FRAMES = ["world", "swivel", "plunge", "reach"]
PARENT = {"world": None, "swivel": "world", "plunge": "swivel", "reach": "plunge"}


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
        if self.kind == "box":
            x, y, z = self.p; dx, dy, dz = self.s
            return (x, y, z, x + dx, y + dy, z + dz)
        ax, L, d = self.s
        x, y, z = self.p; r = d / 2.0
        if ax == "x":  return (x, y - r, z - r, x + L, y + r, z + r)
        if ax == "y":  return (x - r, y, z - r, x + r, y + L, z + r)
        return (x - r, y - r, z, x + r, y + r, z + L)


def _on_axis(part):
    """A Z cylinder centred on the swivel axis is unchanged by the swivel, so
    rotating its bounding box would inflate it by sqrt(2) for nothing."""
    return (part.kind == "cyl" and part.s[0] == "z"
            and abs(part.p[0] - V["CX"]) < 1e-9 and abs(part.p[1] - V["CY"]) < 1e-9)


def world_aabb(part, swivel_deg):
    """Rotate the part's eight corners about the tower axis and enclose them.
    Conservative for a rotated box: the enclosing box is never smaller than the
    true swept solid, so a PASS here is a real pass."""
    a = part.local_aabb()
    if part.frame == "world" or abs(swivel_deg) < 1e-9 or _on_axis(part):
        return a
    t = math.radians(swivel_deg)
    ct, st = math.cos(t), math.sin(t)
    cx, cy = V["CX"], V["CY"]
    xs, ys = [], []
    for x in (a[0], a[3]):
        for y in (a[1], a[4]):
            dx, dy = x - cx, y - cy
            xs.append(cx + dx * ct - dy * st)
            ys.append(cy + dx * st + dy * ct)
    return (min(xs), min(ys), a[2], max(xs), max(ys), a[5])


def build(swivel=0.0, plunge=250.0, reach=0.0):
    """swivel deg (0 = arm points -Y), plunge = carriage bottom z, reach mm."""
    q = V; out = []; A = out.append
    cx, cy = q["CX"], q["CY"]
    pz, rr = plunge, reach

    A(Part("vgr_plate", "frame", "box", (0, 0, -q["PLATE"][2]), q["PLATE"], "slate", "table"))

    # ------------------------------------------------------------ Drehkranz
    A(Part("drehkranz_base", "base", "cyl", (cx, cy, 0), ("z", q["BASE_H"], q["BASE_D"]),
           "black", "plate", note="fixed bearing seat"))
    A(Part("drehkranz_ring", "turn", "cyl", (cx, cy, q["RING_Z"][0]),
           ("z", q["RING_Z"][1] - q["RING_Z"][0], q["RING_D"]), "red", "drehkranz_base",
           frame="swivel", mech="spin:swivel", note="gear ring driven by M3"))
    A(Part("turntable_disc", "turn", "cyl", (cx, cy, q["DISC_Z"][0]),
           ("z", q["DISC_Z"][1] - q["DISC_Z"][0], q["RING_D"]), "black", "drehkranz_ring",
           frame="swivel", note="everything above this turns with the arm"))
    # M3 lies FLAT: upright it stood 60 mm tall and the arm swept straight
    # through it at the lowest plunge - the rotated-sweep check caught that.
    A(Part("M3_mount", "base", "box", (5, cy - 15, 0), (60, 30, q["RING_Z"][0]),
           "red", "plate"))
    A(Part("M3_swivel_motor", "base", "box", (5, cy - 15, q["RING_Z"][0]), (60, 30, 30),
           "ftred", "M3_mount", tag="Q5/Q6 + B5/B6", mech="motor:swivel",
           note="Encodermotor 144643 lying flat, under the arm's sweep"))
    A(Part("M3_pinion", "base", "cyl", (50, cy, q["RING_Z"][0]),
           ("z", q["RING_Z"][1] - q["RING_Z"][0], 90), "black", "M3_swivel_motor",
           mech="spin:swivel", note="meshes the Drehkranz ring"))
    A(Part("I3_ref_swivel", "base", "box", (cx - 15, 6, 0), q["SWITCH"], "green", "plate",
           tag="I3", note="Mini-Taster 37783, struck by a cam on the ring"))

    # ---------------------------------------------------------------- tower
    cz0, cz1 = q["COL_Z"]
    c, i = q["COL"], 0
    for sy in (-1, 1):
        for sx in (-1, 1):
            i += 1
            A(Part(f"tower_column_{i}", "tower", "box",
                   (cx + sx * q["COL_DX"] - c / 2, cy + sy * q["COL_DY"] - c / 2, cz0),
                   (c, c, cz1 - cz0), "alu", "turntable_disc", frame="swivel",
                   mech="profile:15",
                   note="15 x 15 slotted aluminium profile; the carriage slides on it "
                        "through a clearance pocket (GUIDES)"))
    tw, td, th = q["TOP"]
    A(Part("tower_top_plate", "tower", "box", (cx - tw / 2, cy - td / 2, cz1), (tw, td, th),
           "black", "tower_column_1", frame="swivel"))
    A(Part("plunge_spindle", "tower", "cyl", (cx + 25, cy, cz0), ("z", cz1 - cz0, q["SPINDLE_D"]),
           "red", "turntable_disc", frame="swivel", mech="thread:plunge",
           note="4 mm lead, offset 25 mm off the centreline so the arm can "
                "telescope straight through the tower"))
    A(Part("M1_plunge_motor", "tower", "box", (cx + 10, cy - 15, cz1 + th), (30, 30, 60),
           "ftred", "tower_top_plate", frame="swivel", tag="Q1/Q2 + B1/B2",
           mech="motor:plunge", note="Encodermotor 144643, shaft down onto the spindle"))
    A(Part("I1_ref_plunge", "tower", "box", (cx - tw / 2, cy - td / 2 + 2, cz1 + th),
           q["SWITCH"], "green", "tower_top_plate", frame="swivel", tag="I1",
           note="struck by the carriage at the top of the tower"))

    # ------------------------------------------------------------- carriage
    kw, kd, kh = q["CARR"]
    A(Part("plunge_carriage", "carriage", "box", (cx - kw / 2, cy - kd / 2, pz), (kw, kd, kh),
           "black", "columns", frame="plunge", note="clamp carriage on both columns"))
    # Spindle nut for the PLUNGE axis, on the carriage around the vertical spindle
    A(Part("plunge_nut", "carriage", "box", (cx + 15, cy - 10, pz + kh), (20, 20, 10),
           "amber", "plunge_carriage", frame="plunge",
           note="brass nut: the carriage climbs the plunge spindle through this"))
    # Spindle nut for the REACH axis, bolted to the carriage's front face. The
    # reach spindle runs ALONGSIDE the arm (not down its centreline) and turns
    # through this nut, so the arm - carrying spindle and motor - slides.
    sx_ = cx - aw_half(q) - 2 - q["REACH_SPINDLE_D"] / 2 - 2      # spindle axis x
    A(Part("reach_nut", "carriage", "box", (sx_ - 10, cy - kd / 2 - 12, pz + 9), (17, 12, 20),
           "amber", "plunge_carriage", frame="plunge",
           note="brass nut on the carriage face; the reach spindle turns through it"))
    A(Part("I2_ref_reach", "carriage", "box", (cx + 5, cy - kd / 2 - 4, pz + kh),
           q["SWITCH"], "green", "plunge_carriage", frame="plunge", tag="I2"))

    # ------------------------------------------------------------------ arm
    aw, ad, ah = q["ARM"]
    ay = cy - q["ARM_FRONT"] - rr            # arm front face
    rw, re = q["ARM_RAIL"], q["ARM_END"]
    rz = pz + 6 + (ah - rw) / 2
    for nm, x0 in (("L", cx - aw / 2), ("R", cx + aw / 2 - rw)):
        A(Part(f"arm_rail_{nm}", "arm", "box", (x0, ay + re, rz), (rw, ad - 2 * re, rw),
               "alu", "arm_end_F", frame="reach", mech="profile:12",
               note="profile rail; slides through the carriage's rail pockets (GUIDES)"))
    A(Part("arm_end_F", "arm", "box", (cx - aw / 2, ay, pz + 6), (aw, re, ah),
           "red", "arm_rail_L", frame="reach", note="front end block: joins the rails, "
           "carries the suction head and the front spindle bearing"))
    A(Part("arm_end_B", "arm", "box", (cx - aw / 2, ay + ad - re, pz + 6), (aw, re, ah),
           "red", "arm_rail_L", frame="reach", note="rear end block: joins the rails, "
           "carries M2 and the rear spindle bearing"))
    # Reach drive: spindle beside the arm in two bearing blocks, motor on the
    # arm's back end. Motor, bearings and spindle all ride with the arm.
    rd = q["REACH_SPINDLE_D"]
    for nm, by in (("F", ay + 4), ("B", ay + ad - 14)):
        A(Part(f"reach_bearing_{nm}", "arm", "box", (sx_ - 8, by, pz + 11), (17, 10, 16),
               "red", "arm_end_F" if nm == "F" else "arm_end_B", frame="reach",
               note="spindle bearing on the end block's side face"))
    A(Part("reach_spindle", "arm", "cyl", (sx_, ay + 4, pz + 19), ("y", ad - 4, rd),
           "steel", "reach_bearing_F", frame="reach", mech="thread:reach",
           note="4 mm lead; turns through reach_nut on the carriage"))
    A(Part("M2_reach_motor", "arm", "box", (sx_ - 15, ay + ad, pz + 4), (30, 60, 30),
           "ftred", "arm_end_B", frame="reach", tag="Q3/Q4 + B3/B4", mech="motor:reach",
           note="Encodermotor 144643 on the arm's back end, coaxial with the spindle"))

    hw, hd, hh = q["HEAD"]
    A(Part("suction_head", "arm", "box", (cx - hw / 2, ay - hd, pz + 6), (hw, hd, hh),
           "red", "arm_end_F", frame="reach"))
    A(Part("suction_stem", "arm", "cyl", (cx, ay - hd / 2, pz - 16), ("z", 22, q["STEM_D"]),
           "steel", "suction_head", frame="reach", mech="spring",
           note="guided rod inside a compression spring, screwed into the underside "
                "of the head; the cup rides on it and gives by up to SPRING mm when "
                "it lands on the cookie"))
    A(Part("suction_cup", "tool", "cyl", (cx, ay - hd / 2, pz - 28),
           ("z", q["CUP_H"], q["CUP_D"]), "black", "suction_stem", frame="reach", tag="Q8",
           note="cup underside at plunge-28: THAT is the pick plane"))

    # --------------------------------------------------------- pneumatics
    if not UP1:     # Upgrade 1: fed from the central air station (upgrade.py)
        A(Part("compressor", "control", "box", (10, 400, 0), (66.0, 30.0, 30.0), "blue", "plate",
               tag="Q7", note="Kompressor - the only unidirectional output on this module"))
    A(Part("vacuum_valve", "control", "box", (85, 407, 0), (40.0, 15.0, 33.0), "blue", "plate",
           tag="Q8", note="3/2-Wege-Magnetventil"))
    # Upgrade 7: to the plate's front edge - at x 100 it was 925 mm from the
    # nearest guard door, past the 850 mm an arm reaches (lifecycle.access)
    A(Part("vgr_pcb", "control", "box", (5 if UP7 else 100, 440, 0), (160, 100, 22), "green", "plate",
           note="24V adapter PCB: ST1 16-pol + ST2 10-pol"))
    if UP3:     # Upgrade 3: plunge + reach drag chains and the tower duct (chains.py)
        import chains
        out.extend(chains.vgr_parts(Part, pz, rr))
    return out


def aw_half(q):
    return q["ARM"][0] / 2.0


def held_cookie(swivel, plunge, reach, d=45.0, h=20.0):
    """The cookie on the suction cup: its TOP touches the cup underside at
    plunge-28, so it hangs from plunge-48. Its own group - a held workpiece may
    touch the cup and nothing else."""
    q = V
    ay = q["CY"] - q["ARM_FRONT"] - reach
    z = plunge - 28.0 - h
    return [
        Part("wp_held_body", "load", "cyl", (q["CX"], ay - q["HEAD"][1] / 2, z),
             ("z", h - 4, d), "white", "Q11_suction_cup", frame="reach"),
        Part("wp_held_lid", "load", "cyl", (q["CX"], ay - q["HEAD"][1] / 2, z + h - 4),
             ("z", 4, d), "colour", "wp_held_body", frame="reach"),
    ]


JOINED = [("base", "base"), ("turn", "turn"), ("base", "turn"), ("tower", "tower"),
          ("turn", "tower"), ("carriage", "carriage"), ("carriage", "tower"),
          ("arm", "arm"), ("arm", "carriage"), ("tool", "arm"), ("control", "control"),
          ("load", "tool"), ("load", "load"),
          ("chain", "chain")]             # Upgrade 3: a chain's brackets sit in its own envelope


def _ovl(a, b, tol=0.05):
    d = [min(a[i + 3], b[i + 3]) - max(a[i], b[i]) for i in range(3)]
    return min(d) if min(d) > tol else 0.0


def cup_radius(reach):
    """Radial distance of the suction cup from the swivel axis."""
    return V["ARM_FRONT"] + reach + V["HEAD"][1] / 2.0


def carry_allowed(plunge):
    """A LOADED arm has a tighter envelope than an empty one. The cookie hangs
    from plunge-48, and below the carry floor it is down at the level of M3,
    which lies flat across the base. Same rule the HBW needed for its mould."""
    return plunge >= V["CARRY_FLOOR"]


CANTILEVERS = {
    # Upgrade 3: chain brackets and envelopes hang on the side faces they bolt to
    "chain_plunge_env", "chain_plunge_fix", "chain_plunge_bracket", "chain_reach_env",
    "chain_reach_fix", "chain_reach_bracket", "tower_cable_duct",
    "drehkranz_ring", "turntable_disc", "M3_pinion", "tower_top_plate",
    "plunge_spindle", "M1_plunge_motor", "I1_ref_plunge", "plunge_carriage",
    "M2_reach_motor", "I2_ref_reach", "arm_rail_L", "arm_rail_R", "arm_end_F", "arm_end_B",
    "suction_head",
    "plunge_nut", "reach_nut", "reach_bearing_F", "reach_bearing_B", "reach_spindle",
    "suction_stem", "suction_cup", "tower_column_1", "tower_column_2",
    "tower_column_3", "tower_column_4",
}

# What slides through / turns in what. detail.py cuts the clearance pockets and
# nut bores from this table, and check_guides() proves on the exact B-rep that
# every pair has ZERO overlap and a real running clearance - the carriage is
# guided by its profiles, not drawn through them.
#   (host, guest, kind, clearance mm)   kind: slide | thread | bore
GUIDES = [
    *[("plunge_carriage", f"tower_column_{i}", "slide", 0.3) for i in range(1, 5)],
    ("plunge_carriage", "arm_rail_L", "slide", 0.3),
    ("plunge_carriage", "arm_rail_R", "slide", 0.3),
    ("plunge_carriage", "plunge_spindle", "bore", 1.0),
    ("plunge_carriage", "reach_spindle", "bore", 1.0),
    ("plunge_nut", "plunge_spindle", "thread", 0.05),
    ("reach_nut", "reach_spindle", "thread", 0.05),
    ("reach_bearing_F", "reach_spindle", "bore", 0.05),
    ("reach_bearing_B", "reach_spindle", "bore", 0.05),
]


def check(verbose=True):
    fails = []
    p0, p1 = V["PLUNGE"]; r0, r1 = V["REACH"]
    poses = [(sw, pz, rr)
             for sw in (-95.0, -45.0, 0.0, 45.0, 90.0, 135.0)
             for pz in (p0, (p0 + p1) / 2, p1)
             for rr in (r0, (r0 + r1) / 2, r1)]
    ok = {tuple(sorted(j)) for j in JOINED}
    for sw, pz, rr in poses:
        parts = build(sw, pz, rr)
        if carry_allowed(pz):
            parts = parts + held_cookie(sw, pz, rr)
        for a, b in combinations(parts, 2):
            if a.group == "frame" or b.group == "frame":
                continue
            if tuple(sorted((a.group, b.group))) in ok:
                continue
            # Everything above the Drehkranz turns as ONE rigid body, so its
            # internal clearances do not depend on the swivel - compare those
            # locally. Rotating vs static is the only pair that needs the
            # (conservative) rotated enclosure.
            if (a.frame == "world") == (b.frame == "world"):
                o = _ovl(a.local_aabb(), b.local_aabb())
            else:
                o = _ovl(world_aabb(a, sw), world_aabb(b, sw))
            if o:
                fails.append(f"INTERFERENCE {a.name} x {b.name} = {o:.1f} mm "
                             f"@ swivel={sw} plunge={pz} reach={rr}")
    import grounding
    fails += grounding.check_grounding(build(), {"columns": "tower_column_1"},
                                       cantilevers=CANTILEVERS)
    if verbose:
        print(f"parts: {len(build())}   poses checked: {len(poses)}")
        print("\n".join(fails) if fails else
              "ALL CHECKS PASS (no interference at any swivel/plunge/reach, nothing floating)")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if check() else 0)
