# Operations dashboard: user guide

The dashboard (`dashboard.html`, the **Dashboard** button in the 3D twin) shows the cell's production, health, energy and
security, from the twin's models. Every page opens with one line on what it is for; its **Guide** button shows the rest
of that page's section of this document, **Ask** opens the copilot beside the page, and an **i** beside each card
title says what the card shows.

> Every number is simulated from the twin's models, not measured on a real machine. Values the models only assume
> are marked *assumed* on the blueprint sheets.

## Pages

- **Operate**: [Overview](#overview) · [Production](#production) · [Quality & trace](#quality-trace) · [Vision QC](#vision-qc) · [Alarms](#alarms) · [Copilot](#copilot)
- **Maintain**: [Health](#health) · [Maintenance](#maintenance) · [Maintenance · AI predictions](#maintenance-ai-predictions)
- **Analyse**: [Month](#month) · [Throughput](#throughput) · [Oven process](#oven-process) · [Learned scheduler](#learned-scheduler) · [Energy & grid](#energy-grid) · [Carbon per cookie](#carbon-per-cookie) · [OT security](#ot-security) · [Defence in depth](#defence-in-depth)
- **Engineer**: [Engineering](#engineering) · [Validation](#validation) · [Data](#data)
- **Docs**: [Hardware degradation](#hardware-degradation)

---

## Operate

### Overview

The cell at a glance: order progress, what each unit is doing, where efficiency is lost and what needs service next.

**How to read it**

1. The time slider plays the order; every card follows it.
2. The machine-age slider and PM switch age the parts.
3. The links on the cards open the page behind each one.

| Section | What it shows |
|---|---|
| Key figures | Order progress, cookies per hour, OEE, running units and fleet health. |
| Production timeline | Each unit's jobs along the order; the line is now. Hover a legend entry for what a job does. |
| Units now | Each unit's state and job at the chosen time; green border = running. |
| OEE breakdown | Availability × performance × quality; the biggest loss is highlighted. |
| Next maintenance | The five parts closest to failure: health index and shifts left. |
| Downtime by fault | Time lost to each commissioning fault when it happens once. |
| Unit utilisation | Share of the order each unit is busy; the bottleneck is highlighted. |

*Data:* The PLC program's run of the order, commissioning and the wear model.

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

*Data:* The PLC orchestration model and its exhaustive check of every completion order.

### Quality & trace

Every cookie's record: which mould carried it, where the RFID heads read it, its colour reading and whether it matched the order.

**How to read it**

1. Each row is one cookie; click it for the times and readings along its way.
2. 'verified' means the colour sensor's reading put the cookie in the flavour the order asked for.

| Section | What it shows |
|---|---|
| Records | One line per cookie: flavour, mould, RFID reads, colour sensor reading in mV, and the verdict. |

*Data:* The PLC program's traceability design: RFID read points on the HBW belt and the sorting line's colour sensor.

### Vision QC

The inspection camera on the process: its live view, and every cookie the 3D twin bakes, photographed, judged by the CNN and the autoencoder, and checked against the truth the simulation knows.

**How to read it**

1. Open the 3D twin in a window beside this page: its camera in the colour hood streams here live (never recorded), and the photo it takes of each cookie is judged here (and stored by the server).
2. For each cookie: the photo, what the models see, the autoencoder's error map (hot = not as a good cookie looks), the truth and the decision.
3. One cookie in every 12 is damaged on purpose (QC testing, the Orders panel): each rack tests the inspection.
4. The KPIs and the confusion matrix count the cookies inspected since the page opened; escapes are damaged cookies let through.

| Section | What it shows |
|---|---|
| Inspection camera | The twin camera's live view (not recorded); the latest cookie's photo, what the models see, its autoencoder error map, truth, the CNN's answer and the decision; and a strip of recent cookies. |
| The decision | The pass threshold, and what pass, reject and 'to a person' mean for the cookie. |
| Confusion | Truth against the CNN's answer for each condition: everything off the diagonal is a mistake. |
| Ten photos from the process | Ten cookies the camera photographed while the twin baked an order, the QC test's damaged one among them, with what the CNN decided. |
| Drift | The autoencoder's error on normal-looking cookies against its training baseline; above ×2 the line no longer looks like what the models learnt. |
| The camera | Where it is mounted in the colour hood, its lens and trigger, and the mount's checks against the model. |
| Photos stored by the server | Each cookie your own twin photographed, as the server keeps it. |

*Data:* The camera mount (vision/mount.py), and the CNN and autoencoder run in the browser on the 3D twin's own photos.

### Alarms

Every alarm the PLC can raise, and how the machine reacted when each fault was injected into the twin.

**How to read it**

1. Fault matrix: each injected fault, the alarm it raised, how quickly, and whether the reaction was right ('pass').
2. Alarm list: the catalogue an operator would see, with cause, reaction and recovery for each code.

| Section | What it shows |
|---|---|
| Detection time per fault | How fast each injected fault raised its alarm. |
| Time lost per fault | Production lost when the fault happens once, against the mean (MTTR). |
| Fault matrix (commissioned) | Each fault's alarm, reaction and recovery. |
| Alarm list | Every watchdog alarm in the program: its code, the step it guards, and what to do. |

*Data:* Virtual commissioning of the PLC program against the twin.

### Copilot

Ask about the cell in plain words, by typing or by voice. A language model answers by calling the twin's own tools and states only what they return, with citations; the server checks every number before you see it. Conversations are kept in your history, and the facts each one establishes are kept with it.

**How to read it**

1. Pick a tab: Gemini (cloud models), Local (a model on this machine through Ollama) or Voice (speak, hear the answer).
2. If the model you chose is at its limit or not running, the next one answers with the same context - the chip on the answer says it switched.
3. Answers take the form the question needs: a figure, a table for comparisons, numbered steps for an alarm, a status card for 'now'.
4. Copy any question or answer; 🔊 reads an answer aloud.
5. History is on the left; the Context panel on the right lists what the conversation has established.

| Section | What it shows |
|---|---|
| History | Your earlier conversations; open one to continue it, × to delete it. |
| Gemini / Local / Voice | Which model answers first; the others take over when it cannot. |
| Context | The models that answered, the tools used and the facts found - what any model answering next is given. |

*Data:* The server's tools (services/api/tools.py), the model and its tool calls (chat.py), sessions and their context (sessions.py, store.py), speech (tts.py); scored on tests/copilot_eval.json.

---

## Maintain

### Health

How worn each part is at the chosen machine age, and which part needs attention first.

**How to read it**

1. Drag the machine-age slider: health falls as parts wear. Green healthy, amber warned, red failed.
2. Switch PM off to see the machine run to failure.
3. Click a part (runway row or map row) to see its signal; hover any chart to read values.

| Section | What it shows |
|---|---|
| Remaining life runway | For each part, from now: green until it warns, amber from the warning until it fails. The amber length is your window to service it. Switch the horizon to zoom. |
| Not predictable | Faults with no gradual sign, and the check that covers each. |
| Health map | Every part (rows) over the machine's whole life (across), coloured by health. With PM on, each stripe is a renewal; the white line is now. Hover for the value. |
| (the selected part) | Its smoothed signal against the soft and failure limits. Hover to read the health index, the true time to failure and the trend's estimate. |
| About this part | Warning lead time, false warnings, uses so far and the sensor it is measured with. |

*Data:* The condition-monitoring model. The theory is under Docs → Hardware degradation.

### Maintenance

When each part is next serviced and why, how the work spreads over the days, and the spares to stock.

**How to read it**

1. Each row of the schedule is a part; each diamond a service. Colour says why: preventive, warned or failed.
2. Switch PM off: the diamonds become breakdowns (×), the stops PM prevents.
3. Click a row for its interval and service door.

| Section | What it shows |
|---|---|
| Service schedule · next 30 days | Every service ahead, part by part, plus the routine PM visit. |
| Workload · services per day | How many services fall on each day; busy days are highlighted. |
| Work orders | The next six jobs, soonest first. |
| Spare parts | Wear parts used per year against stock, and the one-off breakdown spares. |

*Data:* Condition monitoring (warnings) and the lifecycle design (spares).

### Maintenance · AI predictions

A neural network that predicts each part's remaining life from its sensor history, tested on machines it never saw, and running here in your browser.

**How to read it**

1. Start with the scores: how often it warned in time, and how much part life it threw away.
2. The network advises; the rules of the Health page still decide. Together they warn early and waste less.
3. The showcase compares the network's prediction with the truth on one unseen machine.

| Section | What it shows |
|---|---|
| What happened to each of the | Every failure on machines the network never saw: warned at least a shift ahead (green), late (amber) or missed (red), per method. |
| Verdict | What to do with the network, in three lines. |
| The trade-off | Each method as a point: failures warned in time against part life thrown away. Top-left is better; hover a point. |
| Choosing the network's alarm threshold | How the share warned in time changes with the alarm threshold; the chosen value is marked. |
| Per part | Network (blue) against the rules (amber) for each part: the gap shows where the network is weak. |
| Training loss | How the error fell while it learned; 'Model and data' opens the details. |
| An unseen machine | Predicted against true remaining life, part by part, with the failure, the alarms and the rule warnings marked. |
| Running here | The network applied to the simulated month, live in this page. |
| At order | Each part's predicted remaining life at the chosen order, shortest first. |

*Data:* A TCN trained on a fleet of simulated machines, exported to ONNX and to the browser.

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
| Good cookies per day | Daily output against the month's average; amber = planned maintenance that night, red = a failure. The axis starts near the lowest day so differences show. |
| OEE per day | Daily OEE against the month's figure; hover for the value. |
| Where the time went | Planned time split into producing, faults, maintenance and idle. |
| Orders started per hour | When in the day orders arrived (day × hour). |
| The counterfactual month | The same month without preventive maintenance: what failed and what it cost. |
| Component sensor traces | Colour sensor mV per order, actuator current, compressor duty and vacuum losses - the signals wear shows in. |
| Hours per state, per unit | RUN, HELD, IDLE and FAULT hours from each unit's state machine. |
| Downloads (CSV) and event log | Every order, event and sensor reading of the month. |

*Data:* The month simulator (month.py) driven by the wear model and the maintenance plan.

### Throughput

How the same machine was made faster by changing only its program, and what each change is worth.

**How to read it**

1. Compare the two Gantt rows: before and after, on one time scale.
2. The critical path shows which jobs set the order time; the ablation shows each improvement's own value.

| Section | What it shows |
|---|---|
| What the study says | The headline: order time before and after, and why. |
| The same order, before and after | Both programs' runs, step by step, from virtual commissioning. |
| Where the time went: the critical path | The chain of jobs that decides the order time. |
| Ablation | The order time with each improvement switched off; hover a bar for cycle time and the busiest unit. |
| What each measure is worth | Seconds each improvement saves alone and in the full set; they differ because the measures interact. |
| The VGR's tours | Each tour's time before and after the blended paths. |
| With a real bake | Order time against bake time: the longer the bake, the less the faster loop matters. |
| OEE, before and after | Availability, performance, quality and OEE, measured the same way. |
| Proofs the faster program still passes | Deadlock freedom and fault recovery, re-run for the new program. |

*Data:* The throughput study, measured by virtual commissioning.

### Oven process

The bake as heat and water: the oven heating and holding, a cookie baking through its thickness, four ways to end a bake, and what a real bake does to capacity and energy.

**How to read it**

1. The headline figures: cookies right first time with the best way of ending a bake, cookies an hour with a real bake, the heat per cookie.
2. One cookie in the oven: the centre waits near 100 °C while the water boils off; the colour comes last and fast.
3. Four ways to end a bake, run over the same shifts: compare how many cookies come out right, and which dough each one gets wrong.

| Section | What it shows |
|---|---|
| What the model found | The findings in short: quality, capacity, energy and the microgrid. |
| One cookie in the oven | Surface, centre and bottom temperatures, the water left and the browning index of a nominal cookie, with when it is done and when it reaches its colour. |
| The oven heating up | From switch-on to 180 °C: the elements, the air, the thermocouple and the walls, and the heater's duty. |
| Four ways to end a bake | A fixed timer, the PLC's model of the cookie (soft sensor), the camera correcting the colour, and dough sensors: cookies right, underbaked and burnt. |
| Each cookie of one shift | Every cookie's browning against the right band, per policy, with the dough lots marked. |
| The oven through a shift | The chamber air and the cookie through the door openings of a shift. |
| What a real bake does to capacity | The 12-cookie order with the 2 s lamp and with a real bake, and how many ovens the rest of the cell could feed. |
| Where the heat goes | One shift's heat: walls, door, vent, the open mouth, the tray outside and the steam. |
| Checks | The model's proofs, the faults they catch, and every parameter with its source. |

*Data:* The oven and cookie model of Upgrade 19 (stf-cad/hbw/bake.py), from the oven's parts (oven_model.py) and the order's door openings (control.py).

### Learned scheduler

Whether a learning scheduler finds a faster order than the PLC's priority list without ever risking a deadlock.

**How to read it**

1. The headline: order time against the PLC, and the deadlocks with and without the shield.
2. The two Gantt charts share one time axis; hover a block for its job and slot.
3. The test runs use identical random job times for every scheduler, so the comparison is fair run by run.

| Section | What it shows |
|---|---|
| The same order, two schedulers | The PLC's schedule and the scheduler's, on one time axis. |
| Order time on random job times | Fastest to slowest run, and the mean, for every scheduler. |
| Run by run against the PLC | Seconds saved in each test run with identical job times. |
| Learning, and what the shield blocked | Order time while the agent learned; hover for how many actions the shield blocked. |
| Where the moulds go | The rack slots each scheduler stores into: the gain comes from shorter crane travel. |

*Data:* sched_rl.py: Q-learning and a rollout scheduler over the PLC's job choices, behind a shield proven by exhaustive exploration.

### Energy & grid

The cell behind a small microgrid - solar panels, a battery and an energy manager - and the real oven on its own circuit, over the simulated month.

**How to read it**

1. Pick a day to see its power flows hour by hour.
2. Compare the three ways of powering the site on cost, grid use and outages survived.
3. The oven's supply compares the oven on its own circuit with a microgrid big enough to carry it.

| Section | What it shows |
|---|---|
| What the month says | The results: energy, cost, outages ridden through. |
| Power flows on day | Solar, battery, grid and load for one day; hover to read every flow. |
| Three ways to power the site | Grid only, PV only and PV + battery + energy manager on cost, CO₂, peak import and self-sufficiency. |
| Energy per day | PV, load and grid import for each day: import rises on dull days. |
| Power quality | Every mains event, whether the cell rides through and whether the oven goes cold; hover a result for why. |
| Power-asset health | The power supply's capacitors and the cabinet air filter, which wear with heat and dust. |
| PV soiling | Panel performance against the irradiance sensor, and the cleanings. |
| Battery and contactors | Battery ageing and contactor switching at this month's rate. |
| Economics, honestly | Capital cost by item, payback and production protected. |
| The oven's supply | The 1 300 W oven on its own 230 V circuit against a resized microgrid that carries it: outages, demand response, bill and payback. |
| Standards the design follows | The norms the microgrid design is checked against. |

*Data:* The microgrid model (grid.py), simulated, not measured.

### Carbon per cookie

How many grams of CO₂e each good cookie costs, where they come from, and what each lever saves.

**How to read it**

1. The headline figures: grams per cookie and per order, how much of it is the oven and the cell standing idle, and an estimate with a real bake.
2. The levers re-run the same month through the same energy manager, one change at a time.
3. Hover the hourly chart to see the grid's carbon intensity at each hour.

| Section | What it shows |
|---|---|
| Where a cookie's carbon comes from | The month's emissions shared out over what drew the power; red is drawn whether or not a cookie is made, amber is the oven held hot. |
| What each lever does | Grams per cookie with each change added: PV and battery, sleep when idle, a carbon-aware battery, the faster program. |
| The day, hour by hour | Load, PV and grid import through an average day, and the grid's carbon intensity by hour. |
| Per day | Grams per cookie each day, coloured by the weather. |

*Data:* The microgrid month (grid.py) allocated by carbon.py.

### OT security

The cell's network split into IEC 62443 zones, and what happens when attacks are replayed on the twin.

**How to read it**

1. Start with the zone picture: which devices trust each other, and the only paths (conduits) between zones.
2. For each attack, compare: no protection, detection only, and the OT security design.

| Section | What it shows |
|---|---|
| What the analysis says | The findings in short. |
| Zones and conduits | Each zone, its target security level, and the allowed paths between zones. |
| Attacks, replayed on the twin | Each attack's effect without and with the protections; for the spoofed sensor, which steps catch a lie. |
| Conduit C1: the Modbus allow-list | Every message the PLC may send to the I/O nodes, generated from the PLC program itself. |
| Conduit C3: what the energy manager may write | The few inverter settings the energy manager may change. |
| Security levels | Capability (red) against target SL 2 (green) per device and requirement; hover for the countermeasure. |
| Safety stays off the network | Why the E-stops and door locks have no network interface. |
| HMI: what an operator may write | The tags an operator may change, and who. |
| New alarms | The security alarms this upgrade adds. |
| Signed program manifest | The hashes the PLC checks before it runs a program. |

*Data:* The security design (security.py): a model-based assessment, not a penetration test.

### Defence in depth

Where the machine no longer trusts its own program: hardwired interlocks, and the OT security findings re-run.

**How to read it**

1. Each jog rule is hardwired only where the machine already has the switch it needs.
2. The re-run shows each finding closed on the hardened machine, and what it cost.

| Section | What it shows |
|---|---|
| What changed | The hardening in short. |
| Every jog rule | Steps each manual-move rule guards; green = now a relay contact, grey = no switch to wire it to, red = would block the program's own steps. |
| The OT security findings, re-run | Each earlier finding against the hardened machine. |
| Energy: what holding the reserve costs | Lowest battery charge and grid import in demand-response windows, before and after. |
| New parts | The interlock relays on each I/O node's rail and the standstill monitor in the cabinet. |

*Data:* The hardened machine (hardening.py).

---

## Engineer

### Engineering

The mechanical engineering behind the machine: how precisely it positions, its tolerances, stiffness and service access.

**How to read it**

1. Each table compares what the design achieves with what it must achieve; green is within the limit.

| Section | What it shows |
|---|---|
| Positioning accuracy | Each axis's stopping error (blue) against what is allowed (green). |
| Tolerance chains | Clearance left when every tolerance stacks the wrong way; red would mean parts can collide or miss. Hover for the value before the lifecycle changes. |
| Structure | Each frame member's lowest natural frequency against the minimum the drives need. |
| Service access | How far a technician must reach through each door to the part; red bars are beyond the allowed reach. |

*Data:* Commissioning and the lifecycle design.

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
| Register map | Each signal, its node and its Modbus register. |

*Data:* The register map; the live MQTT/Sparkplug namespace is in the twin's 'MQTT Sparkplug · UNS' panel.

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

*Data:* health.py and health_theory.py; the same model ported to the browser.

---

## Terms

| Term | Meaning |
|---|---|
| Soft sensor | A quantity no sensor measures, computed from a model fed by the sensors there are: here the cookie's centre temperature, water and colour, from a model of the oven run on the thermocouple. |
| Run-to-run control | Correcting the next run from how the last one came out: here the camera's colour reading moves the next cookie's colour target. |
| Browning index | 0 = raw dough, 1 = as dark as it gets. It grows faster the hotter and drier the surface (Maillard reactions); 0.35-0.65 is the right colour. |
| SFC | Sequential function chart (IEC 61131-3): a program drawn as steps, each with its outputs, and the transitions between them, each with its condition. |
| PLC | Programmable logic controller: the industrial computer that reads the sensors and drives the motors, scan after scan (here every 5 ms). |
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
