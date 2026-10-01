// FB_Feeder - heijunka W R B ..., lead-compensated gravity drop.
// Fall time 101 ms -> the belt moves 2.02 mm: the gate opens 2.02 mm BEFORE the
// puck centre is under the tube (proven in line_model.timing). A puck the light barrier I1
// sees as full (recirculating) is skipped; an empty tube leaves the puck empty (counted loss).
FUNCTION_BLOCK FB_Feeder
VAR_INPUT fMasterPos : LREAL; END_VAR
VAR
    aTubeX   : ARRAY[0..5] OF LREAL := [50.0, 110.0, 170.0, 230.0, 290.0, 350.0];  // loop position of each tube
    aGate    : ARRAY[0..5] OF POINTER TO BOOL;
    nSeq     : UINT;                 // heijunka index
    fLead    : LREAL := 2.02;
END_VAR
aGate[0] := ADR(GVL_IO.qQ2); aGate[1] := ADR(GVL_IO.qQ3); aGate[2] := ADR(GVL_IO.qQ4);
aGate[3] := ADR(GVL_IO.qQ5); aGate[4] := ADR(GVL_IO.qQ6); aGate[5] := ADR(GVL_IO.qQ7);
// for the next puck: choose flavour nSeq MOD 3, tube A or B (the one not low: I2..I7),
// fire when LMOD(fMasterPos - aTubeX[k] + fLead, 80) crosses 0; write the tag via IO-Link (NFC-W)
