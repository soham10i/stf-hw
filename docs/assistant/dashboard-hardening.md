# Dashboard: Defence in depth

Dashboard group: Analyse. Page id: `hardening`.

Where the machine no longer trusts its own program: hardwired interlocks, and the OT security findings re-run.

## In brief

Where the machine no longer trusts its own program: hardwired interlocks, and the OT security findings re-run.

## How to read it

1. Each jog rule is hardwired only where the machine already has the switch it needs.
2. The re-run shows each finding closed on the hardened machine, and what it cost.

## Sections

### What changed

The hardening in short.

### Every jog rule

Steps each manual-move rule guards; green = now a relay contact, grey = no switch to wire it to, red = would block the program's own steps.

### The OT security findings, re-run

Each earlier finding against the hardened machine.

### Energy: what holding the reserve costs

Lowest battery charge and grid import in demand-response windows, before and after.

### New parts

The interlock relays on each I/O node's rail and the standstill monitor in the cabinet.

## Where the numbers come from

The hardened machine (hardening.py).

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Ride-through**: Energy kept in the battery so the cell can finish its work through a mains outage.
- **Demand response**: Using less grid power when the grid operator asks, in exchange for a lower price.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
