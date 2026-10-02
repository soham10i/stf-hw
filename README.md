# STF digital twin

[![CI](https://github.com/soham10i/stf-hw/actions/workflows/ci.yml/badge.svg)](https://github.com/soham10i/stf-hw/actions/workflows/ci.yml)
[![Pages](https://github.com/soham10i/stf-hw/actions/workflows/pages.yml/badge.svg)](https://soham10i.github.io/stf-hw/)

**Live demo: [soham10i.github.io/stf-hw](https://soham10i.github.io/stf-hw/)** (the 3D twin) and the
[operations dashboard](https://soham10i.github.io/stf-hw/dashboard.html). Both run entirely in the browser.

A digital twin of the fischertechnik *Fabrik Simulation 24V* (536634): the warehouse (HBW), the vacuum
gripper robot (VGR), the oven with its turntable, and the sorting line. One parametric model is the source
of truth for the CAD, the kinematics, the I/O, the PLC program and the analytics. Nothing is exported unless
its proofs pass.

## What is where

| Path | What |
|---|---|
| `stf-cad/hbw/` | The model and its proofs (geometry, kinematics, wiring, safety, I/O, the generated PLC program, virtual commissioning, health, lifecycle, throughput, OT security, hardening) and the analytics (`month.py`, `grid.py`, `ml/`). `validate.py` re-proves everything. |
| `stf-cad/hbw/sil/` | Upgrade 13: the PLC program as a complete IEC 61131-3 project, compiled by MatIEC to WebAssembly and run against an I/O-level plant (`web/src/sil/`). `python3 -m sil.run` proves it. |
| `stf-cad/hbw/aas/` | Upgrade 14 (step 1): Asset Administration Shells for the cell, its 9 part types and its 2 AI models, each submodel from its official IDTA template, verified against the AAS v3 metamodel. |
| `stf-cad/hbw/vision/` | Upgrade 15: vision inspection - a renderer of camera images from the model, a CNN trained only on them, exported to ONNX and to the browser (`web/src/vision/`). |
| `packages/` | The physics kernel (`stf_kernel`) and the layout (`stf_layout`) that the live simulation runs on. |
| `services/api/` | The live API: `/layout`, `/orders`, `/health`, `POST /command` (operator only, see `docs/SECURITY.md`) and the `/ws` frame stream. |
| `web/` | The 3D twin (`index.html`) and the operations dashboard (`dashboard.html`): React, three.js. |
| `docs/` | `UPGRADE_PLAN.md` (Upgrades 1-15, as built), `VALIDATION.md`, `SECURITY.md`. |
| `tests/` | Kernel, layout, golden trajectories, the API's access control. |

The twin shows one machine, **Upgrade 12**, which contains every upgrade before it. Its **PLC program (live)** panel runs
the generated control program, compiled by an IEC 61131-3 compiler to WebAssembly, in your browser (Upgrade 13), and
its **Vision inspection** panel runs a defect-detection CNN trained only on rendered images (Upgrade 15), and its
**Asset Administration Shells** panel browses the cell's Industry 4.0 digital identity (Upgrade 14). Each upgrade's view of it is a
side panel: safety, remote I/O, the PLC program and HMI, commissioning, health, AI maintenance, microgrid,
throughput, OT security and defence in depth. The **Components** views show the parts one by one.

## Run it

```bash
make install          # .venv with the API and dev dependencies
make api              # the live API on 127.0.0.1:8000
cd web && npm install && npm run dev      # http://localhost:5173/stf/ (this machine only)
```

To share it, build and tunnel the **production** build, never the dev server:

```bash
cd web && npm run build && npm run preview     # http://localhost:4173/stf/
ngrok http localhost:4173
```

A tunnelled twin is read-only. Commands need the operator's machine or `STF_API_TOKEN` (see `.env.example`).

### The public demo

The twin does not need the API: the machine, its PLC cycle and every panel are built from the generated
files in `web/public`. `npm run build:pages` builds it without the API (`VITE_LIVE_API=0`, into
`web/dist-pages`), with its security policy in the page itself. `make pages` serves that build locally as
GitHub Pages will. Every push to `main` publishes it (`.github/workflows/pages.yml`); CI runs the tests,
lint, type check and dependency audits on every push (`ci.yml`).

## Regenerate the data

From `stf-cad/hbw`, with the project's venv (`../../.venv/bin/python`):

```bash
STF_VARIANT=up12 python3 hbw_export.py     # the machine the twin shows (runs every proof first)
python3 validate.py                        # re-prove every variant, mutation tests, robustness (~25 min)
```

The analytics have their own scripts: `month.py`, `grid.py`, `ml/train.py` + `ml/tune.py`, `throughput.py`,
`security.py`, `hardening.py`. Each script's docstring says which variant to run it with.

## Tests

```bash
make test             # pytest
make lint             # ruff
cd web && npx tsc --noEmit -p .
```
