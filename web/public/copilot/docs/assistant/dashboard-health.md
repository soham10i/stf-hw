# Dashboard: Health

Dashboard group: Maintain. Page id: `health`.

How worn each part is at the chosen machine age, and which part needs attention first.

## In brief

How worn each part is at the chosen machine age, and which part needs attention first.

## How to read it

1. Drag the machine-age slider: health falls as parts wear. Green healthy, amber warned, red failed.
2. Switch PM off to see the machine run to failure.
3. Click a part (runway row or map row) to see its signal; hover any chart to read values.

## Sections

### Remaining life runway

For each part, from now: green until it warns, amber from the warning until it fails. The amber length is your window to service it. Switch the horizon to zoom.

### Not predictable

Faults with no gradual sign, and the check that covers each.

### Health map

Every part (rows) over the machine's whole life (across), coloured by health. With PM on, each stripe is a renewal; the white line is now. Hover for the value.

### (the selected part)

Its smoothed signal against the soft and failure limits. Hover to read the health index, the true time to failure and the trend's estimate.

### About this part

Warning lead time, false warnings, uses so far and the sensor it is measured with.

## Where the numbers come from

The condition-monitoring model. The theory is under Docs → Hardware degradation.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Health index (HI)**: 100 = as new, 0 = it fails now. Computed from how far a part's measured behaviour has drifted toward its failure limit.
- **RUL**: Remaining useful life: how many shifts (or orders) a part has left before it fails.
- **Shift**: 8 hours of production. Machine age and remaining life are counted in shifts.
- **PM**: Preventive maintenance: renewing a part when it warns, before it fails. The PM switch shows the machine with and without it.
- **EWMA**: Exponentially weighted moving average: each new reading moves the smoothed value a small step (2 %) towards it, so noise averages out but a real trend shows.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
