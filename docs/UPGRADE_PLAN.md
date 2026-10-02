# STF upgrade plan: from training model to industrial practice

Six upgrade levels for the fischertechnik Fabrik Simulation 24V (536634) twin. Each level builds on
the one before it, and each follows the same rules:

- **One source of truth.** Every change is made in the Python models (`stf-cad/hbw`) as a variant
  (`STF_VARIANT=up1`, `up2`, and so on). The base machine's export stays byte-identical, and the web
  view, drawings and FreeCAD file are all generated from the models.
- **Gated export.** A level ships only when every proof passes: the module checks, `check_cross`,
  `vgr_path`, the level's own checks, and the wiring gate.
- **Blueprint sheets are generated, not drawn.** Each level gets an `Un-xx` sheet set built from its
  export and the base export. The change list is always the diff of the two.
- **Measured before trusted.** Every dimension marked *assumed* stays flagged until it has been
  measured on the real machine.

"Industrial level" here means industrial **practice** (safety, wiring, control, verification and
maintainability), not industrial size. The twin stays at its 2× structural scale.

| Level | Theme | State |
|---|---|---|
| 1 | Utilities, buffer, stiff structure | **built**: see the Upgrade 1 views |
| 2 | Machine safety | **built**: see the Upgrade 2 views |
| 3 | Distributed I/O, cable carriers, cabinet to standard | **built**: see the Upgrade 3 views |
| 4 | Control program and traceability | **built**: see the Upgrade 4 views |
| 5 | Virtual commissioning | **built**: see the Upgrade 5 views |
| 6 | Operations analytics and predictive maintenance | **built**: see the Upgrade 6 views |
| 7 | Maintainability and lifecycle | **built**: see the Upgrade 7 views |
| 8 | Semi-supervised deep learning for maintenance | **built**: dashboard, "AI maintenance" |
| 9 | The cell as a microgrid | **built**: dashboard, "Energy & grid" |
| 10 | Throughput | **built**: dashboard, "Throughput" |
| 11 | OT security to IEC 62443 | **built**: dashboard, "OT security" |
| 12 | Defence in depth | **built**: dashboard "Defence in depth" |
| 13 | Software-in-the-loop PLC | **built**: twin panel "PLC program (live)" |
| 15 | Vision inspection, trained on rendered images | **built**: twin panel "Vision inspection" |

**The app shows one machine: Upgrade 12**, which contains every level. Each upgrade is a side panel of that view, not
a view of its own (2026-10-01). The intermediate variants still build and are re-proven by `validate.py`; they
are no longer exported into the web app.

---

## Upgrade 1: utilities, buffer, stiff structure (BUILT)

**Goal.** Use the empty space, remove duplicated utilities, and make the structure stiff enough
that the tools land where the model says they do.

### What was changed (from the diff of the two exports)

| Area | Change | Numbers |
|---|---|---|
| Air supply | 3 module compressors (oven Q10, sorting Q2, VGR Q7) → 1 central station: diaphragm compressor, 0.5 l tank, pressure switch 0.6–0.8 bar, filter-regulator at 0.7 bar, lockable shut-off with exhaust, 4-outlet manifold | 3 → 1 pump. Air hose on the table goes from 4.0 to 8.1 m (the trade-off). |
| Buffer | 6-nest cookie buffer in the reachable part of the dead corner. Pads Ø55 with tops at z 45 (the Lagerstelle height), 4 locating pins Ø4 on r 27.5, 20×20 profile legs | Reach margin 26–183 mm, swivel margin ≥ 18° |
| Placement | The dead corner behind the HBW (652 × 500) is split along the VGR's reach (r 168–568): the buffer inside that reach, the air station outside it | The PLC stays at the front edge: the spot it would free is 1019 mm from the tower, outside the arm's reach |
| Oven members | Members that failed the 0.2 mm sag check → aluminium profile | Pusher beam 3.71 → 0.013 mm, door gantry 1.30 → 0.001 mm, Sauger rail 0.29 → 0.023 mm. The saw arm passes (0.035 mm) and is left alone. |
| HBW mast | 4 × Ø10 tubes → 4 × 15×15 slotted profiles, and the carriage is guided like the VGR tower | Legs 16 → 22 mm (3.5 mm wall around a 15.6 mm pocket), fork yoke 50 → 62 deep, outrigger 112 × 62, load passage 75 mm for the 60 mm mould |
| Precise geometry | Every part is drawn with its exact CAD shape (`web_precise.py`): guide pockets, T-slot profiles, threads, kiln seams, saw teeth | Every detailed solid is asserted to stay inside its proven envelope |

### Blueprint sheets (Upgrade 1 → blueprint view)

| Sheet | Content |
|---|---|
| U1-01 | Layout plan: table, modules, dead corner, VGR reach, placement rule, air mains |
| U1-02 | Central air station: plan and front elevation, numbered parts list |
| U1-03 | Cookie buffer: plan and front elevation, nest pitch, solved VGR stations |
| U1-04 | Oven: changed members highlighted, sag table before and after, profile sections |
| U1-05 | HBW mast: plan section before and after, the 12 guide pairs with their clearances |
| U1-06 | Change list (the diff), proofs, title block |

### Proofs that gate it

