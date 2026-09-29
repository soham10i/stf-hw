---
name: stf-sorting-model
description: The Sortierstrecke module (ft 536633) — colour sensor limits, pulse-counted belt, and the loop closure
metadata:
  type: project
---
`sorting_model.py` (2026-09-06), ft 536633. 55 solids, all clear. Belt, colour
sensor, three pneumatic ejectors, three Lagerstellen. Full Belegungsplan in the
docstring: I1 Impulstaster, I2 inlet, I3 after-colour, **A4 Farbsensor analogue**,
I5/I6/I7 per-bay barriers; Q1 belt (unidirectional), Q2 compressor, Q3/Q4/Q5
ejector valves.

**Datasheet 128599 changes the design, do not re-derive:**
- The Farbsensor is **NOT an RGB sensor**. LED + phototransistor measuring
  reflected intensity; "similar colours can produce similar values", and the
  reading depends on ambient light AND on the distance to the object. So
  `SENSOR_GAP` (25 mm above the workpiece top) is a real design parameter.
- Sensor outputs **0-2 VDC** but terminal 9 is specified **0-10 VDC** - the 24 V
  adapter PCB scales it. Never assume the terminal's range at the sensor.
- **No encoder on this module either** (nor on the oven, see [[stf-oven-model]]).
  I1 is a pulse switch; the controller counts pulses from the inlet barrier to
  decide which ejector to fire.

**Loop closure** (booklet, Erste Schritte): the workpieces START in these
Lagerstellen and the VGR collects them from here. Modelled as resting stock.

Placed rotated +90 (see [[stf-factory-layout]]); ejectors at the table front, bays toward the VGR. That forced
the VGR's swivel range open from -95 to **-125 deg** - the three bays solve at
-94/-104/-113. The solver found that; nobody guessed it. See [[stf-vgr-model]].
