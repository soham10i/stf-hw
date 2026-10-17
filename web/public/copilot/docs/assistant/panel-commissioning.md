# Panel: Commissioning

Virtual commissioning: the PLC program tested against the twin before any hardware exists, with
the real scan times (10 ms task, 5 ms for the robot) and Modbus TCP at 10 ms with the real
register map.


## In brief

Virtual commissioning: the PLC program tested against the twin before any hardware exists, with the real scan times (10 ms task, 5 ms for the robot) and Modbus TCP at 10 ms with the real register map.

## Verdict and OEE

The *Verified* line: the commissioned order time against the model (429.8 s vs 425.7 s, +1 %,
within tolerance), faults handled, accuracy within tolerance.

OEE for one shift in which every fault happens once: 30.8 % = availability 63.1 % x performance
48.8 % x quality 100 %. Low on purpose: the shift injects all seven faults. The bottleneck is the
crane (209.8 s busy of 429.8 s), not the oven as first expected.

## Faults

Click a fault for what was injected, what was observed and how fast, the reaction and the
recovery. Each must raise the expected alarm within its bound.

| Id | Fault | Alarm |
|---|---|---|
| F1 | stuck switch | HBW-C01 |
| F2 | motor stall | VGR-A04 |
| F3 | cylinder never arrives | OVN-D01 |
| F4 | lost vacuum | VGR-V01 |
| F5 | air pressure drop | SYS-05 |
| F6 | lost bus node | SYS-04 |
| F7 | E-stop | SYS-01 |

## Accuracy

Each axis's stopping error against what is allowed: travel ±0.75 / 4 mm, lift ±0.75 / 4 mm,
plunge ±0.6 / 4 mm, reach ±0.6 / 2.5 mm, swivel ±1.49 / 2.5 mm. Hover for why the limit is what
it is.

Folded: the test setup, and which faults were found only late (and how) before the commissioning
sensors were added.
