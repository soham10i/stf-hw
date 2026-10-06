#!/usr/bin/env bash
# Every proof of STF-2, in dependency order; stops at the first failure.   Run from stf-cad/line2.
#   ./check_all.sh          model, control, joints, PLC, safety, line sim, BOM, drawings, twin scene (~8 min)
#   ./check_all.sh --full   + precise CAD build, motion sweep, player validation (+ ~40 min)
set -euo pipefail
cd "$(dirname "$0")"
FC=${FC:-/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd}
step() { printf '%-14s ' "$1"; shift; out=$("$@" 2>&1) || { echo "FAILED"; echo "$out" | tail -20; exit 1; }; echo "$out" | tail -1 | cut -c1-110; }
step line_model  python3 line_model.py
step oven_ctrl   python3 oven_ctrl.py
step joints      python3 joints.py
step plc_io      python3 plc_io.py
step safety      python3 safety.py
step line_sim    python3 line_sim.py
step bom         python3 bom.py
step elec_draw   python3 elec_draw.py
step line_draw   python3 line_draw.py
step oven_draw   python3 oven_draw.py
if [ "${1:-}" = "--full" ]; then
  step cad       bash -c "$FC line_cad_precise.py > /tmp/line_cad_precise.log 2>&1; grep -E 'B-rep|STF2_Precise ' /tmp/line_cad_precise.out | tail -1; ! grep -q REFUSING /tmp/line_cad_precise.out"
  step motion    python3 motion.py
  step validate  bash -c "rm -f /tmp/validate_motion.out; $FC validate_motion.py > /dev/null 2>&1; cat /tmp/validate_motion.out; grep -q 'PLAYER == MODEL' /tmp/validate_motion.out"
fi
if [ -x ../../.venv-twin/bin/python ]; then
  step twin_scene twin/export_scene.sh
else
  echo "twin_scene     skipped (no .venv-twin: see twin/MAC_SETUP.md section 4)"
fi
echo "ALL STF-2 PROOFS PASS"
