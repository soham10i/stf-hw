# PLC orchestrator and dispatch

`PROGRAM MAIN` (lines 1167-1923) is the orchestrator: every scan it reads the units' state,
and when a unit finishes a job it offers jobs again in one fixed priority order. A job is
bound to its arguments (a cookie, a mould, a slot, a bay) and may need several units at once.

## Jobs and the units they need

| Job | Units | Bound to |
|---|---|---|
| sort | line | cookie, bay |
| ovenbelt | ovenbelt | cookie |
| saw_eject | turntable | cookie |
| to_tt | sauger, door | cookie |
| bake | door | cookie |
| present | door | cookie |
| place_oven | arm, door | cookie, source |
| belt_to_oven | arm, belt | cookie, mould |
| bay_to_belt | arm, belt | cookie, bay, mould |
| belt_back | belt | mould, cookie |
| store_retrieve | crane, belt | mould, cookie, slot, cookie, mould, slot |
| belt_fwd | belt | mould, cookie |
| store | crane, belt | mould, cookie, slot |
| fetch_empty | crane, belt | mould, slot |
| retrieve | crane, belt | cookie, mould, slot |

## Dispatch policies

Each policy was explored exhaustively over every order in which jobs can complete (every
possible timing). The PLC runs the one in bold.

| Policy | Rule | 12-cookie order | States explored |
|---|---|---|---|
| prefetch | the crane fetches the next mould as soon as the crane end of the belt is free | deadlocks | 38 |
| single | one mould on the belt at a time; empty moulds go back into the rack | 492.2 s | 2203 |
| **reuse** | + an empty mould at the hand-over is refilled with a cookie going into the rack | 425.7 s | 1787 |
| buffer | + the VGR parks raw cookies in Upgrade 1's buffer while the oven is busy | 425.7 s | 1787 |

### Why `prefetch` deadlocks

crane end of the belt: mould M01 empty, going back in; VGR hand-over: mould M03 empty, going back in. The belt can only move one way at a time and each move needs the other end free - a circular wait on one belt

The trace that ends in the deadlock: `sort('c00', 'blau')` -> `belt_to_oven('c02', 'M03')` -> `bake('c01',)` -> `to_tt('c01',)` -> `saw_eject('c01',)` -> `present('c02',)` -> `place_oven('c02', 'belt')` -> `ovenbelt('c01',)` -> `sort('c01', 'weiss')` -> `bake('c02',)` -> `to_tt('c02',)` -> `saw_eject('c02',)` -> `ovenbelt('c02',)` -> `sort('c02', 'rot')`.

## Bake time and order time

How long a 12-cookie order takes as the bake gets longer: the oven becomes the bottleneck
and the policies converge.

| Bake (s) | single | reuse | buffer |
|---|---|---|---|
| 2.0 | 492.2 | 425.7 | 425.7 |
| 30.0 | 594.5 | 542.2 | 542.2 |
| 60.0 | 848.8 | 805.3 | 805.3 |
| 120.0 | 1388.8 | 1345.3 | 1345.3 |


*Sources: `web/public/hbw_parts_up12.json (control.policies, control.study)`; `web/public/sil/plc.json (jobs, job_units, layout)`; `web/public/sil/stf_plc.st#L1167-L1923`.*

*Generated from the twin's exports by `docs/gen/plc_docs.py`; do not edit.*
