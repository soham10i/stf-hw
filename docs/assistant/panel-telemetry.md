# Panel: Telemetry

Live readings of the twin, sampled 8 times a second.


## In brief

Live readings of the twin, sampled 8 times a second.

## Sensors

Lights at the top: on (lit) or off. The warehouse light barriers (I2, I3), the robot's vacuum
switch (vacuum above 50 %), *oven heating* (the elements are on), *oven at temperature* (the
chamber is at 170 C or more) and the sorting line's vacuum.

## Machine cards

| Card | Readings |
|---|---|
| Crane | travel, lift, fork (Ausleger) and belt position, in mm |
| Robot arm | swivel (degrees), reach and plunge (mm), vacuum (%), what it is carrying |
| Oven & sorting | chamber temperature from the thermocouple (amber above 240 C), whether the elements are heating, oven tray (slider), door and oven gripper (Sauger) position, turntable angle, bake progress (%), position along the belt path |

The tag next to the title is the current cycle: the slot the mould comes from and goes to, and
how far the cycle is.

## Physics kernel

Folded by default. When the live API runs, its own simulation of the original 3 x 3 machine:
every joint with its tracking error (red above 1 mm), the motors' current, health and phase, and
three manual commands (Retrieve B2, Store B2, Home crane). Without the API the section is absent.
