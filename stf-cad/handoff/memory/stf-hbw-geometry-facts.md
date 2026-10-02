---
name: stf-hbw-geometry-facts
description: HBW facts established 2026-09-06 from the ft manuals, and where the old sim layout is wrong
metadata:
  type: reference
---
Established 2026-09-06 by reading every PDF in `~/workspace/stf-cad/hw/`
(the "hm folder") and zooming the labelled photos.

**Hard facts from the documents**
- No supplied document contains a single dimension of the model. Only the
  bought parts have datasheet sizes: encoder motor 60x30x30 (144643), mini
  switch 30x15x7.5 (37783), phototransistor 15x15x7.5 (36134), colour sensor
  30x15x15 (128599).
- Belegungsplan HRL: Q3 = "horizontal **towards the rack**", Q4 = "towards the
  **conveyor**" — these are the two ENDS OF THE TRAVEL AXIS. The user's top-view
  sketch (2026-09-06) confirms: rack and conveyor are on the **same side** of the
  picker rail, the conveyor sitting beyond the rack along travel. So the Ausleger
  telescopes ONE WAY ONLY and I5 vorne / I6 hinten are the two ends of a single
  stroke — one stop (115 mm) serves a rack bay and the belt hand-over alike.
- I2 = Lichtschranke **innen**, I3 = **außen**. I5/I6 = Ausleger vorne/hinten.
  A1/A2 = Spursensor (barcode), lower/upper.

**Deduced from the photos (ext. description p.5, booklet p.22/p.26)**
- Four black posts → three bays; three rows → nine slots.
- ~~No Werkstückträger~~ — **the user corrected this 2026-09-06: there ARE
  moulds**, one per slot. The VGR drops a cookie into a mould at the belt's
  front hand-over; the crane always carries the whole mould. 12 slots / 12
  moulds, but one is always in circulation so exactly one slot is free — that
  free slot is what lets an emptied mould be put away.
- The crane is a travelling mast on a front rail (spindle + guide rod), and is
  visibly taller than the rack.

**Motor 144643 datasheet (T–N–I curve, read from the page image 2026-09-06):**
no-load 440 rpm, stall 1800 g·cm, Pmax 2.03 W, **Imax 0.6 A**, ηmax 36 %;
encoder quadrature push-pull 0/24 V, ≤1 kHz; shaft Ø4 × 7.5 out of a 30×30 end
face. TWO CONTRADICTIONS with `factory.layout.yaml`: it models HBW_X/HBW_Y at
1.5 A running (2.5× the motor maximum), and 440 rpm behind the recorded 25:1
gearbox gives ~18 rpm at the spindle, not the 214 rpm the drive block assumes.
The 14.27 mm/s lab figure and the pulse rate are self-consistent, so the suspect
value is the gear ratio. Unresolved — flagged to the user.

**Where `factory.layout.yaml` is wrong today** (migration will invalidate
`tests/golden/`): belt modelled parallel to the rack instead of running out of
the module; carrier tray that does not exist; fork stops 5/10/85/-55 instead of
0/60/95.

**CONFIRMED BY THE USER 2026-09-07:**
- The mould does NOT travel beyond the warehouse conveyor belt. The external VGR
  picks the COOKIE itself off the mould with its suction cup, at the belt. The
  mould stays in the HBW and goes back to a free slot. (This is what the model
  already did — now confirmed, not assumed.)
- **Cookies are RAW WHITE by default.** The colour changes to the flavour only
  AFTER baking. Baked vanilla is only slightly off-white compared to raw.
- The user is measuring the real machine and will supply all dimensions. Until
  then every module plate size in the model is a placeholder of mine.

**Still unconfirmed by the user** — asked on the build sheet, no answer yet:
conveyor direction, three pinning measurements (bay pitch, shelf pitch,
workpiece Ø and height), tray-or-no-tray, and whether to model the lift motor's
real right-angle crown gear. See [[stf-cad-pipeline]].

**2026-09-27:** a whitelist hid a real collision - I5 sat on stage 1's top face, the
plane the fork table slides in, and ("tool","fork") was whitelisted. Switches now on
stage 1's SIDE, own group `fork_sensor`. Brute-force scans with the whitelist OFF
catch what the proof's allowed-contact list can hide. Hood COVER_Y 340..540 (I2..I3);
light barriers stand on the rail tops (mech beam:rx/tx) so the mould breaks them;
belt drive pulleys outboard of the R rail, `belt:loop` drawn as a real loop.
