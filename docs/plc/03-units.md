# PLC unit sequencers

Each unit is a step sequence. A step sets its outputs, waits for its completion signal
(`done`), and is watched by a time limit when it moves anything. Every state can fall to
`ESTOP` (the safety relay drops `Enable`) and every moving step to `FAULT` (its watchdog).
Times are the model's nominal times, in seconds.

## crane: HBW crane: travel, lift, Ausleger

Module: high-bay warehouse. Outputs: Q3 Q4 Q5 Q6 Q7 Q8. Jobs: retrieve, fetch_empty, store, store_retrieve.
Function block `FB_Crane`, lines 13-336 of the source.

```plc-sfc crane
```

| Step | What happens | Outputs on | Done when | Nominal (s) | Watchdog (s) |
|---|---|---|---|---|---|
| INIT | power-up: all outputs off | - | - | - | - |
| H:fork | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| H:lift | lift to the reference switch (direction ASSUMED: down) | Q5 | I4 | 1.87 | 3.3 |
| H:travel | travel to the reference switch (direction ASSUMED: to the belt) | Q4 | I1 | 3.63 | 6.0 |
| READY | homed, waiting for a job | - | - | - | - |
| retrieve.01 | travel to the slot column | Q3 | \|pos_travel - 120\| <= 1 (B1/B2) | 3.63 | 6.0 |
| retrieve.02 | lift to row-20 | Q5 | \|pos_lift - 100\| <= 1 (B3/B4) | 1.07 | 2.1 |
| retrieve.03 | Ausleger out to its front stop | Q7 | I5 | 0.77 | 1.7 |
| retrieve.04 | lift to row | Q6 | \|pos_lift - 120\| <= 1 (B3/B4) | 0.4 | 1.1 |
| retrieve.05 | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| retrieve.06 | lift to transit | Q6 | \|pos_lift - 260\| <= 1 (B3/B4) | 0.93 | 1.9 |
| retrieve.07 | travel to the conveyor | Q4 | \|pos_travel - 665\| <= 1 (B1/B2) | 3.63 | 6.0 |
| retrieve.08 | lift to 100 | Q5 | \|pos_lift - 100\| <= 1 (B3/B4) | 1.07 | 2.1 |
| retrieve.09 | Ausleger out to its front stop | Q7 | I5 | 0.77 | 1.7 |
| retrieve.10 | lift to 80 | Q5 | \|pos_lift - 80\| <= 1 (B3/B4) | 0.4 | 1.1 |
| retrieve.11 | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| retrieve.12 | lift to transit | Q6 | \|pos_lift - 260\| <= 1 (B3/B4) | 1.2 | 2.3 |
| fetch_empty.01 | travel to the slot column | Q3 | \|pos_travel - 120\| <= 1 (B1/B2) | 3.63 | 6.0 |
| fetch_empty.02 | lift to row-20 | Q5 | \|pos_lift - 100\| <= 1 (B3/B4) | 1.07 | 2.1 |
| fetch_empty.03 | Ausleger out to its front stop | Q7 | I5 | 0.77 | 1.7 |
| fetch_empty.04 | lift to row | Q6 | \|pos_lift - 120\| <= 1 (B3/B4) | 0.4 | 1.1 |
| fetch_empty.05 | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| fetch_empty.06 | lift to transit | Q6 | \|pos_lift - 260\| <= 1 (B3/B4) | 0.93 | 1.9 |
| fetch_empty.07 | travel to the conveyor | Q4 | \|pos_travel - 665\| <= 1 (B1/B2) | 3.63 | 6.0 |
| fetch_empty.08 | lift to 100 | Q5 | \|pos_lift - 100\| <= 1 (B3/B4) | 1.07 | 2.1 |
| fetch_empty.09 | Ausleger out to its front stop | Q7 | I5 | 0.77 | 1.7 |
| fetch_empty.10 | lift to 80 | Q5 | \|pos_lift - 80\| <= 1 (B3/B4) | 0.4 | 1.1 |
| fetch_empty.11 | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| fetch_empty.12 | lift to transit | Q6 | \|pos_lift - 260\| <= 1 (B3/B4) | 1.2 | 2.3 |
| store.01 | lift to 80 | Q5 | \|pos_lift - 80\| <= 1 (B3/B4) | 1.2 | 2.3 |
| store.02 | Ausleger out to its front stop | Q7 | I5 | 0.77 | 1.7 |
| store.03 | lift to 100 | Q6 | \|pos_lift - 100\| <= 1 (B3/B4) | 0.4 | 1.1 |
| store.04 | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| store.05 | lift to transit | Q6 | \|pos_lift - 260\| <= 1 (B3/B4) | 1.07 | 2.1 |
| store.06 | travel to the slot column | Q3 | \|pos_travel - 120\| <= 1 (B1/B2) | 3.63 | 6.0 |
| store.07 | lift to row | Q5 | \|pos_lift - 120\| <= 1 (B3/B4) | 0.93 | 1.9 |
| store.08 | Ausleger out to its front stop | Q7 | I5 | 0.77 | 1.7 |
| store.09 | lift to row-20 | Q5 | \|pos_lift - 100\| <= 1 (B3/B4) | 0.4 | 1.1 |
| store.10 | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| store.11 | lift to transit | Q6 | \|pos_lift - 260\| <= 1 (B3/B4) | 1.07 | 2.1 |
| store.12 | travel to the conveyor | Q4 | \|pos_travel - 665\| <= 1 (B1/B2) | 3.63 | 6.0 |
| store_retrieve.01 | lift to 80 | Q5 | \|pos_lift - 80\| <= 1 (B3/B4) | 1.2 | 2.3 |
| store_retrieve.02 | Ausleger out to its front stop | Q7 | I5 | 0.77 | 1.7 |
| store_retrieve.03 | lift to 100 | Q6 | \|pos_lift - 100\| <= 1 (B3/B4) | 0.4 | 1.1 |
| store_retrieve.04 | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| store_retrieve.05 | lift to transit | Q6 | \|pos_lift - 260\| <= 1 (B3/B4) | 1.07 | 2.1 |
| store_retrieve.06 | travel to the slot column | Q3 | \|pos_travel - 120\| <= 1 (B1/B2) | 3.63 | 6.0 |
| store_retrieve.07 | lift to row | Q5 | \|pos_lift - 120\| <= 1 (B3/B4) | 0.93 | 1.9 |
| store_retrieve.08 | Ausleger out to its front stop | Q7 | I5 | 0.77 | 1.7 |
| store_retrieve.09 | lift to row-20 | Q5 | \|pos_lift - 100\| <= 1 (B3/B4) | 0.4 | 1.1 |
| store_retrieve.10 | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| store_retrieve.11 | lift to transit | Q6 | \|pos_lift - 260\| <= 1 (B3/B4) | 1.07 | 2.1 |
| store_retrieve.12 | travel to the next slot's column | Q4 | \|pos_travel - 240\| <= 1 (B1/B2) | 0.8 | 1.7 |
| store_retrieve.13 | lift to row-20 | Q5 | \|pos_lift - 100\| <= 1 (B3/B4) | 1.07 | 2.1 |
| store_retrieve.14 | Ausleger out to its front stop | Q7 | I5 | 0.77 | 1.7 |
| store_retrieve.15 | lift to row | Q6 | \|pos_lift - 120\| <= 1 (B3/B4) | 0.4 | 1.1 |
| store_retrieve.16 | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| store_retrieve.17 | lift to transit | Q6 | \|pos_lift - 260\| <= 1 (B3/B4) | 0.93 | 1.9 |
| store_retrieve.18 | travel to the conveyor | Q4 | \|pos_travel - 665\| <= 1 (B1/B2) | 2.83 | 4.8 |
| store_retrieve.19 | lift to 100 | Q5 | \|pos_lift - 100\| <= 1 (B3/B4) | 1.07 | 2.1 |
| store_retrieve.20 | Ausleger out to its front stop | Q7 | I5 | 0.77 | 1.7 |
| store_retrieve.21 | lift to 80 | Q5 | \|pos_lift - 80\| <= 1 (B3/B4) | 0.4 | 1.1 |
| store_retrieve.22 | Ausleger back to its rear stop | Q8 | I6 | 0.77 | 1.7 |
| store_retrieve.23 | lift to transit | Q6 | \|pos_lift - 260\| <= 1 (B3/B4) | 1.2 | 2.3 |
| FAULT | a step timed out: outputs off, alarm raised | - | - | - | - |
| ESTOP | safety relay dropped: outputs off (K1/K2 open) | - | - | - | - |

