# STF-2 safety concept (draft, for Upgrade PA-1 "physical AI")

Status: **engineering draft, not a certified assessment.** The required performance levels below come
from the ISO 13849-1 risk graph as I read the hazards; a qualified person must confirm them
before the machine runs with anyone near it. The hardware is built (Upgrade S-1, see below); the
reach audit still has open findings.

## Why now

PA-1 lets learned models command real axes: drop lead, kick/pass, grip retry, and later pick
trajectories. A learned model can be wrong in ways nobody tested, so it must **never be the thing
that keeps a person safe.** Safety is a separate, non-learned layer that the model cannot write to.

## Hazards (ISO 12100), by module

| Module | Hazard | Source | Exposure |
|---|---|---|---|
| M6 pick | impact / crushing | two delta robots, 0.5 m/s, NEMA 17 + strain-wave | reaching into the cell, clearing a jam |
| M4 stamp | crushing / burn | carriage on Tr8x4, D16 cylinder, heated die | reaching under the portal |
| M5 QC | impact | kicker D10x100 across the chain | hand at the guide gap |
| M1 loop | drawing-in | chain entering the bends / drive unit | hand on the chain |
| M3 oven | burn | 3 x 300 W IR bars, product ~180 C | reaching into the tunnel |
| M7 pack | crushing / burn | sealer D25 (188 N), heated heads, stacker lifts | clearing a tray |
| M7 shuttle | crushing | cassette shuttle, 7 kg moving | AMR port / manual swap |
| M8 | electric / stored energy | 230 V heaters, 48 V motors, 6 bar air | maintenance |

## Required safety functions

| # | Function | PLr (risk graph) | Architecture |
|---|---|---|---|
| SF1 | Emergency stop: all motion + heaters off | d | Cat. 3: 2-channel E-stop -> TwinSAFE logic -> two contactors in series on the 48 V motor supply (the EL7047 has no STO) + dump valve de-energised + heater SSR supply off |
| SF2 | Guard interlock with locking on the pick cell and the stamp | d | guard (polycarbonate on 30x30 profile, the U2 pattern of the 536634 twin) + locking switch; unlock only after standstill (EL7047 encoder = 0 for 1 s, monitored in TwinSAFE) |
| SF3 | Safe exhaust of all pneumatics on SF1 / SF2 | c | FRL soft-start / dump valve Q19, spring return, monitored |
| SF4 | Independent over-temperature cutout on every heater | c | hardwired safety temperature limiter per zone, NOT the PID and NOT a learned bake model |
| SF5 | Chain drawing-in protection at the bends and the drive unit | c | fixed guards (tool to remove) |
| SF6 | Safe AMR docking | c | AMR in the port area only with the port's shuttle at standstill (interlock signal) |

## Rules for learned models (PA-1 and later)

1. A model **cannot write a safety output.** Safety runs on TwinSAFE; the models run in standard tasks.
2. Every model output passes **FB_SafeEnvelope**: position windows, speed and force limits from
   line_model, clamped not scaled. The envelope is code, not data, and is covered by tests.
3. Learned motion only **inside a closed, locked guard** (SF2). With the guard open, only jog
   at reduced speed with enabling, and never by a model.
4. New models run in **shadow mode first**: they predict, the fixed program acts, and the two are
   logged side by side (FB_DataTag). A model acts only after its shadow record meets an agreed error bound.
5. Every model is **versioned** with its training-data hash, and rollback is one parameter.

## Hardware (Upgrade S-1, BUILT 2026-09-29 - `L["SAFE1"]`, proven by `safety.py`)

What changed against the draft above, and why:

- **Perimeter guard instead of "pick cell + stamp".** The chain loop runs through every module, so a
  partial guard always has chain openings next to a hazard (ISO 13857 wants 850 mm behind any opening
  > 120 mm). The whole deck is enclosed: 2020 frame, 4 mm PC outside it, PC roof on 2040 rails, top at
  900 mm. The front wall steps from 16 mm (feeder) to 60 mm, and the back wall sits 60 mm in, so the
  E-stop heads stay on the deck.
- **3 doors with guard locking**: S20 front (oven exit / stamp / QC), S21 back (pick cell), S22 back
  (pack). Power-to-unlock RFID switches; unlock only after SS1 plus 1 s standstill.
- **3 E-stops** (S10 front, S11 back, S12 back-right) and a reset S13, all panel-mounted.
- **AMR ports**:
  - *boxes* (left) and *out* (right) are **airlocks** (S-1b, below). The light curtains are gone.
  - *raw*: a pour strip over the front of the hoppers. Fixed lids behind it mean it opens only into the
    hopper interiors, where the singulator discs are low-energy (0.5 Nm, about 6 N).
- **TwinSAFE**: EL6910 + 10 x EL1904 + 4 x EL2904, on their own EK1100 bus segment. K1+K2 in series
  on the 48 V supply, K3+K4 in series on the heater feed, each pair with mirror-contact EDM. The
  dump valve Q19 is now a monitored safe output.
- **SF4**: a duplex thermocouple per heated zone (7). One element goes to the PID, the other to a
  hardwired STL whose relay contact sits in that zone's load path.
- **Cabinet**: grown to 980 x 720 x 210 (the TwinSAFE rail, 6 contactors, 7 STLs). The 24 V logic
  supply is now an SDR-480-24.

## Airlocks (S-1b, built) - replace the curtain-protected side ports

The first audit showed the side ports were open 44-64 mm from the chain bends and the shuttles, which
no curtain can protect. Each side port now opens only into a closed chamber:

