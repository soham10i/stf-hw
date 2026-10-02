// FB_DeltaPicker - conveyor tracking pick of a moving cookie, place into the lane pocket.
// Kinematics: the NC delta transformation (TF5110-class, licence to confirm) with conveyor
// tracking coupled to the master axis; the tracking camera CAM2 gives pose + phase. A is
// upstream and picks; B catches what A missed (N+1). Placement budget: backlash + steps
// <= DELTA_REP (proven in line_model.sizing with the Jacobian).
FUNCTION_BLOCK FB_DeltaPicker
VAR_INPUT fMasterPos : LREAL; bUpstream : BOOL; bPartnerMissed : BOOL; END_VAR
VAR_OUTPUT bMissed : BOOL; END_VAR
VAR eState : (WAIT, TRACK, GRIP, LIFT, PLACE, RELEASE, HOME); END_VAR
// GRIP: vacuum valve ON, wait for the vacuum switch (.OK); no OK within 0.8 s -> bMissed (the cookie recirculates)
