# Industrial gap analysis & continuous-production roadmap

Plan-mode report, 2026-10-26. No code changed. Question: can the cookie production be made
**continuous** instead of the single robotic arm shuffling carriers place-to-place, and what
would close the gap between this twin and an industrial one?

Sources: `docs/HARDWARE_MODEL.md` (the physical reference), `docs/FACTORY_GROUND_TRUTH.md`,
`docs/UPGRADE_PLAN.md` (Upgrades 1–19 BUILT), the live kernel's flow (HBW → belt → VGR →
oven → conveyor/sort → HBW), and the operating invariants already in the sim (9 bays A1–C3,
the 12-cookie conservation rule, shortest-path pick-and-place, order queue cap of 12).

---

## 1. Where the current cell sits

The twin faithfully models the fischertechnik Factory Simulation 24V:

| Module | Simulated today | Role in the flow |
|---|---|---|
| HBW (3×3 rack, stacker crane X/Z/fork + front belt) | yes | raw/finished storage, staging |
| VGR (turntable + vertical + reach + suction) | yes | **every** pick-and-place in the cell |
| Oven (kiln station at swivel +55°) | yes | **batch** bake, one carrier at a time |
| Delivery/sorting + colour detection | yes | finished-goods handling, QC |
| Energy, vision QC, PLC (SIL), AAS/OPC UA/MQTT, copilot | yes | the I4.0 wrapper |

The architecture is a **serial loop with one flexible handler**:

```
HBW bay → crane → HBW belt → VGR picks → VGR loads OVEN → bake (dwell)
→ VGR unloads → conveyor/sort (+vision) → crane → HBW bay
```

This is a classic **job-shop/batch cell**: one general-purpose robot does all transfer,
one batch oven does all processing. It is an excellent *training* architecture (it exercises
planning, kinematics, safety invariants, scheduling) but it has three structural ceilings:

1. **The arm is the bottleneck and the coupling point.** Every cookie crosses the arm 4–6
   times (raw stage, oven load, oven unload, sort, store, sometimes re-handle). Arm busy-time
   per cookie ≈ 4–6 × (pick + place + transit). Nothing else in the cell can move while the
   arm is on a move, and the oven sits idle between batches.
2. **No decoupling buffers.** There is no place for WIP to wait *between* stations except the
   9 rack bays. Any station slowdown (a slow bake, a vision re-check) stalls the whole loop.
   Industrial lines decouple stations with accumulation conveyors so each station runs at its
   own best rate.
3. **Batch oven.** A kiln processes one carrier per dwell. Industrial biscuit production is a
   *continuous* process: forming → tunnel oven → cooling → packing, with product flowing at a
   steady pitch.

## 2. What "industrial" actually looks like (the reference)

An industrial biscuit/cookie line (the gap target):

```
mixer → rotary moulder/stencil former → **tunnel oven** (zoned, steel/mesh band,
1–5 min transit) → ambient **cooling conveyor** (2× bake length) → stacker →
checkweigher / metal detector / vision → flow-wrapper → case packer
```

Properties the twin lacks today:

- **Takt/pitch flow**: one cookie per fixed pitch time *p*; throughput = 1/p, independent of
  the bake duration (the oven is long enough to hold a whole bake-time of product).
- **Dedicated transport**: conveyors move product between stations; robots only load/unload
  at fixed points, or are eliminated where gravity/belt suffices.
- **Accumulation**: accumulating conveyor zones buffer jitter; upstream never blocks on
  downstream (and vice versa) within buffer limits.
- **Zoned process control**: oven as 3–5 thermal zones with ramp/soak profiles; cooling as a
  first-class stage (product is not "done" at oven exit — moisture equilibration).
- **100% inline inspection** at line speed with automatic reject/divert.
- **Changeover/SMED**: SKU (flavour) changes are scheduled, timed, and partially automated.

## 3. Candidate architectures for the tabletop cell

