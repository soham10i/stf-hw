"""
Multi-Bearbeitungsstation mit Brennofen (ft 536632) - rebuilt from scratch
against the booklet 536634-Fabrik_Simulation_24V.pdf, p.30 and Abbildung 9.

Module frame = FACTORY axes (the module is only translated onto the table, never
rotated): origin at the plate's corner, +X toward the VGR, +Y toward the sorting
line, +Z up, mm. Seen as in Abb. 9 the viewer stands on the +X side, so Abb. 9's
"left to right" is +Y here and its "back" is -X.

WHAT ABB. 9 SHOWS, AND WHAT THE OLD MODEL GOT WRONG
  1. Everything the workpiece touches lies on ONE flow line (x = X_LINE):
       Ofenschieber tray -> Sauger -> Drehtisch -> Auswerfer -> Foerderband -> out.
     The old model spread the Sauger portal across the whole plate (x 55..440),
     which put a rail over the VGR's hand-over and forced the oven onto a pedestal.
  2. The Sauger is a compact unit on the OVEN'S FRONT FACE: a short rail behind
     the flow line, the lowering cylinder cantilevered forward over it.
  3. Q12 "Ventil Senken" is a single-acting pneumatic cylinder: it has exactly
     TWO positions. The old model lowered it 82 mm at the tray and 166 mm at the
     turntable - a stroke a pneumatic cylinder cannot make. Here the tray top,
     the turntable disc top and the belt top are all the same working level
     Z_W, so one stroke serves both stations. CUP_TARGETS proves it.
  4. The Saege stands on a black column BEHIND the Drehtisch and hangs over its
     saw position; the Auswerfer (Q14) sits over the disc centre and pushes the
     workpiece radially off the disc onto the belt.
  5. The Foerderband runs +Y and its end is the sorting line's inlet: the
     workpiece leaves this module on a belt and is still on a belt in the next
     one (p.36: "sobald ein Werkstueck von der Bearbeitungsstation auf das
     Foerderband der Sortierstrecke uebergeben wird"). The old belt ran away
     from the sorting line, which is why the cookie had to vanish.

Complete I/O (Belegungsplan, p.5). NO ENCODERS anywhere - every axis runs to a
switch, so the controller can only ask "has it arrived", never "where is it".

  I1 Ref Drehkranz (Position Sauger)      Q1/Q2  M1 Drehkranz cw/ccw
  I2 Ref Drehkranz (Position Foerderband) Q3     M2 Foerderband vorwaerts
  I3 Lichtschranke Ende Foerderband       Q4     M3 Saege
  I4 Ref Drehkranz (Position Saege)       Q5/Q6  M4 Ofenschieber ein/aus
  I5 Ref Sauger (Position Drehkranz)      Q7/Q8  M5 Sauger zum Ofen / Drehkranz
  I6 Ref Ofenschieber innen               Q9     Leuchte Ofen
  I7 Ref Ofenschieber aussen              Q10    Kompressor
  I8 Ref Sauger (Position Brennofen)      Q11    Ventil Vakuum
  I9 Lichtschranke Brennofen              Q12    Ventil Senken
                                          Q13    Ventil Ofentuer
                                          Q14    Ventil Schieber (Auswerfer)

Documented process (p.30): the VGR lays the workpiece on the extended slider ->
I9 is interrupted -> door opens, slider retracts -> bake (Q9) -> door opens,
slider extends -> the station's OWN Sauger lifts it onto the Drehtisch -> the
Drehtisch dwells under the Saege -> turns to the belt -> the Auswerfer pushes it
onto the belt -> the belt carries it through I3 into the Sortierstrecke; passing
I3 sends the Drehtisch home and stops the belt after a delay.
"""
import math
from dataclasses import dataclass
from itertools import combinations

from variant import UP1

