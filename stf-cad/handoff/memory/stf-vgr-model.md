---
name: stf-vgr-model
description: The VGR module model in stf-cad/hbw/vgr_model.py — kinematics, proven clearances, what is still missing
metadata:
  type: project
---
`vgr_model.py` (started 2026-09-06) is the Vakuum-Sauggreifer, ft 536632, built
in the same style as [[stf-cad-pipeline]]: one parameter table, 24 solids, its
own `check()` — 54 poses, all pass.

**Kinematics are CYLINDRICAL (R-P-P), never cartesian** — the Belegungsplan has
an explicit "Motor drehen im/gegen Uhrzeigersinn":
swivel Q5/Q6+B5/B6 ref I3 · reach Q3/Q4+B3/B4 ref I2 · plunge Q1/Q2+B1/B2 ref I1
· Q7 compressor · Q8 vacuum valve. Frames: world → swivel(Rz) → plunge(+Z) →
reach(−Y). Ranges: swivel −95…+135°, plunge 80…250 (carriage bottom), reach
0…150. **Cup underside = plunge − 28; that is the pick plane.**

**Three things the checker forced, worth not re-deriving:**
- The swivel is a ROTATION, so a rotated box's axis-aligned enclosure is only
  conservative. Everything above the Drehkranz turns as one rigid body, so
  compare those pairs in the LOCAL frame; only rotating-vs-static needs the
  rotated enclosure. And a Z cylinder centred on the swivel axis must be
  exempted or its box inflates by √2 and reports phantom hits.
- The plunge spindle is offset 25 mm off the centreline — on the centreline it
  is exactly where the arm telescopes through.
- The reach axis is now a **spindle beside the arm** (x = cx-24), motor on the arm's back
  end, nut on the carriage face (2026-09-27, user asked for visible threads). Not down the
  centreline - that is where the arm is.
- M3 lies FLAT. Upright (60 tall) the arm swept straight through it.

**Placed and exported (2026-09-06).** Plate 300x340, tower at (150,170), standing
at factory (270,520) so the tower is 215 mm from the belt's VGR hand-over.
Cup radius = 155 + reach = 125..245 mm, so the hand-over is in reach —
`factory_layout.vgr_reach_check()` asserts this and prints it.
Arm is a single long member (300) driven by rack and pinion, per the p.18 photo.
In the browser it runs an idle sweep through swivel/plunge/reach until the
kernel drives it. **Stations are SOLVED, never typed** — `factory_layout.solve_station()` turns a
factory point into (swivel, reach); the export takes the VGR's stops from there,
so the gripper's idea of the hand-over cannot drift from the conveyor's.
`check_stations()` asserts each solved pose lands on its target (<0.01 mm) and
`check_cross()` is the project's first CROSS-MODULE interference test (VGR arm
at the belt vs the whole warehouse). Both gate the export. Only stations in
`BUILT_STATIONS` gate it — the oven/sorting footprints are placeholders and are
reported by `reach_coverage()` instead of failing the build.

**Enlarged 2026-09-06** (user asked): plate 360x560, tower 380 tall, arm 500
long with a 280 stroke - cup annulus **168..448 mm**. The arm must still be
gripped by the carriage at full reach (back end CY+70 vs carriage CY+27), and
that is what sets the arm length. Tower now at factory (700,580): belt 333 mm,
oven 414 mm, sorting only partly reachable (nearest corner 420, centre out).

**Per-station plunge BANDS, not single stops** (FL.VGR_PLUNGE_BAND): belt
140..320 (floor: above the belt strips and drums), oven 140..210 (ceiling: under
the oven's own Sauger portal rail). Same shape of constraint as the HBW's
identification tunnel. See [[stf-oven-model]].

**Cross-module checks use ORIENTED boxes** (FL._obb_hit, 2D SAT). The
conservative axis-aligned enclosure is fine inside a module, but a long arm at
45 degrees has an enormous AABB and reports hits that are not there.

The browser cycle now performs the real hand-over (swivel/reach/plunge, Q8 on,
cookie transfers from mould to cup) driven by `vgrHot`, the same mutable-hot
pattern as `store.ts`. See [[stf-hbw-geometry-facts]].


**2026-09-27 rebuild (user feedback: arm cut through the oven portal, cup went
into the mould, cup looked unattached):** columns to 600, PLUNGE 90..540, TRANSIT
500, ARM 640 / REACH 0..400, spring stem (SPRING 6, OVERTRAVEL 4). Motion is now
planned and swept in `vgr_path.py` (see [[stf-pipeline]]): swing at transit,
descend beside the station at the longest clear reach (planner searches it), extend,
plunge to CONTACT = cookie top + 28. Exported as `vgr.plan`; the viewer plays it.
Negative test: the old 300->210 swing to the oven reports 13 collisions.

**Viewer bugs that looked like geometry bugs:** (1) parts are authored at plunge
250 but the viewer offset from the 320 limit -> whole arm drawn 70 mm low;
use `doc.vgr.authoring`. (2) a spindle whose joint the drive lacks gets
`undefined/4 = NaN` and three.js silently hides it - the stem (and so the cup's
attachment) vanished. Verify rendered geometry by measuring world boxes, not
by captions.
