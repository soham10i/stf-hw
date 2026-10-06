# STF-2 digital twin - technology stack (Apple M4, 24 GB, no hardware)

Target machine:
- Apple M4 (10-core CPU, 10-core GPU), 24 GB unified memory, macOS 26.
- Everything below runs natively on Apple Silicon unless a row says otherwise.
- Versions are the ones installed on this Mac today, or the minimum the twin needs.

## 1. The decision in one table

| Layer | Choice | Runs on the M4 | Why this one | Omniverse equivalent |
|---|---|---|---|---|
| Source of truth | `line_model.py` + proofs (Python 3.13) | yes | exists, proven | - |
| CAD | FreeCAD 1.1 (headless `freecadcmd`) | yes | exists: 5,996 solids, STEP, B-rep checks | CAD connectors |
| Scene format | **OpenUSD** (`usd-core` wheel, `pxr` API) | yes (arm64 wheels) | Omniverse's native format: the stage moves to Omniverse unchanged; layers, variants, instancing | USD stage / Nucleus |
| Web scene | glTF 2.0 / GLB (via `trimesh`) | yes | three.js loads it directly; small, streamable | Kit streaming viewer |
| Apple scene | USDZ (Reality Composer Pro / Quick Look) | yes | AR on iPad / Vision Pro, Finder preview | - |
| Live 3D view | React 18 + three.js + react-three-fiber (existing `web/`) | yes (browser, Metal via WebGL2/WebGPU) | already the twin's viewer on `main` | Omniverse viewport |
| Photoreal render | **Blender 5.2** (Cycles on Metal, EEVEE) + `bpy` scripts | yes | GPU path tracing on Apple Silicon, Python-driven, imports USD | RTX renderer |
| Synthetic data | Blender `bpy` (optional BlenderProc) | yes | labelled images for the QC camera | Omniverse Replicator |
| Kinematics | own closed-form models (delta IK, chain, band) from `line_model` | yes | exact, already proven; no solver drift | PhysX articulations |
| Contact physics | **MuJoCo 3** (`pip install mujoco`) | yes, CPU, native arm64 | stable contacts, fast, MJCF generated from the parts' primitives | PhysX |
| Physics, GPU option | Genesis (Apple Metal backend) | yes (Metal) | many parallel scenes on the M4 GPU, for parameter sweeps | Isaac Lab |
| Physics, NVIDIA path | Newton (Warp) | CPU only on macOS | the engine behind Isaac Lab's future; keep MJCF/USD portable to it | Newton / PhysX |
| Process models | NumPy, own models (`oven.py`, `oven_ctrl.Plant`), FMI 3.0 via FMPy (optional) | yes | the oven model is already proven; FMU makes it tool-neutral | - |
| Discrete events | `line_sim.py` (existing); SimPy optional | yes | stock, AMR, losses already modelled | - |
| PLC (SIL) | **MatIEC** (`iec2c`) → C → native / WebAssembly (clang + lld from Homebrew) | yes | same pipeline as Upgrade 13 on `main`; deterministic scan in virtual time | - |
| PLC, second runtime | OpenPLC Runtime (uses MatIEC) in Docker, or CODESYS Control for Linux ARM64 SL in Docker | yes (Linux container) | a "real" soft-PLC with Modbus/OPC UA; CODESYS needs its Windows IDE | - |
| PLC, target | TwinCAT 3 (Beckhoff) | **no** (Windows x64 / TwinCAT/BSD x86 only) | the program is written for it; used at DT-10 on a Windows PC or Beckhoff IPC | - |
| OPC UA | `asyncua` 2.0 (Python) | yes | reused from `main` (Machinery companion spec, Sign & Encrypt) | Omniverse OPC UA connector |
| MQTT broker | Eclipse Mosquitto 2.1 (Homebrew) | yes | reused from `main` (TLS, per-role ACL) | - |
| Sparkplug B / UNS | `paho-mqtt` 2.1 + Sparkplug B protobuf (existing `uns/`) | yes | ISA-95 Unified Namespace already built for cell 1 | - |
| PLC link to real TwinCAT | `pyads` (ADS) or OPC UA | yes (client side) | DT-10: the twin talks to the real PLC | - |
| Time series | DuckDB (local) ↔ InfluxDB 2.7 (container) | yes | the `stf-factory` twin already mirrors both | - |
| Events / genealogy | SQLite | yes | orders, alarms, the per-cookie bake log | - |
| API | FastAPI + Uvicorn, WebSocket frames | yes | reuse `services/api` pattern from `main` | Kit services |
| AI | PyTorch 2.11 (MPS backend), ONNX Runtime 1.29 (CoreML EP) | yes (Metal GPU, Neural Engine) | QC classifier on renders; anomaly models on telemetry | Isaac / TAO |
| Containers | OrbStack or Colima (Docker API) | yes | InfluxDB, Grafana, OpenPLC, CODESYS runtime | - |
| Tests / CI | pytest, ruff, `tsc`, GitHub Actions (macos-14+ runners are arm64) | yes | same as `main` | - |

