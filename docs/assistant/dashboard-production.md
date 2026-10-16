# Dashboard: Production

Dashboard group: Operate. Page id: `production`.

The order in detail: every job of every unit, how far each flavour is, and why the PLC uses the dispatch policy it does.

## How to read it

1. Play or drag the time slider and watch the Gantt chart and the unit steps move together.
2. In the policy table, a lower order time is better; 'deadlock' means that policy can get stuck.

## Sections

### Gantt: the 12-cookie order, PLC policy

Each unit's jobs over time under the chosen policy; waiting shows as gaps.

### Units and their current step

The step and job of each unit at the chosen time, as the PLC sees it.

### Order by flavour

How many cookies of each flavour are baked, sorted and back in the rack.

### Dispatch policies (measured)

Each policy's order time, checked over every possible timing; the one in use is highlighted.

## Where the numbers come from

The PLC orchestration model and its exhaustive check of every completion order.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Order time (makespan)**: How long the whole 12-cookie order takes from the first move to the last cookie stored.
- **Gantt chart**: One row per unit, one block per job, along a time axis: shows what runs in parallel and what waits.
- **Policy**: The rule the PLC uses to decide which cookie or mould to move next. Different policies give different order times.
- **Deadlock**: A state where every unit waits for another and nothing can move. The policies are checked so this can never happen.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
