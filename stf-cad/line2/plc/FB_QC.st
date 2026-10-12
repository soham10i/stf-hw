// FB_QC - camera verdict (edge PC via ADS: stQc, one per puck) + colour sensor; kick on the fly.
// Camera -> kicker = 110 mm = 5.5 s >= AI latency 0.5 s.
// A rejected cookie is kicked when its puck reaches the kicker (200 ms pulse). Whether it left is
// known at the transfer (I1): until then the puck is 'kicked' and keeps its data.
FUNCTION_BLOCK FB_QC
VAR_IN_OUT aPuck : T_PuckArray; END_VAR
VAR_INPUT fMaster : LREAL; stQc : ST_QcResult; END_VAR
VAR_OUTPUT bKick : BOOL; nKicks, nVerdicts : DINT; END_VAR
VAR fbKick : FB_Arrivals; nSeen, pk : INT; fKickEnd : LREAL; bFirst : BOOL := TRUE; END_VAR
IF bFirst THEN nSeen := stQc.nSeq;  bFirst := FALSE; END_IF;
IF stQc.nSeq <> nSeen THEN                 // a new verdict: 1 pass, 2 reject
    nSeen := stQc.nSeq;  aPuck[stQc.nPuck].nVerdict := stQc.nVerdict;  nVerdicts := nVerdicts + 1;
END_IF;
fbKick(fMaster := fMaster, fStation := 2181.718530718);
IF fbKick.bArrive THEN
    pk := fbKick.nPuck;
    IF aPuck[pk].bFull AND NOT aPuck[pk].bKicked AND aPuck[pk].nVerdict = 2 THEN
        aPuck[pk].bKicked := TRUE;  fKickEnd := fbKick.fArr + 4.0000;  nKicks := nKicks + 1;
    END_IF;
END_IF;
bKick := fMaster < fKickEnd;
