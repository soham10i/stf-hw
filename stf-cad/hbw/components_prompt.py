"""
Generate the FreeCAD build prompt for an AI assistant (Gemini in FreeCAD) from
components.py - the same table the verified CAD is built from, so every number
in the prompt is one the reference model already passed its checks with.

    python3 components_prompt.py
    -> ~/workspace/stf-factory/cad/components/FREECAD_AI_PROMPTS.md
"""
import os

import components as C

OUT = os.path.expanduser("~/workspace/stf-factory/cad/components/FREECAD_AI_PROMPTS.md")
SRC = {"datasheet": "DATASHEET", "photo": "photo-estimate", "ft-std": "ft-standard",
       "assumed": "ASSUMED-measure"}

COMMON = """You are writing ONE FreeCAD 1.x Python macro (run it from the Python console or as
a .FCMacro). Hard rules:

1. Units are millimetres. Work to 0.01 mm: type every dimension exactly as given,
   never round, never "approximately".
2. Create a Spreadsheet object named `Params` and put EVERY dimension below into it
   with the given alias; drive all geometry from `Params` expressions (or from Python
   variables read from it) so a caliper measurement can later be typed in and the
   model recomputes.
3. Build with the Part workbench (Part.makeBox / makeCylinder / cut / fuse / makeChamfer
   / extrude of a Part.makePolygon face). Keep each named sub-part a SEPARATE
   Part::Feature inside one App::Part container - do not fuse different sub-parts.
4. Coordinate frame: origin at the housing's minimum corner; +X = length, +Y = depth,
   +Z = up. The face at y = 0 is the FRONT.
5. Colour each Part::Feature with ViewObject.ShapeColor as given (RGB 0..1).
6. Finish with the SELF-CHECK below: compute each housing's exact bounding box with
   shape.optimalBoundingBox(True, False), print it, and raise an error if any value
   differs from the datasheet by more than 0.01 mm. Then call
   Gui.SendMsgToActiveView("ViewFit") and Gui.activeDocument().activeView().viewIsometric().
7. Values tagged ASSUMED-measure or photo-estimate are NOT from the datasheet: keep
   them as Params entries and add a comment "# verify with calipers".
"""