Recovery: `FAULT` -> `ESTOP` when NOT Enable; `FAULT` -> `H:fork` when Ack AND Enable; `ESTOP` -> `INIT` when Reset (S3) AND Enable.


*Sources: `web/public/hbw_parts_up12.json (control.units.crane)`; `web/public/sil/stf_plc.st#L13-L336`.*

## belt: HBW belt and the two RFID read points

Module: high-bay warehouse. Outputs: Q1 Q2. Jobs: belt_fwd, belt_back.
Function block `FB_Belt`, lines 337-410 of the source.

```plc-sfc belt
```

| Step | What happens | Outputs on | Done when | Nominal (s) | Watchdog (s) |
|---|---|---|---|---|---|
| INIT | power-up: all outputs off | - | - | - | - |
| H:check | occupancy check: I2/I3 against the record | - | record = I2, I3 | 0.1 | None |
| READY | homed, waiting for a job | - | - | - | - |
| belt_fwd.01 | belt out to the VGR hand-over; RP1 reads the tag on the fly | Q1 | I3 AND RF1.valid | 5.1 | 8.1 |
| belt_fwd.02 | RP2 reads the tag at rest and compares it with the record | - | RF2.valid AND RF2.tag = record | 0.3 | 0.9 |
| belt_back.01 | RP2 reads the tag of the mould going in | - | RF2.valid AND RF2.tag = record | 0.3 | 0.9 |
| belt_back.02 | belt back to the crane; RP1 reads the tag on the fly | Q2 | I2 AND RF1.valid | 5.1 | 8.1 |
| FAULT | a step timed out: outputs off, alarm raised | - | - | - | - |
| ESTOP | safety relay dropped: outputs off (K1/K2 open) | - | - | - | - |

