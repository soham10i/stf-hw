"""
Sortierstrecke mit Farberkennung (ft 536633) - from-scratch model.

Module frame: origin front-left of its own plate, top face. +X right (belt run),
+Y back (ejection direction), +Z up, mm.

Complete I/O from 536634-Fabrik_Simulation_24V-Belegungsplan.pdf:

  I1 Impulstaster (belt travel)     Q1 Motor Foerderband (unidirectional)
  I2 Lichtschranke Eingang          Q2 Kompressor
  I3 Lichtschranke nach Farbsensor  Q3 Ventil erster Auswurf  (weiss)
  A4 Farbsensor, 0-10 VDC ANALOG    Q4 Ventil zweiter Auswurf (rot)
  I5/I6/I7 Lichtschranke            Q5 Ventil dritter Auswurf (blau)
           weiss / rot / blau

Two things the datasheets settle, and both change the design:

1. The Farbsensor (128599) is 30x15x15, needs 6-10 VDC, and outputs an ANALOGUE
   0-2 VDC in millivolts. It is expressly **not an RGB sensor** - an LED shines
   and a phototransistor measures how much comes back, so "similar colours can
   produce similar values", and the reading depends on ambient light AND on the
   distance to the object. SENSOR_GAP below is therefore a real design
   parameter, not a placement convenience.
2. The sensor gives 0-2 V but terminal 9 is specified 0-10 VDC: the 24 V adapter
   PCB scales it. Anything reading the raw sensor must not assume the terminal's
   range.

There is no position feedback on the belt either - I1 is a pulse switch, so the
controller counts pulses from the inlet barrier to know which ejector to fire.

Booklet, Erste Schritte: the workpieces START in the Lagerstellen here, and the
VGR collects them from these bays - which is what closes the factory loop.
"""
from variant import UP1
from dataclasses import dataclass
from itertools import combinations

S = dict(
    # 2x the first model's footprint (2026-09-27): longer belt, a real colour
    # hood, deep Lagerstellen that hold a chute of workpieces. The ft parts stay
    # at their precise component envelopes.
    PLATE=(1040.0, 640.0, 10.0),
    # BELT_Z 45: 15 mm below the oven belt, whose nose reaches over this belt's
    # back rail - the workpiece is carried across and drops onto it
    BELT=(16.0, 200.0, 824.0, 60.0), BELT_Z=45.0, FRAME_H=30.0, RAIL_T=10.0,
    DRUM_D=20.0,
    INLET_X=140.0, SENSOR_X=240.0, AFTER_X=340.0,
    HOOD_X=(180.0, 300.0), HOOD_H=140.0,
    SENSOR_GAP=25.0,                 # cup-to-workpiece-top distance; see docstring
    EJECT_X=(460.0, 600.0, 740.0), EJECT=(0.0, 90.0),   # pushes it through the bay mouth
    BAY=(100.0, 160.0, 8.0), BAY_Y=30.0, WALL=8.0, BAY_WALL_H=25.0,
    WP_D=45.0, WP_H=20.0,
    # the resting cookie: pushed through the mouth it slides back to 6.5 mm off
    # the back wall, across the bay's own light barrier (that is how the bay
    # reads "full")
    WP_DY=123.0,
    S_MOTOR=(75.0, 40.0, 30.0), SWITCH=(30.0, 15.0, 7.5), PHOTO=(15.0, 15.0, 7.5),
    COLOUR=(30.0, 15.0, 15.0), CYL=(15.0, 69.0, 20.0), VALVE=(40.0, 15.0, 33.0),
    COMPRESSOR=(66.0, 30.0, 30.0), PCB=(160.0, 100.0, 22.0),
)
from pipeline import BAY_START, FLAVOURS, BIN_OF       # noqa: E402
COLOURS = ("weiss", "rot", "blau")
BAY_FLAVOUR = dict(BAY_START)                          # bin -> flavour resting there
BAY_TAGS = ("I5", "I6", "I7")
EJECT_TAGS = ("Q3", "Q4", "Q5")

def rest_y():
    """Centre of a cookie resting in its Lagerstelle: WP_DY in from the bay MOUTH
    (the belt side), which leaves it 6.5 mm clear of the back wall and still
    across the bay's own light barrier near the mouth."""
    return S["BAY_Y"] + S["BAY"][1] - S["WP_DY"]


