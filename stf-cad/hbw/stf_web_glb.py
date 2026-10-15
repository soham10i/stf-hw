"""
Export the whole factory as ONE binary .glb for a three.js viewer, plus a
sidecar JSON with the parts table and the joint table.

    python3 stf_web_glb.py [--out-dir ~/workspace/stf-factory/web/public/assets]

Same node tree as stf_gltf.py (build_roots is shared), so the web model and the
FreeCAD model carry identical parts and joints. What differs is the target:

    stf_gltf.py    .gltf, Z up, millimetres      -> FreeCAD
    stf_web_glb.py .glb,  Y up, metres, PBR      -> three.js / any web viewer

Vertex data stays in the factory's Z-up frame; a single root node rotates it
-90 deg about X so +Z becomes three.js +Y. The joint nodes therefore still move
along their factory axes (J1_Travel_X along local +X, J2_Lift_Z along local +Z
...), and the viewer drives them exactly as the CAD model does.

Materials are PBR, classed from the model's own colour names: alu/steel parts
are metal, belts rubber, everything else ft plastic. Every mesh node carries
extras {module, part}, which three.js exposes as userData, so a click on any
part finds its row in the parts table.

Refuses to export unless every clearance proof passes, like every generator.
"""
import argparse, json, math, os, struct, sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                       # inside freecadcmd: tessellate the PRECISE B-rep
    import FreeCAD as App  # noqa: F401
    import detail
    PRECISE = True
except ImportError:        # plain python: the proven box/cylinder envelopes
    PRECISE = False

import stf_gltf as SG
import parts_table as PT
import factory_layout as FL
import hbw_model as HM
import oven_model as OM
import sorting_model as SM
import vgr_model as VG

DEFAULT_OUT = os.path.expanduser("~/workspace/stf-factory/web/public/assets")

# colour name -> material class. Driven by the model's own colour vocabulary,
# so a part that is drawn aluminium is also shaded as aluminium.
METAL = {"alu", "steel"}
RUBBER = {"darkgrey"}
PBR = {
    #            metallic roughness
    "metal":   (0.85, 0.32),
    "rubber":  (0.00, 0.92),
    "plastic": (0.00, 0.55),     # ft ABS: satin, not glossy
    "food":    (0.00, 0.80),     # the cookies
}


def material_class(p):
    name = p.colour
    if isinstance(name, str) and name.startswith("#"):
        return "food"            # only pipeline flavours arrive as literal hex
    if name in METAL:
        return "metal"
    if name in RUBBER:
        return "rubber"
    return "plastic"


def _linear(v):
    """sRGB transfer function, inverted (IEC 61966-2-1)."""
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


