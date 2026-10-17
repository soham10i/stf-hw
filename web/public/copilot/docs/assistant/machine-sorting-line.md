# Machine: Sorting line (ft 536633)


## In brief

Receives the baked cookie from the oven belt, reads its colour and ejects it into its bay.  The cookies wait in the bays until the robot collects them, which closes the factory loop.

## What it does

Receives the baked cookie from the oven belt, reads its colour and ejects it into its bay. The
cookies wait in the bays until the robot collects them, which closes the factory loop.

## How it sorts

- The belt (Q1) runs one way. There is no position feedback: I1 is a pulse switch, so the
  controller counts pulses from the inlet barrier (I2) to know which ejector to fire.
- The colour sensor (A4, ft 128599) is **not an RGB sensor**: an LED shines and a phototransistor
  measures how much light comes back, as 0-2 V (scaled by the adapter board to the 0-10 V
  terminal). The reading depends on the distance and on ambient light, so the flavours are chosen
  to be far apart in brightness: chocolate ~340 mV, strawberry ~950 mV, vanilla ~1660 mV.
- I3 after the sensor; then three pneumatic ejectors: Q3 first (weiss, vanilla), Q4 second (rot,
  strawberry), Q5 third (blau, chocolate). Each bay has its own light barrier (I5/I6/I7).
- A bay holds up to 4 cookies; a full bay raises ORD-01.

## Checks

A flavour that differs from the cookie's record raises TRC-03. A cookie that does not reach the
next barrier in time raises SRT-L01 to L03.

## Wear watched

The colour sensor's LED ages: the margin between each flavour's reading and its band edge
shrinks. See *Dashboard: Quality*.

## Hazard

H6, the ejectors: PLr b.