O = dict(
    # 2x the first rebuild's footprint (2026-09-27, user: "increase the size of
    # the oven 2x"): the structure and the spacing doubled; the ft parts and the
    # 45 mm workpiece did NOT - they are real parts, sized to the precise
    # component envelopes (components.py), so the complete setup can draw the
    # exact FreeCAD component in each one's place.
    PLATE=(660.0, 795.0, 10.0),
    X_LINE=460.0,           # the flow line: tray, Sauger, Drehtisch, belt
    Z_W=60.0,               # working level: tray top = disc top = belt top
    WP_D=45.0, WP_H=20.0,
    # Brennofen chamber (walls 10 mm, open at +X where the door is)
    CH_X=(60.0, 340.0), CH_Y=(10.0, 190.0), CH_Z=(40.0, 220.0), WALL=10.0, ROOF_T=12.0,
    MOUTH_TOP=160.0,
    DOOR_T=8.0, DOOR_H=110.0, DOOR_Z=(50.0, 170.0),      # door bottom: shut / open
    # Ofenschieber: tray x-min at innen (I6) / aussen (I7)
    TRAY=(50.0, 60.0, 10.0), TRAY_Y=100.0, SLIDER=(250.0, 435.0),
    RAIL_X=(70.0, 492.0),
    # Drehtisch: workpiece nest at radius R; stations as disc turn angles
    TT=(460.0, 400.0), TT_D=200.0, TT_BASE_D=150.0, TT_DISC_T=12.0, TT_R=65.0,
    TURN=(-180.0, 0.0),     # 0 = Sauger station, -90 = Saege, -180 = Foerderband
    # Sauger: its carriage travels +Y; stops at the tray and at the disc nest
    # (the turntable stop is also where it PARKS while the VGR loads the tray)
    SAUGER=(100.0, 335.0),  # I8 (oven) / I5 (Drehkranz)
    RAIL_Y=(0.0, 372.0), RAIL_Z=170.0,
    CUP_UP=130.0, CUP_D=30.0, CUP_H=12.0, LOWER=(0.0, 50.0),
    # Auswerfer (Q14) over the disc centre, pushing +Y onto the belt
    PUSH=(0.0, 80.0), PADDLE_Y=429.0,
    # Foerderband: web x 435..485, runs +Y to the plate edge
    # the belt runs on legs to BELT_MAIN, then a thin NOSE (rails z 50..60, a
    # 6 mm nose roller) reaches over the sorting belt's rail and ends above its
    # centre: a real right-angle transfer, the workpiece drops 15 mm onto it
    BELT_Y=(502.0, 792.0), BELT_MAIN=752.0, BELT_W=50.0, RAIL_T=8.0, DRUM_D=20.0, NOSE_D=7.0,
    # precise component envelopes (components.py / components.json)
    S_MOTOR=(40.0, 75.0, 30.0),      # S-Motor 24V + U-Getriebe, overall, lying along Y
    SWITCH=(30.0, 15.0, 7.5),
    # pneumatics sized to the precise components' OVERALL envelopes (nipples,
    # rod ends and leads included), so the drawn parts can never overlap
    CYL=(20.0, 15.0, 69.0), VALVE=(40.0, 15.0, 33.0),
    COMPRESSOR=(66.0, 30.0, 30.0), PCB=(100.0, 160.0, 22.0),
    # Upgrade 1: the members the sag check (upgrade.py) failed become 20 x 20
    # aluminium profile; the Sauger rail stays 15 mm but becomes aluminium
    PROFILE=20.0 if UP1 else None,
)
q = O
Z_W = O["Z_W"]
# Where the cup lands at each Sauger stop: the TOP FACE of the workpiece, which
# is Z_W + WP_H at both. Two equal numbers is what lets ONE pneumatic stroke
# serve both stations - the old model needed two different strokes.
CUP_TARGETS = {O["SAUGER"][0]: Z_W + O["WP_H"], O["SAUGER"][1]: Z_W + O["WP_H"]}
assert O["CUP_UP"] - O["LOWER"][1] == Z_W + O["WP_H"], "one stroke must reach both stations"
STATIONS = {"sauger": 0.0, "saege": -90.0, "band": -180.0}

FRAMES = ["world", "slider", "door", "turn", "sauger", "lower", "push"]
PARENT = {"world": None, "slider": "world", "door": "world", "turn": "world",
          "sauger": "world", "lower": "sauger", "push": "world"}
AXES = {"slider": "+x", "door": "+z", "turn": "rz", "sauger": "+y", "lower": "-z",
        "push": "+y"}


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


def _rot(x, y, deg):
    cx, cy = O["TT"]
    t = math.radians(deg); c, s = math.cos(t), math.sin(t)
    dx, dy = x - cx, y - cy
    return cx + dx * c - dy * s, cy + dx * s + dy * c


def world_aabb(part, turn_deg):
    a = part.local_aabb()
    if part.frame != "turn" or abs(turn_deg) < 1e-9:
        return a
    if part.kind == "cyl" and part.s[0] == "z":         # round: only its centre moves
        cx, cy = _rot(part.p[0], part.p[1], turn_deg)
        r = part.s[2] / 2
        return (cx - r, cy - r, a[2], cx + r, cy + r, a[5])
    xs, ys = [], []
    for x in (a[0], a[3]):
        for y in (a[1], a[4]):
            rx, ry = _rot(x, y, turn_deg)
            xs.append(rx); ys.append(ry)
    return (min(xs), min(ys), a[2], max(xs), max(ys), a[5])


def nest(turn_deg):
    """Centre of the workpiece nest on the disc at a given turn angle. At turn 0
    it is under the Sauger's turntable stop."""
    cx, cy = O["TT"]
    return _rot(cx, cy - O["TT_R"], turn_deg)


