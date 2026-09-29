---
name: stf-controller-board
description: The ft 24V adaptor PCB / PLC interface (536634 extended description) - data file, web tab, reconciliation, doc discrepancies
metadata:
  type: project
---
The "microcontroller" in 536634-Factory-simulation-24V-extended-description.pdf is the
PLC interface: one 24V adaptor PCB per module (ST1/ST2 ribbons to model, ST3 17x2 to
PLC = terminals 1..30, relays R1..R8 as 4 motor pairs, valve terminals V1..V4).
Inputs P-reading (sinking), outputs P-switching; other controllers need 24 V I/O and
>= 10 ms cycle. Bidirectional motor = 2 outputs -> 2 changeover relays; both on = STOP
(both leads +24 V), not a short. Terminal 1 = motor supply for ALL motors (speed).

`stf-cad/hbw/controller.py` holds the transcription (pages cited) -> stf-hw
web/public/controller.json; web tab "Controller board" = `ui/ControllerView.tsx`
(interactive PCB SVG, I/O simulator with relays + quadrature encoders, circuits p.35-38).
reconcile(): all 72 plan signals exist in the model; only extras are HBW AUX1-4 cover
sensors; module requirements sum exactly to p.2 totals (26/10/1/35). p.2 also confirms
5 encoders, 15 ref switches, 9 light barriers - see [[stf-components]].

Doc discrepancies (shown in the UI, not silently resolved): colour sensor 0-10 V here vs
0-2 V datasheet; HBW p.10 "Q6/Q7 (M3)" typo (really Q5/Q6); oven V2 "vacuum" (p.4) vs
Q12 lowering (p.18); sorting ST3 pin 9 labelled I4 but is A4 analogue; oven Q1 English
"counterclockwise" for both directions.