# Ejection runs -Y: ejectors stand BEHIND the belt, the Lagerstellen are in
# FRONT of it. Booklet Abb. 10 / photo p.39 with the inlet on the left: the
# ejector cylinders at the back, the bays at the front. (The first version had
# them swapped - a mirror image of the real machine.)
EJECT_AXIS = "-y"
FRAMES = ["world", "push0", "push1", "push2"]
PARENT = {"world": None, "push0": "world", "push1": "world", "push2": "world"}


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


def build(push=(0.0, 0.0, 0.0)):
    q = S; out = []; A = out.append
    bx, by, bl, bw = q["BELT"]; bz = q["BELT_Z"]; fh = q["FRAME_H"]; rt = q["RAIL_T"]

    A(Part("sorting_plate", "frame", "box", (0, 0, -q["PLATE"][2]), q["PLATE"], "slate", "table"))

    # ------------------------------------------------------- Foerderband
    for nm, ry in (("F", by), ("B", by + bw - rt)):
        for j, lx in enumerate((bx, bx + bl - rt)):
            A(Part(f"belt_leg_{nm}{j}", "belt", "box", (lx, ry, 0), (rt, rt, bz - fh),
                   "red", "plate"))
        A(Part(f"belt_rail_{nm}", "belt", "box", (bx, ry, bz - fh), (bl, rt, fh),
               "black", f"belt_leg_{nm}0"))
    A(Part("belt_web", "belt", "box", (bx, by + rt, bz - 4), (bl, bw - 2 * rt, 4),
           "darkgrey", "belt_rail_F", mech="belt",
           note="single web - nothing has to reach underneath here"))
    for nm, dx in (("in", bx + 15), ("out", bx + bl - 15)):
        A(Part(f"belt_drum_{nm}", "belt", "cyl", (dx, by, bz - q["DRUM_D"] / 2),
               ("y", bw, q["DRUM_D"]), "black", "belt_rail_F", mech="pulley"))
    A(Part("Q1_mount", "belt", "box", (bx + bl + 8, by, 0), (q["S_MOTOR"][0], q["S_MOTOR"][1], 15),
           "red", "plate"))
    A(Part("Q1_belt_motor", "belt", "box", (bx + bl + 8, by, 15),
           q["S_MOTOR"], "black", "Q1_mount", tag="Q1", mech="motor:belt",
           note="unidirectional - this belt only runs forward"))
    A(Part("I1_impulstaster", "belt", "box", (bx + bl - 20, by + bw, bz - fh),
           q["SWITCH"], "green", "belt_rail_B", tag="I1",
           note="Impulstaster: the ONLY travel feedback on this module. No "
                "encoder, so the controller counts pulses from the inlet barrier "
                "to know which ejector to fire."))

    # ------------------------------------------------- inlet + colour + after
    for nm, sx, tg, note in (
            ("I2_inlet", q["INLET_X"], "I2", "Lichtschranke Eingang"),
            ("I3_after_colour", q["AFTER_X"], "I3", "Lichtschranke nach Farbsensor")):
        A(Part(f"{nm}_rx", "sense", "box", (sx, by + rt - 7.5, bz), (15, 7.5, 15),
               "green", f"belt_rail_F", tag=tg, note="Fototransistor 36134; " + note))
        A(Part(f"{nm}_tx", "sense", "box", (sx, by + bw - rt, bz), (15, 7.5, 15),
               "amber", f"belt_rail_B", tag=tg, note="Lichtschranken-LED"))
    gap = q["SENSOR_GAP"]; ctop = bz + q["WP_H"]
    # the darkened lock (booklet p.36): a red hood over the belt, sensor inside
    hx0, hx1 = q["HOOD_X"]; hh = q["HOOD_H"]
    for nm, wy in (("F", by - 12), ("B", by + bw + 2)):
        A(Part(f"colour_hood_{nm}", "hood", "box", (hx0, wy, 0), (hx1 - hx0, 10, hh - 10),
               "ftred", "plate", note="side of the Farberkennung hood - keeps ambient light out"))
    A(Part("colour_hood_roof", "hood", "box", (hx0, by - 12, hh - 10), (hx1 - hx0, bw + 24, 10),
           "ftred", "colour_hood_F", note="roof of the darkened colour lock"))
    A(Part("colour_arm", "sense", "box", (q["SENSOR_X"] - 5, by + bw / 2 - 5, ctop + gap + 15),
           (10, 10, hh - 10 - (ctop + gap + 15)), "black", "colour_hood_roof"))
    A(Part("A4_colour_sensor", "sense", "box",
           (q["SENSOR_X"] - 15, by + bw / 2 - 7.5, ctop + gap), q["COLOUR"],
           "green", "colour_arm", tag="A4",
           note=f"Farbsensor 128599, {gap:.0f} mm above the workpiece top. NOT an "
                "RGB sensor - reflected intensity only, and the reading depends "
                "on this gap and on ambient light. 0-2 VDC at the sensor, "
                "scaled to the terminal's 0-10 VDC by the adapter PCB."))

    # --------------------------------------------------- ejectors + bays
    bw_, bd_, bt_ = q["BAY"]; wl = q["WALL"]
    for i, ex in enumerate(q["EJECT_X"]):
        col, tg, btag = COLOURS[i], EJECT_TAGS[i], BAY_TAGS[i]
        A(Part(f"{tg}_stand_{col}", "eject", "box", (ex - 15, by + bw + 5, 0),
               (30, 69, bz), "red", "plate"))
        A(Part(f"{tg}_cylinder_{col}", "eject", "box", (ex - 7.5, by + bw + 5, bz),
               q["CYL"], "grey", f"{tg}_stand_{col}", tag=tg, mech="pneumatic",
               note=f"Pneumatikzylinder, Ventil Auswurf {col}"))
        A(Part(f"pusher_{col}", f"push{i}", "box", (ex - 20, by + bw - 5 - push[i], bz),
               (40, 10, 26), "ftred", f"{tg}_cylinder_{col}", frame=f"push{i}",
               note="sweeps the workpiece across the belt into its Lagerstelle"))
        # Lagerstelle
        A(Part(f"bay_{col}_pedestal", "bay", "box", (ex - bw_ / 2 + 5, q["BAY_Y"] + 5, 0),
               (bw_ - 10, bd_ - 10, bz - bt_), "red", "plate"))
        A(Part(f"bay_{col}_floor", "bay", "box", (ex - bw_ / 2, q["BAY_Y"], bz - bt_),
               (bw_, bd_, bt_), "black", f"bay_{col}_pedestal",
               note="Lagerstelle - the workpieces start here and the VGR "
                    "collects them from here (booklet, Erste Schritte)"))
        A(Part(f"bay_{col}_wall_B", "bay", "box",
               (ex - bw_ / 2, q["BAY_Y"], bz), (bw_, wl, q["BAY_WALL_H"]),
               "black", f"bay_{col}_floor"))
        for sfx, wx in (("L", ex - bw_ / 2), ("R", ex + bw_ / 2 - wl)):
            A(Part(f"bay_{col}_wall_{sfx}", "bay", "box", (wx, q["BAY_Y"] + wl, bz),
                   (wl, bd_ - wl, q["BAY_WALL_H"]), "black", f"bay_{col}_floor"))
        A(Part(f"{btag}_bay_{col}_rx", "sense", "box",
               (ex - bw_ / 2 + wl, q["BAY_Y"] + 30, bz), (7.5, 15, 15), "green",
               f"bay_{col}_wall_L", tag=btag, note=f"Lichtschranke {col}"))
        A(Part(f"{btag}_bay_{col}_tx", "sense", "box",
               (ex + bw_ / 2 - wl - 7.5, q["BAY_Y"] + 30, bz), (7.5, 15, 15), "amber",
               f"bay_{col}_wall_R", tag=btag))
        # the workpiece resting in its bay
        A(Part(f"wp_{col}_body", "stock", "cyl", (ex, rest_y(), bz),
               ("z", q["WP_H"] - 4, q["WP_D"]), "white", f"bay_{col}_floor"))
        A(Part(f"wp_{col}_lid", "stock", "cyl", (ex, rest_y(), bz + q["WP_H"] - 4),
               ("z", 4, q["WP_D"]), FLAVOURS[BAY_FLAVOUR[col]]["colour"],
               f"wp_{col}_body",
               note=f"{BAY_FLAVOUR[col]} - this bin takes the flavour whose "
                    "reflected brightness the Farbsensor reads here"))

    # --------------------------------------------------------- pneumatics
    if not UP1:     # Upgrade 1: fed from the central air station (upgrade.py)
        A(Part("Q2_compressor", "control", "box", (900, 330, 0), q["COMPRESSOR"], "blue", "plate",
               tag="Q2", note="Kompressor (Membranpumpe), 24 V, 0.7 bar"))
    for i, col in enumerate(COLOURS):
        A(Part(f"valve_{col}", "control", "box", (880, 380 + i * 22, 0), q["VALVE"], "blue", "plate",
               note=f"3/2-Wege-Magnetventil for {EJECT_TAGS[i]} (Auswurf {col})"))
    A(Part("sorting_pcb", "control", "box", (40, 500, 0), q["PCB"], "green", "plate",
           note="24V adapter PCB: ST1 20-pol + ST2 14-pol + ST3 34-pol"))
    return out


