# STF-2 digital twin - simulation models

The plant the PLC talks to. Each model is either **reused** from the proven code (named), or **new** (marked
NEW with its proof). The plant has no hidden state of its own: everything it knows comes from `line_model.L` and
the PLC outputs.

## 1. Execution model

```
virtual time t, tick = 10 ms (the PLC task)

loop:
  1. PLC scan        inputs image (181 values, by tag)  ->  MatIEC program  ->  outputs image
  2. safety logic    SF1-SF6 from safety_functions.csv  ->  K1/K2, K3/K4, KHn, Q19 states (overrides outputs)
  3. plant step      actuators (outputs) -> motion, process, product state, at dt = 10 ms
                     (the oven node integrates at 0.5 s sub-steps, the bake model per cookie event)
  4. sensors         plant state -> inputs image for the next scan (with each sensor's delay / filter)
  5. publish         every 50 ms of virtual time: frame on the WebSocket, OPC UA values, Sparkplug NDATA
```

- **Lockstep and deterministic.** One seed fixes every random draw: grip success, AMR delay, sensor noise. Two runs with the same seed and commit are bit-identical, so a failed run can be replayed exactly.
- **Speed.** The plant runs faster than real time (target ≥ 20× for the logic-only run). The viewer may pace it to 1×.

## 2. Actuators

| Actuator (tags) | Model | Parameters (source) |
|---|---|---|
| Steppers on EL7047 (`STEP`, 18: master Q1, band Q40, rolls Q41, deltas, shuttles, carriers) | position-controlled axis: `SIM_MC` holds the position, velocity and enable state. `MC_MoveVelocity` / `MC_GearIn` integrate with the axis acceleration limit; `MC_Stop` decelerates; no enable → holds still | `L["V"]` 20 mm/s chain, `band_v` 2.29 mm/s, gear ratios from `FB_Band`; the axis limits come from the motor sizing rows of `line_model.check` |
| Pneumatic cylinders ISO 6432 (`DO` coil + `DI` reeds S1/S2) | first-order stroke: valve delay + stroke time from the sizing check; rod length re-shaped per tick as in the timeline; no air (Q19 exhausted) → the rod stops | stroke, bore and force from `line_model` sizing; `P_SUPPLY` 0.6 MPa |
| Vacuum ejectors (cups) | vacuum level rises with `T_GRAB` 0.8 s; grip success with probability `PICK_OK` 0.995 per pick, or from MuJoCo (DT-6) | `L` |
| Oven element SSRs (9 × `qE…`) | conduct when the output is 1 (2 s time-proportioning made by the PLC); element power from `oven_power()` × the supply factor | `oven/control.json` |
| Zone contactors KH1-3 | open when the zone STB trips (SF4) or K3/K4 drop; manual STB reset | `safety_functions.csv` |
| Fans QF1-3, cooling QC1-3, exhaust | on/off; impeller coast-down `FAN_RUNDOWN` 2 s | `L` |
| Sealers (DC SSR + TC) | lumped heater node like an oven zone, own STB | `hardware.LOADS["sealer_head"]` |
| Airlock doors, carriers, AMR | timed moves: `DOOR_T` 1.5 s, `SHUTTLE_V` 100 mm/s, AMR swap `AMR_EXCH` 20 s | `L`, `line_sim.py` |

## 3. Process models

### 3.1 Motion (reused: `motion.py`, `line_model`)

The chain, the pucks, the band rows, the depositor wire and the delta arms are **kinematic**:
- the same closed-form functions that wrote `timeline.json` (`band_pose`, `delta_ik`, the chain arc length);
- driven by the live axis positions instead of the recorded clock;
- proof of DT-3: fed the recorded axis trajectories, the live plant reproduces `timeline.json` at every frame within 0.05 mm (the `validate_motion.py` tolerance).

### 3.2 Oven (reused: `oven.py`, `oven_ctrl.py`)

