# Panel: Safety & security

Two sub-tabs. While *OT security* is open, the 3D view shows the network zones instead of the
hazard zones.


## In brief

Two sub-tabs.  While *OT security* is open, the 3D view shows the network zones instead of the hazard zones.

## Machine safety (ISO 12100, ISO 13849-1)

7 hazards, each with its required performance level (PLr, a-e; d is the highest here):

| Id | Hazard | PLr |
|---|---|---|
| H1 | warehouse stacker crane | d |
| H2 | robot swivel arm | d |
| H3 | oven tray and door | b |
| H4 | oven turntable, saw and gripper | c |
| H5 | oven pusher | b |
| H6 | sorting ejectors | b |
| H7 | stored air | b |

Hover a row for what the hazard is and its S/F/P rating. 4 safety functions:

| Id | Function | Category | PL | Devices |
|---|---|---|---|---|
| SF1 | Emergency stop | 3 | d | ES1-ES3 -> safety relay K0 -> contactors K1/K2 + valve Y1; stop category 0 |
| SF2 | Guard interlock with locking | 3 | d | door switches SA-SC -> K0 -> K1/K2 + Y1; doors locked until standstill (ISO 14119) |
| SF3 | Safe exhaust | 3 | b | K0 -> Y1 (monitored): air supply cut, cylinders vented |
| SF4 | Monitored reset | 2 | c | S3 -> K0: no restart without a deliberate reset |

**Proven** ticks: *reach* (every hazard zone at least 20 mm inside the guard), *fit* (no guard part
touches a module), *logic* (every combination of safety inputs checked: motion only with all
E-stops released, all doors closed and locked and a reset; any single-channel fault blocks it; a
door unlocks only at standstill), *air* (every cylinder fed only through the safe exhaust valve).

Why guard locking, not a light curtain: it removes the need for a measured stopping time. The PL
achieved still needs the devices' MTTFd, DCavg and CCF from their datasheets.

## OT security (IEC 62443)

Zones Z0-Z5: Z0 hardwired safety (no network), Z1 cell control (the PLC and the four I/O nodes,
SL 2), Z2 supervisory, Z3 energy, Z4 DMZ, Z5 enterprise and internet (untrusted). Conduits between
zones carry only what is on the allow-list (25 rules for 70 program accesses). Three writable
signals the program never uses are flagged.

**Replay an attack**: pick one and compare the outcome with no protection, detection only, and the
protected design. Example: a rogue coil write is blocked at conduit C1 because the source is not
the PLC (port lock and static ARP). *Full page* opens the dashboard's security page.
