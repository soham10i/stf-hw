// FB_CameraTrigger - fire every camera at a puck's master position via EL2252 (DC time), so each image
// is exactly aligned with the puck (NFC id), the master position and every other sensor sample.
FUNCTION_BLOCK FB_CameraTrigger
VAR_INPUT fMasterPos : LREAL; fTriggerPos : LREAL; END_VAR
VAR_IN_OUT stOut : ST_TsOutput; END_VAR
// nFireAt := DC time now + (fTriggerPos - fMasterPos) / 20 mm/s -> the terminal fires on the ns