| Part | Model |
|---|---|
| Zone air (Z1-Z3) | `oven_ctrl.Plant`: one lumped node per zone. Inputs: heat capacity, wall, mouth and band losses, the product + vapour load × band content, zone-to-zone exchange G. |
| Thermocouples TC1-3 | first-order lag `TC_TAU` 15 s → `tcTCn` in 0.1 °C |
| Real oven ≠ model | `oven_ctrl.Mismatch(cf, lb, lp, pf, tf)`: the twin can run an oven that differs from the PLC's model, so the learning feed-forward is exercised |
| Phase currents BC1-3 | sum of the conducting elements' currents per phase (+ fans), √(P ratio) for voltage, transducer lag `t_resp` 0.3 s and accuracy 1 % of 20 A → `aiBCn` |
| Each cookie | when its row leaves the oven, `oven.simulate` runs on the zone temperatures it actually saw (the zone history over its residence) → core temperature, moisture, colour index → its colour in the 3D view and its bake-log verdict |
| STB | own sensor lag; trips at 250 °C → KHn opens (SF4) |

### 3.3 Product flow (NEW, from `line_sim.py` rules)

Each cookie is an entity with a state machine:

```
dough slug (row k, flavour from row) -> on band -> zone 1/2/3 (temperature history) -> cooling hood
  -> pick window -> [grip ok] in puck (NFC write: id, flavour, bake log)   | [grip miss] catch tray (counted)
  -> QC camera (colour) -> [ok] lane -> tray pocket -> sealed pack -> cassette -> AMR
                         | [reject] kicker -> reject drawer
```

Rules come from `line_sim.py`: the band never stops; a missed cookie is a counted loss; a full cassette is swapped by the AMR
through the airlock. Stocks (dough 15 kg, topping 0.8 kg per flavour, trays, film) deplete per cookie and are refilled by AMR tasks.
Proof: a 1 h nominal run gives `sim_results.json["nominal_1h"]` within ±1 %. The other scenarios in that file (deltas down,
AMR fleet down 15/45 min, one AMR per shift) must reproduce their claims.

### 3.4 Sensors (NEW: synthesized from plant state)

| Sensor | Synthesis |
|---|---|
| Reed switches S1/S2 | rod position within 2 mm of its end |
| Diffuse / through-beam (I1, I9, …) | a product or puck AABB crosses the beam line; 3 ms filter (EL1809) |
| Timestamped latches (DITS) | exact virtual-time crossing, distributed-clock resolution |
| Master encoder B1 | chain position × 1024 ppr / wheel circumference, UDINT wrap |
| ToF levels (IO-Link) | hopper fill height from the stock mass and density (`DOUGH_RHO`, `TOP_RHO`) |
| NFC heads | read and write the cookie's record (the bake log) when its puck passes |
| Vacuum level (IO-Link) | from the ejector model; low on a failed grip |
| Pyrometer IR1 | surface temperature of the cookie under it (from its bake record) |
| Colour sensor R/G/B | the cookie's colour (oven colour index → `cookie_hex`) + noise |
| Cameras (GigE) | DT-7: Blender renders of the cookie in its pose; until then the QC verdict comes from the colour index (`AI_LATENCY` 0.5 s) |
| Door switches, E-stops, light curtains (SI) | operator actions from the dashboard (open door, press E-stop) |

## 4. The PLC in the loop (DT-4)

1. **Port.**
   - A converter turns the generated TwinCAT ST into portable IEC 61131-3 (the mapping table in [DATA_CONTRACT.md §2.5](DATA_CONTRACT.md)).
   - It is generated, like everything else: `plc_io.py` gets a `target="iec"` switch, rather than a hand-edited copy.
   - The FB bodies stay identical.
2. **Compile.**
   - MatIEC `iec2c` → C. Then clang → a native library (for the plant service) and → WebAssembly (for the browser twin, as on `main`).
3. **Couple.**
   - The I/O image is laid out from `io_list.csv`; the runtime glue copies it in and out once per scan.
   - Axes (`AXIS_REF`) are shared structs that the `SIM_MC` FBs and the plant both read.
