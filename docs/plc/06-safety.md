# PLC safety and manual mode

## Emergency stop and faults

- **ESTOP**: the two-channel safety relay K0 drops `Enable` for every unit at once. Every state
  has a transition to `ESTOP` on `NOT Enable`; outputs are off in `ESTOP`. Leaving it needs the
  reset S3 through the safety relay, then the unit homes again (`ESTOP -> INIT`).
- **FAULT**: a watchdog or a failed sensor puts one unit in `FAULT` with its alarm. Outputs are
  off; the operator clears the cause and acknowledges on the HMI (`FAULT -> READY` on `Ack AND
  Enable`).
- **Force-guided contactors K1 and K2** switch the actuators' 24 V, so a stop removes the power
  that moves anything, not only the program's command.
- Outputs are off in `INIT`, `READY`, `FAULT` and `ESTOP` (proved, chapter 7).

## Manual jog permits

In manual mode an axis may be jogged only when the model says the move is safe from where
the machine is:

| Unit | Axis | Outputs | Allowed when | Checked by |
|---|---|---|---|---|
| crane | travel | Q3/Q4 | Ausleger at its rear stop (I6) | hbw_model.pose_allowed |
| crane | lift | Q5/Q6 | Ausleger back, or at a column inside the slot band | hbw_model.fork_allowed |
| crane | Ausleger | Q7/Q8 | only at a rack column or the conveyor, at a slot height | hbw_model.fork_allowed |
| belt | belt | Q1/Q2 | crane Ausleger back (I6), VGR cup not at the belt | vgr_path plunge band 'belt' |
| arm | swivel | Q5/Q6 | plunge at transit height (500 mm) - swing only up high | vgr_path.plan legs |
| arm | plunge | Q1/Q2 | inside the station's plunge band | factory_layout.vgr_plunge_allowed |
| arm | reach | Q3/Q4 | descent reach of the station below transit | vgr_path.descent_reach |
| door | Ofenschieber | Q5/Q6 | door open (Q13 on) | oven_model.pose_allowed (door/slider) |
| door | door | Q13 | Ofenschieber fully in (I6) or fully out (I7) | oven_model.pose_allowed |
| sauger | Sauger travel | Q7/Q8 | Sauger up (Q12 off) | oven_model.pose_allowed (Q12 at a stop) |
| sauger | lower | Q12 | Sauger at a stop (I8 or I5) | oven_model.pose_allowed (Q12 at a stop) |
| turntable | turn | Q1/Q2 | Auswerfer home, Sauger up | oven_model.pose_allowed |
| turntable | Auswerfer | Q14 | Drehtisch at the belt (I2) | oven_model.pose_allowed (Auswerfer at the belt) |
| ovenbelt | belt | Q3 | Auswerfer home | - |
| line | belt | Q1 | no ejector out | sorting_model.pose_allowed |
| line | ejectors | Q3/Q4/Q5 | belt stopped, one ejector at a time | sorting_model.pose_allowed |

## Design rules the layout keeps

- The identification tunnel starts at y=580, past the far end of the extended telescope (y=555), so the crane can descend to the belt at any height without a forbidden lift band.
- The Ausleger telescopes +Y only. The rack and the belt are both on that side, so one stop (115) serves a bay and the hand-over alike.
- Extended only where a station exists at that height.

Retired outputs (driven by nothing, after the upgrades replaced their actuators): vacuum gripper robot: Q7; multi-processing oven: Q10; sorting line: Q2.

<!-- Sources: `web/public/hbw_parts_up12.json (control.units edges, control.jog, interlocks, control.retired)`; `web/public/hbw_parts_up12.json (plc.parts: safety_relay_K0, contactor_K1, contactor_K2)`. -->

<!-- Generated from the twin's exports by `docs/gen/plc_docs.py`; do not edit. -->
