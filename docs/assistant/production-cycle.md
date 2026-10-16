# The production cycle

## In brief

One cookie's journey, as the 3D view plays it and the PLC runs it:


One cookie's journey, as the 3D view plays it and the PLC runs it:

1. **Retrieve**: the crane travels to the mould's slot, lifts, extends the fork, takes the mould
   and puts it on the belt.
2. **Belt and RFID**: the belt carries it past RP1 and RP2; the tag is checked against the record.
3. **To the oven**: the robot picks the cookie off the mould and lays it on the oven tray.
4. **Bake** in the heated chamber.
5. **Turntable, saw, pusher**: the oven's gripper moves it to the turntable, which dwells under the
   saw and turns to the belt; the pusher puts it on the outlet belt.
6. **Sort**: the sorting line reads its colour and ejects it into its bay.
7. **Back to the rack**: the robot collects it from the bay and puts it in a mould at the warehouse
   belt; the crane stores the mould.

The cell overlaps cookies: while one bakes, the crane fetches the next. The PLC's dispatch policy
decides what moves next; the one used (reuse) refills an empty mould at the hand-over with a cookie
going into the rack. Its full 12-cookie order takes about 425.7 s in the model and 429.8 s when
commissioned against the twin.

Safety: every transfer takes all its locks at once and in one fixed order, and never starts unless
its destination has room, so the cell cannot deadlock. This is proven over every possible
completion order.
