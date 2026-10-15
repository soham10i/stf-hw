// FB_Transfer - delta C takes the cookies of the row in the pick window (70 mm = 31 s,
// >= 6 takts) in row order (W R B W R B) and places each into the next empty puck on the bend
// (-30..-2 deg). I1 = puck already full (recirculating): skip it, the cookie waits.
// Rows come from FB_Band (the rows really cut); a row is in the window from 1335 mm of band after its cut for
// 70 mm, then it falls off the nose (lost). The band is judged where it was when the puck arrived.
// The grip is known from the vacuum after T_GRAB (0.8 s): held -> the puck is loaded; not held -> the
// cookie stays on the band for the next puck.
FUNCTION_BLOCK FB_Transfer
VAR_IN_OUT stJob : ST_DeltaJob; aPuck : T_PuckArray; END_VAR
VAR_INPUT fMaster : LREAL; fBand : LREAL; nRows : UDINT; fRowPos : LREAL; bPuckFull : BOOL; nVacuum : INT;
    bLoad : BOOL; END_VAR
VAR_OUTPUT bVacuum : BOOL; nLoaded, nGripFail, nRecirc, nEmpty, nLost, nTrackErr : DINT; END_VAR
VAR fbArr : FB_Arrivals; aRow : ARRAY[0..31] OF LREAL; nHead, nTail, nCol, pk, nJobPuck : INT; nSeen : UDINT;
    bFirst : BOOL := TRUE; bWait : BOOL; fGrip, fPlace, d : LREAL;
    aColFlav : ARRAY[0..5] OF INT := [0, 1, 2, 0, 1, 2];   // flavour of each column
END_VAR
IF bFirst THEN nSeen := nRows;  bFirst := FALSE; END_IF;
IF nRows <> nSeen THEN aRow[nTail] := fRowPos;  nTail := (nTail + 1) MOD 32;  nSeen := nRows; END_IF;
fbArr(fMaster := fMaster, fStation := 1550.008729295);
IF bWait AND fMaster >= fGrip THEN         // the grip of the last job
    bWait := FALSE;
    IF nVacuum <= -300 THEN
        aPuck[nJobPuck].bFull := TRUE;  aPuck[nJobPuck].nFlav := aColFlav[nCol];  aPuck[nJobPuck].nCol := nCol;
        aPuck[nJobPuck].fRowPos := aRow[nHead];  aPuck[nJobPuck].nVerdict := 0;
        aPuck[nJobPuck].bKicked := FALSE;  aPuck[nJobPuck].bPending := FALSE;
        nLoaded := nLoaded + 1;  nCol := nCol + 1;
        IF nCol >= 6 THEN nCol := 0;  nHead := (nHead + 1) MOD 32; END_IF;
    ELSE
        nGripFail := nGripFail + 1;  fPlace := fMaster;      // nothing held: vacuum off, the cookie stays
    END_IF;
END_IF;
IF fbArr.bArrive AND bLoad THEN
    pk := fbArr.nPuck;
    d := fBand - (fMaster - fbArr.fArr) * 0.114583333333;   // the band when the puck arrived
    WHILE nHead <> nTail AND d - aRow[nHead] >= 1405.000000000 DO   // past the nose: lost
        nLost := nLost + 6 - INT_TO_DINT(nCol);  nCol := 0;  nHead := (nHead + 1) MOD 32;
    END_WHILE;
    IF bPuckFull THEN                      // recirculating (or a kick that failed: the cookie is still in it)
        nRecirc := nRecirc + 1;
        IF NOT aPuck[pk].bFull THEN nTrackErr := nTrackErr + 1; END_IF;
        aPuck[pk].bKicked := FALSE;
    ELSE
        IF aPuck[pk].bFull AND NOT aPuck[pk].bKicked THEN nTrackErr := nTrackErr + 1; END_IF;
        aPuck[pk].bFull := FALSE;  aPuck[pk].bKicked := FALSE;     // kicked out: empty
        IF nHead = nTail THEN
            nEmpty := nEmpty + 1;
        ELSIF d - aRow[nHead] < 1335.000000000 THEN
            nEmpty := nEmpty + 1;                                     // the next row is not in the window yet
        ELSE
            stJob.nPuck := pk;  stJob.nCol := nCol;  stJob.nLane := -1;  stJob.fRowPos := aRow[nHead];
            stJob.fStart := fbArr.fArr;  stJob.nJob := (stJob.nJob + 1) MOD 10000;
            bWait := TRUE;  nJobPuck := pk;
            fGrip := fbArr.fArr + 16.0000;  fPlace := fbArr.fArr + 40.0000;
        END_IF;
    END_IF;
END_IF;
bVacuum := fMaster < fPlace;
