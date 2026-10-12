// FB_Band - the mesh band (2.292 mm/s) and the depositor rolls are GEARED to the master axis:
// one row of 6 per 6 pucks (24 s). The wire is cammed from the rolls.
// Topping: rows k and k+3 get flavour k (Q2/Q3/Q4), 100 mm after the die.
// A cold oven (bOvenReady FALSE) stops the depositor, never the band: what is in the oven bakes out.
// aZoneContent (the oven's feed-forward): every row the depositor cuts (the rolls' measured motion, AND dough in the
// hopper - IOL1) is remembered at the band position of its cut; a zone's content = the rows between its walls / the
// 3.69 rows a full zone holds. Turning rolls on an empty hopper cut nothing (DT-4a finding 15).
FUNCTION_BLOCK FB_Band
VAR_IN_OUT axBand : AXIS_REF; axRolls : AXIS_REF; axMaster : AXIS_REF; END_VAR   // by reference (MC blocks)
VAR_INPUT bOvenReady : BOOL; nDoughLevel : INT; END_VAR   // nDoughLevel: IOL1 distance to the dough, 0.1 mm
VAR_OUTPUT fPos : LREAL; aZoneContent : T_ZoneArray;   // 0..1 per zone, from the rows cut
    nRows : UDINT; fRowPos : LREAL;        // rows cut so far, the band position of the last (-> FB_Transfer)
END_VAR
VAR RETAIN                                 // the rows on the band survive a power cycle (they are still there)
    aCut : ARRAY[0..31] OF LREAL;          // band position of each row cut (ring), -1 = empty
    nCut : INT; fLastCut : LREAL; bFirst : BOOL := TRUE;
END_VAR
VAR fbGearBand, fbGearRolls : MC_GearIn; fbGearOutRolls : MC_GearOut; fbHaltRolls : MC_Halt;
    k, i : INT; d : LREAL; fDough : LREAL;   // kg of dough in the hopper
    fDoughRow : LREAL;                     // the most dough seen while this row was pressed out
    aZoneOff : ARRAY[0..2] OF LREAL := [200.0, 403.0, 606.0];   // die -> zone start, mm of band
END_VAR
fbGearBand(Master := axMaster, Slave := axBand, Execute := TRUE, RatioNumerator := 2.291666666667,
           RatioDenominator := 20);   // band mm/s per master mm/s: exact (rounded, rows drift: finding 17)
fbGearRolls(Master := axMaster, Slave := axRolls, Execute := bOvenReady, RatioNumerator := 1.0, RatioDenominator := 1);
// a FALLING Execute does not decouple a geared slave (PLCopen): oven not ready -> decouple the rolls, then brake them
fbGearOutRolls(Slave := axRolls, Execute := NOT bOvenReady);
fbHaltRolls(Axis := axRolls, Execute := NOT bOvenReady AND fbGearOutRolls.Done, Deceleration := 40.0);
fPos := axBand.NcToPlc.ActPos;
fDough := (276.0 - INT_TO_LREAL(nDoughLevel) * 0.1) * 0.111090;
fDoughRow := MAX(fDoughRow, fDough);       // the level drops as the slug leaves: judge the row on the level before
IF bFirst THEN
    FOR i := 0 TO 31 DO aCut[i] := -1.0; END_FOR;
    fLastCut := fPos;  bFirst := FALSE;
END_IF;
IF fPos - fLastCut >= 55.0000 THEN                  // one row pitch of band: the wire cuts a row if the rolls run
    fLastCut := fLastCut + 55.0000;
    // a row exists if the rolls REALLY turned (their actual velocity), not if they were told to: a halt brakes;
    // and only from a hopper holding a row's dough (6 x 0.0112 kg)
    IF ABS(axRolls.NcToPlc.ActVelo) > 0.0 AND fDoughRow >= 0.0672 THEN
        aCut[nCut] := fLastCut;  nCut := (nCut + 1) MOD 32;  nRows := nRows + 1;  fRowPos := fLastCut;
    END_IF;
    fDoughRow := fDough;
END_IF;
FOR k := 0 TO 2 DO
    aZoneContent[k] := 0.0;
    FOR i := 0 TO 31 DO
        IF aCut[i] >= 0.0 THEN
            d := fPos - aCut[i];
            IF d >= aZoneOff[k] AND d < aZoneOff[k] + 203.0 THEN
                aZoneContent[k] := aZoneContent[k] + 0.270936;
            END_IF;
        END_IF;
    END_FOR;
    aZoneContent[k] := MIN(aZoneContent[k], 1.0);
END_FOR;
