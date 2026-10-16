# Dashboard: Hardware degradation

Dashboard group: Docs. Page id: `docs-degradation`.

The theory behind the Health page: how wear is modelled, measured, smoothed and turned into warnings, running live.

## How to read it

1. Pick a part: its own wear law runs on the chart, one life in about 30 seconds.
2. The numbered circles on the chart match the numbered equations below.
3. Switch to 'healthy' to see that no warning comes; raise the noise to see why smoothing matters.

## Sections

### Live

Measured signal, true wear, smoothed signal, the trend and both limits, cycle by cycle.

### Steps 1-10

Each modelling step as an equation, with its source and its value for the chosen part.

### Every part: closed form vs simulation

The equations predict when each part warns; the simulation agrees.

### References

The standards, papers and books each step comes from.

## Where the numbers come from

health.py and health_theory.py; the same model ported to the browser.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Health index (HI)**: 100 = as new, 0 = it fails now. Computed from how far a part's measured behaviour has drifted toward its failure limit.
- **RUL**: Remaining useful life: how many shifts (or orders) a part has left before it fails.
- **EWMA**: Exponentially weighted moving average: each new reading moves the smoothed value a small step (2 %) towards it, so noise averages out but a real trend shows.
- **Shift**: 8 hours of production. Machine age and remaining life are counted in shifts.
- **Simulated**: Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