## 2. What does NOT run on this Mac, and the replacement

| Tool | Why not | Replacement in this plan | Path back to it |
|---|---|---|---|
| NVIDIA Omniverse Kit / USD Composer | Linux or Windows + NVIDIA RTX GPU only | OpenUSD files + Blender + three.js | DT-9: open the same USD stage on a cloud RTX machine, stream to the Mac browser |
| NVIDIA Isaac Sim 5 / Isaac Lab | Linux or Windows; minimum RTX 4080 16 GB | MuJoCo (CPU) or Genesis (Metal) | MJCF + USD stay portable; Newton accepts MJCF |
| Omniverse Replicator | part of Omniverse | Blender `bpy` scripted renders | same labels format (COCO), re-render later if wanted |
| TwinCAT 3 XAE / XAR | Windows x64 (XAR also TwinCAT/BSD on x86) | MatIEC SIL of the same ST program | DT-10: TwinCAT on a Windows x64 PC or a Beckhoff IPC; twin via ADS / OPC UA |
| TwinSAFE editor | part of TwinCAT | safety logic as a separate SIL module from `safety/safety_functions.csv` | real TwinSAFE project at DT-10 |
| SISTEMA (IFA) | Windows | `safety.pl_estimate()` (existing, typical data) | Windows VM or a colleague's PC for the formal PL verification |
| CODESYS IDE | Windows x64 | not needed for the SIL path | Windows 11 ARM VM (x64 emulation) if a CODESYS project is wanted |

**A Windows-on-ARM VM (Parallels or UTM) does not solve TwinCAT.** The TwinCAT runtime needs a real-time x64 kernel and does not
run on ARM Windows. The engineering IDE might install under x64 emulation, but it cannot run the program.

## 3. Why OpenUSD is the centre

- **One stage, three viewers.** A `.usd` stage feeds Blender (USD import), Apple tools (`.usdz`) and, later, Omniverse/Isaac Sim, unchanged. The web twin gets a `.glb` exported from the same tessellation.
- **Structure that matches the model.** Layers per module (`M1_loop.usda` … `M10_safety.usda`) under one root, `/STF2/<module>/<group>/<part>`.
  - Custom attributes per prim: `stf:tag` (Q41, TC1, …), `stf:hw`, `stf:module`, `stf:assumed`.
  - The I/O list, the PLC tags and the 3D parts therefore share one key.
