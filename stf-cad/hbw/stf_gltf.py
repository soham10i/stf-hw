"""
Export the whole factory to a single self-contained .gltf.

    python3 stf_gltf.py [--units mm|m] [-o STF_Factory.gltf]

Coordinates are the FACTORY frame: Z up, millimetres by default, because that is
what FreeCAD works in. Pass --units m for renderers that assume the glTF metre
convention (three.js, Blender).

The node tree carries the JOINTS, so the file is articulable rather than a frozen
snapshot:

    STF_Factory
      Table
      HBW            (placed: +90 deg about Z, then translate)
        J1_Travel_X -> J2_Lift_Z -> J3_Ausleger_Y
      VGR
        J_Swivel -> J_Plunge -> J_Reach
      Reserved_*     (oven / sorting footprints, not yet designed)

NOTE ON PRECISION: glTF is a MESH format - cylinders become SEG-gons. For exact
B-rep geometry in FreeCAD, import STF_HBW.step instead; this file is for
rendering and for checking the arrangement.
"""
import argparse, base64, json, math, struct, sys

from hbw_model import P, build as hbw_build
from hbw_frames import by_frame as hbw_by_frame
import vgr_model as VG
import oven_model as OM
import sorting_model as SM
import factory_layout as FL

# 64-segment cylinders: the spindles, drums, suction cups and the Drehkranz all
# read as round rather than faceted. Roughly doubles the file, still under 2 MB.
SEG = 64


def box_mesh(dx, dy, dz, ox, oy, oz):
    """Axis-aligned box with flat normals. Returns (positions, normals, indices)."""
    x0, y0, z0 = ox, oy, oz
    x1, y1, z1 = ox + dx, oy + dy, oz + dz
    faces = [
        ([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1)),
        ([(x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)], (0, 0, -1)),
        ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0)),
        ([(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)], (0, 1, 0)),
        ([(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)], (-1, 0, 0)),
        ([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], (1, 0, 0)),
    ]
    pos, nrm, idx = [], [], []
    for quad, n in faces:
        b = len(pos)
        pos += list(quad)
        nrm += [n] * 4
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    return pos, nrm, idx


def cyl_mesh(axis, length, dia, ox, oy, oz):
    r = dia / 2.0
    pos, nrm, idx = [], [], []

    def place(u, vv, w):
        """u,v = circle plane, w = along the axis, mapped back to xyz."""
        if axis == "z":  return (ox + u, oy + vv, oz + w)
        if axis == "x":  return (ox + w, oy + u, oz + vv)
        return (ox + u, oy + w, oz + vv)

    def nrm3(u, vv):
        if axis == "z":  return (u, vv, 0.0)
        if axis == "x":  return (0.0, u, vv)
        return (u, 0.0, vv)

    for i in range(SEG):
        a0 = 2 * math.pi * i / SEG
        a1 = 2 * math.pi * (i + 1) / SEG
        c0, s0 = math.cos(a0), math.sin(a0)
        c1, s1 = math.cos(a1), math.sin(a1)
        b = len(pos)
        pos += [place(r * c0, r * s0, 0.0), place(r * c1, r * s1, 0.0),
                place(r * c1, r * s1, length), place(r * c0, r * s0, length)]
        nrm += [nrm3(c0, s0), nrm3(c1, s1), nrm3(c1, s1), nrm3(c0, s0)]
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    # caps
    for w, sgn in ((0.0, -1.0), (length, 1.0)):
        centre = len(pos)
        pos.append(place(0.0, 0.0, w))
        n = nrm3(0.0, 0.0)
        n = (0, 0, sgn) if axis == "z" else ((sgn, 0, 0) if axis == "x" else (0, sgn, 0))
        nrm.append(n)
        first = len(pos)
        for i in range(SEG):
            a = 2 * math.pi * i / SEG
            pos.append(place(r * math.cos(a), r * math.sin(a), w))
            nrm.append(n)
        for i in range(SEG):
            j0, j1 = first + i, first + (i + 1) % SEG
            idx += [centre, j0, j1] if sgn > 0 else [centre, j1, j0]
    return pos, nrm, idx


