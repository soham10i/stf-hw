# PROMPT: Build a precise web-based simulation of the fischertechnik "Fabrik Simulation 24V" (536634)

You are building an interactive, browser-based 3D simulation (three.js / React-Three-Fiber, TypeScript) of a
fischertechnik training factory. It must reproduce the mechanics of an existing, formally checked CAD twin
EXACTLY: same geometry, same joint frames, same limits, same proven motion sequences, same interlocks. Every
number below was generated from the Python source models on 2026-09-28 after all proofs passed
(HBW, VGR, OVEN, SORTING, CROSS, VGR PATH, OVEN MOTION). Do not invent, round or "tidy" numbers. Where something is not given, say so in the UI
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
- Table 1870 x 1510 mm, white, top face at z = -10. Each module sits on a black ft base
  plate (top face z = 0, 10 mm thick), perforated/grooved on a 15 mm grid. Keep the table top 10 mm below the
  plates (coplanar faces flicker).
- Every module is modelled in its OWN module frame and placed by a RIGID transform:
  - HBW, oven, sorting: rotate +90 deg about Z, then translate: factory(x, y) = (-y + TX, x + TY), z unchanged.
  - VGR, PLC: translate only: factory(x, y) = (x + TX, y + TY).

| Module | Transform | TX | TY | Plate (module frame) | Factory footprint rect [x, y, w, h] |
|---|---|---|---|---|---|
| HBW | rot +90 | 1858.0 | 150.0 | 860 x 640 | [1218.0, 150.0, 640.0, 860.0] |
| VGR | translate | 720.0 | 760.0 | 495 x 740 | [720.0, 760.0, 495.0, 740.0] |
| Oven | rot +90 | 1212.0 | 10.0 | 660 x 795 | [417.0, 10.0, 795.0, 660.0] |
| Sorting | rot +90 | 650.0 | 424.0 | 1040 x 640 | [10.0, 424.0, 640.0, 1040.0] |
| PLC | translate | 60.0 | 20.0 | 300 x 380 | [60.0, 20.0, 300.0, 380.0] |

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
 |   +- J_Swivel  position (CX, CY, 0) = (180.0, 200.0, 0), rotation (swivel deg about Z)
 |       +- pivot    position (-CX, -CY, 0)                <- frame "swivel" parts
 |           +- J_Plunge  translate (0, 0, plunge - 250)  <- frame "plunge"
 |               +- J_Reach translate (0, -reach, 0)     <- frame "reach"   (arm moves toward -Y as reach grows)
 +- Oven         rot +90 about Z at (TX, TY)
 |   +- J_Ofenschieber translate (slider - 435, 0, 0)    <- "slider"
 |   +- J_Ofentuer     translate (0, 0, door - 170)      <- "door"
 |   +- J_Drehkranz    position (TTx, TTy, 0) = (460, 400, 0), rotation (turn deg about Z)
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
  against the model for all 183 parts at HOME = {'travel': 665.0, 'lift': 120.0, 'fork': 0.0}.
- VGR, oven, sorting parts are given in MODULE coordinates at the AUTHORING pose; the joint node applies the
  DIFFERENCE from that pose (VGR authoring {'swivel': 0.0, 'plunge': 250.0, 'reach': 0.0}, oven authoring {'slider': 435.0, 'door': 170.0, 'turn': 0.0, 'sauger': 335.0, 'lower': 0.0, 'push': 0.0},
  sorting authoring = all ejectors 0). The formulas in the tree above already subtract it.
- VGR swivel 0 = arm pointing to module -Y; positive = counter-clockwise seen from above.

## 3. Joints, limits and proven stops

| Module | Joint | Kind / axis | Limits | Named stops (proven) |
|---|---|---|---|---|
| HBW | travel | prismatic x | [120.0, 665.0] | {'bay1': 120.0, 'bay2': 240.0, 'bay3': 360.0, 'bay4': 480.0, 'conveyor': 665.0} |
| HBW | lift | prismatic z | [80.0, 360.0] | {'rowA_under': 100.0, 'rowB_under': 220.0, 'rowC_under': 340.0, 'rowA_lift': 120.0, 'rowB_lift': 240.0, 'rowC_lift': 360.0, 'belt_under': 80.0, 'belt_lift': 100.0, 'transit': 260.0} |
| HBW | fork | prismatic y | [0.0, 115.0] | {'retracted': 0.0, 'bay': 115.0, 'conveyor': 115.0} |
| vgr | swivel | revolute  | [-125.0, 135.0] | {'home': 0.0, 'belt': 69.013} |
| vgr | plunge | prismatic  | [84.0, 540.0] | {'raised': 500.0, 'transit': 500.0, 'pick': 156.0} |
| vgr | reach | prismatic  | [0.0, 400.0] | {'retracted': 0.0, 'belt': 236.857} |
| oven | slider | prismatic +x | [250.0, 435.0] | {'innen': 250.0, 'aussen': 435.0} |
| oven | door | prismatic +z | [50.0, 170.0] | {'shut': 50.0, 'open': 170.0} |
| oven | turn | revolute rz | [-180.0, 0.0] | {'sauger': 0.0, 'saege': -90.0, 'band': -180.0} |
| oven | sauger | prismatic +y | [100.0, 335.0] | {'oven': 100.0, 'turntable': 335.0} |
| oven | lower | prismatic -z | [0.0, 50.0] | {'up': 0.0, 'down': 50.0} |
| oven | push | prismatic +y | [0.0, 80.0] | {'home': 0.0, 'out': 80.0} |
| sorting | push | prismatic -y | [0.0, 90.0] | {'home': 0.0, 'eject': 90.0} |

VGR stations (SOLVED from the geometry, not typed; cup centre in factory coordinates):

| Station | Target (factory x, y) | swivel deg | reach mm | plunge band [min, max] |
|---|---|---|---|---|
| belt | [1278.0, 815.0] | 69.013 | 236.857 | (140.0, 320.0) |
| oven | [1112.0, 470.0] | 23.396 | 365.895 | (100.0, 320.0) |
| bay_weiss | [583.0, 884.0] | -76.518 | 157.983 | (110.0, 320.0) |
| bay_rot | [583.0, 1024.0] | -101.414 | 155.396 | (110.0, 320.0) |
| bay_blau | [583.0, 1164.0] | -122.763 | 208.968 | (110.0, 320.0) |

VGR geometry rules: cup underside z = plunge - 28 (the pick plane). The cup sits on a spring stem
that absorbs up to 6 mm of over-travel (4 mm used at contact). Cup radius from the swivel axis =
168 + reach. Transit (swing) height = plunge 500. A LOADED arm must stay at plunge >= 100.
Real 536630 range for reference (fischertechnik product page): 270 deg, 140 mm reach, 120 mm vertical. This
twin is deliberately built at 2x structural scale (400 mm reach, 456 mm plunge) - show that as a note,
do not "fix" it.

Drives (for animating spindles, drums and gears - mechanics, not decoration):
- HBW travel and lift, VGR plunge and reach: threaded spindles, 4 mm lead -> spindle angle = travel / 4 * 360 deg.
- Encoder motors (ft 144643): 3 pulses per motor rev, 25:1 gearbox -> 75 pulses per output rev (booklet).
- Belts: surface speed = drum rim speed; drums D20. Oven/sorting have NO encoders; the sorting belt is
  measured by the I1 pulse switch (Impulstaster).

## 4. Guides - what slides through / turns in what (proven on the exact CAD)

Render these as REAL guides: the host has a pocket/bore, the guest runs through it with the clearance shown. Never let a carriage be drawn through its columns. The CAD proves zero overlap and gap == clearance for every pair; reproduce the pockets (e.g. CSG or pre-cut geometry) so a close-up looks mechanical.

| Module | Host (moving or fixed) | Guest | Kind | Radial clearance mm |
|---|---|---|---|---|
| vgr | plunge_carriage | tower_column_1 | slide | 0.3 |
| vgr | plunge_carriage | tower_column_2 | slide | 0.3 |
| vgr | plunge_carriage | tower_column_3 | slide | 0.3 |
| vgr | plunge_carriage | tower_column_4 | slide | 0.3 |
| vgr | plunge_carriage | arm_rail_L | slide | 0.3 |
| vgr | plunge_carriage | arm_rail_R | slide | 0.3 |
| vgr | plunge_carriage | plunge_spindle | bore | 1.0 |
| vgr | plunge_carriage | reach_spindle | bore | 1.0 |
| vgr | plunge_nut | plunge_spindle | thread | 0.05 |
| vgr | reach_nut | reach_spindle | thread | 0.05 |
| vgr | reach_bearing_F | reach_spindle | bore | 0.05 |
| vgr | reach_bearing_B | reach_spindle | bore | 0.05 |
| hbw | lift_carriage_L | mast_tube_1 | slide | 0.3 |
| hbw | lift_carriage_L | mast_tube_3 | slide | 0.3 |
| hbw | lift_carriage_R | mast_tube_2 | slide | 0.3 |
| hbw | lift_carriage_R | mast_tube_4 | slide | 0.3 |
| hbw | lift_carriage_L | lift_spindle | thread | 0.05 |
| hbw | lift_carriage_yoke | mast_tube_1 | slide | 0.3 |
| hbw | lift_carriage_yoke | mast_tube_2 | slide | 0.3 |
| hbw | lift_carriage_yoke | mast_tube_3 | slide | 0.3 |
| hbw | lift_carriage_yoke | mast_tube_4 | slide | 0.3 |
| hbw | fork_yoke | mast_tube_1 | slide | 0.3 |
| hbw | fork_yoke | mast_tube_2 | slide | 0.3 |
| hbw | fork_yoke | mast_tube_3 | slide | 0.3 |
| hbw | fork_yoke | mast_tube_4 | slide | 0.3 |
| hbw | lift_carriage_yoke | lift_spindle | bore | 1.0 |
| hbw | fork_yoke | lift_spindle | bore | 1.0 |
| hbw | travel_carriage | guide_rod | slide | 0.3 |
| hbw | travel_carriage | travel_spindle | thread | 0.05 |

