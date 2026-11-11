"""
Build the WHOLE factory as a coloured, articulated FreeCAD document.

    /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd build_cad.py

Every solid is the PRECISE shape from detail.py (bevelled blocks, true helical
threads, spring, cone cup, toothed belt), and detail.py asserts each one stays
inside the envelope the clearance proofs checked - so the proofs still hold for
exactly this geometry. Written to ~/workspace/stf-factory/cad/ as .FCStd and .step.

Nested App::Part containers carry the joints, so the assembly poses in the GUI
exactly as the simulation does. Colours are written afterwards by
fcstd_colour.py, because a headless FreeCAD has no ViewObject to set them on.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import detail
import factory_layout
import FreeCAD as App
import hbw_model
import oven_model
import Part
import sorting_model
import vgr_model
import vgr_path
from hbw_frames import by_frame as hbw_by_frame

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.expanduser("~/workspace/stf-factory/cad")
BASE_GREY = "#8d949b"
SIBLINGS = {p.name: p for p in hbw_model.build()}  # the belt loop finds its pulleys
V = App.Vector
COLOURS = {
    "black": "#2b2b2f", "red": "#cf3a2f", "ftred": "#e0492f", "alu": "#d6d9da",
    "steel": "#aeb4b8", "white": "#f2f0ea", "colour": "#2f6fd0", "green": "#1b8f52",
    "amber": "#e0a02a", "grey": "#8b9196", "darkgrey": "#474b52", "slate": "#3a3f44",
}


def hexof(c):
    return c if isinstance(c, str) and c.startswith("#") else COLOURS.get(c, "#8b9196")


def shape(p):
    return detail.precise(p, SIBLINGS)


def main():
    checks = (("HBW", hbw_model.check(verbose=False)), ("VGR", vgr_model.check(verbose=False)),
              ("OVEN", oven_model.check(verbose=False)), ("SORTING", sorting_model.check(verbose=False)),
              ("CROSS", factory_layout.check_cross() + factory_layout.check_stations()),
              ("VGR PATH", vgr_path.check(verbose=False)))
    for name, fails in checks:
        if fails:
            print(f"REFUSING to build - {name} fails its checks:")
            print("\n".join(fails[:6])); sys.exit(1)

    for old in list(App.listDocuments()):
        App.closeDocument(old)
    doc = App.newDocument("STF_Factory")
    colour_of, made = {}, [0]

    def solid(p, parent):
        if p.group == "frame":          # module plates -> the one grey base
            return None
        nm = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in p.name)
        o = doc.addObject("Part::Feature", nm)
        o.Label = p.name
        o.Shape = shape(p)
        for prop, val in (("STF_Group", p.group), ("STF_IO", p.tag),
                          ("STF_Note", p.note[:200])):
            o.addProperty("App::PropertyString", prop, "STF").__setattr__(prop, val)
        parent.addObject(o)
        colour_of[o.Name] = hexof(p.colour)
        made[0] += 1
        return o

    def container(label, parent=None, t=(0, 0, 0), rot=0.0):
        c = doc.addObject("App::Part", label)
        c.Label = label
        c.Placement = App.Placement(V(*t), App.Rotation(V(0, 0, 1), rot))
        if parent is not None:
            parent.addObject(c)
        return c

    # --- table
    table = container("STF_Table")
    fl = factory_layout.doc()
    fx, fy, ft = fl["plate"]
    tp = doc.addObject("Part::Feature", "Base_Plate")
    tp.Label = "Base_Plate"
    tp.Shape = detail.rounded_box(fx, fy, 10 + ft, (0, 0, -10 - ft))
    table.addObject(tp)
    colour_of[tp.Name] = BASE_GREY

    # --- HBW, articulated
    hbw = container("HBW_Hochregallager", table, (factory_layout.TX, factory_layout.TY, 0), factory_layout.ROTATE_DEG)
    hf = hbw_by_frame()
    j1 = container("J1_Travel_X", hbw, (hbw_model.P["CV_X"], 0, 0))
    j2 = container("J2_Lift_Z", j1, (0, 0, 120.0))
    j3 = container("J3_Ausleger_Y", j2, (0, 0, 0))
    for p in hf["world"]:  solid(p, hbw)
    for p in hf["travel"]: solid(p, j1)
    for p in hf["lift"]:   solid(p, j2)
    for p in hf["fork"]:   solid(p, j3)

    # --- VGR, articulated
    vx, vy = factory_layout.VGR_AT
    vgr = container("VGR_Sauggreifer", table, (vx, vy, 0))
    sw = container("J_Swivel", vgr, (vgr_model.V["CX"], vgr_model.V["CY"], 0))
    piv = container("_pivot", sw, (-vgr_model.V["CX"], -vgr_model.V["CY"], 0))
    pl = container("J_Plunge", piv, (0, 0, 0))
    rc = container("J_Reach", pl, (0, 0, 0))
    vp = {f: [] for f in vgr_model.FRAMES}
    for p in vgr_model.build():
        vp[p.frame].append(p)
    for p in vp["world"]:  solid(p, vgr)
    for p in vp["swivel"]: solid(p, piv)
    for p in vp["plunge"]: solid(p, pl)
    for p in vp["reach"]:  solid(p, rc)

    # --- Oven, articulated
    oven = container("OVEN_Brennofen", table, (factory_layout.OVEN_TX, factory_layout.OVEN_TY, 0), factory_layout.OVEN_ROT)
    jsl = container("J_Ofenschieber", oven)
    jdr = container("J_Ofentuer", oven)
    tcx, tcy = oven_model.O["TT"]
    jtu = container("J_Drehkranz", oven, (tcx, tcy, 0))
    jtp = container("_tt_pivot", jtu, (-tcx, -tcy, 0))
    jsa = container("J_Sauger", oven)
    jlo = container("J_Senken", jsa)
    jpu = container("J_Auswerfer", oven)
    op = {f: [] for f in oven_model.FRAMES}
    for p in oven_model.build():
        op[p.frame].append(p)
    for f, c in (("world", oven), ("slider", jsl), ("door", jdr),
                 ("turn", jtp), ("sauger", jsa), ("lower", jlo),
                 ("push", jpu)):
        for p in op[f]:
            solid(p, c)

    # --- Sorting, articulated
    sort = container("SORT_Sortierstrecke", table,
                     (factory_layout.SORT_TX, factory_layout.SORT_TY, 0), factory_layout.SORT_ROT)
    sp = {f: [] for f in sorting_model.FRAMES}
    for p in sorting_model.build():
        sp[p.frame].append(p)
    for p in sp["world"]:
        solid(p, sort)
    for i, col in enumerate(sorting_model.COLOURS):
        jc = container(f"J_Auswurf_{col}", sort)
        for p in sp[f"push{i}"]:
            solid(p, jc)

    # --- PLC cabinet
    import plc_model
    plc = container("PLC_Schaltschrank", table, (factory_layout.PLC_AT[0], factory_layout.PLC_AT[1], 0))
    for p in plc_model.build():
        if p.group != "frame":
            solid(p, plc)

    doc.recompute()
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "STF_Factory.FCStd")
    step = os.path.join(OUT_DIR, "STF_Factory.step")
    import Import
    Import.export([table], step)          # the App::Part tree, placements included
    doc.saveAs(out)

    import shutil

    import fcstd_colour
    # frame the whole model: union of every solid's GLOBAL bounding box
    bb = App.BoundBox()
    for o in doc.Objects:
        if o.TypeId == "Part::Feature":
            sh = o.Shape.copy()
            sh.Placement = o.getGlobalPlacement()
            bb.add(sh.BoundBox)
    cam = fcstd_colour.iso_camera((bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax))
    n = fcstd_colour.colourise(out, colour_of, camera=cam)
    shutil.copy(out, os.path.join(HERE, "STF_Factory.FCStd"))
    print(f"built {made[0]} precise solids in 4 modules, {n} coloured")
    print(f"wrote {out}  ({os.path.getsize(out) / 1e6:.1f} MB)")
    print(f"wrote {step}  ({os.path.getsize(step) / 1e6:.1f} MB)")
    print("joints: HBW J1/J2/J3 - VGR J_Swivel/J_Plunge/J_Reach - "
          "OVEN J_Ofenschieber/J_Ofentuer/J_Drehkranz/J_Sauger/J_Senken/J_Auswerfer - "
          "SORT J_Auswurf_weiss/rot/blau")


# freecadcmd runs a script with __name__ = its module name, not "__main__"
if __name__ == "__main__" or sys.argv[-1].endswith("stf_freecad.py"):
    main()
