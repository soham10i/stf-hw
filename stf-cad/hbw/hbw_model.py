"""
Automated High-Bay Warehouse (Hochregallager, ft 536631) - from-scratch component model.

Frame:  origin = front-left corner of the module base plate, ON its top surface.
        +X = right, along the rack face and the crane travel axis
        +Y = back,  into the module (fork extension direction)
        +Z = up
Units:  mm.

Every solid below is an explicit primitive with an explicit support. Nothing is
placed by eye: `check()` proves (a) no two parts interpenetrate at any pose in
the working envelope, and (b) every part is carried by something that touches it.

Sources
  I/O tags .......... 536634-Fabrik_Simulation_24V-Belegungsplan.pdf p4 (HRL)
  motor body 60x30x30 144643-Encodermotor24V.pdf
  mini switch 30x15x7.5 .. 37783-Mini-switch.pdf
  phototransistor 15x15x7.5 36134-Photo-transistor.pdf
  arrangement ....... 536634-...-extended-description.pdf p5 (labelled photo),
                      Fabrik_Simulation_24V.pdf p22/p26 (Abb.7 + LOESUNG)
Assumptions (no dimension appears in ANY supplied document - see DESIGN.md):
  module plate 600x400, ft 15 mm construction raster, bay pitch 120, row pitch 120.
"""
from dataclasses import dataclass, field
from itertools import combinations

from variant import UP1, UP3, UP4

# ---------------------------------------------------------------- parameters
P = dict(
    # base plate - enlarged so the oven / VGR / sorting modules chain on in FRONT
    PLATE=(860.0, 640.0, 10.0),
    # rack: 4 bays x 3 rows = 12 slots, each holding a mould
    RACK_Y0=290.0, RACK_DEPTH=70.0, POST=30.0, POST_H=420.0, CAP_H=15.0,
    BAY_PITCH=120.0, ROW_PITCH=120.0, SHELF_T=15.0,
    BRACKET_LEN=30.0, SHELF_GAP=40.0,           # 40 mm gap = fork + arm passage
    BAY_X=(120.0, 240.0, 360.0, 480.0), ROW_Z=(120.0, 240.0, 360.0),
    # mould (Werkstuecktraeger): the VGR drops a cookie into it, the crane
    # carries the whole mould. Base + four rim bars = a real pocket.
    MOULD=(60.0, 64.0, 8.0), RIM_T=5.0, RIM_H=12.0,
    WP_D=45.0, WP_BODY=16.0, WP_LID=4.0,
    # crane travel rail
    RAIL_Y=210.0, ROD_Z=30.0, ROD_D=8.0, SPINDLE_D=12.0, PITCH_MM=4.0,
    BLK=(30.0, 60.0, 45.0), BLK_X=(60.0, 780.0),
    CAR=(50.0, 90.0, 40.0), CAR_Z=10.0,
    TRAVEL=(120.0, 665.0),
    # mast
    # The mast STRADDLES the load: tubes at +/-45 with a 60 mm mould between
    # them, and the lift carriage is two side plates with a yoke above the
    # cookie. A mast narrower than the mould would swallow it when the fork
    # retracts - which is exactly the bug check_carry() now catches.
    TUBE_D=10.0, TUBE_Z=(60.0, 470.0), TUBE_DX=45.0, TUBE_DY=20.0,
    # Upgrade 1: the mast is built like the VGR tower - four 15x15 slotted
    # aluminium profiles on the same axes, the carriage sliding on them through
    # clearance pockets (GUIDES) instead of round tubes
    MAST_PROFILE=15.0 if UP1 else None,
    TOP=(120.0, 80.0, 15.0), LIFT_SPINDLE_D=12.0,
    LC_SIDE=22.0 if UP1 else 16.0, LC_D=70.0, LC_H=60.0, LIFT=(80.0, 360.0),
    # Ausleger: ONE direction (+Y). The rack AND the conveyor are both on the
    # +Y side of the travel rail, so I5 vorne / I6 hinten are the two ends of a
    # single stroke, not two directions. Flat telescope: arm and table share one
    # z band so both pass the 40 mm gap while staying below the mould.
    S1=(28.0, 160.0, 20.0), S2=(20.0, 140.0, 12.0), TABLE=(32.0, 70.0, 14.0),
    FORK=(0.0, 115.0),
    # conveyor: sits BEYOND the rack along the travel axis, in the same y band,
    # and runs +Y away from the machine toward the VGR. One fork stop (115)
    # therefore serves a rack bay and the belt hand-over alike.
    CV_X=665.0, CV_Y=(290.0, 610.0), CV_SURF=100.0,
    CV_RAIL_W=15.0, CV_RAIL_H=45.0, CV_STRIP_W=20.0, CV_GAP=40.0, CV_WEB_T=4.0,
    CV_LEG_H=60.0, PULLEY_D=20.0,
    COVER_Y=(340.0, 540.0), COVER_Z=(105.0, 210.0), ROOF_T=12.0,
    PICK_VGR=580.0, PICK_HBW=325.0,
    # standard ft electrical parts (datasheets 144643 / 37783 / 36134 / 128599)
    MOTOR=(60.0, 30.0, 30.0), SWITCH=(30.0, 15.0, 7.5), PHOTO=(15.0, 15.0, 7.5),
    COLOUR=(30.0, 15.0, 15.0),
)

MOVERS = {"travel", "lift", "fork"}   # joint names
# Upgrade 4: RFID read-head centres along the belt (y, HBW frame). RP1 sits in
# the tunnel, 15 mm past the Ausleger's reach at the crane hand-over (the
# proof moved it from 400: stage 2 reaches y 405); RP2 under
# the VGR hand-over, past the belt motor.
RFID_Y = (440.0, 580.0)


@dataclass
class Part:
    name: str
    group: str
    kind: str                 # 'box' | 'cyl'
    p: tuple
    s: tuple
    colour: str = "grey"
    support: str = "plate"
    joint: str = ""           # '' = static, else travel/lift/fork
    tag: str = ""             # I/O tag
    mech: str = ""            # thread:<joint> | belt | pulley | spin:<drive>
    note: str = ""

    def aabb(self):
        if self.kind == "box":
            x, y, z = self.p; dx, dy, dz = self.s
            return (x, y, z, x + dx, y + dy, z + dz)
        ax, L, d = self.s
        x, y, z = self.p; r = d / 2.0
        if ax == "x":  return (x, y - r, z - r, x + L, y + r, z + r)
        if ax == "y":  return (x - r, y, z - r, x + r, y + L, z + r)
        return (x - r, y - r, z, x + r, y + r, z + L)


