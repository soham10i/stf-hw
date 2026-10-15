"""
Headless proof that the FreeCAD player shows exactly the model's motion (run with freecadcmd):
  1. every frame: each moved CAD solid lands where line_model + motion.py put it
     (rods: centroid on the analytic axis midpoint; boxes / cylinders: bounding box), 0.05 mm
  2. every SAMPLE s: B-rep common() of each moving solid with the machine and the other moving solids
     (the same declared contacts as motion.sweep excepted) - no shared volume
Run: freecadcmd validate_motion.py   (log: /tmp/validate_motion.out)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "motion"))
import FreeCAD as App

import line_model as M
import motion as Mo
import motion_player as MP

LOG = open("/tmp/validate_motion.out", "w")
SAMPLE = 1.0
TOL = 0.05


def log(*a):
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


def main():
    fc = os.path.expanduser("~/workspace/stf-factory/cad/line2_precise/STF2_Precise.FCStd")
    doc = App.openDocument(fc)
    pl = MP.Player(doc, os.path.join(HERE, "motion", "timeline.json"))
    base = {p.name: p for p in M.build()}
    fails, n_pos, n_brep = [], 0, 0
    if pl.missing:
        fails.append(f"{len(pl.missing)} timeline parts missing in the CAD: {pl.missing[:5]}")
    every = int(round(SAMPLE / pl.dt))
    for k in range(pl.n):
        pl.apply(k)
        t = k * pl.dt
        now, vis, _ = Mo.frame(t, base)
        for n, o in pl.obj.items():
            p = now[n]
            if p.kind == "rod":
                a, b = Mo.rod_ends(p)
                mid = App.Vector(*[(a[i] + b[i]) / 2 for i in range(3)])
                err = (o.Shape.CenterOfMass - mid).Length
            else:
                bb, ab = o.Shape.BoundBox, p.aabb()
                err = max(abs(bb.XMin - ab[0]), abs(bb.YMin - ab[1]), abs(bb.ZMin - ab[2]),
                          abs(bb.XMax - ab[3]), abs(bb.YMax - ab[4]), abs(bb.ZMax - ab[5]))
            n_pos += 1
            if err > TOL:
                fails.append(f"POSITION {n} at t={t:.1f}: CAD is {err:.3f} mm off the model")
        if k % every:
            continue
        movers = [(n, o) for n, o in pl.obj.items() if vis.get(n, True)]
        mv = {n for n, _ in movers}
        others = [o for o in doc.Objects if o.TypeId == "Part::Feature" and o.Label in base and o.Label not in mv]
        for n, o in movers:
            bo = o.Shape.BoundBox
            for q in others + [x for m, x in movers if m != n]:
                if not bo.intersect(q.Shape.BoundBox):
                    continue
                pq = now.get(q.Label) or base.get(q.Label)
                if pq is None or Mo._exempt(now[n], pq):
                    continue
                n_brep += 1
                v = o.Shape.common(q.Shape).Volume
                if v > 1e-3:
                    fails.append(f"BREP {n} x {q.Label} at t={t:.1f}: {v:.3f} mm3")
    log(f"validate_motion: {pl.n} frames, {n_pos} placements checked (<= {TOL} mm), {n_brep} B-rep pairs at "
        f"{SAMPLE:g} s samples, {len(pl.fol)} screws/brackets follow")
    log("\n".join(sorted(set(fails))[:40]) if fails else "PLAYER == MODEL at every frame, no B-rep interference")
    App.closeDocument(doc.Name)


main()
os._exit(0)
