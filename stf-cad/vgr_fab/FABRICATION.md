# VGR fabrication dossier — vacuum gripper robot (Upgrade 12 geometry)

**Source of truth:** every dimension in this dossier and in `vgr_fab.blend` / `vgr_fab.glb`
is parsed programmatically from `../hbw/vgr_model.py` (the project's proven parametric
model). Nothing was re-measured by hand, so the fabricated part is identical to the
model the collision, swept-path and tolerance proofs were run against. Pose shown:
swivel 0°, plunge 320 mm, reach 150 mm.

**Design intent:** a light cylindrical (R-P-P) pick-and-place arm carrying a 45 mm
cookie (≈ 20 g workpiece, ~1.5 kg moving mass incl. motors) over a 568 mm max cup
radius at up to ~0.5 m/s. Precision target: **±0.1 mm repeatability at the cup**.

---

## 1. Material selection (industry best for this duty)

| Part | Material | Why this is the industry choice |
|---|---|---|
| Arm rails, end blocks, suction head, tower plates | **EN AW-6082-T6** (AlMgSi1) | The standard structural aluminium for machined robot arms. Rp0.2 ≈ 260 MPa, excellent machinability, **weldable** (TIG/MIG, filler ER5356) and anodizeable. 7075-T6 is stronger but unweldable and stress-corrosion sensitive — disqualified because the end-block joints are welded/doweled. |
| Drehkranz gear ring, both spindles | **C45 (1.0503)**, Q&T | Cheap, hardenable (ring teeth induction-hardened to 45 HRC), excellent for rolled trapezoidal threads (Tr12×4 / Tr10×4). |
| Suction stem, fasteners, spring | **1.4305 / 1.4310 stainless** | Stem sees constant sliding + food proximity; spring 1.4310 (high tensile, corrosion resistant). |
| Spindle nuts | **CuZn39Pb3 brass** | Standard screw-nut material: low friction, no galling against steel threads, good for the 0.05 mm thread clearance the model's guides table requires. |
| Suction cup | **NBR, 60 Shore A, FDA 21 CFR 177.2600** | The industrial default for food-adjacent vacuum handling; (EC) 1935/2004 compliant. Silicone is the alternative where temperatures rise. |
| Welds (aluminium) | **ER5356 filler, GTAW (TIG)** | Standard for 6xxx-series structural aluminium; gives the best fillet cosmetics and ISO 5817-C quality with TIG. |

## 2. Weld map

| Weld | Joint | Type | Process / filler | Quality level | NDT |
|---|---|---|---|---|---|
| W1 | `drehkranz_base` → machine plate | circumferential fillet, a = 4 mm | GTAW / ER5356 | ISO 5817-C | 100 % VT, PT on start/stop |
| W2 | `turntable_disc` → gear ring | circumferential fillet, a = 3 mm | GTAW / ER5356 | ISO 5817-C | 100 % VT |
| W3–W6 | `tower_top_plate` → column tops (4×) | fillet pads, a = 3 mm | GTAW / ER5356 | ISO 5817-C | VT |

**Welding sequence (this is what delivers 0.1 mm after welding):**

1. Machine all weld prep to saw + mill quality; deburr; acetone clean (aluminium).
2. Tack at 4 points, alternate-opposite order; check squareness ≤ 0.3 mm.
3. Weld W3–W6 with back-step technique, 30 % duty cycle to hold interpass < 100 °C.
4. **Stress-relieve the turntable + top-plate assemblies** (2 h at 170 °C, furnace) before any finish machining — without this step, 0.1 mm is not achievable on a welded aluminium assembly.
5. Finish-machine all datums in ONE setup per assembly (see §3).

## 3. Tolerance scheme (ISO 1101 / ISO 286)

| Feature | Requirement | Achieved by |
|---|---|---|
| Tower guide faces (4 columns) | flatness 0.03 mm; parallelism **0.05 mm over 560 mm** | clamp 4 profiles in one vice setup, gang-mill the guide faces after assembly+weld |
| Carriage guide pockets (6) | width +0.05/+0.15 mm (running clearance 0.3 per model GUIDES table) | single-setup boring |
| Plunge / reach spindle bores in carriage | **Ø13 H7 / Ø11 H7** (1.0 mm clearance per model) | bored, single setup |
| Bearing blocks on arm | bore **Ø10 H7**, spindle journals **k6** | line-bore the two blocks mounted on the arm |
| Thread fits (nuts ↔ spindles) | nut 7H, screw 7e (0.05 mm per model guides table) | rolled thread, ground nut tap |
| Top plate bores (spindle, motor pilot) | position 0.1 mm to the guide-face datum | machined after stress relief, one setup |
| End block ↔ rail joints | face flatness 0.02; located by **2× Ø4 dowels ISO 2338 m6** | match-bore after assembly |
| Positioning repeatability at the cup | **±0.1 mm** | stack-up of the above + the twin's 5 ms VGR task |

## 4. Machining & assembly sequence