Four realistic options, evaluated for the *simulation* (and note where the physical
fischertechnik kit could mirror them):

### A. Conveyor-through oven (tunnel-ize the kiln) — **recommended first**
Replace the batch kiln with an **oven segment on the main conveyor**: the belt carries
cookie carriers straight through a heated tunnel (2–3 zoned sections), entry and exit on the
same belt line. The VGR only (a) stages raw carriers from the HBW belt onto the line and
(b) lifts finished carriers off the line for sorting/storage.
- **Why first**: removes the two biggest arm jobs (oven load/unload) and converts baking from
  serial dwell to pipelined transit. Physically plausible with the kit (the multi-processing
  station already sits on the belt path; a "tunnel" is a guarded heated segment).
- **Throughput**: from ~1 cookie per (arm cycle + full dwell) to ~1 cookie per belt pitch
  (cookie spacing). Expect the largest single gain available.
- **Sim work**: oven node becomes a conveyor segment with a residence-time profile (zones);
  thermal model goes from dwell-timer to transit-time + zone temps; arm planner loses two
  stations and gains fixed pick/place windows; renderer gets a tunnel shell.
- **Risk**: medium. Baking physics must respect transit = f(zone temps); the 12-cookie
  invariant becomes "cookies in system = raw + on-line (incl. in oven) + stored + finished".

### B. Rotary indexing table at the oven (dial)
Keep a batch oven but put a 4–6-station Geneva-indexed dial between arm and oven: the arm
loads station 1, the dial indexes, the oven processes one station while the arm loads the
next. Decouples arm from dwell.
- Good second step if A is too big a jump; keeps the kiln physics untouched.
- Sim work: dial kinematics (indexing), station occupancy, interlock matrix.

### C. Second handler (dual-arm pipelining)
Add a second small robot (delta or a second VGR) so one arm tends HBW+raw staging while the
other tends oven+sorting. 
- Doubles handling capacity but **does not remove the serial loop**; the oven batch ceiling
  stays. Better as a complement to A/B than a substitute.

### D. Closed-loop accumulating conveyor (power-and-free)
Replace point-to-point carrier moves with a loop belt past fixed stations (HBW load, oven,
cooling, vision, unload); carriers ride the loop; the arm only transfers carriers on/off at
the loop's HBW junction.
- The "most industrial" layout; highest sim effort (carrier traffic management, collisions,
  accumulation logic); best saved for after A proves the continuous-flow model.

## 4. The gap map (industrial vs current twin)

Severity: ●●● large, ●● moderate, ● small. "Closes in" refers to the phases in §5.

| # | Dimension | Industrial practice | Current twin | Gap | Closes in |
|---|---|---|---|---|---|
| G1 | Process type | continuous line (takt flow) | batch loop, serial arm | ●●● | P1 (A) |
| G2 | Transport | conveyors between stations; robots at fixed points only | one arm moves everything | ●●● | P1–P3 |
| G3 | Decoupling/WIP | accumulation buffers, FIFO lanes | none (only 9 rack bays) | ●●● | P2 |
| G4 | Oven | tunnel, 3–5 zones, transit-time control | batch kiln, dwell | ●●● | P1 |
| G5 | Cooling | first-class cooling stage | none | ●● | P2 |
| G6 | Inspection | 100% inline at line speed | vision at sort, per-carrier | ●● | P2 |
| G7 | Throughput | set by pitch, ~1000s/h | set by arm cycle + dwell | ●●● | P1 |
| G8 | Changeover | SMED, per-SKU recipes | flavour is a label, instant switch | ●● | P4 |
| G9 | Baking physics | moisture loss, colour development, zone profile | time-based done-ness | ●● | P2–P3 |
| G10 | Material unit | cookie on belt directly | cookie in carrier (tray) everywhere | ●● | P3 |
| G11 | Control | line-level PLC with takt master, station autonomy | cell PLC, sequential recipes | ●● | P2 |
| G12 | Data/I4.0 | AAS submodels per line asset, UNS topics per station | present (U14/17) but cell-shaped | ● | P2 (regenerate AAS) |
| G13 | Safety | zone guarding, light curtains, safe takt restart | e-stop latch, invariant guard (good) | ● | — |
| G14 | Maintenance | wear per moving part, line-balancing data | present (U6/8) | ● | P3 (new parts) |

