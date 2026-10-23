# The precision simulation engine

The upgrade of the STF twin (`stf-live`) from a kinematic animation into a deterministic,
millimetre-accurate simulation: physics and electrics in workers at a fixed 100 Hz, float64
master state, a graph netlist, and the main thread as a renderer only.

Status: **Deliverables 1-4 built and verified**: the shared-memory bridge, the physics worker,
CAD mating and snapping, and the live netlist with its fault checks. Not yet wired into the 3D
twin's UI (see "Next").

## File tree

New and planned files are marked; everything else is the repository as it is.

```
stf-hw/
├── Dockerfile, docker-compose.yml, render.yaml   deployment (Render service "stf-live")
├── Makefile, pyproject.toml
├── docs/
│   ├── architecture/
│   │   └── simulation-engine.md          NEW  this document
│   ├── DEPLOY.md, SECURITY.md, ...            operations
│   └── maintenance/, plc/, process/, ...      the engineering record
├── packages/                                  Python: the twin's models (shared with the API)
├── services/api/                              FastAPI: copilot, live link, records, security
│   └── app.py                                 sends COOP + COEP (cross-origin isolation)
├── stf-cad/                                   FreeCAD generators: parts, drawings, exports
├── supabase/                                  the factory database schema
├── tests/                                     Python tests
└── web/                                       the twin and the dashboard (Vite, React, three.js)
    ├── vite.config.ts                         dev server sends COOP + COEP (isolation plugin)
    └── src/
        ├── core/                         NEW  engine core, main-thread side
        │   ├── schema.ts                 NEW  part / project schemas, strict parsers, pin table
        │   ├── SimulationBridge.ts       NEW  D1: shared memory layout, seqlock, input mutex
        │   ├── math64.ts                 NEW  float64 poses: quaternions, compose, slerp
        │   ├── PhysicsClient.ts          NEW  starts the worker, reads snapshots, sends commands
        │   └── *.test.ts                 NEW  layout, torn-frame, mutex, schema tests
        ├── workers/                      NEW  headless simulation threads
        │   ├── protocol.ts               NEW  main <-> worker messages, roles, joints, telemetry
        │   ├── physicsCore.ts            NEW  D2: Rapier world, fixed step, modes (thread-free)
        │   ├── physics.worker.ts         NEW  D2: the 100 Hz accumulator loop, WebSocket intake
        │   ├── physicsCore.test.ts       NEW  conveyor, sensor, chains, telemetry, determinism
        ├── cad/                          NEW
        │   ├── SnapEngine.ts             NEW  D3: connector mating, 0.1 mm grid, twist steps
        │   └── SnapEngine.test.ts        NEW
        ├── circuit/                      NEW
        │   ├── NetlistSolver.ts          NEW  D4: adjacency matrix, shorts, overvoltage (runs in
        │   │                                  the physics worker after every step)
        │   └── NetlistSolver.test.ts     NEW
        ├── scene/                             the 3D machine (R3F); becomes a reader of the bridge
        │   └── engine/CellCoordinator.ts      today's cell logic, still on the main thread
        ├── twin/, panels/, views/             the twin's shell, side panels, controller view
        ├── dashboard/                         the operations dashboard
        ├── sil/, vision/, shared/             PLC software-in-the-loop, inspection, shared UI
        └── copilot/                           offline copilot fallback
```

## Deliverable 1: the simulation bridge (`web/src/core/SimulationBridge.ts`)

One buffer, one layout, read in place by both threads:

| bytes | view | contents |
|---|---|---|
| 0-63 | `Int32[16]` header | magic `STFB`, version, **seqlock**, capacities, counts, mode, step (2 words), flags, **input mutex**, input sequence |
| 64-95 | `Float64[4]` | simulation time (s), publish wall time (ms), fixed timestep, real-time rate |
| 96- | `Float64[7·parts]` | per part: position x y z (mm), quaternion x y z w |
| - | `Float64[pins]` / `Int32[pins]` | pin voltage; flags `HIGH`, `FORCED`, `TELEMETRY`, `FAULT` |
| - | `Float64[pins]` / `Int32[pins]` | inputs the UI forces (a pushed button), `INPUT_SET` |
| - | `Float64[9·axes]` | per motor axis: position, rpm, current, volts, encoder count, task, last error, crashes, homed (version 2) |

