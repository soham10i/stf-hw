# Operations dashboard: user guide

The dashboard (`dashboard.html`, the **Dashboard** button in the 3D twin) shows the cell's production, health, energy and
security, from the twin's models. Every page has a **Guide** button that shows the section of this document for that
page, and an **i** beside each card title that says what the card shows.

> Every number is simulated from the twin's models, not measured on a real machine. Values the models only assume
> are marked *assumed* on the blueprint sheets.

## Pages

- **Operate**: [Overview](#overview) · [Production](#production) · [Quality & trace](#quality-trace) · [Vision QC](#vision-qc) · [Alarms](#alarms)
- **Maintain**: [Health](#health) · [Maintenance](#maintenance) · [AI maintenance](#ai-maintenance)
- **Analyse**: [Month](#month) · [Throughput](#throughput) · [Energy & grid](#energy-grid) · [OT security](#ot-security) · [Defence in depth](#defence-in-depth)
- **Engineer**: [Engineering](#engineering) · [Validation](#validation) · [Data](#data)
- **Docs**: [Hardware degradation](#hardware-degradation)

---

## Operate

### Overview

The cell at a glance: where the current order is, what each unit is doing, what costs time and what needs maintenance next.

**How to read it**

1. The time slider at the top plays the 12-cookie order; every card follows it.
2. The machine-age slider ages the parts; the PM switch shows them with and without preventive maintenance.
3. The links on the cards (details →, planner →, alarms →) open the page behind each one.

| Section | What it shows |
|---|---|
| Key figures | Order progress, cookies per hour, OEE, running units, component health and the worst part, for the time and age you have chosen. |
| Production timeline | A Gantt chart of the order: each unit's jobs along the time axis, with the current time marked. |
| Units now | The step every unit's state machine is in at the chosen time. |
| Next maintenance | The parts closest to their warning at the chosen machine age, and how many shifts they have left. |
| Downtime by cause (U5 fault matrix) | How much time each fault from the commissioning tests costs when it happens once. |
| Unit utilisation | The share of the order each unit is busy: the highest bar is the bottleneck. |

*Data:* The PLC program's run of the order (Upgrade 4), commissioning (Upgrade 5) and the wear model (Upgrade 6).

### Production

The order in detail: every job of every unit, how far each flavour is, and why the PLC uses the dispatch policy it does.

**How to read it**

1. Play or drag the time slider and watch the Gantt chart and the unit steps move together.
2. In the policy table, a lower order time is better; 'deadlock' means that policy can get stuck.

| Section | What it shows |
|---|---|
| Gantt: the 12-cookie order, PLC policy | Each unit's jobs over time under the chosen policy; waiting shows as gaps. |
| Units and their current step | The step and job of each unit at the chosen time, as the PLC sees it. |
| Order by flavour | How many cookies of each flavour are baked, sorted and back in the rack. |
| Dispatch policies (measured) | Each policy's order time, checked over every possible timing; the one in use is highlighted. |

*Data:* The PLC orchestration model and its exhaustive check of every completion order (Upgrade 4).

### Quality & trace

Every cookie's record: which mould carried it, where the RFID heads read it, its colour reading and whether it matched the order.

**How to read it**

1. Each row is one cookie; click it for the times and readings along its way.
2. 'verified' means the colour sensor's reading put the cookie in the flavour the order asked for.

| Section | What it shows |
|---|---|
| Records | One line per cookie: flavour, mould, RFID reads, colour sensor reading in mV, and the verdict. |

*Data:* The traceability design of Upgrade 4: RFID read points on the HBW belt and the sorting line's colour sensor.

### Vision QC

The inspection camera's live feed: every cookie photographed, judged by the CNN and the autoencoder, and checked against the truth the simulation knows.

**How to read it**

1. Watch the live camera: the image, the CNN's answer and decision, and the autoencoder's error map (hot = not as a good cookie looks).
2. The KPIs and the confusion matrix say how right the CNN is over the last 50 cookies; escapes are defects it let through.
3. Change the conditions (ageing light, a warmer lamp, a worn belt) and watch the drift chart rise before the CNN's answers go wrong.
4. With the 3D twin open in another tab, the feed photographs the twin's own cookies.

| Section | What it shows |
|---|---|
| Live camera | The latest cookie: camera image, autoencoder error map, truth, the CNN's answer and the line's decision, and a strip of recent cookies. |
| The line | Run or pause, the conditions, the defect rate the simulation injects and the line's speed. |
| Confusion (last 50) | Truth against the CNN's answer for each condition: everything off the diagonal is a mistake. |
| Drift | The autoencoder's error on normal-looking cookies against its training baseline; above ×2 the line no longer looks like training. |
| The camera | Where it is mounted in the colour hood, its lens and trigger, and the mount's checks against the model. |
| The models, tested offline | The CNN and the autoencoder on held-out images like training and on unseen conditions. |

*Data:* Upgrade 15: the camera mount (vision/mount.py), the CNN (vision/train.py) and the autoencoder (vision/autoencoder.py), run in the browser on images drawn by the renderer port.

### Alarms

Every alarm the PLC can raise, and how the machine reacted when each fault was injected into the twin.

**How to read it**

1. Fault matrix: each injected fault, the alarm it raised, how quickly, and whether the reaction was right ('pass').
2. Alarm list: the catalogue an operator would see, with cause, reaction and recovery for each code.

| Section | What it shows |
|---|---|
| Fault matrix (commissioned) | Seven faults injected into the virtual machine - stuck switch, motor stall, lost vacuum, E-stop and more - and the result of each. |
| Alarm list | Every watchdog alarm in the program: its code, the step it guards, and what to do. |

*Data:* Virtual commissioning of the PLC program against the twin (Upgrade 5).

---

## Maintain

### Health

How worn each part is at the chosen machine age, and which part needs attention first.

**How to read it**

1. Drag the machine-age slider: health falls as parts wear. Green healthy, amber warned, red failed.
2. Switch PM off to see the machine run to failure.
3. Click a part (bar, line or legend) to see its signal.

| Section | What it shows |
|---|---|
| Health index now | Every part's health, worst first, with shifts left until failure. |
| Health over machine age | Each part's health across the machine's life; the dashed line is now. |
| (the selected part) | Its smoothed signal against the soft limit and the failure limit, and when it was warned. |
| Not predictable | Faults with no gradual sign, and the check that covers each. |

*Data:* The condition-monitoring model of Upgrade 6. The theory is under Docs → Hardware degradation.

### Maintenance

The work orders the health warnings create, and the spare parts to keep in stock.

**How to read it**

1. A work order appears when a part warns; it is done at the next shift change, or at once if the part will not last that long.
2. The spare-parts table says how many of each part to stock and why.

| Section | What it shows |
|---|---|
| Work orders | Each order: the part, why it was raised, when it is due and what it costs in time. |
| Spare parts (U7) | Stock per part from its life and lead time, so a warned part can always be replaced. |

*Data:* Upgrade 6 (warnings) and Upgrade 7 (lifecycle and spares).

### AI maintenance

A neural network that predicts each part's remaining life from its sensor history, tested on machines it never saw, and running here in your browser.

**How to read it**

1. Start with the scores: how often it warned in time, and how much part life it threw away.
2. The network advises; the rules of the Health page still decide. Together they warn early and waste less.
3. The showcase compares the network's prediction with the truth on one unseen machine.

| Section | What it shows |
|---|---|
| Scored on unseen machines | Warnings in time, false alarms and wasted life, against the rule-based warnings. |
| The decision, tuned properly | The alarm threshold chosen on validation data: the trade-off between warning late and renewing early. |
| Per component | The same scores for each part. |
| How it was trained | The network type, the data and the training method. |
| Training loss | How the error fell while it learned. |
| Running here, in the browser | The network applied to the simulated month, live in this page. |
| An unseen test machine | Predicted against true remaining life for one machine the network never saw. |

*Data:* Upgrade 8: a TCN trained on a fleet of simulated machines, exported to ONNX and to the browser.

---

## Analyse

### Month

A whole simulated month of production - orders, faults, wear and maintenance - and what it says.

**How to read it**

1. Read the insights first; each one points to the chart that shows it.
2. Hover a bar or a cell for the numbers of that day or hour; click a note to expand it.
3. The CSV downloads hold the same data for your own analysis.

| Section | What it shows |
|---|---|
| Insights from the month's data | The findings: what cost the most, what maintenance saved, where the trends are. |
| Good cookies per day, and OEE | Daily output; amber days had planned maintenance. |
| Where the time went | Planned time split into producing, faults, maintenance and idle. |
| Orders started per hour | When in the day orders arrived (day × hour). |
| The counterfactual month | The same month without preventive maintenance: what failed and what it cost. |
| Component sensor traces | Colour sensor mV per order, actuator current, compressor duty and vacuum losses - the signals wear shows in. |
| Hours per state, per unit | RUN, HELD, IDLE and FAULT hours from each unit's state machine. |
| Downloads (CSV) and event log | Every order, event and sensor reading of the month. |

*Data:* The month simulator (month.py) driven by the wear model of Upgrade 6 and the maintenance of Upgrade 7.

### Throughput

How the same machine was made faster by changing only its program, and what each change is worth.

**How to read it**

1. Compare the two Gantt rows: before (Upgrade 7) and after (Upgrade 10), on one time scale.
2. The critical path shows which jobs set the order time; the ablation shows each improvement's own value.

| Section | What it shows |
|---|---|
| What the study says | The headline: order time before and after, and why. |
| The same order, before and after | Both programs' runs, step by step, from virtual commissioning. |
| Where the time went: the critical path | The chain of jobs that decides the order time. |
| Ablation | Each improvement switched off alone: the time it saves. |
| The VGR's tours | The arm's blended paths, flown just above the height the collision sweep proves clear. |
| With a real bake | How the oven starts to limit the order when baking takes longer. |
| OEE, same shift definition | OEE before and after, measured the same way. |
| Proofs the faster program still passes | Deadlock freedom and collision checks, re-run for the new program. |

*Data:* Upgrade 10's throughput study, measured by virtual commissioning.

### Energy & grid

The cell behind a small microgrid - solar panels, a battery and an energy manager - over the simulated month.

**How to read it**

1. Pick a day to see its power flows hour by hour.
2. Compare the three ways of powering the cell on cost, grid use and outages survived.

| Section | What it shows |
|---|---|
| What the month says | The results: energy, cost, outages ridden through. |
| Power flows on day … | Solar, battery, grid and load for one day, as the energy manager planned them. |
| Three ways to power the cell | Grid only, solar + battery, and with the energy manager, side by side. |
| Power quality | Every mains event (dips, outages) and what the inverter made of it. |
| Power-asset health | The power supply's capacitors and the cabinet air filter, which wear with heat and dust. |
| PV soiling, battery and contactors | Panel cleaning, battery ageing and switching. |
| Economics, honestly | What it costs and saves, with the assumptions stated. |
| Standards the design follows | The norms the microgrid design is checked against. |

*Data:* Upgrade 9's microgrid model (grid.py), simulated, not measured.

### OT security

The cell's network split into IEC 62443 zones, and what happens when attacks are replayed on the twin.

**How to read it**

1. Start with the zone picture: which devices trust each other, and the only paths (conduits) between zones.
2. For each attack, compare: no protection, detection only, and the Upgrade 11 design.

| Section | What it shows |
|---|---|
| What the analysis says | The findings in short. |
| Zones and conduits | Each zone, its target security level, and the allowed paths between zones. |
| Attacks, replayed on the twin | Each attack's effect on production without and with the protections. |
| Conduit C1: the Modbus allow-list | Every message the PLC may send to the I/O nodes, generated from the PLC program itself. |
| Conduit C3: what the energy manager may write | The few inverter settings the energy manager may change. |
| Security levels | Where the devices fall short of SL 2, and what covers the gap. |
| Safety stays off the network | Why the E-stops and door locks have no network interface. |
| HMI and the signed program manifest | What an operator may change, and how the PLC refuses an altered program. |

*Data:* Upgrade 11's security design (security.py): a model-based assessment, not a penetration test.

### Defence in depth

Where the machine no longer trusts its own program: hardwired interlocks, and the Upgrade 11 findings re-run.

**How to read it**

1. Each jog rule is hardwired only where the machine already has the switch it needs.
2. The re-run shows each finding closed on the hardened machine, and what it cost.

| Section | What it shows |
|---|---|
| What changed | The hardening in short. |
| Every jog rule | Which manual-move rules are now relay contacts instead of program logic, and why the others are not. |
| The U11 findings, re-run | Each earlier finding against the hardened machine. |
| Energy: the trade-off | What keeping a ride-through reserve costs in demand response. |
| New parts | The interlock relays on each I/O node's rail and the standstill monitor in the cabinet. |

*Data:* Upgrade 12 (hardening.py).

---

## Engineer

### Engineering

The mechanical engineering behind the machine: how precisely it positions, its tolerances, stiffness and service access.

**How to read it**

1. Each table compares what the design achieves with what it must achieve; green is within the limit.

| Section | What it shows |
|---|---|
| Positioning accuracy (U5) | How far each axis overshoots its target at the PLC's task cycle, against what is allowed. |
| Tolerance chains, worst case (U7) | Stacked part tolerances at their worst combination, before and after Upgrade 7: a negative worst case means parts can collide or miss. |
| Structure dynamics (U7) | How far each frame member bends under load (δ) and its lowest natural frequency (f₁): a stiff member vibrates fast and little. |
| Service access (U7) | How far a technician must reach through each door to the part; red bars are beyond the allowed reach. |

*Data:* Upgrades 5 and 7.

### Validation

How the project checks itself: every variant re-built, the plant varied, and defects planted to prove the checks can fail.

**How to read it**

1. Regression: every upgrade's machine is re-exported and must give the same result.
2. Mutation tests: each planted defect must be caught; one that survives would be a gap in the proofs.

| Section | What it shows |
|---|---|
| Regression: every variant re-exported | Each upgrade's export rebuilt and compared with its recorded fingerprint. |
| Robustness: ±20 % on every plant step | Random plants with every step time varied; no false alarms allowed. |
| Data products | Checks on the published data: the network's ONNX and browser copies against the original, the month and grid files, the tests and the web build. |
| Mutation tests | A defect planted in each proof, and which check caught it. |
| Failing checks | Anything currently failing (normally empty). |

*Data:* validate.py, which re-proves every variant.

### Data

Where the dashboard's data would come from on a real machine: the MQTT topics and the I/O register map.

**How to read it**

1. Topics: the path from the PLC through MQTT and a historian to this page.
2. Register map: every PLC signal's Modbus address on the remote I/O nodes.

| Section | What it shows |
|---|---|
| Topics (PLC → MQTT → historian → this page) | The message topics the page would read on real hardware. |
| Register map (U5) | Each signal, its node and its Modbus register. |

*Data:* Upgrade 5's register map; the live MQTT/Sparkplug namespace is in the twin's 'MQTT Sparkplug · UNS' panel (Upgrade 14).

---

## Docs

### Hardware degradation

The theory behind the Health page: how wear is modelled, measured, smoothed and turned into warnings, running live.

**How to read it**

1. Pick a part: its own wear law runs on the chart, one life in about 30 seconds.
2. The numbered circles on the chart match the numbered equations below.
3. Switch to 'healthy' to see that no warning comes; raise the noise to see why smoothing matters.

| Section | What it shows |
|---|---|
| Live | Measured signal, true wear, smoothed signal, the trend and both limits, cycle by cycle. |
| Steps 1-10 | Each modelling step as an equation, with its source and its value for the chosen part. |
| Every part: closed form vs simulation | The equations predict when each part warns; the simulation agrees. |
| References | The standards, papers and books each step comes from. |

*Data:* health.py (Upgrade 6) and health_theory.py; the same model ported to the browser.

---

## Terms

| Term | Meaning |
|---|---|
| OEE | Overall equipment effectiveness = availability × performance × quality. 100 % means making only good parts, as fast as possible, with no stops. |
| Order time (makespan) | How long the whole 12-cookie order takes from the first move to the last cookie stored. |
| Shift | 8 hours of production. Machine age and remaining life are counted in shifts. |
| Health index (HI) | 100 = as new, 0 = it fails now. Computed from how far a part's measured behaviour has drifted toward its failure limit. |
| RUL | Remaining useful life: how many shifts (or orders) a part has left before it fails. |
| EWMA | Exponentially weighted moving average: each new reading moves the smoothed value a small step (2 %) towards it, so noise averages out but a real trend shows. |
| PM | Preventive maintenance: renewing a part when it warns, before it fails. The PM switch shows the machine with and without it. |
| Watchdog | A time limit on each PLC step. A step that takes too long raises an alarm - the first sign of a stuck switch or a stalled motor. |
| Policy | The rule the PLC uses to decide which cookie or mould to move next. Different policies give different order times. |
| Deadlock | A state where every unit waits for another and nothing can move. The policies are checked so this can never happen. |
| PLr | Required performance level (ISO 13849-1), a to e: how reliable a safety function must be for its hazard. |
| SL | Security level (IEC 62443), 1 to 4: how strong an attacker a zone must withstand. The cell targets SL 2. |
| Zone / conduit | IEC 62443 groups devices into zones of equal trust; a conduit is the only allowed path between two zones. |
| Allow-list | The complete list of network messages that may pass a conduit. Anything not on it is dropped. |
| Gantt chart | One row per unit, one block per job, along a time axis: shows what runs in parallel and what waits. |
| Critical path | The chain of jobs that sets the order time: speeding up anything off this chain does not shorten the order. |
| Ablation | Switching off one improvement at a time to measure what each one is worth on its own. |
| Mutation test | Planting a deliberate defect to check that the proof catches it. A proof that cannot fail proves nothing. |
| TCN | Temporal convolutional network: the neural network that reads each part's sensor history and predicts its remaining life. |
| Semi-supervised | Trained on many simulated machines where failures are known for only some of them. |
| Ride-through | Energy kept in the battery so the cell can finish its work through a mains outage. |
| Demand response | Using less grid power when the grid operator asks, in exchange for a lower price. |
| mV (colour sensor) | The colour sensor gives a voltage in millivolts that depends on how bright the cookie is - it is a brightness reading, not a colour. |
| Autoencoder | A network trained to rebuild images of good cookies only. What it rebuilds badly is unusual - it needs no defect labels. |
| Drift | The line's conditions moving away from what the models were trained on (light, lamp colour, belt wear). The autoencoder's error rises before the classifier's answers go wrong. |
| Escape | A defective cookie the inspection passed as good - the costly mistake. |
| False reject | A good cookie the inspection threw out - wasted product. |
| Simulated | Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'. |

*Generated from `web/src/dashboard/guide.ts` by `web/scripts/guide-md.ts`.*
