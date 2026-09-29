---
name: stf-cad-pipeline
description: How stf-cad/hbw generates FreeCAD, drawings and the browser scene from one parameter table
metadata:
  type: project
---
`~/workspace/stf-cad/hbw/` is the generator for the High-Bay Warehouse
(ft 536631). Single source of truth = the `P` dict in `hbw_model.py`.

- `hbw_model.py` — 170 primitive solids (v2: 12 slots + moulds + belt cover) + `check()`, a clearance proof
  (96 poses, pairwise AABB, support-touch, plate bounds) PLUS `check_carry()`,
  which asserts the carried mould touches ONLY the fork table's top face. The
  `("mould","fork")` pair is deliberately NOT whitelisted — that whitelist being
  too broad is what let the mould sink into the arm and the mast unnoticed.. Nothing downstream
  runs unless `check()` passes.
- `hbw_frames.py` — decomposes parts into world / travel(+X) / lift(+Z) /
  fork(+Y) frames; `verify()` proves the decomposition reproduces `build()`.
- `hbw_freecad.py` — headless FreeCAD → `STF_HBW.FCStd` (nested `App::Part`
  containers ARE the joints) + `STF_HBW.step`. Re-verifies against the model.
  Run with `/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd`
  (FreeCAD 1.1.3). Headless has no `ViewObject`, so the .FCStd carries no
  colours — colour lives in the `STF_Colour` property and in the JSON export.
- `hbw_draw.py` — dimensioned orthographic SVGs.
- `hbw_export.py` — `stf-hw/web/public/hbw_parts.json` (HBW + VGR + factory).
**web/vite.config.ts sets `base: "/stf/"`.** Any fetch of a public asset MUST
go through `import.meta.env.BASE_URL` — an absolute `/hbw_parts.json` 404s behind
that base, and the dev app lives at http://localhost:5173/**stf/**, not the root.
`src/vite-env.d.ts` carries the vite/client types so `import.meta.env` compiles.

**A FreeCAD document needs a ViewProvider for EVERY object, containers included.**
An `App::Part` with no view provider leaves its children with no visibility state
and the 3D view opens completely blank — that was the "renders nothing" bug.

- `stf_freecad.py` — the WHOLE factory as a coloured, articulated .FCStd
  (320 solids, 12 joint containers). Colours come from `fcstd_colour.py`, which
  writes GuiDocument.xml and one 40-byte ShapeAppearance blob per object directly
  into the zip — headless FreeCAD has no ViewObject, so this is the only way.
  Blob format: uint32 count=1, four LE uint32 colours packed 0xRRGGBBAA
  (ambient/diffuse/specular/emissive), float32 shininess, float32 transparency,
  12 zero bytes. Verified against the user's own STF.FCStd.
- `stf_gltf.py` — `STF_Factory.gltf`, whole table, ARTICULATED (joint nodes),
  hand-rolled writer, no deps. Factory frame, Z up, **mm by default** because
  FreeCAD works in mm (`--units m` for three.js/Blender). Verified: FreeCAD 1.1.3
  imports it via `Import.insert` as 278 named objects. glTF meshes cylinders as
  32-gons — for exact B-rep tell the user to open `STF_HBW.step`.

Parts carry a `mech` tag that makes the drivetrain animate off the pose rather
than being decoration: `thread:<joint>` (spindle, turns at travel / 4 mm lead),
`pulley` / `spin:*` (drum or gear, turns with the belt), `belt` (strip whose
surface scrolls). The renderer reads it; the model owns it.

Browser side: `web/src/scene/HbwCad.tsx` renders the JSON and articulates it.
Two rendering gotchas already paid for: a `CanvasTexture` needs `repeat` set from
the strip length or the whole belt is one band and reads as static, and texture
`offset` runs OPPOSITE the surface so it must be negated.
Both views share ONE `<Canvas>` in `App.tsx` — mounting a second Canvas loses
the WebGL context. Serves the thesis in [[stf-single-source-thesis]].

**GROUNDING (`grounding.py`, shared by all four modules).** The old support
test only asked "does this part touch the thing it names?", and naming `plate`
skipped even that - so a part could declare the base plate while floating 90 mm
up and pass. That is why modules looked like they hung in mid-air. The rule now:
support=="plate" means the underside must actually be at z~0; otherwise the part
must touch its support AND have solid material directly beneath its footprint,
OR be listed in that module's `CANTILEVERS` set (bolted to a vertical face, with
>=40 mm2 of real face contact so an edge-touch cannot pass as a bolt). It found
13 genuinely airborne parts and 2 edge-supported ones; each module now carries an
explicit cantilever list.

**THE RULE THAT MATTERS MOST (learned the hard way, twice):** a moving thing's
position must be DERIVED from the geometry that carries it, never written as a
literal. Both bugs the user caught by eye were literals that stopped following
their parameter: `TUBE_Y` did not follow `RAIL_Y` and drove the mast through the
rack; the renderer's carried mould was pinned at fork-frame y=360 while the fork
table moved to y=210, so it was drawn 150 mm deep inside the stored moulds. It
now reads the fork_table part's own geometry.

