// FB_SafetyIf - the STANDARD side of the TwinSAFE project (EL6910). It never switches a safe
// output: it sends REQUESTS (unlock a door, mute a port, reset) and reads STATUS via the EL6910's
// standard process data. The safety functions themselves (SF1..SF6, SAFETY_CONCEPT.md, safety.py) are
// configured in the TwinSAFE editor from safety/safety_functions.csv.
//   SS1: on any stop demand the NC ramps every axis down (MC_Stop), then TwinSAFE drops K1/K2 after
//        1.20 s (longest ramp + 0.2 s margin, proven in safety.py).
//   Doors S20, S21, S22: unlock request -> TwinSAFE unlocks only after every encoder reports standstill for
//        2.5 s (the standard encoders are a plausibility input; see SAFETY_CONCEPT open items).
//   Ports: airlocks (S-1b) - FB_Airlock sequences them; TwinSAFE enforces the interlocks
//        (outer door unlocks only with the inner side shut and the zone at safe standstill).
FUNCTION_BLOCK FB_SafetyIf
VAR_OUTPUT
    bRunEnable   : BOOL;          // no stop demand active, all doors locked, all resets done
    bStopDemand  : BOOL;          // SS1 in progress -> every station: MC_Stop now
    aDoorLocked  : ARRAY[0..2] OF BOOL;
    aPortMuted   : ARRAY[0..1] OF BOOL;
END_VAR
VAR
    aUnlockReq   : ARRAY[0..2] OF BOOL;   // from the HMI
    aMuteReq     : ARRAY[0..1] OF BOOL;   // from FB_AmrPorts when an AMR is due
END_VAR