`upgrade.check` (plates, reach and sag), `check_cross` (every new part against every module, with
the VGR at 11 stations), `vgr_path.check_buffer` (24 visits, 242 waypoints), `mechanics.check_guides`
(all 12 HBW mast pairs with 0 overlap and a 0.3 mm gap), the wiring gate (no conductor crosses the
cookie's path), and the 4 module proofs.

### Still open in Upgrade 1

- The buffer is placed and its paths are proven, but the scheduler doesn't use it yet. That is
  Upgrade 4.
- The sag model uses solid PA6 sections. Real ft blocks are hollow, so the base values are optimistic.
- The compressor, cylinders, valves and S-motors are booklet parts with **assumed** sizes.

---

## Upgrade 2: machine safety (BUILT)

**As built** (`STF_VARIANT=up2`, `stf-cad/hbw/safety.py`):

- **Hazard zones.** Seven zones, each the swept envelope of a mechanism over its full joint range
  (the VGR arm sampled every 5°, drawn as its true swept outline):
  - H1 HBW crane, PLd
  - H2 VGR arm, PLd
  - H3 oven door and tray, PLb
  - H4 turntable, saw and Sauger, PLc
  - H5 Auswerfer, PLb
  - H6 sorting ejectors, PLb
  - H7 stored air, PLb
- **Guard.** A closed enclosure: 30×30 profile frame (14 posts, top and bottom rails), 4 mm
  polycarbonate walls and roof, 900 mm above the plates, 25 mm outside the table edge. Every hazard
  zone is at least 20 mm inside it.
- **Doors and devices.**
  - Three hinged doors (A oven + PLC, B sorting, C HBW service), each with an interlock switch
    **with guard locking**.
  - E-stops ES1–ES3 and a monitored reset S3.
  - Dual-channel safety relay K0 and force-guided contactors K1/K2 on the cabinet rail, switching
    the actuator 24 V.
  - Safe exhaust valve Y1 between the filter-regulator and the manifold.
- **Why locking, not a light curtain.** S = K·T + C is at least 200 mm even for a 0.1 s stop, and
  the hazards come to within about 25 mm of the table edge. That calculation is on sheet U2-03.
- **Proofs.**
  - Reach and fit: every zone inside the guard, and no guard part touching the machine.
  - Logic: 26,626 input states checked exhaustively, including every single-channel fault.
  - Air: all 9 cylinders are fed only through Y1.
- **Finding.** The retracted VGR arm's rear reaches 1.3 mm past the table edge. It is still
  23.7 mm inside the guard.
- **Wiring.** Every safety device is wired dual-channel in a duct on the outside of the bottom
  rail, through one gland into the cabinet.
- **Blueprint.** Sheets U2-01 to U2-05 are in the "Upgrade 2: blueprint" view.
- **Still open.** PL achieved (needs the devices' MTTFd, DCavg and CCF). Real device sizes
  (ft-scale sizes are assumed).

### Original plan

**Goal.** Make it impossible for a person to reach a moving hazard, and prove it in the model. No
real cell runs without this, and today the twin has none of it.

### Scope

1. **Risk assessment (ISO 12100).** List every hazard with its place and its energy:
   - crane crushing and shearing (HBW lift and travel);
   - the VGR swing zone (swivel of 260°, arm up to 568 mm);
   - Ofenschieber and door pinch points;
   - the turntable and saw;
   - stored pneumatic energy (tank and cylinders);
   - heat, for a real oven.

   Each hazard is graded to a required performance level (PLr, ISO 13849-1).
2. **Guarding.**
   - Perimeter guard: aluminium profile frame with polycarbonate panels, at safety distances from
     ISO 13857 (opening size → distance to the hazard).
   - Loading side: a light curtain or an interlocked door, positioned at the ISO 13855 distance
     S = K·T + C, from the machine's measured stopping time T.
3. **Safety circuit.** E-stop mushroom buttons (front and loading side), a safety relay or small
   safety PLC, two-channel monitored contactors for 24 V motor power, and a door switch with
   guard locking where run-down is long.
4. **Pneumatic safety.** A safe exhaust valve (two-channel, monitored) replaces Upgrade 1's manual
   shut-off as the E-stop function. The manual lockout stays for maintenance.
5. **Safety I/O in the twin.** A new signal layer (E-stop chain, guard closed, light curtain OK,
   safe torque off) that gates every motion command.

### Blueprint sheets

| Sheet | Content |
|---|---|
| U2-01 | Hazard map: plan view with every hazard zone, its PLr and its guard |
| U2-02 | Guarding layout: plan and elevations with ISO 13857 distances dimensioned |
| U2-03 | Light curtain or door: the S = K·T + C calculation, mounting positions |
| U2-04 | Safety circuit schematic: E-stop chain, safety relay, contactors, safe exhaust |
| U2-05 | Safety function table: function → PLr → achieved PL → the parts that realise it |

### Proofs that gate it

- **Reach proof.** No point outside the guard can reach a hazard zone, checked as geometry: the
  hazard volumes against the guard openings, using ISO 13857 reach.
- **Stop proof.** With any guard open, no motion command is possible. This is checked over every
  interlock state, the same way the oven interlocks are checked today.
- **Air proof.** With the E-stop pressed, every cylinder volume is vented within the stop time.

### Depends on

Upgrade 1 (a single air entry is what makes one safe exhaust possible). The stopping times must be
measured on the real machine.

---

## Upgrade 3: distributed I/O, cable carriers, cabinet to standard (BUILT)

**As built** (`STF_VARIANT=up3`, `stf-cad/hbw/io_nodes.py`, `chains.py`, `plc_model.py`):

- **Remote I/O.** One Modbus TCP node per module (coupler plus DI8/DO8/AI2/CNT slices; the sizes
  are assumed, 750-series-like). All 67 Belegungsplan signals sit on exactly one channel, with at
  least 20 % of each type spare. Placement is searched: the nearest free spot to the PCB that
  clears every part, every U2 hazard zone and the VGR sweep. The VGR's own plate lies wholly under
  its arm's sweep, so its node stands in the free table corner.
- **Drag chains**, with the envelope computed per pose and swept by every proof:

  | Chain | Stroke (mm) | R (min 10.5) | Fill | Length | Devices |
  |---|---|---|---|---|---|
  | HBW travel | 120 to 665 | 20 | 11 % | 335 | 5 |
  | HBW lift | 80 to 360 | 20 | 5 % | 440 | 3 |
  | VGR plunge | 84 to 540 | 20 | 8 % | 560 | 3 |
  | VGR reach | 0 to 400 | 12 | 8 % | 447 | 2 |

  The swivel uses a guided cable loop in a tower duct.
- **Cabinet.** The DIN rail is 253.7 of 355 mm used (28.5 % free). An Ethernet switch and a
  4-channel electronic breaker replace the I/O boards. PE has its own busbar, and power and signal
  run in separate ducts.
- **Findings.**
  - The lift chain's fixed end had to move under the mast top plate (it hit the carriage legs).
  - The reach chain's moving end moved 43 mm forward: at the bay pose its loop hit the HBW cover.
  - Two brackets were too weak as cantilevers and were enlarged.
- **Wiring, honestly counted.** Cabinet-bound conductors drop from 119.5 to 47.1 conductor-m.
  The ST3 ribbons from each PCB to its node add 70.3 conductor-m locally. Moving each PCB next to
  its node would recover most of that.
- **Blueprint.** Sheets U3-01 to U3-05 are in the "Upgrade 3: blueprint" view.
- **Still open.** Real node and chain part numbers, and M12 sensor cables in place of the ribbons.

### Original plan


**Goal.** Wiring that can be built, serviced and extended the way plants do it. Today there are
56 point-to-point cables (about 40 m), and the cables on moving parts aren't modelled at all.

### Scope

1. **Distributed I/O.** An IO-Link master (or remote I/O block) on each module. Sensors and
   actuators connect with short M12 cables (< 0.3 m). Each module has one bus cable plus a 24 V
   trunk to the cabinet, in a duct under the table edge. Target: about 6 m of cable.
2. **Cable carriers (drag chains).** HBW travel (545 mm stroke), HBW lift (280 mm), VGR reach
   (400 mm) and swivel (a rotary carrier or cable loop). Each is sized from the cables it carries
   and its minimum bend radius.
3. **Cabinet to EN 60204-1.** Separate power and signal ducts, a fuse or electronic breaker per
   circuit, wire markers, a PE busbar, and 20 % spare space. The safety relay from Upgrade 2 lives
   here.
4. **Wiring gate extended.** No moving cable outside its carrier, the carrier's path swept against
   every part (the same method as `vgr_path`), and the existing "never cross the cookie's path"
   rule kept.

### Blueprint sheets

| Sheet | Content |
|---|---|
| U3-01 | I/O architecture: bus topology, master per module, port allocation table |
| U3-02 | Cable carriers: stroke, bend radius and fill for each axis, with elevations |
| U3-03 | Cabinet layout: front view to scale, ducts, rail, terminals |
| U3-04 | Wiring diagrams per module (from the Belegungsplan), with terminal numbers |
| U3-05 | Cable list: every cable with its type, length, route and both ends |

### Proofs that gate it

The carrier sweep proof, a bend-radius proof, the wiring gate, and a check that every I/O point
from the Belegungsplan has exactly one port.

---

## Upgrade 4: control program and traceability (BUILT)

**As built** (`STF_VARIANT=up4`, `stf-cad/hbw/control.py`):

- **Eight sequencers** (crane, belt, arm, door, sauger, turntable, oven belt, sorting line). Each is a
  state machine INIT → homing → READY → job steps → READY, with FAULT and ESTOP. The steps are not
  typed in. They come from motion the models already prove:
  - the HBW legs of `hbw_model.cycle()`;
  - the VGR waypoints of `vgr_path.plan()`: all 16 tours the orchestrator can command are swept
    clear;
  - the rows of `motion.OVEN_CYCLE`, which pass the door interlock.
- **Generated IEC 61131-3 structured text.** One function block per unit plus the orchestrator.
  Positioning targets are table lookups, and the proof checks that every slot, station and bay
  gives the same step structure.
- **Moulds are modelled.** There are 12 tagged moulds. The base schedule let the empty mould
  vanish at the VGR hand-over. Here it goes back into the rack, or it is refilled with a cookie
  that is going in ("reuse").
- **Orchestrator:** a PLC-style priority scan. Each dispatch policy was explored over every
  completion order, which covers every possible timing:

  | Policy | States | 12-cookie order |
  |---|---|---|
  | prefetch (crane refills the belt as soon as its end is free) | 35 | **deadlock** |
  | single mould on the belt | 905 | 745.3 s |
  | + mould reuse (**PLC policy**) | 933 | 644.5 s (−13.5 %) |
  | + Upgrade 1 buffer | 44,711 | 644.5 s |

  The prefetch deadlock is a circular wait on one belt. The crane end holds a mould going out and
  the hand-over holds an empty mould going back, and each belt move needs the other end free.
- **The buffer never pays** (bake-time study: 2, 30, 60 and 120 s). With the booklet's demo bake,
  the single-mould belt channel is the bottleneck. With long bakes the oven is, but a raw cookie is
  already waiting at the hand-over whenever the tray frees, so parking it costs the VGR a second
  tour (+49 s at a 60 s bake). The buffer stays as a proven deadlock-free degraded mode for a held
  oven.
- **Traceability.**
  - Two RFID read heads sit under the HBW belt on an IO-Link slice of the HBW node. RP1 had to move
    from y 400 to 440, because the Ausleger's second stage reaches y 405 (the HBW proof caught it).
  - After the hand-over, "data follows the part" through the oven. The colour sensor re-checks the
    flavour before the ejector fires.
  - Every record is proved complete and in order.
- **Alarm list.** 23 watchdog alarms, one per unit and completion signal, plus 9 system,
  traceability and order alarms. Each has a cause, a reaction and a recovery.
- **Finding.** Three cylinders have no feedback signal in the Belegungsplan: the oven door, the
  Sauger lowering and the Auswerfer. Their six moves can only be timed, not supervised. The fix is
  a reed switch per cylinder end.
- **HMI.** A sidebar HMI replays the nominal run with unit states, order progress, alarms,
  records and jog rules. Blueprint sheets U4-01 to U4-05 hold the SFCs, the Gantt and study, the
  alarm list, the traceability view and the HMI with the generated source.
- **Assumed.** The axis speeds of motion.py, belts at 50 mm/s, an RFID read of 0.3 s, a vacuum
  time of 0.5 s, and the reference-switch directions.

### Original plan


**Goal.** The factory is run by a real PLC program, not a demo timeline, and every cookie can be
traced.

### Scope

1. **IEC 61131-3 program** (structured text or SFC), in a state machine per module: idle, homing,
   ready, run, fault, E-stop. It includes homing to the reference switches, timeouts on every
   motion, and fault recovery with an operator acknowledge.
2. **Orchestrator.** It plays the 96-transfer deadlock-free schedule (`pipeline.py`) as PLC logic,
   including the buffer from Upgrade 1, so the throughput gain can be measured.
3. **Traceability.** An RFID tag or 2D code per mould, with a read station at the HBW belt and one
   at the VGR hand-over. Each cookie has an ID, a flavour, timestamps and a bake record.
4. **HMI.** Order entry, state per module, alarms with plain-language causes, and manual jog with
   the interlocks from the twin enforced.

### Blueprint sheets

| Sheet | Content |
|---|---|
| U4-01 | State machines per module (SFC charts) |
| U4-02 | Sequence and timing: Gantt of one cycle with the buffer |
| U4-03 | Alarm list: code, cause, reaction, recovery |
| U4-04 | Traceability: tag positions, read points, data model |
| U4-05 | HMI screens |

### Proofs that gate it

The existing deadlock-freedom proof, rerun on the PLC's actual state machine. Every state has a
path to "safe"; every motion has a timeout.

---

## Upgrade 5: virtual commissioning (BUILT)

**As built** (`STF_VARIANT=up5`, `stf-cad/hbw/vc.py`):

- **Coupling.** Upgrade 4's program runs against the twin over the same Modbus TCP register map as
  the real nodes (77 signals, every one the program reads or writes on exactly one register).
  - PLC task: 10 ms, and 5 ms for the VGR.
  - Bus: a 10 ms poll each way.
  - Each step's observed time is the plant's time plus both bus hops, rounded up to the scan.
- **Plant physics.** Trapezoid motor ramps, 3 % belt slip, cylinder travel to the reed switches,
  vacuum build-up and RFID reads. All are flagged as assumed until measured.
- **Healthy run.** 636.0 s against the model's 644.5 s (−1.3 %, gate ±10 %). No step came near
  its watchdog.
- **Accuracy (found).** The ft motors are relay-switched, so positioning is bang-bang with a brake
  lead. At 10 ms the swivel stops within ±3.0 mm at the cup, but the seal allows ±2.5 mm (a 40 mm
  cup on a 45 mm cookie). The VGR therefore runs a 5 ms task (±1.5 mm). Without the brake lead,
  the swivel would overshoot by 45 mm.
- **Fault matrix: 7 of 7 pass.** Each fault raises the expected alarm first, within its bound, and
  the order then completes with 12 cookies, 12 moulds and complete records.

  | Fault | Alarm | Detected after | Time lost |
  |---|---|---|---|
  | Stuck switch (crane I6) | HBW-C01 | 1.7 s | 31.7 s |
  | Motor stall (VGR swivel) | VGR-A04 | 3.5 s | 33.5 s |
  | Cylinder never arrives (oven door) | OVN-D01 | 2.0 s | 32.0 s |
  | Lost vacuum | VGR-V01 | 0.012 s | 50.4 s |
  | Air pressure drop | SYS-05 | 0.01 s | 46.5 s |
  | Oven node lost | SYS-04 | 0.05 s | 29.5 s |
  | E-stop | SYS-01 | 0.01 s | 65.4 s |

- **Found: missing sensors.** On Upgrade 4's hardware, the door fault was only noticed at the
  slider, 4.3 s later, after the slider had driven into the shut door. A lost vacuum was only
  noticed at the oven-belt end, 56.6 s later, after an empty bake, transfer and saw cycle, with
  the record reading "baked". Upgrade 5 adds three sets of sensors, with cables routed to the node
  DI slices:
  - reed switches on the door, Sauger and Auswerfer cylinders (oven I10–I15);
  - a vacuum switch (vgr I4);
  - the air-pressure contact that SYS-05 had assumed (vgr I5).
- **Found: E-stop during a VGR carry drops the cookie** (Y1 vents the ejector). It is recovered by
  the lost-vacuum procedure. The next step is a non-return valve and a small vacuum reservoir.
- **Recovery path proved.** From every waypoint and mid-leg pose of every VGR tour, plunging
  straight up to transit height is clear, so re-homing the arm is safe wherever it stops.
- **Performance.** The bottleneck is the VGR arm (253 s busy), not the oven that the plan
  expected. OEE over one shift with every fault once: availability 69 % × performance 40 % ×
  quality 100 % = 27 %. The buffer still changes nothing.

### Original plan


**Goal.** Test the real control program against the twin before it touches hardware.

### Scope

1. **Coupling.** The twin is driven by the PLC over OPC UA (or Modbus TCP): outputs in, sensor
   states out, at 10 ms or faster.
2. **Physics where it matters.** Motor ramps, belt slip, cylinder travel times and vacuum build-up,
   taken from datasheets and measurements.
3. **Fault injection.** A stuck sensor, a cylinder that never arrives, lost vacuum, an air
   pressure drop, a motor stall, a lost bus node. Each must end in a safe and recoverable state.
4. **Performance.** Measured cycle time, the bottleneck (the oven is the expected one), OEE, and
   the effect of the buffer.

### Blueprint sheets

U5-01 coupling architecture · U5-02 signal map (PLC tag ↔ twin signal) · U5-03 fault matrix
(fault × expected reaction × observed) · U5-04 performance report.

### Proofs that gate it

The whole fault matrix passes. The measured cycle time matches the model within a stated tolerance.

---

## Upgrade 6: operations analytics and predictive maintenance (BUILT)

**Added after Upgrade 5**, at the owner's request: a dashboard attached to the twin, with component
health and early fault detection. The original Upgrade 6 became Upgrade 7.

**As built** (`STF_VARIANT=up6`, `stf-cad/hbw/health.py`):

- **Idea.** Upgrade 4 times every step against a watchdog, and Upgrade 5 measured how close a
  healthy step comes (66 % at worst). A worn part shows up as a drifting step long before it
  trips. Ten components are monitored from signals already on the U5 register map, plus one new
  reading: the actuator current per module from the U3 electronic breaker. The components are
  the cup seal, three cylinders, the HBW belt, the RFID heads, the travel spindle, the swivel
  gearbox, the air supply and the colour sensor.
- **Model.**
  - r = observed / healthy baseline, smoothed by an EWMA.
  - It fails where the tightest step reaches its watchdog, the breaker trips, the pump can't keep
    up, or a flavour crosses its band.
  - It warns at a soft limit (half the margin used) or on a remaining-life trend below 3 shifts.
- **Proof.** Every injected wear mode is warned about well before it fails, from 8.2 shifts ahead
  (the sudden-onset gearbox, wear ∝ n¹⁰) to 145 shifts. There are 0 false warnings in 60,000
  healthy cycles per component.
- **Found.** The RFID read steps had no timeout in Upgrade 4, so a tag that never read would hold
  the belt for ever. U6 gives them one (TRC-01).
- **Dashboard** ("Upgrade 6: operations dashboard"):
  - live KPIs: order progress, throughput, OEE, bottleneck, MTTR and worst health;
  - unit states;
  - component health cards on a machine-age slider, with an "apply predictive maintenance"
    switch;
  - the maintenance planner, the downtime Pareto, traceability search and the MQTT topic list.
- **Blueprint.** U6-01 to U6-05.

## Upgrade 7: maintainability and lifecycle (BUILT)

**As built** (`STF_VARIANT=up7`, `stf-cad/hbw/lifecycle.py`):

- **Tolerance chains (worst case).** Four chains; the cup-seal chains failed badly on U6:

  | Chain | On U6 | On U7 |
  |---|---|---|
  | T1 fork table in the shelf gap | +1.05 mm | +1.05 mm |
  | T2 RP1 head vs the Ausleger | +11 mm | +11 mm |
  | T3 cup seal on a cookie in its mould | **−5.09 mm** | +1.71 mm |
  | T4 cup seal on a cookie in a Lagerstelle | **−8.09 mm** | +1.41 mm |

  The mould pocket let the cookie sit 4.5 mm off-centre, and a Lagerstelle does not locate it at
  all. U7 fixes:
  - a 35 mm cup instead of 40 mm;
  - a conical centring seat in each mould;
  - a V-guide in each Lagerstelle;
  - the VGR stays on its 5 ms task. The smaller cup's margin is spent on part position, not on a
    slower task.
- **Access.** 28 of 28 PCBs, valves, motors and couplers are reachable, from above or the side,
  within 850 mm of a door.
  - The VGR adapter PCB sat 925 mm from the nearest door; U7 moves it 95 mm to 830 mm.
  - The HBW belt motor is under the belt and is serviced from the side.
  - The VGR vacuum valve is exactly at 850 mm, with no margin.
- **Spare parts.** Generated from every module and upgrade, with wear parts sized from Upgrade 6's
  lives.
- **Maintenance plan.** Upgrade 6's intervals and triggers, with the door to use for each task.
- **Structure dynamics** under Upgrade 5's accelerations. Every member is ≤ 0.5 mm and ≥ 20 Hz.
  The lowest mode is the VGR arm vertically, at 29 Hz. Ausleger stage 1, the last load-carrying
  ft block, drops from 0.25 mm (PA6) to 0.025 mm as a 20×20 profile in the same envelope.
- **Still open.** Every tolerance contributor, wear life and density is assumed. The tables are
  the measurement plan.

### Original plan (as written before Upgrade 6 was added)


**Goal.** A cell someone can own for years.

### Scope

1. **Measured model.** Every *assumed* dimension replaced by a measurement, with tolerances. The
   clearance proofs then run on worst-case sizes, not nominal ones.
2. **Condition monitoring.** Motor current, cycle count per cylinder and valve, vacuum level, and
   air consumption, with trends and limits.
3. **Maintenance access.** Every PCB, valve and motor must be reachable from one side without
   removing another module. This becomes a new clear-zone check in `check_cross`.
4. **Spare parts and documentation.** A generated spare-parts list, a maintenance plan by cycle
   count, and wear parts identified.
5. **All-profile structure.** Load-bearing ft blocks replaced with aluminium profile everywhere,
   with a dynamic check (deflection under acceleration, first natural frequency) instead of the
   static sag check.

### Blueprint sheets

U6-01 measured-dimension table · U6-02 access zones · U6-03 spare parts and wear parts ·
U6-04 maintenance plan · U6-05 structure and dynamics report.

---

## Upgrade 8: semi-supervised deep learning for maintenance (BUILT)

**As built** (`stf-cad/hbw/ml/`, `STF_VARIANT=up7 python3 -m ml.train`, then `python3 -m ml.tune`):

- **Data.** 80 simulated machines, 45 days each, run to failure with no maintenance: 242,494
  orders and 469 failures. 64 machines are used for training, and only 8 of
  them have failure records, as a real maintenance log would. 16 machines are held out for testing.
- **Model.** A channel-independent causal temporal CNN with 15,108 parameters: 4 dilated Conv1d layers with a
  residual connection, then MLP heads.
  - It reads one component at a time: its health h = (r − 1) / (r_fail − 1), measured against the limit the machine already
    knows, plus the hall temperature, vacuum losses, order time and the component's identity.
  - It predicts remaining life and a health class (healthy, degrading, critical).
  - A first design gave each component its own output from all signals at once. The rarely failing parts never learned.
- **Semi-supervised training.** Three stages:
  1. self-supervised masked-reconstruction pre-training on all training machines;
  2. supervised fine-tuning on the labelled machines;
  3. Mean Teacher consistency training on the unlabelled machines (Tarvainen & Valpola, NeurIPS 2017).
- **Deployed.** As ONNX for the RevPi (67 kB, identical to PyTorch). Also as JSON weights with a
  TypeScript forward pass that runs in the dashboard, where it matches PyTorch on every order checked (maximum difference 0.0000).
- **Scored on the 16 unseen machines** (96 failures). The alarm threshold was tuned on the labelled machines only:
  the smallest that warns ≥ 95 % of failures a shift ahead.

  | Policy | Warned ≥ 1 shift | Missed | Late | Part life thrown away |
  |---|---|---|---|---|
  | U6 rules | 96/96 | 0 | 0 | 14.5 shifts |
  | semi-supervised network | 64/96 | 26 | 6 | 2.6 shifts |
  | hybrid (the rules flag, the network times the work) | 91/96 | 0 | 5 | 11.8 shifts |

  Remaining-life error: semi-supervised 75.0 orders, supervised-only on the same labels
  81.5, and 48.1 with every label.
- **Verdict.** The rules know each part's true limit and never miss, but they renew parts about 15 shifts early. The network
  times the work far better, but it misses failures on unseen machines, because its threshold, tuned on 8 machines, doesn't
  carry over. The network therefore goes in as an advisory remaining-life estimate beside the rules (shadow mode), until it is
  trained on real run-to-failure data. The semi-supervised stages still give a better estimate from the same labels.
- **Limits.** Everything is trained and tested on simulated machines whose wear laws were written by hand.

## Upgrade 9: the cell as a microgrid (BUILT)

**As built** (`stf-cad/hbw/grid.py`, over the month):

- **Assets.** Mains → a 600 W hybrid inverter in online UPS mode, a 1 kWh LFP battery and 400 Wp of PV → the 24 V PSU → the U3
  breaker. The design follows EN 50160, IEC 61000-4-30, OpenADR 2.0b, IEEE 1547-2018, SunSpec Modbus and ISO 50001.
- **Energy management.** A day-ahead dynamic programme over the battery's charge (10 Wh steps, 15 minutes) against time-of-use
  and day-ahead prices, with a battery-wear cost. A real-time guard holds the peak cap and covers forecast misses during
  demand-response windows. It never discharges into the 30 % ride-through reserve.
- **Month results.**

  | | Grid only | PV only | PV + battery + EMS |
  |---|---|---|---|
  | Cost | €14.37 | €7.08 | €6.16 |
  | CO₂ | 12.95 kg | 8.53 kg | 7.2 kg |
  | Self-sufficiency | 0 % | 40 % | 48 % |

  - All 3 demand-response events were met with the battery.
  - 10/10 mains events were ridden through, against
    1/10 without the inverter.
- **Findings.**
  - The ride-through reserve beats peak shaving: the demand peak stays at 83.9 W against a 70 W cap,
    because on dull mornings the battery sits at its reserve.
  - The energy bill alone pays back in 13.9 years. The case rests on ride-through, demand response
    and the data.
- **Power-asset maintenance.**
  - A cabinet sensor sees the air filter clogging, and the filter is changed in the night gap. Without that, the PSU's capacitors
    (Arrhenius) would lose 31 % of their life.
  - PV soiling shows up in the performance ratio, and it triggers one cleaning.
  - Battery state of health and contactor wear are tracked.

## Upgrade 10: throughput (BUILT)

**As built** (`STF_VARIANT=up10`, `stf-cad/hbw/throughput.py`; changes in `control.py` and `vgr_path.py`, gated by `control.OPT`):

- **The problem Upgrade 5 left.** 636 s for the 12-cookie order, OEE 27 %, and no unit busy even half the time. The critical
  path showed why: it ran round the *mould loop* (crane → belt → the whole VGR tour to the oven → belt back → crane). The VGR held
  the mould for its entire 25 s tour (229 s of the path).
- **Four measures, each proven before it is measured.**
  - *split*: the VGR job is cut where the cookie leaves the mould (`belt_to_oven` is now the pick half, then `place_oven`). The oven
    presents its tray (`present`) while the arm picks, and the arm may hold the next cookie while the tray is still busy.
  - *blend*: each VGR crossing flies 20 mm above the lowest height the SAT sweep proves clear, and swings while it climbs. The
    waypoint count stays the same, so every binding keeps one step structure. The belt→oven tour drops from 25.5 s to 11.2 s. Results are
    cached in `.cache/`.
  - *dual*: a dual-command crane. The mould coming in is stored in the free slot nearest the next cookie, which is retrieved on
    the same trip (`store_retrieve`).
  - *zero*: a leg with nothing to move costs a 50 ms position check, not the 0.4 s minimum. This only corrects the nominal
    schedule; the commissioned plant never waited on those legs.
- **Proofs.**
  - The explorer finds no deadlock under any timing (single 2203 states, reuse 1787, buffer 1787), and prefetch still deadlocks.
  - Every blended tour is swept at 1°/2 mm.
  - VC: the healthy run is 429.8 s against a nominal 425.7 s (+1.0 %), and the fault matrix passes 7/7.
  - The plunge-up recovery holds from 592 poses.
- **Results** (commissioned):

  | | Before | After |
  |---|---|---|
  | Order | 636.0 s | 429.8 s (−32 %) |
  | Cookies an hour | 50.9 | 75.4 |
  | Steady-state cycle | 64.1 s | 41.1 s |
  | OEE (the order + every fault once) | 27 % | 31 % |

  The measures interact. Each one alone saves: blend 122 s, split 86 s, dual 30 s. Removing each one from the full set costs:
  blend 90 s, split 54 s, dual 30 s.
- **Findings.**
  - The bottleneck moved from the VGR (253 s busy) to the crane (210 s). The next step is on the warehouse side (a second fork, or
    retrieving to a staging position).
  - Availability falls (69 % → 63 %) because the same fault losses now weigh on a shorter order.
  - With a real 120 s bake the gain shrinks to 10 %: the oven limits the order.
  - A cookie dropped after the pick has no mould to go back to, so the operator lays it on the presented tray (vc.py).
  - The alarm table's watchdog limit is now the longest of its steps. Before, it was the first step's, which is wrong once zero legs exist.

## Upgrade 11: OT security to IEC 62443 (BUILT)

**As built** (`STF_VARIANT=up11`, `stf-cad/hbw/security.py` → `web/public/security/`: `security.json`, `cell_firewall.nft`,
`st_manifest.json`):

- **Zones.** Z0 is the hardwired safety circuit, with no network interface. Z1 is cell control (the PLC and 4 nodes, SL-T 2).
  Z2 is supervisory (HMI, historian, EMS). Z3 is energy (inverter, BMS). Z4 is the DMZ (dashboard, OpenADR VEN, jump host). Z5 is
  untrusted.
- **Conduits.** There are 8 conduits (C1 to C8) with protocol, direction and authentication; the other 20 zone pairs are denied.
  Every path from the internet to the cell crosses an authenticated hop.
- **Allow-list, generated from the program.** The PLC's reads and writes (from the state machines of `control.py`) are mapped onto
  the register map of `vc.py`. That gives 25 Modbus DPI rules for 70 accesses: FC15 writes over exactly the coils the program
  drives, the FC1 read-back of the same coils, and FC2/FC3/FC4 reads. The EMS may write only the SunSpec 124 storage set points; the
  reserve and grid charging stay local.
- **Proofs.**
  - Least privilege: every access is allowed, and no spare or retired coil is writable.
  - Default deny.
  - No networked device is in any safety function.
  - Every SL-C gap has a countermeasure.
  - A signed ST manifest (SEC-03).
  - New alarms SEC-01 to SEC-04.
- **Attacks replayed on the twin** (6 of 6 contained):

  | Attack | Result on the twin |
  |---|---|
  | Rogue coil write | Detection is too slow: the crane hits the rack after 27 ms; read-back sees it in 40 ms, but the crane moves 13.5 mm (4 mm clearance). Only prevention works. |
  | Spoofed sensor | The twin's physics catches an instant lie on 49 of 49 moving steps. A lie told on time over a jammed fork is not caught (23 mm), so authenticated I/O is needed. |
  | Flood | Safe through SYS-04 (−33 s per event). |
  | Program download | Blocked by the signed manifest. |
  | Drained battery reserve | Without the controls, 9 of the month's 10 mains events fail. |
  | Forged demand-response event | A 2.8 h window empties the ride-through reserve. |
- **Findings.**
  - F1: the three compressor outputs Upgrade 1 retired are still wired to live coils.
  - F2: every jog interlock is software only; a hardwired Ausleger-back contact in series with the travel relays matters most.
  - F3: U9's EMS let a demand-response window go below the ride-through reserve.
  - Soft link: the guard locks are released by the PLC's standstill signal.
- **Limits.** Component SL-C values are assumed by product class. This is a design and a model-based assessment, not a
  penetration test.

## Validation of Upgrades 1-11 (2026-09-30)

`stf-cad/hbw/validate.py` runs everything again from outside the upgrades (22.6 min on 10 cores); the report is
`docs/VALIDATION.md`, and the dashboard's "Validation" page reads `web/public/validation/validation.json`.

- **Regression.** All 10 variants re-exported through their own proof gates, and every fingerprint equals its baseline
  (`validation/baseline.json`).
- **Robustness.** The U7 and U10 programs were run against 25 random plants each, with every step time varied by ±20 %. No
  watchdog tripped falsely, and U10's slowest run still beats U7's fastest.
- **Mutation tests.** A defect is planted in each proof, and all 9 are caught.
  - One gap was found while writing M1: the explorer checked that cookies were conserved, but not that the VGR's cup holds only
    one. With that invariant off, a dispatcher handing the arm a second job survives. The invariant is now in `control.py`.
  - M4 took three tries.
    - Flying the blended crossing 80 mm lower is still clear, because the height search never goes below the higher station.
      That was no defect.
    - 60 mm was caught, but by the joint-limit check, not the collision sweep.
    - 100 mm, inside the joint limits, is caught by the sweep itself: the carried cookie clips the HBW light barrier. At
      120 mm the crossing would still be clear.
- **Data.**
  - month.json is unchanged, and `grid.py` is deterministic.
  - The network agrees across all its deployments: PyTorch against ONNX 0.0, and the browser's JSON weights (re-implemented in
    numpy) against PyTorch 3e-5 orders, over 600 windows.
  - pytest and the web build pass.

## Upgrade 12: defence in depth (BUILT)

**As built** (`STF_VARIANT=up12`, `stf-cad/hbw/hardening.py` + `interlock.py`; changes in `io_nodes.py`, `safety.py`, `grid.py`):

- **Hardwired interlocks.** Every jog rule of `control.JOG` is a candidate, and it is adopted only if all three hold:
  - the machine already has its permissive switch;
  - replaying the whole order as the PLC runs it (homing first, 13 jobs of steps) never finds a step it would block;
  - violating it is a collision.

  Five are adopted: crane travel with the fork back (IL1), the Ofenschieber with the door open (IL5), Sauger travel with the Sauger
  up (IL6), the Drehtisch with the Auswerfer home (IL7), and the ejectors with the belt stopped (IL8). Each is an interface relay
  on its node's rail, whose contact is in series with the guarded relays' coil supply. The nodes were re-placed and re-cleared.
  Three stay in software:
  - IL2 (lift only with the fork back) would block the program's own pick, which is 36 steps.
  - IL3 (Ausleger only at a slot) has no switch to read.
  - IL4 (VGR swivel only at transit height) blocks 36 steps of Upgrade 10's blended path, but none of Upgrade 7's. The faster
    program and this hard limit exclude each other.
- **Standstill monitor K8.** A lock is released only on the PLC's request AND 0 V on the actuator bus. `safety.check_logic` covers
  26,628 states, and a PLC request alone never unlocks.
- **Dead wires out.** The retired compressor outputs are unwired. Nothing writable is unused, and the allow-list drops to 19 rules.
- **Reserve held in demand response.** This costs nothing this month: the real events never took the battery below 31 %. It
  bites only on a longer or forged event, which U9 let drain the battery to 10 %.
- **Found on the way.** `io_nodes` sized its spare capacity as a share of the channels *used*, while its check counts a share of
  *capacity*. The two agreed until U12 left the oven 13 outputs: 2 slices, 18.75 % free. The formula is fixed, and it gives the
  same slices for every earlier variant.
- **Re-run attacks.**
  - A compromised PLC driving the crane sideways with the fork in a shelf moves 0 mm, against 13.5 mm with detection alone.
  - F1, F3 and the soft link are closed.
- **Limits.** The interlocks protect the machine; they are not safety functions, and no performance level is claimed.

## Upgrade 13: software-in-the-loop PLC (BUILT)

**Why.** Upgrade 4 generated the PLC program, but nothing had ever compiled or run it: commissioning (U5) timed its
steps, it did not execute them. Without hardware, the next best evidence is the program compiled by an independent
IEC 61131-3 compiler and run, scan by scan, against a plant that only sees its outputs.

**As built** (`STF_VARIANT=up12`, `stf-cad/hbw/sil/`, `web/src/sil/`):
- **Program** (`sil/iec.py`). One IEC 61131-3 project, 1,929 lines of Structured Text, regenerated from the same models:
  - eight unit function blocks with per-axis positioning (brake lead of half a scan), target and watchdog tables per binding;
  - MAIN: `control.py`'s dispatcher translated statement for statement (factory state, `complete()`, the priority loop);
  - located I/O (`%IX`, `%QX`, `%IW` RFID and colour, `%ID` encoders) and a `%MW` monitor; one 5 ms task.
- **Compiler** (`sil/build.py`). MatIEC (`iec2c`, the compiler inside OpenPLC and Beremiz) parses and type-checks it and
  emits C. A generated runtime places every located variable in a flat I/O image and advances the IEC clock. clang makes
  one WebAssembly module (164 KB, no imports).
- **Plant** (`web/src/sil/plant.ts`, numbers from `sil/plant.py`). I/O-level and material-tracking: crane, belt with RFID
  heads, VGR with its vacuum switch, oven, Sauger, Drehtisch, Auswerfer, sorting belt with colour sensor, pulse counter,
  ejectors and bays. It flags crashes, drops, motors driven both ways and the Ofenschieber moving against the door.
- **One binary, two places.** The proof runs `plc.wasm` against the plant under Node; the twin runs the same file in the
  visitor's browser.

**Proofs** (`python3 -m sil.run`, about 35 s):
1. Every one of the 103 job decisions the compiled program takes is the decision `control.py`'s proven dispatcher takes
   from the same state (completions replayed in order).
2. The plant ends as the order requires: 9 cookies baked and in their flavour's bay, 3 back in the rack, 12 moulds in 12
   slots, nothing left in transit.
3. No watchdog tripped and the plant flagged nothing.
4. Order time 386 s against the model's 426 s, within 10 %. (Faster: the cylinders run at 80 % of the booklet time,
   as `vc.py` assumes, and the plant has no motor ramps.)
