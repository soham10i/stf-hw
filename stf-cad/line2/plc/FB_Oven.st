// FB_Oven - 3 zones, PID per zone -> time-proportioning PWM (2 s) on every element's SSR
// (Tc2_ControllerToolbox). The recipe and the element plan come from oven.py via line_model:
//   Z1 210 C: TC TC1 -> E1T1 500 W top L1, E1T2 500 W top L2, E1T3 500 W top L3, E1B1 500 W bot L1, E1B2 500 W bot L2; fan QF1
//   Z2 200 C: TC TC2 -> E2T1 500 W top L3, E2B1 350 W bot L2; fan QF2
//   Z3 185 C: TC TC3 -> E3T1 500 W top L1, E3B1 350 W bot L3; fan QF3
// Steady load at 900 cookies/h: Z1 1514 W, Z2 569 W, Z3 563 W.
// bReady (all zones within +-5 K for 60 s) gates the depositor: no dough goes into a cold oven.
// The zone STB (second element of the duplex TC, SF4) drops KHn by hardware - this block only reads <TC>.STL.
FUNCTION_BLOCK FB_Oven
VAR_INPUT  bRunEnable : BOOL; END_VAR
VAR_OUTPUT bReady : BOOL; aTemp : ARRAY[0..2] OF LREAL; aDuty : ARRAY[0..2] OF LREAL;
           fPower_W : LREAL; END_VAR
VAR
    aPid : ARRAY[0..2] OF FB_CTRL_PID;  aPwm : ARRAY[0..2] OF FB_CTRL_PWM_OUT;
    aSet : ARRAY[0..2] OF LREAL := [210.0, 200.0, 185.0];   // degC (oven.py recipe)
    tStable : TON;
END_VAR
aTemp[0] := INT_TO_LREAL(GVL_IO.tcTC1) / 10.0;
aTemp[1] := INT_TO_LREAL(GVL_IO.tcTC2) / 10.0;
aTemp[2] := INT_TO_LREAL(GVL_IO.tcTC3) / 10.0;
// zone k: aPid[k](fSetpointValue := aSet[k], fActualValue := aTemp[k]); aDuty[k] := aPid[k].fOut;
//         aPwm[k](fIn := aDuty[k], tPeriod := T#2S) -> every element SSR of zone k (top/bottom share TOP_SHARE)
// Z1: GVL_IO.qE1T1 := GVL_IO.qE1T2 := GVL_IO.qE1T3 := GVL_IO.qE1B1 := GVL_IO.qE1B2 := aPwm[0].bOut AND bRunEnable;
// Z2: GVL_IO.qE2T1 := GVL_IO.qE2B1 := aPwm[1].bOut AND bRunEnable;
// Z3: GVL_IO.qE3T1 := GVL_IO.qE3B1 := aPwm[2].bOut AND bRunEnable;
GVL_IO.qQF1 := bRunEnable;   // Z1 circulation fan
GVL_IO.qQF2 := bRunEnable;   // Z2 circulation fan
GVL_IO.qQF3 := bRunEnable;   // Z3 circulation fan
tStable(IN := ABS(aTemp[0] - aSet[0]) < 5.0 AND ABS(aTemp[1] - aSet[1]) < 5.0 AND ABS(aTemp[2] - aSet[2]) < 5.0, PT := T#60S);
bReady := tStable.Q;
