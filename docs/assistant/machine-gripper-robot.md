# Machine: Gripper robot (vacuum gripper robot, VGR, ft 536632)

## What it does

Links every station: picks the cookie at the warehouse belt and lays it on the oven tray, and
collects sorted cookies from the sorting bays to bring them back to the warehouse.

## Kinematics

Cylindrical (R-P-P), not cartesian:

| Axis | Drive | Feedback |
|---|---|---|
| Swivel (about Z) | motor M3 on the gear ring (Drehkranz) | encoder B5/B6, reference I3 |
| Plunge (up/down) | motor M1, lead screw; the carriage runs on four column profiles | encoder B1/B2, reference I1 |
| Reach (in/out) | motor M2, lead screw; the arm slides through the carriage on two rails | encoder B3/B4, reference I2 |
| Suction cup | compressor Q7 and vacuum valve Q8 | vacuum switch I4 |

Every station it serves is solved from the geometry, and its swept path is proven clear of the
warehouse, the oven and the sorting line.

## Faults

Vacuum lost while carrying raises VGR-V01; an axis that does not arrive raises VGR-A01 to A06.
Low air at the air station (VGR input I5) raises SYS-05.

## Wear parts watched

The suction cup seal (vacuum build-up time) and the swivel gearbox (move time per degree; it wears
suddenly, which is why the AI model matters for it).

## Hazard

H2, the swivel arm: PLr d.
