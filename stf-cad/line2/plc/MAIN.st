// MAIN - one cycle of every station agent; all stations run on ONE time base (the master axis)
PROGRAM MAIN
VAR
    fbMaster  : FB_MasterAxis;
    fbFeeder  : FB_Feeder;
    fbOven    : FB_Oven;
    fbStamp   : FB_FlyingStamp;
    fbQC      : FB_QC;
    fbPickA, fbPickB : FB_DeltaPicker;
    fbLane    : ARRAY[0..2] OF FB_Lane;
    fbPorts   : FB_AmrPorts;
    fbSafety  : FB_SafetyIf;      // S-1: standard side of the TwinSAFE project (requests + status only)
END_VAR
fbSafety();                      // first: every station below runs only while fbSafety.bRunEnable
fbMaster(axDrive := GVL_IO.axQ1, nEncoder := GVL_IO.encB1);
fbFeeder(fMasterPos := fbMaster.fPos);
fbOven();
fbStamp(axStamp := GVL_IO.axQ14, axMaster := fbMaster.axMaster, bPuckEdge := GVL_IO.itsI8);
fbQC(fMasterPos := fbMaster.fPos);
fbPickA(fMasterPos := fbMaster.fPos, bUpstream := TRUE);
fbPickB(fMasterPos := fbMaster.fPos, bUpstream := FALSE, bPartnerMissed := fbPickA.bMissed);
fbPorts();
