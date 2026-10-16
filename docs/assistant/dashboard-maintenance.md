# Dashboard: Maintenance

Dashboard group: Maintain. Page id: `maintenance`.

When each part is next serviced and why, how the work spreads over the days, and the spares to stock.

## How to read it

1. Each row of the schedule is a part; each diamond a service. Colour says why: preventive, warned or failed.
2. Switch PM off: the diamonds become breakdowns (×), the stops PM prevents.
3. Click a row for its interval and service door.

## Sections

### Service schedule · next 30 days

Every service ahead, part by part, plus the routine PM visit.

### Workload · services per day

How many services fall on each day; busy days are highlighted.

### Work orders

The next six jobs, soonest first.

### Spare parts

Wear parts used per year against stock, and the one-off breakdown spares.

## Where the numbers come from

Condition monitoring (warnings) and the lifecycle design (spares).

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **PM**: Preventive maintenance: renewing a part when it warns, before it fails. The PM switch shows the machine with and without it.
- **Shift**: 8 hours of production. Machine age and remaining life are counted in shifts.
- **RUL**: Remaining useful life: how many shifts (or orders) a part has left before it fails.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
