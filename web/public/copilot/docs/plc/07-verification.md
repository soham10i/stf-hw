# PLC verification

The program is checked three ways: proofs on the model it is generated from, a compiler, and
a run of the compiled program against the simulated plant (software in the loop).

## Proofs on the model

1. Every unit state reaches `READY` and `ESTOP`; outputs are off in `INIT`, `READY`, `FAULT` and
   `ESTOP`; no motor is driven both ways; every signal is in the Belegungsplan; every motion
   has a timeout.
2. The orchestrator, explored exhaustively over every completion order (every possible
   timing), never deadlocks, conserves 12 cookies and 12 moulds, and ends with every cookie in
   its bin.
3. Every cookie's trace record is complete, and its flavour is confirmed by the colour sensor.


<!-- Sources: `stf-cad/hbw/control.py (module docstring: PROOFS)`. -->

## Compiling and running it

Compiler: MatIEC iec2c matiec version 0.1. The compiled program ran a 12-cookie order against the plant:
homed at 4.785 s, done at 391.265 s, 78253 scans, 103
orchestrator decisions; the model predicts 425.7 s.

| Check | Result |
|---|---|
| decisions | pass |
| plant | pass |
| faults | pass |
| timing | pass |

## What compiling and running found

The first program (written as text by Upgrade 4) did not compile, and could not have run. Each
finding was fixed in the generator, and the run repeated:

| Id | Kind | Finding |
|---|---|---|
| F1 | compile | The U4 program used `Step` as a variable, a reserved word of IEC 61131-3: MatIEC rejected it. |
| F2 | compile | Every positioning step waited for one undeclared `Target[Arg]`; each step needs its own target. |
| F3 | logic | `Done` was set and never cleared, so the orchestrator could not see a unit's second job end. |
| F4 | logic | The orchestrator (MAIN) existed only as comments. |
| F5 | logic | A multi-axis VGR move drove every axis until the step ended: the axes that arrived first overran. |
| F6 | compile | Several step conditions were prose (RF2.tag = record, count(I1) = N_eject, I5 broken). |
| F7 | run | Homing left the crane's lift at its bottom reference switch; every job starts at transit height. |
| F8 | run | The oven door (single-acting) fell shut on the extended Ofenschieber between U10's present and place. |
| F9 | run | The Drehtisch's 180 degree return had the time of a 90 degree turn: its watchdog tripped. |
| F10 | run | Watchdogs were the same for every binding: the run to the blue ejector (8 s) was watched as 2.4 s. |

## Mutants: can the checks fail?

Deliberate faults put into the program; each must be caught by the run:

| Id | Fault | Result | How it was caught |
|---|---|---|---|
| SM1 | the production order's first two cookies swapped in MAIN | caught | t=4.785: the program started [('retrieve', ('c01', 'M02', 'A2'))], control.py [('retrieve', ('c00', 'M01', 'A1'))] |
| SM2 | the colour bands of red and blue swapped | caught | the order did not complete in 3600 s (states {'crane': 100, 'belt': 100, 'arm': 2001, 'door': 3001, 'sauger': 100, 'turntable': 100, 'ovenbelt': 100, 'line': 1001}) |
| SM3 | slot A1's travel target set to the next column | caught | the order did not complete in 3600 s (states {'crane': 100, 'belt': 910, 'arm': 100, 'door': 100, 'sauger': 100, 'turntable': 100, 'ovenbelt': 100, 'line': 100}) |


<!-- Sources: `web/public/sil/sil.json`; `stf-cad/hbw/sil/iec.py (module docstring)`. -->

<!-- Generated from the twin's exports by `docs/gen/plc_docs.py`; do not edit. -->
