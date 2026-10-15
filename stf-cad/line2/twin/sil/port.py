"""
DT-4a: the generated TwinCAT program (plc/*.st) -> ONE portable IEC 61131-3 project that MatIEC compiles.

The function-block BODIES are not rewritten: each rule below maps a TwinCAT construct to its IEC / simulation
equivalent, and twin/sil_check.py proves the bodies are the generated ones apart from these rules.

  R1  pragmas {attribute ...}                         removed
  R2  GVL_IO.<name> (qualified_only)                  <name>; the POU gets VAR_EXTERNAL <name> : <type>
  R3  AT %I* / AT %Q* (linked in the I/O tree)        located: BOOL %IX / %QX, INT %IW, UDINT %ID, in signal order;
                                                      IO-Link arrays and timestamp structs stay unlocated (DT-4b)
  R4  AXIS_REF + Tc2_MC2 (MC_Power, MC_MoveVelocity,  SIM_MC: AXIS_REF {NcToPlc, PlcToNc} and the FBs with PLCopen
      MC_GearIn, MC_GearOut, MC_Halt, MC_Direction)   semantics (Execute edges, Status / Done); the NC itself (the
                                                      position loop) is the plant's (twin/sil/nc.py)
  R5  axes <-> the plant                              PROGRAM SIL_IN copies the NC's located feedback into each
                                                      AXIS_REF before MAIN, PROGRAM SIL_OUT its commands out after
  R6  VAR PERSISTENT                                  VAR RETAIN
  R7  LMOD (Tc2_Standard)                             FUNCTION LMOD (floored modulo)
  R8  '//' comments                                   (* ... *)
  R9  a POU file without END_*                        END_FUNCTION_BLOCK / END_FUNCTION / END_PROGRAM appended
  R10 the task (10 ms) + VAR_GLOBAL                   CONFIGURATION / RESOURCE / TASK, programs SIL_IN, MAIN, SIL_OUT
  R11 not portable, and not instantiated by MAIN      left out, listed: FB_Policy (Tc3_MLL, a licensed TwinCAT ML
                                                      library), ST_PuckEvent (refers to E_Station / E_Outcome, which
                                                      are never generated - finding)
  R13 ARRAY[..] OF <function block> (IEC 3rd ed.)   expanded into one instance per index (MatIEC is 2nd ed.)
  R12 a POU without statements (a stub)               a no-op (sil_stub := FALSE) - and the POU is LISTED as a stub
  R14 job channels: ST_DeltaJob (PLC -> a delta's     located SIL variables, copied like the axes (R5): SIL_OUT
      motion program), ST_QcResult (edge PC -> PLC)   writes each ST_DeltaJob field out, SIL_IN reads ST_QcResult in
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(os.path.dirname(HERE))
PLC = os.environ.get("STF_SIL_PLC", os.path.join(LINE2, "plc"))   # a mutant's copy in the gate
SCAN_MS = 10
EXCLUDED = {"FB_Policy.st": "Tc3_MLL FB_MllPrediction: a licensed TwinCAT ML library, no IEC equivalent; "
                            "not instantiated by MAIN"}
AXES_USED = ("axQ1", "axQ40", "axQ41", "axMasterEnc", "axQ20", "axQ21", "axQ22")   # the axes the stations use
CHANNELS = {"ST_DeltaJob": "out", "ST_QcResult": "in"}   # R14: the struct channels and their direction

SIM_MC = """
TYPE MC_Direction : (MC_Positive_Direction, MC_Shortest_Way, MC_Negative_Direction, MC_Current_Direction); END_TYPE
TYPE ST_NcToPlc : STRUCT ActPos : LREAL; ActVelo : LREAL; Enabled : BOOL; END_STRUCT; END_TYPE
TYPE ST_PlcToNc : STRUCT
    Enable : BOOL; Mode : INT; Velocity : LREAL; Accel : LREAL; Ratio : LREAL; Target : LREAL;