Every array starts on an 8-byte boundary.

- **State: one writer, lock-free readers (seqlock).** The worker bumps the sequence to odd,
  writes, bumps it to even. The renderer copies and keeps the copy only if it saw the same even
  sequence before and after; otherwise it keeps its last frame. The renderer never waits for
  physics and never draws a torn frame (tested with a real second thread writing 200,000 frames).
- **Inputs: two writers, a mutex.** `Atomics.compareExchange` takes it, `Atomics.store` +
  `Atomics.notify` gives it back. The worker may sleep on it (`Atomics.wait`); the main thread
  may not block, so it only tries and retries on its next frame.
- **Float64 until the GPU.** `downcastForRender` is the only float32 conversion, done relative to
  an origin so far-away parts keep their precision.
- **Without isolation** (GitHub Pages cannot send headers) the same layout lives in an ordinary
  `ArrayBuffer`; the worker transfers a copy after each publish and the reader adopts it.

## Deliverable 2: the physics worker (`web/src/workers/`)

- `physics.worker.ts` - the loop. Real time (times the run rate) fills an accumulator, and
  fixed 10 ms steps (`fixedTimeStep = 1 / 100`) drain it, at most 25 per wake-up. A backlog
  beyond that (a background tab) is dropped and counted as an overrun, never run in a burst.
  It owns the WebSocket for live telemetry.
- `physicsCore.ts` - one `stepOnce()` is one step; nothing in it reads a clock. Commands
  (spawn, belt speed, mode, inputs) are queued and applied between steps, so the same commands
  at the same steps give the same run.
  - **Units:** millimetres, z up; Rapier is told `lengthUnit = 1000`.
  - **Kinematic chains:** joint values become poses composed parent-first in float64; that pose
    is what is published.
  - **Conveyors:** Coulomb-limited carrying, at most `mu * g * dt` of relative velocity per step;
    the belt collider has no friction of its own.
  - **Sensors:** a sensor volume drives its pin while a dynamic body is inside.
- **Modes:**
  - `SIMULATION_MODE`: joints follow planned tracks; Rapier steps.
  - `LIVE_TELEMETRY_MODE`: joints follow the factory's `joint_angles`, interpolated on a playout
    clock one delay behind the newest sample (catching up after a stall); `sensor_states` drive
    the pins; a stale buffer is flagged.

## Deliverable 3: mating and snapping (`web/src/cad/SnapEngine.ts`)

`calculateSnapTransform(activePart, candidateParts, snapThresholdMm = 5, gridSnapMm = 0.1, options?)`

- **Candidates:** every connector of the dragged part is tried against every free connector of
  the same mating type within the threshold. Parts whose boxes are out of reach are skipped first.
  The nearest pair wins, and ties go by instance and node id, so the result never depends on the
  candidates' order.