1. Saw/mill blanks → stress-relieve (T6 stock: 2 h/170 °C after roughing).
2. Machine spindles (turn, roll thread, harden journals if needed, grind k6).
3. Weld W1/W2 (turntable), W3–W6 (top plate); stress-relieve; face flat.
4. Gang-mill tower columns; verify parallelism with a dial sweep (0.05/560).
5. Machine carriage from 6082 plate: pockets + bores in one setup.
6. Machine end blocks, head; press dowels; lap-fit rails to pockets.
7. Turn brass nuts (7H), lap to spindles to 0.05 feeler-free.
8. Assemble: spindles → bearings (light press), nuts → carriage; grease EP2.
9. Bond cup (NBR) to Al retainer with food-grade adhesive; fit stem + 1.4310 spring.
10. Verify: cup runout ≤ 0.1 mm TIR on the spindle axis; plunge/reach full-stroke
    free movement; then virtual-commission against the twin (`sil/` harness).

## 5. Surface treatment & fastening

- 6082 parts: **sulphuric anodize 15 µm** (EN 12373), sealed — except guide faces
  and bores (masked, then oiled).
- C45 ring: zinc-nickel plate + seal; teeth left bare, oiled.
- Stainless: passivate per EN 2516 (citric).
- Fasteners: **M6 ISO 4762, A4-70**, torque 10 Nm with medium threadlocker;
  motor pilots located by Ø10 H7/g6 spigots.

## 6. Files

| File | What |
|---|---|
| `build_vgr_fab.py` | The generator — re-runnable, parses `vgr_model.py`, builds, exports |
| `vgr_fab.blend` | Assembly (57 parts, collections per subassembly, cameras, lights) |
| `vgr_fab.glb` | Web export (49 meshes, 8 materials, metres, Y-up) |
| `parts.json` | Full BOM with per-part material + process |
| `renders/*.png` | Iso / front / side / weld-detail views |
| `preview.html` | three.js viewer: `python3 -m http.server` in this folder, open `preview.html` |

**Known limits (honest):** the model's own `V` dict flags several sizes as *assumed*
(booklet-scale motors, switch sizes); this dossier inherits those. Welding distortion
figures are standard-practice values, not measured. This is a fabrication *package*
for a tabletop-scale cell, not a certified WPS/PQR set — the WPS would need a weld
procedure qualification per EN ISO 15614-2 before production release.

## 7. Bill of materials (generated from parts.json)