Kinds: slide = linear guide (pocket = guest cross-section + clearance on each side); thread = spindle nut (bore =
spindle major diameter + clearance, the nut converts spindle rotation to travel); bore = clearance hole only.
Profiles: VGR tower = 4 x 15x15 mm slotted aluminium profiles at (CX +/- 50, CY +/- 15), z 38..600;
VGR arm = two 12x12 profile rails joined by red end blocks (14 mm) - the arm slides through the
carriage. Slot profile (assumed, ft-style): mouth 3.2, inner 4.4, depth 3.6 at 15 mm, scaled for 12 mm; centre bore 4.2.

## 5. Interlocks - the simulation must enforce these (block or flag the command)

Oven (oven_model.pose_allowed - geometry, not house rules):
1. The Ofenschieber (slider) may move only with the door OPEN (door >= open height); a shut door blocks the mouth.
2. Q12 (lower) may lower only AT a Sauger stop (oven or turntable), by its one 50 mm stroke; the cup then sits
   exactly on the cookie top. Tray top = disc top = belt top = Z_W = 60 mm, so one stroke serves both stops.
3. The Auswerfer (push) fires only with the Drehtisch at the belt station (-180 deg), and the Drehtisch turns
   only with the Auswerfer home.
Sorting: only ONE ejector out at a time (shared compressor; each sweeps the full belt width).
VGR: plunge must stay inside the station's plunge band while at a station; swing only at transit height when
carrying; the cup never goes below a cookie's top face.
HBW: the fork telescopes +Y only, one 115 mm stroke serves a rack bay and the belt hand-over; it may extend only
where a station exists at the current height (row / belt levels in the lift stops).
Relays: a bidirectional motor is a relay pair; both relays on = STOP (both leads +24 V), not a short.

## 6. Motion - the proven cycles (keyframes, seconds, linear interpolation, each machine loops its own cycle)

These are the ONLY sequences proven collision-free (VGR: 2 191 swept poses; oven: every interpolated frame passes the interlocks; HBW: 24 legs x 14 steps swept). Play them as given; any free/jog mode must run the interlocks of section 5 and should warn that it is outside the proven set.

### hbw (25 keyframes, cycle 22.4 s)

| t (s) | travel | lift | fork | note |
|---|---|---|---|---|
| 0.00 | 665 | 260 | 0 |  |
| 2.83 | 240 | 260 | 0 |  |
| 3.23 | 240 | 220 | 0 |  |
| 4.00 | 240 | 220 | 115 |  |
| 4.40 | 240 | 240 | 115 |  |
| 5.17 | 240 | 240 | 0 |  |
| 5.57 | 240 | 260 | 0 |  |
| 8.40 | 665 | 260 | 0 |  |
| 9.47 | 665 | 100 | 0 |  |
| 10.23 | 665 | 100 | 115 |  |
| 10.63 | 665 | 80 | 115 |  |
| 11.40 | 665 | 80 | 0 |  |
| 12.60 | 665 | 260 | 0 |  |
| 13.80 | 665 | 80 | 0 |  |
| 14.57 | 665 | 80 | 115 |  |
| 14.97 | 665 | 100 | 115 |  |
| 15.73 | 665 | 100 | 0 |  |
| 16.80 | 665 | 260 | 0 |  |
| 18.03 | 480 | 260 | 0 |  |
| 18.70 | 480 | 360 | 0 |  |
| 19.47 | 480 | 360 | 115 |  |
| 19.87 | 480 | 340 | 115 |  |
| 20.63 | 480 | 340 | 0 |  |
| 21.17 | 480 | 260 | 0 |  |
| 22.40 | 665 | 260 | 0 |  |

### vgr (42 keyframes, cycle 42.9 s)

| t (s) | swivel | plunge | reach | carry | note |
|---|---|---|---|---|---|
| 0.00 | 0 | 500 | 0 | 0 | VGR at home, transit height |
| 1.97 | 69.013 | 500 | 236.857 | 0 | swing to the warehouse belt at transit height |
| 4.47 | 69.013 | 201 | 236.857 | 0 | descend beside the warehouse belt |
| 4.87 | 69.013 | 201 | 236.857 | 0 | extend over the warehouse belt |
| 5.27 | 69.013 | 156 | 236.857 | 0 | cup meets the cookie's top face |
| 5.67 | 69.013 | 152 | 236.857 | 0 | press: the spring stem takes up the over-travel |
| 6.07 | 69.013 | 152 | 236.857 | 1 | Q7/Q8 vacuum on - the cup sucks down onto the cookie |
| 6.47 | 69.013 | 156 | 236.857 | 1 | spring relaxes - seal holds |
| 6.87 | 69.013 | 201 | 236.857 | 1 | lift the cookie clear |
| 7.27 | 69.013 | 201 | 236.857 | 1 | retract out from the station |
| 9.76 | 69.013 | 500 | 236.857 | 1 | rise to transit height |
| 10.83 | 23.396 | 500 | 365.895 | 1 | swing to the oven's Ofenschieber at transit height |
| 13.72 | 23.396 | 153 | 365.895 | 1 | descend beside the oven's Ofenschieber |
| 14.12 | 23.396 | 153 | 365.895 | 1 | extend over the oven's Ofenschieber |
| 14.52 | 23.396 | 108 | 365.895 | 1 | cup meets the cookie's top face |
| 14.92 | 23.396 | 104 | 365.895 | 1 | press: the spring stem takes up the over-travel |
| 15.32 | 23.396 | 104 | 365.895 | 0 | vacuum off - the cookie is released |
| 15.72 | 23.396 | 108 | 365.895 | 0 | spring relaxes |
| 16.12 | 23.396 | 153 | 365.895 | 0 | lift clear |
| 16.52 | 23.396 | 153 | 365.895 | 0 | retract out from the station |
| 19.42 | 23.396 | 500 | 365.895 | 0 | rise to transit height |
| 21.50 | -101.414 | 500 | 155.396 | 0 | swing to the rot Lagerstelle at transit height |
| 24.51 | -101.414 | 138 | 155.396 | 0 | descend beside the rot Lagerstelle |
| 24.91 | -101.414 | 138 | 155.396 | 0 | extend over the rot Lagerstelle |
| 25.31 | -101.414 | 93 | 155.396 | 0 | cup meets the cookie's top face |
| 25.71 | -101.414 | 89 | 155.396 | 0 | press: the spring stem takes up the over-travel |
| 26.11 | -101.414 | 89 | 155.396 | 1 | Q7/Q8 vacuum on - the cup sucks down onto the cookie |
| 26.51 | -101.414 | 93 | 155.396 | 1 | spring relaxes - seal holds |
| 26.91 | -101.414 | 138 | 155.396 | 1 | lift the cookie clear |
| 27.31 | -101.414 | 138 | 155.396 | 1 | retract out from the station |
| 30.33 | -101.414 | 500 | 155.396 | 1 | rise to transit height |
| 33.17 | 69.013 | 500 | 236.857 | 1 | swing to the warehouse belt at transit height |
| 35.66 | 69.013 | 201 | 236.857 | 1 | descend beside the warehouse belt |
| 36.06 | 69.013 | 201 | 236.857 | 1 | extend over the warehouse belt |
| 36.46 | 69.013 | 156 | 236.857 | 1 | cup meets the cookie's top face |
| 36.86 | 69.013 | 152 | 236.857 | 1 | press: the spring stem takes up the over-travel |
| 37.26 | 69.013 | 152 | 236.857 | 0 | vacuum off - the cookie is released |
| 37.66 | 69.013 | 156 | 236.857 | 0 | spring relaxes |
| 38.06 | 69.013 | 201 | 236.857 | 0 | lift clear |
| 38.46 | 69.013 | 201 | 236.857 | 0 | retract out from the station |
| 40.95 | 69.013 | 500 | 236.857 | 0 | rise to transit height |
| 42.93 | 0 | 500 | 0 | 0 | VGR back home |

