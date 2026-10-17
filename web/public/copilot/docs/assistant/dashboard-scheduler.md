# Dashboard: Learned scheduler

Dashboard group: Analyse. Page id: `scheduler`.

Whether a learning scheduler finds a faster order than the PLC's priority list without ever risking a deadlock.

## In brief

Whether a learning scheduler finds a faster order than the PLC's priority list without ever risking a deadlock.

## How to read it

1. The headline: order time against the PLC, and the deadlocks with and without the shield.
2. The two Gantt charts share one time axis; hover a block for its job and slot.
3. The test runs use identical random job times for every scheduler, so the comparison is fair run by run.

## Sections

### The same order, two schedulers

The PLC's schedule and the scheduler's, on one time axis.

### Order time on random job times

Fastest to slowest run, and the mean, for every scheduler.

### Run by run against the PLC

Seconds saved in each test run with identical job times.

### Learning, and what the shield blocked

Order time while the agent learned; hover for how many actions the shield blocked.

### Where the moulds go

The rack slots each scheduler stores into: the gain comes from shorter crane travel.

## Where the numbers come from

sched_rl.py: Q-learning and a rollout scheduler over the PLC's job choices, behind a shield proven by exhaustive exploration.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Deadlock**: A state where every unit waits for another and nothing can move. The policies are checked so this can never happen.
- **Policy**: The rule the PLC uses to decide which cookie or mould to move next. Different policies give different order times.
- **Gantt chart**: One row per unit, one block per job, along a time axis: shows what runs in parallel and what waits.
- **Simulated**: Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
