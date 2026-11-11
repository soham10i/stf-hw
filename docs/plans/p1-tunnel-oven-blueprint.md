# P1 Blueprint — Tunnel Oven Continuous Bake

**Status:** blueprint for review — nothing implemented. A fresh session can build this from
this document alone. Implements phase P1 of `docs/plans/industrial-gap-plan.md`.

**Owner decisions assumed (change if decided otherwise):** tunnel oven behind a config flag
`STF_OVEN=tunnel|kiln` (batch cell stays for teaching); sim leads hardware (numbers marked
CALIBRATE must be re-derived from `packages/stf_layout/factory.layout.yaml`, not trusted
blindly); target bake ~15 s sim-time at a 5 s pitch (CALIBRATE to the time-scale the owner wants
to demo).

---

## 1. Handoff brief for the implementing session

- Repo: `/Users/sohampatel/workspace/stf-hw`. Backend `services/api/` (FastAPI + in-memory
  simulation `runtime.py`, kernel in `packages/stf_kernel/`: `kernel.py`, `planner.py`,
  `motor.py`, `trajectory.py`). World geometry: `packages/stf_layout/factory.layout.yaml`.
  Renderer: `web/src/scene/`, physics workers `web/src/workers/motors.ts`. PLC SIL:
  `services/api/cycle.py`. Docs for grounding: `docs/reference/factory/hardware-model.md`,
  `docs/reference/factory/ground-truth.md`.
- Rules: **never commit or push** — leave all changes uncommitted for owner review. Gates
  before handing back: `PYTHONPATH=packages .venv/bin/python -m pytest -q --ignore=tests/perf`
  (known pre-existing failures: 2 golden-request recordings) and
  `.venv/bin/ruff check packages services tests` must show no NEW violations. Mirror testing
  is owner-driven (deploy/staging.sh); do not deploy.
- Conventions: fix in shared helpers; one regression test per behavior change; docstrings on
  classes/methods; the layout file is the single source of world geometry — derive every
  rendered pose from it (the codebase enforces this pattern already).

## 2. Goal and non-goals

**Goal:** convert baking from a batch kiln the VGR loads/unloads into a continuous
tunnel-oven line: carriers flow HBW → feed belt → tunnel (3 zones) → sort; the VGR shrinks
from flow-engine to exception/QC handler plus empty-carrier return.

**Non-goals (later phases):** accumulation buffers & cooling (P2), stamper/former and
carrier-less flow (P3), SMED changeovers & line-AAS (P4). Do not build them here.

**Success numbers (acceptance):** with the kiln path unchanged available under the flag, the
tunnel path bakes ≥3 carriers concurrently, sustains one finished cookie per pitch time, and
the VGR performs zero oven-load/unload moves per cookie (2 arm moves per cookie: QC/reject
and empty-carrier return, amortized).

## 3. Current geometry (verified against factory.layout.yaml)

- HBW rack face y=0; crane aisle y=−55; HBW Förderband y=−110, along x, crane transfer
  x=400 (belt-local 120) → VGR end x=520 (local 0); I3 pick window x=505, local 15.
- VGR base (600,−110); swivel 0 = arm along −x (cup at x=505 at reach 95); swivel limits
  [−95°, +135°]; reach [0,180] (conveyor position 95); plunge: transit 145 mm, pick 100 mm.
- Stations: oven pose (545.5,−187.8,100) at swivel +55°; delivery (624.6,−201.8,100) at
  swivel +105°.
- Processing plate: origin (440,−340), size 320×160 (x 440–760, y −340…−180).

## 4. New layout (all frame mm, +Z up; every pose derivable from the layout file)

```
plan view
 y=0    rack face (unchanged)
 y=-55  crane aisle (unchanged)
 y=-110 HBW belt:  x=400 [crane transfer] ========== x=520 [belt end]
                       raw carrier with dough travels ->

        [P1: feed pusher @ x≈515]  pushes carrier -y onto tunnel infeed
 y=-160 tunnel infeed window (fixed transfer point, no arm)
 y=-200..-260  TUNNEL BELT (new independent drive, along x)
        zone Z1 x 560-660 (ramp) | Z2 x 660-760 (soak) | Z3 x 760-860 (finish/colour)
        tunnel shell y -190..-270, heaters over Z1..Z3
 y=-260..-310 sorting conveyor (existing delivery direction, extended plate)
        vision/QC gate at x≈820, reject bin at x≈850
        empty-carrier exit buffer @ (640,-290), capacity 3 (arm-reachable)
        cookie offload: carriers tip/press at x≈780 -> cookies onto sort line (CALIBRATE
        mechanism: lift-gate flip, simplest is a fixed flip chute, no extra axis)

 VGR jobs now:  (a) reject pick at sort line (swivel ~+105..+120 window)
                (b) empty carrier: buffer (624,-201 area, reach 95 OK) -> HBW belt end
                    (swivel 0, conveyor) -> crane stores to C-column
 HBW: bays A1-B3 raw/finished (6); C1-C3 empty carriers (3)
```

