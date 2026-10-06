"""
Load the twin's USD stage into Blender the way the twin needs it (used by the preview render and by DT-7).

    blender -b -P twin/blender_load.py -- [--render out.png] [--module M3_oven]

Two importer facts of Blender 5.2 that this works around:
  - merge_parent_xform (default on) folds each part's Xform into its single child mesh and names the result after
    the child ('geo'): the part names are lost. We import with it off, so every part is an Empty named by its prim,
    carrying its 'geo' mesh.
  - inputs:opacity of UsdPreviewSurface is not imported (Alpha stays 1, checked with a minimal valid file). We read the
    opacity from the stage with Blender's bundled pxr and set Alpha + blended rendering on those materials.
The part name, module, tag of every Empty are set as custom properties (stf_name, stf_module, stf_tag) from the stage.
"""
import os
import sys

import bpy
from pxr import Usd, UsdShade

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(HERE, "out", "stf2.usda")


def load(module=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mask = f"/STF2/{module};/Looks" if module else ""        # the materials live in /Looks
    bpy.ops.wm.usd_import(filepath=STAGE, support_scene_instancing=False, merge_parent_xform=False, prim_path_mask=mask)
    st = Usd.Stage.Open(STAGE)
    alpha = {}
    for p in st.Traverse():
        if p.IsA(UsdShade.Material):
            sh = UsdShade.Shader(st.GetPrimAtPath(p.GetPath().AppendChild("Surface")))
            v = sh.GetInput("opacity").Get() if sh else None
            if v is not None and v < 1.0:
                alpha[p.GetName()] = float(v)
    for m in bpy.data.materials:
        a = alpha.get(m.name.split(".")[0])
        if a is None or not m.use_nodes:
            continue
        for n in m.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                n.inputs["Alpha"].default_value = a
        if hasattr(m, "surface_render_method"):
            m.surface_render_method = "BLENDED"
    meta = {}
    for p in Usd.PrimRange(st.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        if p.HasAttribute("stf:name"):
            meta[p.GetName()] = {k: p.GetAttribute(f"stf:{k}").Get() for k in ("name", "module", "tag")}
    for o in bpy.data.objects:
        d = meta.get(o.name.split(".")[0]) if o.type == "EMPTY" else None
        if d:
            for k, v in d.items():
                o[f"stf_{k}"] = v or ""
    return st


def render(path, res=(1800, 1100)):
    import mathutils
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    pts = [o.matrix_world @ mathutils.Vector(c) for o in objs for c in o.bound_box]
    lo = mathutils.Vector([min(p[i] for p in pts) for i in range(3)])
    hi = mathutils.Vector([max(p[i] for p in pts) for i in range(3)])
    c, size = (lo + hi) / 2, max(hi - lo)
    sc = bpy.context.scene
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    cam.location = c + mathutils.Vector((-0.9, -1.25, 0.85)).normalized() * size * 1.35
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 40
    sc.camera = cam
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy, sun.rotation_euler = 3.5, (0.7, 0.2, -0.6)
    sc.collection.objects.link(sun)
    w = bpy.data.worlds.new("w")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    sc.world = w
    sc.render.engine = "BLENDER_EEVEE"
    sc.view_settings.view_transform = "Standard"
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    mod = argv[argv.index("--module") + 1] if "--module" in argv else None
    load(mod)
    print(f"loaded {sum(1 for o in bpy.data.objects if o.type == 'MESH')} parts", flush=True)
    if "--render" in argv:
        render(argv[argv.index("--render") + 1])
        print("rendered", argv[argv.index("--render") + 1], flush=True)