### oven (22 keyframes, cycle 28.1 s)

| t (s) | slider | door | turn | sauger | lower | push | note |
|---|---|---|---|---|---|---|---|
| 0.00 | 250 | 50 | 0 | 335 | 0 | 0 | idle: slider in, door shut, Sauger parked over the Drehtisch |
| 1.00 | 250 | 170 | 0 | 335 | 0 | 0 | Q13: door opens |
| 3.00 | 435 | 170 | 0 | 335 | 0 | 0 | Q6: Ofenschieber extends - the VGR lays the workpiece on it (I9 breaks) |
| 5.00 | 250 | 170 | 0 | 335 | 0 | 0 | Q5: slider retracts into the oven |
| 6.00 | 250 | 50 | 0 | 335 | 0 | 0 | door shuts - bake (Q9 lamp) |
| 8.00 | 250 | 50 | 0 | 335 | 0 | 0 | baking |
| 9.00 | 250 | 170 | 0 | 335 | 0 | 0 | door opens |
| 11.00 | 435 | 170 | 0 | 335 | 0 | 0 | slider extends |
| 13.00 | 435 | 170 | 0 | 100 | 0 | 0 | Q7: Sauger to the oven (I8) |
| 13.60 | 435 | 170 | 0 | 100 | 50 | 0 | Q12: lower onto the workpiece, Q11 vacuum |
| 14.20 | 435 | 170 | 0 | 100 | 0 | 0 | lift |
| 16.20 | 435 | 170 | 0 | 335 | 0 | 0 | Q8: Sauger to the Drehtisch (I5) |
| 16.80 | 435 | 170 | 0 | 335 | 50 | 0 | lower, release onto the disc |
| 17.40 | 435 | 170 | 0 | 335 | 0 | 0 | lift |
| 19.40 | 250 | 170 | 0 | 335 | 0 | 0 | slider retracts |
| 20.40 | 250 | 50 | 0 | 335 | 0 | 0 | door shuts |
| 21.90 | 250 | 50 | -90 | 335 | 0 | 0 | Q1: Drehtisch to the Säge (I4) |
| 23.90 | 250 | 50 | -90 | 335 | 0 | 0 | Q4: saw runs |
| 25.40 | 250 | 50 | -180 | 335 | 0 | 0 | Drehtisch to the belt (I2) |
| 26.00 | 250 | 50 | -180 | 335 | 0 | 80 | Q14: Auswerfer pushes the workpiece onto the belt |
| 26.60 | 250 | 50 | -180 | 335 | 0 | 0 | Auswerfer home |
| 28.10 | 250 | 50 | 0 | 335 | 0 | 0 | I3 passed: Drehtisch home |

### sorting (10 keyframes, cycle 9.0 s)

| t (s) | push0 | push1 | push2 | note |
|---|---|---|---|---|
| 0.00 | 0 | 0 | 0 | belt runs |
| 2.00 | 0 | 0 | 0 | eject weiss |
| 2.50 | 90 | 0 | 0 | eject weiss |
| 3.00 | 0 | 0 | 0 | eject weiss |
| 5.00 | 0 | 0 | 0 | eject rot |
| 5.50 | 0 | 90 | 0 | eject rot |
| 6.00 | 0 | 0 | 0 | eject rot |
| 8.00 | 0 | 0 | 0 | eject blau |
| 8.50 | 0 | 0 | 90 | eject blau |
| 9.00 | 0 | 0 | 0 | eject blau |

Synchronisation: these four cycles are each proven on their own and loop INDEPENDENTLY. They are not yet choreographed with each other (e.g. the oven keyframe 'VGR lays the workpiece' does not wait for the VGR). The factory-level order is the deadlock-free schedule in sim_data.json -> pipeline.transfers (96 atomic transfers, 12 conserved cookies, 3 flavours): a stretch goal is an orchestrator that plays a machine's cycle segment only when its transfer is due and hands the cookie object from machine to machine.

VGR `carry` = 1 means a cookie hangs on the cup (top face at the cup underside, i.e. cookie bottom at plunge - 28 - 20). Show/hide it by that flag.

## 7. PLC I/O (Belegungsplan) - drive the sim from these signals if you add a control panel

Terminal : signal -> the model part(s) that carry it (the meaning, from the Belegungsplan-derived model).

**hbw** (Automated High-Bay Warehouse 24V, ft 536631, supply 24 V / 1.2 A)

| terminal | signal | model part(s) |
|---|---|---|
| 5 | I1 | I1_ref_horizontal |
| 6 | I2 | I2_lightbarrier_inner_rx, I2_lightbarrier_inner_tx |
| 7 | I3 | I3_lightbarrier_outer_rx, I3_lightbarrier_outer_tx |
| 8 | I4 | I4_ref_vertical |
| 9 | A1 | A1_trail_lower |
| 10 | A2 | A2_trail_upper |
| 11 | B1 | M2_travel_motor |
| 12 | B2 | M2_travel_motor |
| 13 | B3 | M3_lift_motor |
| 14 | B4 | M3_lift_motor |
| 15 | I5 | I5_ref_ausleger_front |
| 16 | I6 | I6_ref_ausleger_back |
| 17 | Q1 | M1_belt_motor |
| 18 | Q2 | M1_belt_motor |
| 19 | Q3 | M2_travel_motor |
| 20 | Q4 | M2_travel_motor |
| 21 | Q5 | M3_lift_motor |
| 22 | Q6 | M3_lift_motor |
| 23 | Q7 | M4_fork_motor |
| 24 | Q8 | M4_fork_motor |

**vgr** (Vacuum Gripper Robot 24V, ft 536630, supply 24 V / approx. 0.9 A)

| terminal | signal | model part(s) |
|---|---|---|
| 5 | I1 | I1_ref_plunge |
| 6 | I2 | I2_ref_reach |
| 7 | I3 | I3_ref_swivel |
| 9 | B1 | M1_plunge_motor |
| 10 | B2 | M1_plunge_motor |
| 11 | B3 | M2_reach_motor |
| 12 | B4 | M2_reach_motor |
| 13 | B5 | M3_swivel_motor |
| 14 | B6 | M3_swivel_motor |
| 17 | Q1 | M1_plunge_motor |
| 18 | Q2 | M1_plunge_motor |
| 19 | Q3 | M2_reach_motor |
| 20 | Q4 | M2_reach_motor |
| 21 | Q5 | M3_swivel_motor |
| 22 | Q6 | M3_swivel_motor |
| 23 | Q7 | compressor |
| 24 | Q8 | suction_cup, vacuum_valve |

**oven** (Multi Processing Station with Oven 24V, ft 536632, supply 24 V / approx. 1.6 A)

| terminal | signal | model part(s) |
|---|---|---|
| 5 | I1 | I1_ref_turn_sauger |
| 6 | I2 | I2_ref_turn_band |
| 7 | I3 | I3_lightbarrier_rx, I3_lightbarrier_tx |
| 8 | I4 | I4_ref_turn_saege |
| 9 | I5 | I5_ref_sauger_turntable |
| 10 | I6 | I6_ref_slider_in |
| 11 | I7 | I7_ref_slider_out |
| 12 | I8 | I8_ref_sauger_oven |
| 13 | I9 | I9_lightbarrier_rx, I9_lightbarrier_tx |
| 17 | Q1 | M1_turntable_motor |
| 18 | Q2 | M1_turntable_motor |
| 19 | Q3 | M2_belt_motor |
| 20 | Q4 | M3_saw_motor |
| 21 | Q5 | M4_slider_motor |
| 22 | Q6 | M4_slider_motor |
| 23 | Q7 | M5_sauger_motor |
| 24 | Q8 | M5_sauger_motor |
| 25 | Q9 | Q9_oven_lamp |
| 26 | Q10 | Q10_compressor |
| 27 | Q11 | Q11_suction_cup, V1_valve_vakuum |
| 28 | Q12 | Q12_lower_cylinder, V2_valve_senken |
| 29 | Q13 | Q13_door_cylinder, Q13_oven_door, V3_valve_ofentuer |
| 30 | Q14 | Q14_pusher_cylinder, V4_valve_schieber |

**sorting** (Sorting Line with Detection 24V, ft 536633, supply 24 V / 1.1 A)

| terminal | signal | model part(s) |
|---|---|---|
| 5 | I1 | I1_impulstaster |
| 6 | I2 | I2_inlet_rx, I2_inlet_tx |
| 7 | I3 | I3_after_colour_rx, I3_after_colour_tx |
| 9 | A4 | A4_colour_sensor |
| 10 | I5 | I5_bay_weiss_rx, I5_bay_weiss_tx |
| 11 | I6 | I6_bay_rot_rx, I6_bay_rot_tx |
| 12 | I7 | I7_bay_blau_rx, I7_bay_blau_tx |
| 17 | Q1 | Q1_belt_motor |
| 18 | Q2 | Q2_compressor |
| 20 | Q3 | Q3_cylinder_weiss, valve_weiss |
| 21 | Q4 | Q4_cylinder_rot, valve_rot |
| 22 | Q5 | Q5_cylinder_blau, valve_blau |


