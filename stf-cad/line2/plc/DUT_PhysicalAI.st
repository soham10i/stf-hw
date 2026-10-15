// timestamped I/O and the record every learned model is trained on
TYPE ST_TsInput : STRUCT bNewEdge : BOOL; nTimestamp : ULINT; END_STRUCT; END_TYPE     // EL1252 (DC ns)
TYPE ST_TsOutput : STRUCT bArm : BOOL; nFireAt : ULINT; END_STRUCT; END_TYPE          // EL2252 (DC ns)
// station states: named types (an enumeration declared inline in a VAR block is not portable)
TYPE T_ZoneArray : ARRAY[0..2] OF LREAL; END_TYPE   // per oven zone (one named type: FB_Band -> FB_Oven)
TYPE E_PickState : (WAIT, TRACK, GRIP, LIFT, PLACE, RELEASE, HOME); END_TYPE
TYPE E_AirlockOut : (IDLE, CARRY_OUT, INNER_CLOSE, OUTER_OPEN, SWAP, OUTER_CLOSE, INNER_OPEN, CARRY_IN); END_TYPE
// the stations (DT-4b)
TYPE ST_DeltaJob : STRUCT              // PLC -> a delta's motion program: a new nJob starts the job
    nJob : INT; nPuck : INT; nCol : INT; nLane : INT;   // C: the band row (fRowPos) + column -> puck; A/B: puck -> lane
    fRowPos : LREAL; fStart : LREAL;                    // band mm of the row's cut; master mm to start at
END_STRUCT; END_TYPE
TYPE ST_QcResult : STRUCT nSeq : INT; nPuck : INT; nVerdict : INT; END_STRUCT; END_TYPE   // edge PC: 1 pass, 2 reject
TYPE ST_Puck : STRUCT
    bFull : BOOL; bKicked : BOOL; bPending : BOOL;      // pending: a pick is decided, its grip not yet known
    nFlav : INT; nCol : INT; nVerdict : INT; fRowPos : LREAL;
END_STRUCT; END_TYPE
TYPE T_PuckArray : ARRAY[0..47] OF ST_Puck; END_TYPE
TYPE ST_Lane : STRUCT fBlock : LREAL; fPackAt : LREAL; nPackReq : INT; bCanPack : BOOL; END_STRUCT; END_TYPE   // s (master)
TYPE T_LaneArray : ARRAY[0..2] OF ST_Lane; END_TYPE
TYPE ST_PuckEvent : STRUCT
    nPuck : UINT; sNfc : STRING(16); nDcTime : ULINT; fMasterPos : LREAL;
    eStation : E_Station; aSignals : ARRAY[0..15] OF REAL; nImageId : UDINT; eOutcome : E_Outcome;
END_STRUCT; END_TYPE
