"""
DT-1, step 2: the mesh cache -> OpenUSD stage, USDZ package, glTF binary, scene index.

    .venv-twin/bin/python twin/build_scene.py        (from stf-cad/line2, after twin/export_mesh.py)

USD   twin/out/stf2.usda            root: defaultPrim /STF2, metersPerUnit 0.001 (mm), upAxis Z, one sublayer per module
      twin/out/layers/protos.usdc   class /Prototypes/P<k> (Xform) / geo (UsdGeom.Mesh, mm, normals) + /Looks
      twin/out/layers/<module>.usda /STF2/<module>/<group>/<part>: an Xform that references its prototype, instanceable
                                    when the prototype is shared; xformOp order = [transform:anim] (moving parts only,
                                    identity here - DT-2/DT-3 drive it with the timeline's Placement(t, q)) then
                                    translate:offset (the prototype's place in the CAD); stf:* attributes
USDZ  twin/out/stf2.usdz            the flattened stage, packaged (Quick Look / Reality Composer Pro)
GLB   twin/out/stf2.glb             glTF 2.0: root node scales mm -> m and turns Z-up into glTF's Y-up; one node per
                                    part (name = part name, extras = stf:*); a mesh per (prototype, colour), shared
Index twin/out/scene_index.json     part -> prim path, GLB node, module, group, tag, moving, prototype, triangles
"""
import json
import os
import re
import struct
import sys
from collections import Counter, defaultdict

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils, Vt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
CACHE = os.path.join(OUT, "cache")


def ident(s):
    s = re.sub(r"[^A-Za-z0-9_]", "_", s)
    return s if s and not s[0].isdigit() else "_" + s


def rgba(colour):
    """'#rrggbb' or '#rrggbb/70' -> ((r, g, b), opacity); '/70' = 70 % TRANSPARENT, as in fcstd_colour (PC panels)."""
    c, _, a = colour.partition("/")
    h = c.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)), (1.0 - int(a) / 100 if a else 1.0)


def load():
    idx = json.load(open(os.path.join(CACHE, "index.json")))
    npz = np.load(os.path.join(CACHE, "meshes.npz"))
    return idx["meta"], idx["solids"], npz


