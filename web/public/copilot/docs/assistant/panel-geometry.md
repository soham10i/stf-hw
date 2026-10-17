# Panel: Geometry

## In brief

What the 3D machine is made of: every part is generated from one parameter table (`stf-cad/hbw/hbw_model. py`, the same table that builds the FreeCAD model) and exported only after the clearance proof passes.


What the 3D machine is made of: every part is generated from one parameter table
(`stf-cad/hbw/hbw_model.py`, the same table that builds the FreeCAD model) and exported only
after the clearance proof passes.

- **Parts**: the warehouse module's parts per group, as bars (moulds, rack, conveyor, workpieces,
  crane, rails, covers, chain, fork, RFID, control, sensors, frame, tools).
- **Cookies**: the 12 cookies by flavour and the bay each is sorted into.
- Folded: the module's I/O tags, the pipeline's safety rules (exactly 12 cookies; every transfer
  atomic; locks in one fixed order; a move never starts unless its destination has room; the oven
  as a single-part station; every commanded pose checked), where the geometry comes from, and why
  the three flavours (the sensor measures brightness).