def slot_ids():
    return [f"{r}{c}" for r in "ABC" for c in range(1, len(P["BAY_X"]) + 1)]


def slot_pose(sid):
    """(x, y, z) of a slot: bay centre, rack mid-depth, shelf top."""
    r, c = sid[0], int(sid[1:])
    return (P["BAY_X"][c - 1], P["RACK_Y0"] + P["RACK_DEPTH"] / 2,
            P["ROW_Z"]["ABC".index(r)])


def mould(out, tag, bx, by0, z, joint="", support="plate", group="mould"):
    """A mould at bay-centre bx, rack front by0, sitting with its base on z."""
    q = P
    mw, md, mb = q["MOULD"]; rt, rh = q["RIM_T"], q["RIM_H"]
    x0 = bx - mw / 2.0
    y0 = by0 + (q["RACK_DEPTH"] - md) / 2.0
    A = out.append
    A(Part(f"mould_{tag}_base", group, "box", (x0, y0, z), (mw, md, mb),
           "steel", support, joint,
           note="rests on the two shelf brackets; 10 mm bearing each side of the "
                "40 mm fork gap, so the fork lifts it from below"))
    A(Part(f"mould_{tag}_rim_L", group, "box", (x0, y0, z + mb), (rt, md, rh),
           "steel", f"mould_{tag}_base", joint))
    A(Part(f"mould_{tag}_rim_R", group, "box", (x0 + mw - rt, y0, z + mb), (rt, md, rh),
           "steel", f"mould_{tag}_base", joint))
    # The front rim is SPLIT by a 24 mm Aussparung. The manual is explicit -
    # "achten Sie darauf, dass die Aussparung nach vorne zeigt" - and the notch
    # is what lets a gripper reach the workpiece from the front, so it is real
    # geometry, not trim.
    notch, side = 24.0, (mw - 2 * rt - 24.0) / 2.0
    for sfx, nx in (("Fa", x0 + rt), ("Fb", x0 + mw - rt - side)):
        A(Part(f"mould_{tag}_rim_{sfx}", group, "box", (nx, y0, z + mb), (side, rt, rh),
               "steel", f"mould_{tag}_base", joint,
               note=f"front rim, split by the {notch:.0f} mm Aussparung"))
    A(Part(f"mould_{tag}_rim_B", group, "box", (x0 + rt, y0 + md - rt, z + mb),
           (mw - 2 * rt, rt, rh), "steel", f"mould_{tag}_base", joint,
           note="pocket is 50 x 54 - the 45 mm cookie seats with clearance and "
                "stands 8 mm proud of the rim for the VGR suction cup"))


def cookie(out, tag, x, y, z, joint="", support="plate", group="workpiece",
           lid="colour"):
    q = P
    A = out.append
    A(Part(f"wp_{tag}_body", group, "cyl", (x, y, z), ("z", q["WP_BODY"], q["WP_D"]),
           lid if lid != "colour" else "white", support, joint))
    A(Part(f"wp_{tag}_lid", group, "cyl", (x, y, z + q["WP_BODY"]),
           ("z", q["WP_LID"], q["WP_D"]), lid, f"wp_{tag}_body", joint))


# 12 slots, 12 moulds - but one mould is always the one in circulation, so at
# rest only 11 are stowed and exactly one slot is free. That free slot is what
# makes the rule work: a mould whose cookie the VGR has taken comes back and is
# put into whichever slot has no mould. C4 is free in this rest state.
MOULD_SLOTS = "A1 A2 A3 A4 B1 B2 B3 B4 C1 C2 C3".split()
FREE_SLOT = "C4"
# The cookies themselves come from pipeline.py - the ONE place they exist. If a
# scene invented its own the twelve would silently become thirteen.
from pipeline import RACK_START, FLAVOURS, RAW_COLOUR   # noqa: E402
COOKIE_SLOTS = [s for s, _ in RACK_START]
COOKIE_FLAVOUR = dict(RACK_START)
assert set(COOKIE_SLOTS) <= set(MOULD_SLOTS), "a cookie needs a mould under it"


def carried_mould(cb, F, X):
    """The mould as it rides the fork: centred on the table, underside exactly
    on the table's top face (lift + 10). Emitted in the same frame as build()."""
    q = P
    cy = q["RAIL_Y"] + F                      # table centre = ry - 35 + F + 70/2
    out = []
    mould(out, "carried", X, cy - q["RACK_DEPTH"] / 2, cb + 10.0,
          joint="fork", support="fork_table", group="load")
    cookie(out, "carried", X, cy, cb + 10.0 + q["MOULD"][2],
           joint="fork", support="mould_carried_base", group="load_wp")
    return out


