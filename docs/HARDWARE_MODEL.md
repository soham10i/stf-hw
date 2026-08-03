# Physical hardware model — Fischertechnik Factory Simulation 24V (536634)

Derived from the manuals in `docs/` (`536634-Fabrik_Simulation_24V.pdf`, the
extended description, and the RevPi occupancy plans / Belegungspläne). This is
the reference the 3D simulation must match physically. Section numbers refer to
the extracted German source; quotes are translated inline.

## Factory overview

The full kit chains four modules (only the first two are simulated so far):

1. **Automated High-Bay Warehouse** (Automatisiertes Hochregallager, **HRL/HBW**)
2. **Vacuum Gripper Robot** (Vakuum-Sauggreifer, **VSG/VGR**)
3. Multi-processing station with kiln/oven (Multi-Bearbeitungsstation mit Brennofen)
4. Sorting line with colour detection (Sortierstrecke mit Farkerkennung)

Material flow (manual §"Verkettung"): the vacuum gripper loads workpieces onto
the stacker crane of the high-bay warehouse, which stores them sorted by colour;
for retrieval the crane returns carriers to the conveyor and the gripper picks
the workpiece back off.

---

## 1. High-Bay Warehouse (HBW)

> "Storage and retrieval is performed by stacker cranes that move **in an aisle
> located between two rack rows**. … the goods are staged by means of a
> **conveyor belt**; identification is by a barcode read with the trail sensor."

### Physical structure

**Corrected after actually viewing Abbildung 7** (the photo of the module —
earlier revisions of this document were derived from the extracted *text*
alone, and got the belt orientation wrong):

```
   plan view (looking down); +x to the right — THREE PARALLEL LANES

   ┌──────────────────────────────┐
   │   R A C K   (3 × 3 bays)     │   y = 0, openings face the lane
   └──────────────────────────────┘
   ───────── crane lane ───────────   y = -55: mast travels along x
        Ausleger extends FORWARD (+y) into a bay
        and BACKWARD (−y) over the belt (I5 vorne / I6 hinten)
        ┌───────────────────────┐
        │ Förderband ──────────►│      y = -110, runs ALONG x, parallel
        └───────────────────────┘
        x=400 (crane transfer,          x=520 (VGR end, local 0;
        belt-local 120; I2 at 105)      I3 pick window at local 15)

                              [VGR tower at (505, -230); at swivel 0 the
                               arm reaches +y over the belt end]
```

The crane deposits by extending the cantilever *backward* over the belt; the
belt carries the tray along the front lane, past the identification sensors,
to the far end where the vacuum gripper picks it. Rack, crane travel and belt
all share one lane direction.

### Axes (the stacker crane / Regalbediengerät)

Three servo axes plus a transport belt. From the Belegungspläne:

| Axis | Motion | Motor | Encoder | Reference switch |
|---|---|---|---|---|
| **horizontal** | travel along the rack (X) | M2 (Q3/Q4) | B1/B2 | I1 (horizontal) |
| **vertical** | lift up/down the mast (Z) | M3 (Q5/Q6) | B3/B4 | I4 (vertical) |
| **cantilever / Ausleger** | telescope into a bay (Y) | M4 (Q7/Q8) | — | I5 front, I6 back |
| conveyor belt (Förderband) | stage carriers to/from VGR | M1 (Q1/Q2) | — | I2/I3 light barriers |

- The crane mast and carriage live **in the aisle, in front of the shelves** —
  they never pass through a bay. Only the Ausleger enters a bay, to slide a
  carrier on/off a shelf.
- Encoder motors: 75 pulses/rev, 4 mm spindle pitch → 18.75 pulses/mm; lab
  calibration 214 rpm → 14.27 mm/s (see `factory.layout.yaml`).
- The Förderband carries a carrier from the crane's transfer point (HBW end)
  to the VGR end, past the identification unit (trail sensor + two light
  barriers I2/I3 that gate the barcode read).

### Storage

3 × 3 = 9 bays holding workpiece carriers (Werkstückträger). Static assignment
in the sim: top row white, middle red, bottom blue. Labelled A1–C3 with A the
bottom row.

---

## 2. Vacuum Gripper Robot (VGR)

> "The working space of the vacuum gripper can be described as a **hollow
> cylinder**." — "The kinematic structure consists of a **Drehkranz** (rotary
> turntable) and two translational axes."

### Physical structure

A cylindrical-coordinate robot — **not** three Cartesian axes (the earlier
model got this wrong).

```
        vertical axis (up/down the column)
              │
        ┌─────┴─────┐   horizontal axis (arm reaches in/out)
        │  carriage ├──────────────────►  ● suction cup (Sauger = effector,
        │           │                        points DOWN)
        │  column   │
        │           │
     ═══╧═══════════╧═══   Drehkranz (rotary turntable) — the whole
        base / turntable    column+arm assembly rotates about the vertical axis
```

### Axes

| # | Axis | Motion | Motor | Encoder | Reference |
|---|---|---|---|---|---|
| 1 | **Drehkranz** (rotate) | swivel about the vertical base axis | M3 (Q5/Q6) | B5/B6 | I3 |
| 2 | **vertical** | carriage up/down the column | M1 (Q1/Q2) | B1/B2 | I1 |
| 3 | **horizontal** | arm extends in/out | M2 (Q3/Q4) | B3/B4 | I2 |
| — | suction (Sauger) | vacuum effector at the arm tip | compressor + valve | — | — |

- The turntable rotates the **entire** column + arm + suction assembly (this is
  what sweeps the hollow-cylinder work envelope).
- The suction cup hangs off the end of the horizontal arm and faces downward,
  so it descends onto a workpiece.
- Reference run: drive all three axes to their reference switches, zero the
  encoders, then move by counted pulses (incremental positioning).

---

## 3. What this means for the simulation

Concrete corrections applied to `factory.layout.yaml` and the renderer:

1. **Crane aisle.** The HBW base is offset in depth so the mast and carriage sit
   in an aisle in front of the rack; shelf boxes sit behind their openings. The
   Ausleger (`hbw.fork`) telescopes from the aisle into a bay. The crane no
   longer passes through the storage boxes.
2. **Floor.** A coloured table-top platform sits under the rack + aisle +
   conveyor so the warehouse reads as one machine on a surface.
3. **Opposite-end handoff.** The Förderband runs from the crane transfer point
   (HBW end) out to the VGR end; the crane deposits at one end and the VGR
   picks at the other.
4. **VGR structure.** Rebuilt as Drehkranz (rotary base) + vertical column +
   horizontal arm + downward suction cup, positioned to reach the far
   (VGR) end of the conveyor — opposite the crane.

The joint *semantics* in the kernel are unchanged (travel/lift/fork for the HBW;
swivel/reach/plunge for the VGR); only the world placement and the rendered
geometry change, so the planner, the golden trajectories and the physics are
unaffected.
