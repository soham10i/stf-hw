// FB_DeltaPicker - conveyor tracking pick of a moving cookie, place into the lane pocket.
// Kinematics: the NC delta transformation (TF5110-class, licence to confirm) with conveyor tracking coupled to the
// master axis executes stJob (the puck, the lane, the master position to start at). A is upstream and picks; B
// catches what A missed (N+1). Placement budget: backlash + steps <= DELTA_REP (line_model.sizing, the Jacobian).
// A passing pass-verdict cookie is taken if the delta is free (after its last pick, 2 s) and its lane is not
// indexing, early enough to grip (0.8 s) before the puck leaves the reach; else B counts it missed (it
// recirculates). The grip is known from the vacuum at T_GRAB: the pick is booked when it is decided (the tray fill,
// a full tray indexes the lane: blocked 2 s) and taken back if the cup holds nothing.
FUNCTION_BLOCK FB_DeltaPicker
VAR_IN_OUT stJob : ST_DeltaJob; aPuck : T_PuckArray; aLane : T_LaneArray; END_VAR
VAR_INPUT fMaster : LREAL; nDelta : INT; fIn : LREAL; fOut : LREAL; nVacuum : INT; END_VAR
VAR_OUTPUT bVacuum : BOOL; bMissed : BOOL; nPicks, nPickFail, nMissed, nRollback : DINT; END_VAR
VAR fbArr : FB_Arrivals; pk, f, q : INT; t, tOut, tStart, tNow, fBusy, fHold : LREAL;
    aFill : ARRAY[0..2] OF INT;            // cookies in this delta's tray, per lane
    aQPuck, aQLane : ARRAY[0..3] OF INT; aQStart, aQPrev : ARRAY[0..3] OF LREAL; aQPack : ARRAY[0..3] OF BOOL;
    nQHead, nQTail : INT;                  // the jobs given to the delta, not yet gripped
END_VAR
tNow := fMaster / 20.0;
fbArr(fMaster := fMaster, fStation := fIn);
bMissed := FALSE;
IF fbArr.bArrive THEN
    pk := fbArr.nPuck;
    IF aPuck[pk].bFull AND NOT aPuck[pk].bPending AND NOT aPuck[pk].bKicked AND aPuck[pk].nVerdict = 1 THEN
        f := aPuck[pk].nFlav;
        t := fbArr.fArr / 20.0;
        tOut := t + (fOut - fIn) / 20.0;
        tStart := MAX(t, MAX(fBusy, aLane[f].fBlock));
        IF tStart + 0.8 <= tOut AND aLane[f].bCanPack THEN
            fBusy := tStart + 2.0;
            stJob.nPuck := pk;  stJob.nCol := aPuck[pk].nCol;  stJob.nLane := f;  stJob.fRowPos := aPuck[pk].fRowPos;
            stJob.fStart := tStart * 20.0;  stJob.nJob := (stJob.nJob + 1) MOD 10000;
            aPuck[pk].bPending := TRUE;
            aQPuck[nQTail] := pk;  aQLane[nQTail] := f;  aQStart[nQTail] := tStart;  aQPack[nQTail] := FALSE;
            aFill[f] := aFill[f] + 1;
            IF aFill[f] >= 3 THEN       // the tray is full: the lane indexes when this pick ends
                aFill[f] := 0;  aQPack[nQTail] := TRUE;  aQPrev[nQTail] := aLane[f].fBlock;
                aLane[f].fBlock := fBusy + 2.0;  aLane[f].fPackAt := fBusy;
                aLane[f].nPackReq := aLane[f].nPackReq + 1;
            END_IF;
            nQTail := (nQTail + 1) MOD 4;
        ELSIF nDelta = 1 THEN
            bMissed := TRUE;  nMissed := nMissed + 1;
        END_IF;
    END_IF;
END_IF;
IF nQHead <> nQTail THEN                   // the grip of the oldest job
    IF tNow >= aQStart[nQHead] + 0.8 THEN
        pk := aQPuck[nQHead];  f := aQLane[nQHead];
        IF nVacuum <= -300 THEN
            aPuck[pk].bFull := FALSE;  aPuck[pk].bPending := FALSE;  nPicks := nPicks + 1;
            fHold := aQStart[nQHead] + 2.0;   // held until it is placed
        ELSE                               // not held: the cookie rides on, the booking is taken back
            aPuck[pk].bPending := FALSE;  nPickFail := nPickFail + 1;
            IF aQPack[nQHead] THEN
                aFill[f] := 2;  aLane[f].fBlock := aQPrev[nQHead];  aLane[f].nPackReq := aLane[f].nPackReq - 1;
            ELSE
                aFill[f] := aFill[f] - 1;
            END_IF;
            q := (nQHead + 1) MOD 4;       // a later job of this delta already booked on the taken-back fill
            IF q <> nQTail THEN nRollback := nRollback + 1; END_IF;
        END_IF;
        nQHead := (nQHead + 1) MOD 4;
    END_IF;
END_IF;
bVacuum := tNow < fHold;
IF nQHead <> nQTail THEN
    IF tNow >= aQStart[nQHead] THEN bVacuum := TRUE; END_IF;
END_IF;
