# STF-2 digital twin - setup on the M4 Mac

Step by step, from a clean macOS (Apple Silicon) to a running twin. Items marked **(today)** already work. Items marked
**(after DT-n)** describe the command the phase adds; they do not exist yet.

## 0. Check the machine

```bash
sysctl -n machdep.cpu.brand_string hw.memsize      # Apple M4, 25769803776 (24 GB)
sw_vers -productVersion                            # macOS 15 or newer
```

## 1. Base tools (Homebrew)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"   # if missing
brew install git python@3.13 node mosquitto llvm lld wasi-libc wasi-runtimes bison flex autoconf automake libtool
brew install --cask freecad blender orbstack        # orbstack: Docker API for InfluxDB / OpenPLC (or: brew install colima docker)
```

Installed on this Mac today: FreeCAD 1.1.3, Blender 5.2.1, Node 25, Mosquitto 2.1.2, LLVM/LLD 23, wasi-libc. Webots R2025a is also
installed but is not needed.

## 2. The repository and its model chain (today)

```bash
cd ~/workspace/stf-hw-stf2/stf-cad/line2
python3 line_model.py && python3 oven_ctrl.py && python3 joints.py && python3 plc_io.py \
  && python3 safety.py && python3 line_sim.py && python3 bom.py && python3 elec_draw.py \
  && python3 line_draw.py && python3 oven_draw.py          # every proof, then the drawings (~6 min)
FC=/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd
$FC line_cad_precise.py                                    # precise CAD -> ~/workspace/stf-factory/cad/line2_precise (~30 min)
python3 motion.py                                          # 40 s timeline + collision sweep (~4 min)
$FC validate_motion.py; cat /tmp/validate_motion.out       # PLAYER == MODEL
python3 verify_plan.py                                     # +-20 % sensitivity of 96 values (~1-2 h)
```

Each script refuses to write its outputs if one of its proofs fails.

## 3. Look at it (today)

- **FreeCAD:**
  1. Open `~/workspace/stf-factory/cad/line2_precise/STF2_Precise.FCStd`.
  2. Run Macro → Macros… → `motion/play_motion.FCMacro` (in the same folder).
  3. Use the slider and Play / Pause. The oven panel shows kW, phase currents, duty and TC per zone.
- **Drawings:** open `stf-cad/line2/blueprints/index.html` in a browser (layout, M1-M10, M3_thermal, M3_control).

## 4. The twin's Python environment

```bash
cd ~/workspace/stf-hw-stf2
python3.13 -m venv .venv-twin && source .venv-twin/bin/activate
pip install --upgrade pip
pip install numpy pyyaml "pydantic>=2" usd-core trimesh pygltflib mujoco \
            fastapi "uvicorn[standard]" websockets "asyncua>=2.0" "paho-mqtt>=2.1" protobuf \
            duckdb influxdb-client fmpy torch torchvision onnx onnxruntime pytest ruff
python -c "from pxr import Usd; import mujoco, torch; print(Usd.GetVersion(), mujoco.__version__, torch.backends.mps.is_available())"
```

The last line should print the USD version, the MuJoCo version and `True` (Metal available to PyTorch).
`usd-core` and `mujoco` ship native arm64 wheels, so nothing compiles.

FreeCAD steps (DT-1 export) run in FreeCAD's own Python (`freecadcmd`). They write files; the venv reads them.

## 5. MatIEC (the IEC 61131-3 compiler for the SIL PLC)

```bash
mkdir -p ~/workspace/stf-hw/.cache && cd ~/workspace/stf-hw/.cache
git clone https://github.com/beremiz/matiec.git && cd matiec
export PATH="$(brew --prefix bison)/bin:$(brew --prefix flex)/bin:$PATH"
autoreconf -i && ./configure && make -j8
./iec2c -h | head -3                                     # the compiler answers
export STF_MATIEC=~/workspace/stf-hw/.cache/matiec       # the same variable sil/build.py on main uses
```

The `STF_CLANG`, `STF_WASM_LD` and `STF_WASI` defaults of `stf-cad/hbw/sil/build.py` already point at the Homebrew
`llvm`, `lld` and `wasi-libc` installed in step 1.

## 6. Broker and time series

```bash
brew services start mosquitto        # development only; DT-5 writes the TLS + ACL config as uns/broker.py on main does
docker run -d --name influx -p 8086:8086 \
  -e DOCKER_INFLUXDB_INIT_MODE=setup -e DOCKER_INFLUXDB_INIT_USERNAME=stf \
  -e DOCKER_INFLUXDB_INIT_PASSWORD=stf-dev-password -e DOCKER_INFLUXDB_INIT_ORG=stf \
  -e DOCKER_INFLUXDB_INIT_BUCKET=line2 -e DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=stf-dev-token influxdb:2.7   # optional
```

Without InfluxDB the twin records to DuckDB and SQLite files, like the `stf-factory` twin already does.

## 7. Run the twin (after DT-1 … DT-8)

```bash
source .venv-twin/bin/activate && cd stf-cad/line2
$FC twin/export_scene.py                       # DT-1: twin/out/stf2.usda, .usdz, .glb, scene_index.json
python3 -m twin.sil.build                      # DT-4: plc/*.st -> IEC -> MatIEC -> libplc + plc.wasm
python3 -m twin.plant.serve --plc sil --speed 1 # DT-3/4: plant + PLC on :8200, WebSocket /ws/frames
python3 -m twin.opcua.server &                 # DT-5: opc.tcp://localhost:4840/stf2
python3 -m twin.uns.edge &                     # DT-5: Sparkplug B -> Mosquitto
cd ../../web && npm install && npm run dev     # the 3D twin + dashboard
open twin/out/stf2.usdz                        # Quick Look: the line in AR-ready USDZ
blender -b -P twin/render/render_qc.py         # DT-7: synthetic QC images (Cycles on Metal)
twin/run_all_checks.sh                         # every gate (see ROADMAP.md, Acceptance)
```

## 8. Keeping inside 24 GB

- Run the heavy jobs **one at a time**: the FreeCAD precise build (3-5 GB), Blender Cycles renders (4-8 GB) and PyTorch training (2-4 GB).
- The live set (plant + PLC + API + broker + browser view) needs about 4 GB.
- In OrbStack, cap the container VM at 4 GB.
- `verify_plan.py` starts one process per core (10). Each runs the full proof chain, so close Blender while it runs.

## 9. Optional: Omniverse / Isaac Sim (DT-9)

They don't run on macOS. To use them on the same stage:
1. Rent a cloud instance with an NVIDIA RTX GPU (Linux).
2. Install Isaac Sim / USD Composer there.
3. Copy `twin/out/` (or the repository) to the instance.
4. Open `stf2.usda`.
5. View it on the Mac through the Kit app streaming web client.

Stop the instance when done; it is billed per hour.