Inputs are P-reading (sinking), outputs P-switching (sourcing), 24 V. Encoder channels B.. are quadrature
(push-pull 0/24 V, max 1 kHz). Colour sensor A4 is analogue (0-2 V at the sensor; the adapter PCB scales it -
documents disagree, 0-9/0-10 V; expose the scale as a setting).

## 8. Look and components

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
- Wiring: every conductor its own tube (d ~1.4 mm), IEC role colours: +24V #d62828, 0V #1d4ed8, PE PE, L #7a4a1f, N #4aa3df, DI #e5e7eb, DO #f97316, ENC #eab308, AI #8b5cf6, AIR #7cc3f5. Hoses: translucent PU (#7cc3f5, d 4 mm). Routes are polylines in factory coordinates in sim_data.json (bend radius 10). Moving parts are NOT wired yet (would need drag chains) - leave them unwired.

## 9. Every part (module frame; see section 2 for which frame each column refers to)

kind box: p = min corner, s = size. kind cyl: p = centre of the START face, axis x|y|z, L = length along +axis, D = diameter. 'mech' tags drive animation: thread:<joint> spins with that joint (4 mm lead), spin:<drive> / pulley turns with the belt or axis, belt = strip whose texture scrolls, spring = compresses at contact, profile:N = slotted aluminium profile.

### HBW (joint-local frames)

