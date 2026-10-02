---
name: stf-factory-repo
description: ~/workspace/stf-factory is the production/dashboard twin; its kinematics are the OLD pre-sketch layout, not stf-cad's
metadata:
  type: project
---
`~/workspace/stf-factory` (own git, no remote) is Soham's standalone production
twin: FastAPI `twin/` on **:8100**, React/R3F web on **:5200**, safety rules,
telemetry, InfluxDB/DuckDB, maintenance tab. Soham calls it the home for the 3D
CAD model (2026-09-26).

Its `packages/stf_layout/factory.layout.yaml` was forked from stf-hw BEFORE the
sketch rearrangement, so it is a DIFFERENT machine from stf-cad: 9 slots (not
12), conveyor as a front lane (not at the travel end), HBW travel 0-460 / lift
0-300 / fork -70..90, VGR reach 0-180 / plunge 0-160, no oven/sorting modules.
Its `render.meshes` .glb paths were declared but never existed.

**Why:** dropping stf-cad meshes onto its runtime would mis-place every joint -
the exact drift [[stf-single-source-thesis]] is about.

**How to apply:** the CAD view there (tab "CAD Model", `web/src/scene/CadModel.tsx`)
is fed by `stf-cad/hbw/stf_web_glb.py` -> `web/public/assets/stf_factory.glb` +
`stf_parts.json` and is driven by its own sliders, not telemetry. Migrating the
runtime to the stf-cad layout is an open decision for Soham. The preview tool
reads launch.json from stf-hw, which has a `factory-web` entry for :5200.

**2026-09-27:** `stf-factory/cad/` now holds the generated STF_Factory.FCStd/.step
(see [[stf-cad-pipeline]]); CAD tab glb is the precise tessellation (~150k tris,
5.7 MB). Open item: longer VGR arm at home (swivel 0) overhangs the table's back
edge by 130 mm - home angle depends on where I3 really sits (lab measurement).
The 5173/5200 dev servers started via preview_start die when the preview session ends;
a viewer showing "hbw_parts.json missing" with the file present = server down.