- **The turn:** the shortest rotation that makes the dragged connector's normal point straight
  into the target's (`normalDot` = -1 to 1e-14), applied to the part's current turn. A connector
  facing the same way as the target's is flipped half a revolution. Optionally the turn about the
  mating axis rounds to a step (`twistStepDeg: 15`, BenchTwin's "Turn 15°"), measured against
  the target part's frame.
- **The move:** the two connector points meet. The position is then locked to the grid, by its
  decimal (0.3, not 0.30000000000000004). A mate between parts placed on the grid lands on it
  exactly. Otherwise `residualMm` says how far the grid moved the connectors apart, at most half
  a step per axis, instead of silently leaving a part off the grid.
- No pair in range: the part keeps its turn and its position snaps to the grid.

## Deliverable 4: the live netlist (`web/src/circuit/NetlistSolver.ts`)

- **The graph:** every pin of every placed part is a vertex. Wires (all pin pairs of a
  `wire_net`) and **closed** contacts (relays, switches, jumpers) are zero-impedance edges in an
  n x n adjacency matrix. Loads are not edges, so current through a motor is never a short.
  Connected components are the electrical nodes, rebuilt only when wiring or a contact changes.
- **Supplies are declared** (a positive terminal at a voltage, and its ground), because the
  schema's pin types do not say which part is a source.
- **Checks on every node:**
  - `SHORT_CIRCUIT`: a supply's positive terminal and a ground on one node (no load between), or
    two supplies at different voltages joined.
  - `OVERVOLTAGE`: the node's voltage outside a pin's `voltage_limits`. The voltage comes from
    its supply, else from the pins the simulation drives (a sensor output, a forced input); a
    floating node is not judged.
- **Output:** one diagnostic per wire net, plus any faulted node no net names:
  `{ status, affectedInstances, netId, pins, volts, message }`, the message in plain words.
- **Continuous:** the physics worker evaluates after every step's pins, sets `PIN_FAULT` on the
  faulted pins in the shared bridge (for the 3D view to highlight or burn), and posts the
  diagnostics only when a status changes. Rewiring (`setNets`) is checked against the schema
  first; contacts change with `setContact`.

## Where this differs from the brief, and why

- **There is no float64 Rapier for JavaScript.** `rapier3d-f64` is not published; every JS
  build stores float32. The engine uses `@dimforge/rapier3d-deterministic-compat` (identical
  results on every platform) and keeps the **master** state float64 outside it. Fixed and
  kinematic parts are published from their float64 pose, exactly (a 123.4 mm joint lands at
  exactly 1123.4 mm). Only free bodies (cookies) carry the solver's float32, about 0.0001 mm at
  factory scale.
- **SharedArrayBuffer needs cross-origin isolation.** The API, `vite preview` and the dev server
  now send `Cross-Origin-Embedder-Policy: require-corp` beside the existing
  `Cross-Origin-Opener-Policy`. This is safe because the CSP already loads nothing from another
  origin. Static hosting uses the transfer fallback.
- **MQTT** reaches the worker through a WebSocket bridge (JSON samples, one or an array); a
  browser cannot open MQTT's TCP port, and an MQTT client library would add weight for no gain
  over the broker's own WebSocket listener.
- **Today's cell logic** (`scene/engine/CellCoordinator.ts`, the PLC sequence that moves the
  machine) still runs on the main thread. Moving it into the worker is the next migration step;
  the worker already accepts its output as joint tracks.

## Step 1: the Test bench (the sorting line on the engine)

The first part of the factory that runs on the engine, and is drawn from the bridge:

- **The world from the CAD export** (`web/src/scene/bench/sortingWorld.ts`). The sorting line's
  own boxes, placed in the factory frame in float64:
  - the belt (a conveyor), with frictionless guide rails flush with its top;
  - the three bays, with smooth plastic floors (μ 0.15), the base plate, and the three pushers;
  - the five light barriers I2, I3, I5, I6 and I7, each a 3 mm beam from its transmitter to its
    receiver driving an OUT pin.
- **Actuators with motion profiles** (`driveStep`, `JointDrive`). A driven joint accelerates at
  most `amax`, cruises at most `vmax` and brakes to land exactly on its target. The braking limit
  is the discrete one, so it never lands harder than one step of acceleration. The ejectors are
  pneumatic cylinders: 90 mm in about 0.15 s (900 mm/s, 15 m/s²). A `pulse` command is one
  stroke: out, hold, back.
- **Drawn from shared memory** (`scene/bench/BenchBodies.tsx`). The cookies at their poses, the
  pushers' strokes, the belt's travel and the beams cut by the physics' own pins.
- **The Test bench panel**: start, pause, add a cookie, fire an ejector, set the belt speed, and
  live readings (each barrier, each stroke, steps per second). Rapier loads only when the bench
  starts; the twin's own bundle does not carry it.

Verified, in Node at 40, 60 and 100 mm/s and in Chrome through the real worker:
- a cookie passes I2, then I3;
- the white ejector fired at x = 459 mm pushes it into the white bay, where it rests at
  y = 67.0 mm, the twin's own hand-over point;
- I5 sees it, I6 and I7 do not, and the pusher returns exactly home.

## Step 2: encoder motors and reference switches (the warehouse axes)