- **Instancing.** Screws, brackets, pucks and cookies are USD instanceable prototypes, so 1,000 screws cost one mesh.
- **Units and axes.** `metersPerUnit = 0.001` (the model is in mm) and `upAxis = Z` (the model's frame), so no transforms are guessed.
- **Animation.** The 40 s timeline can be written as USD time samples (`xformOp:transform` per frame) for offline review. The live twin streams transforms over WebSocket instead.

## 4. Physics: what actually needs a solver

The STF-2 motion is **prescribed**:
- the chain, the band, the depositor rolls and the cutting wire follow the master axis (electronic gearing);
- the deltas follow their inverse kinematics;
- the pistons follow their valve and stroke time.

A rigid-body solver would only add drift to motions that are exact by construction. The twin therefore moves them
**kinematically**, from the same functions `motion.py` uses, and asks a physics engine only where contact decides the outcome:

| Step | Question | Engine |
|---|---|---|
| Delta C pick off the moving band | does the twin-cup grip hold at the band speed + vacuum build-up 0.8 s? | MuJoCo |
| Place into the passing puck | does the cookie seat in the nest (Ø48 × 2 chamfer) at the place speed? | MuJoCo |
| Reject kicker / drawer | does a kicked cookie land in the bin and not on the deck? | MuJoCo |
| Cassette fill (loose cookies) | packing fraction (`PACKING` 0.5 [assumed]) and jam risk | MuJoCo, or Genesis for many seeds |
| Dough extrusion, spreading in the oven | not rigid-body; already a 1-D bake model (`oven.py`) | own model |

MuJoCo on the M4 CPU handles these small scenes far faster than real time. Genesis on Metal is for sweeps
(thousands of drop seeds for the packing fraction).

## 5. Memory budget (24 GB unified)

| Process | Typical | Note |
|---|---|---|
| macOS + browser + editor | 6-8 GB | |
| FreeCAD export of the precise model | 3-5 GB | **batch only**, not while Blender renders |
| USD stage (tessellated, instanced) in memory | 0.5-1.5 GB | budget ≤ 3 M triangles for the viewer LOD |
| Web twin (three.js, GLB) | 0.5-1.5 GB | LOD: precise parts only for the module in focus |
| Blender, Cycles render of the full line | 4-8 GB | Metal shares the same memory; render one module at a time if tight |
| Plant service + MatIEC PLC + API | < 1 GB | |
| Mosquitto, OPC UA server | < 0.2 GB | |
| Container VM (InfluxDB, Grafana, OpenPLC) | 2-4 GB | optional; DuckDB needs none |
| PyTorch training (MPS), small CNN | 2-4 GB | not at the same time as a Cycles render |

The live set (plant + PLC + API + broker + web view + DuckDB) fits in about 4 GB. The heavy jobs (FreeCAD export,
Blender renders, training) each run on their own, which the generated, file-based pipeline makes natural.

## 6. Python environment

One virtual environment for the twin (`uv` or `python -m venv`). The FreeCAD steps keep using FreeCAD's bundled Python.

```
numpy  pyyaml  pydantic>=2          # model, config
usd-core  trimesh  pygltflib        # scene export (USD, GLB)
mujoco                               # contact physics
fastapi  uvicorn[standard]  websockets
asyncua>=2.0                         # OPC UA (as on main)
paho-mqtt>=2.1  protobuf             # Sparkplug B (as on main)
duckdb  influxdb-client              # time series
fmpy                                 # optional: oven model as FMU
torch  torchvision  onnx  onnxruntime   # vision (MPS / CoreML)
pyads                                # DT-10 only
pytest  ruff
```

Homebrew: `mosquitto`, `llvm`, `lld`, `wasi-libc`, `wasi-runtimes` (MatIEC → WASM, as on `main`), `node` (web).
Applications: FreeCAD 1.1, Blender 5.2, OrbStack (or Colima).
Optional: Webots (installed) as a second robot simulator for ROS 2 work; it is not needed by this plan.

## 7. Costs

Everything in sections 1-6 is free and open source, except optional commercial runtimes (CODESYS) and the
cloud GPU of DT-9 (hourly rental of an RTX-class instance).

## Sources (checked 2026-10)

- Isaac Sim requirements (Linux / Windows, RTX GPU): https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html
- Newton physics (macOS CPU only): https://github.com/newton-physics/newton
- Genesis (CPU, NVIDIA, AMD, Apple Metal backends): https://github.com/Genesis-Embodied-AI/genesis-world