| part | frame | geometry | colour | I/O | mech | component |
|---|---|---|---|---|---|---|
| rack_post_1 | world | box p=(45,290,0) s=(30,70,420) | #2b2b2f |  |  |  |
| rack_post_2 | world | box p=(165,290,0) s=(30,70,420) | #2b2b2f |  |  |  |
| rack_post_3 | world | box p=(285,290,0) s=(30,70,420) | #2b2b2f |  |  |  |
| rack_post_4 | world | box p=(405,290,0) s=(30,70,420) | #2b2b2f |  |  |  |
| rack_post_5 | world | box p=(525,290,0) s=(30,70,420) | #2b2b2f |  |  |  |
| rack_cap_beam | world | box p=(45,290,420) s=(510,70,15) | #2b2b2f |  |  |  |
| shelf_A1_L | world | box p=(70,290,105) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_A1_R | world | box p=(140,290,105) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_B1_L | world | box p=(70,290,225) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_B1_R | world | box p=(140,290,225) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_C1_L | world | box p=(70,290,345) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_C1_R | world | box p=(140,290,345) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_A2_L | world | box p=(190,290,105) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_A2_R | world | box p=(260,290,105) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_B2_L | world | box p=(190,290,225) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_B2_R | world | box p=(260,290,225) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_C2_L | world | box p=(190,290,345) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_C2_R | world | box p=(260,290,345) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_A3_L | world | box p=(310,290,105) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_A3_R | world | box p=(380,290,105) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_B3_L | world | box p=(310,290,225) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_B3_R | world | box p=(380,290,225) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_C3_L | world | box p=(310,290,345) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_C3_R | world | box p=(380,290,345) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_A4_L | world | box p=(430,290,105) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_A4_R | world | box p=(500,290,105) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_B4_L | world | box p=(430,290,225) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_B4_R | world | box p=(500,290,225) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_C4_L | world | box p=(430,290,345) s=(30,70,15) | #cf3a2f |  |  |  |
| shelf_C4_R | world | box p=(500,290,345) s=(30,70,15) | #cf3a2f |  |  |  |
| mould_A1_base | world | box p=(90,293,120) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_A1_rim_L | world | box p=(90,293,128) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_A1_rim_R | world | box p=(145,293,128) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_A1_rim_Fa | world | box p=(95,293,128) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_A1_rim_Fb | world | box p=(132,293,128) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_A1_rim_B | world | box p=(95,352,128) s=(50,5,12) | #aeb4b8 |  |  |  |
| wp_A1_body | world | cyl p=(120,325,128) axis=z L=16 D=45 | #F4F2EC |  |  |  |
| wp_A1_lid | world | cyl p=(120,325,144) axis=z L=4 D=45 | #F4F2EC |  |  |  |
| mould_A2_base | world | box p=(210,293,120) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_A2_rim_L | world | box p=(210,293,128) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_A2_rim_R | world | box p=(265,293,128) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_A2_rim_Fa | world | box p=(215,293,128) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_A2_rim_Fb | world | box p=(252,293,128) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_A2_rim_B | world | box p=(215,352,128) s=(50,5,12) | #aeb4b8 |  |  |  |
| wp_A2_body | world | cyl p=(240,325,128) axis=z L=16 D=45 | #F4F2EC |  |  |  |
| wp_A2_lid | world | cyl p=(240,325,144) axis=z L=4 D=45 | #F4F2EC |  |  |  |
| mould_A3_base | world | box p=(330,293,120) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_A3_rim_L | world | box p=(330,293,128) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_A3_rim_R | world | box p=(385,293,128) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_A3_rim_Fa | world | box p=(335,293,128) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_A3_rim_Fb | world | box p=(372,293,128) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_A3_rim_B | world | box p=(335,352,128) s=(50,5,12) | #aeb4b8 |  |  |  |
| wp_A3_body | world | cyl p=(360,325,128) axis=z L=16 D=45 | #F4F2EC |  |  |  |
| wp_A3_lid | world | cyl p=(360,325,144) axis=z L=4 D=45 | #F4F2EC |  |  |  |
| mould_A4_base | world | box p=(450,293,120) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_A4_rim_L | world | box p=(450,293,128) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_A4_rim_R | world | box p=(505,293,128) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_A4_rim_Fa | world | box p=(455,293,128) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_A4_rim_Fb | world | box p=(492,293,128) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_A4_rim_B | world | box p=(455,352,128) s=(50,5,12) | #aeb4b8 |  |  |  |
| wp_A4_body | world | cyl p=(480,325,128) axis=z L=16 D=45 | #F4F2EC |  |  |  |
| wp_A4_lid | world | cyl p=(480,325,144) axis=z L=4 D=45 | #F4F2EC |  |  |  |
| mould_B1_base | world | box p=(90,293,240) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_B1_rim_L | world | box p=(90,293,248) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_B1_rim_R | world | box p=(145,293,248) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_B1_rim_Fa | world | box p=(95,293,248) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_B1_rim_Fb | world | box p=(132,293,248) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_B1_rim_B | world | box p=(95,352,248) s=(50,5,12) | #aeb4b8 |  |  |  |
| wp_B1_body | world | cyl p=(120,325,248) axis=z L=16 D=45 | #F4F2EC |  |  |  |
| wp_B1_lid | world | cyl p=(120,325,264) axis=z L=4 D=45 | #F4F2EC |  |  |  |
| mould_B2_base | world | box p=(210,293,240) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_B2_rim_L | world | box p=(210,293,248) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_B2_rim_R | world | box p=(265,293,248) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_B2_rim_Fa | world | box p=(215,293,248) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_B2_rim_Fb | world | box p=(252,293,248) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_B2_rim_B | world | box p=(215,352,248) s=(50,5,12) | #aeb4b8 |  |  |  |
| wp_B2_body | world | cyl p=(240,325,248) axis=z L=16 D=45 | #F4F2EC |  |  |  |
| wp_B2_lid | world | cyl p=(240,325,264) axis=z L=4 D=45 | #F4F2EC |  |  |  |
| mould_B3_base | world | box p=(330,293,240) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_B3_rim_L | world | box p=(330,293,248) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_B3_rim_R | world | box p=(385,293,248) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_B3_rim_Fa | world | box p=(335,293,248) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_B3_rim_Fb | world | box p=(372,293,248) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_B3_rim_B | world | box p=(335,352,248) s=(50,5,12) | #aeb4b8 |  |  |  |
| wp_B3_body | world | cyl p=(360,325,248) axis=z L=16 D=45 | #F4F2EC |  |  |  |
| wp_B3_lid | world | cyl p=(360,325,264) axis=z L=4 D=45 | #F4F2EC |  |  |  |
| mould_B4_base | world | box p=(450,293,240) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_B4_rim_L | world | box p=(450,293,248) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_B4_rim_R | world | box p=(505,293,248) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_B4_rim_Fa | world | box p=(455,293,248) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_B4_rim_Fb | world | box p=(492,293,248) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_B4_rim_B | world | box p=(455,352,248) s=(50,5,12) | #aeb4b8 |  |  |  |
| wp_B4_body | world | cyl p=(480,325,248) axis=z L=16 D=45 | #F4F2EC |  |  |  |
| wp_B4_lid | world | cyl p=(480,325,264) axis=z L=4 D=45 | #F4F2EC |  |  |  |
| mould_C1_base | world | box p=(90,293,360) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_C1_rim_L | world | box p=(90,293,368) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_C1_rim_R | world | box p=(145,293,368) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_C1_rim_Fa | world | box p=(95,293,368) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_C1_rim_Fb | world | box p=(132,293,368) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_C1_rim_B | world | box p=(95,352,368) s=(50,5,12) | #aeb4b8 |  |  |  |
| wp_C1_body | world | cyl p=(120,325,368) axis=z L=16 D=45 | #F4F2EC |  |  |  |
| wp_C1_lid | world | cyl p=(120,325,384) axis=z L=4 D=45 | #F4F2EC |  |  |  |
| mould_C2_base | world | box p=(210,293,360) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_C2_rim_L | world | box p=(210,293,368) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_C2_rim_R | world | box p=(265,293,368) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_C2_rim_Fa | world | box p=(215,293,368) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_C2_rim_Fb | world | box p=(252,293,368) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_C2_rim_B | world | box p=(215,352,368) s=(50,5,12) | #aeb4b8 |  |  |  |
| mould_C3_base | world | box p=(330,293,360) s=(60,64,8) | #aeb4b8 |  |  |  |
| mould_C3_rim_L | world | box p=(330,293,368) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_C3_rim_R | world | box p=(385,293,368) s=(5,64,12) | #aeb4b8 |  |  |  |
| mould_C3_rim_Fa | world | box p=(335,293,368) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_C3_rim_Fb | world | box p=(372,293,368) s=(13,5,12) | #aeb4b8 |  |  |  |
| mould_C3_rim_B | world | box p=(335,352,368) s=(50,5,12) | #aeb4b8 |  |  |  |
| rail_block_L | world | box p=(60,180,0) s=(30,60,45) | #cf3a2f |  |  |  |
| rail_block_R | world | box p=(780,180,0) s=(30,60,45) | #cf3a2f |  |  |  |
| guide_rod | world | cyl p=(60,195,30) axis=x L=750 D=8 | #aeb4b8 |  |  |  |
| travel_spindle | world | cyl p=(90,225,30) axis=x L=690 D=12 | #cf3a2f |  | thread:travel |  |
| M2_mount | world | box p=(0,210,0) s=(60,30,15) | #cf3a2f |  |  |  |
| M2_travel_motor | world | box p=(0,210,15) s=(60,30,30) | #e0492f | Q3/Q4 + B1/B2 | motor:travel | encoder_motor |
| M2_coupler | world | cyl p=(60,225,30) axis=x L=14 D=16 | #aeb4b8 |  | spin:travel |  |
| I1_post | world | box p=(700,250,0) s=(30,15,20) | #cf3a2f |  |  |  |
| I1_ref_horizontal | world | box p=(700,250,20) s=(30,15,7.5) | #1b8f52 | I1 |  | mini_switch |
| cv_leg_L0 | world | box p=(610,290,0) s=(15,15,60) | #cf3a2f |  |  |  |
| cv_leg_L1 | world | box p=(610,595,0) s=(15,15,60) | #cf3a2f |  |  |  |
| cv_side_rail_L | world | box p=(610,290,60) s=(15,320,45) | #2b2b2f |  |  |  |
| cv_leg_R0 | world | box p=(705,290,0) s=(15,15,60) | #cf3a2f |  |  |  |
| cv_leg_R1 | world | box p=(705,595,0) s=(15,15,60) | #cf3a2f |  |  |  |
| cv_side_rail_R | world | box p=(705,290,60) s=(15,320,45) | #2b2b2f |  |  |  |
| cv_belt_L | world | box p=(625,295,96) s=(20,310,4) | #474b52 |  | belt |  |
| cv_belt_R | world | box p=(685,295,96) s=(20,310,4) | #474b52 |  | belt |  |
| cv_drum_out_L | world | cyl p=(610,300,90) axis=x L=35 D=20 | #2b2b2f |  | pulley |  |
| cv_drum_out_R | world | cyl p=(685,300,90) axis=x L=35 D=20 | #2b2b2f |  | pulley |  |
| cv_drum_in_L | world | cyl p=(610,600,90) axis=x L=35 D=20 | #2b2b2f |  | pulley |  |
| cv_drum_in_R | world | cyl p=(685,600,90) axis=x L=35 D=20 | #2b2b2f |  | pulley |  |
| M1_belt_mount | world | box p=(630,550,0) s=(60,30,25) | #cf3a2f |  |  |  |
| M1_belt_motor | world | box p=(630,550,25) s=(60,30,30) | #e0492f | Q1/Q2 | motor:belt | s_motor |
| M1_shaft | world | cyl p=(690,565,40) axis=x L=40 D=8 | #aeb4b8 |  | spin:belt_x |  |
| M1_drive_pulley | world | cyl p=(720,565,40) axis=x L=10 D=26 | #2b2b2f |  | spin:belt_x |  |
| M1_drum_pulley | world | cyl p=(720,600,90) axis=x L=10 D=26 | #2b2b2f |  | spin:belt_x |  |
| M1_drive_belt | world | box p=(721,550,25) s=(8,65,80) | #474b52 |  | belt:loop |  |
| cover_pillar_1 | world | box p=(610,340,105) s=(15,15,105) | #cf3a2f |  |  |  |
| cover_pillar_2 | world | box p=(610,525,105) s=(15,15,105) | #cf3a2f |  |  |  |
| cover_pillar_3 | world | box p=(705,340,105) s=(15,15,105) | #cf3a2f |  |  |  |
| cover_pillar_4 | world | box p=(705,525,105) s=(15,15,105) | #cf3a2f |  |  |  |
| cover_roof | world | box p=(605,330,210) s=(120,220,12) | #2b2b2f |  |  |  |
| CS1_colour_front_L | world | box p=(625,357,195) s=(30,15,15) | #1b8f52 | AUX1 |  | colour_sensor |
| CS2_colour_front_R | world | box p=(675,357,195) s=(30,15,15) | #1b8f52 | AUX2 |  | colour_sensor |
| LB1_pos_back_L | world | box p=(625,508,195) s=(30,15,15) | #1b8f52 | AUX3 |  | phototransistor |
| LB2_pos_back_R | world | box p=(675,508,195) s=(30,15,15) | #1b8f52 | AUX4 |  | phototransistor |
| I2_lightbarrier_inner_rx | world | box p=(617.5,317,105) s=(7.5,15,15) | #1b8f52 | I2 | beam:rx | phototransistor |
| I2_lightbarrier_inner_tx | world | box p=(705,317,105) s=(7.5,15,15) | #e0a02a | I2 | beam:tx |  |
| I3_lightbarrier_outer_rx | world | box p=(617.5,572,105) s=(7.5,15,15) | #1b8f52 | I3 | beam:rx | phototransistor |
| I3_lightbarrier_outer_tx | world | box p=(705,572,105) s=(7.5,15,15) | #e0a02a | I3 | beam:tx |  |
| A1_trail_lower | world | box p=(617.5,370,105) s=(7.5,15,15) | #1b8f52 | A1 |  | ir_track_sensor |
| A2_trail_upper | world | box p=(617.5,370,120) s=(7.5,15,15) | #1b8f52 | A2 |  | ir_track_sensor |
| adapter_pcb_24V | world | box p=(230,20,0) s=(160,100,22) | #1b8f52 |  |  |  |
| terminal_block | world | box p=(150,20,0) s=(60,30,25) | #8b9196 |  |  |  |
| travel_carriage | travel | box p=(-25,165,10) s=(50,90,40) | #cf3a2f |  |  |  |
| mast_outrigger | travel | box p=(-50,185,50) s=(100,50,10) | #cf3a2f |  |  |  |
| mast_tube_1 | travel | cyl p=(-45,190,60) axis=z L=410 D=10 | #d6d9da |  |  |  |
| mast_tube_2 | travel | cyl p=(45,190,60) axis=z L=410 D=10 | #d6d9da |  |  |  |
| mast_tube_3 | travel | cyl p=(-45,230,60) axis=z L=410 D=10 | #d6d9da |  |  |  |
| mast_tube_4 | travel | cyl p=(45,230,60) axis=z L=410 D=10 | #d6d9da |  |  |  |
| mast_top_plate | travel | box p=(-60,170,470) s=(120,80,15) | #2b2b2f |  |  |  |
| lift_spindle | travel | cyl p=(-45,210,60) axis=z L=410 D=12 | #cf3a2f |  | thread:lift |  |
| M3_lift_motor | travel | box p=(-60,195,485) s=(30,30,60) | #e0492f | Q5/Q6 + B3/B4 | motor:lift | encoder_motor |
| M3_coupler | travel | cyl p=(-45,210,471) axis=z L=14 D=16 | #aeb4b8 |  | spin:lift |  |
| I4_ref_vertical | travel | box p=(-60,172,485) s=(30,15,7.5) | #1b8f52 | I4 |  | mini_switch |
| lift_carriage_L | lift | box p=(-50,175,0) s=(16,70,60) | #2b2b2f |  |  |  |
| lift_carriage_R | lift | box p=(34,175,0) s=(16,70,60) | #2b2b2f |  |  |  |
| lift_carriage_yoke | lift | box p=(-50,175,45) s=(100,70,15) | #2b2b2f |  |  |  |
| fork_yoke | lift | box p=(-50,185,-20) s=(100,50,20) | #cf3a2f |  |  |  |
| ausleger_stage1 | lift | box p=(-14,130,-20) s=(28,160,20) | #2b2b2f |  |  |  |
| M4_fork_motor | lift | box p=(-15,70,-25) s=(30,60,30) | #e0492f | Q7/Q8 | motor:fork | s_motor |
| ausleger_spindle | lift | cyl p=(0,70,-10) axis=y L=220 D=8 | #aeb4b8 |  | thread:fork |  |
| ausleger_bearing_B | lift | box p=(-9,130,-16) s=(18,12,12) | #cf3a2f |  |  |  |
| ausleger_bearing_F | lift | box p=(-9,278,-16) s=(18,12,12) | #cf3a2f |  |  |  |
| I6_ref_ausleger_back | lift | box p=(14,136,-20) s=(7.5,30,15) | #1b8f52 | I6 |  | mini_switch |
| I5_ref_ausleger_front | lift | box p=(14,254,-20) s=(7.5,30,15) | #1b8f52 | I5 |  | mini_switch |
| ausleger_stage2 | fork | box p=(-10,150,-16) s=(20,140,12) | #d6d9da |  |  |  |
| fork_table | fork | box p=(-16,175,-4) s=(32,70,14) | #cf3a2f |  |  |  |