Recovery: `FAULT` -> `ESTOP` when NOT Enable; `FAULT` -> `H:check` when Ack AND Enable; `ESTOP` -> `INIT` when Reset (S3) AND Enable.


*Sources: `web/public/hbw_parts_up12.json (control.units.belt)`; `web/public/sil/stf_plc.st#L337-L410`.*

## arm: VGR arm and vacuum

Module: vacuum gripper robot. Outputs: Q1 Q2 Q3 Q4 Q5 Q6 Q8. Jobs: belt_to_oven, bay_to_belt, belt_to_buf, buf_to_oven, place_oven.
Function block `FB_Arm`, lines 411-754 of the source.

```plc-sfc arm
```

| Step | What happens | Outputs on | Done when | Nominal (s) | Watchdog (s) |
|---|---|---|---|---|---|
| INIT | power-up: all outputs off | - | - | - | - |
| H:plunge | plunge up to the reference switch | Q1 | I1 | 3.8 | 6.2 |
| H:reach | reach back to the reference switch | Q3 | I2 | 3.33 | 5.5 |
| H:swivel | swivel to the reference switch | Q6 | I3 | 4.33 | 7.0 |
| READY | homed, waiting for a job | - | - | - | - |
| belt_to_oven.01 | swing to the source at transit height | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| belt_to_oven.02 | descend beside the source | Q2 Q4 Q5 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 2.49 | 4.2 |
| belt_to_oven.03 | extend over the source | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| belt_to_oven.04 | cup meets the cookie's top face | Q2 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_oven.05 | press: the spring stem takes up the over-travel | Q2 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_oven.06 | Q8 vacuum on: the cup seals on the cookie (I4 made) | Q8 | I4 | 0.5 | 1.2 |
| belt_to_oven.07 | spring relaxes - seal holds | Q1 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_oven.08 | lift the cookie clear | Q1 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_oven.09 | retract out from the station | Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| belt_to_oven.10 | rise to transit height | Q1 Q4 Q6 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.54 | 1.3 |
| bay_to_belt.01 | swing to the source at transit height | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| bay_to_belt.02 | descend beside the source | Q2 Q4 Q6 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 3.02 | 5.0 |
| bay_to_belt.03 | extend over the source | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| bay_to_belt.04 | cup meets the cookie's top face | Q2 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| bay_to_belt.05 | press: the spring stem takes up the over-travel | Q2 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| bay_to_belt.06 | Q8 vacuum on: the cup seals on the cookie (I4 made) | Q8 | I4 | 0.5 | 1.2 |
| bay_to_belt.07 | spring relaxes - seal holds | Q1 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| bay_to_belt.08 | lift the cookie clear | Q1 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| bay_to_belt.09 | retract out from the station | Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| bay_to_belt.10 | rise to transit height | Q1 Q4 Q5 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 1.21 | 2.3 |
| bay_to_belt.11 | swing to the target at transit height | Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| bay_to_belt.12 | descend beside the target | Q2 Q4 Q5 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 1.21 | 2.3 |
| bay_to_belt.13 | extend over the target | Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| bay_to_belt.14 | cup meets the cookie's top face | Q2 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| bay_to_belt.15 | press: the spring stem takes up the over-travel | Q2 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| bay_to_belt.16 | Q8 off: the cookie is released (I4 drops) | - | NOT I4 | 0.3 | 0.9 |
| bay_to_belt.17 | spring relaxes | Q1 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| bay_to_belt.18 | lift clear | Q1 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| bay_to_belt.19 | retract out from the station | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| bay_to_belt.20 | rise to transit height | Q1 Q3 Q6 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 2.49 | 4.2 |
| bay_to_belt.21 | VGR back home | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| belt_to_buf.01 | swing to the source at transit height | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| belt_to_buf.02 | descend beside the source | Q2 Q4 Q5 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 2.49 | 4.2 |
| belt_to_buf.03 | extend over the source | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| belt_to_buf.04 | cup meets the cookie's top face | Q2 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_buf.05 | press: the spring stem takes up the over-travel | Q2 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_buf.06 | Q8 vacuum on: the cup seals on the cookie (I4 made) | Q8 | I4 | 0.5 | 1.2 |
| belt_to_buf.07 | spring relaxes - seal holds | Q1 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_buf.08 | lift the cookie clear | Q1 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_buf.09 | retract out from the station | Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| belt_to_buf.10 | rise to transit height | Q1 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.82 | 1.7 |
| belt_to_buf.11 | swing to the target at transit height | Q3 Q5 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_buf.12 | descend beside the target | Q2 Q3 Q5 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 1.35 | 2.5 |
| belt_to_buf.13 | extend over the target | Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| belt_to_buf.14 | cup meets the cookie's top face | Q2 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_buf.15 | press: the spring stem takes up the over-travel | Q2 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_buf.16 | Q8 off: the cookie is released (I4 drops) | - | NOT I4 | 0.3 | 0.9 |
| belt_to_buf.17 | spring relaxes | Q1 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_buf.18 | lift clear | Q1 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| belt_to_buf.19 | retract out from the station | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| belt_to_buf.20 | rise to transit height | Q1 Q3 Q6 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 3.02 | 5.0 |
| belt_to_buf.21 | VGR back home | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| buf_to_oven.01 | swing to the source at transit height | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| buf_to_oven.02 | descend beside the source | Q2 Q4 Q5 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 3.02 | 5.0 |
| buf_to_oven.03 | extend over the source | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| buf_to_oven.04 | cup meets the cookie's top face | Q2 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| buf_to_oven.05 | press: the spring stem takes up the over-travel | Q2 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| buf_to_oven.06 | Q8 vacuum on: the cup seals on the cookie (I4 made) | Q8 | I4 | 0.5 | 1.2 |
| buf_to_oven.07 | spring relaxes - seal holds | Q1 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| buf_to_oven.08 | lift the cookie clear | Q1 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| buf_to_oven.09 | retract out from the station | Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| buf_to_oven.10 | rise to transit height | Q1 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 1.35 | 2.5 |
| place_oven.01 | swing to the target at transit height | Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| place_oven.02 | descend beside the target | Q2 Q4 Q6 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.72 | 1.6 |
| place_oven.03 | extend over the target | Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| place_oven.04 | cup meets the cookie's top face | Q2 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| place_oven.05 | press: the spring stem takes up the over-travel | Q2 Q8 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| place_oven.06 | Q8 off: the cookie is released (I4 drops) | - | NOT I4 | 0.3 | 0.9 |
| place_oven.07 | spring relaxes | Q1 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| place_oven.08 | lift clear | Q1 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.4 | 1.1 |
| place_oven.09 | retract out from the station | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| place_oven.10 | rise to transit height | Q1 Q3 Q6 | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 3.05 | 5.1 |
| place_oven.11 | VGR back home | - | \|pos - target\| <= tol on swivel (B5/B6), plunge (B1/B2), reach (B3/B4) | 0.05 | 0.6 |
| FAULT | a step timed out: outputs off, alarm raised | - | - | - | - |
| ESTOP | safety relay dropped: outputs off (K1/K2 open) | - | - | - | - |

