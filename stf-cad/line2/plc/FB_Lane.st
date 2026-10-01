// FB_Lane - index one tray pitch when a tray is full; seal in the index pause (1 s <= 2 s);
// stacker lifts each pack through the pawls; the lift counter says 'cassette full' at 27 packs;
// shuttle swap (OPEN DESIGN ISSUE: a single bar cannot exchange two cassettes - see joints/README).
FUNCTION_BLOCK FB_Lane
VAR_INPUT nLane : INT; END_VAR
VAR nPacks : INT; END_VAR
