// FB_Oven - three zones, PID -> slow PWM on the SSRs (Tc2_ControllerToolbox)
FUNCTION_BLOCK FB_Oven
VAR
    aPid : ARRAY[0..2] OF FB_CTRL_PID;  aPwm : ARRAY[0..2] OF FB_CTRL_PWM_OUT;
    aSet : ARRAY[0..2] OF LREAL := [180.0, 180.0, 170.0];     // degC [assumed recipe]
END_VAR
// zone k: aPid[k](fSetpointValue := aSet[k], fActualValue := INT_TO_LREAL(GVL_IO.tcTC1) / 10.0, ...)
//         aPwm[k](...) -> GVL_IO.qQ8 / qQ9 / qQ10
