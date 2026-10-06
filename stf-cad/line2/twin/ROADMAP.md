# STF-2 digital twin - roadmap

Ten phases. Each one follows the repository's rules: it is generated from the model, it ships only when its proof passes,
and it reuses what `main` already built for cell 1. Effort is for one person who knows this code. "Gate" is the
script that must exit 0.

| Phase | Builds | Gate | Effort | Needs |
|---|---|---|---|---|
| DT-1 | Scene export: OpenUSD, USDZ, GLB | `twin/scene_check.py` | **built** (2026-10-06) | - |
| DT-2 | Kinematic playback in the web twin and Blender | `twin/playback_check.py` | **built** (2026-10-06) | DT-1 |
| DT-3 | Live plant service (real-time stepping, WebSocket) | `twin/plant_check.py` | 6-8 d | DT-2 |
| DT-4 | PLC in the loop (SIL): ST → IEC → MatIEC, safety module | `twin/sil_check.py` | 8-10 d | DT-3 |
| DT-5 | OPC UA server + Sparkplug B / UNS | `twin/opcua_check.py`, `twin/uns_check.py` | 3-4 d | DT-4 |
| DT-6 | Contact physics for the handling steps (MuJoCo) | `twin/contact_check.py` | 4-5 d | DT-3 |
| DT-7 | Renders, synthetic QC images, vision model | `twin/vision_check.py` | 4-6 d | DT-1 |
| DT-8 | Operations: dashboard, KPIs, bake log, fault injection | `twin/ops_check.py` | 5-7 d | DT-4, DT-5 |
| DT-9 | Optional: the same USD stage in Omniverse / Isaac Sim (cloud) | manual review | 2-3 d | DT-1, a cloud RTX instance |
| DT-10 | Hardware in the loop: the real Beckhoff PLC replaces the SIL | `twin/hil_check.py` | when hardware arrives | DT-4, hardware |

Critical path: DT-1 → DT-2 → DT-3 → DT-4 → DT-8, about 6-7 weeks. DT-6 and DT-7 run in parallel with DT-4.

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

Tolerance: 0.2 mm (tessellation) for CAD meshes, 0.05 mm for the rebuilt cylinders.

**It can fail:**
- a swapped quaternion order in `player.js` fails P2 (2.5 m off, pucks named);
- screws detached from their bodies in `playback.py` fail P1 (the screws named as missing).

**Not in DT-2:** live motion (DT-3) and the dashboard in the `main` React app (DT-8). The viewer is a standalone page
so that the proof and the view share one file.

## DT-3 Live plant service

**Builds.** `twin/plant/`, a Python package that is stepped at 10 ms of virtual time:
- axes (`SIM_MC`), cylinders, ejectors;
- the kinematic motion (§3.1 of [SIM_MODELS.md](SIM_MODELS.md));
- the oven (`oven_ctrl.Plant` / `Mismatch`, phase currents, STB);
- product entities, stocks, the AMR, and the sensors.

Around it:
- **FastAPI** with `/ws/frames` (format in [DATA_CONTRACT.md §3.2](DATA_CONTRACT.md));
- **REST**: `/state`, `/scenario`, `/fault`, `/run`.
- In DT-3 it is driven by a **scripted controller**: a Python port of the PLC's intent, just enough to run the nominal cycle. DT-4 replaces it with the real program.

**Gate - `plant_check.py`:**
- **Replay:** fed the recorded axis trajectories of the reference run, the plant reproduces `timeline.json` frame by frame within 0.05 mm, including element bits, power and temperatures.
- **Oven:** the plant's oven, driven like `oven_ctrl.run`, reproduces S1-S5 within 0.1 K.
- **Flow:** one nominal hour gives `sim_results.json["nominal_1h"]` within ±1 %.
- **Determinism:** two runs with the same seed are identical.

## DT-4 PLC in the loop (SIL)

**Builds.**
- `plc_io.py --target iec` generates a portable IEC 61131-3 project from the same sources: located I/O, `SIM_MC` instead of Tc2_MC2, no pragmas, retained memory for `VAR PERSISTENT`.
- `twin/sil/` compiles it with MatIEC → C → native (`ctypes`) and → WebAssembly (`clang`, `wasm-ld`), reusing `stf-cad/hbw/sil` from `main`.
- The safety module implements SF1-SF6 from `safety/safety_functions.csv` and runs before the standard task.

**Gate - `sil_check.py`:**
1. The program compiles with no warnings.
2. A diff check proves the IEC FB bodies equal the TwinCAT ones, apart from the mapped constructs.
3. One hour of nominal production runs with **the PLC deciding**, and gives the DT-3 flow result.
4. Faults F1-F7 and F11-F12 of the [fault catalogue](SIM_MODELS.md#6-fault-catalogue) give their expected responses, measured on the plant: alarm times, which element is named, depositor hold, STB trip time, SS1 timing, unlock delay.
5. The learned `W0` / `a1` survive a restart (retained memory).
6. The WebAssembly build runs the same 10-minute scenario with an identical I/O trace.
7. **It can fail.** Mutants of the program are each rejected by a gate, for example:
   - band gear ratio off by one row;
   - the heater-break threshold doubled;
   - SF2 unlock without the standstill wait.

**Expect findings.** On `main`, cell 1's generated program was first rejected by MatIEC with 910 errors. Writing it
properly and running it exposed ten real problems, one of them a design flaw (Upgrade 13, F8). The STF-2 program has
never been compiled either, so DT-4 budgets time for the same. Every finding is fixed in the generator
(`plc_io.py`), never in the output.

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
