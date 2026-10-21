# Dashboard: Quality & trace

Dashboard group: Operate. Page id: `quality`.

Every cookie's record: which mould carried it, where the RFID heads read it, its colour reading and whether it matched the order.

## In brief

Every cookie's record: which mould carried it, where the RFID heads read it, its colour reading and whether it matched the order.

## How to read it

1. Each row is one cookie; click it for the times and readings along its way.
2. 'verified' means the colour sensor's reading put the cookie in the flavour the order asked for.

## Sections

### Records

One line per cookie: its journey (rack → belt → oven → bin) with the current stage lit, the RFID reads, its bake on a shared time axis, and the colour verdict.

## Where the numbers come from

The PLC program's traceability design: RFID read points on the HBW belt and the sorting line's colour sensor.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **mV (colour sensor)**: The colour sensor gives a voltage in millivolts that depends on how bright the cookie is - it is a brightness reading, not a colour.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
