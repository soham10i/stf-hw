# STF-2 digital twin - roadmap

Ten phases. Each one follows the repository's rules: it is generated from the model, it ships only when its proof passes,
and it reuses what `main` already built for cell 1. Effort is for one person who knows this code. "Gate" is the
script that must exit 0.

| Phase | Builds | Gate | Effort | Needs |
|---|---|---|---|---|
| DT-1 | Scene export: OpenUSD, USDZ, GLB | `twin/scene_check.py` | **built** (2026-10-06) | - |
| DT-2 | Kinematic playback in the web twin and Blender | `twin/playback_check.py` | **built** (2026-10-06) | DT-1 |
| DT-3a | Live plant core (machine time, events, oven, WebSocket, live viewer) | `twin/plant_check.py` | **built** (2026-10-11) | DT-2 |
| DT-3b | Product flow (line_sim's engine), stocks + AMR, bake logs, the oven under its closed loop | `twin/flow_check.py` | **built** (2026-10-11) | DT-3a |
| DT-4a | PLC in the loop: the generated program compiled (MatIEC) and run against the plant - oven + drives | `twin/sil_check.py` | **built** (2026-10-12) | DT-3b |
| DT-4b | The station logic (the 9 stubs) + the 181-signal sensor image; PLC-run flow = line_sim | `twin/sil_flow_check.py` | 5-7 d | DT-4a |
| DT-4c | Safety module SF1-SF6 (TwinSAFE side), faults F6/F7/F12, WebAssembly build, learning on a mismatched oven | `twin/sil_safety_check.py` | 3-4 d | DT-4b |
| DT-5 | OPC UA server + Sparkplug B / UNS | `twin/opcua_check.py`, `twin/uns_check.py` | 3-4 d | DT-4 |
| DT-6 | Contact physics for the handling steps (MuJoCo) | `twin/contact_check.py` | 4-5 d | DT-3 |
| DT-7 | Renders, synthetic QC images, vision model | `twin/vision_check.py` | 4-6 d | DT-1 |
| DT-8 | Operations: dashboard, KPIs, bake log, fault injection | `twin/ops_check.py` | 5-7 d | DT-4, DT-5 |
| DT-9 | Optional: the same USD stage in Omniverse / Isaac Sim (cloud) | manual review | 2-3 d | DT-1, a cloud RTX instance |
| DT-10 | Hardware in the loop: the real Beckhoff PLC replaces the SIL | `twin/hil_check.py` | when hardware arrives | DT-4, hardware |

Critical path: DT-1 → DT-2 → DT-3a → DT-3b → DT-4a → DT-4b → DT-4c → DT-8, about 6-7 weeks. DT-6 and DT-7 run in parallel with DT-4.

---

## DT-1 Scene export (BUILT)

**As built.** `twin/export_scene.sh` runs three steps (about 40 s in all):

1. `export_mesh.py` (FreeCAD):
   - meshes every B-rep **face** of the 5,996 solids, with LinearDeflection 0.2 mm and AngularDeflection 20°;
   - normals are averaged only inside a face, so edges stay sharp;
   - solids whose meshes are equal up to a translation share one prototype: **958 prototypes, 1,112,524 triangles drawn, 286,128 stored**;
   - it writes `out/cache/` (meshes.npz + index.json), recording the exact B-rep box (`optimalBoundingBox`) and the volume of every solid.
2. `build_scene.py` (OpenUSD 26.08) writes:
   - `out/stf2.usda`: mm, Z-up, one sublayer per module.
   - `out/layers/protos.usdc`: `class /Prototypes/P<k>/geo` meshes and `/Looks` with UsdPreviewSurface.
   - `out/layers/M*.usda`: `/STF2/<module>/<group>/<part>`, which references its prototype, is instanceable when the prototype is shared, and carries `xformOp:transform:anim` (identity) first on the 490 moving parts plus `stf:*` attributes.
   - `out/stf2.usdz` (8.1 MB), `out/stf2.glb` (10.7 MB, Y-up m, extras = stf:*) and `out/scene_index.json`.
3. `scene_check.py`: the gate below.

A low-detail `stf2_lod1.glb` is not needed: the full scene is 1.1 M triangles against the 3 M budget.

**Gate - `scene_check.py`** (all pass):

| Proof | Result |
|---|---|
| S1 complete | 5,996 prims = the 5,996 solids listed in the FCStd's own `Document.xml` (independent of the export); only the 10 modules |
| S2 geometry | worst box difference 0.099 mm (≤ 0.2 mm deflection); every mesh encloses its B-rep volume within 1.32 % (≤ 2 %), all closed |
| S3 identity | 152 of 152 drawn signals sit on their part; the part's tag is the signal's tag or its stem |
| S4 motion | 490 moving prims animatable, no static one; the other 73 timeline tracks are cookies the timeline spawns |
| S5 composition | 0 composition errors, 5,996 materials bound |
| S6 validators | all 28 OpenUSD 26.08 validators: 0 errors and 0 warnings, on the stage and on the USDZ |
| S7 GLB | Khronos glTF validator: 0 errors, 0 warnings; every node's box = the USD box (0.0000 mm) |
| S8 budget | 1,112,524 triangles ≤ 3,000,000 |

**It can fail:**
- a part moved by 1 mm fails S2 and names the part;
- a part dropped from the cache, with its counts adjusted to hide it, fails S1 and names the part.

**Findings made by building it:**
- **F1 (generator).** The contactors K1-K5 and their EDM inputs were flagged "in CAD" in `io_list.csv`, but the cabinet's DIN contents are not drawn. `plc_io.py` now marks them implied: 29 implied points instead of 21.
- **F2 (my error, caught by the render).** `#rrggbb/70` means 70 % **transparent** in `fcstd_colour`. The first export used it as 70 % opaque, and the guards rendered nearly solid. The opacity is now 0.30.
- **F3 (regression from V-1).** `bom.py` still read `plc_io.ELEM`, which V-1 had replaced. It is fixed, and `check_all.sh` now runs every proof in order so such a break cannot be committed again.

**Blender.** `twin/blender_load.py` imports the stage. It works around two Blender 5.2 importer behaviours:
- it turns off `merge_parent_xform`, which would rename every part `geo`;
- it copies `inputs:opacity` from the stage, because the importer leaves Alpha at 1 even for a minimal valid file.

It also renders previews to `out/preview/` (the line in 7 s, a module alone in a few seconds).

## DT-2 Kinematic playback (BUILT)

**As built.** `twin/playback.sh` (~25 s). How to view it: [VIEWING.md](VIEWING.md).

- **The rules, three times:**
  - `twin/playback.py` (Python reference);
  - `twin/web/player.js` (three.js math, no DOM: run by the browser *and* by Node);
  - `twin/blender_anim.py` (Blender keyframes).
  All implement `motion_player.py`'s rules:
  - rigid part = M(t, q) × T(offset);
  - followers ride on their body;
  - a reshaped track is drawn as its frame's cylinder, with the CAD mesh hidden;
  - spawned cookies are cylinders;
  - oven elements glow.
- **Browser:** `twin/web/index.html` + `viewer.js`:
  - the GLB, played at 1×, with scrubbing and 0.25-4× speed;
  - the oven readout (kW, phase currents, duty, TC per zone);
  - module and guard toggles;
  - click a part for its name, module, tag and hardware.
- **Blender:** `twin/out/stf2_anim.blend` holds 295 rigid parts, 36 followers, 232 cylinders and 9 glowing elements, keyed at 10 fps over 401 frames. It is written with Blender 5's slotted actions in bulk (~10 s).
- **Reference:** `twin/playback_ref.py` drives the FreeCAD player itself headless and records the exact B-rep box and the visibility of every object it moves: 563 objects × 41 frames.

**Gate - `playback_check.py`** (all pass):

| Player | Part-frames | Worst box difference | Visibility |
|---|---|---|---|
| P1 Python (on the DT-1 meshes) | 19,907 | 0.097 mm | 0 mismatches |
| P2 browser (`player.js` on the GLB, under Node) | 19,907 | 0.097 mm | 0 mismatches |
| P3 Blender (the keyed scene, evaluated per frame) | 19,907 | 0.097 mm | 0 mismatches |

Tolerance: 0.2 mm (tessellation) for CAD meshes, 0.05 mm for the rebuilt cylinders. **Colours** (re-validated
2026-10-11): the browser and Blender each draw 9,594 coloured part-frames (cookies browning, the 9 elements glowing),
all equal to `timeline.json`'s own values.

**The viewer itself** (`viewer.js`, not only `player.js`): open `twin/web/?selftest`. The page scrubs every second
and checks what `viewer.js` wrote into the three.js scene graph against `player.js`. Result: 41 frames, 13,571
node-frames, 9,512 cylinder-frames and 369 element colours, all exact (worst 0), title "selftest PASS". The mutant
"offset not applied" fails all 13,571 node-frames.

**It can fail:**
- a swapped quaternion order in `player.js` fails P2 (2.5 m off, pucks named);
- screws detached from their bodies in `playback.py` fail P1 (the screws named as missing).

**Not in DT-2:** live motion (DT-3) and the dashboard in the `main` React app (DT-8). The viewer is a standalone page
so that the proof and the view share one file.

## DT-3a Live plant core (BUILT)

**As built.**
- `motion.frame()` is now parametric:
  - `t` = plant time, which drives the event actuators;
  - `tau` = machine time = master position / V, which drives everything geared to the master;
  - `ev` = event start times;
  - `rows` = a band-row mapping.

  With the defaults it regenerated `timeline.json` **byte-identical**, and the collision sweep report is identical too.
- `twin/plant/core.py` steps 10 ms ticks of virtual time:
  - the master axis integrates τ: closed form at constant speed, so the nominal run has τ = t exactly; a 0.5 s ramp `[assumed]` to stop and to start;
  - commands: `kick`, `seal(lane)` (the stacker lifts 2 s later), `exchange`, `master(on)`, `speed(factor)`;
  - the 27 scene band-row names are a pool: a row lives at most 606.5 s, the pool spans 648 s, so a slot always shows its one live row;
  - the oven: the zone model in `reference` mode, integrated exactly as `motion.py` does;
  - frames in `timeline.json`'s own row format.
- **The model is frozen in the plant process.** The pure functions of `L` that recomputed a bake simulation or an IK bisection on every call are memoised there: a frame went from 650 ms to 17 ms.
- `twin/plant/serve.py` (FastAPI): `POST /command`, `/sim` (wall pacing), `/step` (manual mode), `GET /state`, and the WebSocket `/ws/frames`. The first frame is complete; after it, only the rows that changed are sent. It also serves the viewer, and binds 127.0.0.1 only.
- **Viewer** `twin/web/?live`: the same player rules (`player.js` `fromRows`) draw the live frames. It shows t and τ, and has buttons for stop/start master, kick, seal per lane, airlock exchange and sim speed.

**Gate - `plant_check.py`** (all pass, ~2 min):

| Proof | Result |
|---|---|
| L1 replay | the reference schedule gives `timeline.json` exactly: the visibility of all 527 tracks over 401 frames, 180,255 drawn rows, the SSR bits, power and phase currents, the zone temperatures - 0 differ |
| L2 determinism | one command script, every frame of 100 s: identical SHA-256 twice; one kick 10 ms later changes it |
| L3 endurance | 2 h, 982 commands (kick / 20 s, a seal / 12 s, exchange / 300 s), a frame every 10 s: no unreachable pose, all finite, ≤ 26 live rows, rows one band pitch apart |
| L4 event phases | the controller may fire an event at any phase. The swept envelopes of the 30 event parts vs the 497 geared parts over a full 24 s cycle: no pair can meet, so the reference collision sweep holds at every phase |
| L5 stop / resume | ramp-down 0.25 s of travel, then τ frozen and the geared rows frozen while the oven runs on; resume with no step > one tick, back at rate 1 |
| L6 speed | stepping ~800× real time, frame 17 ms (best of 3 batches) |
| L7 service | REST + WebSocket in manual mode: 16 frames (first 527 rows, then 2-502 changed) rebuild exactly the rows of an independent plant given the same commands |

**It can fail:**
- a pool of 26 fails L1 (row visibility) and L3 (rows out of order);
- a master that ignores the stop fails L5 (geared rows moved).

**Not in DT-3a** (→ DT-3b, the rest of this phase's original plan):
- product entities, so cookies that really exist rather than "loaded by position";
- stocks and the AMR;
- synthesized sensors;
- a controller that reacts to them;
- the oven under PI control with equivalence to `oven_ctrl` S1-S5;
- the flow proof against `sim_results.json`.

## DT-3b Product flow and the oven's closed loop (BUILT)

**The decision: one flow model, not two.** The twin runs `line_sim.py`'s own event engine. It does not use a second flow
model that would only agree statistically: with a 3 % defect rate, "38 rejects" cannot be matched within ±1 % by
different random draws.

- `line_sim.run()` became `flow()`, a generator that *reports* every event: deposit, load, QC, kick, pick, pack,
  exchange, AMR, losses. Cookies get an ID at deposit. `run()` drains it, and `sim_results.json` regenerates
  **byte-identical** for all 11 scenarios.
- `oven_ctrl.run()` became `ZoneLoop`, FB_Oven's closed loop one step at a time. `run()` drives it, and the control
  proofs and `oven/control.json` regenerate **byte-identical**.
- `twin/plant/flow.py` runs the engine 10 s ahead into a time-ordered queue and releases events at machine time. It
  keeps the product state: pucks, band, rows, stock, drawer, packs, cassettes, AMRs, and the **bake log** of every
  cookie.
- The plant turns flow decisions into motion:
  - a kick is a kicker stroke;
  - a full tray (pack) is a seal of its lane;
  - a weiss cassette exchange is the airlock sequence.

  What is drawn follows the flow: cookies on pucks, with their flavour's topping colour (frame `paint`); cookies on the
  band, by row, moving until the flow takes them; toppings only on topped cookies.
- The **oven** runs `ZoneLoop` on the band content the flow really deposited. Each cookie's bake log gets the
  worst |TC − set point| of each zone during its stay; outside ±2 K, it is flagged.
- **Two findings in DT-3a, fixed here:**
  - the band-row pool held only the names the 40 s recording showed, so some (row, column) slots of an endless band
    could not be drawn. The pool is now complete (27 × 6, base + topping), and the viewer creates the extra cylinders
    from the WebSocket hello;
  - `band_pose` stopped a cookie at its *scheduled* pick time. With a flow, the cookie moves until the flow takes it.

  Both are new optional arguments, and `timeline.json` is still byte-identical.
- The server runs the flow by default: `--scenario` for any line_sim scenario, `--hours` (24), `--no-flow` for the
  DT-3a plant. The viewer gains a product-flow panel.

**Gate - `flow_check.py`** (all pass, ~1 min):

| Proof | Result |
|---|---|
| F1 engine | `line_sim.flow()` gives all 11 scenarios of `sim_results.json` exactly |
| F2 oven loop | `ZoneLoop` stepped as the plant steps it = the stored S3 trace (241 samples, 0 differ) |
| F3 one hour | the plant's KPIs = `nominal_1h` exactly (894 loaded, 281 / 284 / 279 packed, 38 rejected, 15 band losses), and its released events agree |
| F4 genealogy | 1,056 bake logs: 844 packed (deposit < load < qc pass < pick), 38 rejected (qc reject), 706 with a 3-zone history, 0 incomplete |
| F5 coupling | 38 / 38 kicks, 279 / 279 seals, 3 / 3 weiss exchanges at the flow's own time (within one tick) |
| F6 drawn = flow | 360 frames: 17,280 puck checks (presence + flavour colour), 54,007 band cookies placed at the depositor + v_band (τ − row period) position, an independent formula; 0 wrong |
| F7 oven + flow | both deltas down 10 min with the agent policy: 150 cookies throttled, zone content 0 → 1 → 0; worst TC 0.52 K off its set point; 0 flagged |
| F8 determinism | 10 min, a frame every second: identical SHA-256 |

F9 (service): the server with the flow, in manual mode, sends WebSocket frames (rows, paint, flow summary, duty) that
rebuild an independent plant carrying the same flow exactly: 40 frames over 10 min, 0 differ.

F10 (every scenario, re-validated 2026-10-11): all 11 line_sim scenarios, including the 8 h AMR shifts (43,152
cookies), run **inside the plant** and give `sim_results.json` exactly. The oven, sampled over every whole run, is
never more than 0.58 K off. That worst case is the band running empty when the dough is starved (`shift_no_AMR`),
and no cookie is flagged.

**It can fail:**
- the pool's row lookup off by one row fails F6 (2,520 wrong, named);
- a pack that does not seal its lane fails F5 (0 / 279 seals).

**Moved to DT-4.** These belong with the PLC that consumes them:
- the synthesized sensor image (`SIM_MODELS.md` §3.4, the 181 signals);
- a controller that reacts to it.

In DT-3b the decisions are line_sim's. That is the proven model, but not yet the PLC program.

## DT-4a PLC in the loop: the oven and the drives (BUILT)

**What was there.** The generated TwinCAT program had never been compiled. Most of it is a skeleton:

| Has logic | Stubs (declarations + a comment, no statements) |
|---|---|
| FB_Oven, FB_Band, FB_MasterAxis, FB_SafetyIf, F_InSlice, MAIN | FB_Transfer, FB_QC, FB_DeltaPicker, FB_Lane, FB_AmrPorts, FB_Airlock, FB_SafeEnvelope, FB_DataTag, FB_CameraTrigger |

DT-4a therefore proves the part that exists (the oven and the drives) and DT-4b writes the stations.

**As built:**
- `twin/sil/port.py` turns `plc/*.st` into one IEC 61131-3 project through 13 listed rules (R1-R13). The rules cover:
  - pragmas, `GVL_IO.` qualifiers and the `VAR_EXTERNAL` declarations IEC needs;
  - located I/O and `RETAIN`;
  - `LMOD`;
  - `//` comments and missing `END_*` keywords;
  - the configuration and task (10 ms);
  - FB arrays (an IEC 3rd-edition feature);
  - stubs, which are made explicit and listed;
  - **SIM_MC**: `AXIS_REF` and the Tc2_MC2 blocks with PLCopen semantics (rising-edge Execute; MC_GearIn does *not* decouple on a falling Execute).
- `twin/sil/build.py` runs MatIEC (`iec2c`, 0 errors, 0 warnings) then clang, giving a native library. Its `glue.c` gives every located variable storage and a name table; `mon.c` provides read-only monitors of the program's internals (what an HMI reads over ADS) and the RETAIN memory for a power cycle.
- `twin/sil/runtime.py` drives the program from Python, scan by scan, with `power_cycle()`.
- `twin/sil/plant.py` is the plant the PLC sees at its own 10 ms scan:
  - a simulated NC for the commanded axes;
  - the band and the rows really cut, while the rolls actually turn;
  - the oven zones integrated every 10 ms from the SSR outputs that are on;
  - the thermocouple lag, giving `tcTCn`;
  - the phase currents through the transducer model (lag and accuracy), giving `aiBCn`.

**Findings.** The generated program had 15 defects, all fixed in the generator (`plc_io.py`), never in its output:

| # | Found by | Finding |
|---|---|---|
| 1 | review | `fNow_s` (the task clock) was never advanced: the PWM phase stayed 0, so no time-proportioning, and no heater-break timing |
| 2 | review | `aSp` (the set-point ramp) never initialised: a PLC restart on a hot oven ramps from 0 °C (a 112 K dip, mutant M2) |
| 3 | review | `AXIS_REF` passed as `VAR_INPUT`: the MC blocks moved a *copy*; the real axes never moved. Now `VAR_IN_OUT` |
| 4 | review | `FB_SafetyIf` had no body: `bRunEnable` always FALSE, so the oven never heated. Now from the EL6910 status `xSafeRunPermit` |
| 5 | review | `FB_Band.aZoneContent` was never computed: the oven's feed-forward (14.5 K → 0.7 K in O-2) was dead. Now FB_Band tracks every row it cuts |
| 6 | compiler | two names with two initialisers in one declaration; expressions as array initialisers |
| 7 | **run** | `MC_GearIn(Execute := bOvenReady)` cannot stop the depositor (PLCopen: a falling Execute does not decouple). A Z2/Z3 heater break would keep feeding dough. Now MC_GearOut + MC_Halt (mutant M3) |
| 8 | compiler | `ST_PuckEvent` refers to `E_Station` / `E_Outcome`, never generated (left out of the SIL, listed) |
| 9 | compiler | inline enumerations in VAR blocks (`eState : (WAIT, ...)`) → named types |
| 10 | compiler | `// ... END_VAR`: FB_Oven's `VAR_INPUT` was closed inside a comment, so the program could never have compiled |
| 11 | **run** | **a heater break shut its whole zone off.** Naming re-ran while the lagged current settled, adding the element's power to `aLost` again (6,000 W lost of 850 W), so the duty was 0 forever. Now idempotent, and a named element is no candidate (mutant M4) |
| 12 | **run** | a power cycle lost FB_Band's row memory: the feed-forward saw an empty band under a full one (a 12.4 K dip). Now `VAR RETAIN` (mutant M5) |
| 13 | **run** | after a naming, the settling current named a second, innocent element on the same phase. Now a 1 s hold-off |
| 14 | **run** | FB_Band counted rows from its *command* (`bOvenReady`) rather than the rolls' measured motion: the row cut while the rolls brake was missed (a 3.7 K dip). Now from `axRolls.NcToPlc.ActVelo` (mutant M6) |
| 15 | **validation** | FB_Band counted a row whenever the rolls turned, **even on an empty hopper**. Through a dough outage the feed-forward heated for dough that was not there: the PLC ran 12.1 K from the proven loop and left the bake window. Now a row needs the hopper level IOL1 (ToF, process data = distance in 0.1 mm, `line_model.hopper_tof`) to have held a row's dough while it was pressed out (mutant M7). Judging on the level *after* the slug left misses the last row (3.7 K, mutant M8) |

Also strict IEC typing: real literals (`20.0`, not `20`), `END_IF;` and a named `T_ZoneArray`. TwinCAT accepts all of
them, and the generated TwinCAT files now use them.

**Gate - `sil_check.py`** (all pass, ~30 s on 10 cores):

| Proof | Result |
|---|---|
| C1 compiles | 718 lines → MatIEC 0 errors, 0 warnings → native library; 138 located variables; the 9 stubs listed |
| C2 port only | the 15 ported POUs = the generated ones token for token, apart from R1-R13 |
| C3 PWM | each of the 9 elements conducts its zone's duty (within one scan in 200), in staggered slices |
| C4 cold start | within ±2 K after 18.5 min (oven_ctrl S1: 18.3 min); overshoot 1.05 K (S1: 1.64 K); ready at 19.5 min |
| C5 production start | ready at 61 s; FB_Band's content = the band's true content at 1,500 / 1,500 s; worst zone 0.62 K |
| C6 heater break × 9 | each element named correctly and only it, after 1-8 s; Z1 rides through (≤ 0.6 K); Z2 / Z3 hold: the depositor stops, no row is cut after the hold, the zone is back in the window once the band empties; FB_Band = the band throughout |
| C7 no nuisance | 1 h of production, transducer error against the proof: no phase alarm, nothing named |
| C8 hot restart | power cycle on a running oven: rows + learned feed-forward kept (RETAIN), worst zone 0.42 K |
| C9 determinism | 300 s of outputs + TCs identical |
| C10 PLC = model | 1 h of production; the hopper runs dry at 14.4 min and is refilled at 25 min. The compiled PLC and `oven_ctrl.ZoneLoop` on the same true band content: within 0.16 K (tolerance 0.5 K); FB_Band = the true content at 3,600 / 3,600 s; worst zone 0.62 K; no hold |
| mutants | M1-M8 (findings 1, 2, 7, 11 + 13, 12, 14, 15 and the post-cut level put back) each rejected |

## DT-4b The stations (to build)

- Write the station logic the 9 stubs only describe, generated in `plc_io.py`:
  - delta C transfer;
  - QC + kicker;
  - the delta pickers;
  - the lanes (index, seal, stack);
  - the AMR ports and airlocks;
  - the data tag.
- Extend the plant to the full 181-signal sensor image (`SIM_MODELS.md` §3.4).
- The plant obeys the PLC's outputs instead of line_sim's decisions.
- **Proof:** the PLC-run line reproduces `sim_results.json["nominal_1h"]`, with the random outcomes (defects, grips, QC errors) drawn from one table shared by line_sim and the plant.

## DT-4c Safety and the rest (to build)

- SF1-SF6 as a separate module (the TwinSAFE side) feeding `xSafeRunPermit` and the stop categories;
- faults F6 / F7 / F12;
- the WebAssembly build, for the browser;
- learning (W0 / a1) on a mismatched oven in the loop, and PERSISTENT across a program download.

## DT-5 OPC UA and Sparkplug B / UNS

**Builds.**
- `twin/opcua/`: the line on the Machinery companion specification, one MachineryItem per module, values in engineering units, methods `StartProduction` / `StopProduction` / `ResetAlarms` / `InjectFault`. Sign & Encrypt only, as on `main`.
- `twin/uns/`: a Sparkplug B edge node (one device per module) to Mosquitto (TLS, per-role ACL), and the ISA-95 namespace `stf/<site>/bakery/line2/<module>/<tag>`.

**Gate:**
- `opcua_check.py` browses the server, checks the address space against the companion NodeSets, reads every tag live and checks security, as `opcua/check.py` on `main` does.
- `uns_check.py` judges every message of a 10-minute run against the Sparkplug 3.0 requirements, reusing `uns/check.py` (50 requirements).

## DT-6 Contact physics

**Builds.**
- `twin/contact/`: MJCF scenes generated from the primitive parts: delta C cups and band end, puck nest, kicker and bin, cassette.
- Each scene runs sweeps over band speed, vacuum time, friction and drop height. A Genesis/Metal variant handles the large packing sweep.

**Gate - `contact_check.py`:**
- each scene's static geometry equals the model's primitives;
- the grip, seat and landing rates come with confidence intervals;
- the line simulation re-run with those rates still meets its claims, or a finding is written.

## DT-7 Renders and vision

**Builds.**
- `twin/render/`: Blender (`bpy`) imports the USD stage and places the QC camera with its intrinsics from the model (CAM positions in `line_model`).
- It renders cookies from `oven.profile` colours with surface variation, under-bake, over-bake, broken and missing-topping classes.
- Labels in COCO format.
- A small CNN is trained with PyTorch (MPS) and exported to ONNX (CoreML execution provider), following Upgrade 15 on `main`.

**Gate - `vision_check.py`:**
- accuracy on held-out renders;
- a confusion-matrix threshold per class;
- inference ≤ `AI_LATENCY` 0.5 s on the M4.

The check states plainly that this is accuracy on **renders**, not on real cookies.

## DT-8 Operations

**Builds.** Dashboard tabs in the web twin:
- **Line:** takt, buffers, AMR, stock.
- **Oven:** zones, duty, phase currents, learned values, the element map with broken elements.
- **Quality:** the per-cookie bake log, rejects.
- **Alarms.**
- **KPIs:** OEE as availability × performance × quality, energy per cookie.
- **Fault injection:** the catalogue, one click each.

Records go to DuckDB (or InfluxDB) and SQLite, each tagged with the model's git commit.

**Gate - `ops_check.py`:**
- every fault in the catalogue, injected through the API, shows the expected alarm and KPI effect on the dashboard's data endpoints;
- the bake log of every cookie is complete (deposit → pack);
- the OEE of the nominal hour equals the value computed from `sim_results.json`.

## DT-9 Optional: Omniverse / Isaac Sim

- Rent an RTX instance (cloud GPU).
- Open `stf2.usda` in USD Composer / Isaac Sim and use the Kit app streaming client in the Mac's browser.
- Use it for RTX path-traced reviews, Replicator data at scale, or PhysX/Newton comparisons against the MuJoCo results.
- Nothing in DT-1 … DT-8 depends on it.

## DT-10 Hardware in the loop

When the Beckhoff hardware exists:
- the TwinCAT project (generated `plc/*.st` + the TwinSAFE project) runs on the IPC;
- the twin's plant replaces the field through ADS (`pyads`) or OPC UA for the I/O image, or EtherCAT simulation on the IPC side;
- the same gates as DT-4 run against the real controller.

Then the field devices are connected one module at a time, and each one is compared with its twin.

## Acceptance

The twin is accepted when, on the M4 Mac, `twin/run_all_checks.sh` passes:
- DT-1 to DT-8 gates;
- the existing model chain (`line_model`, `oven_ctrl`, `joints`, `plc_io`, `safety`, `line_sim`, `motion`, `validate_motion`);
- a one-hour SIL run at ≥ 20× real time with no gate failing and memory below 8 GB for the live set.
