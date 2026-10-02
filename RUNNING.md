# Running the STF Digital Twin

Three ways to see the twin, from least to most setup.

## 1. Terminal — watch the kernel run (no browser, no Node)

```bash
make install                 # one time: venv + Python deps
make sim SLOT=B2 OP=retrieve # real time (~62 s)
make sim SLOT=A1 OP=store FAST=1   # same physics, runs flat out
```

Renders joint positions, tracking error, motor phase/health, belt and sensors
live in the terminal. This is the kernel itself; everything else is a view onto it.

## 2. Browser — the live 3D twin

Two processes. **Backend** (runs the kernel, streams state):

```bash
make install     # one time
make api         # FastAPI + WebSocket on http://localhost:8000
```

**Frontend** (3D scene) in a second terminal:

```bash
make web         # installs web deps if needed, serves on http://localhost:5173
```

Open <http://localhost:5173>. Pick a slot, then:

- **Retrieve / Store** — drive just the crane to/from a bay.
- **Run full cycle** — the whole material flow: the crane pulls a carrier from
  the bay, sets it on the belt, the belt conveys it to the gripper end, and the
  VGR picks it and places it on the delivery stand. Watch the coloured cookie
  carrier ride from station to station.

The whole scene is built from `packages/stf_layout/factory.layout.yaml` via
`GET /layout`, so moving a shelf in that file moves it in the 3D view.

**Demo speed.** A full cycle runs ~2 minutes at true hardware speed (14.27 mm/s).
To watch it faster, start the backend with a time multiplier — physics is
unchanged, only the wall-clock pacing:

```bash
STF_TIME_SCALE=6 make api      # a full cycle in ~20 seconds
```

API surface:

| | |
|---|---|
| `GET /layout` | scene descriptor the front end builds from |
| `GET /health` | liveness + connected client count |
| `GET /orders` | recent order history |
| `POST /command` | `{"op":"retrieve","slot":"B2"}` |
| `WS /ws` | live world frames at ~30 Hz |

Drive it without the UI:

```bash
curl -X POST localhost:8000/command -H 'content-type: application/json' \
  -d '{"op":"retrieve","slot":"C3"}'
```

## 3. Tests — prove the physics

```bash
make test        # 75 tests: determinism, golden trajectories, layout invariants
make plan SLOT=B2 OP=retrieve   # print a planned trajectory with real timings
```

## Infrastructure (not required yet)

`make up` starts Redis + TimescaleDB + Mosquitto via Docker. Nothing consumes
them until the hybrid data layer lands (plan phase 2), so you can skip it for
now. It needs a container runtime — on macOS, `brew install colima docker
docker-compose && colima start`.

## Notes

- The crane genuinely moves at 14.27 mm/s (the real lab calibration), so a
  retrieve takes ~45-75 s depending on the slot. That is correct, not slow; the
  old simulator's ~8 s cycle came from a hardcoded speed 7x too fast.
- If the 3D canvas ever comes up black after many hot reloads during
  development, it is WebGL context exhaustion in the browser tab — open a fresh
  tab. It does not happen in normal use.