4. **Safety.**
   - SF1-SF6 run as a separate module before the standard task, from `safety/safety_functions.csv`.
   - The standard program can only request; the safety module grants. This is the TwinSAFE split, kept in software.

## 5. Contact physics (DT-6)

- An MJCF scene is generated from the primitive parts of the handling stations: delta C's cups, the band end, puck nests, the kicker, the reject bin and a cassette.
- Material parameters: dough-on-steel friction μ, restitution, cookie mass `COOKIE_M` 0.012 kg (all `[assumed]` until measured).
- **Used for:**
  - grip success vs band speed and vacuum time, replacing the fixed `PICK_OK`;
  - seat success in the nest;
  - reject landing;
  - the cassette packing fraction (`PACKING` 0.5 `[assumed]`).
- **Not used for:** the prescribed motions (§3.1).
- **Fed back:** the measured rates become distributions the live plant samples, and the line simulation's claims are re-run with them.

## 6. Fault catalogue

Each fault can be injected from the dashboard or a scenario file. The **expected** column is what the existing proofs
predict, and a twin run must reproduce it. Rows marked NEW need a proof added to the model first, because the twin must not
invent behaviour.

| # | Fault | Expected response | Source |
|---|---|---|---|
| F1 | One oven element open (any of 9) | seen ≤ 0.5 s, named ≤ 6.5 s; Z1 rides through (≤ 1.4 K); Z2/Z3 hold the depositor; 90-128 cookies flagged by their bake log | `oven_ctrl` S4 |
| F2 | Z1 SSRs stuck on | STB trips ~153 s later, air peaks 252 °C (< 300 °C), KH1 drops | `oven_ctrl` S5, SF4 |
| F3 | Depositor stop 10 min + restart | zones within 0.6 K | `oven_ctrl` S3 |
| F4 | Real oven 20 % off the model | after warm-up + 1 h learning, within 0.1 K; first hour flagged | `oven_ctrl` S6 |
| F5 | Cold start | set point within 18.3 min, overshoot ≤ 1.6 K | `oven_ctrl` S1 |
| F6 | E-stop | SF1: SS1 then K1/K2 off, K3/K4 off, Q19 exhausts; the oven content over-bakes (counted) | `safety_functions.csv` |
| F7 | Guard door opened | SF2: SS1, unlock only after 2.5 s standstill (fan rundown 2 s) | `safety.py` G8 |
| F8 | Delta C misses a grip | cookie to the catch tray, counted; band never stops | `line_sim.py` |
| F9 | Delta A down 10 min / both down | the other delta carries / recirculation counted | `sim_results.json` |
| F10 | AMR fleet down 15 / 45 min | 93 % for 15 min, 158 cookies recirculated; 45 min claim per file | `sim_results.json` |
| F11 | Dough hopper empty | depositor stops, band bakes out, no stop of the line | `line_sim.py` |
| F12 | Airlock door out of sequence | SF6: SF1 response without heaters | `safety_functions.csv` |
| F13 | Thermocouple open circuit | NEW: EL3314 reports a wire break → the zone goes to a safe duty, the depositor holds, the STB still protects | to add to `oven_ctrl` |
| F14 | Current transducer failed (reads 0) | NEW: every element on that phase looks broken → plausibility check (all candidates at once) → "sensor fault", not "element fault" | to add to `oven_ctrl` |
| F15 | Supply voltage −10 % | power −19 %; learning absorbs it (S6 covers ±10 % power) | `oven_ctrl` S6 |

## 7. Fidelity: what the twin is, and is not

- **Exact by construction:** geometry, kinematics, I/O, PLC logic, wiring, timing of the takt.
- **Model-accurate, with unmeasured inputs:** oven thermal and bake, cooling, stock depletion, grip and seat rates. Every such input is in `VERIFICATION_PLAN.md`. 18 of them break a proof within ±20 % and are to be measured first.
- **Not modelled:** dough rheology, crumbs and flour dust, EMC, network jitter beyond EtherCAT's distributed clock, wear.

The dashboard shows a badge on any value that rests on an `[assumed]` input.