def build(slider=435.0, door=170.0, turn=0.0, sauger=335.0, lower=0.0, push=0.0):
    out = []; A = out.append
    XL = q["X_LINE"]
    cx0, cx1 = q["CH_X"]; cy0, cy1 = q["CH_Y"]; cz0, cz1 = q["CH_Z"]; wl = q["WALL"]
    SM = q["S_MOTOR"]

    A(Part("oven_plate", "frame", "box", (0, 0, -q["PLATE"][2]), q["PLATE"], "slate", "table"))

    # ------------------------------------------------------------ Brennofen
    A(Part("oven_pedestal", "oven", "box", (cx0, cy0, 0), (cx1 - cx0, cy1 - cy0, cz0 - 10),
           "black", "plate", note="lifts the chamber floor to the slider rail"))
    A(Part("oven_floor", "oven", "box", (cx0, cy0, cz0 - 10), (cx1 - cx0, cy1 - cy0, 10),
           "ftred", "oven_pedestal"))
    A(Part("oven_wall_back", "oven", "box", (cx0, cy0, cz0), (wl, cy1 - cy0, cz1 - cz0),
           "ftred", "oven_floor"))
    A(Part("oven_wall_L", "oven", "box", (cx0 + wl, cy0, cz0), (cx1 - cx0 - wl, wl, cz1 - cz0),
           "ftred", "oven_floor"))
    A(Part("oven_wall_R", "oven", "box", (cx0 + wl, cy1 - wl, cz0), (cx1 - cx0 - wl, wl, cz1 - cz0),
           "ftred", "oven_floor"))
    mt = q["MOUTH_TOP"]
    A(Part("oven_front_lintel", "oven", "box", (cx1 - wl, cy0 + wl, mt), (wl, cy1 - cy0 - 2 * wl, cz1 - mt),
           "ftred", "oven_wall_L", note="front wall above the mouth; the door slides in front of it"))
    A(Part("oven_roof", "oven", "box", (cx0, cy0, cz1), (cx1 - cx0, cy1 - cy0, q["ROOF_T"]),
           "black", "oven_wall_L", note="black slatted top (Abb. 9)"))
    A(Part("Q9_oven_lamp", "oven", "box", (cx1 - 40, cy1 - 40, cz1 + q["ROOF_T"]), (20, 20, 12),
           "amber", "oven_roof", tag="Q9",
           note="Leuchte Ofen - on the roof at the front corner, where it can be seen; "
                "lit while the oven bakes"))

    # door: guides stand on the plate either side of the mouth, a gantry on top
    dt = q["DOOR_T"]
    for nm, gy in (("L", cy0 + 2), ("R", cy1 - 10)):
        A(Part(f"door_guide_{nm}", "oven", "box", (cx1, gy, 0), (dt, 8, 300), "black", "plate",
               note="the Ofentuer slides between these two uprights"))
    PF = q["PROFILE"]
    gw, gh = (PF, PF) if PF else (dt + 8, 5)
    A(Part("door_gantry", "oven", "box", (cx1 + dt / 2 - gw / 2, cy0 + 2, 300), (gw, cy1 - cy0 - 4, gh),
           "alu" if PF else "black", "door_guide_L", mech=f"profile:{PF:.0f}" if PF else "",
           note="carries the door cylinder above the mouth"
                + (" - 20x20 aluminium profile (Upgrade 1: sag check)" if PF else "")))
    A(Part("Q13_door_cylinder", "oven", "box", (cx1 - 6, q["TRAY_Y"] - 7.5, 300 + gh), q["CYL"],
           "steel", "door_gantry", tag="Q13", mech="pneumatic",
           note="Pneumatikzylinder; Ventil Ofentuer pulls the door up"))
    A(Part("Q13_oven_door", "door", "box", (cx1, cy0 + 10, door), (dt, cy1 - cy0 - 20, q["DOOR_H"]),
           "ftred", "door_guide_L", frame="door", tag="Q13", mech="pneumatic",
           note="Ofentuer: shut at z=50 (sits on the slider rail), open at z=170"))
    A(Part("door_rod", "door", "cyl", (cx1 + 4, q["TRAY_Y"], door + q["DOOR_H"] - 5), ("z", 165 + gh, 8),
           "steel", "Q13_oven_door", frame="door", note="piston rod up into the door cylinder"))

    # ----------------------------------------------- Ofenschieber (I6 / I7)
    tw, td, th = q["TRAY"]; ty = q["TRAY_Y"]; r0, r1 = q["RAIL_X"]
    A(Part("slider_rail", "slider_fix", "box", (r0, ty - 5, cz0), (r1 - r0, 10, 10),
           "steel", "oven_floor", note="guide from the back of the chamber, through the door "
                                     "mouth, out to the flow line"))
    A(Part("slider_leg", "slider_fix", "box", (r1 - 15, ty - 5, 0), (15, 10, cz0), "black",
           "plate", note="carries the outer end of the rail"))
    A(Part("M4_slider_motor", "slider_fix", "box", (10, ty - SM[1] / 2, 0), SM, "black", "plate",
           tag="Q5/Q6", mech="motor:slider",
           note="S-Motor 24V + U-Getriebe behind the chamber; runs to a switch, no encoder"))
    A(Part("I6_ref_slider_in", "slider_fix", "box", (240, ty + 12, cz0), q["SWITCH"], "green",
           "oven_floor", tag="I6", note="Ofenschieber innen - under the retracted tray"))
    A(Part("I7_ref_slider_out", "slider_fix", "box", (440, ty + 5, cz0), q["SWITCH"], "green",
           "slider_rail", tag="I7", note="Ofenschieber aussen - under the extended tray"))
    A(Part("ofenschieber_tray", "slider", "box", (slider, ty - td / 2, cz0 + 10), (tw, td, th),
           "ftred", "slider_rail", frame="slider",
           note="carries the workpiece into the chamber and back; the VGR loads it "
                "at the extended stop, on the flow line"))

    # I9 across the extended tray, at workpiece height
    for nm, py, col in (("rx", ty - 79, "green"), ("tx", ty + 72, "amber")):
        A(Part(f"I9_post_{nm}", "oven", "box", (XL - 8, py, 0), (15, 7.5, Z_W + 2),
               "black", "plate"))
        A(Part(f"I9_lightbarrier_{nm}", "oven", "box", (XL - 8, py, Z_W + 2), (15, 7.5, 15),
               col, f"I9_post_{nm}", tag="I9",
               note="Lichtschranke Brennofen - registers the workpiece being LAID on the "
                    "tray (p.34), not its presence" if nm == "rx" else "Lichtschranken-LED"))

    # ------------------------------------------------------------- Sauger
    ry0, ry1 = q["RAIL_Y"]; rz = q["RAIL_Z"]
    A(Part("sauger_column", "portal", "box", (360, ry0, 0), (15, 15, rz + 15), "ftred", "plate",
           note="the Sauger unit stands on the oven's front face (Abb. 9)"))
    A(Part("sauger_post_far", "portal", "box", (345, 340, 0), (15, 15, rz + 15), "ftred", "plate",
           note="second upright: the rail is 372 mm long"))
    A(Part("sauger_rail", "portal", "box", (360, ry0, rz), (15, ry1 - ry0, 15), "alu" if PF else "black",
           "sauger_column", mech="profile:15" if PF else "",
           note="behind the flow line, so the VGR can come down on the tray"
                + (" - aluminium 15x15 profile (Upgrade 1: sag check)" if PF else "")))
    A(Part("M5_sauger_motor", "portal", "box", (240, 30, cz1 + q["ROOF_T"]), SM,
           "black", "oven_roof", tag="Q7/Q8", mech="motor:sauger",
           note="Motor Sauger zum Ofen / zum Drehkranz - on the oven roof, clear of the "
                "VGR's approach to the tray; it pulls the carriage along the rail"))
    for nm, sy, tg in (("oven", q["SAUGER"][0], "I8"), ("turntable", q["SAUGER"][1], "I5")):
        A(Part(f"{tg}_ref_sauger_{nm}", "portal", "box", (360, sy - 15, rz + 15), (15, 30, 7.5),
               "green", "sauger_rail", tag=tg, note="on top of the rail, struck by the carriage"))
    A(Part("sauger_carriage", "sauger", "box", (361, sauger - 15, 150), (XL + 20 - 361, 30, 20),
           "ftred", "sauger_rail", frame="sauger",
           note="runs under the rail; its arm reaches forward over the flow line"))
    cu = q["CUP_UP"]; ch = q["CUP_H"]
    A(Part("Q12_lower_cylinder", "sauger", "cyl", (XL, sauger, cu + ch), ("z", 58, 20), "steel",
           "sauger_carriage", frame="sauger", tag="Q12", mech="pneumatic",
           note="Pneumatikzylinder, Ventil Senken: TWO positions only - up, or 50 mm down"))
    A(Part("Q12_piston_rod", "lower", "cyl", (XL, sauger, cu + ch - lower), ("z", 50, 8), "steel",
           "Q12_lower_cylinder", frame="lower"))
    A(Part("Q11_suction_cup", "tool", "cyl", (XL, sauger, cu - lower), ("z", ch, q["CUP_D"]),
           "black", "Q12_piston_rod", frame="lower", tag="Q11",
           note="Vakuumsauger, Ventil Vakuum; underside at 130 up / 80 down = workpiece top"))

    # ---------------------------------------------------------- Drehtisch
    tx, tyc = q["TT"]; dz0 = Z_W - q["TT_DISC_T"]
    A(Part("drehtisch_base", "turn_fix", "cyl", (tx, tyc, 0), ("z", dz0, q["TT_BASE_D"]), "black",
           "plate", note="Drehkranz bearing + gear"))
    A(Part("drehtisch_disc", "turn", "cyl", (tx, tyc, dz0), ("z", q["TT_DISC_T"], q["TT_D"]),
           "ftred", "drehtisch_base", frame="turn", mech="spin:turn",
           note="three stops: Sauger (0), Saege (-90), Foerderband (-180)"))
    nx, ny = nest(0.0)
    A(Part("drehtisch_nest", "turn", "cyl", (nx, ny, Z_W - 0.5), ("z", 0.5, q["WP_D"] + 6),
           "black", "drehtisch_disc", frame="turn", note="the workpiece seat on the disc"))
    A(Part("M1_turntable_motor", "turn_fix", "box", (575, tyc - SM[1] / 2, 0), SM, "black", "plate",
           tag="Q1/Q2", mech="motor:turn", note="S-Motor 24V; drives the Drehkranz via a worm; no encoder"))
    for tg, ang, nm, sz in (("I1", -60.0, "sauger", (30, 15, 7.5)),
                            ("I4", 180.0, "saege", (15, 30, 7.5)),
                            ("I2", 45.0, "band", (30, 15, 7.5))):
        a = math.radians(ang); rr = 110.0
        A(Part(f"{tg}_ref_turn_{nm}", "turn_fix", "box",
               (tx + rr * math.cos(a) - sz[0] / 2, tyc + rr * math.sin(a) - sz[1] / 2, 0), sz,
               "green", "plate", tag=tg,
               note=f"Referenzschalter Drehkranz, Position {nm} - a cam under the rim strikes it"))

    # --------------------------------------------------------------- Saege
    sx, sy = nest(STATIONS["saege"])
    A(Part("saw_column", "saw", "box", (290, 355, 0), (20, 68, 200), "black", "plate",
           note="black tower behind the Drehtisch (Abb. 9)"))
    A(Part("saw_arm", "saw", "box", (310, sy - 12, 190), (sx + 15 - 310, 25, 10), "black", "saw_column",
           note="passes the sag check as it is (0.035 mm), so Upgrade 1 leaves it alone"
                if PF else ""))
    A(Part("M3_saw_motor", "saw", "box", (sx - 45, sy - 20, 200), (SM[1], SM[0], SM[2]), "black",
           "saw_arm", tag="Q4", mech="motor:saw", note="S-Motor on the arm, drives the spindle"))
    A(Part("saw_spindle", "saw", "cyl", (sx, sy, 90), ("z", 100, 8), "steel", "saw_arm",
           note="vertical spindle down through the arm to the cutter"))
    A(Part("saw_blade", "saw", "cyl", (sx, sy, 86), ("z", 4, 30), "steel", "saw_spindle",
           mech="spin:saw", note="cutter disc, 6 mm above the workpiece top - a simulated process"))

    # ------------------------------------------------ Auswerfer (Q14)
    py0 = q["PADDLE_Y"]
    bw_, bh_ = (PF, PF) if PF else (10, 8)
    A(Part("pusher_beam", "push_fix", "box", (310, 360, 104), (XL + 8 - 310, bw_, bh_),
           "alu" if PF else "black", "saw_column", mech=f"profile:{PF:.0f}" if PF else "",
           note="carries the Auswerfer from the saw column out over the disc centre"
                + (" - 20x20 aluminium profile (Upgrade 1: sag check)" if PF else "")))
    A(Part("Q14_pusher_cylinder", "push_fix", "box", (XL - 7.5, py0 - 2 - 69, 84), (15, 69, 20),
           "steel", "pusher_beam", tag="Q14", mech="pneumatic",
           note="Pneumatikzylinder, Ventil Schieber - fixed over the disc centre"))
    A(Part("pusher_rod", "push", "cyl", (XL, py0 - 28 + push, 91.5), ("y", 30, 8), "steel",
           "Q14_pusher_cylinder", frame="push"))
    A(Part("pusher_paddle", "push", "box", (XL - 10, py0 + push, Z_W + 4), (20, 6, 34),
           "ftred", "pusher_rod", frame="push",
           note="retracted inside the nest's inner radius, so the disc turns freely"))

    # --------------------------------------------------------- Foerderband
    b0, b1 = q["BELT_Y"]; bm = q["BELT_MAIN"]; bw = q["BELT_W"]; rt = q["RAIL_T"]; bx0 = XL - bw / 2
    for nm, rx in (("L", bx0 - rt), ("R", bx0 + bw)):
        for j, ly in enumerate((b0, bm - 8)):
            A(Part(f"belt_leg_{nm}{j}", "belt", "box", (rx, ly, 0), (rt, 8, 30), "black", "plate"))
        A(Part(f"belt_rail_{nm}", "belt", "box", (rx, b0, 30), (rt, bm - b0, Z_W - 30),
               "black", f"belt_leg_{nm}0"))
        A(Part(f"belt_nose_{nm}", "belt", "box", (rx, bm, Z_W - 10), (rt, b1 - bm, 10),
               "black", f"belt_rail_{nm}", note="thin nose: passes over the sorting belt's rail"))
    A(Part("belt_web", "belt", "box", (bx0, b0, Z_W - 4), (bw, b1 - b0, 4), "darkgrey",
           "belt_rail_L", mech="belt"))
    A(Part("belt_drum_in", "belt", "cyl", (bx0, b0 + 10, Z_W - 4 - q["DRUM_D"] / 2),
           ("x", bw, q["DRUM_D"]), "black", "belt_rail_L", mech="pulley"))
    A(Part("belt_drum_out", "belt", "cyl", (bx0, bm - 10, Z_W - 4 - q["DRUM_D"] / 2),
           ("x", bw, q["DRUM_D"]), "black", "belt_rail_L", mech="pulley",
           note="the driven drum; the belt runs on over the nose roller"))
    A(Part("belt_nose_roller", "belt", "cyl", (bx0, b1 - q["NOSE_D"] / 2, Z_W - 4 - q["NOSE_D"] / 2),
           ("x", bw, q["NOSE_D"]), "steel", "belt_nose_L", mech="pulley",
           note="7 mm knife-edge roller over the sorting belt: the workpiece drops off here"))
    A(Part("M2_mount", "belt", "box", (bx0 + bw + rt, bm - SM[1], 0), (SM[0], SM[1], 20), "black", "plate"))
    A(Part("M2_belt_motor", "belt", "box", (bx0 + bw + rt, bm - SM[1], 20), SM, "black",
           "M2_mount", tag="Q3", mech="motor:belt",
           note="S-Motor 24V, forward only - drives the out drum"))
    for nm, rx, col in (("rx", bx0 - rt + 0.5, "green"), ("tx", bx0 + bw, "amber")):
        A(Part(f"I3_lightbarrier_{nm}", "belt", "box", (rx, bm - 25, Z_W), (7.5, 15, 15), col,
               f"belt_rail_{'L' if nm == 'rx' else 'R'}", tag="I3",
               note="Lichtschranke Ende Foerderband - hands off to the Sortierstrecke"
               if nm == "rx" else "Lichtschranken-LED"))

    # ---------------------------------------------------------- pneumatics
    if not UP1:     # Upgrade 1: one central air station feeds every module (upgrade.py)
        A(Part("Q10_compressor", "control", "box", (580, 20, 0), q["COMPRESSOR"], "blue", "plate",
               tag="Q10", note="Kompressor (Membranpumpe), 24 V, 0.7 bar"))
    for i, (tg, what) in enumerate((("Q11", "Vakuum"), ("Q12", "Senken"),
                                    ("Q13", "Ofentuer"), ("Q14", "Schieber"))):
        A(Part(f"V{i + 1}_valve_{what.lower()}", "control", "box", (600, 70 + i * 22, 0),
               q["VALVE"], "blue", "plate",
               note=f"3/2-Wege-Magnetventil for {tg} ({what})"))
    for k, vy in enumerate((70.0, 92.0)):
        A(Part(f"vacuum_cylinder_{'ab'[k]}", "control", "box", (520, vy, 0), (69, 15, 20), "steel",
               "plate", mech="pneumatic",
               note="two coupled Pneumatikzylinder: driven apart, they make the vacuum for Q11 (p.10)"))
    A(Part("oven_pcb", "control", "box", (540, 540, 0), q["PCB"], "green", "plate",
           note="24V adapter PCB: ST1 20-pol + ST2 20-pol + ST3 34-pol, relays R1-R8, valve terminals V1-V4"))
    return out


