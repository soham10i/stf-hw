# Machine: Oven (multi-processing station with kiln, ft 536632)


## In brief

Everything the cookie touches lies on one flow line:

## The flow

Everything the cookie touches lies on one flow line:

1. The robot lays the raw cookie on the extended tray (Ofenschieber); light barrier I9 sees it.
2. The door opens, the tray retracts into the chamber (stop I6), the door closes.
3. Bake: the heating elements run (output Q9) until the cookie is done.
4. The door opens, the tray extends (stop I7).
5. The oven's own suction gripper (Sauger) lifts the cookie onto the turntable (Drehtisch).
6. The turntable stops under the saw, then turns to the belt; the pusher (Auswerfer, Q14) pushes
   the cookie onto the outlet belt.
7. The belt carries it through I3 onto the sorting line.

One pneumatic stroke of the gripper (Q12) serves both the tray and the turntable, because the tray
top, the turntable top and the belt top are all at the same working level (60 mm).

## The baking system

The original ft model only signals baking with a lamp. The twin's oven is built to bake:

- **Chamber**: about 7.5 litres. Brushed stainless casing over 10 mm ceramic-fibre insulation,
  a 1.5 mm stainless liner inside, a stainless floor, a black enamelled top.
- **Heating**: tubular heating elements (8 mm stainless sheath, 230 V). A grill hairpin of
  2 x 400 W hangs on stainless hangers 70 mm above the cookie, in sight through the door window, and two
  250 W hairpins sit on steatite standoffs under the tray, either side of its rail. Their cold
  ends pass through the back wall into a terminal box.
- **Convection fan** on the back wall (motor outside the hot zone) for even heat over the tray.
- **Temperature sensor**: a K-type thermocouple (3 mm sheath) reaches 30 mm into the chamber at
  mid height through the side wall and runs straight into the control panel, where the PID
  controller reads it. Its reading is shown on the panel's display and in *Telemetry* (chamber
  temperature, and an *oven at temperature* light from 170 C).
- **Nothing heat-sensitive inside**: the tray's "in" reference I6 is not a plastic mini switch but a
  high-temperature inductive proximity sensor (M18, rated 230 C) mounted from below through the
  insulated floor. Its body and cable stay in the cool pedestal; only its ceramic face shows, 7 mm
  under the stainless tray when the tray is in. All other sensors and every cable are outside the
  chamber.
- **Door**: a stainless frame round a triple-glazed borosilicate window.
- **Control panel** on the oven's side: PID temperature controller with display, the solid-state
  relay that Q9 switches, a 10 A fuse, and a manual-reset over-temperature cutout at 250 C. The
  mains contactor drops with the safety relay, so an E-stop also cuts the heat.
- **Steam vent** on the roof.

In the 3D view the elements glow while baking (they heat and cool with a lag of seconds), the
chamber light follows them, and the control panel shows the chamber temperature, rising toward
182 C while baking and falling back toward 25 C after.

All of these parts are in the oven's parameter table and pass its proofs: nothing intersects the
tray, the rail, the door or the cookie in any allowed pose.

## I/O (wiring plan)

Inputs: I1/I2/I4 turntable positions (gripper, belt, saw), I3 belt end, I5/I8 gripper at turntable
/ at oven, I6/I7 tray in / out, I9 oven light barrier, I10/I11 door, I12/I13 gripper cylinder,
I14/I15 pusher. I6 is the high-temperature inductive sensor in the floor. Outputs: Q1/Q2 turntable, Q3 belt, Q4 saw, Q5/Q6 tray, Q7/Q8 gripper travel, Q9
oven (heat), Q10 compressor, Q11 vacuum, Q12 lower gripper, Q13 door, Q14 pusher. No encoders:
every axis runs to a switch.

## Faults and wear

Alarms OVN-D (door and tray), OVN-S (gripper), OVN-T (turntable, saw, pusher), OVN-B01 (belt).
Wear watched: door cylinder, gripper lowering cylinder and pusher cylinder (reed-to-reed travel
time).

## Hazards

H3 tray and door (PLr b), H4 turntable, saw and gripper (PLr c), H5 pusher (PLr b).
