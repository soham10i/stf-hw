// The dashboard's user guide: for every page, what it shows, how to read it, what each
// section means and the terms it uses. The dashboard shows it (the Guide button, and the
// i on each card); web/scripts/guide-md.ts writes the same text to docs/DASHBOARD_GUIDE.md.

export type PageGuide = {
  title: string;
  /** one sentence: what the page is for */
  what: string;
  /** how to read it, in a few steps */
  read: string[];
  /** section title (as on the page) -> what it shows */
  sections: [string, string][];
  /** where the numbers come from */
  source: string;
  /** the TERMS this page uses */
  terms: string[];
};

export const TERMS: Record<string, string> = {
  "OEE": "Overall equipment effectiveness = availability × performance × quality. 100 % means making only good parts, as fast as possible, with no stops.",
  "Order time (makespan)": "How long the whole 12-cookie order takes from the first move to the last cookie stored.",
  "Shift": "8 hours of production. Machine age and remaining life are counted in shifts.",
  "Health index (HI)": "100 = as new, 0 = it fails now. Computed from how far a part's measured behaviour has drifted toward its failure limit.",
  "RUL": "Remaining useful life: how many shifts (or orders) a part has left before it fails.",
  "PM": "Preventive maintenance: renewing a part when it warns, before it fails. The PM switch shows the machine with and without it.",
  "Watchdog": "A time limit on each PLC step. A step that takes too long raises an alarm - the first sign of a stuck switch or a stalled motor.",
  "Policy": "The rule the PLC uses to decide which cookie or mould to move next. Different policies give different order times.",
  "Deadlock": "A state where every unit waits for another and nothing can move. The policies are checked so this can never happen.",
  "PLr": "Required performance level (ISO 13849-1), a to e: how reliable a safety function must be for its hazard.",
  "SL": "Security level (IEC 62443), 1 to 4: how strong an attacker a zone must withstand. The cell targets SL 2.",
  "Zone / conduit": "IEC 62443 groups devices into zones of equal trust; a conduit is the only allowed path between two zones.",
  "Allow-list": "The complete list of network messages that may pass a conduit. Anything not on it is dropped.",
  "Gantt chart": "One row per unit, one block per job, along a time axis: shows what runs in parallel and what waits.",
  "Critical path": "The chain of jobs that sets the order time: speeding up anything off this chain does not shorten the order.",
  "Ablation": "Switching off one improvement at a time to measure what each one is worth on its own.",
  "Mutation test": "Planting a deliberate defect to check that the proof catches it. A proof that cannot fail proves nothing.",
  "TCN": "Temporal convolutional network: the neural network that reads each part's sensor history and predicts its remaining life.",
  "Semi-supervised": "Trained on many simulated machines where failures are known for only some of them.",
  "Ride-through": "Energy kept in the battery so the cell can finish its work through a mains outage.",
  "Demand response": "Using less grid power when the grid operator asks, in exchange for a lower price.",
  "mV (colour sensor)": "The colour sensor gives a voltage in millivolts that depends on how bright the cookie is - it is a brightness reading, not a colour.",
  "Autoencoder": "A network trained to rebuild images of good cookies only. What it rebuilds badly is unusual - it needs no defect labels.",
  "Drift": "The line's conditions moving away from what the models were trained on (light, lamp colour, belt wear). The autoencoder's error rises before the classifier's answers go wrong.",
  "Escape": "A defective cookie the inspection passed as good - the costly mistake.",
  "False reject": "A good cookie the inspection threw out - wasted product.",
  "Simulated": "Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'.",
};