5. It can fail: three mutants are each rejected.
   - SM1, production order swapped: rejected at the first decision.
   - SM2, red and blue colour bands swapped: the sorting line refuses the cookie.
   - SM3, slot A1 aimed at the next column: the crane fetches the wrong mould, RFID RP2 reads M02 where the record says
     M01, and the belt's watchdog stops the line.
   A mutant that stores in the farthest free slot is equivalent here: with 12 moulds in 12 slots there is never more
   than one free slot to choose.

**Findings.** U4's program is rejected by MatIEC (910 errors). Writing it properly, then running it, exposed ten problems:

| # | Found by | Finding |
|---|---|---|
| F1 | compiler | the step variable was `Step`, a reserved word |
| F2 | compiler | every positioning step waited for one undeclared `Target[Arg]` |
| F3 | review | `Done` was never cleared, so a unit's second job could not be seen to end |
| F4 | review | MAIN was only comments |
| F5 | review | a three-axis VGR move drove every axis until the step ended, so the first to arrive overran |
| F6 | compiler | conditions were prose (`RF2.tag = record`, `count(I1) = N_eject`, `I5 broken`) |
| F7 | run | homing left the lift at its bottom switch; every crane job starts at transit height |
| F8 | run | the single-acting oven door fell shut on the extended Ofenschieber between U10's `present` and `place_oven` |
| F9 | run | the Drehtisch's 180° return had the time of a 90° turn, so its watchdog tripped |
| F10 | run | watchdogs were the same for every binding: the 8 s run to the blue ejector was watched as 2.4 s |

