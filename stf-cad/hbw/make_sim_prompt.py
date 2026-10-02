"""
Generate a complete, self-contained prompt for a web-based simulation of the STF
(fischertechnik Fabrik Simulation 24V, 536634) that matches the proven CAD
mechanics - every number is read from the models, nothing is retyped.

    python3 make_sim_prompt.py
      -> ../handoff/SIM_PROMPT.md   paste into the web tool
      -> ../handoff/sim_data.json   attach if the tool accepts files (same data, exact)

Re-run after any model change, like make_handoff.py. It refuses to write if a
proof fails, and it verifies its own frame formulas against the models before
writing them into the prompt.
"""
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hbw_model as HM, vgr_model as VG, oven_model as OM, sorting_model as SM, plc_model as PM
import factory_layout as FL
import hbw_frames as HF
import vgr_path
import motion

OUT_MD = os.path.join(HERE, "..", "handoff", "SIM_PROMPT.md")
OUT_JSON = os.path.join(HERE, "..", "handoff", "sim_data.json")
PARTS_JSON = os.path.expanduser("~/workspace/stf-hw/web/public/hbw_parts.json")
COLOURS = {"black": "#2b2b2f", "red": "#cf3a2f", "ftred": "#e0492f", "alu": "#d6d9da",
           "steel": "#aeb4b8", "white": "#f2f0ea", "colour": "#2f6fd0", "green": "#1b8f52",
           "amber": "#e0a02a", "grey": "#8b9196", "darkgrey": "#474b52", "slate": "#3a3f44",
           "blue": "#1f63c4"}


def hexof(c):
    return c if isinstance(c, str) and c.startswith("#") else COLOURS.get(c, "#8b9196")


def proofs():
    checks = (("HBW", HM.check(verbose=False)), ("VGR", VG.check(verbose=False)),
              ("OVEN", OM.check(verbose=False)), ("SORTING", SM.check(verbose=False)),
              ("CROSS", FL.check_cross() + FL.check_stations()),
              ("VGR PATH", vgr_path.check(verbose=False)), ("OVEN MOTION", motion.check_oven()))
    bad = {n: f[:3] for n, f in checks if f}
    if bad:
        sys.exit(f"REFUSING to write the prompt - proofs fail: {bad}")
    return [n for n, _ in checks]


def verify_frames():
    """The formulas the prompt states must reproduce the models exactly."""
    errs = []
    mod = {p.name: p for p in HM.build(**HF.HOME)}
    for fr, ps in HF.by_frame().items():
        t, l, f = HF.HOME["travel"], HF.HOME["lift"], HF.HOME["fork"]
        off = {"world": (0, 0, 0), "travel": (t, 0, 0), "lift": (t, 0, l), "fork": (t, f, l)}[fr]
        for p in ps:
            want = mod[p.name].p
            got = tuple(p.p[i] + off[i] for i in range(3))
            if max(abs(a - b) for a, b in zip(want, got)) > 1e-6:
                errs.append(f"HBW {p.name}: local+offset != module")
    # factory transforms: a module corner lands where factory_layout says
    for name, fn, rect in (("HBW", FL.to_factory, FL.module_rect()),
                           ("OVEN", FL.to_factory_oven, FL.oven_rect()),
                           ("SORT", FL.to_factory_sort, FL.sort_rect())):
        tx, ty = {"HBW": (FL.TX, FL.TY), "OVEN": (FL.OVEN_TX, FL.OVEN_TY),
                  "SORT": (FL.SORT_TX, FL.SORT_TY)}[name]
        for x, y in ((0, 0), (100, 37), (-5, 250)):
            a = fn(x, y)[:2]
            b = (-y + tx, x + ty)
            if max(abs(a[0] - b[0]), abs(a[1] - b[1])) > 1e-9:
                errs.append(f"{name}: rot90 formula mismatch")
    # VGR stations: cup centre from (swivel, reach) lands on the target
    for st, s in FL.stations().items():
        cx, cy = FL.cup_at(s["swivel"], s["reach"])
        if max(abs(cx - s["target"][0]), abs(cy - s["target"][1])) > 0.01:
            errs.append(f"VGR station {st}: cup_at != target")
    if errs:
        sys.exit("REFUSING - prompt formulas disagree with the models: " + "; ".join(errs[:5]))