Envelope checks (must hold in the layout file so the renderer proves reachability, as the
current stations do):
- Feed pusher and flip chute: fixed mechanisms, no arm — no check needed.
- Arm to empty-carrier buffer: cup target (624,−201) — current `delivery` station already
  sits there at reach 95, swivel +105. ✔ within limits.
- Arm to HBW belt end: swivel 0, reach 95 → cup (505,−110). ✔ existing.
- Sort reject window: place at swivel +120°, reach 95 → cup (600−95·cos120, −110−95·sin120)
  = (547.5,−192.3) — declare as `sort_reject` station; ✔ within [−95,135].
- Plate extension: processing plate grows to x 440–900 (renderer-only module entry; label
  Bearbeitungsstation → Tunnelofen line).

## 5. Mechanical bill of materials (fischertechnik-plausible)

| # | Part | Function |
|---|---|---|
| 1 | Tunnel shell (alu/profile + insulating panels, ~320×90×120 mm over the belt) | zones enclosure |
| 2 | 3× heating cartridges + zone dampers (Q per zone) | Z1 ramp / Z2 soak / Z3 finish |
| 3 | Independent belt drive M-tunnel (encoder) + 2 idlers | transit, pitch control |
| 4 | Feed pusher (small linear axis + flat paddle) | belt→tunnel transfer |
| 5 | Flip chute at exit (passive mechanics) | carrier→cookie onto sort line |
| 6 | Light barriers: tunnel entry/exit, one per zone inlet (4 total) | tracking, interlocks |
| 7 | Temperature sensor per zone (I2C/sim analog) | closed-loop zone control |
| 8 | Reject bin + existing colour/vision sensor moved to sort line | QC at line speed |

## 6. Process design

- **Pitch**: carrier pitch 100 mm (CALIBRATE to carrier length+gap); belt speed 20 mm/s
  (CALIBRATE; kit belt ~50 mm/s at 24 V — pick the demo value and record it) → pitch time
  **5 s/cookie**.
- **Residence**: tunnel 300 mm → 15 s transit = bake time; zones 180 °C / 220 °C / 200 °C
  (CALIBRATE; must satisfy: done-ness ≈ old dwell result for parity test).
- **WIP**: 3 carriers in tunnel + 1 at infeed + 1 at exit buffer max; total line WIP ≤ 5.
- **Invariant rewrite** (replaces the 12-cookie rule under the flag):
  `cookies_total = raw_in_rack + dough_carriers_on_feed + in_tunnel + at_exit + on_sort +
  finished_in_rack + rejected`, constant per session. Arm conservation: cookies only move
  QC/reject; dough→cookie identity happens at the tunnel exit (flip).
- **Energy**: heaters draw only while a carrier is in their zone + preheat state; energy
  model feeds the existing U9/U18 accounting (add `tunnel_zones` consumers).

## 7. Control design

New PLC states (add to `cycle.py` beside existing recipes; keep SIL style):
`TUNNEL_IDLE → TUNNEL_PREHEAT(Zi) → TUNNEL_RUN` with per-zone `temp_ok` bits; transitions
gated by light barriers; e-stop latch (existing `trigger_emergency_stop`) halts M-tunnel and
zone heaters. Interlocks: pusher extended blocks tunnel belt step; flip chute occupied
blocks exit transfer; buffer full (`exit_buffer.n=3`) stalls tunnel at Z3 exit (back-pressure
— first taste of accumulation, full version is P2).
Scheduler interface (U16): the learned scheduler gains `pitch_s` and `zone_temps` as
actions; reward unchanged (throughput − waste). Watchdog: new telemetry (zone temp
deviation, belt slip vs encoder, residence over/under) with severities matching the
existing incident ladder.

## 8. Software changes, file by file

1. `packages/stf_layout/factory.layout.yaml` — new `tunnel` section (belt line, zones,
   stations `sort_reject`, `empty_buffer`, pusher/flip poses), plate extension, C-column
   comment, arm station list drops `oven` (kept under flag), plunge/heights unchanged.