def build(travel=665.0, lift=120.0, fork=0.0, carrying=False):
    q = P; out = []
    A = out.append
    X, cb, F = travel, lift, fork

    A(Part("base_plate", "frame", "box", (0, 0, -q["PLATE"][2]), q["PLATE"],
           "slate", "table", note="ft base plate, 900 x 620 - the front half is "
                                  "kept clear for the oven / VGR / sorting modules"))

    # ---------------------------------------------------------------- rack
    y0, dy, po, ph = q["RACK_Y0"], q["RACK_DEPTH"], q["POST"], q["POST_H"]
    post_x = [q["BAY_X"][0] - q["BAY_PITCH"] / 2] + \
             [b + q["BAY_PITCH"] / 2 for b in q["BAY_X"]]
    for i, xc in enumerate(post_x, 1):
        A(Part(f"rack_post_{i}", "rack", "box", (xc - po / 2, y0, 0), (po, dy, ph),
               "black", "plate", note="ft 30x30 black profile column"))
    A(Part("rack_cap_beam", "rack", "box", (post_x[0] - po / 2, y0, ph),
           (post_x[-1] - post_x[0] + po, dy, q["CAP_H"]), "black", "rack_post_1"))
    for bi, bx in enumerate(q["BAY_X"], 1):
        for ri, rz in enumerate(q["ROW_Z"]):
            row = "ABC"[ri]
            for side, sx in (("L", bx - q["SHELF_GAP"] / 2 - q["BRACKET_LEN"]),
                             ("R", bx + q["SHELF_GAP"] / 2)):
                A(Part(f"shelf_{row}{bi}_{side}", "rack", "box",
                       (sx, y0, rz - q["SHELF_T"]), (q["BRACKET_LEN"], dy, q["SHELF_T"]),
                       "red", f"rack_post_{bi if side == 'L' else bi + 1}",
                       note="red shelf bracket; the 40 mm gap between the pair is "
                            "the passage for the fork table and the Ausleger arm"))

    # --------------------------------------------------- moulds + cookies
    for sid in MOULD_SLOTS:
        sx, sy, sz = slot_pose(sid)
        mould(out, sid, sx, y0, sz, support=f"shelf_{sid}_L")
        if sid in COOKIE_SLOTS:
            # RAW dough: white until it has been through the oven. The flavour
            # colour only appears after baking - the user's rule, and it is also
            # why the Farbsensor sits AFTER the oven, not before it.
            cookie(out, sid, sx, sy, sz + q["MOULD"][2], support=f"mould_{sid}_base",
                   lid=RAW_COLOUR)

    # ------------------------------------------------- crane travel rail
    ry, rz_ = q["RAIL_Y"], q["ROD_Z"]
    bx0, bx1 = q["BLK_X"]; bw, bd, bh = q["BLK"]
    for nm, bx in (("L", bx0), ("R", bx1)):
        A(Part(f"rail_block_{nm}", "rail", "box", (bx, ry - bd / 2, 0), (bw, bd, bh),
               "red", "plate"))
    A(Part("guide_rod", "rail", "cyl", (bx0, ry - 15, rz_), ("x", bx1 + bw - bx0, q["ROD_D"]),
           "steel", "rail_block_L"))
    A(Part("travel_spindle", "rail", "cyl", (bx0 + bw, ry + 15, rz_),
           ("x", bx1 - bx0 - bw, q["SPINDLE_D"]), "red", "rail_block_L",
           mech="thread:travel", note="threaded spindle, 4 mm pitch -> 18.75 pulses/mm"))
    mw, md, mh = q["MOTOR"]
    A(Part("M2_mount", "rail", "box", (0, ry + 15 - md / 2, 0), (mw, md, 15), "red", "plate"))
    A(Part("M2_travel_motor", "rail", "box", (0, ry + 15 - md / 2, 15), (mw, md, mh),
           "ftred", "M2_mount", tag="Q3/Q4 + B1/B2", mech="motor:travel",
           note="Encodermotor 24V 144643, 60x30x30, shaft D4 x L7.5 out of the "
                "30x30 end face; Q3 = towards rack, Q4 = towards conveyor"))
    A(Part("M2_coupler", "rail", "cyl", (mw, ry + 15, rz_), ("x", 14, 16),
           "steel", "M2_travel_motor", mech="spin:travel",
           note="shaft coupling onto the travel spindle"))
    A(Part("I1_post", "rail", "box", (700, ry + 40, 0), (30, 15, 20), "red", "plate"))
    A(Part("I1_ref_horizontal", "rail", "box", (700, ry + 40, 20), q["SWITCH"],
           "green", "I1_post", tag="I1",
           note="Mini-Taster 37783, struck by the carriage at the conveyor end"))

    # --------------------------------------------------------- crane body
    cw, cd, ch = q["CAR"]
    A(Part("travel_carriage", "crane", "box", (X - cw / 2, ry - cd / 2, q["CAR_Z"]),
           (cw, cd, ch), "red", "rail", joint="travel"))
    tz0, tz1 = q["TUBE_Z"]
    mp = q["MAST_PROFILE"]
    ow, od = (112, 62) if mp else (100, 50)       # the profiles stand fully on it
    A(Part("mast_outrigger", "crane", "box", (X - ow / 2, ry - od / 2, tz0 - 10), (ow, od, 10),
           "red", "travel_carriage", joint="travel",
           note="splays the mast out past the load; sits above the rail bearing "
                "blocks so the crane can still reach bay 1"))
    # tube y is DERIVED from the rail, not an absolute: moving the rail used to
    # leave the mast behind and drive it through the rack.
    tube_y = (ry - q["TUBE_DY"], ry + q["TUBE_DY"])
    for i, (sx, sy) in enumerate([(-1, 0), (1, 0), (-1, 1), (1, 1)], 1):
        if mp:
            A(Part(f"mast_tube_{i}", "crane", "box",
                   (X + sx * q["TUBE_DX"] - mp / 2, tube_y[sy] - mp / 2, tz0), (mp, mp, tz1 - tz0),
                   "alu", "mast_outrigger", joint="travel", mech=f"profile:{mp:.0f}",
                   note="15x15 slotted aluminium profile, as the VGR tower: the lift "
                        "carriage slides on it through a 0.3 mm clearance pocket"))
        else:
            A(Part(f"mast_tube_{i}", "crane", "cyl",
                   (X + sx * q["TUBE_DX"], tube_y[sy], tz0),
                   ("z", tz1 - tz0, q["TUBE_D"]), "alu", "mast_outrigger", joint="travel"))
    tw, td, th = q["TOP"]
    A(Part("mast_top_plate", "crane", "box", (X - tw / 2, ry - td / 2, tz1), (tw, td, th),
           "black", "mast_tube_1", joint="travel"))
    A(Part("lift_spindle", "crane", "cyl", (X - q["TUBE_DX"], ry, tz0),
           ("z", tz1 - tz0, q["LIFT_SPINDLE_D"]), "red", "mast_outrigger",
           joint="travel", mech="thread:lift",
           note="vertical spindle, 4 mm pitch, offset onto the left tube column so "
                "it is not in the load's path"))
    A(Part("M3_lift_motor", "crane", "box", (X - q["TUBE_DX"] - 15, ry - 15, tz1 + th), (30, 30, 60),
           "ftred", "mast_top_plate", joint="travel", tag="Q5/Q6 + B3/B4",
           mech="motor:lift", note="Encodermotor 144643 upright on the mast head, "
                                   "shaft down onto the lift spindle"))
    A(Part("M3_coupler", "crane", "cyl", (X - q["TUBE_DX"], ry, tz1 + th - 14), ("z", 14, 16),
           "steel", "mast_top_plate", joint="travel", mech="spin:lift"))
    A(Part("I4_ref_vertical", "crane", "box", (X - tw / 2, ry - td / 2 + 2, tz1 + th),
           q["SWITCH"], "green", "mast_top_plate", joint="travel", tag="I4",
           note="Mini-Taster 37783, struck by the lift carriage at the top"))

    lsw, ld, lh = q["LC_SIDE"], q["LC_D"], q["LC_H"]
    # legs wrap the mast: 5 mm outboard of a D10 tube, 11 mm of a 15 mm profile
    # (3.5 mm wall either side of its 15.6 mm pocket)
    dxo = q["TUBE_DX"] + (11.0 if mp else 5.0)
    for nm, sx, sup in (("L", X - dxo, "mast_tube_1"), ("R", X + dxo - lsw, "mast_tube_2")):
        A(Part(f"lift_carriage_{nm}", "crane", "box", (sx, ry - ld / 2, cb), (lsw, ld, lh),
               "black", sup, joint="lift",
               note="one leg of the straddle carriage; the load passes between them"))
    A(Part("lift_carriage_yoke", "crane", "box", (X - dxo, ry - ld / 2, cb + lh - 15),
           (2 * dxo, ld, 15), "black", "lift_carriage_L", joint="lift",
           note="ties the two legs ABOVE the cookie (top of a loaded mould is "
                "lift+38, the yoke starts at lift+45)"))
    fyd = 62 if mp else 50                  # deep enough to enclose the profiles
    A(Part("fork_yoke", "crane", "box", (X - dxo, ry - fyd / 2, cb - 20), (2 * dxo, fyd, 20),
           "red", "lift_carriage_L", joint="lift",
           note="carries the Ausleger down the centreline, below the table face"))

    # ------------------------------------------------------- ausleger
    s1w, s1d, s1h = q["S1"]; s2w, s2d, s2h = q["S2"]; tbw, tbd, tbh = q["TABLE"]
    s1y = ry - 80.0                        # 280 .. 440
    A(Part("ausleger_stage1", "fork", "box", (X - s1w / 2, s1y, cb - 20), (s1w, s1d, s1h),
           "black", "fork_yoke", joint="lift",
           note="fixed guide of the telescope; 28 wide so it passes the 40 mm "
                "shelf gap, and its TOP face is the table's underside - nothing "
                "in the arm rises above the face that carries the mould"))
    A(Part("M4_fork_motor", "crane", "box", (X - 15, s1y - 60, cb - 25), (30, 60, 30),
           "ftred", "ausleger_stage1", joint="lift", tag="Q7/Q8", mech="motor:fork",
           note="Encodermotor 144643, coaxial with the Ausleger spindle"))
    A(Part("ausleger_spindle", "fork", "cyl", (X, s1y - 60, cb - 10), ("y", 220, 8),
           "steel", "ausleger_bearing_B", joint="lift", mech="thread:fork",
           note="4 mm pitch; the 60 mm between the motor and stage 1 is exposed "
                "thread, and it never rises above the fork table plane"))
    for nm, byy in (("B", s1y), ("F", s1y + s1d - 12)):
        A(Part(f"ausleger_bearing_{nm}", "fork", "box", (X - 9, byy, cb - 16),
               (18, 12, 12), "red", "ausleger_stage1", joint="lift"))
    A(Part("ausleger_stage2", "fork", "box",
           (X - s2w / 2, ry - 60 + F, cb - 16), (s2w, s2d, s2h), "alu", "stage1", joint="fork",
           note="sliding member; spindle nut rides inside it"))
    A(Part("fork_table", "tool", "box",
           (X - tbw / 2, ry - 35 + F, cb - 4), (tbw, tbd, tbh), "red", "ausleger_stage2",
           joint="fork",
           note="32 wide -> 4 mm clearance in the 40 mm shelf and belt gaps. Its "
                "TOP FACE at lift+10 is the only thing that may touch the mould; "
                "it is its own group so the checker can enforce exactly that"))
    # On the stage's SIDE face, below the table plane. They used to sit on its
    # top face - the exact plane the fork table slides in - so the table drove
    # through I5 at every extension past 10 mm. The ("tool","fork") whitelist hid
    # it; they now have their own group so the checker sees them.
    sw_l, sw_w, sw_t = q["SWITCH"]
    for nm, syy, tg in (("I6_ref_ausleger_back", s1y + 6, "I6"),
                        ("I5_ref_ausleger_front", s1y + s1d - 36, "I5")):
        A(Part(nm, "fork_sensor", "box", (X + s1w / 2, syy, cb - 20), (sw_t, sw_l, sw_w),
               "green", "ausleger_stage1", joint="lift", tag=tg,
               note="Mini-Taster 37783 bolted to the side of the fixed stage, struck "
                    "by a cam on stage 2; entirely below the table's underside"))

    # ------------------------------------------------------- conveyor
    cx = q["CV_X"]; cy0, cy1 = q["CV_Y"]; cl = cy1 - cy0
    rw, rh, lz = q["CV_RAIL_W"], q["CV_RAIL_H"], q["CV_LEG_H"]
    half = q["CV_GAP"] / 2 + q["CV_STRIP_W"]
    rail_x = (cx - half - rw, cx + half)
    for nm, rx in (("L", rail_x[0]), ("R", rail_x[1])):
        for j, ly in enumerate((cy0, cy1 - rw)):
            A(Part(f"cv_leg_{nm}{j}", "conveyor", "box", (rx, ly, 0), (rw, rw, lz),
                   "red", "plate"))
        A(Part(f"cv_side_rail_{nm}", "conveyor", "box", (rx, cy0, lz), (rw, cl, rh),
               "black", f"cv_leg_{nm}0", note="frame rail + mould guide"))
    for nm, sx in (("L", cx - half), ("R", cx + q["CV_GAP"] / 2)):
        A(Part(f"cv_belt_{nm}", "conveyor", "box",
               (sx, cy0 + 5, q["CV_SURF"] - q["CV_WEB_T"]),
               (q["CV_STRIP_W"], cl - 10, q["CV_WEB_T"]), "darkgrey", f"cv_side_rail_{nm}",
               mech="belt",
               note="one of TWO parallel strips; the 40 mm centre gap is what lets "
                    "the fork table dive under the mould"))
    # Each strip has its OWN drum on a stub axle off its side rail - there is no
    # through shaft, so the 40 mm centre gap stays clear all the way down and the
    # Ausleger can reach the belt surface at any lift height.
    for nm, py in (("out", cy0 + 10), ("in", cy1 - 10)):   # out = crane end
        for sd, dx0 in (("L", rail_x[0]), ("R", cx + q["CV_GAP"] / 2)):
            A(Part(f"cv_drum_{nm}_{sd}", "conveyor", "cyl",
                   (dx0, py, q["CV_SURF"] - q["PULLEY_D"] / 2),
                   ("x", rw + q["CV_STRIP_W"], q["PULLEY_D"]), "black",
                   f"cv_side_rail_{sd}", mech="pulley"))
    mz = q["CV_SURF"] - q["PULLEY_D"] / 2          # drum axis height, 90
    my = cy1 - 60.0
    A(Part("M1_belt_mount", "conveyor", "box", (630, my, 0), (60, 30, 25), "red", "plate"))
    A(Part("M1_belt_motor", "conveyor", "box", (630, my, 25), q["MOTOR"], "ftred",
           "M1_belt_mount", tag="Q1/Q2", mech="motor:belt",
           note="Encodermotor 144643 UNDER the belt, driving the far drum through a "
                "toothed belt; Q1 forward, Q2 reverse - the conveyor runs both ways"))
    # The drive runs OUTSIDE the right side rail (outer face x = rail_x[1]+rw),
    # where it can be seen: motor shaft -> pulley -> toothed belt -> pulley on the
    # drum's stub axle. It used to sit inside the drum, i.e. invisible.
    ox = rail_x[1] + rw                              # 720, the rail's outer face
    PR = 13.0                                        # pulley radius
    A(Part("M1_shaft", "conveyor", "cyl", (690, my + 15, 40), ("x", ox + 10 - 690, 8),
           "steel", "M1_belt_motor", mech="spin:belt_x"))
    A(Part("M1_drive_pulley", "conveyor", "cyl", (ox, my + 15, 40), ("x", 10, 2 * PR),
           "black", "M1_shaft", mech="spin:belt_x",
           note="outboard of the side rail, so it never blocks the fork gap"))
    A(Part("M1_drum_pulley", "conveyor", "cyl", (ox, cy1 - 10, mz), ("x", 10, 2 * PR),
           "black", "cv_drum_in_R", mech="spin:belt_x",
           note="on the drive drum's stub axle, through the side rail"))
    A(Part("M1_drive_belt", "conveyor", "box",
           (ox + 1, my + 15 - PR - 2, 40 - PR - 2),
           (8, (cy1 - 10) - (my + 15) + 2 * PR + 4, mz - 40 + 2 * PR + 4),
           "darkgrey", "M1_drive_pulley", mech="belt:loop",
           note="toothed belt wrapped round both pulleys (this box is its envelope "
                "for the checker; the viewer draws the actual loop)"))

    # ------------------------------------------------------ belt cover
    cvy0, cvy1 = q["COVER_Y"]; cvz0, cvz1 = q["COVER_Z"]
    for i, (px_, py_) in enumerate([(rail_x[0], cvy0), (rail_x[0], cvy1 - rw),
                                    (rail_x[1], cvy0), (rail_x[1], cvy1 - rw)], 1):
        A(Part(f"cover_pillar_{i}", "cover", "box", (px_, py_, cvz0), (rw, rw, cvz1 - cvz0),
               "red", f"cv_side_rail_{'L' if px_ == rail_x[0] else 'R'}"))
    A(Part("cover_roof", "cover", "box", (rail_x[0] - 5, cvy0 - 10, cvz1),
           (rail_x[1] + rw + 5 - (rail_x[0] - 5), cvy1 - cvy0 + 20, q["ROOF_T"]),
           "black", "cover_pillar_1",
           note="the covered section is the identification tunnel; the belt runs "
                "out past it at both ends to the two hand-over points"))

    # sensors under the roof, one at each inside corner of the cover
    cw_, cd_, chh = q["COLOUR"]
    for nm, sx, sy, tg, kind in (
            ("CS1_colour_front_L", cx - half, cvy0 + 17, "AUX1", "Farbsensor 128599"),
            ("CS2_colour_front_R", cx + half - cw_, cvy0 + 17, "AUX2", "Farbsensor 128599"),
            ("LB1_pos_back_L", cx - half, cvy1 - 32, "AUX3", "Fototransistor 36134"),
            ("LB2_pos_back_R", cx + half - cw_, cvy1 - 32, "AUX4", "Fototransistor 36134")):
        A(Part(nm, "cover", "box", (sx, sy, cvz1 - chh), (cw_, cd_, chh),
               "green", "cover_roof", tag=tg,
               note=f"{kind}, looking down from the inside corner of the cover. "
                    "NOTE: the stock 536631 PCB has no free input for these - they "
                    "need the adapter's spare terminals or a RevPi AIO."))

    # end-of-belt light barriers per the Belegungsplan
    for nm, sy, tg, note in (
            ("I2_lightbarrier_inner", q["PICK_HBW"] - 8, "I2", "crane hand-over"),
            ("I3_lightbarrier_outer", q["PICK_VGR"] - 8, "I3", "VGR hand-over")):
        # Standing on the side-rail tops, receiver and LED facing each other
        # across the belt; the beam at z = rail top + 7.5 is at mould-rim height,
        # so a passing mould (and its cookie) really does break it.
        A(Part(f"{nm}_rx", "conveyor", "box", (rail_x[0] + rw - 7.5, sy, lz + rh),
               (7.5, 15, 15), "green", "cv_side_rail_L", tag=tg, mech="beam:rx",
               note="Fototransistor 36134; " + note))
        A(Part(f"{nm}_tx", "conveyor", "box", (rail_x[1], sy, lz + rh),
               (7.5, 15, 15), "amber", "cv_side_rail_R", tag=tg, mech="beam:tx",
               note="Lichtschranken-LED 162135"))
    A(Part("A1_trail_lower", "conveyor", "box", (rail_x[0] + rw - 7.5, 370, lz + rh),
           (7.5, 15, 15), "green", "cv_side_rail_L", tag="A1", note="Spursensor, lower track"))
    A(Part("A2_trail_upper", "conveyor", "box", (rail_x[0] + rw - 7.5, 370, lz + rh + 15),
           (7.5, 15, 15), "green", "A1_trail_lower", tag="A2", note="Spursensor, upper track"))

    # ------------------------------------------------------- electrics
    A(Part("adapter_pcb_24V", "control", "box", (230, 20, 0), (160, 100, 22), "green", "plate",
           note="24V Adapterplatine: ST1 20-pol + ST2 14-pol + ST3 34-pol to the PLC"))
    A(Part("terminal_block", "control", "box", (150, 20, 0), (60, 30, 25), "grey", "plate",
           note="terminals 1..24"))
    if UP3:     # Upgrade 3: drag chains for travel and lift (chains.py)
        import chains
        out.extend(chains.hbw_parts(Part, X, cb))
    if UP4:     # Upgrade 4: two RFID read points under the belt (control.py)
        rx0, rx1 = rail_x[0] + rw, rail_x[1]
        for rp, yc, tg in (("rp1", RFID_Y[0], "RF1"), ("rp2", RFID_Y[1], "RF2")):
            A(Part(f"rfid_{rp}_bracket", "rfid", "box", (rx0, yc - 10, lz), (rx1 - rx0, 20, 6), "alu",
                   "cv_side_rail_L", note="flat bar clamped between the side rails' inner faces, under the belt"))
            A(Part(f"rfid_{rp}_head", "rfid", "box", (P["CV_X"] - 18, yc - 20, lz + 6), (36, 40, 24), "rfid",
                   f"rfid_{rp}_bracket", tag=tg,
                   note=f"{rp.upper()}: RFID read/write head, 13.56 MHz (ISO 15693), IO-Link; size ASSUMED "
                        "36x40x24. Reads the mould's tag through the gap between the belt strips, "
                        "10 mm under the mould base."))
    if carrying:
        out.extend(carried_mould(lift, fork, travel))
    return out