JOINED = [("hood", "hood"), ("sense", "hood"), ("belt", "belt"), ("sense", "belt"), ("sense", "bay"), ("sense", "sense"),
          ("bay", "bay"), ("eject", "eject"), ("control", "control"),
          ("stock", "bay"), ("stock", "stock")]
for i in range(3):
    JOINED += [(f"push{i}", "eject"), (f"push{i}", f"push{i}")]


def _ovl(a, b, tol=0.05):
    d = [min(a[i + 3], b[i + 3]) - max(a[i], b[i]) for i in range(3)]
    return min(d) if min(d) > tol else 0.0


def pose_allowed(push):
    """Only one ejector fires at a time - they share one compressor and each
    sweeps the full belt width."""
    return sum(1 for p in push if p > 1.0) <= 1


CANTILEVERS = {
    "belt_rail_F", "belt_rail_B", "belt_web", "belt_drum_in", "belt_drum_out",
    "I1_impulstaster", "colour_arm", "A4_colour_sensor", "colour_hood_roof",
    "I2_inlet_rx", "I2_inlet_tx", "I3_after_colour_rx", "I3_after_colour_tx",
    "bay_weiss_wall_B", "bay_weiss_wall_L", "bay_weiss_wall_R",
    "bay_rot_wall_B", "bay_rot_wall_L", "bay_rot_wall_R",
    "bay_blau_wall_B", "bay_blau_wall_L", "bay_blau_wall_R",
    "I5_bay_weiss_rx", "I5_bay_weiss_tx", "I6_bay_rot_rx", "I6_bay_rot_tx",
    "I7_bay_blau_rx", "I7_bay_blau_tx",
    "pusher_weiss", "pusher_rot", "pusher_blau",
}


