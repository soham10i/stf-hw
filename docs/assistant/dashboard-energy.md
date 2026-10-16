# Dashboard: Energy & grid

Dashboard group: Analyse. Page id: `energy`.

The cell behind a small microgrid - solar panels, a battery and an energy manager - over the simulated month.

## How to read it

1. Pick a day to see its power flows hour by hour.
2. Compare the three ways of powering the cell on cost, grid use and outages survived.

## Sections

### What the month says

The results: energy, cost, outages ridden through.

### Power flows on day

Solar, battery, grid and load for one day; hover to read every flow.

### Three ways to power the cell

Grid only, PV only and PV + battery + energy manager on cost, CO₂, peak import and self-sufficiency.

### Energy per day

PV, load and grid import for each day: import rises on dull days.

### Power quality

Every mains event and whether the cell rides through; hover a result for why.

### Power-asset health

The power supply's capacitors and the cabinet air filter, which wear with heat and dust.

### PV soiling

Panel performance against the irradiance sensor, and the cleanings.

### Battery and contactors

Battery ageing and contactor switching at this month's rate.

### Economics, honestly

Capital cost by item, payback and production protected.

### Standards the design follows

The norms the microgrid design is checked against.

## Where the numbers come from

The microgrid model (grid.py), simulated, not measured.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Ride-through**: Energy kept in the battery so the cell can finish its work through a mains outage.
- **Demand response**: Using less grid power when the grid operator asks, in exchange for a lower price.
- **Simulated**: Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