**And: a load in transit needs its OWN collision group.** The carried mould was
in the same group as the stored moulds, so `(mould, rack)` and `(mould, mould)`
were whitelisted for it too and the checks were structurally blind. Groups
`load` / `load_wp` may touch the fork table and their own cookie, nothing else.
Same pattern now in vgr_model (`held_cookie`) and oven_model (`tray_load`).

**`check_path()` sweeps the real cycle** — 24 legs x 14 steps, every moving
solid against every other. Named stops alone cannot catch a load that is clear
at both ends of a move and passes through a post in between. Whether the fork is
carrying is DERIVED from the pose (table top above the support surface), not
flagged per leg — flagging put the transfer at the end of a move and modelled
the load sinking through the belt.

**Two traps already paid for:** the factory table and the module plates had
COPLANAR top faces at z=0 — that was the on-screen flicker; the table top now
sits at z=-10. And `TUBE_Y` was an absolute that did not follow `RAIL_Y`, so
shrinking the plate drove the mast through the rack — derive it from the rail.

**v3 (2026-09-06): plate 860x640** (the empty band between the PCB and the rail
was removed by moving RAIL_Y 360->210 and RACK_Y0 440->290; their 80 mm offset
must be preserved or the fork's bay stop stops being 115). Factory plate
1240x920, warehouse at X 575..1215. Belt motor now sits UNDER the belt driving
the far drum through a toothed belt.

**v2 geometry decisions worth not re-deriving** (2026-09-06): plate 900×620 with
the front half kept clear for the oven/VGR/sorting chain; rack at the back with
4 bays × 3 rows; belt runs along ±Y at x=665 with the crane hand-over at y=245
and the VGR hand-over at y=75; Ausleger is BIDIRECTIONAL (+115 into a bay, −115
onto the belt) and its arm shares the fork table's z band so both pass the same
40 mm gap while staying under the mould. Two clearances that are easy to break:
the identification tunnel must END before y=220 (the Ausleger motor) or the
crane cannot descend to the belt without a forbidden lift band; and the belt
drums must be on stub axles per strip — a through shaft crosses the 40 mm gap
and blocks the fork.

`factory_layout.py` places the module on the full table: the warehouse is
designed and proven in its OWN module frame (travel +X, Ausleger +Y) and put on
the 1400×1010 factory plate by a rigid +90° rotation about Z plus a translate
(module (x,y) -> factory (-y+1390, x+55)). A rigid transform cannot introduce
interference, so the clearance proof carries over — never re-derive geometry in
factory coordinates. It also reserves footprints for VGR / oven / sorting per
the user's sketch (items 5 / 6 / 7).

**Not yet done:** `factory.layout.yaml` still holds the OLD geometry, so the CAD
view runs a scripted demo cycle rather than live kernel joints. See
[[stf-hbw-geometry-facts]] for what changes when that migration happens.

Headless apps on this Mac (not on PATH, call the bundle paths):
`/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd` (FreeCAD 1.1.3,
needed for `import FreeCAD`) and `/Applications/Blender.app/Contents/MacOS/Blender -b -P x.py`
(Blender 5.2; its glTF importer is a good independent validator).
`stf_gltf.build_roots(g, pose)` is the shared node tree for FreeCAD .gltf and
web .glb (`stf_web_glb.py`: Y-up, metres, PBR, sRGB->linear colours). glTF
baseColorFactor is LINEAR - writing hex straight in washes colours out.
`hbw_export.py` / `stf_gltf.py` now guard `main()`; importing them is side-effect free.

**Precise CAD (2026-09-27):** `detail.py` turns each proven envelope into real
B-rep (chamfered blocks, helical threads, spring, cone cup, toothed belt loop) and
ASSERTS every shape stays inside its envelope - so detail can only remove
material and every proof still holds. Use `optimalBoundingBox()` for that
check: `BoundBox` includes spline poles and overstates threads/fillets by mm.
One command: `freecadcmd build_cad.py` -> stf-factory/cad/STF_Factory.FCStd + .step
and the precise web glb. freecadcmd runs scripts with `__name__` = module name,
not "__main__". Traps found: a single helix sweep >~100 turns fails in
MakePipeShell (stack 10-turn segments); fillets on blocks tessellate to ~9k
tris each (use chamfers); tessellate threads with MeshPart angular deflection
(27k -> 5k tris / 100 mm). Plain-python `stf_web_glb.py` now refuses to
overwrite the precise glb unless `--envelope`.

**FCStd "shows nothing" - real cause (2026-09-27, found only by opening in the GUI):**
an EMPTY `<Camera settings="">` makes FreeCAD open zoomed into the origin corner, and
visible App::Origin helpers (21 containers x 7) clutter it. `fcstd_colour.colourise()`
now writes `iso_camera(bbox)` and hides ORIGIN_TYPES. Headless reopen proves nothing
about display: verify with the GUI binary `/Applications/FreeCAD.app/Contents/MacOS/FreeCAD
script.py` (script ends with `Gui.getMainWindow().close()`) + `ActiveView.saveImage()`.
