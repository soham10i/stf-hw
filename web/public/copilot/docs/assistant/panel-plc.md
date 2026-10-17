# Panel: PLC

Two sub-tabs. The choice is remembered.

## Live run

The actual PLC program, IEC 61131-3 Structured Text compiled by MatIEC to WebAssembly, scanned in
the browser against a plant model (software in the loop). Controls: pause/run, speed 1x/4x/16x/64x,
restart. The tag shows the phase (Homing, Running the order, Order complete) and the clock.

- **Proven line**: how many of the program's decisions match the proven orchestration model
  (every job start is replayed in control.py), how many planted mutants the check caught, and the
  order time.
- **Units**: one row per unit (crane, belt, arm, door, sauger, turntable, ovenbelt, line) with its
  state number and what the state means. 100 = ready, 910 = fault, 1000+ = busy in a job.
- **I/O image**: every input and output per module, lit when on.
- **Jobs**: the last job starts and ends, and the plant's last events.
- **About this program** (folded): what the run exposed, the source size, compiler and hash.
  *Source* opens the Structured Text.

The plant sees only the program's outputs; light barriers, the vacuum switch, RFID and the colour
sensor report what is physically there.

## Program & HMI

The operator screen, replaying the PLC's planned run of the 12-cookie order at 20x.

- **Units** with state lights, the job each is doing and the step.
- **Order**: how many cookies are baked and sorted, and how many returned to the rack.
- Folded: **Alarms** (preview any alarm: cause, reaction, recovery, watchdog), **Cookie trace**
  (click a cookie: every RFID read and timestamp, and its colour reading against its record),
  **Manual jog** (which outputs each axis uses and when jogging is allowed: mode MANUAL, guard
  closed, hold-to-run) and **Dispatch policies compared**.

## Dispatch policies

The rule that decides which mould moves next, each explored over every possible completion order:

| Policy | What it does | Order time |
|---|---|---|
| prefetch | the crane fetches the next mould as soon as the belt is free | deadlocks |
| single | one mould on the belt at a time | 492.2 s |
| reuse (used) | an empty mould at the hand-over is refilled with a cookie going into the rack | 425.7 s |
| buffer | reuse, plus the robot parks raw cookies in a buffer while the oven is busy | 425.7 s |