- **Boxes airlock (left)**: a chamber over the three tray magazines at z 616-896 (2020 corners, PC walls, a
  6 mm floor with a cutout over each magazine). Under each cutout is a **trapdoor unit**: bi-parting drop
  flaps on spring-return rotary actuators, 0.5 Nm, which is low energy.
  - The outer sliding door S30 unlocks only with every trapdoor closed and the Y1 zone exhausted.
  - The trapdoors drop a stack only with S30 locked.
  - The lanes and tray forks keep running throughout.
- **Out airlock (right)**: the old standby bay **is** the chamber. The fixed parts that separate it:
  - an inner sliding door S32 that parks behind the lanes;
  - a fixed 3030 header that the lane beams end on, with the MGN rails passing under it;
  - PC walls front and back.

  Each lane now has a one-cassette **carrier**, which also fixes the old "one bar cannot swap two
  cassettes" problem. The exchange sequence:
  1. The carrier moves the full cassette into the chamber, and S32 closes and locks.
  2. K5 (the shuttles) goes off, and the outer door S31 opens.
  3. The AMR swaps the full cassette for an empty one, and S31 closes.
  4. S32 opens, and the carrier brings the empty cassette back.

  The exchange takes 30 s. The stackers and lanes stay running behind the inner door.

**Cost, stated honestly**: there is no longer a standby cassette. Three measures keep it from costing
production:
- The stacker platform holds one sealed pack (36 s, which is more than the 30 s exchange).
- The AMR is called 75 s before the lift counter says full.
- The three lanes run a third of a fill apart, so exchanges never coincide.

One AMR is now 69 % utilised (limit 70 %). In the simulation:
- nominal: 95 % efficiency, no blocked lanes;
- one AMR for 8 h: 93 %;
- fleet down for 15 min: 94 % (previously no loss).

A late robot blocks only that lane; the loop never stops.

**Reach audit now**: 46/46 checks met. The chamber boundaries' largest gap is a 10 mm slot above the
inner door, more than 500 mm from any running hazard (ISO 13857 needs 80 mm).

## Under the deck and the reject drawer (S-1c, built)

- **Lift guard.** A closed 1.5 mm sheet-steel box, flanged to the deck, encloses the three stacker lift
  cylinders under the deck. Their rods leave it only through the deck. Proof G10: every moving part
  below the deck is inside it.
- **Reject drawer.** Three changes:
  - The bin moved 30 mm back. The old deck hole reached 31 mm beyond the bin, so it was open from
    under the table even with the drawer in. The bin now covers the whole 50 mm hole (proof G11).
  - A spring-closed shutter under the hole is held open by a push pin on the drawer. It shuts within
    the first 20 mm of pulling. The drawer switch S34 monitors the drawer.
  - With the drawer in, the 10 mm gap between the bin top and the deck is 110 mm from the chain along
    the only path (to the hole, up the funnel). ISO 13857 needs 80 mm.

**Reach audit: 55/55 checks met, no findings.**

## PL estimate (G12, ISO 13849-1 simplified method)

`safety.py` models every function as input -> TwinSAFE logic -> output:
- **Electromechanical parts:** MTTFd = B10d / (0.1 n_op), with the operations per year taken from the
  line itself (e.g. the out-zone contactor K5 switches at every cassette exchange). The category and
  diagnostic coverage (DCavg) follow the architecture. The PL is read from Figure 5, taking the lower
  PL wherever the bar straddles two.
- **Certified devices** (RFID switches, TwinSAFE, STB) carry their own PL.
- **Combination:** Table 11.

Result: SF1 d, SF2 d, SF3 c, SF4 d, SF6 c (both airlocks). Every function meets its PLr (d / d / c / c / c).

This caught one design error: plain position switches on the trapdoors cannot reach PLr c. They are
now 2-channel safety sensors (PL d). Four planted weaknesses (worn contactors, a plain trapdoor switch,
a cheap E-stop, a PL c lock) are all caught.

It is an **estimate on typical data**. The real verification is SISTEMA with the ordered parts' B10d /
PFHd; `VERIFICATION_PLAN.md` lists every value to replace.

## Brush strip (reject bin)

A 3 mm PP brush on the bin rim (split where the shutter crosses the back edge) closes the bin-top
slot to about 4 mm [assumed]. ISO 13857 then needs 2 mm; the path distance is 110 mm.

## Open (engineering, not geometry)

1. **Door force.** The airlock doors are force-limited to 50 N [assumed]. This must be verified on the
   bought drive (ISO 14120), or a safety edge must be added.
2. **Reject shutter coupling.** The push-pin coupling needs a prototype check: it must shut before
   the hole is exposed.
3. **Measurements.** Every [assumed] / [typ] value is in `VERIFICATION_PLAN.md`, ranked by how close
   its proof is to breaking.

## Still open

- ISO 13849-1 PL verification (B10d / PFHd of the bought parts, SISTEMA). PLr values need
  confirmation by a qualified person.
- Standstill for guard unlocking comes from the standard EL7047 encoders. For PLd this needs either
  safe standstill monitoring (e.g. EL5021-0090 / safe motion) or a fixed time delay justified by the
  measured run-down. The build uses SS1 + 1 s, which is a design value to be validated.
- Every [assumed] stop time and force in `safety.py` (t_mech, F_LOW = 50 N) must be measured.
- TwinSAFE project (from `safety/safety_functions.csv`) and FB_SafetyIf are not compiled.
