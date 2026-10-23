# From simulation to a real digital twin: research and roadmap

What it takes to turn the STF twin from a precise *simulation* into a *digital twin* of a real
line: one that runs the real PLC program, is fed by the real machine, and is shown to predict it
within a stated error. Written 2026-10-22.

## 1. Where the twin stands

| Layer | Today | Evidence |
|---|---|---|
| Geometry | FreeCAD B-rep from one parameter table; components and devices checked to 0.01 mm against their datasheets | `docs/architecture/devices.md` |
| Physics | Rapier (deterministic build) at a fixed 100 Hz in a worker; DC motor model, belts, sensed switches, homing with a creep pass | `docs/architecture/simulation-engine.md` |
| Electrics | Netlist of 111 parts and 820 pins, relay contacts, safety contactors, `PS_OK` | `docs/architecture/electrics.md` |
| Control | Generated ST and a simulated PLC; proofs (deadlock freedom, swept paths) | `docs/VALIDATION.md` |
| Data | AAS (18 shells), live stream at 30 Hz, PdM with an EKF | `docs/maintenance/pdm-pipeline.md` |

**What it is not yet: validated against a machine.**
- Every timing and position the twin predicts is checked against the twin itself (proofs, ±20 %
  robustness runs), never against a measurement.
- The robustness median (636.1 s) against the nominal 644.5 s is a sim-vs-sim spread, not an
  accuracy. The copilot quoted it as "high temporal accuracy"; it is not one.
- Many plant values are still tagged `[assumed]`, for example the S-motor stall torque and the arm's
  swivel ratio.
- The last validation run had 12 failing checks (`docs/VALIDATION.md`).

The gap is not more modelling. It is closing the loop with the machine.

## 2. What "a real digital twin" means, concretely

ISO 23247 (*Digital twin framework for manufacturing*) splits a manufacturing twin into four layers:
1. the observable manufacturing elements;
2. device communication;
3. the digital-twin core;
4. the user.

