# Dashboard: Engineering

Dashboard group: Engineer. Page id: `engineering`.

The mechanical engineering behind the machine: how precisely it positions, its tolerances, stiffness and service access.

## In brief

The mechanical engineering behind the machine: how precisely it positions, its tolerances, stiffness and service access.

## How to read it

1. Each table compares what the design achieves with what it must achieve; green is within the limit.

## Sections

### Positioning accuracy

Each axis's stopping error (blue) against what is allowed (green).

### Tolerance chains

Clearance left when every tolerance stacks the wrong way; red would mean parts can collide or miss. Hover for the value before the lifecycle changes.

### Structure

Each frame member's lowest natural frequency against the minimum the drives need.

### Service access

How far a technician must reach through each door to the part; red bars are beyond the allowed reach.

## Where the numbers come from

Commissioning and the lifecycle design.

Every number is simulated from the twin's models, not measured on a real machine.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