Recovery: `FAULT` -> `ESTOP` when NOT Enable; `FAULT` -> `H:plunge` when Ack AND Enable; `ESTOP` -> `INIT` when Reset (S3) AND Enable.


*Sources: `web/public/hbw_parts_up12.json (control.units.arm)`; `web/public/sil/stf_plc.st#L411-L754`.*

## door: oven door, Ofenschieber and lamp

Module: multi-processing oven. Outputs: Q5 Q6 Q9 Q13. Jobs: bake, to_tt, present.
Function block `FB_Door`, lines 755-854 of the source.

```plc-sfc door
```

| Step | What happens | Outputs on | Done when | Nominal (s) | Watchdog (s) |
|---|---|---|---|---|---|
| INIT | power-up: all outputs off | - | - | - | - |
| H:open | door open | Q13 | I10 | 1.0 | 2.0 |
| H:slider | Ofenschieber in | Q13 Q5 | I6 | 2.0 | 3.5 |
| H:shut | door shut | - | I11 | 1.0 | 2.0 |
| READY | homed, waiting for a job | - | - | - | - |
| bake.01 | Q5: slider retracts into the oven | Q13 Q5 | I6 | 2.0 | 3.5 |
| bake.02 | door shuts - bake (Q9 lamp) | - | I11 | 1.0 | 2.0 |
| bake.03 | baking | Q9 | timer | 2.0 | None |
| bake.04 | door opens | Q13 | I10 | 1.0 | 2.0 |
| bake.05 | slider extends | Q13 Q6 | I7 | 2.0 | 3.5 |
| to_tt.01 | slider retracts | Q13 Q5 | I6 | 2.0 | 3.5 |
| to_tt.02 | door shuts | - | I11 | 1.0 | 2.0 |
| present.01 | Q13: door opens | Q13 | I10 | 1.0 | 2.0 |
| present.02 | Q6: Ofenschieber extends - the VGR lays the workpiece on it (I9 breaks) | Q13 Q6 | I7 | 2.0 | 3.5 |
| FAULT | a step timed out: outputs off, alarm raised | - | - | - | - |
| ESTOP | safety relay dropped: outputs off (K1/K2 open) | - | - | - | - |