Part 5 (the digital thread) was published in June 2026. NIST has published use-case scenarios for
implementing it. ([ISO 23247-1](https://www.iso.org/standard/87425.html?browse=tc),
[NIST use cases](https://www.nist.gov/publications/use-case-scenarios-digital-twin-implementation-based-iso-23247))

Mapped onto STF, a real twin needs:

1. **The same control program** running against the model and against the machine, unchanged.
   This is virtual commissioning.
2. **A plant model whose parameters are measured**, with an error budget.
3. **A live data path** from the machine into the twin, with time stamps.
4. **A continuous comparison**: predicted vs measured, with drift detection and recalibration.
5. **Interoperable descriptions** (AAS, OPC UA) so others can use it. STF is already strong here.

## 3. The upgrades, in order of impact

### U-A. Smooth motion on screen (built today)

**Problem.** The worker steps at 100 Hz and the screen draws at 60, 120 or 144 Hz. Drawn as
published, a part moves one step on some frames and two on others, a ±40 % frame-to-frame jitter
at 60 Hz. However exact the physics is, the motion looks rough.

**Fix.** This is the standard "Fix Your Timestep" remedy: render a little behind the simulation and
blend the two states either side of the render time
([Fiedler](https://gafferongames.com/post/fix_your_timestep/)). It is built in
`web/src/core/SnapshotInterpolator.ts`:
- positions are blended linearly;
- rotations use normalised quaternion lerp along the shorter arc;
- axis positions are blended linearly;
- pins and switches come from the newest state, so a switch is never shown half on;
- the render clock only runs forwards, and holds when the worker stalls.

**Measured** (5 tests, `SnapshotInterpolator.test.ts`):

| Display | Per-frame motion of a part at 100 mm/s |
|---|---|
| 60 Hz | 1.660–1.680 mm (ideal 1.667), was 1–2 mm |
| 120 Hz | 0.825–0.845 mm (ideal 0.833) |
| 144 Hz | 0.685–0.705 mm (ideal 0.694) |

**Cost.** 25 ms of display latency, which is one frame plus one step. The physics itself is
untouched, so determinism and the test results are unchanged.

### U-B. Jerk-limited motion profiles (built 2026-10-22)

**Problem.** `driveStep` (`physicsCore.ts`) is a trapezoid: acceleration switches instantly, so jerk
is unbounded. Real drives and PLCopen's `MC_MoveAbsolute` take a jerk limit:
- Rockwell documents that a zero jerk gives a trapezoid, and a positive jerk an S-curve;
- Kollmorgen gives the constraints relating jerk to acceleration.

([Rockwell MC_MoveAbsolute](https://www.rockwellautomation.com/en-ie/docs/factorytalk-design-workbench/1-00-00/ftdw-help-ditamap/micro800-controller/micro800-instruction-set/motion-move-instructions/mc_moveabsolute.html),
[Kollmorgen MC_MoveLinAbs](https://webhelp.kollmorgen.com/kas4.02/Content/11.TechRefs/Motion-Common/Coordinated-Motion/Motion/MC_MoveLinAbs.htm))

**Fix.** Add a seven-segment S-curve generator with `vmax`, `amax` and `jmax` per driven joint,
where `jmax = 0` keeps today's trapezoid. Use the same parameters the PLC's motion blocks would be
given.

**Acceptance.**
- Jerk is bounded by `jmax` at every step.
- Move time matches the closed-form S-curve time within one step.
- The existing tests are unchanged when `jmax = 0`.

**Note.** The fischertechnik motors are on/off DC motors driven through relays, so they have no
profile at all: their motion comes from the DC motor model (`motors.ts`). The S-curve applies to
the upgraded line's servo axes and to the kinematic joints.

**Built.** `web/src/workers/scurve.ts` plans each move rest to rest in closed form (the seven
segments, peak velocity found by bisection when the distance has no room for a cruise) and samples
it exactly; `JointDrive.jmax` turns it on, and `jmax` 0 or absent keeps the trapezoid. A target
given during an S-curve move is taken up when that move stops (PLCopen BufferMode "Buffered"),
so the jerk bound holds through retargets. `scurve.test.ts` checks the acceptance: jerk, acceleration
and speed within their limits at every 10 ms step for long, medium and short moves; the move time
equal to the closed form (`D/V + V/A + A/J` with a cruise, `4·(D/2J)^(1/3)` with neither limit
reached) and arrival within one step of it; the existing trapezoid tests unchanged. The sorting
pushers stay at `jmax` 0: a pneumatic cylinder has no programmed profile.

**Also fixed (fast-forward).** At 2×/4×/8× the factory twin's cookies and axes jumped. Three causes,
each now covered by a test in `CellCoordinator.test.ts` that fails without its fix:
1. The clock was `elapsed × speed`, so changing speed moved the twin's time (1×→4× at 60 s jumped it to
   240 s). The coordinator now keeps its own clock, advanced by `frame × rate`; long frames are cut
   into FSM steps of at most 50 ms, so every transition fires in order.
2. The inspection verdict arrives in wall time; at 8× it could land after the cookie had been
   ejected, and the cookie was switched onto the reject path mid-belt. The cookie is now committed to
   its path at the end of the colour reading, and the belt holds there until the verdict is in
   (up to 4 s of wall time, then it goes on un-inspected).
3. With two cookies pipelined, a crane or VGR segment started from its own script's first pose,
   not from where the resource had stopped (up to 545 mm away). Each segment now begins with a
   repositioning move when needed (crane: fork in, up to transit, across, down; VGR: retract, rise
   to transit, swing, descend, extend). Worst per-frame speed through 1→8→2→4→8→1× switches went
   from 39,900 mm/s to 85.6 mm/s, the scripted motor speed at its easing peak.

### U-C. Drive-train fidelity at 1 kHz (about 1 week)

**Problem.** The motor model runs inside the 10 ms physics step, and the PLC scans every 10 ms. That
is why the arm lands within ±2 encoder counts rather than one: the stop decision is made up to a
whole step late.

A real controller sees the encoder edge and the relay drops within about 1 ms.

**Fix.** Sub-step the drive train (motor electrical and mechanical, gear, encoder) at 1 kHz inside
each Rapier step. Rapier keeps the contacts at 100 Hz; motors and encoders are cheap ODEs. Then:
- time-stamp encoder edges;
- let the PLC model run at its real scan time (RevPi: configurable; typically 5–10 ms);
- add relay drop-out time (a few ms, from the relay datasheet).

Friction should be Coulomb plus viscous with a smooth (tanh) transition, as identified for brushed
DC motors in
[IJEECS](https://ijeecs.iaescore.com/index.php/IJEECS/article/view/45138).

**Acceptance.**
- The ±2-count spread is explained component by component: scan time, relay delay, coast.
- The spread shrinks when the scan time is shortened in the model, the way it would on the bench.

### U-D. Measured parameters instead of `[assumed]` (needs one module of hardware)

This is the single largest gain in credibility.

**Identify each motor from step responses.** Apply a voltage step, log position and current, and
fit:
- the torque constant;
- the back-EMF constant;
- inertia;
- Coulomb and viscous friction.

Peer-reviewed methods exist for exactly this:
- step and ramp torque responses ([Cardona Soto et al., *Sensors* 2025](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12788085/));
- gradient-based fitting of seven geared-PMDC parameters from current and speed steps ([IEEE Access 2023](https://doaj.org/article/769dc426bf6e4adbac47c397cee60d42));
- a lab procedure ([Utah ECE 5670](https://my.ece.utah.edu/~bodson/5670/Labs/Lab2.pdf)).

**Then propagate the uncertainty.** The project already tags every value with its source, so a
Monte-Carlo run can sample each `[assumed]` value over its plausible range and report which ones
move the cycle time most. Measure those first.

**Acceptance.** Each motor's simulated step response is within a stated RMSE of the measured one
(target: position RMSE under 2 % of travel). The tag changes from `assumed` to `measured`, with the
log file kept in `docs/`.

### U-E. The real PLC program in the loop (software-in-the-loop, then hardware-in-the-loop)

**Software-in-the-loop, with no hardware.** Run an IEC 61131-3 runtime against `physicsCore`
(headless, in Node) over Modbus TCP, in lockstep: each PLC scan is one exchange at a fixed virtual
time, so runs stay reproducible.
- **OpenPLC** runs a Modbus server on port 502 and can attach Modbus TCP slave devices
  ([Autonomy docs](https://autonomylogic.com/?p=814)).
- **CODESYS** is the industrial option.
- The generated ST and the `electrical.json` I/O table are the contract between the two.

**Hardware-in-the-loop.** Put the real RevPi on the PC's plant model:
- run the plant on a deterministic loop at 1 kHz, on a PC or a second Pi with a PREEMPT_RT kernel;
- connect them over Modbus TCP or, better, real I/O through a second DIO;
- budget the latency and measure it.

**Industrial references for the same pattern:**
- **Beckhoff TE1421** packages a TwinCAT runtime as an FMU (FMI 2.0 and 3.0), so the real PLC
  project co-simulates in any FMI tool
  ([Beckhoff TE1421](https://www.beckhoff.com/te1421)).
- **Siemens** couples NX MCD (mechanics), S7-PLCSIM Advanced (virtual controller) and SIMIT
  (drives, sensors, safety) to run the original PLC code
  ([Siemens](https://xcelerator.siemens.com/global/en/all-offerings/solutions/v/virtual-commissioning-for-machine-builders.html)).

**Acceptance.** The same compiled PLC program completes a 12-cookie order in the twin and on the
machine, with:
- the cycle time within ±3 %;
- every PLC-visible event (switch, light barrier) in the same order;
- each event's timing within one scan.

### U-F. Live twin, running in shadow mode

**Data path.** Machine → OPC UA (or MQTT Sparkplug B) → the API → the twin. Time-stamp at the
source, never on arrival.

For controller-to-controller links, OPC UA FX released its first specifications:
- Parts 80, 81, 82 and 84;
- PubSub with UAFX Connections for controller-to-controller exchange.

([OPC Foundation](https://opcconnect.opcfoundation.org/?p=3956))

**Shadow mode.** The twin runs alongside the machine on the same commands and compares:
- per-axis position residuals;
- event-timing residuals;
- current residuals.

The PdM pipeline already has an EKF; extend it to state-estimate the axes and flag residuals beyond
3σ. A residual that keeps drifting means one of two things, and the twin should say which:
- the machine is wearing, so the residual is a maintenance signal;
- the model is wrong, so the residual is a recalibration trigger.

### U-G. Physics engine: keep Rapier, add a reference engine for validation

**Candidates:**

| Engine | Strength | Fit for STF |
|---|---|---|
| **Rapier** (current) | Deterministic cross-platform build; runs in the browser (WASM); multibody joints with IK ([changelog](https://github.com/dimforge/rapier/blob/master/CHANGELOG.md)) | Right for the browser twin and reproducible tests |
| **MuJoCo / MJWarp** | Accurate articulated dynamics, soft contacts; GPU batch (MJWarp, beta; no autodiff in MJX-Warp) ([MJX docs](https://mujoco.readthedocs.io/en/stable/mjx.html)) | Offline cross-check of the arm and crane dynamics; parameter fitting over many runs |
| **Newton** | GPU, built on NVIDIA Warp and OpenUSD, multiple solvers, MuJoCo-compatible; Linux Foundation project since Sept 2025, still maturing ([Linux Foundation](https://www.linuxfoundation.org/press/linux-foundation-announces-contribution-of-newton-by-disney-research-google-deepmind-and-nvidia-to-accelerate-open-robot-learning?hsLang=en)) | Watch; too new to anchor a validation claim on |
| **Project Chrono** | Multiphysics: rigid and flexible bodies, BSD-3, C++ with Python ([projectchrono.org](https://projectchrono.org/about)) | If belts, cables or compliance ever matter |
| **PhysX / Isaac Sim** | Industrial robotics, sensors | Heavy; not needed for a tabletop line |

**Recommendation.** Do not replace Rapier. The accuracy limit today is the parameters and the
10 ms control timing, not the contact solver.
- Put the drive train on its own 1 kHz ODE (U-C).
- Export the plant as an **FMU (FMI 3.0)** so it can be coupled with a PLC runtime or another tool.
- Use MuJoCo offline as an independent second model of the arm. Two engines agreeing, and both
  matching a measurement, is a much stronger claim than one engine matching itself.

## 4. The roadmap

| Phase | Work | Hardware | Effort | Result you can show |
|---|---|---|---|---|
| 0 | Interpolated rendering | none | **done** | Smooth motion at any display rate |
| 1 | S-curve profiles; 1 kHz drive sub-steps; relay and scan delays | none | 1–2 weeks | The ±2-count spread explained term by term |
| 2 | Software-in-the-loop: OpenPLC or CODESYS ↔ headless `physicsCore` over Modbus TCP, lockstep | none | 1–2 weeks | The real IEC 61131-3 runtime runs the twin |
| 3 | One module on the bench: warehouse with RevPi Connect, DIO, 24 V; motor identification | ~€600–900 | 2–4 weeks | Measured parameters; predicted-vs-measured plots |
| 4 | Hardware-in-the-loop and shadow mode: the real PLC on the twin, then the twin beside the machine | phase 3 | 2–3 weeks | The validation table: cycle time, event order, residuals |
| 5 | Plant as an FMU; OPC UA server; MuJoCo cross-check | none | 2 weeks | Interoperability with industrial tools |

**One rule for the whole roadmap:** no number is called "accurate" until it has been compared with
a measurement. Report the comparison, error and all.

## 5. Sources

- [ISO 23247-1](https://www.iso.org/standard/87425.html?browse=tc), [NIST use-case scenarios](https://www.nist.gov/publications/use-case-scenarios-digital-twin-implementation-based-iso-23247)
- [Fiedler, "Fix Your Timestep!"](https://gafferongames.com/post/fix_your_timestep/)
- [Rockwell MC_MoveAbsolute](https://www.rockwellautomation.com/en-ie/docs/factorytalk-design-workbench/1-00-00/ftdw-help-ditamap/micro800-controller/micro800-instruction-set/motion-move-instructions/mc_moveabsolute.html), [Kollmorgen MC_MoveLinAbs](https://webhelp.kollmorgen.com/kas4.02/Content/11.TechRefs/Motion-Common/Coordinated-Motion/Motion/MC_MoveLinAbs.htm)
- [Cardona Soto et al., *Sensors* 2025](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12788085/), [IEEE Access 2023](https://doaj.org/article/769dc426bf6e4adbac47c397cee60d42), [IJEECS](https://ijeecs.iaescore.com/index.php/IJEECS/article/view/45138), [Utah ECE 5670 lab](https://my.ece.utah.edu/~bodson/5670/Labs/Lab2.pdf)
- [OpenPLC (Autonomy)](https://autonomylogic.com/?p=814), [Beckhoff TE1421](https://www.beckhoff.com/te1421), [Siemens virtual commissioning](https://xcelerator.siemens.com/global/en/all-offerings/solutions/v/virtual-commissioning-for-machine-builders.html)
- [OPC UA FX release](https://opcconnect.opcfoundation.org/?p=3956)
- [Rapier changelog](https://github.com/dimforge/rapier/blob/master/CHANGELOG.md), [MuJoCo MJX](https://mujoco.readthedocs.io/en/stable/mjx.html), [Newton (Linux Foundation)](https://www.linuxfoundation.org/press/linux-foundation-announces-contribution-of-newton-by-disney-research-google-deepmind-and-nvidia-to-accelerate-open-robot-learning?hsLang=en), [Project Chrono](https://projectchrono.org/about)
