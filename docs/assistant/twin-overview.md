# The digital twin: overview

## What it is

A digital twin of a fischertechnik Smart Tabletop Factory (536634, 24 V) that bakes cookies. One
parameter table per module drives the 3D view, the FreeCAD models, the drawings and every
analysis, so the CAD, the kinematics and the I/O can never drift apart. Every placement is
checked by proofs before it is exported: no two parts intersect in any allowed pose, every part
is carried by something, and the workpiece clears every station on its whole journey.

Everything is simulated. There is no physical machine connected; the "Live" or "Simulation" chip
in the top bar says whether the physics API is running or the twin runs entirely in the browser.

## The four modules

- **Warehouse** (high-bay warehouse, ft 536631): a 3 x 4 rack (slots A1-C4) and a stacker crane
  with travel, lift and a telescopic fork (Ausleger); a belt carries moulds to the robot.
- **Gripper robot** (vacuum gripper robot, VGR, ft 536632): a cylindrical robot (swivel, plunge,
  reach) with a suction cup. It links every station.
- **Oven** (multi-processing station with kiln, ft 536632): tray (Ofenschieber), heated chamber,
  its own suction gripper, turntable with saw, pusher and an outlet belt.
- **Sorting line** (ft 536633): belt, colour sensor, three pneumatic ejectors and three bays
  (weiss, rot, blau).

Around them: a guard enclosure with doors and E-stops, a PLC cabinet, four remote I/O nodes, a
central air station, drag chains and the wiring.

## The product

Exactly 12 cookies exist in the system, each in its own mould. Three flavours, chosen so the
colour sensor (which measures reflected brightness, not colour) can tell them apart:

| Flavour | Sensor reading | Bay |
|---|---|---|
| chocolate | ~340 mV | blau |
| strawberry | ~950 mV | rot |
| vanilla | ~1660 mV | weiss |

Raw dough is pale. A cookie gets its flavour colour when it is baked.

## Where things are in the app

- **3D twin** (`/`): the machine, the order form and nine side panels. See *The 3D view* and the
  *Panel:* documents.
- **Dashboard** (`dashboard.html`): production, health, maintenance, energy, security and
  engineering pages, with a chat on every page. See the *Dashboard:* documents.
- **View switcher** (top bar, or Cmd/Ctrl+K): the factory, the controller board, and each
  component and mechanism in detail.
