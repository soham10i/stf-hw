# Machine: Warehouse (high-bay warehouse, ft 536631)


## In brief

Stores the 12 moulds, each holding one cookie, in a rack of 3 rows x 4 columns (slots A1-C4).  A stacker crane fetches a mould and puts it on a belt that carries it to the gripper robot, and stores it again when it comes back.

## What it does

Stores the 12 moulds, each holding one cookie, in a rack of 3 rows x 4 columns (slots A1-C4).
A stacker crane fetches a mould and puts it on a belt that carries it to the gripper robot, and
stores it again when it comes back.

## Axes

| Axis | Drive | Feedback |
|---|---|---|
| Travel (along the rack) | encoder motor on a lead screw, the carriage on a ground steel guide rod | encoder B1/B2, reference switch I1 |
| Lift | encoder motor on a vertical lead screw; the carriage runs on four aluminium mast tubes | encoder B3/B4, reference switch I4 |
| Fork (Ausleger) | motor on a lead screw between two bearing blocks, front and rear stops | switches I5 (front), I6 (rear) |
| Belt | motor, carries the mould between the crane and the robot | light barriers I2, I3 |

Homing: fork back to I6, lift to I4, travel to I1. Each move has a watchdog; a target not reached
in time raises an HBW-C alarm.

## Traceability

Two RFID read points on the belt (IO-Link): RP1 at the crane end, RP2 at the robot hand-over.
Every mould's tag is read and compared with its record; a missing or different tag raises TRC-01
or TRC-02.

## Wear parts watched

The belt (transit time I2 <-> I3 grows with slip), the travel spindle and nut (actuator current
and move time) and the RFID heads (read time including retries). See *Dashboard: Hardware health*.

## Hazard

H1, the stacker crane: PLr d, behind the locked guard.