END_STRUCT; END_TYPE
(* Mode: 0 standstill, 1 velocity, 2 geared to the master (Ratio), 3 halt (ramp to 0), 4 free (keep velocity),
   5 position (to Target at Velocity, Accel) *)
TYPE AXIS_REF : STRUCT NcToPlc : ST_NcToPlc; PlcToNc : ST_PlcToNc; END_STRUCT; END_TYPE

FUNCTION_BLOCK MC_Power
VAR_IN_OUT Axis : AXIS_REF; END_VAR
VAR_INPUT Enable : BOOL; Enable_Positive : BOOL; Enable_Negative : BOOL; END_VAR
VAR_OUTPUT Status : BOOL; END_VAR
Axis.PlcToNc.Enable := Enable;
Status := Enable AND Axis.NcToPlc.Enabled;
END_FUNCTION_BLOCK

FUNCTION_BLOCK MC_MoveVelocity
VAR_IN_OUT Axis : AXIS_REF; END_VAR
VAR_INPUT Execute : BOOL; Velocity : LREAL; Acceleration : LREAL; Deceleration : LREAL; Direction : MC_Direction; END_VAR
VAR_OUTPUT InVelocity : BOOL; Busy : BOOL; END_VAR
VAR rTrig : R_TRIG; END_VAR
rTrig(CLK := Execute);
IF rTrig.Q THEN                               (* PLCopen: the command is taken on the rising edge *)
    Axis.PlcToNc.Mode := 1;
    Axis.PlcToNc.Velocity := SEL(Direction = MC_Negative_Direction, Velocity, -Velocity);
    Axis.PlcToNc.Accel := Acceleration;
END_IF;
Busy := Axis.PlcToNc.Mode = 1;
InVelocity := Busy AND ABS(Axis.NcToPlc.ActVelo - Axis.PlcToNc.Velocity) < 1.0E-6;
END_FUNCTION_BLOCK

FUNCTION_BLOCK MC_GearIn
VAR_IN_OUT Master : AXIS_REF; Slave : AXIS_REF; END_VAR
VAR_INPUT Execute : BOOL; RatioNumerator : LREAL; RatioDenominator : UINT; END_VAR   (* as Tc2_MC2 *)
VAR_OUTPUT InGear : BOOL; END_VAR
VAR rTrig : R_TRIG; END_VAR
rTrig(CLK := Execute);
IF rTrig.Q THEN                               (* couples on the rising edge; a FALLING Execute does NOT decouple *)
    Slave.PlcToNc.Mode := 2;
    Slave.PlcToNc.Ratio := RatioNumerator / UINT_TO_LREAL(RatioDenominator);
END_IF;
InGear := Slave.PlcToNc.Mode = 2;
END_FUNCTION_BLOCK

FUNCTION_BLOCK MC_GearOut
VAR_IN_OUT Slave : AXIS_REF; END_VAR
VAR_INPUT Execute : BOOL; END_VAR
VAR_OUTPUT Done : BOOL; END_VAR
VAR rTrig : R_TRIG; END_VAR
rTrig(CLK := Execute);
IF rTrig.Q AND Slave.PlcToNc.Mode = 2 THEN    (* decoupled: the slave keeps its velocity (PLCopen) *)
    Slave.PlcToNc.Mode := 4;
END_IF;
Done := Execute AND Slave.PlcToNc.Mode <> 2;
END_FUNCTION_BLOCK

FUNCTION_BLOCK MC_Halt
VAR_IN_OUT Axis : AXIS_REF; END_VAR
VAR_INPUT Execute : BOOL; Deceleration : LREAL; END_VAR
VAR_OUTPUT Done : BOOL; END_VAR
VAR rTrig : R_TRIG; END_VAR
rTrig(CLK := Execute);
IF rTrig.Q THEN Axis.PlcToNc.Mode := 3;  Axis.PlcToNc.Accel := Deceleration; END_IF;
Done := Axis.PlcToNc.Mode = 3 AND ABS(Axis.NcToPlc.ActVelo) < 1.0E-9;
END_FUNCTION_BLOCK

