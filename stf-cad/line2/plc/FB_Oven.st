// FB_Oven - 3 zones. Per zone: FEED-FORWARD of the product load (from the band content FB_Band tracks,
// row by row) + PI on the zone TC (SIMC-tuned on the oven_ctrl.py model) with conditional-integration
// anti-windup -> 2 s time-proportioning PWM on every element SSR of the zone. Cold start: set point ramp
// 10 K/min with the ramp power fed forward. Duty observer: measured duty - model duty, filtered 60 s;
// > half an element for the zone -> element-failure alarm (proven in oven_ctrl S4). The STB (SF4) is hardware.
//   Z1 210 C: TC TC1 -> E1T1 500 W top L1, E1T2 500 W top L2, E1T3 500 W top L3, E1B1 500 W bot L1, E1B2 500 W bot L2; fan QF1
//   Z2 200 C: TC TC2 -> E2T1 500 W top L3, E2B1 350 W bot L2; fan QF2
//   Z3 185 C: TC TC3 -> E3T1 500 W top L1, E3B1 350 W bot L3; fan QF3
// Steady load at 900 cookies/h: Z1 1516 W, Z2 563 W, Z3 562 W.
// The recipe holds +-2 K (oven.py bake window); bReady = every zone inside it for 60 s.
FUNCTION_BLOCK FB_Oven
VAR_INPUT  bRunEnable : BOOL; aContent : ARRAY[0..2] OF LREAL;     // 0..1 zone filled (from FB_Band) END_VAR
VAR_OUTPUT bReady : BOOL; aTemp : ARRAY[0..2] OF LREAL; aDuty : ARRAY[0..2] OF LREAL;
           aElementAlarm : ARRAY[0..2] OF BOOL; fPower_W : LREAL; END_VAR
VAR
    aSet  : ARRAY[0..2] OF LREAL := [210.0, 200.0, 185.0];      // degC (oven.py recipe)
    aKc   : ARRAY[0..2] OF LREAL := [0.0225, 0.0650, 0.0673];  // 1/K
    aTi   : ARRAY[0..2] OF LREAL := [150, 152, 148];  // s
    aP    : ARRAY[0..2] OF LREAL := [2500, 850, 850];        // W installed
    aC    : ARRAY[0..2] OF LREAL := [2109, 2109, 2109];        // J/K
    aLoadEmpty, aLoadFull : ARRAY[0..2] OF LREAL := [538, 23, 264], [1516, 563, 562];
    aSp, aI, aObs : ARRAY[0..2] OF LREAL;     // aSp := aTemp at power-up (the ramp starts where the zone is)
    fRamp : LREAL := 0.1667;    // K/s
    aElMin : ARRAY[0..2] OF LREAL := [500, 350, 350];   // W, smallest element
    fNow_s, fPhase : LREAL;     // fNow_s: task time in s (TwinCAT system time)
    tStable : TON; k : INT; e, uff, u : LREAL; bRamp : BOOL;
END_VAR
aTemp[0] := INT_TO_LREAL(GVL_IO.tcTC1) / 10.0;
aTemp[1] := INT_TO_LREAL(GVL_IO.tcTC2) / 10.0;
aTemp[2] := INT_TO_LREAL(GVL_IO.tcTC3) / 10.0;
FOR k := 0 TO 2 DO
    aSp[k] := MIN(aSet[k], aSp[k] + fRamp * 0.01);  bRamp := aSp[k] < aSet[k];        // 10 ms task
    e := aSp[k] - aTemp[k];
    uff := (aLoadEmpty[k] + aContent[k] * (aLoadFull[k] - aLoadEmpty[k]) + SEL(bRamp, 0.0, aC[k] * fRamp)) / aP[k];
    u := uff + aKc[k] * (e + aI[k] / aTi[k]);
    IF (u > 0.0 AND u < 1.0) OR (u >= 1.0 AND e < 0.0) OR (u <= 0.0 AND e > 0.0) THEN aI[k] := aI[k] + e * 0.01; END_IF
    aDuty[k] := LIMIT(0.0, u, 1.0);
    aObs[k] := aObs[k] + (aDuty[k] - uff - aObs[k]) * 0.01 / 60.0;
    aElementAlarm[k] := NOT bRamp AND aObs[k] > 0.5 * aElMin[k] / aP[k];
END_FOR
// time-proportioning, 2 s period: element i of n in a zone conducts in its own slice of the period (phase
// [i/n, i/n + duty)) - the zone gets its duty, the phases see the load spread instead of all at once
fPhase := LMOD(fNow_s / 2.0, 1.0);
GVL_IO.qE1T1 := F_InSlice(fPhase, 0.0 / 5.0, aDuty[0]) AND bRunEnable;   // Z1
GVL_IO.qE1T2 := F_InSlice(fPhase, 1.0 / 5.0, aDuty[0]) AND bRunEnable;   // Z1
GVL_IO.qE1T3 := F_InSlice(fPhase, 2.0 / 5.0, aDuty[0]) AND bRunEnable;   // Z1
GVL_IO.qE1B1 := F_InSlice(fPhase, 3.0 / 5.0, aDuty[0]) AND bRunEnable;   // Z1
GVL_IO.qE1B2 := F_InSlice(fPhase, 4.0 / 5.0, aDuty[0]) AND bRunEnable;   // Z1
GVL_IO.qE2T1 := F_InSlice(fPhase, 0.0 / 2.0, aDuty[1]) AND bRunEnable;   // Z2
GVL_IO.qE2B1 := F_InSlice(fPhase, 1.0 / 2.0, aDuty[1]) AND bRunEnable;   // Z2
GVL_IO.qE3T1 := F_InSlice(fPhase, 0.0 / 2.0, aDuty[2]) AND bRunEnable;   // Z3
GVL_IO.qE3B1 := F_InSlice(fPhase, 1.0 / 2.0, aDuty[2]) AND bRunEnable;   // Z3
GVL_IO.qQF1 := bRunEnable;   // Z1 circulation fan
GVL_IO.qQF2 := bRunEnable;   // Z2 circulation fan
GVL_IO.qQF3 := bRunEnable;   // Z3 circulation fan
tStable(IN := ABS(aTemp[0] - aSet[0]) < 2 AND ABS(aTemp[1] - aSet[1]) < 2 AND ABS(aTemp[2] - aSet[2]) < 2, PT := T#60S);
bReady := tStable.Q;