class WebGltf(SG.Gltf):
    """Gltf with PBR material classes and a binary .glb writer."""

    def __init__(self):
        super().__init__(0.001)                     # mm -> m
        self._cls = "plastic"

    def material(self, colour):
        key = (colour, self._cls)
        if key in self.mat_by_colour:
            return self.mat_by_colour[key]
        c = colour.lstrip("#")
        # glTF baseColorFactor is LINEAR; the model's hex colours are sRGB. Writing
        # them straight in makes three.js brighten them twice (ft red -> salmon).
        rgb = [_linear(int(c[i:i + 2], 16) / 255.0) for i in (0, 2, 4)]
        metal, rough = PBR[self._cls]
        self.mats.append({
            "name": f"{self._cls}:{colour}",
            "pbrMetallicRoughness": {"baseColorFactor": rgb + [1.0],
                                     "metallicFactor": metal, "roughnessFactor": rough},
        })
        self.mat_by_colour[key] = len(self.mats) - 1
        return self.mat_by_colour[key]

    # chordal tolerance (mm) per kind of detail: planar blocks cost nothing,
    # helical threads and the spring are where the triangles go
    # (linear mm, angular rad). The ANGULAR bound is what matters on swept
    # helices: linear-only tessellation put 27k triangles in 100 mm of thread.
    TOLS = {"thread": (0.4, 0.7), "spring": (0.3, 0.5), "cyl": (0.15, 0.35), "box": (0.1, 0.5)}

    def part_node(self, p):
        self._cls = material_class(p)
        try:
            if not PRECISE:
                return super().part_node(p)
            shp = detail.precise(p, SIBLINGS)
            kind = ("thread" if p.mech.startswith("thread:") else
                    "spring" if p.mech == "spring" else p.kind)
            pos, nrm, idx = face_mesh(shp, self.TOLS[kind])
            m = self.mesh(p.name, pos, nrm, idx, p.c if hasattr(p, "c") else SG.COLOUR(p.colour))
            ex = {"module": getattr(self, "module", ""), "part": p.name, "group": p.group,
                  "support": p.support, "io": p.tag, "note": p.note}
            return self.node(p.name, mesh=m, extras=ex)
        finally:
            self._cls = "plastic"

    def slab(self, name, x, y, w, h, z, t, colour):
        self._cls = "plastic"
        return super().slab(name, x, y, w, h, z, t, colour)

    def glb(self, roots):
        # Z-up factory -> Y-up three.js: -90 deg about X maps +Z to +Y.
        h = math.radians(-90.0) / 2.0
        top = {"name": "STF_Factory", "children": roots,
               "rotation": [math.sin(h), 0.0, 0.0, math.cos(h)],
               "extras": {"units": "m", "source_frame": "factory, Z up"}}
        self.nodes.append(top)
        doc = {
            "asset": {"version": "2.0",
                      "generator": "stf-cad/hbw/stf_web_glb.py - generated from the "
                                   "hbw/vgr/oven/sorting models"},
            "scene": 0, "scenes": [{"nodes": [len(self.nodes) - 1]}],
            "nodes": self.nodes, "meshes": self.meshes, "materials": self.mats,
            "accessors": self.acc, "bufferViews": self.views,
            "buffers": [{"byteLength": len(self.buf)}],
        }
        js = json.dumps(doc, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        bn = bytes(self.buf) + b"\0" * (-len(self.buf) % 4)
        total = 12 + 8 + len(js) + 8 + len(bn)
        return (struct.pack("<III", 0x46546C67, 2, total)
                + struct.pack("<II", len(js), 0x4E4F534A) + js
                + struct.pack("<II", len(bn), 0x004E4942) + bn)


def face_mesh(shape, tol):
    import MeshPart
    lin, ang = tol
    """Tessellate face by face: normals are smooth WITHIN a face and sharp
    between faces, so a chamfered block keeps crisp edges and a thread reads
    round. Each face's winding is checked against its true surface normal."""
    pos, nrm, idx = [], [], []
    for f in shape.Faces:
        m = MeshPart.meshFromShape(Shape=f, LinearDeflection=lin, AngularDeflection=ang,
                                   Relative=False)
        pts, tris = m.Topology
        if not tris:
            continue
        acc = [[0.0, 0.0, 0.0] for _ in pts]
        (a, b, c) = tris[0]
        n0 = (pts[b] - pts[a]).cross(pts[c] - pts[a])
        try:
            u, v = f.Surface.parameter((pts[a] + pts[b] + pts[c]) * (1.0 / 3.0))
            flip = n0.dot(f.normalAt(u, v)) < 0
        except Exception:
            flip = False
        base = len(pos)
        for (a, b, c) in tris:
            if flip:
                b, c = c, b
            n = (pts[b] - pts[a]).cross(pts[c] - pts[a])
            for k in (a, b, c):
                acc[k][0] += n.x; acc[k][1] += n.y; acc[k][2] += n.z
            idx += [base + a, base + b, base + c]
        for q, nv in zip(pts, acc):
            ln = math.sqrt(nv[0] ** 2 + nv[1] ** 2 + nv[2] ** 2) or 1.0
            pos.append((q.x, q.y, q.z))
            nrm.append((nv[0] / ln, nv[1] / ln, nv[2] / ln))
    return pos, nrm, idx


# the belt loop needs to know where its two pulleys are
SIBLINGS = {p.name: p for p in HM.build()}


def joint_table():
    """What the viewer's sliders drive. `node` is the glTF node name; `axis` is
    in that node's local (factory, Z-up) frame; value -> node transform is
    position = sign * (value - offset) mm, or rotation = value deg."""
    P, V = HM.P, VG.V
    return [
        {"module": "hbw", "joint": "travel", "node": "J1_Travel_X", "kind": "prismatic",
         "axis": "x", "sign": 1, "offset": 0.0, "limits": list(P["TRAVEL"]),
         "home": P["CV_X"], "io": "M2 Q3/Q4, ref I1"},
        {"module": "hbw", "joint": "lift", "node": "J2_Lift_Z", "kind": "prismatic",
         "axis": "z", "sign": 1, "offset": 0.0, "limits": list(P["LIFT"]),
         "home": 120.0, "io": "M3 Q5/Q6, ref I4"},
        {"module": "hbw", "joint": "fork", "node": "J3_Ausleger_Y", "kind": "prismatic",
         "axis": "y", "sign": 1, "offset": 0.0, "limits": list(P["FORK"]),
         "home": 0.0, "io": "M4 Q7/Q8, ref I5/I6"},
        {"module": "vgr", "joint": "swivel", "node": "J_Swivel", "kind": "revolute",
         "axis": "z", "sign": 1, "offset": 0.0, "limits": list(V["SWIVEL"]),
         "home": 0.0, "io": "M3 Q5/Q6, ref I3"},
        {"module": "vgr", "joint": "plunge", "node": "J_Plunge", "kind": "prismatic",
         "axis": "z", "sign": 1, "offset": V["PLUNGE"][1], "limits": list(V["PLUNGE"]),
         "home": V["PLUNGE"][1], "io": "M1 Q1/Q2, ref I1"},
        {"module": "vgr", "joint": "reach", "node": "J_Reach", "kind": "prismatic",
         "axis": "y", "sign": -1, "offset": 0.0, "limits": list(V["REACH"]),
         "home": 0.0, "io": "M2 Q3/Q4, ref I2"},
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    ap.add_argument("--envelope", action="store_true",
                    help="plain-python fallback: write box/cylinder envelopes")
    a, _ = ap.parse_known_args()      # freecadcmd passes its own argv through
    if not PRECISE and not a.envelope:
        print("stf_web_glb: not running inside FreeCAD, so it would write the coarse "
              "envelope model over the precise one. Run\n  freecadcmd build_cad.py\n"
              "or pass --envelope if the box/cylinder version is really wanted.")
        sys.exit(2)

    for name, fails in (("HBW", HM.check(verbose=False)), ("VGR", VG.check(verbose=False)),
                        ("OVEN", OM.check(verbose=False)), ("SORTING", SM.check(verbose=False)),
                        ("CROSS", FL.check_cross() + FL.check_stations())):
        if fails:
            print(f"REFUSING to export - {name} fails its clearance proof:")
            print("\n".join(fails)); sys.exit(1)

    jt = joint_table()
    home = {j["joint"]: j["home"] for j in jt}
    pose = SimpleNamespace(travel=home["travel"], lift=home["lift"], fork=home["fork"],
                           swivel=home["swivel"], plunge=home["plunge"], reach=home["reach"])
    g = WebGltf()
    roots = SG.build_roots(g, pose)
    blob = g.glb(roots)

    os.makedirs(a.out_dir, exist_ok=True)
    glb_path = os.path.join(a.out_dir, "stf_factory.glb")
    with open(glb_path, "wb") as fh:
        fh.write(blob)

    rows = PT.build_all()
    side = {
        "units": "mm (table); the .glb itself is in metres",
        "source": "stf-cad/hbw - hbw_model, vgr_model, oven_model, sorting_model",
        "parts": rows,
        "joints": jt,
        "open_questions": [
            "Farbsensor 128599 outputs analogue 0-2 VDC; the RevPi DIO has no analogue "
            "input and the Belegungsplan marks that terminal 'nicht verwendet'.",
            "HBW cover sensors CS1/CS2/LB1/LB2 (AUX1-4) have no terminal in the "
            "536631 Belegungsplan.",
            "Every dimension is a model value until measured at the machine.",
        ],
    }
    with open(os.path.join(a.out_dir, "stf_parts.json"), "w") as fh:
        json.dump(side, fh, indent=1)

    cls = {}
    for m in g.mats:
        k = m["name"].split(":")[0]
        cls[k] = cls.get(k, 0) + 1
    print(f"wrote {glb_path}  ({len(blob)/1024:.0f} kB)")
    ntri = sum(a_["count"] for a_ in g.acc if a_["type"] == "SCALAR") // 3
    print(f"  {len(g.meshes)} meshes, {ntri} triangles, {len(g.mats)} materials {cls}, "
          f"Y up, metres, {'PRECISE B-rep tessellation' if PRECISE else 'envelope primitives'}")
    print(f"wrote {os.path.join(a.out_dir, 'stf_parts.json')}  ({len(rows)} parts, {len(jt)} joints)")


# freecadcmd runs a script with __name__ = its module name, not "__main__"
if __name__ == "__main__" or sys.argv[-1].endswith("stf_web_glb.py"):
    main()
