// FB_Oven - 3 zones. Per zone: FEED-FORWARD of the band load (from the band content FB_Band tracks,
// row by row) + PI on the zone TC (SIMC-tuned on the oven_ctrl.py model) with conditional-integration
// anti-windup -> 2 s time-proportioning PWM on every element SSR of the zone. Cold start: set point ramp
// 10 K/min with the ramp power fed forward.
// LEARNING feed-forward (upgrade V-1): calm at the set point (+-0.5 K for 120 s) on an empty band the PI
// share moves into aW0 (base load error, W), on a full band into aA1 (product load factor), time constant
// 600 s; the integrator gives the same amount back. Both are PERSISTENT (oven_ctrl S6: +-20 % model error).
// HEATER BREAK: current transducers BC1, BC2, BC3 on L1-L3 of the element feed. The expected phase current
// (every element in its PWM slice + the fans) lagged by the transducer's 0.3 s; short by > half the
// smallest element of the phase for 0.2 s -> alarm; the elements in their slice through the short are
// the candidates, an element seen conducting while the phase reads right is cleared -> named (oven_ctrl S4).
// A named element leaves its zone's model (power, gain); if the rest cannot carry the full load, bReady drops
// and FB_Band stops the depositor. The STB (SF4) is hardware.
//   Z1 210 C: TC TC1 -> E1T1 500 W top L1, E1T2 500 W top L2, E1T3 500 W top L3, E1B1 500 W bot L1, E1B2 500 W bot L2; fan QF1
//   Z2 200 C: TC TC2 -> E2T1 500 W top L3, E2B1 350 W bot L2; fan QF2
//   Z3 185 C: TC TC3 -> E3T1 500 W top L1, E3B1 350 W bot L3; fan QF3
// Steady load at 900 cookies/h: Z1 1516 W, Z2 563 W, Z3 562 W.
// The recipe holds +-2 K (oven.py bake window); bReady = every zone inside it for 60 s.
FUNCTION_BLOCK FB_Oven
VAR_INPUT  bRunEnable : BOOL; aContent : ARRAY[0..2] OF LREAL;     // 0..1 zone filled (from FB_Band) END_VAR
VAR_OUTPUT bReady : BOOL; aTemp : ARRAY[0..2] OF LREAL; aDuty : ARRAY[0..2] OF LREAL;
           aElementAlarm : ARRAY[0..2] OF BOOL; aBroken : ARRAY[0..8] OF BOOL; bHold : BOOL;
           fPower_W : LREAL; END_VAR
VAR PERSISTENT
    aW0 : ARRAY[0..2] OF LREAL;                                   // W, learned base-load error
    aA1 : ARRAY[0..2] OF LREAL := [1.0, 1.0, 1.0];   // learned product-load factor
END_VAR
VAR
    aSet  : ARRAY[0..2] OF LREAL := [210.0, 200.0, 185.0];      // degC (oven.py recipe)
    aKc   : ARRAY[0..2] OF LREAL := [0.0225, 0.0650, 0.0673];  // 1/K
    aTi   : ARRAY[0..2] OF LREAL := [150, 152, 148];  // s
    aP    : ARRAY[0..2] OF LREAL := [2500, 850, 850];        // W installed
    aC    : ARRAY[0..2] OF LREAL := [2109, 2109, 2109];        // J/K
    aLoadEmpty, aLoadFull : ARRAY[0..2] OF LREAL := [538, 23, 264], [1516, 563, 562];
    aSp, aI, aLost, aCalm : ARRAY[0..2] OF LREAL;   // aSp := aTemp at power-up (the ramp starts where the zone is)
    fRamp : LREAL := 0.1667;    // K/s
    // elements, flattened in slice order: zone, slice i of n, phase 0..2 = L1..L3, W
    aElZone  : ARRAY[0..8] OF INT := [0, 0, 0, 0, 0, 1, 1, 2, 2];
    aElSlice : ARRAY[0..8] OF LREAL := [0.0 / 5.0, 1.0 / 5.0, 2.0 / 5.0, 3.0 / 5.0, 4.0 / 5.0, 0.0 / 2.0, 1.0 / 2.0, 0.0 / 2.0, 1.0 / 2.0];
    aElPh    : ARRAY[0..8] OF INT := [0, 1, 2, 0, 1, 2, 1, 0, 2];
    aElW     : ARRAY[0..8] OF LREAL := [500, 500, 500, 500, 500, 500, 350, 500, 350];
    aOn, aCand : ARRAY[0..8] OF BOOL;
    aFanA : ARRAY[0..2] OF LREAL := [0.000, 0.304, 0.152];   // A, fans on the feed
    aThrA : ARRAY[0..2] OF LREAL := [1.087, 0.761, 0.761];   // A, half the smallest element
    aExp, aExpLag, aMeas, aShort : ARRAY[0..2] OF LREAL;
    aPhAlarm, aShortOn : ARRAY[0..2] OF BOOL;
    aOnT : ARRAY[0..8] OF LREAL;  aRecent, aTry, aOnLast : ARRAY[0..8] OF BOOL;
    aSince, aAlarmT, aProbeT, aProbeMax : ARRAY[0..2] OF LREAL;
    aProbe : ARRAY[0..2] OF INT := [-1, -1, -1];
    fNow_s, fPhase, dW, fProd : LREAL;     // fNow_s: task time in s (TwinCAT system time)
    tStable : TON; k, i, j, n, m : INT; e, uff, u : LREAL; bRamp, bAnyAlarm, bSame, bSettled : BOOL;