- **The motor** (`web/src/workers/motors.ts`): the fischertechnik 24 V encoder motor 144643 from
  its datasheet (`docs/144643-Encodermotor24V.pdf`).
  - A straight speed-torque line: 440 rpm with no load, stall at 1800 g·cm (0.177 N·m), 0.60 A.
    At another voltage the line shifts in proportion.
  - Shorted leads (the 24 V board's "off") brake it through its back EMF.
  - Against it act the spindle's Coulomb friction and a constant load torque (the lift's weight).
  - Between steps the speed follows its exact exponential solution, so the motion is the same at
    10 ms or 1 ms steps (to 1e-9).
  - The spindle friction comes from the lab calibration, not a guess. On a straight line, 214 rpm
    means a load of 1 − 214/440 of stall; the no-load current follows from the booklet's 320 mA
    there.
  - The model reproduces:
    - 440 rpm, 0.60 A at stall, and the 2.03 W peak;
    - 214 rpm and 14.27 mm/s on the 4 mm spindle, at 320 mA;
    - braking within 3 encoder pulses, and the spindle holding the lift against gravity.
  - The inertia is not published: [assumed] a 20 ms mechanical time constant.
- **Encoder:** 75 pulses per output turn (25:1 gearbox, 3 pulses per motor turn), 18.75 per mm.
  The count is published in the bridge's new axes region, version 2.
- **Reference switches:** the Mini-Taster closes at its point with 0.5 mm differential travel.
  The CAD switch boxes are photo estimates (the carriage would stop 10 mm short of I1), so each
  closes at the axis end the CAD export documents. The hard stops are [assumed] 3 mm beyond.
- **The PLC's positioning block** (`scan`) runs every 10 ms scan, on the inputs of the scan
  before:
  - homing drives to the reference switch and zeroes the count where it closed;
  - a move switches the motor off a brake lead before the target;
  - an axis without an encoder (the fork) drives until its end switch.
  - A move before homing is refused, and a jog into the mechanism's end is a crash. A refused
    command is reported without stopping the world.
- **The warehouse world** (`web/src/scene/bench/warehouseWorld.ts`):
  - travel, lift and fork as nested kinematic frames from the CAD export;
  - three motors: travel and lift with encoders, the fork by I5 and I6;
  - I1, I4, I5 and I6 riding the frames that carry them;
  - the lift loaded by the carriage's [assumed] 0.25 kg.
- **The brake lead, measured on the model:** at full speed a 10 ms scan is 2.7 counts of travel,
  so where the PLC switches the motor off spreads over that. Over 24 targets a lead of 2 stops
  every move within two counts and most within one (1 and 4 reach three); step 2 first reported
  "within one count" from a single target, corrected in step 3. The true position also carries
  the homing offset: the count is zeroed a scan after the switch closed while the axis coasts on,
  about 0.1 mm, as on the machine.
- **The Test bench panel** has a Warehouse axes module:
  - Home all; move each axis to the PLC program's stops; jog and stop;
  - per axis: position, encoder count, speed, current, task, the last stop's error and crashes;
  - the four switches; runs at 1×, 2×, 4× or 8×.
  - The crane in 3D is drawn from the worker's axis positions. The panel reads the bridge on its
    own timer, so a background tab, which stops rendering, does not stop the readings.
- **Verified in Chrome:**
  - homing ran at 214 rpm, 14.27 mm/s and 320 mA, and stopped 0.22 mm past I1;
  - the travel to bay 2 stopped at 240.13 mm (+1 count as the PLC sees it), and the lift to
    row B at 240.08 mm (0 counts);
  - the lift goes down slightly faster (218 rpm) than up, with its weight;
  - 800 steps/s at 8× takes 0.05 ms per step.

## Step 3: the warehouse belt and the robot arm's motors

- **A motor can drive a belt** (`AxisMotor.belt`): the conveyor's surface speed follows the
  motor's speed × the travel per output turn, each step. A belt with a motor refuses a plain
  belt-speed command.
- **Switches can be sensors** (`AxisSwitch` without `at`): the axis reads the pin a light
  barrier's volume drives, and waits on it with `until`.