### VGR

| part | frame | geometry | colour | I/O | mech | component |
|---|---|---|---|---|---|---|
| drehkranz_base | world | cyl p=(180,200,0) axis=z L=14 D=160 | #2b2b2f |  |  |  |
| drehkranz_ring | swivel | cyl p=(180,200,14) axis=z L=12 D=180 | #cf3a2f |  | spin:swivel |  |
| turntable_disc | swivel | cyl p=(180,200,26) axis=z L=12 D=180 | #2b2b2f |  |  |  |
| M3_mount | world | box p=(5,185,0) s=(60,30,14) | #cf3a2f |  |  |  |
| M3_swivel_motor | world | box p=(5,185,14) s=(60,30,30) | #e0492f | Q5/Q6 + B5/B6 | motor:swivel | encoder_motor |
| M3_pinion | world | cyl p=(50,200,14) axis=z L=12 D=90 | #2b2b2f |  | spin:swivel |  |
| I3_ref_swivel | world | box p=(165,6,0) s=(30,15,7.5) | #1b8f52 | I3 |  | mini_switch |
| tower_column_1 | swivel | box p=(122.5,177.5,38) s=(15,15,562) | #d6d9da |  | profile:15 |  |
| tower_column_2 | swivel | box p=(222.5,177.5,38) s=(15,15,562) | #d6d9da |  | profile:15 |  |
| tower_column_3 | swivel | box p=(122.5,207.5,38) s=(15,15,562) | #d6d9da |  | profile:15 |  |
| tower_column_4 | swivel | box p=(222.5,207.5,38) s=(15,15,562) | #d6d9da |  | profile:15 |  |
| tower_top_plate | swivel | box p=(110,175,600) s=(140,50,14) | #2b2b2f |  |  |  |
| plunge_spindle | swivel | cyl p=(205,200,38) axis=z L=562 D=12 | #cf3a2f |  | thread:plunge |  |
| M1_plunge_motor | swivel | box p=(190,185,614) s=(30,30,60) | #e0492f | Q1/Q2 + B1/B2 | motor:plunge | encoder_motor |
| I1_ref_plunge | swivel | box p=(110,177,614) s=(30,15,7.5) | #1b8f52 | I1 |  | mini_switch |
| plunge_carriage | plunge | box p=(110,173,250) s=(140,54,46) | #2b2b2f |  |  |  |
| plunge_nut | plunge | box p=(195,190,296) s=(20,20,10) | #e0a02a |  |  |  |
| reach_nut | plunge | box p=(146,161,259) s=(17,12,20) | #e0a02a |  |  |  |
| I2_ref_reach | plunge | box p=(185,169,296) s=(30,15,7.5) | #1b8f52 | I2 |  | mini_switch |
| arm_rail_L | reach | box p=(165,64,263) s=(12,612,12) | #d6d9da |  | profile:12 |  |
| arm_rail_R | reach | box p=(183,64,263) s=(12,612,12) | #d6d9da |  | profile:12 |  |
| arm_end_F | reach | box p=(165,50,256) s=(30,14,26) | #cf3a2f |  |  |  |
| arm_end_B | reach | box p=(165,676,256) s=(30,14,26) | #cf3a2f |  |  |  |
| reach_bearing_F | reach | box p=(148,54,261) s=(17,10,16) | #cf3a2f |  |  |  |
| reach_bearing_B | reach | box p=(148,676,261) s=(17,10,16) | #cf3a2f |  |  |  |
| reach_spindle | reach | cyl p=(156,54,269) axis=y L=636 D=10 | #aeb4b8 |  | thread:reach |  |
| M2_reach_motor | reach | box p=(141,690,254) s=(30,60,30) | #e0492f | Q3/Q4 + B3/B4 | motor:reach | encoder_motor |
| suction_head | reach | box p=(162,14,256) s=(36,36,32) | #cf3a2f |  |  |  |
| suction_stem | reach | cyl p=(180,32,234) axis=z L=22 D=18 | #aeb4b8 |  | spring |  |
| suction_cup | reach | cyl p=(180,32,222) axis=z L=14 D=40 | #2b2b2f | Q8 |  |  |
| compressor | world | box p=(10,400,0) s=(66,30,30) | #1f63c4 | Q7 |  | compressor |
| vacuum_valve | world | box p=(85,407,0) s=(40,15,33) | #1f63c4 | Q8 |  | solenoid_valve |
| vgr_pcb | world | box p=(100,440,0) s=(160,100,22) | #1b8f52 |  |  |  |

### Oven