# ------------------------------------------------------------------ USD
def write_usd(meta, solids, npz):
    import shutil
    shutil.rmtree(os.path.join(OUT, "layers"), ignore_errors=True)       # every run writes the stage from scratch
    for f in ("stf2.usda", "stf2.usdz"):
        if os.path.exists(os.path.join(OUT, f)):
            os.remove(os.path.join(OUT, f))
    os.makedirs(os.path.join(OUT, "layers"), exist_ok=True)
    uses = Counter(s["proto"] for s in solids)
    colours = sorted({s["colour"] for s in solids})
    look = {c: f"/Looks/M_{i:03d}" for i, c in enumerate(colours)}

    pl = Sdf.Layer.CreateNew(os.path.join(OUT, "layers", "protos.usdc"))
    ps = Usd.Stage.Open(pl)
    UsdGeom.SetStageMetersPerUnit(ps, 0.001)
    UsdGeom.SetStageUpAxis(ps, UsdGeom.Tokens.z)
    ps.CreateClassPrim("/Prototypes")
    for k in range(meta["prototypes"]):
        UsdGeom.Xform.Define(ps, f"/Prototypes/P{k}")             # the instance shares this prim's CHILDREN:
        m = UsdGeom.Mesh.Define(ps, f"/Prototypes/P{k}/geo")      # the mesh must sit below the referenced root
        v, n, i = npz[f"v{k}"], npz[f"n{k}"], npz[f"i{k}"]
        m.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(v))
        m.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(n))
        m.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
        m.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(np.full(len(i), 3, dtype=np.int32)))
        m.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(i.astype(np.int32).ravel()))
        m.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        m.CreateExtentAttr(Vt.Vec3fArray([Gf.Vec3f(*map(float, v.min(0))), Gf.Vec3f(*map(float, v.max(0)))]))
    UsdGeom.Scope.Define(ps, "/Looks")
    for c, path in look.items():
        (r, g, b), a = rgba(c)
        mat = UsdShade.Material.Define(ps, path)
        sh = UsdShade.Shader.Define(ps, path + "/Surface")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(r, g, b))
        sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)
        sh.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        sh.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(a)
        mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    pl.Save()

    root = Usd.Stage.CreateNew(os.path.join(OUT, "stf2.usda"))
    UsdGeom.SetStageMetersPerUnit(root, 0.001)
    UsdGeom.SetStageUpAxis(root, UsdGeom.Tokens.z)
    top = UsdGeom.Xform.Define(root, "/STF2")
    root.SetDefaultPrim(top.GetPrim())
    Usd.ModelAPI(top).SetKind("assembly")
    root.GetRootLayer().customLayerData = dict(
        stf_source=meta["source"], stf_solids=meta["solids"], stf_prototypes=meta["prototypes"],
        stf_triangles=meta["triangles_instanced"], stf_deflection_mm=meta["deflection"],
        stf_note="generated by twin/build_scene.py from line_model / line_cad_precise - do not edit")
    by_mod = defaultdict(list)
    for s in solids:
        by_mod[s["module"]].append(s)
    sub = ["layers/protos.usdc"]
    paths = {}
    def xf(layer, path, kind=None):
        spec = Sdf.CreatePrimInLayer(layer, path)
        spec.specifier, spec.typeName = Sdf.SpecifierDef, "Xform"
        if kind:
            spec.SetInfo("kind", kind)
        return spec

    def attr(spec, name, typ, value, custom=True, uniform=False):
        a = Sdf.AttributeSpec(spec, name, typ, Sdf.VariabilityUniform if uniform else Sdf.VariabilityVarying, custom)
        a.default = value

    for mod in sorted(by_mod, key=lambda m: int(m[1:].split("_")[0])):
        lp = os.path.join("layers", f"{mod}.usda")
        ml = Sdf.Layer.CreateNew(os.path.join(OUT, lp))      # pure Sdf: no composition while authoring
        with Sdf.ChangeBlock():
            xf(ml, "/STF2").specifier = Sdf.SpecifierOver
            xf(ml, f"/STF2/{mod}", "group")
            seen = set()
            for s in by_mod[mod]:
                g = f"/STF2/{mod}/{ident(s['group'])}"
                if g not in seen:
                    xf(ml, g)
                    seen.add(g)
                path = f"{g}/{ident(s['name'])}"
                spec = xf(ml, path)
                spec.referenceList.Prepend(Sdf.Reference(primPath=f"/Prototypes/P{s['proto']}"))
                if uses[s["proto"]] > 1:
                    spec.instanceable = True
                order = []
                if s["moving"]:
                    attr(spec, "xformOp:transform:anim", Sdf.ValueTypeNames.Matrix4d, Gf.Matrix4d(1.0), custom=False)
                    order.append("xformOp:transform:anim")
                attr(spec, "xformOp:translate:offset", Sdf.ValueTypeNames.Double3, Gf.Vec3d(*s["offset"]), custom=False)
                order.append("xformOp:translate:offset")
                attr(spec, "xformOpOrder", Sdf.ValueTypeNames.TokenArray, Vt.TokenArray(order), custom=False,
                     uniform=True)
                spec.SetInfo("apiSchemas", Sdf.TokenListOp.Create(prependedItems=["MaterialBindingAPI"]))
                rel = Sdf.RelationshipSpec(spec, "material:binding", False)
                rel.targetPathList.Prepend(Sdf.Path(look[s["colour"]]))
                for k_ in ("name", "module", "group", "hw", "tag", "note"):
                    attr(spec, f"stf:{k_}", Sdf.ValueTypeNames.String, s[k_] or "")
                attr(spec, "stf:moving", Sdf.ValueTypeNames.Bool, bool(s["moving"]))
                attr(spec, "stf:fastener", Sdf.ValueTypeNames.Bool, bool(s["fastener"]))
                paths[s["name"]] = path
        ml.Save()
        sub.insert(0, lp)
    root.GetRootLayer().subLayerPaths = sub
    root.GetRootLayer().Save()

    # USDZ: flatten (prototypes become flattened prototypes, instancing kept), then package
    st = Usd.Stage.Open(os.path.join(OUT, "stf2.usda"))
    flat = os.path.join(OUT, "stf2_flat.usdc")
    st.Export(flat)
    usdz = os.path.join(OUT, "stf2.usdz")
    ok = UsdUtils.CreateNewUsdzPackage(Sdf.AssetPath(flat), usdz)
    os.remove(flat)
    return paths, ok


