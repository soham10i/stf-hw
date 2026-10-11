// timestamped I/O and the record every learned model is trained on
TYPE ST_TsInput : STRUCT bNewEdge : BOOL; nTimestamp : ULINT; END_STRUCT; END_TYPE     // EL1252 (DC ns)
TYPE ST_TsOutput : STRUCT bArm : BOOL; nFireAt : ULINT; END_STRUCT; END_TYPE          // EL2252 (DC ns)
// station states: named types (an enumeration declared inline in a VAR block is not portable)
TYPE T_ZoneArray : ARRAY[0..2] OF LREAL; END_TYPE   // per oven zone (one named type: FB_Band -> FB_Oven)
TYPE E_PickState : (WAIT, TRACK, GRIP, LIFT, PLACE, RELEASE, HOME); END_TYPE
TYPE E_AirlockOut : (IDLE, CARRY_OUT, INNER_CLOSE, OUTER_OPEN, SWAP, OUTER_CLOSE, INNER_OPEN, CARRY_IN); END_TYPE
TYPE ST_PuckEvent : STRUCT
    nPuck : UINT; sNfc : STRING(16); nDcTime : ULINT; fMasterPos : LREAL;
    eStation : E_Station; aSignals : ARRAY[0..15] OF REAL; nImageId : UDINT; eOutcome : E_Outcome;
END_STRUCT; END_TYPE
