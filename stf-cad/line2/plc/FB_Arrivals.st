// FB_Arrivals - the pucks passing ONE station of the loop, from the master position alone: puck k is at the
// station when the master is at fStation - k x 80 (mod 3840.037061436, the loop); after puck k comes puck k-1.
// The arrival is reported in the scan the master passes it, with the EXACT position it happened at (fArr).
FUNCTION_BLOCK FB_Arrivals
VAR_INPUT fMaster : LREAL; fStation : LREAL; END_VAR
VAR_OUTPUT bArrive : BOOL; nPuck : INT; fArr : LREAL; END_VAR
VAR bInit : BOOL; nNext, k : INT; fNext, f : LREAL; END_VAR
bArrive := FALSE;
IF NOT bInit THEN                          // the first arrival from now on, over all 48 pucks
    fNext := fMaster + 3840.037061436;
    FOR k := 0 TO 47 DO
        f := fMaster + LMOD(fStation - INT_TO_LREAL(k) * 80.0 - fMaster, 3840.037061436);
        IF f < fNext THEN fNext := f;  nNext := k; END_IF;
    END_FOR;
    bInit := TRUE;
END_IF;
IF fMaster >= fNext THEN
    bArrive := TRUE;  nPuck := nNext;  fArr := fNext;
    nNext := (nNext + 47) MOD 48;
    fNext := fArr + LMOD(fStation - INT_TO_LREAL(nNext) * 80.0 - fArr, 3840.037061436);
END_IF;