| part | frame | geometry | colour | I/O | mech | component |
|---|---|---|---|---|---|---|
| oven_pedestal | world | box p=(60,10,0) s=(280,180,30) | #2b2b2f |  |  |  |
| oven_floor | world | box p=(60,10,30) s=(280,180,10) | #e0492f |  |  |  |
| oven_wall_back | world | box p=(60,10,40) s=(10,180,180) | #e0492f |  |  |  |
| oven_wall_L | world | box p=(70,10,40) s=(270,10,180) | #e0492f |  |  |  |
| oven_wall_R | world | box p=(70,180,40) s=(270,10,180) | #e0492f |  |  |  |
| oven_front_lintel | world | box p=(330,20,160) s=(10,160,60) | #e0492f |  |  |  |
| oven_roof | world | box p=(60,10,220) s=(280,180,12) | #2b2b2f |  |  |  |
| Q9_oven_lamp | world | box p=(300,150,232) s=(20,20,12) | #e0a02a | Q9 |  |  |
| door_guide_L | world | box p=(340,12,0) s=(8,8,300) | #2b2b2f |  |  |  |
| door_guide_R | world | box p=(340,180,0) s=(8,8,300) | #2b2b2f |  |  |  |
| door_gantry | world | box p=(336,12,300) s=(16,176,5) | #2b2b2f |  |  |  |
| Q13_door_cylinder | world | box p=(334,92.5,305) s=(20,15,69) | #aeb4b8 | Q13 | pneumatic | pneumatic_cylinder |
| Q13_oven_door | door | box p=(340,20,170) s=(8,160,110) | #e0492f | Q13 | pneumatic |  |
| door_rod | door | cyl p=(344,100,275) axis=z L=170 D=8 | #aeb4b8 |  |  |  |
| slider_rail | world | box p=(70,95,40) s=(422,10,10) | #aeb4b8 |  |  |  |
| slider_leg | world | box p=(477,95,0) s=(15,10,40) | #2b2b2f |  |  |  |
| M4_slider_motor | world | box p=(10,62.5,0) s=(40,75,30) | #2b2b2f | Q5/Q6 | motor:slider | s_motor |
| I6_ref_slider_in | world | box p=(240,112,40) s=(30,15,7.5) | #1b8f52 | I6 |  | mini_switch |
| I7_ref_slider_out | world | box p=(440,105,40) s=(30,15,7.5) | #1b8f52 | I7 |  | mini_switch |
| ofenschieber_tray | slider | box p=(435,70,50) s=(50,60,10) | #e0492f |  |  |  |
| I9_post_rx | world | box p=(452,21,0) s=(15,7.5,62) | #2b2b2f |  |  |  |
| I9_lightbarrier_rx | world | box p=(452,21,62) s=(15,7.5,15) | #1b8f52 | I9 |  | phototransistor |
| I9_post_tx | world | box p=(452,172,0) s=(15,7.5,62) | #2b2b2f |  |  |  |
| I9_lightbarrier_tx | world | box p=(452,172,62) s=(15,7.5,15) | #e0a02a | I9 |  |  |
| sauger_column | world | box p=(360,0,0) s=(15,15,185) | #e0492f |  |  |  |
| sauger_post_far | world | box p=(345,340,0) s=(15,15,185) | #e0492f |  |  |  |
| sauger_rail | world | box p=(360,0,170) s=(15,372,15) | #2b2b2f |  |  |  |
| M5_sauger_motor | world | box p=(240,30,232) s=(40,75,30) | #2b2b2f | Q7/Q8 | motor:sauger | s_motor |
| I8_ref_sauger_oven | world | box p=(360,85,185) s=(15,30,7.5) | #1b8f52 | I8 |  | mini_switch |
| I5_ref_sauger_turntable | world | box p=(360,320,185) s=(15,30,7.5) | #1b8f52 | I5 |  | mini_switch |
| sauger_carriage | sauger | box p=(361,320,150) s=(119,30,20) | #e0492f |  |  |  |
| Q12_lower_cylinder | sauger | cyl p=(460,335,142) axis=z L=58 D=20 | #aeb4b8 | Q12 | pneumatic | pneumatic_cylinder |
| Q12_piston_rod | lower | cyl p=(460,335,142) axis=z L=50 D=8 | #aeb4b8 |  |  |  |
| Q11_suction_cup | lower | cyl p=(460,335,130) axis=z L=12 D=30 | #2b2b2f | Q11 |  |  |
| drehtisch_base | world | cyl p=(460,400,0) axis=z L=48 D=150 | #2b2b2f |  |  |  |
| drehtisch_disc | turn | cyl p=(460,400,48) axis=z L=12 D=200 | #e0492f |  | spin:turn |  |
| drehtisch_nest | turn | cyl p=(460,335,59.5) axis=z L=0.5 D=51 | #2b2b2f |  |  |  |
| M1_turntable_motor | world | box p=(575,362.5,0) s=(40,75,30) | #2b2b2f | Q1/Q2 | motor:turn | s_motor |
| I1_ref_turn_sauger | world | box p=(500,297.237,0) s=(30,15,7.5) | #1b8f52 | I1 |  | mini_switch |
| I4_ref_turn_saege | world | box p=(342.5,385,0) s=(15,30,7.5) | #1b8f52 | I4 |  | mini_switch |
| I2_ref_turn_band | world | box p=(522.782,470.282,0) s=(30,15,7.5) | #1b8f52 | I2 |  | mini_switch |
| saw_column | world | box p=(290,355,0) s=(20,68,200) | #2b2b2f |  |  |  |
| saw_arm | world | box p=(310,388,190) s=(100,25,10) | #2b2b2f |  |  |  |
| M3_saw_motor | world | box p=(350,380,200) s=(75,40,30) | #2b2b2f | Q4 | motor:saw | s_motor |
| saw_spindle | world | cyl p=(395,400,90) axis=z L=100 D=8 | #aeb4b8 |  |  |  |
| saw_blade | world | cyl p=(395,400,86) axis=z L=4 D=30 | #aeb4b8 |  | spin:saw |  |
| pusher_beam | world | box p=(310,360,104) s=(158,10,8) | #2b2b2f |  |  |  |
| Q14_pusher_cylinder | world | box p=(452.5,358,84) s=(15,69,20) | #aeb4b8 | Q14 | pneumatic | pneumatic_cylinder |
| pusher_rod | push | cyl p=(460,401,91.5) axis=y L=30 D=8 | #aeb4b8 |  |  |  |
| pusher_paddle | push | box p=(450,429,64) s=(20,6,34) | #e0492f |  |  |  |
| belt_leg_L0 | world | box p=(427,502,0) s=(8,8,30) | #2b2b2f |  |  |  |
| belt_leg_L1 | world | box p=(427,744,0) s=(8,8,30) | #2b2b2f |  |  |  |
| belt_rail_L | world | box p=(427,502,30) s=(8,250,30) | #2b2b2f |  |  |  |
| belt_nose_L | world | box p=(427,752,50) s=(8,40,10) | #2b2b2f |  |  |  |
| belt_leg_R0 | world | box p=(485,502,0) s=(8,8,30) | #2b2b2f |  |  |  |
| belt_leg_R1 | world | box p=(485,744,0) s=(8,8,30) | #2b2b2f |  |  |  |
| belt_rail_R | world | box p=(485,502,30) s=(8,250,30) | #2b2b2f |  |  |  |
| belt_nose_R | world | box p=(485,752,50) s=(8,40,10) | #2b2b2f |  |  |  |
| belt_web | world | box p=(435,502,56) s=(50,290,4) | #474b52 |  | belt |  |
| belt_drum_in | world | cyl p=(435,512,46) axis=x L=50 D=20 | #2b2b2f |  | pulley |  |
| belt_drum_out | world | cyl p=(435,742,46) axis=x L=50 D=20 | #2b2b2f |  | pulley |  |
| belt_nose_roller | world | cyl p=(435,788.5,52.5) axis=x L=50 D=7 | #aeb4b8 |  | pulley |  |
| M2_mount | world | box p=(493,677,0) s=(40,75,20) | #2b2b2f |  |  |  |
| M2_belt_motor | world | box p=(493,677,20) s=(40,75,30) | #2b2b2f | Q3 | motor:belt | s_motor |
| I3_lightbarrier_rx | world | box p=(427.5,727,60) s=(7.5,15,15) | #1b8f52 | I3 |  | phototransistor |
| I3_lightbarrier_tx | world | box p=(485,727,60) s=(7.5,15,15) | #e0a02a | I3 |  |  |
| Q10_compressor | world | box p=(580,20,0) s=(66,30,30) | #1f63c4 | Q10 |  | compressor |
| V1_valve_vakuum | world | box p=(600,70,0) s=(40,15,33) | #1f63c4 |  |  | solenoid_valve |
| V2_valve_senken | world | box p=(600,92,0) s=(40,15,33) | #1f63c4 |  |  | solenoid_valve |
| V3_valve_ofentuer | world | box p=(600,114,0) s=(40,15,33) | #1f63c4 |  |  | solenoid_valve |
| V4_valve_schieber | world | box p=(600,136,0) s=(40,15,33) | #1f63c4 |  |  | solenoid_valve |
| vacuum_cylinder_a | world | box p=(520,70,0) s=(69,15,20) | #aeb4b8 |  | pneumatic | pneumatic_cylinder |
| vacuum_cylinder_b | world | box p=(520,92,0) s=(69,15,20) | #aeb4b8 |  | pneumatic | pneumatic_cylinder |
| oven_pcb | world | box p=(540,540,0) s=(100,160,22) | #1b8f52 |  |  |  |

### Sorting