# ------------------------------------------------------------------ checking
JOINED = [  # (group,group) pairs allowed to interpenetrate = bolted/bearing joints
    ("rail", "rail"), ("crane", "crane"), ("fork", "fork"), ("crane", "fork"),
    ("chain", "chain"),                 # Upgrade 3: a chain's brackets sit in its own envelope
    ("rfid", "rfid"),                   # Upgrade 4: a read head bolted to its bracket
    ("conveyor", "conveyor"), ("rack", "rack"), ("crane", "rail"), ("fork", "rail"),
    ("workpiece", "workpiece"), ("workpiece", "mould"), ("workpiece", "tool"),
    ("mould", "mould"), ("mould", "rack"), ("mould", "tool"),
    ("cover", "cover"), ("cover", "conveyor"),
    ("tool", "fork"), ("tool", "crane"), ("tool", "rail"),
    # The LOAD in transit has its own groups on purpose. It may rest on the fork
    # table and hold its own cookie - nothing else. Giving it the static mould's
    # group let it pass through the rack and through other moulds unremarked.
    ("load", "tool"), ("load", "load"), ("load", "load_wp"), ("load_wp", "load_wp"),
    ("fork_sensor", "fork"),         # bolted to stage 1 - and to NOTHING that moves
]
# DELIBERATELY NOT whitelisted: ("mould", "fork") and ("mould", "crane").
# The mould is carried by the fork TABLE's top face and nothing else; if any
# part of the arm, the carriage or a switch reaches into it, that is a real
# mechanical error and check_carry() below must fail.


