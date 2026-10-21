# Dashboard: Oven process

Dashboard group: Analyse. Page id: `process`.

The bake as heat and water: the oven heating and holding, a cookie baking through its thickness, four ways to end a bake, and what a real bake does to capacity and energy.

## In brief

The bake as heat and water: the oven heating and holding, a cookie baking through its thickness, four ways to end a bake, and what a real bake does to capacity and energy.

## How to read it

1. The headline figures: cookies right first time with the best way of ending a bake, cookies an hour with a real bake, the heat per cookie.
2. One cookie in the oven: the centre waits near 100 °C while the water boils off; the colour comes last and fast.
3. Four ways to end a bake, run over the same shifts: compare how many cookies come out right, and which dough each one gets wrong.

## Sections

### What the model found

The findings in short: quality, capacity, energy and the microgrid.

### One cookie in the oven

Surface, centre and bottom temperatures, the water left and the browning index of a nominal cookie, with when it is done and when it reaches its colour.

### The oven heating up

From switch-on to 180 °C: the elements, the air, the thermocouple and the walls, and the heater's duty.

### Four ways to end a bake

A fixed timer, the PLC's model of the cookie (soft sensor), the camera correcting the colour, and dough sensors: cookies right, underbaked and burnt.

### Each cookie of one shift

Every cookie's browning against the right band, per policy, with the dough lots marked.

### The oven through a shift

The chamber air and the cookie through the door openings of a shift.

### What a real bake does to capacity

The 12-cookie order with the 2 s lamp and with a real bake, and how many ovens the rest of the cell could feed.

### Where the heat goes

One shift's heat: walls, door, vent, the open mouth, the tray outside and the steam.

### Checks

The model's proofs, the faults they catch, and every parameter with its source.

## Where the numbers come from

The oven and cookie model (stf-cad/hbw/bake.py), from the oven's parts (oven_model.py) and the order's door openings (control.py).

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Soft sensor**: A quantity no sensor measures, computed from a model fed by the sensors there are: here the cookie's centre temperature, water and colour, from a model of the oven run on the thermocouple.
- **Run-to-run control**: Correcting the next run from how the last one came out: here the camera's colour reading moves the next cookie's colour target.
- **Browning index**: 0 = raw dough, 1 = as dark as it gets. It grows faster the hotter and drier the surface (Maillard reactions); 0.35-0.65 is the right colour.
- **Simulated**: Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