def _wp(name, x, y, z, frame, support):
    return [Part(f"{name}_body", "load", "cyl", (x, y, z), ("z", O["WP_H"] - 4, O["WP_D"]),
                 "white", support, frame=frame),
            Part(f"{name}_lid", "load", "cyl", (x, y, z + O["WP_H"] - 4), ("z", 4, O["WP_D"]),
                 "colour", f"{name}_body", frame=frame)]


def tray_load(slider):
    """The workpiece on the Ofenschieber. It may touch the tray and nothing else,
    which is what makes the door interlock provable."""
    return _wp("wp_tray", slider + O["TRAY"][0] / 2, O["TRAY_Y"], Z_W, "slider",
               "ofenschieber_tray")


def cup_load(sauger, lower):
    return _wp("wp_cup", O["X_LINE"], sauger, O["CUP_UP"] - lower - O["WP_H"], "lower",
               "Q11_suction_cup")


def disc_load(turn):
    x, y = nest(turn)
    return _wp("wp_disc", x, y, Z_W, "world", "drehtisch_disc")


def belt_load(y):
    return _wp("wp_belt", O["X_LINE"], y, Z_W, "world", "belt_web")


JOINED = [("oven", "oven"), ("oven", "door"), ("slider", "slider_fix"),
          ("slider_fix", "oven"), ("slider", "oven"), ("turn", "turn_fix"),
          ("turn_fix", "turn_fix"), ("saw", "saw"), ("belt", "belt"),
          ("portal", "portal"), ("sauger", "portal"), ("portal", "oven"), ("lower", "sauger"),
          ("tool", "lower"), ("tool", "sauger"), ("control", "control"),
          ("push_fix", "saw"), ("push_fix", "push_fix"), ("push", "push_fix"),
          ("push", "push"), ("door", "door"), ("sauger", "sauger"), ("turn", "turn"),
          ("load", "slider"), ("load", "load"), ("load", "tool"), ("load", "turn"),
          ("load", "belt")]


