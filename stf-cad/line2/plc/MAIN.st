// MAIN - one cycle of every station agent; all stations run on ONE time base (the master axis)
PROGRAM MAIN
VAR
    fbMaster  : FB_MasterAxis;
    fbOven    : FB_Oven;          // zones, elements, fans, warm-up gate (oven.py recipe)
    fbBand    : FB_Band;          // band + depositor + topping, geared to the master
    fbTransfer: FB_Transfer;      // delta C: band row -> passing puck, NFC write
    fbQC      : FB_QC;
    fbPickA, fbPickB : FB_DeltaPicker;
    fbLane    : ARRAY[0..2] OF FB_Lane;
    fbPorts   : FB_AmrPorts;
    fbSafety  : FB_SafetyIf;      // S-1: standard side of the TwinSAFE project (requests + status only)
END_VAR
fbSafety();                      // first: every station below runs only while fbSafety.bRunEnable
fbMaster(axDrive := GVL_IO.axQ1, nEncoder := GVL_IO.encB1);
fbOven(bRunEnable := fbSafety.bRunEnable);
fbBand(axBand := GVL_IO.axQ40, axRolls := GVL_IO.axQ41, axMaster := fbMaster.axMaster,
       bOvenReady := fbOven.bReady);
fbTransfer(fMasterPos := fbMaster.fPos, fBandPos := fbBand.fPos, bPuckFull := GVL_IO.iI1);
fbQC(fMasterPos := fbMaster.fPos);
fbPickA(fMasterPos := fbMaster.fPos, bUpstream := TRUE);
fbPickB(fMasterPos := fbMaster.fPos, bUpstream := FALSE, bPartnerMissed := fbPickA.bMissed);
fbPorts();