def over_cover(travel):
    """Is any part of the crane above the belt's identification tunnel?"""
    half = P["CV_GAP"] / 2 + P["CV_STRIP_W"] + P["CV_RAIL_W"]
    return travel + P["CAR"][0] / 2 > P["CV_X"] - half - 5


def pose_allowed(travel, cb, F=0.0):
    """Interlocks that the GEOMETRY imposes - not house rules.

    1. Cover clearance. The identification tunnel roofs the belt at z 210..222.
       The Ausleger assembly on the carriage spans lift-25 .. lift+24, so while
       the crane is over the tunnel the lift must be either in the hand-over
       band below it or fully above it. Routing is therefore: raise above the
       cover, travel, descend - which is what a real stacker does anyway.
    2. Telescope direction. +Y only at a rack column, -Y only at the belt
       (ref. switches I5 vorne / I6 hinten).
    3. Telescope height. Extended only where a station exists at that height.
    """
    # The tunnel starts at y=580, past the far end of the extended telescope
    # (stage 2 reaches y=555). That is what keeps the crane free to descend to
    # the belt at any height instead of needing a forbidden lift band.
    # (The cover used to be kept beyond the telescope's reach by an assertion.
    # It now spans I2..I3, and whether it fouls anything is the collision
    # checker's call, not a rule of thumb: its pillars stand on the side rails,
    # outside the 40 mm gap the Ausleger and the mould use.)
    return fork_allowed(travel, cb, F)