Recovery: `FAULT` -> `ESTOP` when NOT Enable; `FAULT` -> `H:open` when Ack AND Enable; `ESTOP` -> `INIT` when Reset (S3) AND Enable.


*Sources: `web/public/hbw_parts_up12.json (control.units.door)`; `web/public/sil/stf_plc.st#L755-L854`.*

## sauger: oven Sauggreifer

Module: multi-processing oven. Outputs: Q7 Q8 Q11 Q12. Jobs: to_tt.
Function block `FB_Sauger`, lines 855-938 of the source.

```plc-sfc sauger
```

| Step | What happens | Outputs on | Done when | Nominal (s) | Watchdog (s) |
|---|---|---|---|---|---|
| INIT | power-up: all outputs off | - | - | - | - |
| H:up | Sauger up, vacuum off | - | I13 | 0.6 | 1.4 |
| H:tt | Sauger to the Drehtisch | Q8 | I5 | 2.0 | 3.5 |
| READY | homed, waiting for a job | - | - | - | - |
| to_tt.01 | Q7: Sauger to the oven (I8) | Q7 | I8 | 2.0 | 3.5 |
| to_tt.02 | Q12: lower onto the workpiece, Q11 vacuum | Q11 Q12 | I12 | 0.6 | 1.4 |
| to_tt.03 | lift | Q11 | I13 | 0.6 | 1.4 |
| to_tt.04 | Q8: Sauger to the Drehtisch (I5) | Q11 Q8 | I5 | 2.0 | 3.5 |
| to_tt.05 | lower, release onto the disc | Q12 | I12 | 0.6 | 1.4 |
| to_tt.06 | lift | - | I13 | 0.6 | 1.4 |
| FAULT | a step timed out: outputs off, alarm raised | - | - | - | - |
| ESTOP | safety relay dropped: outputs off (K1/K2 open) | - | - | - | - |

Recovery: `FAULT` -> `ESTOP` when NOT Enable; `FAULT` -> `H:up` when Ack AND Enable; `ESTOP` -> `INIT` when Reset (S3) AND Enable.


*Sources: `web/public/hbw_parts_up12.json (control.units.sauger)`; `web/public/sil/stf_plc.st#L855-L938`.*

## turntable: Drehtisch, Saege and Auswerfer

Module: multi-processing oven. Outputs: Q1 Q2 Q4 Q14. Jobs: saw_eject.
Function block `FB_Turntable`, lines 939-1023 of the source.

```plc-sfc turntable
```

