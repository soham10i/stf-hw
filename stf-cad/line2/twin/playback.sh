#!/usr/bin/env bash
# DT-2: FreeCAD player reference -> Blender keyframes (+ boxes) -> the gate (Python, browser, Blender = FreeCAD).
# Run from stf-cad/line2 after twin/export_scene.sh (DT-1).
set -euo pipefail
cd "$(dirname "$0")/.."
FC=${FC:-/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd}
PY=${PY:-../../.venv-twin/bin/python}
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
"$FC" twin/playback_ref.py > /dev/null 2>&1 || { echo "playback_ref failed"; exit 1; }
cat twin/out/playback_ref.log
"$BLENDER" -b -P twin/blender_anim.py -- --check --save 2>&1 | grep -E "^(animated|saved)" || { echo "blender_anim failed"; exit 1; }
"$PY" twin/playback_check.py
