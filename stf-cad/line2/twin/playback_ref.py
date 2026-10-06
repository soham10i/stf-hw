"""
DT-2 reference: the FreeCAD player itself (motion/motion_player.py) applied to STF2_Precise.FCStd at sample frames;
records every object it moves (tracks, followers, spawned cookies): exact bounding box (mm) and visibility.

    freecadcmd twin/playback_ref.py        (from stf-cad/line2; ~1 min)  ->  twin/out/playback_ref.json
"""
import json
import os
import sys
import time

import FreeCAD as App

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(LINE2, "motion"))
import motion_player as MP                                 # noqa: E402

CAD = os.path.expanduser("~/workspace/stf-factory/cad/line2_precise/STF2_Precise.FCStd")
STEP = 10                                                   # every 10th frame (1 s): 41 frames incl. the first and last


def main():
    t0 = time.time()
    doc = App.openDocument(CAD)
    p = MP.Player(doc, os.path.join(LINE2, "motion", "timeline.json"))
    objs = {n: o for n, o in p.obj.items()}
    for o, body, _ in p.fol:
        objs[o.Label] = o
    for o in p.spawned:
        objs[o.Label] = o
    frames = sorted(set(range(0, p.n, STEP)) | {p.n - 1})
    ref = {}
    for k in frames:
        p.apply(k)
        rows = {}
        for n, o in objs.items():
            b = o.Shape.optimalBoundingBox(False, False)
            rows[n] = [round(x, 4) for x in (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)] + [1 if o.Visibility else 0]
        ref[k] = rows
    out = dict(source=CAD, frames=frames, objects=len(objs), missing=p.missing, ref=ref)
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "out", "playback_ref.json"), "w"))
    with open(os.path.join(HERE, "out", "playback_ref.log"), "w") as fh:
        fh.write(f"playback_ref: {len(objs)} moved objects x {len(frames)} frames, "
                 f"{len(p.missing)} tracks without a CAD object, {time.time() - t0:.0f} s\n")


main()
