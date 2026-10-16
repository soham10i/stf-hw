# Dashboard: Overview

Dashboard group: Operate. Page id: `overview`.

The cell at a glance: order progress, what each unit is doing, where efficiency is lost and what needs service next.

## How to read it

1. The time slider plays the order; every card follows it.
2. The machine-age slider and PM switch age the parts.
3. The links on the cards open the page behind each one.

## Sections

### Key figures

Order progress, cookies per hour, OEE, running units and fleet health.

### Production timeline

Each unit's jobs along the order; the line is now. Hover a legend entry for what a job does.

### Units now

Each unit's state and job at the chosen time; green border = running.

### OEE breakdown

Availability × performance × quality; the biggest loss is highlighted.

### Next maintenance

The five parts closest to failure: health index and shifts left.

### Downtime by fault

Time lost to each commissioning fault when it happens once.

### Unit utilisation

Share of the order each unit is busy; the bottleneck is highlighted.

## Where the numbers come from

The PLC program's run of the order, commissioning and the wear model.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **OEE**: Overall equipment effectiveness = availability × performance × quality. 100 % means making only good parts, as fast as possible, with no stops.
- **Order time (makespan)**: How long the whole 12-cookie order takes from the first move to the last cookie stored.
- **Shift**: 8 hours of production. Machine age and remaining life are counted in shifts.
- **Health index (HI)**: 100 = as new, 0 = it fails now. Computed from how far a part's measured behaviour has drifted toward its failure limit.
- **PM**: Preventive maintenance: renewing a part when it warns, before it fails. The PM switch shows the machine with and without it.
- **Gantt chart**: One row per unit, one block per job, along a time axis: shows what runs in parallel and what waits.
- **Simulated**: Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
