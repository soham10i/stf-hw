# Dashboard: Throughput

Dashboard group: Analyse. Page id: `throughput`.

How the same machine was made faster by changing only its program, and what each change is worth.

## In brief

How the same machine was made faster by changing only its program, and what each change is worth.

## How to read it

1. Compare the two Gantt rows: before and after, on one time scale.
2. The critical path shows which jobs set the order time; the ablation shows each improvement's own value.

## Sections

### The same order, before and after

Both programs' runs, step by step, from virtual commissioning.

### Where the time went: the critical path

The chain of jobs that decides the order time.

### Ablation

The order time with each improvement switched off; hover a bar for cycle time and the busiest unit.

### What each measure is worth

Seconds each improvement saves alone and in the full set; they differ because the measures interact.

### The VGR's tours

Each tour's time before and after the blended paths.

### With a real bake

Order time against bake time: the longer the bake, the less the faster loop matters.

### OEE, before and after

Availability, performance, quality and OEE, measured the same way.

### Proofs the faster program still passes

Deadlock freedom and fault recovery, re-run for the new program.

## Where the numbers come from

The throughput study, measured by virtual commissioning.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Order time (makespan)**: How long the whole 12-cookie order takes from the first move to the last cookie stored.
- **Gantt chart**: One row per unit, one block per job, along a time axis: shows what runs in parallel and what waits.
- **Critical path**: The chain of jobs that sets the order time: speeding up anything off this chain does not shorten the order.
- **Ablation**: Switching off one improvement at a time to measure what each one is worth on its own.
- **OEE**: Overall equipment effectiveness = availability × performance × quality. 100 % means making only good parts, as fast as possible, with no stops.
- **Deadlock**: A state where every unit waits for another and nothing can move. The policies are checked so this can never happen.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