| part | frame | geometry | colour | I/O | mech | component |
|---|---|---|---|---|---|---|
| belt_leg_F0 | world | box p=(16,200,0) s=(10,10,15) | #cf3a2f |  |  |  |
| belt_leg_F1 | world | box p=(830,200,0) s=(10,10,15) | #cf3a2f |  |  |  |
| belt_rail_F | world | box p=(16,200,15) s=(824,10,30) | #2b2b2f |  |  |  |
| belt_leg_B0 | world | box p=(16,250,0) s=(10,10,15) | #cf3a2f |  |  |  |
| belt_leg_B1 | world | box p=(830,250,0) s=(10,10,15) | #cf3a2f |  |  |  |
| belt_rail_B | world | box p=(16,250,15) s=(824,10,30) | #2b2b2f |  |  |  |
| belt_web | world | box p=(16,210,41) s=(824,40,4) | #474b52 |  | belt |  |
| belt_drum_in | world | cyl p=(31,200,35) axis=y L=60 D=20 | #2b2b2f |  | pulley |  |
| belt_drum_out | world | cyl p=(825,200,35) axis=y L=60 D=20 | #2b2b2f |  | pulley |  |
| Q1_mount | world | box p=(848,200,0) s=(75,40,15) | #cf3a2f |  |  |  |
| Q1_belt_motor | world | box p=(848,200,15) s=(75,40,30) | #2b2b2f | Q1 | motor:belt | s_motor |
| I1_impulstaster | world | box p=(820,260,15) s=(30,15,7.5) | #1b8f52 | I1 |  | mini_switch |
| I2_inlet_rx | world | box p=(140,202.5,45) s=(15,7.5,15) | #1b8f52 | I2 |  | phototransistor |
| I2_inlet_tx | world | box p=(140,250,45) s=(15,7.5,15) | #e0a02a | I2 |  |  |
| I3_after_colour_rx | world | box p=(340,202.5,45) s=(15,7.5,15) | #1b8f52 | I3 |  | phototransistor |
| I3_after_colour_tx | world | box p=(340,250,45) s=(15,7.5,15) | #e0a02a | I3 |  |  |
| colour_hood_F | world | box p=(180,188,0) s=(120,10,130) | #e0492f |  |  |  |
| colour_hood_B | world | box p=(180,262,0) s=(120,10,130) | #e0492f |  |  |  |
| colour_hood_roof | world | box p=(180,188,130) s=(120,84,10) | #e0492f |  |  |  |
| colour_arm | world | box p=(235,225,105) s=(10,10,25) | #2b2b2f |  |  |  |
| A4_colour_sensor | world | box p=(225,222.5,90) s=(30,15,15) | #1b8f52 | A4 |  | colour_sensor |
| Q3_stand_weiss | world | box p=(445,265,0) s=(30,69,45) | #cf3a2f |  |  |  |
| Q3_cylinder_weiss | world | box p=(452.5,265,45) s=(15,69,20) | #8b9196 | Q3 | pneumatic | pneumatic_cylinder |
| pusher_weiss | push0 | box p=(440,255,45) s=(40,10,26) | #e0492f |  |  |  |
| bay_weiss_pedestal | world | box p=(415,35,0) s=(90,150,37) | #cf3a2f |  |  |  |
| bay_weiss_floor | world | box p=(410,30,37) s=(100,160,8) | #2b2b2f |  |  |  |
| bay_weiss_wall_B | world | box p=(410,30,45) s=(100,8,25) | #2b2b2f |  |  |  |
| bay_weiss_wall_L | world | box p=(410,38,45) s=(8,152,25) | #2b2b2f |  |  |  |
| bay_weiss_wall_R | world | box p=(502,38,45) s=(8,152,25) | #2b2b2f |  |  |  |
| I5_bay_weiss_rx | world | box p=(418,60,45) s=(7.5,15,15) | #1b8f52 | I5 |  | phototransistor |
| I5_bay_weiss_tx | world | box p=(494.5,60,45) s=(7.5,15,15) | #e0a02a | I5 |  |  |
| wp_weiss_body | world | cyl p=(460,67,45) axis=z L=16 D=45 | #f2f0ea |  |  |  |
| wp_weiss_lid | world | cyl p=(460,67,61) axis=z L=4 D=45 | #EDE7D6 |  |  |  |
| Q4_stand_rot | world | box p=(585,265,0) s=(30,69,45) | #cf3a2f |  |  |  |
| Q4_cylinder_rot | world | box p=(592.5,265,45) s=(15,69,20) | #8b9196 | Q4 | pneumatic | pneumatic_cylinder |
| pusher_rot | push1 | box p=(580,255,45) s=(40,10,26) | #e0492f |  |  |  |
| bay_rot_pedestal | world | box p=(555,35,0) s=(90,150,37) | #cf3a2f |  |  |  |
| bay_rot_floor | world | box p=(550,30,37) s=(100,160,8) | #2b2b2f |  |  |  |
| bay_rot_wall_B | world | box p=(550,30,45) s=(100,8,25) | #2b2b2f |  |  |  |
| bay_rot_wall_L | world | box p=(550,38,45) s=(8,152,25) | #2b2b2f |  |  |  |
| bay_rot_wall_R | world | box p=(642,38,45) s=(8,152,25) | #2b2b2f |  |  |  |
| I6_bay_rot_rx | world | box p=(558,60,45) s=(7.5,15,15) | #1b8f52 | I6 |  | phototransistor |
| I6_bay_rot_tx | world | box p=(634.5,60,45) s=(7.5,15,15) | #e0a02a | I6 |  |  |
| wp_rot_body | world | cyl p=(600,67,45) axis=z L=16 D=45 | #f2f0ea |  |  |  |
| wp_rot_lid | world | cyl p=(600,67,61) axis=z L=4 D=45 | #D9536F |  |  |  |
| Q5_stand_blau | world | box p=(725,265,0) s=(30,69,45) | #cf3a2f |  |  |  |
| Q5_cylinder_blau | world | box p=(732.5,265,45) s=(15,69,20) | #8b9196 | Q5 | pneumatic | pneumatic_cylinder |
| pusher_blau | push2 | box p=(720,255,45) s=(40,10,26) | #e0492f |  |  |  |
| bay_blau_pedestal | world | box p=(695,35,0) s=(90,150,37) | #cf3a2f |  |  |  |
| bay_blau_floor | world | box p=(690,30,37) s=(100,160,8) | #2b2b2f |  |  |  |
| bay_blau_wall_B | world | box p=(690,30,45) s=(100,8,25) | #2b2b2f |  |  |  |
| bay_blau_wall_L | world | box p=(690,38,45) s=(8,152,25) | #2b2b2f |  |  |  |
| bay_blau_wall_R | world | box p=(782,38,45) s=(8,152,25) | #2b2b2f |  |  |  |
| I7_bay_blau_rx | world | box p=(698,60,45) s=(7.5,15,15) | #1b8f52 | I7 |  | phototransistor |
| I7_bay_blau_tx | world | box p=(774.5,60,45) s=(7.5,15,15) | #e0a02a | I7 |  |  |
| wp_blau_body | world | cyl p=(740,67,45) axis=z L=16 D=45 | #f2f0ea |  |  |  |
| wp_blau_lid | world | cyl p=(740,67,61) axis=z L=4 D=45 | #4A2C17 |  |  |  |
| Q2_compressor | world | box p=(900,330,0) s=(66,30,30) | #1f63c4 | Q2 |  | compressor |
| valve_weiss | world | box p=(880,380,0) s=(40,15,33) | #1f63c4 |  |  | solenoid_valve |
| valve_rot | world | box p=(880,402,0) s=(40,15,33) | #1f63c4 |  |  | solenoid_valve |
| valve_blau | world | box p=(880,424,0) s=(40,15,33) | #1f63c4 |  |  | solenoid_valve |
| sorting_pcb | world | box p=(40,500,0) s=(160,100,22) | #1b8f52 |  |  |  |

### PLC

| part | frame | geometry | colour | I/O | mech | component |
|---|---|---|---|---|---|---|
| din_rail | world | box p=(102.5,25,0) s=(35,330,7.5) | #aeb4b8 |  |  |  |
| psu_wdr120 | world | box p=(57.4,35,7.5) s=(125.2,40,113.5) | #8b9196 |  |  |  |
| revpi_core_3 | world | box p=(72,80,7.5) s=(96,22.5,110.5) | #dcdedd |  |  |  |
| revpi_dio_1 | world | box p=(72,103,7.5) s=(96,22.5,110.5) | #dcdedd |  |  |  |
| revpi_dio_2 | world | box p=(72,126,7.5) s=(96,22.5,110.5) | #dcdedd |  |  |  |
| revpi_dio_3 | world | box p=(72,149,7.5) s=(96,22.5,110.5) | #dcdedd |  |  |  |
| revpi_aio | world | box p=(72,172,7.5) s=(96,22.5,110.5) | #dcdedd |  |  |  |
| terminal_1 | world | box p=(90,203,7.5) s=(60,6.2,45) | #1f63c4 |  |  |  |
| terminal_2 | world | box p=(90,209.2,7.5) s=(60,6.2,45) | #8b9196 |  |  |  |
| terminal_3 | world | box p=(90,215.4,7.5) s=(60,6.2,45) | #8b9196 |  |  |  |
| terminal_4 | world | box p=(90,221.6,7.5) s=(60,6.2,45) | #1f63c4 |  |  |  |
| terminal_5 | world | box p=(90,227.8,7.5) s=(60,6.2,45) | #8b9196 |  |  |  |
| terminal_6 | world | box p=(90,234,7.5) s=(60,6.2,45) | #8b9196 |  |  |  |
| terminal_7 | world | box p=(90,240.2,7.5) s=(60,6.2,45) | #1f63c4 |  |  |  |
| terminal_8 | world | box p=(90,246.4,7.5) s=(60,6.2,45) | #8b9196 |  |  |  |
| terminal_9 | world | box p=(90,252.6,7.5) s=(60,6.2,45) | #8b9196 |  |  |  |
| terminal_10 | world | box p=(90,258.8,7.5) s=(60,6.2,45) | #1f63c4 |  |  |  |
| terminal_11 | world | box p=(90,265,7.5) s=(60,6.2,45) | #8b9196 |  |  |  |
| terminal_12 | world | box p=(90,271.2,7.5) s=(60,6.2,45) | #8b9196 |  |  |  |
| cable_duct | world | box p=(220,25,0) s=(40,330,60) | #8b9196 |  |  |  |

## 10. Acceptance tests - build these into the app (a "Self-test" button) and make them pass

1. Mirror test: det(stage matrix) = +1; the HBW is at the BACK-RIGHT and the sorting line FRONT-LEFT seen from
   the front (camera at negative factory x looking +x).
2. Frame test: at HOME, the HBW part `travel_carriage` world box equals module box shifted by (665,0,0) and
   rotated into the factory rect [1218.0, 150.0, 640.0, 860.0].
3. Station test: set VGR swivel=69.013, reach=236.857: the cup centre (factory) = [1278.0, 815.0] +/- 0.1 mm.
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