def rgb(hexcol):
    h = hexcol.lstrip("#")
    return "({:.3f}, {:.3f}, {:.3f})".format(*(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def params_table(cid):
    rows = ["| alias | meaning | value (mm) | source |", "|---|---|---:|---|"]
    for d in C.COMPONENTS[cid]["dims"]:
        note = f" — {d['note']}" if d["note"] else ""
        rows.append(f"| `{d['key']}` | {d['label']}{note} | {d['value']:.2f} | {SRC[d['source']]} |")
    return "\n".join(rows)


def facts(cid):
    return "\n".join(f"- {a}: {b}" for a, b, _ in C.COMPONENTS[cid]["facts"])


def encoder_motor():
    g = lambda k: C.get("encoder_motor", k)
    L, W, H = g("L"), g("W"), g("H")
    af = g("shaft_d") - 2 * g("flat")
    return f"""
**Sub-part `housing`** (colour {rgb('#d8261c')}, ft red ABS):
1. Box {L:.2f} × {W:.2f} × {H:.2f} at the origin. Chamfer ALL 12 edges by `edge` = {g('edge'):.2f}.
2. Dovetail grooves (ft "Nut"), each running the FULL length in X (extrude from x = −1 to
   x = {L + 1:.2f}). Profile in the YZ plane, a trapezoid: `g_mouth` = {g('g_mouth'):.2f} wide at the
   surface, widening to `g_inner` = {g('g_inner'):.2f} at depth `g_depth` = {g('g_depth'):.2f}.
   - top face (z = {H:.2f}): two grooves centred at y = {g('groove_top_y'):.2f} and y = {W - g('groove_top_y'):.2f}
   - front face (y = 0) and back face (y = {W:.2f}): one groove each centred at z = {g('groove_side_z'):.2f}
     (make the top-centre groove at y = {W / 2:.2f} and rotate copies ±90° about the X axis
     through (y = {W / 2:.2f}, z = {H / 2:.2f}))
   - bottom face: one groove centred at y = {W / 2:.2f} (the same copy rotated 180°)
   Cut all of them from the box.
3. Far end face (x = {L:.2f}): two rectangular socket recesses, each `slot_w` {g('slot_w'):.2f} (Y) ×
   `slot_h` {g('slot_h'):.2f} (Z), `slot_depth` {g('slot_depth'):.2f} deep (−X), centred at z = {H / 2:.2f} and
   y = {W / 2 - g('sock_pitch') / 2:.2f} / {W / 2 + g('sock_pitch') / 2:.2f}. In the centre of each recess drill a
   Ø{g('sock_d'):.2f} hole `sock_depth` {g('sock_depth'):.2f} deep in −X (the ft 2.5 mm plug sockets).
4. Encoder header slot on the same end face: `hdr_w` {g('hdr_w'):.2f} (Y) × `hdr_h` {g('hdr_h'):.2f} (Z),
   4.00 deep, centred at y = {W / 2:.2f}, bottom edge at z = 3.00.

**Sub-part `output_shaft`** (colour {rgb('#b9bec4')}, steel):
5. Cylinder Ø{g('shaft_d'):.2f} on the axis y = {W / 2:.2f}, z = {H / 2:.2f}, from x = +1.00 (1 mm inside the
   housing) to x = −{g('shaft_l'):.2f} (protrudes {g('shaft_l'):.2f} from the x = 0 face).
6. Two flats, `flat` = {g('flat'):.2f} deep each, on the +Z and −Z sides: remove everything with
   |z − {H / 2:.2f}| > {g('shaft_d') / 2 - g('flat'):.2f}. Across-flats must be exactly {af:.2f}.

**Sub-part `bearing_collar`** (colour {rgb('#2a2b2e')}): cylinder Ø{g('collar_d'):.2f}, `collar_h` {g('collar_h'):.2f} long,
on the same axis, from x = 0 to x = −{g('collar_h'):.2f}.

**Sub-part `encoder_header_pins`** (colour {rgb('#c9a24a')}, brass): four 0.64 × 0.64 mm square
pins, 1.50 long in X, at 2.54 mm pitch along Y inside the header slot.

**SELF-CHECK values:** housing {L:.2f} × {W:.2f} × {H:.2f}; shaft across-flats {af:.2f};
shaft diameter {g('shaft_d'):.2f}; shaft protrusion {g('shaft_l'):.2f} (shaft bbox XMin = −{g('shaft_l'):.2f}).
"""


def mini_switch():
    g = lambda k: C.get("mini_switch", k)
    L, W, H = g("L"), g("W"), g("H")
    z0 = g("contact_z")
    return f"""
**Sub-part `housing`** (colour {rgb('#2a2b2e')}, dark ABS):
1. Box {L:.2f} (X) × {W:.2f} (Y, thickness) × {H:.2f} (Z, height). Chamfer all edges by `edge` = {g('edge'):.2f}.
2. Three contact sockets on the FRONT face (y = 0): Ø{g('contact_d'):.2f} blind holes,
   `contact_depth` {g('contact_depth'):.2f} deep in +Y, all at x = {g('contact_x'):.2f}, at
   z = {z0:.2f} (contact 1), z = {z0 + 4:.2f} (contact 2), z = {z0 + 8:.2f} (contact 3).
   Wiring: contacts 1–3 = normally open, 1–2 = normally closed.

**Sub-part `actuator`** (colour {rgb('#e0312a')}, red): box `btn_l` {g('btn_l'):.2f} (X) × `btn_w` {g('btn_w'):.2f} (Y)
× {g('btn_h') + 1:.2f} (Z), placed at x = {g('btn_x'):.2f}, centred in Y (y = {W / 2 - g('btn_w') / 2:.2f}),
from z = {H - 1:.2f} (1 mm sunk into the housing) up to z = {H + g('btn_h'):.2f}. Chamfer its top edges 0.40.

**Sub-part `mounting_tabs`** (colour {rgb('#2a2b2e')}): two boxes `tab_l` {g('tab_l'):.2f} × `tab_w` {g('tab_w'):.2f} ×
`tab_h` {g('tab_h'):.2f}, centred in Y: one on the left end from x = −{g('tab_l'):.2f} to 0 at z = 2.00;
one on the right end from x = {L:.2f} to {L + g('tab_l'):.2f} at z = {H - 2 - g('tab_h'):.2f}.

**SELF-CHECK values:** housing {L:.2f} × {W:.2f} × {H:.2f} (tabs and actuator are outside
this envelope by design and are NOT part of the housing check).
"""


def phototransistor():
    g = lambda k: C.get("phototransistor", k)
    L, W, H = g("L"), g("W"), g("H")
    mk = g("mark")
    return f"""
**Sub-part `housing`** (colour {rgb('#f2c21b')}, ft yellow ABS):
1. Box {L:.2f} × {W:.2f} × {H:.2f}. Chamfer all edges by `edge` = {g('edge'):.2f}.
2. Window slot on the top face: `win_l` {g('win_l'):.2f} (X) × `win_w` {g('win_w'):.2f} (Y),
   `win_depth` {g('win_depth'):.2f} deep, centred on the top face.
3. Two ft plug sockets on the FRONT face (y = 0): Ø{g('sock_d'):.2f}, `sock_depth` {g('sock_depth'):.2f} deep
   in +Y, at z = {H / 2:.2f}, x = {g('sock_x'):.2f} and x = {L - g('sock_x'):.2f}.
4. A {mk:.2f} × {mk:.2f} × 0.20 recess on the top face, corner at
   (x = {L - mk - 1.2:.2f}, y = {W - mk - 1.2:.2f}), for the red "+" marking.

**Sub-part `lens_window`** (colour {rgb('#d9eef7')}, clear): cylinder Ø{g('lens_d'):.2f} × 0.80 standing on the
floor of the window slot (z = {H - g('win_depth'):.2f}), centred at (x = {L / 2:.2f}, y = {W / 2:.2f}).

**Sub-part `plus_marking`** (colour {rgb('#e0312a')}): the {mk:.2f} × {mk:.2f} × 0.20 plate that fills the
recess from step 4 (its top is flush with the housing top, z = {H:.2f}).

**SELF-CHECK values:** housing {L:.2f} × {W:.2f} × {H:.2f}.
"""


def colour_sensor():
    g = lambda k: C.get("colour_sensor", k)
    L, W, H = g("L"), g("W"), g("H")
    x0, x1 = g("hole_x"), g("hole_x") + 4.5
    return f"""
**Sub-part `housing`** (colour {rgb('#2a2b2e')}, dark ABS):
1. Box {L:.2f} × {W:.2f} × {H:.2f}. Chamfer all edges by `edge` = {g('edge'):.2f}.
2. One ft dovetail groove along the full length of the top face, centred at y = {W / 2:.2f}:
   trapezoid `g_mouth` {g('g_mouth'):.2f} at the surface → `g_inner` {g('g_inner'):.2f} at depth `g_depth` {g('g_depth'):.2f}.
3. Two optical windows on the FRONT face (y = 0): Ø{g('hole_d'):.2f} blind holes, `hole_depth`
   {g('hole_depth'):.2f} deep in +Y, at z = {H / 2:.2f}, x = {x0:.2f} (LED) and x = {x1:.2f} (receiver).
4. Two vertical fin slots on the far end face (x = {L:.2f}): `fin_w` {g('fin_w'):.2f} wide (Y),
   `fin_depth` {g('fin_depth'):.2f} deep (−X), from z = 1.00 to z = {H - 1:.2f}, centred at y = {W / 3:.2f} and
   y = {2 * W / 3:.2f}.

**Sub-part `emitter_led`** (colour {rgb('#f5f1e6')}): disc Ø{g('hole_d') - 0.4:.2f} × 0.60 at the bottom of the
x = {x0:.2f} window (from y = {g('hole_depth'):.2f} towards the front).
**Sub-part `receiver`** (colour {rgb('#141414')}): the same disc in the x = {x1:.2f} window.

**Sub-parts `wire_red` / `wire_green` / `wire_black`** (colours {rgb('#d22b2b')} / {rgb('#25a244')} /
{rgb('#1a1a1a')}): cylinders Ø{g('wire_d'):.2f} × {g('wire_l'):.2f} hanging DOWN from the bottom face (z = 0 to
z = −{g('wire_l'):.2f}) at y = {W / 2:.2f}, x = 5.00 / 7.00 / 9.00. (red = 9 VDC, green = ground,
black = analogue signal 0–2 V.)

**SELF-CHECK values:** housing {L:.2f} × {W:.2f} × {H:.2f}.
"""


def s_motor():
    g = lambda k: C.get("s_motor", k)
    L, W, H = g("L"), g("W"), g("H")
    gl, gw, gh = g("gb_l"), g("gb_w"), g("gb_h")
    wz = H / 2 + g("worm_d") / 2 + g("wheel_d") / 2 - 0.5
    return f"""
**Sub-part `housing`** (colour {rgb('#2a2b2e')}, black ABS): box {L:.2f} × {W:.2f} × {H:.2f}, all edges
chamfered `edge` {g('edge'):.2f}. Two ft dovetail grooves along X in the top face at y = 7.50 and
y = {W - 7.5:.2f}. Two Ø{g('sock_d'):.2f} × 6.00 power sockets drilled +X into the x = 0 end face at
y = 10.00 and 20.00, z = {H / 2:.2f}.
**Sub-part `worm_shaft`** (steel): shaft Ø{g('shaft_d'):.2f} from x = {L:.2f} to x = {L + g('worm_l'):.2f} on the
line y = {W / 2:.2f}, z = {H / 2:.2f}; on it a worm, outer Ø{g('worm_d'):.2f}, pitch 1.50, from x = {L + 2:.2f} to
x = {L + g('worm_l'):.2f} (Part Helix + Sweep, or Part Workbench > Thread).
**Sub-part `u_gearbox`** (black ABS): hollow box {gl:.2f} × {gw:.2f} × {gh:.2f} at x = {L:.2f}, wall 1.50,
edges chamfered 0.50; a Ø{g('worm_d') + 1.2:.2f} hole where the worm enters; a Ø{g('axle_d') + 0.6:.2f} hole in
the front wall (y = 0) for the output axle.
**Sub-part `worm_wheel`** (colour {rgb('#e9e6dc')}, POM): gear Ø{g('wheel_d'):.2f} × 4.00 with 20 notches,
axis along Y, centre x = {L + 12:.2f}, z = {wz:.2f}, from y = {W / 2 - 2:.2f} to {W / 2 + 2:.2f}; it meshes with
the worm.
**Sub-part `output_axle`** (steel): Ø{g('axle_d'):.2f} on the wheel's axis, from y = {W / 2 - 2:.2f} out through
the front wall to y = −{g('axle_l'):.2f} (the side output, "seitlicher Abtrieb").

**SELF-CHECK values:** housing {L:.2f} × {W:.2f} × {H:.2f}; gearbox {gl:.2f} × {gw:.2f} × {gh:.2f}; ratio 64.8:1.
"""


def compressor():
    g = lambda k: C.get("compressor", k)
    L, W, H = g("L"), g("W"), g("H")
    r = g("crank_r")
    return f"""
**Sub-part `housing`** (colour {rgb('#1f63c4')}, blue ABS): box {L:.2f} × {W:.2f} × {H:.2f}, edges chamfered
{g('edge'):.2f}, HOLLOWED to a 1.50 wall (Part > Thickness, or cut an inner box). Two ft dovetail grooves
along X in the top at y = 7.50 and y = {W - 7.5:.2f}. A Ø2.40 air hole through the x = {L:.2f} end wall at
y = {W / 2:.2f}, z = {H / 2:.2f}.
**Sub-part `outlet_nipple`** (POM): tube Ø{g('nip_d'):.2f} × {g('nip_l'):.2f} (bore Ø1.80) along +X from that hole.
Inside, on the pump axis y = {W / 2:.2f}, z = {H / 2:.2f} (booklet Abb. 4, from the motor to the nipple):
- `motor`: cylinder Ø14.00 × 12.00, axis Y, at x = 30.00, from y = 1.50.
- `crank` (Kurbeltrieb): disc Ø10.00 × 3.00, axis Y, at x = 30.00, y = 13.50..16.50.
- `crank_pin`: Ø2.00 × 2.50 at x = {30 + r:.2f} (throw {r:.2f}, so the stroke is {2 * r:.2f}).
- `conrod`: bar 10.00 × 2.00 × 2.00 from the pin towards +X.
- `piston` (Kolben): Ø{g('piston_d'):.2f} × 4.00 along X from x = {30 + r + 10:.2f}, in `piston_bore`
  (tube Ø11.00 / Ø{g('piston_d') + 0.4:.2f}, x = 41.00..48.00).
- `membrane` (Membran): disc Ø{g('mem_d'):.2f} × 0.80 at x = 50.00.
- `cover_deckel` (Deckel): hollow cone Ø22 → Ø12 over x = 51.00..57.00.
- `inlet_valve` / `outlet_valve` (Ein-/Auslassventil): flaps 1.50 × 3.00 × 2.00 at x = 56.50,
  z = {H / 2 - 4:.2f} and z = {H / 2 + 2:.2f}.

**SELF-CHECK values:** housing {L:.2f} × {W:.2f} × {H:.2f}; every internal part inside the housing.
"""


def pneumatic_cylinder():
    g = lambda k: C.get("pneumatic_cylinder", k)
    L, W, H = g("L"), g("W"), g("H")
    fc, rc, bd = g("cap_front"), g("cap_rear"), g("barrel_d")
    return f"""
Axis of the cylinder: the line y = {W / 2:.2f}, z = {H / 2:.2f}. The rod extends towards −X.
**Sub-part `housing`** (black ABS): the two end caps. Front cap: box {fc:.2f} × {W:.2f} × {H:.2f} at x = 0 with a
Ø{g('rod_d') + 0.6:.2f} through-hole on the axis. Rear cap: box {rc:.2f} × {W:.2f} × {H:.2f} at x = {L - rc:.2f}.
Edges chamfered 0.40.
**Sub-part `barrel`** (clear PC): tube Ø{bd:.2f} / Ø{bd - 2:.2f} from x = {fc:.2f} to x = {L - rc:.2f}.
**Sub-part `tie_rods`** (steel): two Ø{g('tie_d'):.2f} rods over the full length at (y, z) = (1.80, 1.80) and
({W - 1.8:.2f}, {H - 1.8:.2f}).
**Sub-part `piston`**: Ø{bd - 2.2:.2f} × 3.00 at x = {L - rc - 6:.2f}.
**Sub-part `piston_rod`** (steel): Ø{g('rod_d'):.2f} from x = −{g('rod_out'):.2f} to the piston.
**Sub-part `rod_end`** (red): Ø6.00 × 4.00 from x = −{g('rod_out') + 4:.2f}.
**Sub-part `spring`** (red): compression spring, coil radius 3.20, wire Ø1.00, 9 turns, from the front cap
(x = {fc:.2f}) to the piston.
**Sub-part `air_nipple`** (POM): Ø{g('nip_d'):.2f} × 5.00 standing on the rear cap's top at x = {L - rc / 2:.2f}.

**SELF-CHECK values:** caps span {L:.2f} × {W:.2f} × {H:.2f}; stroke {g('stroke'):.2f}.
"""


def ir_track_sensor():
    g = lambda k: C.get("ir_track_sensor", k)
    L, W, H = g("L"), g("W"), g("H")
    x0, x1 = g("win_x"), L - g("win_x")
    return f"""
**Sub-part `housing`** (colour {rgb('#8f959b')}, grey ABS): box {L:.2f} × {W:.2f} × {H:.2f}, edges chamfered
{g('edge'):.2f}. One ft dovetail groove along X in the top at y = {W / 2:.2f}. Two Ø{g('win_d'):.2f} × 4.00 windows
drilled +Y into the FRONT face (y = 0) at z = {H / 2:.2f}, x = {x0:.2f} and x = {x1:.2f}. Two vertical fin
slots {g('fin_w'):.2f} wide, 1.50 deep in the x = {L:.2f} end face at y = {W / 3:.2f} and {2 * W / 3:.2f}.
**Sub-parts `emitter_1/2`** (IR LED, dark violet) and **`receiver_1/2`** (black): discs Ø1.60 × 0.60 at the
bottom of each window (y = 4.00), emitter at x − 0.90, receiver at x + 0.90.
**Sub-parts `wire_red` / `wire_green` / `wire_black` / `wire_yellow`**: Ø{g('wire_d'):.2f} × {g('wire_l'):.2f}
hanging down from the bottom at y = {W / 2:.2f}, x = 10.00 / 12.50 / 15.00 / 17.50
(red 9 VDC, green ground, black and yellow the two signals).

**SELF-CHECK values:** housing {L:.2f} × {W:.2f} × {H:.2f}.
"""


def solenoid_valve():
    g = lambda k: C.get("solenoid_valve", k)
    L, W, H, t = g("L"), g("W"), g("H"), g("plate_t")
    cw = g("coil_w")
    return f"""
**Sub-part `housing`** (steel): a U bracket of {t:.2f} sheet: bottom plate {L:.2f} × {W:.2f} at z = 0, top plate
at z = {H - t:.2f}, side plate {t:.2f} × {W:.2f} × {H:.2f} at x = 0.
**Sub-part `coil`** (colour {rgb('#1f63c4')}, blue bobbin): box {cw:.2f} × {W - 2:.2f} × {H - 2 * t - 0.2:.2f} centred
between the plates, with a Ø{g('core_d') + 0.6:.2f} vertical bore at x = {L / 2:.2f}, y = {W / 2:.2f}.
**Sub-part `plunger`** (steel, the core "b"): Ø{g('core_d'):.2f} × 14.00 in the bore from z = 4.00; it travels
{g('core_travel'):.2f} up when the coil is energised.
**Sub-part `spring`** ("c"): Ø3.00 coil, wire Ø0.70, from the plunger top (z = 18.00) to the top plate.
**Sub-part `port_1_P`** (POM): nipple Ø{g('nip_d'):.2f} × {g('nip_l'):.2f} up from the top plate at the bore axis.
**Sub-part `port_2_A`**: nipple Ø{g('nip_d'):.2f} × {g('nip_l'):.2f} along +X from x = {L:.2f} at z = 17.00.
**Sub-parts `wire_red` / `wire_black`**: Ø1.20 × 12.00 out of the side plate (−X) at z = 6.00 / 9.00.

**SELF-CHECK values:** bracket {L:.2f} × {W:.2f} × {H:.2f}. Energised: 1 (P) → 2 (A); off: 2 (A) → 3 (R).
"""


BODY = {"encoder_motor": encoder_motor, "mini_switch": mini_switch,
        "phototransistor": phototransistor, "colour_sensor": colour_sensor,
        "s_motor": s_motor, "compressor": compressor, "pneumatic_cylinder": pneumatic_cylinder,
        "ir_track_sensor": ir_track_sensor, "solenoid_valve": solenoid_valve}


def main():
    parts = ["# FreeCAD AI prompts — STF components (all nine from the booklet)\n",
             "Generated by `stf-cad/hbw/components_prompt.py` from `components.py`, the same "
             "table the verified reference models in this folder are built from. Paste ONE "
             "component's section (the shared rules + its section) into the assistant per "
             "request. Reference solutions: `<id>.FCStd` / `<id>.step` next to this file — "
             "compare Gemini's result against them.\n",
             "## Shared rules (paste with every component)\n", "```text", COMMON.strip(), "```\n"]
    for cid, fn in BODY.items():
        c = C.COMPONENTS[cid]
        parts += [f"## {c['name']} — fischertechnik {c['ft']} ({c['name_de']})\n",
                  "```text",
                  f"Build the fischertechnik {c['name']} (part no. {c['ft']}) as a precise FreeCAD model.",
                  f"Datasheet: {c['datasheet']}. Material: {c['material']}.",
                  "", "Ratings and facts (for reference and object properties):", facts(cid),
                  "", "Parameters - create these in the Params spreadsheet with these aliases:",
                  params_table(cid), fn().rstrip(), "```\n"]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(parts))
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1024:.1f} kB)")


if __name__ == "__main__":
    main()
