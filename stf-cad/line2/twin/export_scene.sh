#!/usr/bin/env bash
# DT-1: precise CAD -> mesh cache (FreeCAD) -> USD / USDZ / GLB (OpenUSD) -> gate.   Run from stf-cad/line2.
# Refuses (exit 1) if the gate fails; the outputs in twin/out are then not to be used.
set -euo pipefail
cd "$(dirname "$0")/.."
FC=${FC:-/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd}
PY=${PY:-../../.venv-twin/bin/python}
"$FC" twin/export_mesh.py > /dev/null 2>&1 || { echo "export_mesh failed"; exit 1; }
cat twin/out/cache/export_mesh.log
"$PY" twin/build_scene.py
[ -d twin/node_modules ] || (cd twin && npm install --silent)
"$PY" twin/scene_check.py