- **Homing that starts on its switch leaves it first** (`leave`), then comes back onto it, so the
  count is always zeroed coming from the same side. With `homeCreepV` it also comes onto the
  switch a second time, slowly.
- **The S-Motor 24V** (`S_MOTOR_24V`, booklet 536634 p.9): 10 700 rpm, 5 mNm, 300 mA, 64.8:1, so
  165 rpm at the output. [assumed] 50 % gearbox efficiency, 40 mA no-load, 20 ms time constant.
  `loadedTo(spec, rpm)` sets a load's friction from a speed, as the spindles' came from 214 rpm.
- **The warehouse belt** (`warehouseWorld.ts`): M1 on the 20 mm drum, one conveyor body over both
  belt strips, smooth side rails, I2 (inside, at the crane) and I3 (outside, at the gripper) as
  beams. Its load is set so it runs at the project's [assumed] 50 mm/s, 48 rpm, 225 mA. A mould
  (60 × 64 × 20 mm, [assumed] 40 g) is set at the crane's hand-over (doc.belt.handover).
  - Finding: `doc.belt.I3` says y 370, but the CAD's I3 parts stand at y 572-587. The parts are
    used.
- **The robot arm** (`vgrWorld.ts`), a third bench module: swivel, plunge and reach as nested
  kinematic frames from `doc.vgr`, the cup riding the arm; I3 on the base, I1 on the tower, I2 on
  the carriage.
  - Plunge and reach: 4 mm spindles (the CAD's notes); the plunge lifts [assumed] 0.6 kg.
  - The swivel's gearing is not documented. The CAD draws a 90 mm pinion on the 180 mm ring:
    642°/s and 2.4° (17 mm at the belt) a count, a placeholder. [assumed] 16.8° a motor turn gives
    the kernel's 60°/s: 0.224° a count.
  - I3 is a cam: closed at 0° and below, so the PLC knows which side it is on.
  - The swivel homes a second time at 15 V. At full speed one 10 ms scan is 0.6°, which would
    zero the count up to 4 mm off at the belt; at 15 V it is 0.14°, under a count. Below about
    12.3 V the motor does not start against its friction. PWM on the controller's outputs is
    [assumed].
- **The swivel homes counter-clockwise** onto its cam, as the occupancy plan's homing output Q6
  ("rotate counter-clockwise") says; step 3 first had it clockwise.
- **Slowing one motor is not free on this board:** the RevPi DIO's outputs do PWM (its datasheet,
  40-400 Hz), but the adaptor PCB reverses each motor through relays and slows motors only by a
  reduced voltage on terminal 1 - all bidirectional motors at once. The swivel's slow homing pass
  works because the arm homes its axes one after another, the swivel last.
- **Precision at the belt hand-over:** the CAD's solved pose (69.013°, 236.857 mm) lands the cup
  3.08 mm from the target: the swivel stops at 69.449° - the target rounds to count 308 (69.08°),
  it stopped one count over (309), and the homing zero sits 0.09° past the cam's edge - and the
  reach on its count (236.82 mm). Over 24 targets the swivel stops within two counts, most within
  one. **The swivel's encoder is the arm's precision limit:** one count is 1.58 mm at 405 mm out,
  against 0.053 mm for a spindle count, so the hand-over is good to about ±3 mm.
- **The kernel's speeds disagree with the CAD's drives.** `control.py` plans the arm's linear
  axes at 120 mm/s; on 4 mm spindles the encoder motor gives 14.27 mm/s. Homing the plunge takes
  ~17 s, not 2. This matters for step 5 (cycle times).
- **Verified in Chrome:**
  - the arm homed and went to the belt hand-over: 69.236° (+1 count), reach 236.82 mm (0
    counts), plunge homed at 540.21 mm, the same as in Node; 800 steps/s at 8× (before the
    homing direction was corrected; the Node result after it is 69.449°);
  - a mould sent out ran at 50.0 mm/s, 48 rpm, 225 mA, and the belt stopped with I3 cut.

## The physics plan: how the components will move

The aim: every movement comes from **control plus physics**, not from a script. The PLC program
switches outputs; actuators respond with their real dynamics; parts move by contact and friction;
sensors see what is physically there; the PLC reacts.

