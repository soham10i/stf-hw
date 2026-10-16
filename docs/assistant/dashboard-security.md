# Dashboard: OT security

Dashboard group: Analyse. Page id: `security`.

The cell's network split into IEC 62443 zones, and what happens when attacks are replayed on the twin.

## In brief

The cell's network split into IEC 62443 zones, and what happens when attacks are replayed on the twin.

## How to read it

1. Start with the zone picture: which devices trust each other, and the only paths (conduits) between zones.
2. For each attack, compare: no protection, detection only, and the OT security design.

## Sections

### What the analysis says

The findings in short.

### Zones and conduits

Each zone, its target security level, and the allowed paths between zones.

### Attacks, replayed on the twin

Each attack's effect without and with the protections; for the spoofed sensor, which steps catch a lie.

### Conduit C1: the Modbus allow-list

Every message the PLC may send to the I/O nodes, generated from the PLC program itself.

### Conduit C3: what the energy manager may write

The few inverter settings the energy manager may change.

### Security levels

Capability (red) against target SL 2 (green) per device and requirement; hover for the countermeasure.

### Safety stays off the network

Why the E-stops and door locks have no network interface.

### HMI: what an operator may write

The tags an operator may change, and who.

### New alarms

The security alarms this upgrade adds.

### Signed program manifest

The hashes the PLC checks before it runs a program.

## Where the numbers come from

The security design (security.py): a model-based assessment, not a penetration test.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Zone / conduit**: IEC 62443 groups devices into zones of equal trust; a conduit is the only allowed path between two zones.
- **SL**: Security level (IEC 62443), 1 to 4: how strong an attacker a zone must withstand. The cell targets SL 2.
- **Allow-list**: The complete list of network messages that may pass a conduit. Anything not on it is dropped.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