def _ovl(a, b, tol=0.05):
    d = [min(a[i + 3], b[i + 3]) - max(a[i], b[i]) for i in range(3)]
    return min(d) if min(d) > tol else 0.0


def door_open_enough(door):
    """The tray top is at Z_W; the door's underside must be above it."""
    return door >= Z_W


def at_station(turn, name, tol=0.5):
    return abs(turn - STATIONS[name]) < tol


def pose_allowed(slider, door, turn, sauger, lower, push=0.0):
    """Three interlocks, each one geometry rather than a house rule.

    1. The Ofenschieber never travels with the Ofentuer shut - the shut door
       physically blocks the mouth the tray passes through.
    2. Q12 lowers only AT a Sauger stop, and only by its one stroke; the cup then
       sits exactly on the workpiece top, never below it.
    3. The Auswerfer fires only with the disc at the belt station, and the disc
       turns only with the Auswerfer home - otherwise the paddle and the
       workpiece on the disc collide.
    """
    if not door_open_enough(door) and slider > O["SLIDER"][0] + 1.0:
        return False
    if lower > 0.0:
        at = [sy for sy in CUP_TARGETS if abs(sauger - sy) < 1.0]
        if not at or O["CUP_UP"] - lower < CUP_TARGETS[at[0]] - 0.5:
            return False
    if push > 1.0 and not at_station(turn, "band"):
        return False
    return True