1. **Actuators from their datasheets.** Each replaces a scripted track:
   - *Encoder motors* (the ft 24 V encoder motor, `docs/144643-Encodermotor24V.pdf`): a DC
     motor with its torque-speed line, gearbox and load inertia (a first-order speed response).
     They drive the warehouse axes, the robot arm, the turntable and the belts, and emit encoder
     pulses on their B pins as they turn.
   - *Pneumatics*: compressor, valve (a Q output), pressure rising in the cylinder, force =
     pressure × area − friction, end-of-stroke cushioning. Then the robot arm's vacuum gripper,
     with a holding force: a cookie carried too fast is dropped.
   - *Reference switches*: real contact geometry, so homing stops where the switch closes.
2. **Sensors as physics.** Light barriers (done) and reference switches. The colour sensor's
   analogue value from the cookie's colour and distance. Input thresholds by IEC 61131-2 (done),
   then debounce and a little noise.
3. **The PLC in the loop, inside the worker.** The cell's sequence (today `CellCoordinator` on
   the main thread, and the PLC software-in-the-loop in `web/src/sil/`) moves into the worker
   and runs on a fixed scan cycle against the pins. Each scan it reads the inputs the physics
   set, and writes outputs that drive the actuators. Timing faults then become real: an ejector
   fired late misses its cookie.
4. **Electrics coupled to motion.** `controller.json`'s changeover relays become contacts in
   the netlist. A motor runs only when its relay pair connects it to the 24 V supply, and both
   relays on is a stop, as on the real board. Overcurrent and shorts come from the solver, and a
   part that burns stops working.
5. **Precision and speed.**
   - Physics at a fixed 100 Hz, with stiff actuators sub-stepped inside each step (pneumatics at
     1 kHz).
   - Continuous collision detection for fast small bodies.
   - Collision shapes from the CAD boxes; only moving parts update.
   - A budget under 2 ms per step; today's sorting line takes 0.2-0.4 ms.
6. **Validation.** Parameters come from the datasheets. Simulated cycle times are compared with
   the twin's recorded ones (`validation/baseline.json`). Determinism is checked by the state
   fingerprint, in Node and in the browser.

Order of work:
1. Encoder motors and reference switches: the warehouse axes (done, step 2), its belt and the
   robot arm (done, step 3).
2. Pneumatics with valves and pressure: the ejectors, then the vacuum gripper.
3. The PLC sequence in the worker, driving everything from the pins.
4. The 24 V board's relays in the netlist.
5. Validation against the recorded cycle times.

## Next

1. Draw more of the twin from the bridge (done for the sorting line's bench), module by module
   as each moves onto the engine.
2. Move the cell logic (`CellCoordinator`) into the worker as joint tracks, so the main thread
   only renders.
3. Build the factory's own world from the CAD export and `controller.json`:
   - parts with their real connectors and pins;
   - the 24 V supply and the relay contacts as `supplies` and `contacts`.
4. The editor: drag with `calculateSnapTransform`, draw wires into `wire_nets`, and show the
   diagnostics in a Checks panel (BenchTwin's "Circuit checks").

## Verified

- Web tests: 97 pass (45 new: the bridge and its threading, the mutex, the fallback, the schema,
  physics, snapping and the netlist).
- In Chrome (dev server, isolated): shared bridge, Rapier 0.21.0, **99.7 steps/s, 0 overruns,
  0.31 ms per step**. 521 steps took 5.21 s of wall time (real time). A cookie carried 520 mm
  ended at x = 539.589 mm, z = 23.986 mm, and the light barrier went high at step 366.
- **The same scenario in Node gives the same step and the same position to the micrometre**:
  deterministic across engines.
- The twin still loads under isolation, with no blocked resources.
- **The circuit through the real worker, in Chrome:**
  - Closing a relay contact across the 24 V supply posted `SHORT_CIRCUIT` at once and set the
    fault bit on `+24V` in shared memory. Opening it cleared both.
  - Rewiring a 5 V sensor onto the 24 V rail posted `OVERVOLTAGE`: "s5.VCC takes 0 to 5.5 V but
    its node is at 24 V".
