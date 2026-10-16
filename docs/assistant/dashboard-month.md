# Dashboard: Month

Dashboard group: Analyse. Page id: `month`.

A whole simulated month of production - orders, faults, wear and maintenance - and what it says.

## How to read it

1. Read the insights first; each one points to the chart that shows it.
2. Hover a bar or a cell for the numbers of that day or hour; click a note to expand it.
3. The CSV downloads hold the same data for your own analysis.

## Sections

### Insights from the month's data

The findings: what cost the most, what maintenance saved, where the trends are.

### Good cookies per day

Daily output against the month's average; amber = planned maintenance that night, red = a failure. The axis starts near the lowest day so differences show.

### OEE per day

Daily OEE against the month's figure; hover for the value.

### Where the time went

Planned time split into producing, faults, maintenance and idle.

### Orders started per hour

When in the day orders arrived (day × hour).

### The counterfactual month

The same month without preventive maintenance: what failed and what it cost.

### Component sensor traces

Colour sensor mV per order, actuator current, compressor duty and vacuum losses - the signals wear shows in.

### Hours per state, per unit

RUN, HELD, IDLE and FAULT hours from each unit's state machine.

### Downloads (CSV) and event log

Every order, event and sensor reading of the month.

## Where the numbers come from

The month simulator (month.py) driven by the wear model and the maintenance plan.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **OEE**: Overall equipment effectiveness = availability × performance × quality. 100 % means making only good parts, as fast as possible, with no stops.
- **Shift**: 8 hours of production. Machine age and remaining life are counted in shifts.
- **PM**: Preventive maintenance: renewing a part when it warns, before it fails. The PM switch shows the machine with and without it.
- **mV (colour sensor)**: The colour sensor gives a voltage in millivolts that depends on how bright the cookie is - it is a brightness reading, not a colour.
- **Simulated**: Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