| Part | Group | Dimensions (mm) | Material | Process |
|---|---|---|---|---|
| vgr_plate | frame | 495.0 x 740.0 x 10.0 | plate | reference only |
| drehkranz_base | base | 160.0 dia x 14.0 | c45 | CNC turn, bore/face; weld W1 |
| W1_base_to_plate | weld | fillet ring r=78.0 at z=0.5 | weld | GTAW fillet, ISO 5817-C |
| drehkranz_ring | turn | 180.0 dia x 12.0 | c45 | ring gear, teeth m=1.5, hardened 45 HRC |
| turntable_disc | turn | 180.0 dia x 12.0 | alu6082 | laser-cut 6082 plate; weld W2, then face flat |
| W2_disc_to_ring | weld | fillet ring r=88.0 at z=26.0 | weld | GTAW fillet, ISO 5817-C |
| tower_column_1 | tower | 15.0 x 15.0 x 562.0 | alu6082 | EN AW-6082-T6 profile 15x15, guide faces finish-milled post-assembly |
| tower_column_2 | tower | 15.0 x 15.0 x 562.0 | alu6082 | EN AW-6082-T6 profile 15x15, guide faces finish-milled post-assembly |
| tower_column_3 | tower | 15.0 x 15.0 x 562.0 | alu6082 | EN AW-6082-T6 profile 15x15, guide faces finish-milled post-assembly |
| tower_column_4 | tower | 15.0 x 15.0 x 562.0 | alu6082 | EN AW-6082-T6 profile 15x15, guide faces finish-milled post-assembly |
| tower_top_plate | tower | 140.0 x 50.0 x 14.0 | alu6082 | 6082 plate; welds W3..W6 then bored H7 in one setup |
| W3_topplate_col1 | weld | 16.0 x 16.0 x 2.0 | weld | GTAW fillet, ISO 5817-C |
| W4_topplate_col2 | weld | 16.0 x 16.0 x 2.0 | weld | GTAW fillet, ISO 5817-C |
| W5_topplate_col3 | weld | 16.0 x 16.0 x 2.0 | weld | GTAW fillet, ISO 5817-C |
| W6_topplate_col4 | weld | 16.0 x 16.0 x 2.0 | weld | GTAW fillet, ISO 5817-C |
| plunge_spindle | tower | 12.0 dia x 562.0 | c45 | C45, rolled thread Tr12x4-7e, journals k6 |
| plunge_carriage | carriage | 140.0 x 54.0 x 46.0 | alu6082 | 6082 machined from solid; 4 guide pockets + 2 bores, one setup |
| plunge_nut | carriage | 20.0 x 20.0 x 10.0 | brass | CuZn39Pb3 nut, thread Tr12x4-7H |
| reach_nut | carriage | 17.0 x 12.0 x 20.0 | brass | CuZn39Pb3 nut, thread Tr10x4-7H |
| arm_rail_L | arm | 12.0 x 612.0 x 12.0 | alu6082 | 6082 precision profile 12x12, milled on 3 faces |
| arm_rail_R | arm | 12.0 x 612.0 x 12.0 | alu6082 | 6082 precision profile 12x12, milled on 3 faces |
| arm_end_F | arm | 30.0 x 14.0 x 26.0 | alu6082 | machined 6082; doweled + 4x M6 to rails |
| arm_end_B | arm | 30.0 x 14.0 x 26.0 | alu6082 | machined 6082; doweled + 4x M6 to rails |
| reach_bearing_F | arm | 17.0 x 10.0 x 16.0 | alu6082 | bronze-lined bearing block, bore 10 H7 |
| reach_bearing_B | arm | 17.0 x 10.0 x 16.0 | alu6082 | bronze-lined bearing block, bore 10 H7 |
| reach_spindle | arm | 10.0 dia x 636.0 | c45 | C45, rolled thread Tr10x4-7e, journals k6 |
| suction_head | tool | 36.0 x 36.0 x 32.0 | alu6082 | 6082 machined; stem bore H7 |
| suction_stem | tool | 18.0 dia x 22.0 | stainless | 1.4305; spring 1.4310 (6 mm travel) over stem |
| suction_cup | tool | 35.0 dia x 14.0 | nbr | NBR 60 ShA, FDA 21 CFR 177.2600, bonded to Al retainer |
| spring_sleeve | tool | 22.0 dia x 12.0 | stainless | 1.4310 compression spring, 6 mm travel |
| cookie_body | render | 45.0 dia x 16.0 | dough | render aid |
| cookie_top | render | 45.0 dia x 4.0 | dough | render aid |
| B1_M1_motor_head | fastener | 10.0 dia x 6.0 | stainless | ISO 4762 M6x16 head |
| B1_M1_motor_shank | fastener | 6.0 dia x 10.0 | stainless | ISO 4762 M6x16 shank |
| B1_M1_motor | fastener | M6x16 ISO 4762, A4-70 | stainless | torque 10 Nm |
| B2_M1_motor_head | fastener | 10.0 dia x 6.0 | stainless | ISO 4762 M6x16 head |
| B2_M1_motor_shank | fastener | 6.0 dia x 10.0 | stainless | ISO 4762 M6x16 shank |
| B2_M1_motor | fastener | M6x16 ISO 4762, A4-70 | stainless | torque 10 Nm |
| B3_M1_motor_head | fastener | 10.0 dia x 6.0 | stainless | ISO 4762 M6x16 head |
| B3_M1_motor_shank | fastener | 6.0 dia x 10.0 | stainless | ISO 4762 M6x16 shank |
| B3_M1_motor | fastener | M6x16 ISO 4762, A4-70 | stainless | torque 10 Nm |
| B4_M1_motor_head | fastener | 10.0 dia x 6.0 | stainless | ISO 4762 M6x16 head |
| B4_M1_motor_shank | fastener | 6.0 dia x 10.0 | stainless | ISO 4762 M6x16 shank |
| B4_M1_motor | fastener | M6x16 ISO 4762, A4-70 | stainless | torque 10 Nm |
| B5_M2_motor_head | fastener | 10.0 dia x 6.0 | stainless | ISO 4762 M6x16 head |
| B5_M2_motor_shank | fastener | 6.0 dia x 10.0 | stainless | ISO 4762 M6x16 shank |
| B5_M2_motor | fastener | M6x16 ISO 4762, A4-70 | stainless | torque 10 Nm |
| B6_M2_motor_head | fastener | 10.0 dia x 6.0 | stainless | ISO 4762 M6x16 head |
| B6_M2_motor_shank | fastener | 6.0 dia x 10.0 | stainless | ISO 4762 M6x16 shank |
| B6_M2_motor | fastener | M6x16 ISO 4762, A4-70 | stainless | torque 10 Nm |
| B7_M2_motor_head | fastener | 10.0 dia x 6.0 | stainless | ISO 4762 M6x16 head |
| B7_M2_motor_shank | fastener | 6.0 dia x 10.0 | stainless | ISO 4762 M6x16 shank |
| B7_M2_motor | fastener | M6x16 ISO 4762, A4-70 | stainless | torque 10 Nm |
| B8_M2_motor_head | fastener | 10.0 dia x 6.0 | stainless | ISO 4762 M6x16 head |
| B8_M2_motor_shank | fastener | 6.0 dia x 10.0 | stainless | ISO 4762 M6x16 shank |
| B8_M2_motor | fastener | M6x16 ISO 4762, A4-70 | stainless | torque 10 Nm |
| ground | render | 1400.0 x 1600.0 x 1.0 | plate | render |