# Parts genuinely BOLTED to a vertical face - the way ft brackets and sensor
# mounts really work. Everything else must have solid material beneath it.
CANTILEVERS = {
    "oven_wall_back", "oven_wall_L", "oven_wall_R", "Q9_oven_lamp", "Q13_oven_door",
    "door_gantry", "door_rod", "oven_front_lintel", "slider_rail", "I7_ref_slider_out", "ofenschieber_tray",
    "sauger_rail", "sauger_carriage", "Q12_lower_cylinder", "Q12_piston_rod",
    "Q11_suction_cup", "drehtisch_disc", "saw_arm", "saw_spindle", "saw_blade",
    "pusher_beam", "Q14_pusher_cylinder", "pusher_rod", "pusher_paddle",
    "belt_rail_L", "belt_rail_R", "belt_web", "belt_drum_in", "belt_drum_out",
    "belt_nose_L", "belt_nose_R", "belt_nose_roller",
    "I3_lightbarrier_rx", "I3_lightbarrier_tx", "drehtisch_nest",
}


def _circle(p, turn):
    """(cx, cy, r) for a vertical cylinder, in the world at this turn angle."""
    if p.kind == "cyl" and p.s[0] == "z":
        x, y = (p.p[0], p.p[1]) if p.frame != "turn" else _rot(p.p[0], p.p[1], turn)
        return (x, y, p.s[2] / 2)
    return None


