# PLC program: overview

The Smart Tabletop Factory is run by **one IEC 61131-3 program**: eight unit sequencers and
an orchestrator, generated from the same models that prove the machine's motion. The twin
compiles it with MatIEC to WebAssembly and runs it in the browser against the simulated plant
every 5 ms (software in the loop). Nothing in the 3D view moves unless this
program drives an output.

```plc-architecture
```

## Program structure

- **Units**: one `FUNCTION_BLOCK` per unit. Each is a step sequence `INIT -> homing -> READY ->
  job steps -> READY`, with `FAULT` and `ESTOP` reachable from every state. A unit drives only
  its own outputs.
- **Orchestrator** (`PROGRAM MAIN`): a PLC scan that, after every job completion, offers the units
  jobs in one fixed priority order, following the dispatch policy (here: `reuse`). It tracks the factory state: slots, moulds, belt ends, oven, bins.
- **Positioning**: each axis is driven toward its own target and stops half a scan's travel
  before it (the brake lead), so a three-axis robot move ends with every axis in tolerance.
- **Watchdogs**: every step that moves something has a time limit (1.5 x nominal + 0.5 s); past
  it the unit drops its outputs and goes to `FAULT` with an alarm.

## The units

| Unit | Module | Function block | Outputs | Jobs | What it does | Source lines |
|---|---|---|---|---|---|---|
| crane | high-bay warehouse | `FB_Crane` | Q3 Q4 Q5 Q6 Q7 Q8 | retrieve, fetch_empty, store, store_retrieve | HBW crane: travel, lift, Ausleger | 13-336 |
| belt | high-bay warehouse | `FB_Belt` | Q1 Q2 | belt_fwd, belt_back | HBW belt and the two RFID read points | 337-410 |
| arm | vacuum gripper robot | `FB_Arm` | Q1 Q2 Q3 Q4 Q5 Q6 Q8 | belt_to_oven, bay_to_belt, belt_to_buf, buf_to_oven, place_oven | VGR arm and vacuum | 411-754 |
| door | multi-processing oven | `FB_Door` | Q5 Q6 Q9 Q13 | bake, to_tt, present | oven door, Ofenschieber and lamp | 755-854 |
| sauger | multi-processing oven | `FB_Sauger` | Q7 Q8 Q11 Q12 | to_tt | oven Sauggreifer | 855-938 |
| turntable | multi-processing oven | `FB_Turntable` | Q1 Q2 Q4 Q14 | saw_eject | Drehtisch, Saege and Auswerfer | 939-1023 |
| ovenbelt | multi-processing oven | `FB_Ovenbelt` | Q3 | ovenbelt | oven belt | 1024-1075 |
| line | sorting line | `FB_Line` | Q1 Q3 Q4 Q5 | sort | sorting line and ejectors | 1076-1166 |

## Size of the program

| Measure | Value |
|---|---|
| source | 1929 lines of Structured Text |
| compiler | MatIEC iec2c matiec version 0.1 |
| scan time | 5 ms |
| digital inputs / outputs | 32 / 32 |
| analogue / RFID words | 2 |
| encoder positions | 5 |
| monitoring words for the HMI | 90 |
| units / jobs | 8 / 15 |
| alarms | 46 |
| a 12-cookie order, in the loop | 386.48 s (78253 scans, 103 orchestrator decisions) |
| the same order, as the model predicts | 425.7 s |

## How to read the chapters

1. [Hardware and wiring](01-hardware.md): the controller, the remote I/O, the 24 V conventions.
2. [I/O map](02-io-map.md): every signal with its address in the program.
3. [Unit sequencers](03-units.md): every unit's steps, outputs, completion signals and limits.
4. [Orchestrator and dispatch](04-orchestrator.md): jobs, priorities, the policies and why one deadlocks.
5. [Alarms](05-alarms.md): every alarm, its cause, the machine's reaction and the recovery.
6. [Safety and manual mode](06-safety.md): ESTOP, FAULT, the safety relay, jog permits.
7. [Verification](07-verification.md): what compiling and running the program found and proves.
8. [Traceability](08-traceability.md): moulds, RFID read points, colour bands and the trace record.

4 modules: high-bay warehouse (crane, belt); vacuum gripper robot (arm); multi-processing oven (door, sauger, turntable, ovenbelt); sorting line (line).

*Sources: `web/public/sil/stf_plc.st`; `web/public/hbw_parts_up12.json (control)`; `web/public/sil/plc.json`; `web/public/sil/sil.json`.*

*Generated from the twin's exports by `docs/gen/plc_docs.py`; do not edit.*
