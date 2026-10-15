"""
The software-in-the-loop PLC as a live data source, shared by the Industry 4.0 interfaces
(Upgrade 14: opcua/server.py, uns/edge.py).

web/scripts/sil-stream.ts runs the compiled program (public/sil/plc.wasm) against the plant
and prints one JSON line per emit: the I/O image in plc.json's order, every unit's state,
job and alarm, the job events, the phase. It is bundled once with esbuild and run by Node.
"""
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
HBW = HERE.parent
PUBLIC = HBW.parents[1] / "web" / "public"
SIL = PUBLIC / "sil"
STREAM = HBW / ".cache" / "sil" / "sil-stream.mjs"
WEB = HBW.parents[1] / "web"
PHASES = {0: "homing", 1: "running", 2: "complete"}


def bundle():
    """Bundle web/scripts/sil-stream.ts (and the plant and PLC host it imports) for Node."""
    subprocess.run(["npx", "esbuild", "scripts/sil-stream.ts", "--bundle", "--platform=node", "--format=esm",
                    f"--outfile={STREAM}", "--log-level=warning"], cwd=WEB, check=True)


def command(speed, emit_ms):
    """The argv that starts the stream: speed 1 = real time, 0 = as fast as it can."""
    return ["node", str(STREAM), str(SIL), str(speed), str(emit_ms)]


def state_names():
    """state code -> its comment, per unit, from the compiled program's source."""
    out, fb = {}, None
    for line in open(os.path.join(SIL, "stf_plc.st")).read().splitlines():
        f = re.match(r"^FUNCTION_BLOCK FB_(\w+)", line)
        if f:
            fb = f.group(1).lower()
            out[fb] = {}
            continue
        s = re.match(r"^ {2}(\d+): \(\* (.*?) \*\)", line)
        if s and fb:
            out[fb][int(s.group(1))] = s.group(2)
    return out
