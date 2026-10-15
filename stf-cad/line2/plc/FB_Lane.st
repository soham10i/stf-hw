// FB_Lane - index one tray pitch (160 mm in 1.6 s) when a tray is full, as the pick that filled it ends;
// the pickers keep off the lane meanwhile (2 s). Seal in the index pause (1 s <= 2 s);
// stacker lifts each pack through the pawls; the lift counter says 'cassette full' at 27 packs;
// shuttle swap (OPEN DESIGN ISSUE: a single bar cannot exchange two cassettes - see joints/README).
// bCanPack: TRUE until the logistics (tray magazine, cassette, airlock) are written (DT-4b part 2).
FUNCTION_BLOCK FB_Lane
VAR_IN_OUT axLane : AXIS_REF; stLane : ST_Lane; END_VAR
VAR_INPUT fMaster : LREAL; END_VAR
VAR_OUTPUT nPacks : DINT; END_VAR
VAR fbPower : MC_Power; fbIndex : MC_MoveRelative; nDone : INT; bGo : BOOL; END_VAR
fbPower(Axis := axLane, Enable := TRUE, Enable_Positive := TRUE, Enable_Negative := FALSE);
stLane.bCanPack := TRUE;
bGo := stLane.nPackReq > nDone AND fMaster / 20.0 >= stLane.fPackAt AND fbPower.Status;
fbIndex(Axis := axLane, Execute := bGo, Distance := 160.0, Velocity := 200.0,
        Acceleration := 250.0, Deceleration := 250.0);
IF fbIndex.Done THEN nDone := nDone + 1;  nPacks := nPacks + 1; END_IF;
