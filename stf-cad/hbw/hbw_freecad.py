"""
Generate the HBW CAD assembly from hbw_model.

Run headless:
    /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd hbw_freecad.py

Produces, next to this file:
    STF_HBW.FCStd   articulated assembly - nested App::Part containers whose
                    Placements ARE the three joints, so dragging a container in
                    FreeCAD moves the machine exactly as the simulation does.
    STF_HBW.step    flat STEP for anyone downstream.

The CAD is a VIEW of hbw_model.P, never the other way round. Re-run after any
parameter change; do not hand-edit solids in the tree and expect them to survive.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App
import Part

from hbw_model import P, check
from hbw_frames import by_frame, frame_offset, PARENT, FRAMES, HOME

HERE = os.path.dirname(os.path.abspath(__file__))
V = App.Vector


def shape(p):
    if p.kind == "box":
        return Part.makeBox(*p.s, V(*p.p))
    ax, L, d = p.s
    direction = {"x": V(1, 0, 0), "y": V(0, 1, 0), "z": V(0, 0, 1)}[ax]
    return Part.makeCylinder(d / 2.0, L, V(*p.p), direction)


def main():
    fails = check(verbose=False)
    if fails:
        print("REFUSING to build CAD - the model does not pass its own clearance proof:")
        print("\n".join(fails)); sys.exit(1)

    for old in list(App.listDocuments()):
        App.closeDocument(old)
    doc = App.newDocument("STF_HBW")

    containers = {}
    for f in FRAMES:
        c = doc.addObject("App::Part", {"world": "HBW_Static", "travel": "J1_Travel_X",
                                        "lift": "J2_Lift_Z", "fork": "J3_Ausleger_Y"}[f])
        c.Label = c.Name
        containers[f] = c
    for f in FRAMES:
        if PARENT[f]:
            containers[PARENT[f]].addObject(containers[f])
        ox, oy, oz = frame_offset(f, HOME["travel"], HOME["lift"], HOME["fork"])
        containers[f].Placement.Base = V(ox, oy, oz)

    n = 0
    groups = {}
    for frame, parts in by_frame().items():
        for p in parts:
            o = doc.addObject("Part::Feature", "".join(
                ch if (ch.isalnum() or ch == "_") else "_" for ch in p.name))
            o.Label = p.name
            o.Shape = shape(p)
            o.addProperty("App::PropertyString", "STF_Group", "STF").STF_Group = p.group
            o.addProperty("App::PropertyString", "STF_Colour", "STF").STF_Colour = p.colour
            o.addProperty("App::PropertyString", "STF_IO", "STF").STF_IO = p.tag
            o.addProperty("App::PropertyString", "STF_Support", "STF").STF_Support = p.support
            o.addProperty("App::PropertyString", "STF_Note", "STF").STF_Note = p.note
            containers[frame].addObject(o)
            groups.setdefault(p.group, 0)
            groups[p.group] += 1
            n += 1

    doc.recompute()
    fc = os.path.join(HERE, "STF_HBW.FCStd")
    doc.saveAs(fc)

    # STEP is flat: bake each solid's GLOBAL placement in, so the exported file
    # shows the machine at HOME rather than every frame collapsed onto travel=0.
    feats = [o for o in doc.Objects if o.TypeId == "Part::Feature"]
    placed = [o.Shape.copy() for o in feats]
    for sh, o in zip(placed, feats):
        sh.Placement = o.getGlobalPlacement().multiply(sh.Placement)
    comp = doc.addObject("Part::Feature", "STF_HBW_flat")
    comp.Shape = Part.makeCompound(placed)
    doc.recompute()
    Part.export([comp], os.path.join(HERE, "STF_HBW.step"))
    doc.removeObject(comp.Name)
    doc.recompute()
    doc.save()

    # ---- proof: the CAD assembly must reproduce hbw_model.build(HOME) exactly
    from hbw_model import build
    want = {p.name: p.aabb() for p in build(HOME["travel"], HOME["lift"], HOME["fork"])}
    drift = []
    for o in feats:
        sh = o.Shape.copy()
        sh.Placement = o.getGlobalPlacement().multiply(sh.Placement)
        b = sh.BoundBox
        got = (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)
        w = want[o.Label]
        if max(abs(g - x) for g, x in zip(got, w)) > 1e-6:
            drift.append(f"{o.Label}: CAD {got} != model {w}")
    if drift:
        print("CAD DRIFT from the model:"); print("\n".join(drift)); sys.exit(1)
    print(f"CAD matches hbw_model.build{tuple(HOME.values())} exactly for all {len(feats)} solids")

    tot = sum(s.Volume for s in placed)
    print(f"built {n} solids in 4 joint frames")
    for g, c in sorted(groups.items()):
        print(f"   {g:10s} {c:3d}")
    print(f"total solid volume  {tot/1000.0:.1f} cm3")
    print(f"wrote {fc}")
    print(f"wrote {os.path.join(HERE, 'STF_HBW.step')}")
    print("joints: J1_Travel_X.Placement.x | J2_Lift_Z.Placement.z | J3_Ausleger_Y.Placement.y")


main()