class Gltf:
    def __init__(self, scale):
        self.scale = scale
        self.buf = bytearray()
        self.views, self.acc, self.meshes, self.nodes, self.mats = [], [], [], [], []
        self.mat_by_colour = {}

    def _view(self, data, target):
        while len(self.buf) % 4:
            self.buf.append(0)
        off = len(self.buf)
        self.buf += data
        self.views.append({"buffer": 0, "byteOffset": off,
                           "byteLength": len(data), "target": target})
        return len(self.views) - 1

    def material(self, colour):
        if colour in self.mat_by_colour:
            return self.mat_by_colour[colour]
        c = colour.lstrip("#")
        rgb = [int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        self.mats.append({
            "name": colour,
            "pbrMetallicRoughness": {"baseColorFactor": rgb + [1.0],
                                     "metallicFactor": 0.15, "roughnessFactor": 0.65},
            "doubleSided": False,
        })
        self.mat_by_colour[colour] = len(self.mats) - 1
        return self.mat_by_colour[colour]

    def mesh(self, name, pos, nrm, idx, colour):
        s = self.scale
        pdata = b"".join(struct.pack("<3f", p[0] * s, p[1] * s, p[2] * s) for p in pos)
        ndata = b"".join(struct.pack("<3f", *n) for n in nrm)
        idata = b"".join(struct.pack("<I", i) for i in idx)
        pv, nv, iv = self._view(pdata, 34962), self._view(ndata, 34962), self._view(idata, 34963)
        mn = [min(p[i] for p in pos) * s for i in range(3)]
        mx = [max(p[i] for p in pos) * s for i in range(3)]
        self.acc.append({"bufferView": pv, "componentType": 5126, "count": len(pos),
                         "type": "VEC3", "min": mn, "max": mx})
        self.acc.append({"bufferView": nv, "componentType": 5126, "count": len(nrm),
                         "type": "VEC3"})
        self.acc.append({"bufferView": iv, "componentType": 5125, "count": len(idx),
                         "type": "SCALAR"})
        a = len(self.acc) - 3
        self.meshes.append({"name": name, "primitives": [
            {"attributes": {"POSITION": a, "NORMAL": a + 1}, "indices": a + 2,
             "material": self.material(colour)}]})
        return len(self.meshes) - 1

    def node(self, name, children=None, mesh=None, translation=None, rot_z_deg=None, extras=None):
        n = {"name": name}
        if children:
            n["children"] = children
        if mesh is not None:
            n["mesh"] = mesh
        if translation:
            n["translation"] = [translation[0] * self.scale, translation[1] * self.scale,
                                translation[2] * self.scale]
        if rot_z_deg:
            h = math.radians(rot_z_deg) / 2.0
            n["rotation"] = [0.0, 0.0, math.sin(h), math.cos(h)]
        if extras:
            n["extras"] = extras
        self.nodes.append(n)
        return len(self.nodes) - 1

    def part_node(self, p):
        a = p.p
        if p.kind == "box":
            pos, nrm, idx = box_mesh(p.s[0], p.s[1], p.s[2], a[0], a[1], a[2])
        else:
            pos, nrm, idx = cyl_mesh(p.s[0], p.s[1], p.s[2], a[0], a[1], a[2])
        m = self.mesh(p.name, pos, nrm, idx, p.c if hasattr(p, "c") else COLOUR(p.colour))
        ex = {"module": getattr(self, "module", ""), "part": p.name, "group": p.group,
              "support": p.support, "io": p.tag, "note": p.note}
        return self.node(p.name, mesh=m, extras=ex)

    def slab(self, name, x, y, w, h, z, t, colour):
        pos, nrm, idx = box_mesh(w, h, t, x, y, z)
        return self.node(name, mesh=self.mesh(name, pos, nrm, idx, colour))

    def dump(self, scene_roots):
        return {
            "asset": {"version": "2.0",
                      "generator": "stf-cad/hbw/stf_gltf.py - generated from hbw_model.P"},
            "scene": 0,
            "scenes": [{"nodes": scene_roots}],
            "nodes": self.nodes, "meshes": self.meshes, "materials": self.mats,
            "accessors": self.acc, "bufferViews": self.views,
            "buffers": [{"byteLength": len(self.buf),
                         "uri": "data:application/octet-stream;base64,"
                                + base64.b64encode(bytes(self.buf)).decode()}],
        }


BASE_GREY = "#8d949b"


def _solid(parts):
    """Every part except the per-module plates, which the base replaces."""
    return [p for p in parts if p.group != "frame"]


COLOURS = {
    "black": "#2b2b2f", "red": "#cf3a2f", "ftred": "#e0492f", "alu": "#d6d9da",
    "steel": "#aeb4b8", "white": "#f2f0ea", "colour": "#2f6fd0", "green": "#1b8f52",
    "amber": "#e0a02a", "grey": "#8b9196", "darkgrey": "#474b52", "slate": "#3a3f44",
}


def COLOUR(name):
    if isinstance(name, str) and name.startswith("#"):
        return name
    return COLOURS.get(name, "#8b9196")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", choices=("mm", "m"), default="mm")
    ap.add_argument("-o", "--out", default="STF_Factory.gltf")
    ap.add_argument("--travel", type=float, default=P["CV_X"])
    ap.add_argument("--lift", type=float, default=120.0)
    ap.add_argument("--fork", type=float, default=0.0)
    ap.add_argument("--swivel", type=float, default=0.0)
    ap.add_argument("--plunge", type=float, default=VG.V["PLUNGE"][1])
    ap.add_argument("--reach", type=float, default=0.0)
    a = ap.parse_args()

    from hbw_model import check as hbw_check
    for name, fails in (("HBW", hbw_check(verbose=False)), ("VGR", VG.check(verbose=False)),
                        ("OVEN", OM.check(verbose=False)),
                        ("SORTING", SM.check(verbose=False)),
                        ("CROSS", FL.check_cross() + FL.check_stations())):
        if fails:
            print(f"REFUSING to export - {name} fails its clearance proof:")
            print("\n".join(fails)); sys.exit(1)

    g = Gltf(1.0 if a.units == "mm" else 0.001)
    roots = build_roots(g, a)
    _write(g, roots, a)


def build_roots(g, a):
    """The articulated factory node tree. Shared by the FreeCAD .gltf (here) and
    the web .glb (stf_web_glb.py), so both carry the same joints and parts."""
    fl = FL.doc()

    g.module = "table"
    # ---- table + reserved footprints
    fx, fy, ft = fl["plate"]
    # ONE continuous grey base under all four modules (their own plates are
    # not drawn - they would sit coplanar inside it)
    roots = [g.slab("Base_Plate", 0, 0, fx, fy, -10 - ft, 10 + ft, BASE_GREY)]
    for n in fl["neighbours"]:
        x, y, w, h = n["rect"]
        roots.append(g.slab(f"Reserved_{n['n']}_{n['id']}", x, y, w, h, -10, 3, "#333a42"))

    g.module = "hbw"
    # ---- HBW, articulated
    hf = hbw_by_frame()
    fork_n = [g.part_node(_c(p)) for p in _solid(hf["fork"])]
    lift_n = [g.part_node(_c(p)) for p in _solid(hf["lift"])]
    lift_n.append(g.node("J3_Ausleger_Y", children=fork_n, translation=(0, a.fork, 0)))
    trav_n = [g.part_node(_c(p)) for p in _solid(hf["travel"])]
    trav_n.append(g.node("J2_Lift_Z", children=lift_n, translation=(0, 0, a.lift)))
    world_n = [g.part_node(_c(p)) for p in _solid(hf["world"])]
    world_n.append(g.node("J1_Travel_X", children=trav_n, translation=(a.travel, 0, 0)))
    roots.append(g.node("HBW", children=world_n, translation=(FL.TX, FL.TY, 0),
                        rot_z_deg=FL.ROTATE_DEG,
                        extras={"module": "Automatisiertes Hochregallager 24V (536631)"}))

    g.module = "vgr"
    # ---- VGR, articulated (swivel pivots on the tower axis)
    vp = {f: [] for f in VG.FRAMES}
    for p in VG.build(0.0, VG.V["PLUNGE"][1], 0.0):
        vp[p.frame].append(p)
    reach_n = [g.part_node(_c(p)) for p in _solid(vp["reach"])]
    plunge_n = [g.part_node(_c(p)) for p in _solid(vp["plunge"])]
    plunge_n.append(g.node("J_Reach", children=reach_n, translation=(0, -a.reach, 0)))
    sw_n = [g.part_node(_c(p)) for p in _solid(vp["swivel"])]
    sw_n.append(g.node("J_Plunge", children=plunge_n,
                       translation=(0, 0, a.plunge - VG.V["PLUNGE"][1])))
    cx, cy = VG.V["CX"], VG.V["CY"]
    pivot_in = g.node("_swivel_pivot", children=sw_n, translation=(-cx, -cy, 0))
    swivel = g.node("J_Swivel", children=[pivot_in], translation=(cx, cy, 0),
                    rot_z_deg=a.swivel)
    vworld = [g.part_node(_c(p)) for p in _solid(vp["world"])] + [swivel]
    vx, vy = FL.VGR_AT
    roots.append(g.node("VGR", children=vworld, translation=(vx, vy, 0),
                        extras={"module": "Vakuum-Sauggreifer 24V (536632)"}))

    g.module = "oven"
    # ---- Oven, articulated
    op = {f: [] for f in OM.FRAMES}
    for p in OM.build(OM.O["SLIDER"][1], OM.O["DOOR_Z"][1], 0.0, OM.O["SAUGER"][1], 0.0):
        op[p.frame].append(p)
    low_n = [g.part_node(_c(q)) for q in op["lower"]]
    sau_n = [g.part_node(_c(q)) for q in op["sauger"]]
    sau_n.append(g.node("J_Lower", children=low_n, translation=(0, 0, 0)))
    ow = [g.part_node(_c(q)) for q in _solid(op["world"])]
    ow.append(g.node("J_Ofenschieber", children=[g.part_node(_c(q)) for q in op["slider"]],
                     translation=(0, 0, 0)))
    ow.append(g.node("J_Ofentuer", children=[g.part_node(_c(q)) for q in op["door"]],
                     translation=(0, 0, 0)))
    tcx, tcy = OM.O["TT"]
    tin = g.node("_turn_pivot", children=[g.part_node(_c(q)) for q in op["turn"]],
                 translation=(-tcx, -tcy, 0))
    ow.append(g.node("J_Drehkranz", children=[tin], translation=(tcx, tcy, 0), rot_z_deg=0.0))
    ow.append(g.node("J_Sauger", children=sau_n, translation=(0, 0, 0)))
    ow.append(g.node("J_Auswerfer", children=[g.part_node(_c(q)) for q in op["push"]],
                     translation=(0, 0, 0)))
    roots.append(g.node("OVEN", children=ow, translation=(FL.OVEN_TX, FL.OVEN_TY, 0),
                        rot_z_deg=FL.OVEN_ROT,
                        extras={"module": "Multi-Bearbeitungsstation mit Brennofen 24V (536632)"}))

    g.module = "sorting"
    # ---- Sorting line, articulated (three ejectors)
    sp = {f: [] for f in SM.FRAMES}
    for p in SM.build():
        sp[p.frame].append(p)
    sw = [g.part_node(_c(q)) for q in _solid(sp["world"])]
    for i, col in enumerate(SM.COLOURS):
        sw.append(g.node(f"J_Auswurf_{col}",
                         children=[g.part_node(_c(q)) for q in sp[f"push{i}"]],
                         translation=(0, 0, 0)))
    roots.append(g.node("SORTING", children=sw,
                        translation=(FL.SORT_TX, FL.SORT_TY, 0), rot_z_deg=FL.SORT_ROT,
                        extras={"module": "Sortierstrecke mit Farberkennung 24V (536633)"}))

    g.module = "plc"
    import plc_model as PM
    roots.append(g.node("PLC", children=[g.part_node(_c(q)) for q in _solid(PM.build())],
                        translation=(FL.PLC_AT[0], FL.PLC_AT[1], 0),
                        extras={"module": "PLC cabinet: WDR-120-24 + RevPi Core 3 + 3x DIO + AIO"}))
    return roots


def _write(g, roots, a):
    doc = g.dump(roots)
    with open(a.out, "w") as fh:
        json.dump(doc, fh)
    import os
    print(f"wrote {os.path.abspath(a.out)}  ({os.path.getsize(a.out)/1024:.0f} kB)")
    print(f"  units {a.units}, Z up, factory frame; {len(g.meshes)} meshes, "
          f"{len(g.mats)} materials")
    print("  joints: HBW/J1_Travel_X, J2_Lift_Z, J3_Ausleger_Y; VGR/J_Swivel, J_Plunge, J_Reach")
    print(f"  for EXACT B-rep in FreeCAD open STF_Factory.FCStd - glTF meshes cylinders as {SEG}-gons")


class _c:
    """Adapter so HBW and VGR parts both expose .c for the mesh writer."""
    def __init__(self, p):
        self.__dict__.update(p.__dict__)
        self.c = COLOUR(p.colour)


if __name__ == "__main__":
    main()
