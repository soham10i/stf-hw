// FB_MasterAxis - the electronic line shaft. The chain NEVER stops (no stop path in the
// automatic mode, only losses). v = 20 mm/s, pitch = 80 mm -> takt 4.00 s.
// The master position is the MEASURING-WHEEL encoder B1 (EL5101), not the drive's own encoder,
// so sprocket slip shows as a drift between the two (health signal).
FUNCTION_BLOCK FB_MasterAxis
VAR_IN_OUT                        // axes BY REFERENCE: MC blocks on a copy would never move the real axis
    axDrive  : AXIS_REF;          // Q1 on EL7047 (closed loop)
    axMaster : AXIS_REF;          // NC encoder axis on B1 (virtual master for gearing / cams)
END_VAR
VAR_INPUT
    nEncoder : UDINT;             // B1 counts
END_VAR
VAR_OUTPUT
    fPos     : LREAL;             // mm along the loop, modulo the loop length
    fAbs     : LREAL;             // mm since power-up (the stations' time base: tau = fAbs / v)
    fDrift   : LREAL;             // drive encoder - B1, mm (slip monitor)
END_VAR
VAR
    fbPower : MC_Power; fbVel : MC_MoveVelocity;
END_VAR
fbPower(Axis := axDrive, Enable := TRUE, Enable_Positive := TRUE, Enable_Negative := FALSE);
fbVel(Axis := axDrive, Execute := fbPower.Status, Velocity := 20.0, Acceleration := 20.0, Deceleration := 20.0,
      Direction := MC_Positive_Direction);
fPos := LMOD(axMaster.NcToPlc.ActPos, 3840.037061436);   // the chain's loop, not N x P (finding 16)
fAbs := axMaster.NcToPlc.ActPos;
fDrift := axDrive.NcToPlc.ActPos - axMaster.NcToPlc.ActPos;