2. `packages/stf_kernel/kernel.py` — tunnel belt as a conveyor node with residence tracking;
   zone temperature state; cookie creation at flip (dough→baked identity); keep kiln node
   intact for the flag.
3. `packages/stf_kernel/planner.py` — oven load/unload recipes removed from the default plan
   under the flag; new minimal moves: reject-pick, empty-carrier return (HBW belt end),
   existing shortest-path logic reused unchanged.
4. `services/api/runtime.py` — order pipeline: `cycle` orders now mean "keep line fed",
   queue semantics unchanged; WIP accounting per §6.
5. `services/api/cycle.py` — PLC states/interlocks per §7.
6. `services/api/tools.py` + `agent.py` — `order_submit` unchanged surface; copilot facts
   gain tunnel fields (zones temp, pitch, line WIP); rules router unchanged.
7. `services/api/industrial_io.py` — OPC UA nodes for tunnel (belt speed, zone temps,
   barrier states) under the existing nodeset; AAS: add `TunnelOven` submodel entries
   (TechnicalData + Nameplate pattern already in U14; regeneration via existing AAS flow).
8. `web/src/scene/` — tunnel shell, heaters (emissive when on), flip chute, pusher, buffer
   stack; extend processing plate mesh. All poses from the layout file.
9. `web/src/workers/motors.ts` — tunnel belt + pusher axes in the physics loop.
10. Dashboard: Production/Oven pages get a `Tunnel` view (zone temps, pitch, WIP, residence
    histogram) reusing existing card styles; guide.ts entry for the docs page.
11. `services/api/app.py` — `STF_OVEN` env read, passed into runtime/kernel; no API shape
    change (existing endpoints suffice; new fields are additive).

## 9. Timing diagram (steady state, pitch 5 s)

```
carrier n:   feed --pusher--> Z1 ---- Z2 ---- Z3 --flip--> sort --> rack
              |<-- 5s -->|<-- 5s -->|<-- 5s -->|
time:        t0         t0+5       t0+10      t0+15 (cookie n done)
cookie n+1:                     feed --> Z1 ---- Z2 ...
                                (infeed steps every 5 s; 3 carriers resident)
arm:         idle ... reject pick at t0+16 ... empty-carrier return at t0+22 ...
```

## 10. Test gates (all must pass before handback)

1. **Parity:** same thermal dose → same done-ness distribution as the kiln path
   (statistical check vs recorded kiln outcomes, tolerance in test).
2. **Invariant:** WIP conservation holds across a 20-order soak (randomized timing).
3. **Envelope:** renderer reachability assertion for `sort_reject`/`empty_buffer` stations.
4. **Interlocks:** pusher-extended blocks belt; buffer-full stalls at Z3 exit; e-stop halts
   belt + heaters (extend existing e-stop tests).
5. **Throughput:** sustained ≥1 cookie/pitch for 10 pitches with zero arm oven moves.
6. **Flag:** `STF_OVEN=kiln` path unchanged — existing golden trajectories for the batch
   cell still pass untouched.
7. Regression tests for every new public method (repo convention).

## 11. Build order for the fresh session

1. Layout file: tunnel section + stations + plate (renderer will fail loudly if poses drift).
2. Kernel conveyor node + zone state + flip identity (no renderer yet) — unit tests 2,5.
3. Planner moves + runtime pipeline + flag wiring — tests 3,5,6.
4. PLC states/interlocks — test 4.
5. Renderer/scene + workers — visual check via `make api` + browser.
6. OPC UA/AAS/dashboard/docs — additive; screenshot for the owner review bundle.
7. Full gates + `docs/` note update; leave uncommitted with a summary in session notes.

## 12. Risks and open questions

- **Residence vs pitch**: 15 s bake / 5 s pitch needs ≥3 carriers in the tunnel — that's the
  whole point, but it consumes the 12-cookie budget fast; confirm the invariant cap with the
  owner (proposal: raise total to 24 under the flag, 12 stays the kiln-mode cap).
- **Flip mechanism**: passive chute is the cheap choice; if the owner's fischertechnik build
  wants a real offload axis, swap §5.5 for a small rotary actuator (one extra PLC axis).
- **Bake parity**: zone temps in §6 are starting points; the parity test (gate 1) is the
  authority — tune zones until it passes, then freeze them in the layout file.
- **A1-B3 only 6 storage bays** for raw+finished: if the owner demos >6 flavours/SKUs, the
  C-column split needs revisiting (noted for P4 changeover work).
