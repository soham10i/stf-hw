---
name: stf-oven-model
description: "The Brennofen module (ft 536632) in stf-cad/hbw/oven_model.py - rebuilt 2026-09-27 to booklet Abb. 9; flow line, one-stroke Q12, belt feeds sorting"
metadata:
  node_type: memory
  type: project
  originSessionId: 032e9723-f529-45af-b01b-8acef420d14c
  modified: 2026-09-27T09:36:21.513Z
---

`oven_model.py` was REBUILT FROM SCRATCH 2026-09-27 against 536634-Fabrik_Simulation_24V.pdf
p.30 / Abb. 9 (old version kept as oven_model_v1.py.bak). 69 solids; check() = 196 poses +
the workpiece swept along its whole journey (tray, cup, disc, pusher, belt) + grounding.

**Module frame = factory axes** (translated only, OVEN_AT=(150,0), never rotated): +X toward
the VGR (Abb. 9's viewer), +Y toward the sorting line.

Design facts (do not re-derive):
- ONE flow line x=230: tray -> Sauger -> Drehtisch -> Auswerfer -> belt. Belt is collinear
  with the sorting belt (factory x=380) and ends 10 mm short of it (sorting BELT start moved
  40->8). That is what makes the cookie flow continuous - the old belt ran away from sorting.
- Q12 is a pneumatic cylinder = TWO positions. Tray top = disc top = belt top = Z_W 60, so one
  50 mm stroke serves both Sauger stops (asserted). Old model needed 82 and 166 mm strokes.
- Sauger rail is BEHIND the flow line (on the oven's front face), nothing above the tray, so
  the old pedestal and the VGR plunge ceiling (210) are gone; VGR oven band is now (100,320).
- Sauger parks at its Drehtisch stop while the VGR loads the tray (chained rule). At y=115 it
  sat in the VGR approach corridor (vgr_path found no descent) -> TT moved to y=195, stop 150,
  plate 330x380. VGR_AT moved (520,380)->(520,300) to reach the farther tray.
- Drehtisch stops: 0 Sauger (I1), -90 Saege (I4), -180 belt (I2). Auswerfer Q14 is over the
  disc centre, pushes +Y. Interlock: pusher fires only at the belt stop.
- NO ENCODERS anywhere on this module.

Viewer: web/src/scene/OvenFlow.ts is the single timeline for one cookie from tray to its
Lagerstelle; bake is lengthened automatically so it never lands in a bay the VGR hasn't
emptied. Blueprint: web/src/ui/OvenBlueprint.tsx draws plan/front/side from the export.
See [[stf-sorting-model]], [[stf-vgr-model]], [[stf-pipeline]].
