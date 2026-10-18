# Dashboard: Carbon per cookie

Dashboard group: Analyse. Page id: `carbon`.

How many grams of CO₂e each good cookie costs, where they come from, and what each lever saves.

## In brief

How many grams of CO₂e each good cookie costs, where they come from, and what each lever saves.

## How to read it

1. The headline figures: grams per cookie and per order, how much of it is the oven and the cell standing idle, and an estimate with a real bake.
2. The levers re-run the same month through the same energy manager, one change at a time.
3. Hover the hourly chart to see the grid's carbon intensity at each hour.

## Sections

### Where a cookie's carbon comes from

The month's emissions shared out over what drew the power; red is drawn whether or not a cookie is made, amber is the oven held hot.

### What each lever does

Grams per cookie with each change added: PV and battery, sleep when idle, a carbon-aware battery, the faster program.

### The day, hour by hour

Load, PV and grid import through an average day, and the grid's carbon intensity by hour.

### Per day

Grams per cookie each day, coloured by the weather.

## Where the numbers come from

The microgrid month (grid.py) allocated by carbon.py.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Simulated**: Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