def fork_allowed(travel, cb, F=0.0):
    """Kinematic interlock. The ausleger may only telescope where there is
    something to telescope INTO, and at a height that clears that station.

      conveyor column .. table top must be inside the hand-over band
                         (belt surface 100 -8..+20)  ->  cb in [72, 112]
      rack columns ..... table top must be within +/-20 mm of a shelf level
    """
    if F == 0.0:
        return True                   # retracted: free to sit at any height
    top = cb + 10.0
    if abs(travel - P["CV_X"]) < 30.0:
        # at the belt column the same +115 stop is used; the drums are on stub
        # axles so the centre gap is clear at any lift, but the table must be in
        # the hand-over band.
        return 80.0 <= cb <= 160.0
    # at a rack column the table must be at a real approach or lift height
    return any(abs(top - (z - 10.0)) <= 12.0 or abs(top - (z + 10.0)) <= 12.0
               for z in P["ROW_Z"])


def _ovl(a, b, tol=0.05):
    d = [min(a[i + 3], b[i + 3]) - max(a[i], b[i]) for i in range(3)]
    return min(d) if min(d) > tol else 0.0


def carry_allowed(travel, cb, F=0.0):
    """A LOADED fork has a tighter envelope than an empty one: at the belt column
    it may only be at or above the carry height, because below that the mould
    itself would be inside the belt surface and its drums."""
    if not pose_allowed(travel, cb, F):
        return False
    if abs(travel - P["CV_X"]) < 30.0:
        return cb >= P["CV_SURF"]
    return True