Already at industrial grade (no gap): the I4.0 wrapper (AAS, OPC UA, UNS, security IEC 62443),
the copilot, predictive maintenance, energy/carbon accounting. The gap is **material flow**,
not intelligence.

## 5. Iteration roadmap (each phase independently shippable, gated by the test suite)

**P1 — Tunnel oven + fixed windows (closes G1, G4, G7; halves G2)**
1. Kernel: oven node → conveyor segment, `residence_s` derived from zone temps; cookies on
   the belt through the tunnel; dwell state becomes transit state.
2. Planner: oven load/unload stations disappear from the arm's station list; arm gets
   stage-at-entry / lift-at-exit windows; shortest-path logic unchanged.
3. Invariants: 12-cookie conservation rewritten as WIP accounting over {rack, line, oven,
   sort, store}; order queue logic untouched.
4. Renderer: tunnel shell with 3 zone sections; belt pitch marks.
5. Proof gates: golden trajectories updated; bake-time parity test (same total thermal dose
   → same done-ness); throughput report before/after (the number to show).

**P2 — Buffers, cooling, line control (closes G3, G5, G6, G11; half G9, G12)**
1. Accumulation zone before the oven entry (raw WIP buffer) and after sorting (finished
   buffer), each with a capacity and a blocked-starvation signal to the dashboard.
2. Cooling conveyor segment (ambient, 1.5–2× oven length in belt time) with its own quality
   contribution (crispness/condition attribute drifts if cut short).
3. Line-level takt: a master cycle sets belt pitch; stations report blocked/starved; the
   learned scheduler (U16) starts optimizing *takt and buffer levels*, not just arm moves.
4. Vision moves to line speed at the cooling exit with automatic divert.

**P3 — Continuous forming & carrier-less flow (closes G10, half G2/G9/G14)**
1. Cookies form directly on the belt at a stamper/former station (rotary-moulder analog);
   carriers retire to a small magazine the crane manages — the HBW stores trays/trays of
   dough or finished packs instead of single carriers.
2. Baking physics v2: moisture-loss + colour-development curves per zone (from U19's process
   work), so operator recipe changes (temp/speed) have physically visible quality effects.
3. New moving parts enter the wear/maintenance model (belt drive, stamper, zone dampers).

**P4 — Industrial operations layer (closes G8, remaining G12/G14)**
1. SMED-style flavour changeover: staged recipe switch with a timed pause, waste accounting,
   and a changeover record per SKU in the AAS/UNS.
2. AAS regeneration per *line asset* (tunnel oven zones, buffers, former) rather than per
   cell; UNS topic tree mirrors the line.
3. Copilot upgrade: NEXUS answers in takt/OEE language (pitch, availability, buffer levels),
   and the deep-research loop cites line-design references.

Deliberately **not** proposed: removing the VGR entirely (it is the cell's planning gem and
removing it would gut the training value — it shrinks to two fixed stations instead), and
re-platforming the PLC layer (U13's SIL work stays valid throughout).

## 6. What to decide now

1. **Scope of P1**: tunnel oven as a config flag (`STF_OVEN=tunnel|kiln`) so the batch cell
   remains available for teaching, or a hard cutover?
2. **Physical mirror**: should each sim phase map to a fischertechnik-part buildable layout
   (keeps the twin honest), or is the sim free to lead the hardware?
3. **Throughput target**: what bake time / pitch should P1 demonstrate (drives tunnel length
   and zone count in the layout)?

The recommended sequence is P1 → P2 → P3 → P4, each landing as one reviewed change-set on
`dev`, mirror-tested before `main` — the same pipeline as the security work.