def check(verbose=True):
    fails = []
    vals = (S["EJECT"][0], 40.0, S["EJECT"][1])
    poses = [p for p in [(a, 0.0, 0.0) for a in vals] + [(0.0, a, 0.0) for a in vals]
             + [(0.0, 0.0, a) for a in vals] if pose_allowed(p)]
    ok = {tuple(sorted(j)) for j in JOINED}
    for pose in poses:
        parts = build(pose)
        for a, b in combinations(parts, 2):
            if a.group == "frame" or b.group == "frame":
                continue
            if tuple(sorted((a.group, b.group))) in ok:
                continue
            o = _ovl(a.local_aabb(), b.local_aabb())
            if o:
                fails.append(f"INTERFERENCE {a.name} x {b.name} = {o:.1f} mm @ push={pose}")
    import grounding
    fails += grounding.check_grounding(build(), cantilevers=CANTILEVERS)
    for p in build():
        if p.group == "frame":
            continue
        a = p.local_aabb()
        if a[0] < -0.01 or a[1] < -0.01 or a[3] > S["PLATE"][0] + .01 or a[4] > S["PLATE"][1] + .01:
            fails.append(f"OFF-PLATE {p.name}: {a[:2]}..{a[3:5]}")
    if verbose:
        print(f"parts: {len(build())}   poses checked: {len(poses)}")
        print("\n".join(fails) if fails else
              "ALL CHECKS PASS (no interference in any allowed pose, nothing floating, "
              "nothing off the plate)")
    return fails


def handover_points():
    """Where the VGR collects, one per Lagerstelle: bay centre, workpiece top."""
    return {COLOURS[i]: (ex, rest_y(), S["BELT_Z"] + S["WP_H"])
            for i, ex in enumerate(S["EJECT_X"])}


if __name__ == "__main__":
    import sys
    for k, v in handover_points().items():
        print(f"  Lagerstelle {k:6s} -> {v}")
    sys.exit(1 if check() else 0)