FUNCTION_BLOCK MC_MoveRelative
VAR_IN_OUT Axis : AXIS_REF; END_VAR
VAR_INPUT Execute : BOOL; Distance : LREAL; Velocity : LREAL; Acceleration : LREAL; Deceleration : LREAL; END_VAR
VAR_OUTPUT Done : BOOL; Busy : BOOL; END_VAR
VAR rTrig : R_TRIG; END_VAR
rTrig(CLK := Execute);
IF rTrig.Q THEN                               (* from where the axis is, on the rising edge *)
    Axis.PlcToNc.Mode := 5;  Axis.PlcToNc.Target := Axis.NcToPlc.ActPos + Distance;
    Axis.PlcToNc.Velocity := Velocity;  Axis.PlcToNc.Accel := Acceleration;
    Busy := TRUE;  Done := FALSE;
END_IF;
IF Busy AND Axis.PlcToNc.Mode = 5 AND ABS(Axis.NcToPlc.ActPos - Axis.PlcToNc.Target) < 1.0E-6
   AND ABS(Axis.NcToPlc.ActVelo) < 1.0E-9 THEN
    Busy := FALSE;  Done := TRUE;
END_IF;
IF NOT Execute THEN Done := FALSE; END_IF;
END_FUNCTION_BLOCK