| Step | What happens | Outputs on | Done when | Nominal (s) | Watchdog (s) |
|---|---|---|---|---|---|
| INIT | power-up: all outputs off | - | - | - | - |
| H:push | Auswerfer home | - | I15 | 0.6 | 1.4 |
| H:turn | Drehtisch to the vacuum position | Q2 | I1 | 1.5 | 2.8 |
| READY | homed, waiting for a job | - | - | - | - |
| saw_eject.01 | Q1: Drehtisch to the Säge (I4) | Q1 | I4 | 1.5 | 2.8 |
| saw_eject.02 | Q4: saw runs | Q4 | timer | 2.0 | None |
| saw_eject.03 | Drehtisch to the belt (I2) | Q1 | I2 | 1.5 | 2.8 |
| saw_eject.04 | Q14: Auswerfer pushes the workpiece onto the belt | Q14 | I14 | 0.6 | 1.4 |
| saw_eject.05 | Auswerfer home | - | I15 | 0.6 | 1.4 |
| saw_eject.06 | I3 passed: Drehtisch home | Q2 | I1 | 1.5 | 2.8 |
| FAULT | a step timed out: outputs off, alarm raised | - | - | - | - |
| ESTOP | safety relay dropped: outputs off (K1/K2 open) | - | - | - | - |

Recovery: `FAULT` -> `ESTOP` when NOT Enable; `FAULT` -> `H:push` when Ack AND Enable; `ESTOP` -> `INIT` when Reset (S3) AND Enable.


*Sources: `web/public/hbw_parts_up12.json (control.units.turntable)`; `web/public/sil/stf_plc.st#L939-L1023`.*

## ovenbelt: oven belt

Module: multi-processing oven. Outputs: Q3. Jobs: ovenbelt.
Function block `FB_Ovenbelt`, lines 1024-1075 of the source.

```plc-sfc ovenbelt
```

| Step | What happens | Outputs on | Done when | Nominal (s) | Watchdog (s) |
|---|---|---|---|---|---|
| INIT | power-up: all outputs off | - | - | - | - |
| READY | homed, waiting for a job | - | - | - | - |
| ovenbelt.01 | Q3 carries the cookie to I3 and onto the sorting inlet | Q3 | I3 | 5.8 | 9.2 |
| FAULT | a step timed out: outputs off, alarm raised | - | - | - | - |
| ESTOP | safety relay dropped: outputs off (K1/K2 open) | - | - | - | - |

Recovery: `FAULT` -> `ESTOP` when NOT Enable; `FAULT` -> `READY` when Ack AND Enable; `ESTOP` -> `INIT` when Reset (S3) AND Enable.


*Sources: `web/public/hbw_parts_up12.json (control.units.ovenbelt)`; `web/public/sil/stf_plc.st#L1024-L1075`.*

## line: sorting line and ejectors

Module: sorting line. Outputs: Q1 Q3 Q4 Q5. Jobs: sort.
Function block `FB_Line`, lines 1076-1166 of the source.

```plc-sfc line
```

| Step | What happens | Outputs on | Done when | Nominal (s) | Watchdog (s) |
|---|---|---|---|---|---|
| INIT | power-up: all outputs off | - | - | - | - |
| READY | homed, waiting for a job | - | - | - | - |
| sort.01 | belt runs the cookie past the colour sensor; A4 sampled until I3 | Q1 | I3 | 4.0 | 6.5 |
| sort.02 | min(A4) over the pass -> flavour class; compared with the record | Q1 | class = record flavour | 0.1 | None |
| sort.03 | belt runs on; I1 pulses counted to the ejector | Q1 | count(I1) = N_eject | 2.4 | 4.1 |
| sort.04 | belt stops; the ejector pushes the cookie into its bay | Q3 | I5 broken (the bay's light barrier) | 0.5 | 1.2 |
| sort.05 | ejector back | - | timer | 0.5 | None |
| FAULT | a step timed out: outputs off, alarm raised | - | - | - | - |
| ESTOP | safety relay dropped: outputs off (K1/K2 open) | - | - | - | - |

Recovery: `FAULT` -> `ESTOP` when NOT Enable; `FAULT` -> `READY` when Ack AND Enable; `ESTOP` -> `INIT` when Reset (S3) AND Enable.


*Sources: `web/public/hbw_parts_up12.json (control.units.line)`; `web/public/sil/stf_plc.st#L1076-L1166`.*

*Generated from the twin's exports by `docs/gen/plc_docs.py`; do not edit.*
