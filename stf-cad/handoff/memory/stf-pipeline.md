---
name: stf-pipeline
description: pipeline.py — the 12-cookie inventory, the schedule, and how deadlock freedom is proven
metadata:
  type: project
---
`pipeline.py` (2026-09-06) owns two things nothing else may duplicate:

1. **THE INVENTORY.** Exactly 12 cookies, created here and nowhere else.
   `hbw_model` and `sorting_model` import `RACK_START` / `BAY_START` from it, so
   a scene cannot quietly make it 13. 9 start in the rack, 3 in the Lagerstellen.
2. **THE SCHEDULE.** 69 transfers, 31 scheduler rounds, every cookie ending in
   its own bin.

**Three flavours chosen from the DATASHEET, not aesthetics:** the Farbsensor
128599 is not RGB — it measures reflected brightness — so the flavours separate
on exactly that. chocolate #4A2C17 ~340 mV -> blau; strawberry #D9536F ~950 mV
-> rot; vanilla #EFE0B0 ~1660 mV -> weiss. See [[stf-sorting-model]].

**Deadlock freedom is by construction:** every transfer is ATOMIC (all locks at
once, released at the end) so hold-and-wait cannot occur; locks are acquired in
one fixed total order so circular wait cannot occur; two of Coffman's four
conditions are structurally impossible. `simulate()` also builds the wait-for
graph every step and asserts it is acyclic.

**Two real deadlocks it found by RUNNING, not reading:**
- Modelling "on the fork" as a schedulable state let two cookies be put on one
  fork. Making transfers atomic place-to-place moves removed the class.
- The wait-for graph then closed a cycle between the oven TRAY and CHAMBER: the
  baked cookie could not leave because the tray was occupied, and the tray's
  cookie could not enter because the chamber was. A deadlock in the PROCESS, not
  the code. Fixed with `Op.exclusive` — the oven is a single-part station.

**`check_poses()` ties the schedule to the geometry:** every pose the schedule
commands is validated against `hbw_model.pose_allowed/carry_allowed`,
`factory_layout.vgr_plunge_allowed`, `oven_model.pose_allowed` and
`sorting_model.pose_allowed`. A schedule that would drive a machine somewhere it
cannot go fails the build. See [[stf-cad-pipeline]].

**Not done:** the browser still animates each module on its own loop; it does
not yet PLAY the 69-transfer schedule. The timeline is exported in
`hbw_parts.json -> pipeline.transfers` ready for that.
