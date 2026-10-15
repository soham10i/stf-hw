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
    aPuck     : T_PuckArray;      // what the PLC knows of every puck (filled, flavour, verdict ...)
    aLane     : T_LaneArray;      // per lane: blocked while it indexes, packs to index
END_VAR
fbSafety();                      // first: every station below runs only while fbSafety.bRunEnable
fbMaster(axDrive := GVL_IO.axQ1, axMaster := GVL_IO.axMasterEnc, nEncoder := GVL_IO.encB1);
fbOven(bRunEnable := fbSafety.bRunEnable, aContent := fbBand.aZoneContent);   // last cycle's content
fbBand(axBand := GVL_IO.axQ40, axRolls := GVL_IO.axQ41, axMaster := GVL_IO.axMasterEnc,
       bOvenReady := fbOven.bReady, nDoughLevel := GVL_IO.iolIOL1);
// the stations in the order of the loop: at one master position the transfer comes first, then QC, the kicker,
// delta A, delta B (A and B see their pucks at the same phase: A first)
fbTransfer(stJob := GVL_IO.stDeltaC, aPuck := aPuck, fMaster := fbMaster.fAbs, fBand := fbBand.fPos,
           nRows := fbBand.nRows, fRowPos := fbBand.fRowPos, bPuckFull := GVL_IO.iI1,
           nVacuum := GVL_IO.ioldelta_C_VAC_P, bLoad := GVL_IO.xHmiLoad);
GVL_IO.qdelta_C_VAC := fbTransfer.bVacuum;
fbQC(aPuck := aPuck, fMaster := fbMaster.fAbs, stQc := GVL_IO.stQc);
GVL_IO.qQ18 := fbQC.bKick;
fbPickA(stJob := GVL_IO.stDeltaA, aPuck := aPuck, aLane := aLane, fMaster := fbMaster.fAbs, nDelta := 0,
        fIn := 2534.116936495, fOut := 2629.320124941, nVacuum := GVL_IO.ioldelta_A_VAC_P);
GVL_IO.qdelta_A_VAC := fbPickA.bVacuum;
fbPickB(stJob := GVL_IO.stDeltaB, aPuck := aPuck, aLane := aLane, fMaster := fbMaster.fAbs, nDelta := 1,
        fIn := 2854.116936495, fOut := 2949.320124941, nVacuum := GVL_IO.ioldelta_B_VAC_P);
GVL_IO.qdelta_B_VAC := fbPickB.bVacuum;
fbLane[0](axLane := GVL_IO.axQ20, stLane := aLane[0], fMaster := fbMaster.fAbs);
fbLane[1](axLane := GVL_IO.axQ21, stLane := aLane[1], fMaster := fbMaster.fAbs);
fbLane[2](axLane := GVL_IO.axQ22, stLane := aLane[2], fMaster := fbMaster.fAbs);
fbPorts();
