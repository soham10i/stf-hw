# The factory's electrics, pin by pin

One generator, `stf-cad/hbw/electrical.py`, writes `web/public/electrical.json`. It covers every
electrical part of the factory, its pins and ratings with their sources, and every wire between
them. The twin's circuit solver loads it (`web/src/circuit/factoryCircuit.ts`), and the
**Electrics · pin by pin** view shows it.

```bash
python3 stf-cad/hbw/electrical.py
```

## Where the data comes from

The generator reads its sources and never retypes them:

| What | Source |
|---|---|
| The adaptor PCB's terminals, ribbon pinouts (ST1/ST2), relay pairs, valve terminals | `controller.json` (controller.py, from the 536634 extended description) |
| The ft components' ratings | `components/components.json` (components.py: datasheets and booklet) |
| Which RevPi DIO terminal and channel each signal lands on | the four `docs/occupancyPlan*.ods`, parsed directly |
| RevPi DIO, RevPi Core, the WDR power supply | their datasheets in `docs/`, transcribed into electrical.py |

Every rating and pin limit carries a source tag:

- **datasheet**, **booklet**, **plan**, **board doc**: from a document;
- **derived**: computed from sourced values;
- **measure**: not documented anywhere.

## Two variants

`electrical.json` (schema `stf.electrical/2`) holds one set of part sheets and two wirings. They
share the field side: every sensor, motor, valve and lamp on its module's adaptor PCB, through its
ribbons and relays.

| | original | upgraded (what the 3D twin shows) |
|---|---|---|
| PLC side | a RevPi DIO per module, terminal by terminal from the occupancy plans | a Modbus TCP remote I/O node beside each PCB, channel by channel from the CAD's allocation (`io_nodes.py`) |
| Supply | the WDR-120-24 straight to the boards | an ECB channel per node; the actuator 24 V (motor relays, outputs) through the safety contactors K1/K2, held by the safety relay K0 |
| Air | three module compressors | the central compressor, run by the air station's pressure switch (0.6-0.8 bar), whose second contact is the arm's I5 |
| Extra sensors | - | 6 reed switches on the oven's cylinders, the arm's vacuum switch, 2 RFID heads on IO-Link |
| Colour sensor A4 | no RevPi channel (the plan's gap) | on the sorting node's AI slice |
| Parts, pins, nets | 70, 749, 96 | 111, 818, 112 |

## Placement in 3D

Every part is placed from the CAD export: its tagged part (motors by their I/O tag, light-barrier
receivers as phototransistors and transmitters as lamps, valves, boards, the cabinet's and nodes'
parts). The module's placement is applied, and a part on a moving axis is placed at the axis's
zero pose with its frame named. **All 111 parts of the upgraded factory are placed.** The
original's four DIOs and three module compressors are not in the CAD, which draws the upgraded
factory.

**A check compares each CAD box with its datasheet housing.** Every motor, switch, light barrier
and sensor agrees within 0.5 mm, except one: the oven's I6 is a mini switch in the booklet, but
the CAD draws it as an 18 × 30 mm high-temperature inductive sensor.

## Clicking a part in the 3D twin

Every electrical part in the 3D twin is clickable: modules, cabinet, nodes and upgrade parts are
matched through the CAD names the export records. The card shows:

- the part's pins and the voltage on each now;
- its main ratings and its CAD part;
- a link to its full sheet in the Electrics view (`?view=electrics&part=…`).

**While the Test bench runs the part's module, the values are the physics':**

- a motor's speed, current and voltage come from its motor model;
- its direction switches its relay outputs in the circuit, so its leads read +24 V and GND;
- the bench's switches and light barriers press their contacts.

Otherwise the card says the circuit is at rest.

## Checks

The export is checked before it is written, and the results ship with the JSON.

- **Every wire ends on a pin its part has.** The twin parses the export with the strict schema
  (`parseProjectState`) as well.
- **Inventory against the booklet's own totals (536634 p.2), built only from the ribbon pinouts:**
  15 reference switches, 9 light barriers, 5 encoders, 3 compressors, 8 valves, 1 lamp, 10
  bidirectional and 3 unidirectional motors. All match.
- **The PLC side:** inputs and outputs per DIO (at most 14 of each), and counters per DIO (the
  gripper uses 6 encoder inputs, 3 encoders, of the 6 allowed).
- **Ratings:**
  - phototransistor input current: 2.4 mA DIO input, 5 mA board limit, 15 mA rated;
  - DIO output loads: compressor 70 mA, one-way S-motor 300 mA, against 500 mA;
  - the supply budget with motors running loaded: 4.28 A of 5 A.
- **Warnings (limits, met in normal running):**
  - An unloaded encoder motor (440 rpm) gives 550 Hz per channel, beyond the DIO's 500 Hz
    encoder sequence. The axes run loaded, at 268 Hz.
  - Every motor at its datasheet maximum at once would draw 6.3 A of the supply's 5 A. The
    booklet sizes the factory at 4.8 A.
- **Live in the twin:** any change of wiring or switching re-checks every node for shorts and
  overvoltage. Tests prove a miswired 9 V sensor on 24 V reads OVERVOLTAGE, and a sensor pin on
  ground reads SHORT_CIRCUIT.

## Findings

- **The sorting line's colour sensor (A4, board terminal 9) has no RevPi channel** in the
  occupancy plan, though it is what sorts the cookies. The board's header also calls the
  terminal I4.
- **The RevPi DIO's outputs do PWM (40–400 Hz), but the adaptor PCB cannot use it per motor.**
  It reverses motors through relays and slows them only by a reduced voltage on terminal 1, so
  all bidirectional motors at once.
- **The arm's homing output Q6 is "rotate counter-clockwise"** (the plan). The bench's swivel now
  homes that way.

## Not yet

- **No FreeCAD models yet** for the board, RevPi, supply, nodes or safety parts. The twin draws
  them with its own renderers (PCB with headers and relays; RevPi with plugs and LEDs), not as
  precise B-rep models like the nine ft components.
- **Undocumented currents** (valves, relays, lamps, sensors, the upgrade's parts) stay out of the
  budget until measured.
- **The schematic view.**
- **Live values for the oven, and for every module during the normal cycle.** The twin's cycle is
  scripted and carries no I/O state; only the Test bench's physics gives live values.
