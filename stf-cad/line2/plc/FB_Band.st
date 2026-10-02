// FB_Band - the mesh band (2.292 mm/s) and the depositor rolls are GEARED to the master axis:
// one row of 6 per 6 pucks (24 s). The wire is cammed from the rolls.
// Topping: rows k and k+3 get flavour k (Q2/Q3/Q4), 100 mm after the die.
// A cold oven (bOvenReady FALSE) stops the depositor, never the band: what is in the oven bakes out.
FUNCTION_BLOCK FB_Band
VAR_INPUT axBand : AXIS_REF; axRolls : AXIS_REF; axMaster : AXIS_REF; bOvenReady : BOOL; END_VAR
VAR_OUTPUT fPos : LREAL; aZoneContent : ARRAY[0..2] OF LREAL; END_VAR   // 0..1 per zone, from the rows cut
VAR fbGearBand, fbGearRolls : MC_GearIn; END_VAR
fbGearBand(Master := axMaster, Slave := axBand, Execute := TRUE, RatioNumerator := 2292,
           RatioDenominator := 20000);
fbGearRolls(Master := axMaster, Slave := axRolls, Execute := bOvenReady, RatioNumerator := 1, RatioDenominator := 1);
fPos := axBand.NcToPlc.ActPos;