F8 is a real design flaw of Upgrade 10, not a simulation artefact: the model kept "tray presented" as a state, but the
door only stays open while its valve is on.

**Limits.** The plant has no motor ramps or bus delays (U5 covers those); the light-barrier polarity, the pulse pitch
and the colour readings of the belt and of raw dough are assumed. Only the Upgrade 12 program is generated.

**Tools** (not in the repository): MatIEC built from source (`STF_MATIEC`), and clang, wasm-ld and the WASI sysroot
(Homebrew `llvm lld wasi-libc wasi-runtimes`). The compiled `plc.wasm` is committed, so the twin and CI need neither.

## Upgrade 15: vision inspection, trained on rendered images (BUILT)

**Why.** The colour sensor (A4) tells the flavour but not whether a cookie is cracked, chipped, burnt or underbaked.
A camera and a small network can, but there is no camera and no cookie to photograph. Training on images rendered
from the model, and testing honestly how far that carries, is the core method of physical AI: learn in simulation,
deploy in the world.

**As built** (`stf-cad/hbw/vision/`, `web/src/vision/`):
- **Renderer** (`render.py`). A top-down camera upstream of the colour sensor: 64 x 64 px over 80 mm. The cookie's size,
  the flavour and dough colours, the twin's bake blend and the belt rubber come from the model. Five conditions: ok,
  underbaked, burnt, cracked, chipped. Everything a real image varies in is randomised: position, rotation, size, light
  level and colour, shading, belt texture, noise, focus.