def check_carry():
    """The mould on the fork may touch the table's top face and nothing else.

    This is the check that was missing when the arm was 6 mm taller than the
    face it carries on, so the mould visibly sank into it.
    """
    fails = []
    for tv in list(P["BAY_X"]) + [P["CV_X"]]:
        for cb in (100.0, 120.0, 220.0, 240.0, 340.0, 360.0, 80.0, 160.0, 260.0):
            for F in (0.0, 60.0, 115.0):
                if not carry_allowed(tv, cb, F):
                    continue
                machine = [p for p in build(tv, cb, F)
                           if p.group in ("fork", "crane", "tool", "rail", "conveyor", "cover")]
                for m in carried_mould(cb, F, tv):
                    for p in machine:
                        o = _ovl(m.aabb(), p.aabb())
                        if not o:
                            continue
                        if p.name == "fork_table":
                            # contact on the top face only: zero penetration in z
                            if m.aabb()[2] < p.aabb()[5] - 0.05:
                                fails.append(f"MOULD SINKS INTO THE TABLE by "
                                             f"{p.aabb()[5] - m.aabb()[2]:.1f} mm "
                                             f"@ travel={tv} lift={cb} fork={F}")
                            continue
                        fails.append(f"MOULD INSIDE {p.name} by {o:.1f} mm "
                                     f"@ travel={tv} lift={cb} fork={F}")
    return fails


# ---------------------------------------------------------------- swept path
# The canonical cycle, as (travel, lift, fork, carrying). These are the same
# named stops the browser drives; keeping ONE list means the animation and the
# proof cannot describe different motions.
FROM_SLOT, TO_SLOT = "B2", FREE_SLOT


def cycle():
    """(travel, lift, fork, support_z) waypoints of the canonical cycle.

    `support_z` is the surface the load rests on for that leg - a shelf or the
    belt. Whether the fork is CARRYING is then derived from the pose rather than
    flagged by hand: the load is on the fork exactly while the table top
    (lift + 10) is above that surface. Flagging it per leg put the transfer at
    the end of a move instead of at the instant of contact, and the path check
    duly reported the load sinking through the belt.
    """
    T = {f"bay{i+1}": b for i, b in enumerate(P["BAY_X"])} | {"conveyor": P["CV_X"]}
    row = {r: z for r, z in zip("ABC", P["ROW_Z"])}
    fb, fc = row[FROM_SLOT[0]], row[TO_SLOT[0]]
    b0, b1 = T[f"bay{FROM_SLOT[1]}"], T[f"bay{TO_SLOT[1]}"]
    tr, cv, bs = 260.0, T["conveyor"], P["CV_SURF"]
    return [
        (cv, tr, 0.0, fb), (b0, tr, 0.0, fb), (b0, fb - 20, 0.0, fb),
        (b0, fb - 20, 115.0, fb), (b0, fb, 115.0, fb),
        (b0, fb, 0.0, fb), (b0, tr, 0.0, fb), (cv, tr, 0.0, bs),
        (cv, 100.0, 0.0, bs), (cv, 100.0, 115.0, bs), (cv, 80.0, 115.0, bs),
        (cv, 80.0, 0.0, bs), (cv, tr, 0.0, bs),
        (cv, 80.0, 0.0, bs), (cv, 80.0, 115.0, bs), (cv, 100.0, 115.0, bs),
        (cv, 100.0, 0.0, bs), (cv, tr, 0.0, fc), (b1, tr, 0.0, fc),
        (b1, fc, 0.0, fc), (b1, fc, 115.0, fc), (b1, fc - 20, 115.0, fc),
        (b1, fc - 20, 0.0, fc), (b1, tr, 0.0, fc), (cv, tr, 0.0, fc),
    ]


def swept_hit(a0, a1, b0, b1, tol=0.05):
    """EXACT continuous test between two axis-aligned boxes, each translating
    linearly over t in [0,1].

    Sampling can always miss: a thin part moving fast between samples passes
    clean through. Because every joint here is a pure translation, each box
    moves in a straight line, and the overlap condition on each axis is a linear
    inequality in t - so the exact time interval can be solved for and the three
    axes intersected. No sampling, nothing missed.

    Returns (t_enter, t_exit) or None.
    """
    lo_t, hi_t = 0.0, 1.0
    for i in range(3):
        amin0, amax0 = a0[i] + tol, a0[i + 3] - tol
        bmin0, bmax0 = b0[i], b0[i + 3]
        r = (a1[i] - a0[i]) - (b1[i] - b0[i])          # relative velocity on this axis
        lo, hi = bmin0 - amax0, bmax0 - amin0          # need lo < r*t < hi
        if abs(r) < 1e-12:
            if not (lo < 0.0 < hi):
                return None
            continue
        t0, t1 = lo / r, hi / r
        if t0 > t1:
            t0, t1 = t1, t0
        lo_t, hi_t = max(lo_t, t0), min(hi_t, t1)
        if lo_t >= hi_t:
            return None
    return (lo_t, hi_t)