END_VAR
aTemp[0] := INT_TO_LREAL(GVL_IO.tcTC1) / 10.0;
aTemp[1] := INT_TO_LREAL(GVL_IO.tcTC2) / 10.0;
aTemp[2] := INT_TO_LREAL(GVL_IO.tcTC3) / 10.0;
aMeas[0] := INT_TO_LREAL(GVL_IO.aiBC1) / 32767.0 * 20.0;   // A, L1
aMeas[1] := INT_TO_LREAL(GVL_IO.aiBC2) / 32767.0 * 20.0;   // A, L2
aMeas[2] := INT_TO_LREAL(GVL_IO.aiBC3) / 32767.0 * 20.0;   // A, L3
bAnyAlarm := aPhAlarm[0] OR aPhAlarm[1] OR aPhAlarm[2] OR aElementAlarm[0] OR aElementAlarm[1] OR aElementAlarm[2];   // learning frozen until repaired
FOR k := 0 TO 2 DO
    aSp[k] := MIN(aSet[k], aSp[k] + fRamp * 0.01);  bRamp := aSp[k] < aSet[k];        // 10 ms task
    e := aSp[k] - aTemp[k];
    fProd := aContent[k] * (aLoadFull[k] - aLoadEmpty[k]);
    uff := (aLoadEmpty[k] + aW0[k] + aA1[k] * fProd + SEL(bRamp, 0.0, aC[k] * fRamp)) / (aP[k] - aLost[k]);
    u := uff + aKc[k] * aP[k] / (aP[k] - aLost[k]) * (e + aI[k] / aTi[k]);
    IF (u > 0.0 AND u < 1.0) OR (u >= 1.0 AND e < 0.0) OR (u <= 0.0 AND e > 0.0) THEN aI[k] := aI[k] + e * 0.01; END_IF
    aDuty[k] := LIMIT(0.0, u, 1.0);
    // learning feed-forward
    IF ABS(e) < 0.5 AND NOT bRamp THEN aCalm[k] := aCalm[k] + 0.01; ELSE aCalm[k] := 0.0; END_IF
    IF aCalm[k] > 120 AND NOT bAnyAlarm AND (aContent[k] < 0.05 OR aContent[k] > 0.95) THEN
        dW := (aDuty[k] - uff) * aP[k] * 0.01 / 600;
        IF aContent[k] < 0.05 THEN
            aW0[k] := aW0[k] + dW;
        ELSIF fProd > 1.0 THEN
            u := LIMIT(0.5, aA1[k] + dW / fProd, 1.6);
            dW := (u - aA1[k]) * fProd;  aA1[k] := u;
        END_IF
        aI[k] := aI[k] - dW / aP[k] / aKc[k] * aTi[k];
    END_IF
END_FOR
// time-proportioning, 2 s period: element i of n in a zone conducts in its own slice of the period (phase
// [i/n, i/n + duty)) - the zone gets its duty, the phases see the load spread instead of all at once
fPhase := LMOD(fNow_s / 2.0, 1.0);
FOR j := 0 TO 2 DO aExp[j] := SEL(bRunEnable, 0.0, aFanA[j]); END_FOR
FOR i := 0 TO 8 DO
    aOn[i] := F_InSlice(fPhase, aElSlice[i], aDuty[aElZone[i]]) AND bRunEnable AND NOT aBroken[i]
              AND aProbe[aElPh[i]] <> i;                       // a probed candidate is held off
    IF aOn[i] THEN aExp[aElPh[i]] := aExp[aElPh[i]] + aElW[i] / 230; END_IF
END_FOR
GVL_IO.qE1T1 := aOn[0];   // Z1
GVL_IO.qE1T2 := aOn[1];   // Z1
GVL_IO.qE1T3 := aOn[2];   // Z1
GVL_IO.qE1B1 := aOn[3];   // Z1
GVL_IO.qE1B2 := aOn[4];   // Z1
GVL_IO.qE2T1 := aOn[5];   // Z2
GVL_IO.qE2B1 := aOn[6];   // Z2
GVL_IO.qE3T1 := aOn[7];   // Z3
GVL_IO.qE3B1 := aOn[8];   // Z3
GVL_IO.qQF1 := bRunEnable;   // Z1 circulation fan
GVL_IO.qQF2 := bRunEnable;   // Z2 circulation fan
GVL_IO.qQF3 := bRunEnable;   // Z3 circulation fan
// heater break: expected vs measured phase current (oven_ctrl._HeaterBreak, line for line)
FOR i := 0 TO 8 DO
    IF aOn[i] THEN aOnT[i] := fNow_s; END_IF
    aRecent[i] := fNow_s - aOnT[i] <= 0.3;      // the reading lags: on at some time in t_resp
