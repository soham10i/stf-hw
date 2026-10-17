# STF Digital Twin — Ground Truth & Working Memory

**Purpose of this file:** single durable reference for everything verified about
the real machine, every coordinate decision taken, and every known gap. Read
this FIRST in any future session before changing geometry, layout, or
choreography. Do not re-derive facts that are written here; do not trust
recalled numbers that are not.

Last updated: 2026-09-06 (HBW re-derived from the ft manuals; CAD generator
built). Next: migrate `factory.layout.yaml` to the generated HBW geometry —
that is the change that regenerates `tests/golden/`. See §7.

---

## 1. Sources of truth — and their hard limits

| Source | What it gives | What it does NOT give |
|---|---|---|
| `docs/536634-Fabrik_Simulation_24V.pdf` (42 p didactics booklet) | I/O assignments (Belegungsplan), process sequences, module inventory, a few perspective photos (Abb. 7 HBW, p18 VGR, Abb. 9 p31 processing station) | **No dimensions.** No base-plate layout, no module footprints, no distances, no heights. It is a worksheet, not the construction manual (Aufbauanleitung). |
| User photos (annotated HBW module; full tabletop factory) | Real arrangement of the user's machine: what sits left/right of what | Perspective, no scale. Distances are estimates. |
| YouTube `youtu.be/cm4XQ1Y39vM` | — | **Never watchable** (no video tool). No data was ever taken from it. Any frame stills from it would help. |

**Consequence:** every millimetre coordinate in `factory.layout.yaml` is an
*estimate from photos*, except the values pinned by the Belegungsplan logic
(axis directions, reference switches, sensor roles) and the drive data
(75 pulses/rev, 4 mm spindle pitch, 214 rpm → 14.27 mm/s, from
`docs/144643-Encodermotor24V.pdf` + the lab calibration). When the user
reports a placement error, the fix is a YAML edit — the scene, planner and
tests all follow the YAML.

**Would instantly improve fidelity:** the official fischertechnik
Aufbauanleitung (construction manual) for 536634, or 3–4 top-down/side
photos of the real table with a ruler, or stills from the video.

## 2. The real machine — module map (confirmed from photos)

The factory is **several dark base plates chained on a big white table**, not
one slab. Full-factory photo (`img3`, 1832×1098, perspective/no scale) adds:

- The "tower" at the HBW belt end in wide shots is the **crane mast at the
  handover** (carriage photographed holding a white carrier there) — NOT the
  VGR. The VGR is the separate twin-silver-column tower with the Drehkranz
  gear base and a **long telescoping arm** (≈3× tower width), spring cup
  gripping a **bare disc** (blue disc visible, no tray).
- Sorting plate: a row of **3–4 red pneumatic pushers** + red housing on the
  front-left plate. Oven = red Brennofen housing on the processing plate.
  Blue boxes = BT SmartControllers. The processing station has its **own
  pneumatic Sauger portal** (transparent cylinder + blue hoses, M5).
