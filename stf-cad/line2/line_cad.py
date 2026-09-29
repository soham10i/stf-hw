"""
STF-2 CAD: one FreeCAD document + STEP per module, and the full assembly.

    /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd line_cad.py

-> ~/workspace/stf-factory/cad/line2/<module>.FCStd / .step   (8 modules)
-> ~/workspace/stf-factory/cad/line2/STF2_Line.FCStd / .step  (assembly, joints as App::Part)

Refuses to build unless line_model.check() passes. Colours are written with
fcstd_colour (headless FreeCAD has no ViewObject), with a framed camera and
hidden origins so the files open ready to look at.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "hbw"))

import FreeCAD as App
import Part

import line_model as M
import detail
import fcstd_colour

V = App.Vector
OUT = os.path.expanduser("~/workspace/stf-factory/cad/line2")


def shape(p):
    if p.kind == "box" and p.mech.startswith("tray:"):
        M_ = M.L
        s = Part.makeBox(*p.s, V(*p.p))
        n = int(p.mech.split(":")[1])
        cx, cy = p.p[0] + p.s[0] / 2, p.p[1] + p.s[1] / 2
        top = p.p[2] + p.s[2]
        cuts = [Part.makeCylinder(M_["POCKET_D"] / 2, M_["POCKET_DEPTH"] + 1,
                                  V(cx + (k - (n - 1) / 2) * M_["POCKET_PITCH"], cy, top - M_["POCKET_DEPTH"]))
                for k in range(n)]
        return s.cut(Part.makeCompound(cuts))
    if p.kind == "cyl" and p.mech.startswith("tube:"):
        ax, Ln, d = p.s
        s = Part.makeCylinder(d / 2, Ln).cut(Part.makeCylinder(float(p.mech.split(":")[1]) / 2, Ln + 2, V(0, 0, -1)))
        s.Placement = detail._axis_placement(p).multiply(s.Placement)
        return s
    if p.kind == "box":
        if p.mech.startswith("profile:") and max(p.s) > 3 * min(p.s):
            return detail.slotted_profile(p)
        return detail.rounded_box(*p.s, p.p)
    if p.kind == "cyl":
        ax, Ln, d = p.s
        s = detail.chamfered_cyl(d / 2, Ln).copy()
        s.Placement = detail._axis_placement(p).multiply(s.Placement)
        return s
    if p.kind == "rod":
        a = V(*p.p)
        b = V(*p.s[:3])
        return Part.makeCylinder(p.s[3] / 2, (b - a).Length, a, b - a)
    if p.kind == "arc":
        cx, cy, z0 = p.p
        ri, ro, h, a0, a1 = p.s
        o = Part.makeCylinder(ro, h, V(cx, cy, z0), V(0, 0, 1), a1 - a0)
        i = Part.makeCylinder(ri, h, V(cx, cy, z0), V(0, 0, 1), a1 - a0)
        s = o.cut(i)
        s.rotate(V(cx, cy, z0), V(0, 0, 1), a0)
        return s
    raise ValueError(p.kind)


JOINT_TREE = {"stamp_z": "stamp_x"}          # child joint -> parent joint


def build_doc(name, parts):
    for d in list(App.listDocuments()):
        App.closeDocument(d)
    doc = App.newDocument(name)
    colour_of = {}
    root = doc.addObject("App::Part", name)
    joints = {}

    def joint(j):
        if not j or j == "loop":
            return root
        if j not in joints:
            c = doc.addObject("App::Part", f"J_{j}")
            c.Label = f"J_{j}"
            (joint(JOINT_TREE[j]) if j in JOINT_TREE else root).addObject(c)
            joints[j] = c
        return joints[j]

    for p in parts:
        o = doc.addObject("Part::Feature", "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in p.name))
        o.Label = p.name
        o.Shape = shape(p)
        for prop, val in (("STF_Module", p.module), ("STF_Group", p.group), ("STF_IO", p.tag),
                          ("STF_Mech", p.mech), ("STF_Note", p.note[:200])):
            o.addProperty("App::PropertyString", prop, "STF")
            setattr(o, prop, val)
        joint(p.joint).addObject(o)
        colour_of[o.Name] = p.colour
    doc.recompute()
    os.makedirs(OUT, exist_ok=True)
    fc, st = os.path.join(OUT, f"{name}.FCStd"), os.path.join(OUT, f"{name}.step")
    import Import
    Import.export([root], st)
    doc.saveAs(fc)
    bb = App.BoundBox()
    for o in doc.Objects:
        if o.TypeId == "Part::Feature":
            bb.add(o.Shape.BoundBox)
    fcstd_colour.colourise(fc, colour_of, camera=fcstd_colour.iso_camera(
        (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)))
    n = sum(1 for o in doc.Objects if o.TypeId == "Part::Feature")
    App.closeDocument(doc.Name)
    return fc, st, n


def containment(parts):
    """Every contained thing is really inside its container, touching nothing it
    should not: cookies in pockets, cookies in tubes, pack stacks in cassettes
    (sitting ON the pawls), nested trays inside the magazine guides."""
    by = {p.name: p for p in parts}
    sh = {}
    def S(n):
        if n not in sh:
            sh[n] = shape(by[n])
        return sh[n]
    fails, n = [], 0
    for p in parts:
        host = None
        if "_cookie_" in p.name and p.name.startswith(("tray_", "mag_")):
            host = p.name.split("_cookie_")[0]
        elif p.name.endswith("_stack") and p.name.startswith("cassette_"):
            base = p.name[:-6]
            hosts = [h for h in by if h.startswith(base + "_wall_") or h.startswith(base + "_pawl_")]
            for h in hosts:
                n += 1
                v = S(p.name).common(S(h)).Volume
                if v > 1e-3:
                    fails.append(f"{p.name} overlaps {h} by {v:.2f} mm3")
            pawl_top = max(by[h].aabb()[5] for h in hosts if "_pawl_" in h)
            if abs(by[p.name].p[2] - pawl_top) > 1e-6:
                fails.append(f"{p.name} is not seated on its pawls")
            continue
        if host and host in by:
            n += 1
            v = S(p.name).common(S(host)).Volume
            if v > 1e-3:
                fails.append(f"{p.name} overlaps {host} by {v:.2f} mm3")
            hb = by[host].aabb()
            b = by[p.name].aabb()
            if any(b[i] < hb[i] - 1e-6 or b[i + 3] > hb[i + 3] + 1e-6 for i in range(2)):
                fails.append(f"{p.name} is not inside {host} in plan")
    # the top OUTLET of every cassette must be clear: nothing of the cassette above
    # its inner footprint (a pack pushed out of the top would hit it)
    t = M.L["CASS_WALL"]
    for p in parts:
        if p.name.endswith("_wall_front") and p.name.startswith("cassette_"):
            base = p.name[:-11]
            x0, y0, z0 = p.p
            cw, cd, ch = M.L["CASS"]
            inner = (x0 + t, y0 + t, z0 + ch - 1, x0 + cw - t, y0 + cd - t, z0 + ch + 100)
            for q in parts:
                if q.name.startswith(base + "_") and not q.name.endswith("_stack"):
                    b = q.aabb()
                    n += 1
                    if all(min(b[i + 3], inner[i + 3]) - max(b[i], inner[i]) > 1e-6 for i in range(3)):
                        fails.append(f"{q.name} blocks the top outlet of {base}")
    return fails, n


def main():
    fails = M.check(verbose=False)
    if fails:
        print("REFUSING to build:", fails[:5])
        sys.exit(1)
    parts = M.build()
    cf, cn = containment(parts)
    if cf:
        print("REFUSING to build - containment:", cf[:6])
        sys.exit(1)
    print(f"containment proof: {cn} contained pairs, zero overlap (cookies in pockets/tubes, stacks on pawls)")
    report = []
    for mod, ps in M.by_module(parts).items():
        fc, st, n = build_doc(mod, ps)
        report.append((mod, n, os.path.getsize(fc) / 1e6, os.path.getsize(st) / 1e6))
    table = M.Part("table_top", "M1_loop", "table", "box", (0, 0, -M.L["TABLE"][2]), M.L["TABLE"], "#f4f3ef")
    fc, st, n = build_doc("STF2_Line", [table] + parts)
    report.append(("STF2_Line (assembly)", n, os.path.getsize(fc) / 1e6, os.path.getsize(st) / 1e6))
    for r in report:
        print("%-24s %4d solids  FCStd %5.1f MB  STEP %6.1f MB" % r)
    print("wrote", OUT)


if sys.argv[-1].endswith("line_cad.py") or __name__ == "__main__":
    main()