FUNCTION LMOD : LREAL                         (* Tc2_Standard LMOD: floored modulo of LREALs *)
VAR_INPUT x : LREAL; y : LREAL; END_VAR
LMOD := x - y * LINT_TO_LREAL(TRUNC(x / y));
IF LMOD < 0.0 THEN LMOD := LMOD + y; END_IF;
END_FUNCTION
"""


def _comments(src):
    out = []
    for line in src.split("\n"):
        i = line.find("//")
        if i >= 0:
            text = line[i + 2:].replace("(*", "( *").replace("*)", "* )")
            line = line[:i] + "(*" + text + " *)"
        out.append(line)
    return "\n".join(out)


def _gvl():
    """[(name, type, located or '', comment)] from GVL_IO.st; located addresses assigned in signal order."""
    src = open(os.path.join(PLC, "GVL_IO.st")).read()
    out, n = [], {"IX": 0, "QX": 0, "IW": 0, "QW": 0, "ID": 0}
    for m in re.finditer(r"^\s{4}(\w+)\s+(AT %[IQ]\*)?\s*:\s*([^;]+);", src, re.M):
        name, at, typ = m.group(1), m.group(2), m.group(3).strip()
        loc = ""
        if at:
            d = at[4]
            if typ == "BOOL":
                k = n[f"{d}X"]
                loc = f"%{d}X{k // 8}.{k % 8}"
                n[f"{d}X"] += 1
            elif typ == "INT":
                loc = f"%{d}W{n[f'{d}W']}"
                n[f"{d}W"] += 1
            elif typ == "UDINT" and d == "I":
                loc = f"%ID{n['ID']}"
                n["ID"] += 1
        out.append((name, typ, loc))
    return out


def project():
    """(IEC source, info) - the whole program, ready for iec2c."""
    gvl = _gvl()
    gtype = {n: t for n, t, _ in gvl}
    parts, info = [], dict(excluded=EXCLUDED, pous=[], externals={})
    dut = open(os.path.join(PLC, "DUT_PhysicalAI.st")).read()
    keep = [m.group(0) for m in re.finditer(r"TYPE\s+((?:ST_|E_|T_)\w+)\s*:.*?END_TYPE", dut, re.S)
            if m.group(1) != "ST_PuckEvent"]
    fields = {m.group(1): re.findall(r"(\w+(?:\s*,\s*\w+)*)\s*:\s*(\w+)\s*;", re.sub(r"//[^\n]*", "", m.group(2)))
              for m in re.finditer(r"TYPE\s+(ST_\w+)\s*:\s*STRUCT(.*?)END_STRUCT", dut, re.S)}
    info["excluded"]["DUT_PhysicalAI.st: ST_PuckEvent"] = "refers to E_Station / E_Outcome, never generated"
    parts.append(SIM_MC)
    parts += keep
    order = ["F_InSlice.st"] + sorted(f for f in os.listdir(PLC) if f.startswith("FB_") and f not in EXCLUDED) + \
        ["MAIN.st"]
    for f in order:
        src = open(os.path.join(PLC, f)).read()
        src = re.sub(r"\{attribute[^}]*\}", "", src)                              # R1
        used = sorted(set(re.findall(r"GVL_IO\.(\w+)", src)))
        src = src.replace("GVL_IO.", "")                                           # R2
        src = re.sub(r"\bVAR PERSISTENT\b", "VAR RETAIN", src)                      # R6
        for m in list(re.finditer(r"(\w+)\s*:\s*ARRAY\[(\d+)\.\.(\d+)\]\s+OF\s+(FB_\w+)\s*;", src)):   # R13
            name, lo, hi, fb = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
            if re.search(rf"\b{name}\[(?!\d+\])", src):
                raise SystemExit(f"R13: {name}[...] indexed by a non-literal in {f} - cannot expand")
            src = src.replace(m.group(0), ", ".join(f"{name}_{k}" for k in range(lo, hi + 1)) + f" : {fb};")
            src = re.sub(rf"\b{name}\[(\d+)\]", rf"{name}_\1", src)
            info.setdefault("expanded", []).append(f"{name}: ARRAY[{lo}..{hi}] OF {fb}")
        kind = re.search(r"^(FUNCTION_BLOCK|FUNCTION|PROGRAM)\s+(\w+)", src, re.M)
        lines = src.rstrip("\n").split("\n")
        if used:                                                                    # R2: VAR_EXTERNAL
            ext = "VAR_EXTERNAL " + " ".join(f"{u} : {gtype[u]};" for u in used) + " END_VAR"
            head = next(i for i, ln in enumerate(lines) if ln.startswith(kind.group(0)))
            last = max([i for i, ln in enumerate(lines) if re.search(r"\bEND_VAR\b", ln)] or [head])
            # a block may end on the same line it starts; insert after the last END_VAR of the declarations
            lines.insert(last + 1, ext)
            info["externals"][kind.group(2)] = used
        body = [ln for ln in lines[max([i for i, ln in enumerate(lines) if re.search(r"\bEND_VAR\b", ln)] or
                                       [next(i for i, ln in enumerate(lines) if ln.startswith(kind.group(0)))]) + 1:]
                if ln.strip() and not ln.strip().startswith("//")]
        if not body:                                                                # R12: a stub
            lines.append("VAR sil_stub : BOOL; END_VAR   // STUB: no statements generated yet")
            lines.append("sil_stub := FALSE;")
            info.setdefault("stubs", []).append(kind.group(2))
        end = {"FUNCTION_BLOCK": "END_FUNCTION_BLOCK", "FUNCTION": "END_FUNCTION", "PROGRAM": "END_PROGRAM"}
        lines.append(end[kind.group(1)])                                            # R9
        parts.append("\n".join(lines))
        info["pous"].append(kind.group(2))
    # R5: the axes <-> the plant's NC
    ax_in, ax_out, glob = [], [], []
    il = ql = 0
    for a in AXES_USED:
        glob += [f"    sil_{a}_ActPos AT %IL{il} : LREAL;", f"    sil_{a}_ActVelo AT %IL{il + 1} : LREAL;",
                 f"    sil_{a}_Enabled AT %IX100.{AXES_USED.index(a)} : BOOL;",
                 f"    sil_{a}_Enable AT %QX100.{AXES_USED.index(a)} : BOOL;",
                 f"    sil_{a}_Mode AT %QW{200 + AXES_USED.index(a)} : INT;",
                 f"    sil_{a}_Velocity AT %QL{ql} : LREAL;", f"    sil_{a}_Accel AT %QL{ql + 1} : LREAL;",
                 f"    sil_{a}_Ratio AT %QL{ql + 2} : LREAL;", f"    sil_{a}_Target AT %QL{ql + 3} : LREAL;"]
        il += 2
        ql += 4
        ax_in += [f"{a}.NcToPlc.ActPos := sil_{a}_ActPos;", f"{a}.NcToPlc.ActVelo := sil_{a}_ActVelo;",
                  f"{a}.NcToPlc.Enabled := sil_{a}_Enabled;"]
        ax_out += [f"sil_{a}_Enable := {a}.PlcToNc.Enable;", f"sil_{a}_Mode := {a}.PlcToNc.Mode;",
                   f"sil_{a}_Velocity := {a}.PlcToNc.Velocity;", f"sil_{a}_Accel := {a}.PlcToNc.Accel;",
                   f"sil_{a}_Ratio := {a}.PlcToNc.Ratio;", f"sil_{a}_Target := {a}.PlcToNc.Target;"]
    # R14: the job channels -> located SIL variables (INT %IW / %QW from 300, LREAL after the axes' %IL / %QL)
    ch_vars = []
    w = {"I": 300, "Q": 300}
    lw = {"I": il, "Q": ql}
    for n, t, _ in gvl:
        if t not in CHANNELS:
            continue
        ch_vars.append(f"{n} : {t};")
        d = "I" if CHANNELS[t] == "in" else "Q"
        for names, ft in fields[t]:
            for fn in [x.strip() for x in names.split(",")]:
                if ft == "INT":
                    loc = f"%{d}W{w[d]}"
                    w[d] += 1
                else:
                    loc = f"%{d}L{lw[d]}"
                    lw[d] += 1
                glob.append(f"    sil_{n}_{fn} AT {loc} : {ft};")
                if d == "I":
                    ax_in.append(f"{n}.{fn} := sil_{n}_{fn};")
                else:
                    ax_out.append(f"sil_{n}_{fn} := {n}.{fn};")
    sil_ext = "VAR_EXTERNAL " + " ".join(f"{a} : AXIS_REF;" for a in AXES_USED) + " " + " ".join(ch_vars) + " " + \
        " ".join(g.strip().split(" AT ")[0] + " : " + g.split(":")[-1].strip() for g in glob) + " END_VAR"
    parts.append("PROGRAM SIL_IN\n" + sil_ext + "\n" + "\n".join(ax_in) + "\nEND_PROGRAM")
    parts.append("PROGRAM SIL_OUT\n" + sil_ext + "\n" + "\n".join(ax_out) + "\nEND_PROGRAM")
    cfg = ["CONFIGURATION Line", "VAR_GLOBAL"]
    for n, t, loc in gvl:
        cfg.append(f"    {n}{' AT ' + loc if loc else ''} : {t};")
    cfg += glob
    cfg += ["END_VAR", "    RESOURCE Plc ON PLC",
            f"        TASK Scan(INTERVAL := T#{SCAN_MS}MS, PRIORITY := 0);",
            "        PROGRAM SilIn WITH Scan : SIL_IN;", "        PROGRAM Run WITH Scan : MAIN;",
            "        PROGRAM SilOut WITH Scan : SIL_OUT;", "    END_RESOURCE", "END_CONFIGURATION"]
    parts.append("\n".join(cfg))
    src = _comments("\n\n".join(parts)) + "\n"                                      # R8
    info["gvl"] = gvl
    return src, info


if __name__ == "__main__":
    s, i = project()
    print(f"{s.count(chr(10))} lines, POUs {i['pous']}, excluded {list(i['excluded'])}")