- Which belt end the VGR stands at reads left/right differently across
  camera angles; the structural fact (user's annotated photo): **VGR tower
  fixed at the end of the HBW belt**, belt along the rack front.

1. **HBW module (Hochregallager)** — user's annotated photo:
   - Black 3×3 rack at the **back** (bays hold coloured disc workpieces —
     red / blue / white — on red rails).
   - Stacker crane in the **middle lane** (travel rail along the rack face).
   - Conveyor belt along the **front**, running toward the right.
   - **VGR twin-column tower fixed at the right end of the belt** (labels
     I4/I5 nearby).
   - Motors per the OFFICIAL Belegungsplan (536631 manual, authoritative —
     an earlier reading of the annotation had them mismapped): **M1 Q1/Q2 =
     belt (tower end of the belt), M2 Q3/Q4 = travel (left end of the rail),
     M3 Q5/Q6 = lift (mast base), M4 Q7/Q8 = fork/Ausleger (on carriage)**.
   - Belt spans nearly the whole module front (~560 of the 600 plate, from
     just right of the travel motor to the VGR tower) — the sim's 460 mm
     belt reads visibly "small" next to the storage and must be extended.
2. **VGR module (Vakuum-Sauggreifer, p18 photo)** — twin-column tower, gear
   ring (Drehkranz) at the base, telescoping arm through a clamp carriage,
   spring stem + suction cup. **It grips the bare workpiece disc, not a tray.**
   It is its own small plate, chained at the HBW belt end.
3. **Multi-Bearbeitungsstation mit Brennofen (Abb. 9, p31/p33 photo)** —
   separate plate, on the table **in front of / beside** the HBW module:
   - **Brennofen** = big elevated **red housing** with black slatted top, at
     the **back** of that plate; the **Ofenschieber** slides out toward the
     front (toward the operator/VGR side) carrying the workpiece in/out.
   - Red portal with transparent pneumatic cylinder + blue hoses + suction —
     the station's own Sauger (M5 "Motor Sauger zum Ofen", ref. switch I8).
   - Conveyor through the middle, **Drehtisch** (red rotary table) front
     centre, **Sortierstrecke mit Farberkennung** front-right (big red gear).
   - p15 (chained config): the VSG tower itself may place workpieces on the
     Ofenschieber. Our sim follows this chained variant (VGR serves oven).

### Belegungsplan Bearbeitungsstation mit Brennofen 24V (p6)

| # | Signal | Ref |
|---|---|---|
| 7 | Lichtschranke Ende Förderband | I3 |
| 10 | Referenzschalter Ofenschieber **innen** | I6 |
| 11 | Referenzschalter Ofenschieber **außen** | I7 |
| 12 | Referenzschalter Sauger (Position Brennofen) | I8 |
| 13 | Lichtschranke Brennofen | I9 |
| 21/22 | Motor Ofenschieber ein/aus | Q5/Q6 (M4) |
| 23 | Motor Sauger zum Ofen | Q7 (M5) |
| 25 | Leuchte Ofen | Q9 |
| 29 | Ventil Ofentür | Q13 (pneumatic) |

Oven process (p31): VGR places workpiece on **extended** slider → I9
interrupted → door opens → slider retracts → door closes → bake (lamp Q9) →
door opens → slider extends → VGR picks workpiece.

## 3. Current sim world (all mm, factory frame: +Z up, +X along rack face)

- **Rack (re-engineered 2026-08-09, precision pass):** origin (100, 0, 40),
  3×3, **square pitch 120 (8u ft grid)**, envelope **100×60×80** (opening
  w×d×h), rows A..C bottom-up at **z 40/160/280** (photo: 39/159/279 —
  within 1 mm), columns x 100/220/340. Rack top = 320 = the module height in
  the Christiani datasheet (**module plate 600×400×320, 8.2 kg**). Uprights
  18 mm on grid lines 40/160/280/400; cap beam rides ABOVE the top opening
  (posts 0..320 + cap 18) so row-C entry clears by 2 mm. Pitch 120 is
  grid-clean, matches both measured pitches (col 138.7 px, row 137.5 px at
  ≈1.15 px/mm) and fits 9 bays + handover into the 600 mm module length.
  - Carrier (Werkstückträger): tray **48×12×48** (base 4 + rim 8), front
    **Aussparung 20 mm recess** facing the aisle (manual: "Aussparung nach
    vorne"); cookie = real workpiece cylinder **Ø40×18** (unchanged).
  - Shelf rails 8 thick × 10 wide at ±22 from bay centre (inner faces ±17):
    tray (±24) overlaps rails 7 mm; fork table (±15) slides between rails
    with 2 mm/side.
- HBW crane: base (0, −55, 0); travel +x **0..460** (columns 100/220/340,
  conveyor/rest **460** — right of the rack, posts end 408, mast clears by
  37); lift +z **0..300** (rows 40/160/280, rest/conveyor **100** = belt
  surface); fork ±y (retracted 5 / carry 10 / **extended 85** / belt −55) —
  at 85 the carrier centre lands at bay centre y=+30 and the 30×8×60 table
  spans exactly 0..60 = bay depth, flush with the rack face.
- Pick/place strategy (planner offsets): approach 10 (table slides 2 mm
  UNDER the rails), **lift 8** (carrier clears rail tops by 8 mm; store
  entry top = slot+38 → 2 mm below the opening top), hover 10, place 5.
- Belt: pose (520, −110, 100), axis −x, length 460 (x 60..520), **width 60**
  (the 48 carrier rides the web between guide rails at ±30); I2 at local
  105 (HBW), I3 at local 15 (VGR); crane deposits at x=460 (local 60), VGR
  picks at x=505 (local 15). **Transfer slot in the web at local 43..77**
  (34 mm, centred on the handover): the 30 mm table lowers through it
  (place 5 → table top 95) while the carrier bridges it 7 mm/side; guide
  rails pause over local 20..100. No table/web intersection anywhere —
  before, a deposit forced the table through a solid web (impossible).
- HBW motor map (Belegungsplan, verified against the 536631 + 536634
  manuals): **M1 Q1/Q2 belt, M2 Q3/Q4 travel, M3 Q5/Q6 lift, M4 Q7/Q8
  Ausleger**; encoders B1/B2 travel, B3/B4 lift; I1/I4 ref, I2/I3 light
  barriers, I5/I6 fork front/back. Sim ids map HBW_X/Y/Z → M2/M3/M4,
  CONV_M1 → M1. Encoder motor 24 V, 25:1, 75 pulses/rev, 214 rpm →
  14.27 mm/s (unchanged).
- VGR: base **(600, −110, 0)** — belt ends at the tower plate edge; swivel
  −95..+135 (conveyor 0 / oven +55 / delivery +105); reach 0..180 (retracted
  10, conveyor **95** → cup at x=505); plunge 0..160 (raised 155 / transit
  145 / pick 100). Suction stack (Vgr.tsx): tray centre = plunge+6 → at pick
  the tray bottom lands exactly on the belt surface (100); cup bottom =
  plunge+30 → touches the cookie top (130).
- Stations (derived = base + R_z(swivel)·(−reach,0,0) @ z=100):
  oven **(545.5, −187.8, 100)**, delivery **(624.6, −201.8, 100)**.
- Module plates (render-only): **hbw (−80,−160) 600×400 — the real plate
  per the Christiani datasheet**; vgr / processing still photo estimates —
  see `factory.layout.yaml → modules:`. Table = white slab under them.
- Cycle: bay → fork → belt → suction → **oven (slider in, door shut, lamp
  4 s, door open, slider out)** → suction → delivery. Oven state broadcast
  per frame: `{slider, door, lamp}`; slider never travels with door closed.
- **Precision audit (2026-08-09):** 36-check clearance script (rows/cols/
  rails/table/fork stops/belt slot/mast sweep/square-path) — all PASS.
  HBW scene constants mirror-checked against the layout; keep them in sync
  when changing geometry (candidates to promote into tests/ later).

## 4. Renderer facts (web/src)

- `coords.ts`: VIEW = 0.01 scene units per mm; factory (x,y,z) → three
  (x, z, y). Joints map: travel/reach→x, lift/plunge→y, fork→z.
- Live state flows through `hot` (mutable, read in useFrame), not React state.
- Scene components: Rack, Hbw, Conveyor, Vgr, Oven, Carrier, ThreadedRod
  (helical-thread spindle, 4 mm pitch, used on all 4 spindles), Factory
  (table, plates, lights, StationStand for non-oven stations).
- App.tsx refetches /layout when the WS hello fingerprint ≠ scene fingerprint
  (stale-backend guard) and retries every 3 s when the API is down.
- Backend must run with `--reload` (`make api`) or it serves a stale cached
  layout — this has bitten us twice.

## 5. Known simplifications vs the real machine (deliberate, fix later)

1. VGR carries tray+cookie as one unit; the real VSG grips the bare disc.
2. "delivery" pad is our stand-in for the real downstream (Drehtisch +
   Sortierstrecke mit Farberkennung — not built yet).
3. VGR/processing module plate sizes remain photo estimates (the HBW plate
   600×400 is datasheet-confirmed).
4. ~~Carrier tray 54×12×54~~ → resolved 2026-08-09: 48×12×48 with the front
   Aussparung, riding on bay rails (see §3).
5. Rack cap beam adds +18 over the 320 module height (posts are exactly
   320); the trade for grid-clean 8u pitch + ≥2 mm clearances everywhere.
6. The processing station's own Sauger portal (M5) is not modelled; the
   chained config (VGR serves oven, p15) is simulated instead.

## 6. Session hygiene

- This file = the memory. Update it in the same commit as any geometry or
  choreography change. `docs/HARDWARE_MODEL.md` keeps the narrative history.
- After layout changes: regen goldens only if HBW/belt kinematics changed
  (store/retrieve are HBW-only); run `.venv/bin/python -m pytest` (87+ tests)
  and `npm run build` in `web/` before reporting done.


---

## 7. HBW re-derivation and the CAD generator (2026-09-06)

Every PDF in `~/workspace/stf-cad/hw/` was read, and the labelled HBW photos
(extended description p.5; booklet Abb. 7 p.22 and the LÖSUNG p.26) were
rendered at 420 dpi and zoomed. Section 1's verdict stands and hardens:
**no supplied document contains a single dimension of the model.** Only bought
parts have datasheet sizes — encoder motor 60×30×30, mini switch 30×15×7.5,
phototransistor 15×15×7.5, colour sensor 30×15×15.

### 7.1 Three findings that change the model

1. **Q3 = "horizontal towards the rack", Q4 = "towards the conveyor"**
   (Belegungsplan HRL, terminals 19/20). Rack and conveyor therefore sit at
   *opposite ends of the travel axis*. The belt does not run parallel to the
   rack face along the front lane, as §3 assumed.
2. **There is no Werkstückträger in this module.** In the photos the white
   container sits directly on the paired red shelf brackets. The 48×12×48 tray
   in §3 is an invention; the fork lifts the bare workpiece from below through
   the gap between the brackets.
3. The crane is a **travelling mast** on a front rail (threaded spindle +
   guide rod, motor at the far end), visibly taller than the rack.

### 7.2 The generator — `~/workspace/stf-cad/hbw/`

One parameter table (`hbw_model.py :: P`) drives everything:

| file | output | self-check |
|---|---|---|
| `hbw_model.py` | 89 primitive solids | `check()` — 68 poses, pairwise AABB, every part touches a named support, nothing off the plate |
| `hbw_frames.py` | world / travel / lift / fork decomposition | `verify()` — frames reproduce `build()` to 1e-9 |
| `hbw_freecad.py` | `STF_HBW.FCStd`, `STF_HBW.step` | re-measures the CAD against `build()` per solid |
| `hbw_draw.py` | dimensioned orthographic SVGs | — |
| `hbw_export.py` | `web/public/hbw_parts.json` | refuses to export unless `check()` passes |

FreeCAD 1.1.3 headless:
`/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd hbw_freecad.py`.
The nested `App::Part` containers *are* the three joints, so the CAD articulates
exactly as the browser scene does. Headless FreeCAD has no `ViewObject`, so the
.FCStd carries no colours — colour rides in the `STF_Colour` property.

### 7.3 Key clearances (these set every other number)

- shelf-bracket gap **30** vs fork table **24** → 3 mm/side; this single pair is
  why the fork can lift from below at all.
- workpiece **Ø45** over that 30 mm gap → 7.5 mm bearing on each bracket.
- the arm rides **26 mm above the table** on a drop bracket, so the arm clears
  the belt surface while only the table dips into the belt's 30 mm centre gap
  (the belt is two parallel strips, not one web).

### 7.4 Not yet done

`factory.layout.yaml` still holds the OLD geometry, so `web/src/scene/HbwCad.tsx`
runs a scripted cycle rather than live kernel joints. Migrating it will change
travel to 120..515, lift to 20..300, fork stops to 0/60/95, drop the carrier
tray, and **regenerate every file in `tests/golden/`**.

Four questions are still open with the user (asked on the build sheet, no answer
yet): conveyor direction, the three measurements that pin the scale (bay pitch,
shelf pitch, workpiece Ø×h), tray or no tray, and whether to model the lift
motor's real right-angle crown gear instead of the direct-drive simplification.
