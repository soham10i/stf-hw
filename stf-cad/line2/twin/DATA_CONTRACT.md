# STF-2 digital twin - data contract

Every file and every signal the twin reads or writes: where it comes from, its schema, its units. A file in the
"generated" column is never edited by hand. Change `line_model.py` (or its companion) and regenerate.

## 1. Conventions (apply everywhere)

| Item | Rule |
|---|---|
| Length | **mm** (the model, the CAD, the timeline). USD stages declare `metersPerUnit = 0.001`. GLB files for three.js are scaled to **m** at export, and only there. |
| Frame | Right-handed. **x** along the line, **y** across it (towards the back), **z** up. z = 0 is the deck top; the cabinet hangs below it (to z = −312). The full machine is x 0…1870, y 0…1485, z −312…900. |
| Angles | Degrees in `line_model.L`. Quaternions **(x, y, z, w)** in the timeline (FreeCAD `Rotation(x, y, z, w)`). |
| Time | Seconds. The twin runs on **virtual time**: the PLC scan (10 ms) is the tick and wall-clock pacing is a viewer option. Timestamps on the bus are virtual-time ms since the run's start, plus a run id. |
| Temperature | °C. Power in W, current in A (RMS), duty 0…1. |
| Identity | A **part name** (`line_model.build()`, e.g. `dep_hopper_floor`) is unique. A **tag** (e.g. `Q41`, `TC1`, `E1T1`, `BC2`) is the plant tag shared by the I/O list, the PLC variable, the wiring and the 3D part. One tag may span several parts (a valve's two pistons). The **module** is one of `M1_loop … M10_safety`. |
| Assumptions | A value marked `[assumed]` or `[typ]` in the model stays marked where it is used: the live twin and the dashboard flag every value that rests on one (`VERIFICATION_PLAN.md` lists them). |

## 2. Inputs the twin consumes (all generated, all in `stf-cad/line2`)

### 2.1 Parametric model - `line_model.py`

| Call | Returns |
|---|---|
| `M.L` | the parameter dict (takt, band, oven recipe, delta geometry, …), with `[assumed]` tags in the source |
| `M.build(with_product=False)` | 729 parts, each `{name, module, group, kind, p, s, colour, joint, tag, mech, note, hw}`; `kind` ∈ box (573), cyl (85), rod (63), arc (8). These primitives are the **collision geometry** of the twin (MJCF, DT-6). |
| `M.MODULES` | the 10 modules |
| `M.takt()`, `M.band_v()`, `M.bake_t()`, `M.stations()` | 4.0 s per puck (900 cookies/h), 2.29 mm/s band, 265 s bake, station x positions |
| `M.delta_ik(x, y, z, xd)`, `M.delta_c_poses()`, `motion.band_pose(n, t)` | the closed-form kinematics the live plant reuses |
| `M.oven_power()` | zone loads, the 9 elements (tag, zone, face, W), the phase plan, warm-up |

### 2.2 Precise CAD - `~/workspace/stf-factory/cad/line2_precise/`

| File | Content |
|---|---|
| `STF2_Precise.FCStd` / `.step` | the whole line, 5,996 solids, labels = part names (screws `F####_…` follow their body) |
| `M1_loop.FCStd` … `M10_safety.FCStd` (+ `.step`) | one file per module |
| `brep_report.json` | exact interference result (0 shared volume) |

The USD export (DT-1) tessellates **these** solids, not the primitives, so the twin looks like the CAD. Old files
`M2_feeder`, `M3_tunnel`, `M4_stamp` in that folder belong to the previous design and must not be exported.

### 2.3 Motion timeline - `motion/timeline.json`

Written by `motion.py`, played by `motion/motion_player.py`, proven by `validate_motion.py` (PLAYER == MODEL ≤ 0.05 mm).

```jsonc
{
  "dt": 0.1, "frames": 401, "t_end": 40.0,
  "track": {                                   // 527 moving parts
    "<part name>": [                           // one entry per frame:
      [tx, ty, tz, qx, qy, qz, qw, vis],       //   rigid: Placement(t, q) * CAD placement, vis 0/1
      { "c": [x,y,z], "ax": "z", "dia": 12.0, "len": 25.0, "col": "#c68f4c", "vis": 1 }
                                               //   re-shaped: extending piston rod / spreading band cookie
    ]
  },
  "spawn":  [ { "name": "cookie_00", "kind": "cyl", "p": [x,y,z], "s": ["z", h, d], "colour": "#rrggbb" } ],
  "follow": { ... },                           // screws / brackets that ride on a moving body
  "glow":   { "oven_heater_E1T1": { "on": "#ff6a1a", "off": "#5a2a1c", "bits": "1110…" } },  // SSR state per frame
  "power":  [ [W_total, A_L1, A_L2, A_L3], ... ],   // per frame
  "temps":  [ [TC1, TC2, TC3], ... ],               // °C per frame, oven_ctrl zone model driven by the bits
  "duty":   { "Z1": 0.61, ... }, "zones": [ { "T": 210.0 }, ... ],
  "phases": { "exchange": [...], "kicks": [...], "seals": [...], "lifts": [...] }
}
```

The recorded timeline remains the **reference run**. The live plant of DT-3 must reproduce it frame by frame when
given the same inputs, and that is DT-3's proof.

### 2.4 Signals - `plc/io_list.csv` (181 signals)

Columns: `tag, kind, terminal, module, part, description, hw, load_A, in_cad`.

| kind | n | PLC type (GVL_IO) | variable | plant side |
|---|---|---|---|---|
| DI | 46 | BOOL `AT %I*` | `i<tag>` | sensor state (reed, diffuse, vacuum OK, door switch) |
| DO | 40 | BOOL `AT %Q*` | `q<tag>` | valve coil, SSR, relay, light |
| SI / SO | 32 / 13 | TwinSAFE (FSoE) | `si<tag>` / `so<tag>` | safety inputs/outputs (SF1-SF6) |
| STEP | 18 | `AXIS_REF` (EL7047) | `ax<tag>` | stepper axis: position, velocity, enable |
| IOL | 11 | `ARRAY[0..31] OF BYTE` (EL6224) | `iol<tag>` | ToF level, NFC head, vacuum level |
| AI | 7 | INT 0…32767 = 0…10 V (EL3064) | `ai<tag>` | pyrometer, colour R/G/B, **BC1-BC3 phase currents 0…20 A** |
| TC | 6 | INT, 0.1 °C (EL3314) | `tc<tag>` | 3 oven zones + 3 sealing heads |
| DOTS / DITS | 3 / 1 | timestamped I/O (EL2252 / EL1252) | `qts<tag>` / `its<tag>` | camera triggers / position latch |
| ENC | 1 | UDINT (EL5101) | `enc<tag>` | master encoder B1, 1024 ppr |
| ETH | 3 | - | `cam<tag>` | GigE cameras (images, not I/O) |

**This CSV is the twin's I/O image definition.** The SIL PLC and the plant exchange exactly these 181 values each
scan, keyed by tag. Nothing is added on one side only. Related files:
- `plc/wiring.csv`: cable, cores, mm², length per signal;
- `plc/cabinet.json`: DIN rows and devices;
- `plc/GVL_IO.st`: the PLC declarations.

### 2.5 PLC program - `plc/*.st` (TwinCAT 3 Structured Text)

- `MAIN` calls, in order: `FB_SafetyIf`, `FB_MasterAxis`, `FB_Oven`, `FB_Band`, `FB_Transfer`, `FB_QC`, `FB_DeltaPicker` ×2, `FB_Lane` ×3, `FB_AmrPorts`.
- The other generated units are: `FB_Airlock`, `FB_CameraTrigger`, `FB_DataTag`, `FB_Policy`, `FB_SafeEnvelope`, `F_InSlice`, `DUT_PhysicalAI`.
- Task: 10 ms.
- TwinCAT-specific constructs the SIL port must map (DT-4):

| Construct | Where | SIL mapping |
|---|---|---|
| `AXIS_REF`, `MC_Power`, `MC_MoveVelocity`, `MC_GearIn`, `MC_Stop` (Tc2_MC2) | MasterAxis, Band, SafetyIf | a small `SIM_MC` library: same FB names and pins, the axis state lives in the plant |
| `AT %I*` / `AT %Q*` (unlocated, linked in the I/O tree) | GVL_IO | located addresses generated from `io_list.csv` (`%IX`, `%QX`, `%IW`, `%ID`) |
| `{attribute 'qualified_only'}` and other pragmas | GVL_IO | stripped |
| `VAR PERSISTENT` | FB_Oven (learned W0, a1) | a retained-memory file the runtime loads and saves |
| `LMOD`, `LIMIT`, `SEL`, `TON` | throughout | standard IEC or a 3-line shim |
| TwinSAFE logic | `safety/safety_functions.csv` | a separate safety-logic module, run before the standard task |

### 2.6 Oven - `oven/control.json`, `oven/profile.csv`, `oven/report.md`

`control.json`:
- `ctrl`: the constants (TC_TAU, ZONE_G, PWM, ramp, learning, heater break);
- `gains`: per zone K, τ, θ, Kc, Ti;
- `setpoints`, `P` (W installed), `C` (J/K), `Tp` (mean product temperature per zone);
- `window`: the bake window, ±2 K;
- `scenarios`: S1-S5 traces.

The live plant builds its oven from these numbers. `profile.csv` holds the product temperature, moisture and colour history along the band.

### 2.7 Safety - `safety/safety_functions.csv`, `safety/report.md`

Columns: `SF, function, inputs, response, stop category, PLr, diagnostics`. Six functions:
- SF1 E-stop;
- SF2 guard locking;
- SF3 safe exhaust;
- SF4 STB over-temperature;
- SF5 drawing-in;
- SF6 AMR airlocks.

The twin's safety module implements exactly these. Its responses are checked against this table (DT-4).

### 2.8 Line simulation - `line_sim.py`, `sim_results.json`

The discrete-event model of stock (dough, topping, trays, film), the AMR service and the counted losses.
`sim_results.json` holds the claims the twin's 1 h runs must reproduce within tolerance (DT-8).

## 3. Outputs the twin produces

### 3.1 Scene (DT-1, built) - `twin/out/` (generated, not committed; `twin/export_scene.sh`)

| File | Content |
|---|---|
| `stf2.usda` (root) | defaultPrim `/STF2` (kind assembly), `metersPerUnit = 0.001`, `upAxis = Z`. Sublayers: `layers/M1_loop.usda` … `layers/M10_safety.usda`, then `layers/protos.usdc`. `customLayerData` records the source FCStd, the counts and the deflection. |
| `layers/protos.usdc` | `class /Prototypes/P<k>` (Xform) with child `geo` (UsdGeom.Mesh: points in mm relative to the prototype's corner, vertex normals, triangles), plus `/Looks/M_nnn` (UsdPreviewSurface: diffuseColor, roughness 0.5, opacity) |
| `layers/M*.usda` | `/STF2/<module>/<group>/<part>`: an Xform that references `/Prototypes/P<k>` and is instanceable when the prototype is shared. Ops: `xformOp:transform:anim` (moving parts only, identity; the twin writes the timeline's Placement(t, q) here) then `xformOp:translate:offset`. Binds `/Looks/…`. Attributes: `stf:name`, `stf:module`, `stf:group`, `stf:hw`, `stf:tag`, `stf:note`, `stf:moving`, `stf:fastener`. |
| `stf2.usdz` | the flattened stage, packaged; opens in Quick Look / Reality Composer Pro |
| `stf2.glb` | glTF 2.0: root node `STF2` with scale 0.001 and a −90° rotation about x (Z-up mm → Y-up m); a node per module, then a node per part (name = part name, translation = offset in mm, `extras` = stf:*); one mesh per (prototype, colour), shared |
| `scene_index.json` | part name → prim path, GLB node index, module, group, tag, moving, prototype, triangles |
| `cache/index.json`, `cache/meshes.npz` | the FreeCAD tessellation: per solid the exact B-rep box and volume, the mesh volume and closedness (what the gate compares) |
| `preview/*.png` | Blender EEVEE previews (`blender_load.py --render`) |

`[assumed]` values are not attached to individual prims. A part's size usually depends on several parameters, so
the per-value list stays in `VERIFICATION_PLAN.md`. The dashboard (DT-8) shows it by parameter, not by part.

### 3.2 Live state bus (DT-3) - WebSocket `/ws/frames`

One message per published frame (default 20 Hz of virtual time; the plant itself steps at 10 ms):

```jsonc
{ "run": "2026-10-06T10:00:00Z#7", "t": 1234.56,                 // virtual s
  "xf":   { "<part>": [tx,ty,tz,qx,qy,qz,qw] },                   // only parts that moved since the last frame
  "shape":{ "<part>": { "len": 18.2 } , "<cookie>": { "col": "#b98a4f", "d": 44.1 } },
  "vis":  { "<part>": 0 },
  "io":   { "qE1T1": 1, "tcTC1": 2101, "aiBC1": 9830 },           // changed I/O only, PLC units
  "oven": { "T": [210.0, 200.1, 185.0], "duty": [0.61, 0.58, 0.63], "W": 2650, "A": [4.3, 3.9, 4.1] },
  "kpi":  { "good": 412, "reject": 3, "band_lost": 0 } }
```

The format matches the timeline's track rows, so the existing FreeCAD player can replay a recorded live run.

### 3.3 OPC UA (DT-5) - `opc.tcp://localhost:4840/stf2`

- Information model: Machinery (`Opc.Ua.Machinery`), with one `MachineryItem` per module (M1-M10).
- `Monitoring` and `Parameters` folders per module carry the module's tags from `io_list.csv`, using engineering units (°C, A, mm/s), not raw counts.
- Methods: `StartProduction`, `StopProduction`, `ResetAlarms`, `InjectFault(scenario)` (twin only).
- Security: Sign & Encrypt only, no anonymous access, as on `main`.

### 3.4 Sparkplug B / Unified Namespace (DT-5)

- Edge node `spBv1.0/STF2/NBIRTH|NDATA/<edge>`, one device per module.
- Metrics: the tag names, typed, with the units above.
- UNS path (ISA-95): `stf/<site>/bakery/line2/<module>/<tag>`.
- Broker: Mosquitto with TLS and per-role ACLs: `stf-edge`, `stf-scada`, `stf-viewer`, `stf-auditor`. These are the same roles as `uns/broker.py` on `main`.

### 3.5 Records (DT-8)

| Store | Table / measurement | Key fields |
|---|---|---|
| DuckDB / InfluxDB | `oven` | t, zone, T, TC, duty, W, A_L1..3, learned W0/a1 |
| | `line` | t, master pos, band pos, takt, buffer levels, AMR state |
| | `quality` | t, cookie id, colour RGB, verdict |
| SQLite | `cookie` (genealogy, the NFC bake log) | cookie id, row, flavour, deposit t, zone entry/exit t, max \|ΔT\| per zone, flagged, verdict, pack id, cassette id |
| | `alarm` | t, source tag, class (heater break, STB, door, stock), raised / acknowledged / cleared |
| | `run` | run id, git commit of the model, scenario, seed, result of every gate |

Every record carries the **git commit of `line_model.py`** it was produced with, so a result can be traced to the
exact design it came from.
