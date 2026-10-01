// FB_Airlock - standard-side sequence of the two AMR airlocks. It only REQUESTS; the TwinSAFE
// project (SF6) refuses any unlock that breaks the interlock, so a bug here cannot open both sides.
//
// OUT (cassettes), per lane, started by the lift counter 75 s before full (the AMR is called then):
//   1 carrier: full cassette stacker -> chamber (200 mm at 100 mm/s)
//   2 request S32 close + lock (inner door); TwinSAFE drops K5 (shuttles)
//   3 AMR docked (OUT.DOCK1/2) -> request S31 unlock + open (outer door)
//   4 AMR swaps full <-> empty (20 s [assumed]); S31 close + lock
//   5 request S32 unlock + open; K5 on; carrier: empty chamber -> stacker
//   exchange 30 s; the stacker platform holds 1 sealed pack meanwhile, so a robot on
//   time costs no production. Lanes run a third of a fill apart (CASS_STAGGER) so exchanges never coincide.
// BOXES (tray stacks): AMR docked -> trapdoors closed (Q42..Q44.CL) + Y1 exhausted -> S30 unlock + open;
//   AMR sets stacks in the chamber; S30 close + lock -> Y1 on -> trapdoor over each low magazine drops its stack.
FUNCTION_BLOCK FB_Airlock
VAR_INPUT nLaneFull : INT; bAmrDocked : BOOL; END_VAR
VAR eOut : (IDLE, CARRY_OUT, INNER_CLOSE, OUTER_OPEN, SWAP, OUTER_CLOSE, INNER_OPEN, CARRY_IN); END_VAR
