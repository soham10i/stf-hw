// FB_QC - camera verdict (edge PC via ADS) + colour sensor; kick on the fly.
// Camera -> kicker = 110 mm = 5.5 s >= AI latency 0.5 s.
FUNCTION_BLOCK FB_QC
VAR_INPUT fMasterPos : LREAL; END_VAR
VAR fKickPos : LREAL := 2181.7; aReject : ARRAY[0..47] OF BOOL; END_VAR
// verdict k arrives -> aReject[k] := TRUE; write NFC-W2; when puck k reaches fKickPos: pulse GVL_IO.qQ18 200 ms
