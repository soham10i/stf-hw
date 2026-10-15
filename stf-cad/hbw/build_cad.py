"""
One command for the whole CAD deliverable, run inside FreeCAD:

    /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd build_cad.py

  1. every clearance proof, the swept VGR path and the pipeline must pass
  2. stf-factory/cad/STF_Factory.FCStd + .step  - precise B-rep, coloured
  3. stf-factory/web/public/assets/stf_factory.glb + stf_parts.json - the same
     precise shapes, tessellated, for the CAD Model tab
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stf_freecad
import stf_web_glb

stf_freecad.main()
stf_web_glb.main()
