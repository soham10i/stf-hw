// FB_Transfer - delta C takes the cookies of the row in the pick window (70 mm = 31 s,
// >= 6 takts) in row order (W R B W R B) and places each into the next empty puck on the bend
// (-30..-2 deg). I1 = puck already full (recirculating): skip it, the cookie waits.
// NFC-W writes flavour (band row), batch and the bake log (zone temperatures, IR1) into the tag; I9 confirms.
FUNCTION_BLOCK FB_Transfer
VAR_INPUT fMasterPos : LREAL; fBandPos : LREAL; bPuckFull : BOOL; END_VAR
VAR nRow : UINT; nNext : UINT; END_VAR