def _hit(a, b, turn_a, turn_b, tol=0.05):
    """Penetration depth between two parts. A vertical cylinder is tested as the
    CIRCLE it is - its square bounding box would put the round Drehtisch into
    the oven wall it clears by 40 mm."""
    A, B = world_aabb(a, turn_a), world_aabb(b, turn_b)
    o = _ovl(A, B, tol)
    if not o:
        return 0.0
    ca, cb = _circle(a, turn_a), _circle(b, turn_b)
    if ca is None and cb is None:
        return o
    dz = min(A[5], B[5]) - max(A[2], B[2])
    if ca and cb:
        pen = ca[2] + cb[2] - math.hypot(ca[0] - cb[0], ca[1] - cb[1])
    else:
        c, box = (ca, B) if ca else (cb, A)
        nx = min(max(c[0], box[0]), box[3]); ny = min(max(c[1], box[1]), box[4])
        pen = c[2] - math.hypot(c[0] - nx, c[1] - ny)
    pen = min(pen, dz)
    return pen if pen > tol else 0.0


def _pairs(parts, turn, ok, label, fails):
    for a, b in combinations(parts, 2):
        if a.group == "frame" or b.group == "frame":
            continue
        if tuple(sorted((a.group, b.group))) in ok:
            continue
        o = _hit(a, b, turn, turn)
        if o:
            fails.append(f"INTERFERENCE {a.name} x {b.name} = {o:.1f} mm @ {label}")


