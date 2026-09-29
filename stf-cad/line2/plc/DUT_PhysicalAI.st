// timestamped I/O and the record every learned model is trained on
TYPE ST_TsInput : STRUCT bNewEdge : BOOL; nTimestamp : ULINT; END_STRUCT END_TYPE     // EL1252 (DC ns)
TYPE ST_TsOutput : STRUCT bArm : BOOL; nFireAt : ULINT; END_STRUCT END_TYPE          // EL2252 (DC ns)
TYPE ST_PuckEvent : STRUCT
    nPuck : UINT; sNfc : STRING(16); nDcTime : ULINT; fMasterPos : LREAL;
    eStation : E_Station; aSignals : ARRAY[0..15] OF REAL; nImageId : UDINT; eOutcome : E_Outcome;
END_STRUCT END_TYPE
