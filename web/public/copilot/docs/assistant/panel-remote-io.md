# Panel: Remote I/O

Each module has its own I/O node (Modbus TCP) beside its controller board, so only an Ethernet
line and a fused 24 V feed run to the cabinet instead of 34-way bundles.


## In brief

Each module has its own I/O node (Modbus TCP) beside its controller board, so only an Ethernet line and a fused 24 V feed run to the cabinet instead of 34-way bundles.

## I/O nodes

A bar per node and signal type (DI digital in, DO digital out, AI analogue in, CNT counter/encoder,
IOL IO-Link), filled by the share of channels used. Every signal of the wiring plan is on exactly
one channel, with at least 20 % of each type spare. Amber means a type is fuller than that.

| Node | Where | Slices |
|---|---|---|
| warehouse | its own plate | 2 x DI8, 2 x DO8, 3 counters, IO-Link 4 (the RFID heads) |
| robot | on the table, off every plate | DI8, 2 x DO8, 4 counters |
| oven | its own plate | 3 x DI8, 3 x DO8 |
| sorting | its own plate | DI8, DO8, AI2 (the colour sensor) |

## Drag chains

The moving cables ride in drag chains: crane travel, crane lift, robot plunge, robot reach. Each
row: fill (cable cross-section in the chain, at most the rule's limit) and whether the bend radius
is at least the cables' minimum (the chains use R 20 or R 12 against 10.5 mm). Hover for the
devices, conductors, length and stroke.

## Cabinet (EN 60204-1)

DIN-rail use (253.7 of 355 mm, 28.5 % free; at least 20 % is required). The PLC, Ethernet switch
and 4-channel electronic breaker; PE on its own busbar, power and signal in separate ducts.

Folded: what changed against the original wiring, the chain rules, and the five proofs that gate
the export.