- **Network** (`train.py`). Four 3x3 convolutions (16-32-64-64), batch norm in training, folded into the weights for
  deployment, global average pooling and two heads: flavour and condition. 65k parameters. A grey reference target
  sits in a corner of the field of view, as inspection stations mount one, and the network divides the image by its
  reading.
- **Decision.** A cookie passes only if the condition head says ok with p >= 0.5. If the head is unsure (max p < 0.6),
  the cookie goes to a person. Escapes (defects passed) and false rejects are counted separately.
- **Deployed** as ONNX for an edge controller (checked with ONNX's reference evaluator: 6e-6) and as weights for the
  browser, whose forward pass matches PyTorch to 3e-5 on the published test images (checked under Node). The twin's
  panel classifies 48 test images live (about 40 ms each).

**Results.** Each network is tested once on 3,000 unseen images like its training data, and on 3,000 drawn under
conditions it never saw: darker and brighter light, a warmer lamp, a worn belt, more noise and motion blur.

| Under unseen conditions | Narrow randomisation | Wide randomisation | Wide + grey reference (deployed) |
|---|---|---|---|
| Condition right | 28 % | 64 % | 67 % |
| Good cookies rejected | 91 % | 53 % | 30 % |
| Defects passed | 3.0 % | 3.4 % | 1.7 % |
| Flavour right | 77 % | 92 % | 93 % |

On images like its training data the deployed network gets 98.8 % of conditions and 98.6 % of flavours right, with
0.4 % escapes and 0.7 % false rejects.

**What this shows.**
- Narrow randomisation memorises: under a new lamp it rejects almost every good cookie.
- Wider randomisation doubles the robustness, and the reference target, an engineering fix rather than more data,
  halves the false rejects again.
- Even so, 30 % false rejects under unseen conditions is not deployable. The remaining errors are chips seen against a
  worn, lighter belt, and cracks under blur. On a real line the next step is a few hundred real images to fine-tune
  on, and a controlled lighting enclosure. This is the honest limit of training on rendered images alone.

**Limits.** The renderer's faults, lighting and belt are ASSUMED. The numbers show the method and the deployment path,
not the accuracy on a real camera. The panel does not yet feed the PLC: a reject path into the program (a reject bay
and a new job in MAIN, re-proved by Upgrade 13's software-in-the-loop) is the follow-up.

---

## Order and dependencies

```
U1 utilities ─┬─> U2 safety ──> U3 I/O + carriers ──> U4 program ──> U5 commissioning
              └────────────────────────────────────────────────────────> U6 lifecycle
```

U2 comes next because nothing else would pass an industrial review without it, and it fits the
model as it is: guards are parts, interlocks are rules, and "no motion with a guard open" is a
proof.