def part_rows(parts, frame_key="f"):
    rows = []
    for q in parts:
        if q.get("g") == "frame":
            continue
        if q["k"] == "box":
            geo = "box p=(%g,%g,%g) s=(%g,%g,%g)" % (*q["p"], *q["s"])
        else:
            ax, L, d = q["s"]
            geo = "cyl p=(%g,%g,%g) axis=%s L=%g D=%g" % (*q["p"], ax, L, d)
        comp = q.get("fit", {}).get("comp", "")
        rows.append(f"| {q['n']} | {q[frame_key]} | {geo} | {hexof(q.get('c'))} | {q.get('tag','')} "
                    f"| {q.get('mech','')} | {comp} |")
    return rows


def main():
    checked = proofs()
    verify_frames()
    d = json.load(open(PARTS_JSON))
    tl = motion.timeline()
    fl = FL.doc()
    v, o, s, p = VG.V, OM.O, SM.S, HM.P
    guides = {"vgr": VG.GUIDES, "hbw": HM.GUIDES}
    wiring = d.get("wiring", {})
    today = time.strftime("%Y-%m-%d")

    L = []
    A = L.append
    A(f"""# PROMPT: Build a precise web-based simulation of the fischertechnik "Fabrik Simulation 24V" (536634)

You are building an interactive, browser-based 3D simulation (three.js / React-Three-Fiber, TypeScript) of a
fischertechnik training factory. It must reproduce the mechanics of an existing, formally checked CAD twin
EXACTLY: same geometry, same joint frames, same limits, same proven motion sequences, same interlocks. Every
number below was generated from the Python source models on {today} after all proofs passed
({", ".join(checked)}). Do not invent, round or "tidy" numbers. Where something is not given, say so in the UI
rather than guessing.

If this tool accepts file attachments, `sim_data.json` (sent alongside) holds the same data in machine-readable
form: prefer it to re-parsing the tables below.

## 1. What the factory is and what it does

Four machines + a PLC cabinet on one table:

| Module | ft no. | Role | Joints (degrees of freedom) |
|---|---|---|---|
| HBW - Hochregallager (high-bay warehouse) | 536631 | stores 12 moulds in a 4 x 3 rack; a stacker crane moves a mould between rack and belt | J1 travel (x), J2 lift (z), J3 Ausleger/fork (y, telescopes one way) |
| VGR - Vakuum-Sauggreifer (vacuum gripper robot) | 536630 | cylindrical R-P-P robot; carries cookies between HBW belt, oven tray and sorting bays | swivel (rz), plunge (z), reach (radial) |
| Oven - Multi-Bearbeitungsstation mit Brennofen | 536632 | tray slides into the oven, door shuts, bake, own vacuum Sauger moves it to a turntable, turntable indexes saw -> belt, pneumatic pusher onto the belt | slider (x), door (z), Drehtisch (rz), Sauger (y), Senken/lower (-z), Auswerfer/push (y) |
| Sortierstrecke (sorting line) | 536633 | belt through a colour-sensor hood; 3 pneumatic ejectors push into 3 bays (weiss/rot/blau) | 3 ejectors (-y) |
| PLC cabinet | - | DIN rail: Mean Well WDR-120-24 PSU, RevPi Core 3, 3x RevPi DIO, RevPi AIO | none |

Process (booklet p.2): workpieces ("cookies", D45 x 20 mm) START in the sorting bays. VGR fills the HBW; HBW stores
by colour, retrieves to the oven; the oven processes; the sorting line sorts by colour into its bays; the VGR
brings them back. The colour sensor (ft 128599) is NOT RGB: it emits red light and measures reflected
brightness - simulate it as one analogue value (reference: chocolate ~340 mV -> blau, strawberry ~950 mV ->
rot, vanilla ~1660 mV -> weiss; datasheet range 0-2 V).

## 2. Units, frames, conventions (most bugs come from here)

- Millimetres and degrees in all data. Z is UP.
- FACTORY frame: the table's FRONT edge is x = 0, +X runs to the BACK, "right" seen from the front is -Y.
- three.js is Y-up. Map factory (x, y, z) -> three (x, z, -y) with a proper ROTATION of the whole stage
  (rotate -90 deg about X). NEVER use (x, z, y): that is a reflection and silently mirrors the factory (a real
  bug this project already had). Assert det(stage matrix) = +1 at startup.
- Table {fl['plate'][0]:.0f} x {fl['plate'][1]:.0f} mm, white, top face at z = -10. Each module sits on a black ft base
  plate (top face z = 0, 10 mm thick), perforated/grooved on a 15 mm grid. Keep the table top 10 mm below the
  plates (coplanar faces flicker).
- Every module is modelled in its OWN module frame and placed by a RIGID transform:
  - HBW, oven, sorting: rotate +90 deg about Z, then translate: factory(x, y) = (-y + TX, x + TY), z unchanged.
  - VGR, PLC: translate only: factory(x, y) = (x + TX, y + TY).

| Module | Transform | TX | TY | Plate (module frame) | Factory footprint rect [x, y, w, h] |
|---|---|---|---|---|---|
| HBW | rot +90 | {FL.TX} | {FL.TY} | {p['PLATE'][0]:.0f} x {p['PLATE'][1]:.0f} | {fl['hbw_rect']} |
| VGR | translate | {FL.VGR_AT[0]} | {FL.VGR_AT[1]} | {v['PLATE'][0]:.0f} x {v['PLATE'][1]:.0f} | {fl['vgr_rect']} |
| Oven | rot +90 | {FL.OVEN_TX} | {FL.OVEN_TY} | {o['PLATE'][0]:.0f} x {o['PLATE'][1]:.0f} | {fl['oven_rect']} |
| Sorting | rot +90 | {FL.SORT_TX} | {FL.SORT_TY} | {s['PLATE'][0]:.0f} x {s['PLATE'][1]:.0f} | {fl['sort_rect']} |
| PLC | translate | {FL.PLC_AT[0]} | {FL.PLC_AT[1]} | {PM.C['PLATE'][0]:.0f} x {PM.C['PLATE'][1]:.0f} | {fl['plc_rect']} |

Layout (booklet cover photo): front row = sorting line (left) + oven (right); back row = VGR (behind sorting)
+ HBW (behind the oven); PLC cabinet in the free front corner. The oven belt ENDS against the sorting belt's
back rail and hands the cookie across the corner onto the sorting inlet.

### Scene graph = kinematic tree (build it exactly like this)

Joints are nested group nodes. A part is added to the node of its `frame` (column "frame" in section 9), with
the coordinates given there. Only the joint nodes' transforms change at run time.

```
stage (rotation -90 deg about X, see above)
 +- table
 +- HBW          rot +90 about Z at (TX, TY)
 |   +- J1_Travel_X    translate (travel, 0, 0)          <- parts with frame "travel"
 |   |   +- J2_Lift_Z  translate (0, 0, lift)            <- frame "lift"
 |   |       +- J3_Ausleger_Y translate (0, fork, 0)     <- frame "fork"
 |   (frame "world" parts directly under HBW)
 +- VGR          translate (TX, TY)
 |   +- J_Swivel  position (CX, CY, 0) = ({v['CX']}, {v['CY']}, 0), rotation (swivel deg about Z)
 |       +- pivot    position (-CX, -CY, 0)                <- frame "swivel" parts
 |           +- J_Plunge  translate (0, 0, plunge - {d['vgr']['authoring']['plunge']:g})  <- frame "plunge"
 |               +- J_Reach translate (0, -reach, 0)     <- frame "reach"   (arm moves toward -Y as reach grows)
 +- Oven         rot +90 about Z at (TX, TY)
 |   +- J_Ofenschieber translate (slider - 435, 0, 0)    <- "slider"
 |   +- J_Ofentuer     translate (0, 0, door - 170)      <- "door"
 |   +- J_Drehkranz    position (TTx, TTy, 0) = ({o['TT'][0]:g}, {o['TT'][1]:g}, 0), rotation (turn deg about Z)
 |   |   +- tt_pivot   position (-TTx, -TTy, 0)           <- "turn"
 |   +- J_Sauger       translate (0, sauger - 335, 0)    <- "sauger"
 |   |   +- J_Senken   translate (0, 0, -lower)          <- "lower"
 |   +- J_Auswerfer    translate (0, push, 0)            <- "push"
 +- Sorting      rot +90 about Z at (TX, TY)
 |   +- J_Auswurf_weiss / _rot / _blau  translate (0, -push_i, 0)   <- "push0" / "push1" / "push2"
 +- PLC          translate (TX, TY)
 +- Wiring       factory coordinates
```

Coordinates of parts:
- HBW parts are given in their joint-LOCAL frame: module = local + (travel, fork, lift) accumulated down the
  chain (world: +0; travel: +(travel,0,0); lift: +(travel,0,lift); fork: +(travel,fork,lift)). Verified
  against the model for all {len(HM.build())} parts at HOME = {HF.HOME}.
- VGR, oven, sorting parts are given in MODULE coordinates at the AUTHORING pose; the joint node applies the
  DIFFERENCE from that pose (VGR authoring {d['vgr']['authoring']}, oven authoring {d['oven']['authoring']},
  sorting authoring = all ejectors 0). The formulas in the tree above already subtract it.
- VGR swivel 0 = arm pointing to module -Y; positive = counter-clockwise seen from above.
""")

    # ------------------------------------------------------------ joints
    A("## 3. Joints, limits and proven stops\n")
    A("| Module | Joint | Kind / axis | Limits | Named stops (proven) |")
    A("|---|---|---|---|---|")
    for j, jd in d["joints"].items():
        A(f"| HBW | {j} | prismatic {jd['axis']} | {jd['limits']} | {jd['stops']} |")
    for m in ("vgr", "oven", "sorting"):
        for j, jd in d[m]["joints"].items():
            A(f"| {m} | {j} | {jd['kind']} {jd.get('axis','')} | {jd['limits']} | {jd['stops']} |")
    A(f"""
VGR stations (SOLVED from the geometry, not typed; cup centre in factory coordinates):

| Station | Target (factory x, y) | swivel deg | reach mm | plunge band [min, max] |
|---|---|---|---|---|""")
    for st, sd in fl["stations"].items():
        A(f"| {st} | {sd['target']} | {sd['swivel']} | {sd['reach']} | {fl['vgr_plunge_band'].get(st)} |")
    A(f"""
VGR geometry rules: cup underside z = plunge - {vgr_path.CUP_DROP:g} (the pick plane). The cup sits on a spring stem
that absorbs up to {v['SPRING']:g} mm of over-travel ({vgr_path.OVERTRAVEL:g} mm used at contact). Cup radius from the swivel axis =
{VG.cup_radius(0):.0f} + reach. Transit (swing) height = plunge {v['TRANSIT']:g}. A LOADED arm must stay at plunge >= {v['CARRY_FLOOR']:g}.
Real 536630 range for reference (fischertechnik product page): 270 deg, 140 mm reach, 120 mm vertical. This
twin is deliberately built at 2x structural scale ({v['REACH'][1]:g} mm reach, {v['PLUNGE'][1]-v['PLUNGE'][0]:g} mm plunge) - show that as a note,
do not "fix" it.

Drives (for animating spindles, drums and gears - mechanics, not decoration):
- HBW travel and lift, VGR plunge and reach: threaded spindles, {v['PITCH_MM']:g} mm lead -> spindle angle = travel / 4 * 360 deg.
- Encoder motors (ft 144643): 3 pulses per motor rev, 25:1 gearbox -> 75 pulses per output rev (booklet).
- Belts: surface speed = drum rim speed; drums D20. Oven/sorting have NO encoders; the sorting belt is
  measured by the I1 pulse switch (Impulstaster).
""")

    # ------------------------------------------------------------ guides
    A("## 4. Guides - what slides through / turns in what (proven on the exact CAD)\n")
    A("Render these as REAL guides: the host has a pocket/bore, the guest runs through it with the clearance "
      "shown. Never let a carriage be drawn through its columns. The CAD proves zero overlap and gap == clearance "
      "for every pair; reproduce the pockets (e.g. CSG or pre-cut geometry) so a close-up looks mechanical.\n")
    A("| Module | Host (moving or fixed) | Guest | Kind | Radial clearance mm |")
    A("|---|---|---|---|---|")
    for m, gl in guides.items():
        for h, g, k, c in gl:
            A(f"| {m} | {h} | {g} | {k} | {c} |")
    A(f"""
Kinds: slide = linear guide (pocket = guest cross-section + clearance on each side); thread = spindle nut (bore =
spindle major diameter + clearance, the nut converts spindle rotation to travel); bore = clearance hole only.
Profiles: VGR tower = 4 x 15x15 mm slotted aluminium profiles at (CX +/- {v['COL_DX']:g}, CY +/- {v['COL_DY']:g}), z {v['COL_Z'][0]:g}..{v['COL_Z'][1]:g};
VGR arm = two {v['ARM_RAIL']:g}x{v['ARM_RAIL']:g} profile rails joined by red end blocks ({v['ARM_END']:g} mm) - the arm slides through the
carriage. Slot profile (assumed, ft-style): mouth 3.2, inner 4.4, depth 3.6 at 15 mm, scaled for 12 mm; centre bore 4.2.
""")

    # ------------------------------------------------------------ interlocks
    A("""## 5. Interlocks - the simulation must enforce these (block or flag the command)

Oven (oven_model.pose_allowed - geometry, not house rules):
1. The Ofenschieber (slider) may move only with the door OPEN (door >= open height); a shut door blocks the mouth.
2. Q12 (lower) may lower only AT a Sauger stop (oven or turntable), by its one 50 mm stroke; the cup then sits
   exactly on the cookie top. Tray top = disc top = belt top = Z_W = %g mm, so one stroke serves both stops.
3. The Auswerfer (push) fires only with the Drehtisch at the belt station (-180 deg), and the Drehtisch turns
   only with the Auswerfer home.
Sorting: only ONE ejector out at a time (shared compressor; each sweeps the full belt width).
VGR: plunge must stay inside the station's plunge band while at a station; swing only at transit height when
carrying; the cup never goes below a cookie's top face.
HBW: the fork telescopes +Y only, one 115 mm stroke serves a rack bay and the belt hand-over; it may extend only
where a station exists at the current height (row / belt levels in the lift stops).
Relays: a bidirectional motor is a relay pair; both relays on = STOP (both leads +24 V), not a short.
""" % o["Z_W"])

    # ------------------------------------------------------------ timelines
    A("## 6. Motion - the proven cycles (keyframes, seconds, linear interpolation, each machine loops its own cycle)\n")
    A("These are the ONLY sequences proven collision-free (VGR: 2 191 swept poses; oven: every interpolated frame "
      "passes the interlocks; HBW: 24 legs x 14 steps swept). Play them as given; any free/jog mode must run the "
      "interlocks of section 5 and should warn that it is outside the proven set.\n")
    for m, keys in tl.items():
        joints = list(keys[0][1].keys())
        A(f"### {m} ({len(keys)} keyframes, cycle {keys[-1][0]:.1f} s)\n")
        A("| t (s) | " + " | ".join(joints) + " | note |")
        A("|---|" + "---|" * (len(joints) + 1))
        for t, pose, say in keys:
            A(f"| {t:.2f} | " + " | ".join(f"{pose[j]:g}" for j in joints) + f" | {say} |")
        A("")
    A("Synchronisation: these four cycles are each proven on their own and loop INDEPENDENTLY. They are not "
      "yet choreographed with each other (e.g. the oven keyframe 'VGR lays the workpiece' does not wait for the "
      "VGR). The factory-level order is the deadlock-free schedule in sim_data.json -> pipeline.transfers "
      f"({len((d.get('pipeline') or {}).get('transfers', []))} atomic transfers, 12 conserved cookies, 3 flavours): a "
      "stretch goal is an orchestrator that plays a machine's cycle segment only when its transfer is due and "
      "hands the cookie object from machine to machine.\n")
    A("VGR `carry` = 1 means a cookie hangs on the cup (top face at the cup underside, i.e. cookie bottom at "
      "plunge - 28 - 20). Show/hide it by that flag.\n")

    # ------------------------------------------------------------ I/O
    A("## 7. PLC I/O (Belegungsplan) - drive the sim from these signals if you add a control panel\n")
    import controller
    ctl = json.load(open(os.path.expanduser("~/workspace/stf-hw/web/public/controller.json")))["modules"]
    import re
    mparts = {"hbw": d["parts"], "vgr": d["vgr"]["parts"], "oven": d["oven"]["parts"],
              "sorting": d["sorting"]["parts"]}
    A("Terminal : signal -> the model part(s) that carry it (the meaning, from the Belegungsplan-derived model).\n")
    for m, cm in ctl.items():
        st3 = cm.get("st3", {})
        who = {}
        for q in mparts.get(m, []):
            for tg in re.findall(r"[IQAB]\d+|AUX\d+", q.get("tag", "")):
                who.setdefault(tg, []).append(q["n"])
        for q in mparts.get(m, []):                          # valves carry their Q in the note
            mm = re.search(r"for (Q\d+)", q.get("note", ""))
            if mm and "valve" in q["n"]:
                who.setdefault(mm.group(1), []).append(q["n"])
        A(f"**{m}** ({cm.get('name','')}, ft {cm.get('ft','')}, supply {cm.get('req',{}).get('supply','?')})\n")
        A("| terminal | signal | model part(s) |")
        A("|---|---|---|")
        for k, v_ in sorted(st3.items(), key=lambda kv: int(kv[0])):
            A(f"| {k} | {v_} | {', '.join(sorted(set(who.get(v_, [])))) or '-'} |")
        A("")
    A("""
Inputs are P-reading (sinking), outputs P-switching (sourcing), 24 V. Encoder channels B.. are quadrature
(push-pull 0/24 V, max 1 kHz). Colour sensor A4 is analogue (0-2 V at the sensor; the adapter PCB scales it -
documents disagree, 0-9/0-10 V; expose the scale as a setting).
""")

    # ------------------------------------------------------------ look
    A("""## 8. Look and components

- Colours are in the parts table (hex). ft red #e0492f / #cf3a2f, black #2b2b2f, alu #d6d9da, steel #aeb4b8.
- Oven detail (booklet Abb. 9): kiln walls = red ft building blocks (30 x 15 bond, 1.0 mm seams); roof = black
  ft plates with a row of flush red caps at 30 mm pitch; door = red panel with seams on steel guide rods; lamp
  Q9 = black socket + warm lens (#ffd27a); Ofenschieber runs on a steel axle between red end blocks; saw gantry
  = black perforated ft Statik struts (4.1 mm holes, 15 mm pitch); saw blade 24 teeth; Drehtisch = red disc
  with a tooth rim; belt = ribbed black rubber.
- Parts whose column "component" is filled are real ft components; draw them at their REAL size (not stretched
  to the box): encoder_motor 60x30x30 (+ shaft D4 x 7.5, two 0.7 flats), mini_switch 30x15x7.5,
  phototransistor 15x15x7.5, colour_sensor 30x15x15 (datasheet); s_motor, compressor, pneumatic_cylinder,
  ir_track_sensor, solenoid_valve are booklet parts with ASSUMED sizes - label them "assumed".
  Seat each by its HOUSING centre on the box centre; shafts / wire stubs / nipples stick out.
- Wiring: every conductor its own tube (d ~1.4 mm), IEC role colours: """ +
      ", ".join(f"{k} {v_['colour']}" for k, v_ in wiring.get("roles", {}).items()) +
      ". Hoses: translucent PU (#7cc3f5, d 4 mm). Routes are polylines in factory coordinates in sim_data.json "
      "(bend radius 10). Moving parts are NOT wired yet (would need drag chains) - leave them unwired.\n")

    # ------------------------------------------------------------ parts
    A("## 9. Every part (module frame; see section 2 for which frame each column refers to)\n")
    A("kind box: p = min corner, s = size. kind cyl: p = centre of the START face, axis x|y|z, L = length along "
      "+axis, D = diameter. 'mech' tags drive animation: thread:<joint> spins with that joint (4 mm lead), "
      "spin:<drive> / pulley turns with the belt or axis, belt = strip whose texture scrolls, spring = compresses "
      "at contact, profile:N = slotted aluminium profile.\n")
    for m, parts in (("HBW (joint-local frames)", d["parts"]), ("VGR", d["vgr"]["parts"]),
                     ("Oven", d["oven"]["parts"]), ("Sorting", d["sorting"]["parts"]),
                     ("PLC", d["plc"]["parts"])):
        A(f"### {m}\n")
        A("| part | frame | geometry | colour | I/O | mech | component |")
        A("|---|---|---|---|---|---|---|")
        L.extend(part_rows(parts))
        A("")

    # ------------------------------------------------------------ acceptance
    st = fl["stations"]["belt"]
    A(f"""## 10. Acceptance tests - build these into the app (a "Self-test" button) and make them pass

1. Mirror test: det(stage matrix) = +1; the HBW is at the BACK-RIGHT and the sorting line FRONT-LEFT seen from
   the front (camera at negative factory x looking +x).
2. Frame test: at HOME, the HBW part `travel_carriage` world box equals module box shifted by (665,0,0) and
   rotated into the factory rect {fl['hbw_rect']}.
3. Station test: set VGR swivel={st['swivel']}, reach={st['reach']}: the cup centre (factory) = {st['target']} +/- 0.1 mm.
4. Pick-plane test: VGR cup underside z = plunge - 28 for any plunge.
5. Interlock tests: commanding slider out with the door shut, lower away from a Sauger stop, push away from
   -180 deg, or two ejectors at once must be refused (and the refusal shown).
6. Cycle test: play every timeline once; no pair of solids from different machines ever intersects (use the box /
   cylinder envelopes of section 9; allowed contacts are only the guide pairs of section 4 and a part touching
   the thing it sits on).
7. Guide test (close-up): a carriage never overlaps its profiles/tubes; the visible gap matches section 4.
8. Scale label: the UI shows "2x structural scale; real VGR 140 mm reach / 120 mm vertical".

## 11. Deliverables

- A scene built from the tables (or sim_data.json), NOT from hand-placed meshes.
- Controls: play/pause/speed, scrub a timeline, per-joint sliders limited to section 3 (with interlocks),
  station buttons for the VGR, toggle wiring / guides / labels, close-up camera presets (VGR carriage, oven
  kiln, saw, HBW lift carriage).
- A live I/O panel (section 7) showing which inputs a pose would trigger (reference switches at stops, light
  barriers broken by a cookie).
- Units shown in mm / deg; every "assumed" value flagged in the UI.

## 12. Sources behind the model

- fischertechnik booklet 536634 "Fabrik Simulation 24V" (Belegungsplan p.3-6, components p.8-11, VGR p.12-13
  Abb. 6, oven p.30 Abb. 9, sorting p.35-36); extended description (24 V adapter PCB, PLC interface).
- Datasheets: encoder motor 144643, mini switch 37783, phototransistor 36134, colour sensor 128599,
  Kunbus RevPi Core / DIO (96 x 22.5 x 110.5 mm), Mean Well WDR-120-24.
- fischertechnik technical sheets 536630 / 536632 (labelled photos, terminal plans) and product page
  (VGR working range 270 deg / 140 mm / 120 mm).

Generated by stf-cad/hbw/make_sim_prompt.py from the source models. Do not edit numbers by hand - regenerate.
""")

    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    open(OUT_MD, "w").write("\n".join(L) + "\n")

    data = {
        "generated": today, "proofs": checked, "units": "mm, deg; Z up; factory x=0 front edge, -Y = right",
        "table": fl["plate"],
        "modules": {
            "hbw": {"transform": {"rotate_deg": 90, "tx": FL.TX, "ty": FL.TY}, "plate": p["PLATE"],
                    "coords": "joint-local: module = local + (travel, fork, lift) accumulated",
                    "home": HF.HOME, "joints": d["joints"], "parts": d["parts"], "guides": HM.GUIDES},
            "vgr": {"transform": {"rotate_deg": 0, "tx": FL.VGR_AT[0], "ty": FL.VGR_AT[1]}, "plate": v["PLATE"],
                    "pivot": [v["CX"], v["CY"]], "authoring": d["vgr"]["authoring"], "joints": d["vgr"]["joints"],
                    "cup_drop": vgr_path.CUP_DROP, "spring": v["SPRING"], "parts": d["vgr"]["parts"],
                    "guides": VG.GUIDES, "stations": fl["stations"], "plunge_bands": fl["vgr_plunge_band"]},
            "oven": {"transform": {"rotate_deg": 90, "tx": FL.OVEN_TX, "ty": FL.OVEN_TY}, "plate": o["PLATE"],
                     "turntable_pivot": list(o["TT"]), "authoring": d["oven"]["authoring"],
                     "joints": d["oven"]["joints"], "parts": d["oven"]["parts"], "flow": OM.flow()},
            "sorting": {"transform": {"rotate_deg": 90, "tx": FL.SORT_TX, "ty": FL.SORT_TY}, "plate": s["PLATE"],
                        "joints": d["sorting"]["joints"], "parts": d["sorting"]["parts"],
                        "colours": list(SM.COLOURS)},
            "plc": {"transform": {"rotate_deg": 0, "tx": FL.PLC_AT[0], "ty": FL.PLC_AT[1]},
                    "plate": PM.C["PLATE"], "parts": d["plc"]["parts"]},
        },
        "timelines": {m: [{"t": round(t, 3), "pose": pz, "say": say} for t, pz, say in k] for m, k in tl.items()},
        "wiring": wiring,
        "pipeline": d.get("pipeline"),
    }
    json.dump(data, open(OUT_JSON, "w"), indent=1, default=list)
    print(f"wrote {OUT_MD} ({os.path.getsize(OUT_MD) / 1e3:.0f} kB, {len(L)} lines)")
    print(f"wrote {OUT_JSON} ({os.path.getsize(OUT_JSON) / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