END_FOR
FOR j := 0 TO 2 DO
    bSame := TRUE;                                            // same elements on as last cycle?
    FOR i := 0 TO 8 DO IF aElPh[i] = j AND aOn[i] <> aOnLast[i] THEN bSame := FALSE; END_IF END_FOR
    IF NOT bSame THEN aSince[j] := fNow_s; END_IF
    bSettled := ABS(aExp[j] - aExpLag[j]) < 0.1 * aThrA[j];
    aExpLag[j] := aExpLag[j] + (aExp[j] - aExpLag[j]) * 0.01 / 0.100;
    IF aProbe[j] >= 0 THEN                                     // active probe: candidate aProbe[j] held off
        IF fNow_s - aProbeT[j] >= 0.3 THEN aProbeMax[j] := MAX(aProbeMax[j], aExpLag[j] - aMeas[j]); END_IF
        IF fNow_s - aProbeT[j] >= 2.3 THEN     // a full period: its slice came
            IF aProbeMax[j] < 0.5 * aThrA[j] THEN                  // the short vanished: it is the one
                FOR i := 0 TO 8 DO aCand[i] := aCand[i] AND (aElPh[i] <> j OR i = aProbe[j]); END_FOR
            ELSE
                aCand[aProbe[j]] := FALSE;
            END_IF
            aProbe[j] := -1;
        END_IF
    ELSIF aExpLag[j] - aMeas[j] > aThrA[j] THEN
        aShort[j] := aShort[j] + 0.01;
        FOR i := 0 TO 8 DO
            IF aElPh[i] = j THEN aTry[i] := SEL(aShortOn[j], aRecent[i], aTry[i] AND aRecent[i]); END_IF
        END_FOR
        aShortOn[j] := TRUE;
        IF aShort[j] >= 0.2 THEN
            IF NOT aPhAlarm[j] THEN
                aPhAlarm[j] := TRUE;  aAlarmT[j] := fNow_s;
                FOR i := 0 TO 8 DO IF aElPh[i] = j THEN aCand[i] := aTry[i]; END_IF END_FOR
            ELSE
                FOR i := 0 TO 8 DO IF aElPh[i] = j THEN aCand[i] := aCand[i] AND aTry[i]; END_IF END_FOR
            END_IF
        END_IF
    ELSE
        IF bSettled AND fNow_s - aSince[j] >= 0.3 AND aExpLag[j] - aMeas[j] < 0.2 * aThrA[j] AND aPhAlarm[j] THEN
            FOR i := 0 TO 8 DO
                IF aElPh[i] = j AND aOn[i] THEN aCand[i] := FALSE; END_IF     // conducted, phase read right: not it
            END_FOR
        END_IF
        IF aShort[j] < 0.2 THEN aShortOn[j] := FALSE; END_IF
        aShort[j] := 0.0;
    END_IF
    IF aPhAlarm[j] THEN
        n := 0;  m := -1;
        FOR i := 0 TO 8 DO IF aElPh[i] = j AND aCand[i] THEN n := n + 1; IF m < 0 THEN m := i; END_IF END_IF END_FOR
        IF n = 0 THEN                                          // contradiction: start the diagnosis again
            aPhAlarm[j] := FALSE;  aShortOn[j] := FALSE;  aProbe[j] := -1;
        ELSIF n = 1 THEN                                       // named
            aBroken[m] := TRUE;  aLost[aElZone[m]] := aLost[aElZone[m]] + aElW[m];  aCand[m] := FALSE;
            aElementAlarm[aElZone[m]] := TRUE;  aPhAlarm[j] := FALSE;  aShortOn[j] := FALSE;  aProbe[j] := -1;
        ELSIF aProbe[j] < 0 AND fNow_s - aAlarmT[j] >= 4 THEN
            aProbe[j] := m;  aProbeT[j] := fNow_s;  aProbeMax[j] := -1.0E9;   // the slices cannot tell: probe
        END_IF
    END_IF
END_FOR
FOR i := 0 TO 8 DO aOnLast[i] := aOn[i]; END_FOR
// a zone whose remaining elements cannot carry the full band at 95% duty: hold the depositor
bHold := FALSE;
FOR k := 0 TO 2 DO
    IF (aP[k] - aLost[k]) * 0.95 < aLoadFull[k] + aW0[k] + (aA1[k] - 1.0) * (aLoadFull[k] - aLoadEmpty[k]) THEN bHold := TRUE; END_IF
END_FOR
fPower_W := 0.0;
FOR k := 0 TO 2 DO fPower_W := fPower_W + aDuty[k] * (aP[k] - aLost[k]); END_FOR
tStable(IN := ABS(aTemp[0] - aSet[0]) < 2 AND ABS(aTemp[1] - aSet[1]) < 2 AND ABS(aTemp[2] - aSet[2]) < 2, PT := T#60S);
bReady := tStable.Q AND NOT bHold;