# ------------------------------------------------------------------ glTF 2.0 binary
def write_glb(meta, solids, npz):
    bin_, views, accs, meshes, mats, nodes = bytearray(), [], [], [], [], []

    def view(data, target):
        while len(bin_) % 4:
            bin_.append(0)
        views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=len(data), target=target))
        bin_.extend(data)
        return len(views) - 1

    def acc(arr, ctype, typ, target, minmax=False):
        a = dict(bufferView=view(arr.tobytes(), target), componentType=ctype, count=int(len(arr)), type=typ)
        if minmax:
            a["min"] = [float(x) for x in arr.min(0)]
            a["max"] = [float(x) for x in arr.max(0)]
        accs.append(a)
        return len(accs) - 1

    mat_of, geo_of, mesh_of = {}, {}, {}
    for s in solids:
        c = s["colour"]
        if c not in mat_of:
            (r, g, b), a = rgba(c)
            m = dict(name=c, pbrMetallicRoughness=dict(baseColorFactor=[r, g, b, a], metallicFactor=0.0,
                                                       roughnessFactor=0.5), doubleSided=False)
            if a < 1.0:
                m["alphaMode"] = "BLEND"
            mats.append(m)
            mat_of[c] = len(mats) - 1
        k = s["proto"]
        if k not in geo_of:
            v, n, i = npz[f"v{k}"], npz[f"n{k}"], npz[f"i{k}"]
            idx = i.astype(np.uint16 if len(v) < 65536 else np.uint32).ravel()
            geo_of[k] = (acc(v.astype(np.float32), 5126, "VEC3", 34962, True), acc(n.astype(np.float32), 5126, "VEC3", 34962),
                         acc(idx, 5123 if idx.dtype == np.uint16 else 5125, "SCALAR", 34963))
        key = (k, c)
        if key not in mesh_of:
            p, nn, ii = geo_of[k]
            meshes.append(dict(name=f"P{k}", primitives=[dict(attributes=dict(POSITION=p, NORMAL=nn), indices=ii,
                                                                  material=mat_of[c])]))
            mesh_of[key] = len(meshes) - 1
    nodes.append(dict(name="STF2", rotation=[-0.7071067811865476, 0.0, 0.0, 0.7071067811865476],
                      scale=[0.001, 0.001, 0.001], children=[], extras=dict(units="mm inside, m outside", up="Z")))
    mod_node, node_of = {}, {}
    for s in solids:
        if s["module"] not in mod_node:
            nodes.append(dict(name=s["module"], children=[]))
            mod_node[s["module"]] = len(nodes) - 1
            nodes[0]["children"].append(len(nodes) - 1)
        nodes.append(dict(name=s["name"], mesh=mesh_of[(s["proto"], s["colour"])], translation=s["offset"],
                          extras={f"stf:{k}": s[k] for k in ("module", "group", "hw", "tag", "moving", "fastener")}))
        node_of[s["name"]] = len(nodes) - 1
        nodes[mod_node[s["module"]]]["children"].append(len(nodes) - 1)
    gltf = dict(asset=dict(version="2.0", generator="stf-cad/line2/twin/build_scene.py"), scene=0,
                scenes=[dict(name="STF2", nodes=[0])], nodes=nodes, meshes=meshes, materials=mats,
                accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    bin_ += b"\0" * (-len(bin_) % 4)
    path = os.path.join(OUT, "stf2.glb")
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_)))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        fh.write(struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_))
    return node_of


def main():
    meta, solids, npz = load()
    paths, ok = write_usd(meta, solids, npz)
    node_of = write_glb(meta, solids, npz)
    index = {s["name"]: dict(prim=paths[s["name"]], glb_node=node_of[s["name"]], module=s["module"], group=s["group"],
                             tag=s["tag"], moving=s["moving"], proto=s["proto"], tris=s["tris"]) for s in solids}
    json.dump(dict(meta=meta, parts=index), open(os.path.join(OUT, "scene_index.json"), "w"), indent=0)
    size = {f: os.path.getsize(os.path.join(OUT, f)) / 1e6 for f in ("stf2.usdz", "stf2.glb")}
    print(f"scene: {meta['solids']} parts, {meta['prototypes']} prototypes, {meta['triangles_instanced']:,} triangles; "
          f"stf2.usda + {len({s['module'] for s in solids})} module layers, stf2.usdz {size['stf2.usdz']:.1f} MB"
          f"{'' if ok else ' (PACKAGING FAILED)'}, stf2.glb {size['stf2.glb']:.1f} MB")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
