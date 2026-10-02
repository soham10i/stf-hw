// FB_MasterAxis - the electronic line shaft. The chain NEVER stops (no stop path in the
// automatic mode, only losses). v = 20 mm/s, pitch = 80 mm -> takt 4.00 s.
// The master position is the MEASURING-WHEEL encoder B1 (EL5101), not the drive's own encoder,
// so sprocket slip shows as a drift between the two (health signal).
FUNCTION_BLOCK FB_MasterAxis
VAR_INPUT
    axDrive  : AXIS_REF;          // Q1 on EL7047 (closed loop)
    nEncoder : UDINT;             // B1 counts
END_VAR
VAR_OUTPUT
    axMaster : AXIS_REF;          // NC encoder axis on B1 (virtual master for gearing / cams)
    fPos     : LREAL;             // mm along the loop, modulo N*P
    fDrift   : LREAL;             // drive encoder - B1, mm (slip monitor)
END_VAR
VAR
    fbPower : MC_Power; fbVel : MC_MoveVelocity;
END_VAR
fbPower(Axis := axDrive, Enable := TRUE, Enable_Positive := TRUE, Enable_Negative := FALSE);
fbVel(Axis := axDrive, Execute := fbPower.Status, Velocity := 20.0, Acceleration := 20, Deceleration := 20,
      Direction := MC_Positive_Direction);
fPos := LMOD(axMaster.NcToPlc.ActPos, 3840.0);
fDrift := axDrive.NcToPlc.ActPos - axMaster.NcToPlc.ActPos;