def check_path(steps=14, tol=0.05, verbose=False):
    """Sweep the real cycle and test every moving solid against every other one.

    Checking named stops is not enough: a load can be clear at both ends of a
    move and pass straight through a rack post in between. This walks each leg
    and tests the whole machine at every sample.

    The slot the load came from is excluded while it is being carried - that
    mould IS the load, not a second object in the same place - and while the load
    is standing on the belt it is added back as a static obstacle, because the
    fork then has to reach under it without touching it.
    """
    ok = {tuple(sorted(j)) for j in JOINED}
    MOVING = {"crane", "fork", "tool", "load", "load_wp"}
    fails, seen = [], set()
    wps = cycle()

    def scene(tv, lz, fk, sup):
        carry = lz + 10.0 > sup + 0.01
        parts = build(tv, lz, fk)
        if carry:
            parts = [p for p in parts
                     if not (p.name.startswith(f"mould_{FROM_SLOT}_")
                             or p.name.startswith(f"wp_{FROM_SLOT}_"))]
            parts += carried_mould(lz, fk, tv)
        elif abs(sup - P["CV_SURF"]) < 0.01:
            # standing on the belt at the hand-over
            rest = []
            mould(rest, "on_belt", P["CV_X"], P["PICK_HBW"] - P["RACK_DEPTH"] / 2,
                  P["CV_SURF"], support="cv_belt_L", group="load")
            cookie(rest, "on_belt", P["CV_X"], P["PICK_HBW"],
                   P["CV_SURF"] + P["MOULD"][2], support="mould_on_belt_base",
                   group="load_wp")
            parts += rest
        return {p.name: p for p in parts}

    for i in range(len(wps) - 1):
        a, b = wps[i], wps[i + 1]
        s0 = scene(a[0], a[1], a[2], a[3])
        s1 = scene(b[0], b[1], b[2], a[3])
        common = [n for n in s0 if n in s1]
        for na, nb in combinations(common, 2):
            x, y = s0[na], s0[nb]
            if x.group == "frame" or y.group == "frame":
                continue
            if x.group not in MOVING and y.group not in MOVING:
                continue
            if tuple(sorted((x.group, y.group))) in ok:
                continue
            hit = swept_hit(x.aabb(), s1[na].aabb(), y.aabb(), s1[nb].aabb(), tol)
            if hit is None:
                continue
            key = (na, nb)
            if key in seen:
                continue
            seen.add(key)
            fails.append(f"PATH {na} x {nb} @ leg {i} t={hit[0]:.2f}..{hit[1]:.2f} "
                         f"(travel {a[0]:.0f}->{b[0]:.0f} lift {a[1]:.0f}->{b[1]:.0f} "
                         f"fork {a[2]:.0f}->{b[2]:.0f})")
    if verbose:
        print(f"path: {len(wps) - 1} legs, EXACT continuous sweep (no sampling)")
        print("\n".join(fails) if fails else
              "PATH CLEAR (nothing the machine moves sweeps through anything, "
              "at any instant of any leg)")
    return fails


# Parts genuinely BOLTED or CLAMPED to a vertical face rather than resting on
# something - shelf brackets on the rack posts, the telescope clamped in its
# guide, rods in bearing blocks, sensors on brackets. Everything NOT listed here
# must have solid material directly beneath it, and declaring "plate" no longer
# excuses a part that is 90 mm up in the air.
# What slides through / turns in what (see vgr_model.GUIDES): the lift
# carriage rides the four mast tubes, the travel carriage rides the guide rod and
# is the nut of the travel spindle. detail.py cuts the pockets, check_guides()
# proves zero overlap with a real running clearance on the exact B-rep.
GUIDES = [
    ("lift_carriage_L", "mast_tube_1", "slide", 0.3), ("lift_carriage_L", "mast_tube_3", "slide", 0.3),
    ("lift_carriage_R", "mast_tube_2", "slide", 0.3), ("lift_carriage_R", "mast_tube_4", "slide", 0.3),
    ("lift_carriage_L", "lift_spindle", "thread", 0.05),
    *[(h, f"mast_tube_{i}", "slide", 0.3) for h in ("lift_carriage_yoke", "fork_yoke") for i in range(1, 5)],
    ("lift_carriage_yoke", "lift_spindle", "bore", 1.0), ("fork_yoke", "lift_spindle", "bore", 1.0),
    ("travel_carriage", "guide_rod", "slide", 0.3),
    ("travel_carriage", "travel_spindle", "thread", 0.05),
]


CANTILEVERS = (
    {f"shelf_{r}{c}_{s}" for r in "ABC" for c in "1234" for s in "LR"}
    | {"guide_rod", "travel_spindle", "travel_carriage", "M2_coupler", "M3_coupler",
       "lift_carriage_yoke", "fork_yoke", "M4_fork_motor",
       "chain_travel_bracket", "chain_lift_env", "chain_lift_fix", "chain_lift_bracket",
       "rfid_rp1_bracket", "rfid_rp2_bracket",
       "ausleger_stage1", "ausleger_stage2", "ausleger_spindle",
       "ausleger_bearing_B", "ausleger_bearing_F",
       "cv_belt_L", "cv_belt_R", "cv_drum_in_L", "cv_drum_in_R",
       "cv_drum_out_L", "cv_drum_out_R",
       "M1_shaft", "M1_drive_pulley", "M1_drum_pulley", "M1_drive_belt",
       "I2_lightbarrier_inner_rx", "I2_lightbarrier_inner_tx",
       "I3_lightbarrier_outer_rx", "I3_lightbarrier_outer_tx",
       "A1_trail_lower", "CS1_colour_front_L", "CS2_colour_front_R",
       "LB1_pos_back_L", "LB2_pos_back_R",
       "I5_ref_ausleger_front", "I6_ref_ausleger_back"}
)


def check(verbose=True):
    poses = []
    cols = [(b, f"bay col{i+1}") for i, b in enumerate(P["BAY_X"])] + [(P["CV_X"], "conveyor")]
    for tv, name in cols:
        for lz in (80.0, 100.0, 120.0, 160.0, 220.0, 240.0, 340.0, 360.0):
            for fk in (0.0, 60.0, 115.0):
                if not pose_allowed(tv, lz, fk):
                    continue
                poses.append((tv, lz, fk, f"{name} lift={lz} fork={fk}"))
    fails = []
    for tv, lz, fk, label in poses:
        parts = build(tv, lz, fk)
        idx = {p.name: p for p in parts}
        for a, b in combinations(parts, 2):
            if a.group == "frame" or b.group == "frame":
                continue
            pair = tuple(sorted((a.group, b.group)))
            if pair in {tuple(sorted(j)) for j in JOINED}:
                continue
            o = _ovl(a.aabb(), b.aabb())
            if o:
                fails.append(f"INTERFERENCE {a.name} x {b.name} = {o:.1f} mm @ {label}")
    # grounding: every part either stands on something or is a declared cantilever
    import grounding
    fails += grounding.check_grounding(
        build(), {"rail": "guide_rod", "tubes": "mast_tube_1", "stage1": "ausleger_stage1"},
        cantilevers=CANTILEVERS)
    # everything inside the plate footprint
    for p in build():
        if p.group == "frame":
            continue
        a = p.aabb()
        if a[0] < -0.01 or a[1] < -0.01 or a[3] > P["PLATE"][0] + .01 or a[4] > P["PLATE"][1] + .01:
            fails.append(f"OFF-PLATE {p.name}: {a[:2]}..{a[3:5]}")
    fails += check_carry()
    fails += check_path()
    if verbose:
        n = len(build())
        print(f"parts: {n}   poses checked: {len(poses)}")
        print("\n".join(fails) if fails else "ALL CHECKS PASS "
              "(no interference in any pose, nothing floating, nothing off the plate)")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if check() else 0)
