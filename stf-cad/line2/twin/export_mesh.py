"""
DT-1, step 1 (FreeCAD): tessellate the precise CAD into a neutral mesh cache.

    freecadcmd twin/export_mesh.py        (from stf-cad/line2; ~2 min)

Reads   ~/workspace/stf-factory/cad/line2_precise/STF2_Precise.FCStd and the ten module files (a fastener's module
        is the module file it was written to; every other solid carries STF_Module).
Writes  twin/out/cache/meshes.npz   per prototype k: v{k} float32 (n, 3) mm, n{k} float32 (n, 3), i{k} uint32 (m, 3)
        twin/out/cache/index.json   every solid: name, module, group, hw, tag, note, colour, moving, prototype,
                                    offset (mm), B-rep bounding box and volume, mesh volume, triangles
Tessellation: every B-rep FACE on its own (MeshPart, LinearDeflection DEFLECTION, AngularDeflection ANGULAR), normals
averaged inside a face only - edges between faces stay sharp. Geometry is in world coordinates (the CAD's), so a
part's animation transform is exactly the timeline's Placement(t, q) (motion_player: Placement(t, q) * CAD placement).
Instancing: two solids whose meshes are equal up to a translation (vertices to 1 um) share one prototype; the
instance carries the offset. Screws, nuts, pucks and repeated brackets collapse this way.
Colours follow line_cad_precise.write: the part colour, brackets zinc, fasteners steel / T-nut, PC panels at 70 %.
"""
import hashlib
import json
import os
import sys
import time

import FreeCAD as App
import MeshPart
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(HERE)
sys.path.insert(0, LINE2)
import line_model as M                                      # noqa: E402

CAD = os.path.expanduser("~/workspace/stf-factory/cad/line2_precise")
OUT = os.path.join(HERE, "out", "cache")
DEFLECTION, ANGULAR = 0.2, 0.35                             # mm, rad (20 deg): ~1.1 M triangles for the line
STEEL, ZINC, TNUT_C = "#3a3d40", "#9aa3ab", "#b0b4b8"       # = line_cad_precise
CLEAR = ("PC guard panel 4 mm", "guard door kit")


def log(*a):
    with open(os.path.join(OUT, "export_mesh.log"), "a") as fh:      # freecadcmd swallows stdout
        fh.write(" ".join(str(x) for x in a) + "\n")


def mesh_of(shape):
    """(vertices, normals, triangles) of a shape, face by face."""
    vs, ns, ts, off = [], [], [], 0
    for f in shape.Faces:
        m = MeshPart.meshFromShape(Shape=f, LinearDeflection=DEFLECTION, AngularDeflection=ANGULAR, Relative=False)
        if m.CountFacets == 0:
            continue
        v = np.array([[p.x, p.y, p.z] for p in m.Points], dtype=np.float64)
        t = np.array([fc.PointIndices for fc in m.Facets], dtype=np.int64)
        fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])        # area-weighted face normals
        n = np.zeros_like(v)
        for k in range(3):
            np.add.at(n, t[:, k], fn)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        vs.append(v)
        ns.append(n)
        ts.append(t + off)
        off += len(v)
    if not vs:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    return np.vstack(vs), np.vstack(ns), np.vstack(ts)


def signed_volume(v, t):
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def main():
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "export_mesh.log"), "w").close()
    t0 = time.time()
    parts = {p.name: p for p in M.build()}                 # with product, as line_cad_precise builds it
    tl = json.load(open(os.path.join(LINE2, "motion", "timeline.json")))
    moving = set(tl["track"]) | {s["name"] for s in tl["spawn"]}
    follow = tuple(tl.get("follow", {}))                    # name prefixes (screws F####_) riding on a moving body
    modof, fast = {}, set()
    for mod in M.MODULES:
        d = App.openDocument(os.path.join(CAD, f"{mod}.FCStd"))
        for o in d.Objects:
            if o.TypeId == "Part::Feature":
                modof[o.Label] = mod
                if any(g.Label.endswith("_fasteners") for g in o.InList):
                    fast.add(o.Label)
        App.closeDocument(d.Name)
    doc = App.openDocument(os.path.join(CAD, "STF2_Precise.FCStd"))
    objs = [o for o in doc.Objects if o.TypeId == "Part::Feature"]
    protos, arrays, index = {}, {}, []
    for o in objs:
        name = o.Label
        p = parts.get(name)
        props = {k: getattr(o, k, "") for k in ("STF_Module", "STF_HW", "STF_IO", "STF_Note")}
        module = props["STF_Module"] or modof.get(name, "")
        if name in fast:
            group, colour = "fastener", (TNUT_C if name.endswith("tnut") or "_tnut" in name else STEEL)
        elif p is not None:
            group = p.group
            colour = ZINC if p.group == "bracket" else p.colour
            if p.hw in CLEAR:
                colour = p.colour + "/70"
        else:
            group, colour = "bracket", ZINC
        v, n, t = mesh_of(o.Shape)
        if len(t):
            lo = v.min(axis=0)
            rel = np.round(v - lo, 3)
            key = hashlib.sha1(rel.tobytes() + t.astype(np.int64).tobytes()).hexdigest()
            if key not in protos:
                k = len(protos)
                protos[key] = k
                arrays[f"v{k}"] = (v - lo).astype(np.float32)
                arrays[f"n{k}"] = n.astype(np.float32)
                arrays[f"i{k}"] = t.astype(np.uint32)
            proto, off = protos[key], [round(float(x), 4) for x in lo]
        else:
            proto, off = None, [0.0, 0.0, 0.0]
        bb = o.Shape.optimalBoundingBox(False, False)       # exact, not padded by tolerances / curve poles
        index.append(dict(name=name, module=module, group=group, hw=props["STF_HW"], tag=props["STF_IO"],
                          note=props["STF_Note"], colour=colour, moving=name in moving or name.startswith(follow), fastener=name in fast,
                          proto=proto, offset=off, bbox=[bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax],
                          volume=o.Shape.Volume, mesh_volume=signed_volume(v, t) if len(t) else 0.0,
                          closed=all(s.isClosed() for s in o.Shape.Solids) and bool(o.Shape.Solids),
                          tris=int(len(t))))
    np.savez_compressed(os.path.join(OUT, "meshes.npz"), **arrays)
    meta = dict(source=os.path.join(CAD, "STF2_Precise.FCStd"), deflection=DEFLECTION, angular=ANGULAR,
                units="mm", up="Z", solids=len(index), prototypes=len(protos),
                triangles_instanced=int(sum(e["tris"] for e in index)),
                triangles_stored=int(sum(len(arrays[f"i{k}"]) for k in range(len(protos)))))
    json.dump(dict(meta=meta, solids=index), open(os.path.join(OUT, "index.json"), "w"))
    log(f"export_mesh: {meta['solids']} solids -> {meta['prototypes']} prototypes, "
        f"{meta['triangles_instanced']:,} triangles drawn, {meta['triangles_stored']:,} stored, {time.time() - t0:.0f} s")


main()
