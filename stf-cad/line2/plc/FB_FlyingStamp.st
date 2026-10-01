// FB_FlyingStamp - carriage GEARED 1:1 to the master while stamping (MC_GearIn),
// phase from the puck-edge sensor I8 latched by a touch probe; return at 4x.
FUNCTION_BLOCK FB_FlyingStamp
VAR_INPUT
    axStamp  : AXIS_REF;   axMaster : AXIS_REF;   bPuckEdge : BOOL;
END_VAR
VAR
    eState : (IDLE, SYNC, DOWN, DWELL, UP, RETURN);
    fbGearIn : MC_GearIn; fbGearOut : MC_GearOut; fbHome : MC_MoveAbsolute; fPhase : LREAL;
    tDwell : TON;
END_VAR
CASE eState OF
IDLE:   // I8 is on an EL1252: its distributed-clock timestamp of the puck edge, converted to a master
        // position (master pos at the DC time), phases the carriage - v3 wrongly used a touch probe on an EL1809
        IF GVL_IO.itsI8.bNewEdge THEN fPhase := F_MasterPosAt(GVL_IO.itsI8.nTimestamp); eState := SYNC; END_IF
SYNC:   fbGearIn(Master := axMaster, Slave := axStamp, Execute := TRUE, RatioNumerator := 1, RatioDenominator := 1);
        IF fbGearIn.InGear THEN GVL_IO.qQ16 := TRUE; eState := DOWN; END_IF
DOWN:   IF NOT GVL_IO.qQ16 THEN ; END_IF eState := DWELL;
DWELL:  tDwell(IN := TRUE, PT := T#500MS); IF tDwell.Q THEN GVL_IO.qQ16 := FALSE; eState := UP; END_IF
UP:     fbGearOut(Slave := axStamp, Execute := TRUE); eState := RETURN;
RETURN: fbHome(Axis := axStamp, Execute := TRUE, Position := 0, Velocity := 80);
        IF fbHome.Done THEN eState := IDLE; END_IF
END_CASE