export const GUIDE: Record<string, PageGuide> = {
  overview: {
    title: "Overview",
    what: "The cell at a glance: where the current order is, what each unit is doing, what costs time and what needs maintenance next.",
    read: [
      "The time slider at the top plays the 12-cookie order; every card follows it.",
      "The machine-age slider ages the parts; the PM switch shows them with and without preventive maintenance.",
      "The links on the cards (details →, planner →, alarms →) open the page behind each one.",
    ],
    sections: [
      ["Key figures", "Order progress, cookies per hour, OEE, running units, component health and the worst part, for the time and age you have chosen."],
      ["Production timeline", "A Gantt chart of the order: each unit's jobs along the time axis, with the current time marked."],
      ["Units now", "The step every unit's state machine is in at the chosen time."],
      ["Next maintenance", "The parts closest to their warning at the chosen machine age, and how many shifts they have left."],
      ["Downtime by cause (U5 fault matrix)", "How much time each fault from the commissioning tests costs when it happens once."],
      ["Unit utilisation", "The share of the order each unit is busy: the highest bar is the bottleneck."],
    ],
    source: "The PLC program's run of the order (Upgrade 4), commissioning (Upgrade 5) and the wear model (Upgrade 6).",
    terms: ["OEE", "Order time (makespan)", "Shift", "Health index (HI)", "PM", "Gantt chart", "Simulated"],
  },
  production: {
    title: "Production",
    what: "The order in detail: every job of every unit, how far each flavour is, and why the PLC uses the dispatch policy it does.",
    read: [
      "Play or drag the time slider and watch the Gantt chart and the unit steps move together.",
      "In the policy table, a lower order time is better; 'deadlock' means that policy can get stuck.",
    ],
    sections: [
      ["Gantt: the 12-cookie order, PLC policy", "Each unit's jobs over time under the chosen policy; waiting shows as gaps."],
      ["Units and their current step", "The step and job of each unit at the chosen time, as the PLC sees it."],
      ["Order by flavour", "How many cookies of each flavour are baked, sorted and back in the rack."],
      ["Dispatch policies (measured)", "Each policy's order time, checked over every possible timing; the one in use is highlighted."],
    ],
    source: "The PLC orchestration model and its exhaustive check of every completion order (Upgrade 4).",
    terms: ["Order time (makespan)", "Gantt chart", "Policy", "Deadlock"],
  },
  quality: {
    title: "Quality & trace",
    what: "Every cookie's record: which mould carried it, where the RFID heads read it, its colour reading and whether it matched the order.",
    read: [
      "Each row is one cookie; click it for the times and readings along its way.",
      "'verified' means the colour sensor's reading put the cookie in the flavour the order asked for.",
    ],
    sections: [
      ["Records", "One line per cookie: flavour, mould, RFID reads, colour sensor reading in mV, and the verdict."],
    ],
    source: "The traceability design of Upgrade 4: RFID read points on the HBW belt and the sorting line's colour sensor.",
    terms: ["mV (colour sensor)"],
  },
  vision: {
    title: "Vision QC",
    what: "The inspection camera's live feed: every cookie photographed, judged by the CNN and the autoencoder, and checked against the truth the simulation knows.",
    read: [
      "Watch the live camera: the image, the CNN's answer and decision, and the autoencoder's error map (hot = not as a good cookie looks).",
      "The KPIs and the confusion matrix say how right the CNN is over the last 50 cookies; escapes are defects it let through.",
      "Change the conditions (ageing light, a warmer lamp, a worn belt) and watch the drift chart rise before the CNN's answers go wrong.",
      "With the 3D twin open in another tab, the feed photographs the twin's own cookies.",
    ],
    sections: [
      ["Live camera", "The latest cookie: camera image, autoencoder error map, truth, the CNN's answer and the line's decision, and a strip of recent cookies."],
      ["The line", "Run or pause, the conditions, the defect rate the simulation injects and the line's speed."],
      ["Confusion (last 50)", "Truth against the CNN's answer for each condition: everything off the diagonal is a mistake."],
      ["Drift", "The autoencoder's error on normal-looking cookies against its training baseline; above ×2 the line no longer looks like training."],
      ["The camera", "Where it is mounted in the colour hood, its lens and trigger, and the mount's checks against the model."],
      ["The models, tested offline", "The CNN and the autoencoder on held-out images like training and on unseen conditions."],
    ],
    source: "Upgrade 15: the camera mount (vision/mount.py), the CNN (vision/train.py) and the autoencoder (vision/autoencoder.py), run in the browser on images drawn by the renderer port.",
    terms: ["Simulated", "Drift", "Autoencoder", "Escape", "False reject"],
  },
  alarms: {
    title: "Alarms",
    what: "Every alarm the PLC can raise, and how the machine reacted when each fault was injected into the twin.",
    read: [
      "Fault matrix: each injected fault, the alarm it raised, how quickly, and whether the reaction was right ('pass').",
      "Alarm list: the catalogue an operator would see, with cause, reaction and recovery for each code.",
    ],
    sections: [
      ["Fault matrix (commissioned)", "Seven faults injected into the virtual machine - stuck switch, motor stall, lost vacuum, E-stop and more - and the result of each."],
      ["Alarm list", "Every watchdog alarm in the program: its code, the step it guards, and what to do."],
    ],
    source: "Virtual commissioning of the PLC program against the twin (Upgrade 5).",
    terms: ["Watchdog"],
  },
  health: {
    title: "Health",
    what: "How worn each part is at the chosen machine age, and how the twin detects wear before a part fails.",
    read: [
      "Move the machine-age slider: health falls as parts wear. Green is healthy, amber is warned, red is failing.",
      "Switch PM off to see the same machine without preventive maintenance.",
      "Click a part for its wear curve, its failure limit and when it was warned.",
    ],
    sections: [
      ["Component health", "The health index of each wearing part at the chosen age."],
      ["(the selected part)", "Its wear curve, the soft limit and trend warnings, and its remaining life."],
      ["Detect-only failure modes", "Faults that can only be detected when they happen (not predicted), and the alarm that catches each."],
    ],
    source: "The condition-monitoring model of Upgrade 6: a wear law per part, a noisy measurement, smoothing and two warnings.",
    terms: ["Health index (HI)", "RUL", "Shift", "PM"],
  },
  maintenance: {
    title: "Maintenance",
    what: "The work orders the health warnings create, and the spare parts to keep in stock.",
    read: [
      "A work order appears when a part warns; it is done at the next shift change, or at once if the part will not last that long.",
      "The spare-parts table says how many of each part to stock and why.",
    ],
    sections: [
      ["Work orders", "Each order: the part, why it was raised, when it is due and what it costs in time."],
      ["Spare parts (U7)", "Stock per part from its life and lead time, so a warned part can always be replaced."],
    ],
    source: "Upgrade 6 (warnings) and Upgrade 7 (lifecycle and spares).",
    terms: ["PM", "Shift", "RUL"],
  },
  ai: {
    title: "AI maintenance",
    what: "A neural network that predicts each part's remaining life from its sensor history, tested on machines it never saw, and running here in your browser.",
    read: [
      "Start with the scores: how often it warned in time, and how much part life it threw away.",
      "The network advises; the rules of the Health page still decide. Together they warn early and waste less.",
      "The showcase compares the network's prediction with the truth on one unseen machine.",
    ],
    sections: [
      ["Scored on unseen machines", "Warnings in time, false alarms and wasted life, against the rule-based warnings."],
      ["The decision, tuned properly", "The alarm threshold chosen on validation data: the trade-off between warning late and renewing early."],
      ["Per component", "The same scores for each part."],
      ["How it was trained", "The network type, the data and the training method."],
      ["Training loss", "How the error fell while it learned."],
      ["Running here, in the browser", "The network applied to the simulated month, live in this page."],
      ["An unseen test machine", "Predicted against true remaining life for one machine the network never saw."],
    ],
    source: "Upgrade 8: a TCN trained on a fleet of simulated machines, exported to ONNX and to the browser.",
    terms: ["RUL", "TCN", "Semi-supervised", "Health index (HI)"],
  },
  month: {
    title: "Month",
    what: "A whole simulated month of production - orders, faults, wear and maintenance - and what it says.",
    read: [
      "Read the insights first; each one points to the chart that shows it.",
      "Hover a bar or a cell for the numbers of that day or hour; click a note to expand it.",
      "The CSV downloads hold the same data for your own analysis.",
    ],
    sections: [
      ["Insights from the month's data", "The findings: what cost the most, what maintenance saved, where the trends are."],
      ["Good cookies per day, and OEE", "Daily output; amber days had planned maintenance."],
      ["Where the time went", "Planned time split into producing, faults, maintenance and idle."],
      ["Orders started per hour", "When in the day orders arrived (day × hour)."],
      ["The counterfactual month", "The same month without preventive maintenance: what failed and what it cost."],
      ["Component sensor traces", "Colour sensor mV per order, actuator current, compressor duty and vacuum losses - the signals wear shows in."],
      ["Hours per state, per unit", "RUN, HELD, IDLE and FAULT hours from each unit's state machine."],
      ["Downloads (CSV) and event log", "Every order, event and sensor reading of the month."],
    ],
    source: "The month simulator (month.py) driven by the wear model of Upgrade 6 and the maintenance of Upgrade 7.",
    terms: ["OEE", "Shift", "PM", "mV (colour sensor)", "Simulated"],
  },
  throughput: {
    title: "Throughput",
    what: "How the same machine was made faster by changing only its program, and what each change is worth.",
    read: [
      "Compare the two Gantt rows: before (Upgrade 7) and after (Upgrade 10), on one time scale.",
      "The critical path shows which jobs set the order time; the ablation shows each improvement's own value.",
    ],
    sections: [
      ["What the study says", "The headline: order time before and after, and why."],
      ["The same order, before and after", "Both programs' runs, step by step, from virtual commissioning."],
      ["Where the time went: the critical path", "The chain of jobs that decides the order time."],
      ["Ablation", "Each improvement switched off alone: the time it saves."],
      ["The VGR's tours", "The arm's blended paths, flown just above the height the collision sweep proves clear."],
      ["With a real bake", "How the oven starts to limit the order when baking takes longer."],
      ["OEE, same shift definition", "OEE before and after, measured the same way."],
      ["Proofs the faster program still passes", "Deadlock freedom and collision checks, re-run for the new program."],
    ],
    source: "Upgrade 10's throughput study, measured by virtual commissioning.",
    terms: ["Order time (makespan)", "Gantt chart", "Critical path", "Ablation", "OEE", "Deadlock"],
  },
  energy: {
    title: "Energy & grid",
    what: "The cell behind a small microgrid - solar panels, a battery and an energy manager - over the simulated month.",
    read: [
      "Pick a day to see its power flows hour by hour.",
      "Compare the three ways of powering the cell on cost, grid use and outages survived.",
    ],
    sections: [
      ["What the month says", "The results: energy, cost, outages ridden through."],
      ["Power flows on day …", "Solar, battery, grid and load for one day, as the energy manager planned them."],
      ["Three ways to power the cell", "Grid only, solar + battery, and with the energy manager, side by side."],
      ["Power quality", "Every mains event (dips, outages) and what the inverter made of it."],
      ["Power-asset health", "The power supply's capacitors and the cabinet air filter, which wear with heat and dust."],
      ["PV soiling, battery and contactors", "Panel cleaning, battery ageing and switching."],
      ["Economics, honestly", "What it costs and saves, with the assumptions stated."],
      ["Standards the design follows", "The norms the microgrid design is checked against."],
    ],
    source: "Upgrade 9's microgrid model (grid.py), simulated, not measured.",
    terms: ["Ride-through", "Demand response", "Simulated"],
  },
  security: {
    title: "OT security",
    what: "The cell's network split into IEC 62443 zones, and what happens when attacks are replayed on the twin.",
    read: [
      "Start with the zone picture: which devices trust each other, and the only paths (conduits) between zones.",
      "For each attack, compare: no protection, detection only, and the Upgrade 11 design.",
    ],
    sections: [
      ["What the analysis says", "The findings in short."],
      ["Zones and conduits", "Each zone, its target security level, and the allowed paths between zones."],
      ["Attacks, replayed on the twin", "Each attack's effect on production without and with the protections."],
      ["Conduit C1: the Modbus allow-list", "Every message the PLC may send to the I/O nodes, generated from the PLC program itself."],
      ["Conduit C3: what the energy manager may write", "The few inverter settings the energy manager may change."],
      ["Security levels", "Where the devices fall short of SL 2, and what covers the gap."],
      ["Safety stays off the network", "Why the E-stops and door locks have no network interface."],
      ["HMI and the signed program manifest", "What an operator may change, and how the PLC refuses an altered program."],
    ],
    source: "Upgrade 11's security design (security.py): a model-based assessment, not a penetration test.",
    terms: ["Zone / conduit", "SL", "Allow-list"],
  },
  hardening: {
    title: "Defence in depth",
    what: "Where the machine no longer trusts its own program: hardwired interlocks, and the Upgrade 11 findings re-run.",
    read: [
      "Each jog rule is hardwired only where the machine already has the switch it needs.",
      "The re-run shows each finding closed on the hardened machine, and what it cost.",
    ],
    sections: [
      ["What changed", "The hardening in short."],
      ["Every jog rule", "Which manual-move rules are now relay contacts instead of program logic, and why the others are not."],
      ["The U11 findings, re-run", "Each earlier finding against the hardened machine."],
      ["Energy: the trade-off", "What keeping a ride-through reserve costs in demand response."],
      ["New parts", "The interlock relays on each I/O node's rail and the standstill monitor in the cabinet."],
    ],
    source: "Upgrade 12 (hardening.py).",
    terms: ["Ride-through", "Demand response"],
  },
  engineering: {
    title: "Engineering",
    what: "The mechanical engineering behind the machine: how precisely it positions, its tolerances, stiffness and service access.",
    read: [
      "Each table compares what the design achieves with what it must achieve; green is within the limit.",
    ],
    sections: [
      ["Positioning accuracy (U5)", "How far each axis overshoots its target at the PLC's task cycle, against what is allowed."],
      ["Tolerance chains, worst case (U7)", "Stacked part tolerances at their worst combination, before and after Upgrade 7: a negative worst case means parts can collide or miss."],
      ["Structure dynamics (U7)", "How far each frame member bends under load (δ) and its lowest natural frequency (f₁): a stiff member vibrates fast and little."],
      ["Service access (U7)", "How far a technician must reach through each door to the part; red bars are beyond the allowed reach."],
    ],
    source: "Upgrades 5 and 7.",
    terms: [],
  },
  validation: {
    title: "Validation",
    what: "How the project checks itself: every variant re-built, the plant varied, and defects planted to prove the checks can fail.",
    read: [
      "Regression: every upgrade's machine is re-exported and must give the same result.",
      "Mutation tests: each planted defect must be caught; one that survives would be a gap in the proofs.",
    ],
    sections: [
      ["Regression: every variant re-exported", "Each upgrade's export rebuilt and compared with its recorded fingerprint."],
      ["Robustness: ±20 % on every plant step", "Random plants with every step time varied; no false alarms allowed."],
      ["Data products", "Checks on the published data: the network's ONNX and browser copies against the original, the month and grid files, the tests and the web build."],
      ["Mutation tests", "A defect planted in each proof, and which check caught it."],
      ["Failing checks", "Anything currently failing (normally empty)."],
    ],
    source: "validate.py, which re-proves every variant.",
    terms: ["Mutation test"],
  },
  data: {
    title: "Data",
    what: "Where the dashboard's data would come from on a real machine: the MQTT topics and the I/O register map.",
    read: [
      "Topics: the path from the PLC through MQTT and a historian to this page.",
      "Register map: every PLC signal's Modbus address on the remote I/O nodes.",
    ],
    sections: [
      ["Topics (PLC → MQTT → historian → this page)", "The message topics the page would read on real hardware."],
      ["Register map (U5)", "Each signal, its node and its Modbus register."],
    ],
    source: "Upgrade 5's register map; the live MQTT/Sparkplug namespace is in the twin's 'MQTT Sparkplug · UNS' panel (Upgrade 14).",
    terms: [],
  },
};

/** The one-line explanation of a card, found by its title (titles may carry extra text). */
export function cardHelp(page: string, title: string): string | undefined {
  const g = GUIDE[page];
  if (!g) return undefined;
  const t = title.toLowerCase();
  return g.sections.find(([s]) => t.startsWith(s.toLowerCase().replace(/ …$/, "")) || s.toLowerCase().startsWith(t))?.[1];
}