def check(verbose=True):
    fails = []
    ok = {tuple(sorted(j)) for j in JOINED}
    S0, S1 = O["SLIDER"]; D0, D1 = O["DOOR_Z"]; L1 = O["LOWER"][1]; P1 = O["PUSH"][1]
    poses = []
    for sl in (S0, (S0 + S1) / 2, S1):
        for dr in (D0, D1):
            for tn in (0.0, -45.0, -90.0, -135.0, -180.0):
                for sg in (O["SAUGER"][0], sum(O["SAUGER"]) / 2, O["SAUGER"][1]):
                    for lo in (0.0, 25.0, L1):
                        for pu in (0.0, P1 / 2, P1):
                            if pose_allowed(sl, dr, tn, sg, lo, pu):
                                poses.append((sl, dr, tn, sg, lo, pu))
    for pose in poses:
        parts = build(*pose) + tray_load(pose[0])
        _pairs(parts, pose[2], ok, "slider=%g door=%g turn=%g sauger=%g lower=%g push=%g" % pose,
               fails)
    # the workpiece's own journey, each leg swept against the whole station
    S0y, S1y = O["SAUGER"]
    legs = []
    for sg in [S0y + (S1y - S0y) * i / 10 for i in range(11)]:          # carried by the Sauger
        legs.append((f"carried sauger={sg:.0f}", build(S1, D1, 0.0, sg, 0.0), 0.0,
                     cup_load(sg, 0.0)))
    for lo in (0.0, 25.0, L1):
        legs.append((f"cup lowering at tray {lo}", build(S1, D1, 0.0, S0y, lo), 0.0, cup_load(S0y, lo)))
        legs.append((f"cup lowering at disc {lo}", build(S1, D1, 0.0, S1y, lo), 0.0, cup_load(S1y, lo)))
    for tn in [-i * 10.0 for i in range(19)]:                          # riding the disc
        legs.append((f"on disc turn={tn:g}", build(S1, D1, tn, S1y, 0.0), tn, disc_load(tn)))
    bx, by = nest(STATIONS["band"])
    for pu in [P1 * i / 6 for i in range(7)]:                          # pushed onto the belt
        wy = by + pu
        legs.append((f"pushed push={pu:.0f}", build(S1, D1, -180.0, S1y, 0.0, pu), -180.0,
                     belt_load(wy)))
    for wy in range(int(by + P1), int(O["BELT_Y"][1]), 10):            # riding the belt
        legs.append((f"on belt y={wy}", build(S1, D1, -180.0, S1y, 0.0), -180.0, belt_load(wy)))
    for label, parts, tn, load in legs:
        for w in load:
            for p in parts:
                if p.group == "frame":
                    continue
                if tuple(sorted((w.group, p.group))) in ok:
                    continue
                o = _hit(w, p, 0.0, tn)
                if o:
                    fails.append(f"WORKPIECE {w.name} x {p.name} = {o:.1f} mm @ {label}")
    import grounding
    fails += grounding.check_grounding(build(), cantilevers=CANTILEVERS)
    for p in build():
        if p.group == "frame":
            continue
        a = p.local_aabb()
        if a[0] < -0.01 or a[1] < -0.01 or a[3] > O["PLATE"][0] + .01 or a[4] > O["PLATE"][1] + .01:
            fails.append(f"OFF-PLATE {p.name}: {a[:2]}..{a[3:5]}")
    if verbose:
        print(f"parts: {len(build())}   poses checked: {len(poses)}   workpiece legs: {len(legs)}")
        print("\n".join(fails[:60]) if fails else
              "ALL CHECKS PASS (no interference in any allowed pose, the workpiece clears "
              "the station on every leg of its journey, nothing floating, nothing off the plate)")
    return fails


def handover_point():
    """Where the VGR meets this module: the extended tray's centre, top face."""
    return (O["SLIDER"][1] + O["TRAY"][0] / 2, O["TRAY_Y"], Z_W)


def flow():
    """The workpiece's path through the station, for the viewer. Every number
    comes from the table above."""
    return {
        "x_line": O["X_LINE"], "z_w": Z_W, "wp_h": O["WP_H"], "wp_d": O["WP_D"],
        "tray_y": O["TRAY_Y"], "tray_w": O["TRAY"][0],
        "cup_up": O["CUP_UP"], "stroke": O["LOWER"][1],
        "tt": list(O["TT"]), "tt_r": O["TT_R"], "stations": STATIONS,
        "push": O["PUSH"][1], "belt": list(O["BELT_Y"]),
        "exit": [O["X_LINE"], O["BELT_Y"][1], Z_W], "belt_main": O["BELT_MAIN"],
    }


if __name__ == "__main__":
    import sys
    print("hand-over (module frame):", handover_point())
    sys.exit(1 if check() else 0)
