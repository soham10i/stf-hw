"""
DT-2 in Blender: the 40 s timeline as keyframes on the DT-1 scene - open the .blend and press Space.

    blender -b -P twin/blender_anim.py -- --save                  -> twin/out/stf2_anim.blend  (~1 min)
    blender    -P twin/blender_anim.py                            (GUI: builds it and opens it, ready to play)
    blender -b -P twin/blender_anim.py -- --check                 -> twin/out/blender_boxes.json (for playback_check P3)
    blender -b -P twin/blender_anim.py -- --render 150 out.png    one frame, EEVEE

The rules are twin/playback.py's (= the FreeCAD player's): rigid parts and their screws/brackets get M(t, q) on top
of their CAD place; a reshaped track (band cookies spreading in the oven, rods extending) is drawn as the frame's
cylinder and its CAD mesh is hidden; cookies spawned by the timeline are cylinders; oven elements glow with their SSR
and cookies brown (object colour, keyed). 10 frames per second, frame k+1 = timeline frame k.
"""
import json
import os
import sys

import bmesh
import bpy
import mathutils
import numpy as np
from bpy_extras import anim_utils

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blender_load as BL                                   # noqa: E402
import playback as PB                                       # noqa: E402

MM = 0.001                                                  # Blender scene in metres (the importer converts)
OUT = os.path.join(HERE, "out")


def hex_rgba(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [1.0]


def unit_cylinder_mesh(n=96):
    me = bpy.data.meshes.new("stf_unit_cylinder")
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=n, radius1=0.5, radius2=0.5, depth=1.0)
    bmesh.ops.translate(bm, vec=(0, 0, 0.5), verts=bm.verts)          # base at z = 0, top at z = 1
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = len(p.vertices) == 4
    return me


def colour_material():
    m = bpy.data.materials.new("stf_object_colour")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.6
    return m


def keys(obj, path, values, interp="LINEAR"):
    """values: (frames, components) array -> one F-curve per component, frames 1..n."""
    ad = obj.animation_data or obj.animation_data_create()
    if ad.action is None:
        act = bpy.data.actions.new(f"{obj.name}_motion")
        slot = act.slots.new(id_type="OBJECT", name=obj.name)
        ad.action, ad.action_slot = act, slot
    cb = anim_utils.action_ensure_channelbag_for_slot(ad.action, ad.action_slot)
    values = np.asarray(values, dtype=np.float32)
    n = len(values)
    fr = np.arange(1, n + 1, dtype=np.float32)
    code = {"CONSTANT": 0, "LINEAR": 1}[interp]
    for i in range(values.shape[1]):
        fc = cb.fcurves.new(path, index=i)
        fc.keyframe_points.add(n)
        fc.keyframe_points.foreach_set("co", np.c_[fr, values[:, i]].ravel())
        fc.keyframe_points.foreach_set("interpolation", [code] * n)
        fc.update()


def key_matrices(obj, worlds):
    """worlds: list of 4x4 world matrices (metres) -> location / quaternion / scale keys in the parent's frame."""
    pinv = obj.parent.matrix_world.inverted() if obj.parent else mathutils.Matrix.Identity(4)
    obj.rotation_mode = "QUATERNION"
    loc, rot, scl = [], [], []
    prev = None
    for w in worlds:
        l, q, s = (pinv @ mathutils.Matrix(w.tolist())).decompose()
        if prev is not None and prev.dot(q) < 0:                       # keep quaternions on one hemisphere
            q = -q
        prev = q
        loc.append(l[:])
        rot.append(q[:])
        scl.append(s[:])
    keys(obj, "location", loc)
    keys(obj, "rotation_quaternion", rot)
    keys(obj, "scale", scl)


def build():
    st = BL.load()
    tl = PB.Timeline()
    sc = bpy.context.scene
    sc.render.fps, sc.frame_start, sc.frame_end = int(round(1 / tl.dt)), 1, tl.n
    S = np.diag([MM, MM, MM, 1.0])
    by = {}                                                  # part name -> its Empty (from the stf_name property)
    for o in bpy.data.objects:
        if o.type == "EMPTY" and o.get("stf_name"):
            by[o["stf_name"]] = o
    mesh_of = {n: next((c for c in e.children if c.type == "MESH"), None) for n, e in by.items()}
    idx = {s["name"]: s for s in json.load(open(os.path.join(OUT, "cache", "index.json")))["solids"]}
    frames = [tl.frame(k) for k in range(tl.n)]
    cyl_me, cmat = unit_cylinder_mesh(), colour_material()
    coll = bpy.data.collections.new("STF2_motion")
    sc.collection.children.link(coll)
    made = {}

    cyl_me.materials.append(cmat)                            # one mesh, one material; the colour is per object

    def cylinder_object(name, colour):
        o = bpy.data.objects.new(f"{name}__cyl", cyl_me)
        o["stf_name"] = name
        coll.objects.link(o)
        o.color = hex_rgba(colour)
        made[name] = o
        return o

    def key_visibility(o, vis):
        hidden = np.array([[0.0 if v else 1.0] for v in vis])
        keys(o, "hide_viewport", hidden, "CONSTANT")
        keys(o, "hide_render", hidden, "CONSTANT")

    def key_colour(o, cols, fallback):
        if o.data is not cyl_me:                             # a CAD mesh (oven element): the material per object
            for sl in o.material_slots:
                sl.link = "OBJECT"
                sl.material = cmat
        keys(o, "color", [hex_rgba(c or fallback) for c in cols], "CONSTANT")

    n_rigid = n_cyl = n_fol = 0
    for n in tl.track:
        kind0 = frames[0][n][0]
        if kind0 == "cyl" or n in tl.spawn:
            # a cylinder the player draws: the reshaped track's own cylinder, or a spawned cookie / topping
            colour = tl.spawn[n]["colour"] if n in tl.spawn else next((f[n][3] for f in frames if f[n][3]), "#c68f4c")
            o = cylinder_object(n, colour)
            if kind0 == "cyl":
                worlds = [S @ f[n][1] for f in frames]
            else:
                s = tl.spawn[n]
                base = PB.cylinder_matrix(s["p"], s["s"][0], s["s"][2], s["s"][1])
                worlds = [S @ f[n][1] @ base for f in frames]
            o.matrix_world = mathutils.Matrix(worlds[0].tolist())
            key_matrices(o, worlds)
            key_visibility(o, [f[n][2] for f in frames])
            if kind0 == "cyl":
                key_colour(o, [f[n][3] for f in frames], colour)
            if n in mesh_of and mesh_of[n] is not None:                # the CAD mesh is replaced, as in FreeCAD
                mesh_of[n].hide_viewport = mesh_of[n].hide_render = True
            n_cyl += 1
        elif n in by:
            e = by[n]
            off = np.eye(4)
            off[:3, 3] = idx[n]["offset"]
            key_matrices(e, [S @ f[n][1] @ off for f in frames])
            if mesh_of[n] is not None:
                key_visibility(mesh_of[n], [f[n][2] for f in frames])
            n_rigid += 1
    for n, s in idx.items():                                           # screws / brackets riding on a body
        if not s["moving"] or n in tl.track or n not in by:
            continue
        b = tl.body_of(n)
        if b is None:
            continue
        off = np.eye(4)
        off[:3, 3] = s["offset"]
        key_matrices(by[n], [S @ f[b][1] @ off for f in frames])
        n_fol += 1
    for n, g in tl.glow.items():                                       # oven elements: SSR on / off
        if n in mesh_of and mesh_of[n] is not None:
            key_colour(mesh_of[n], [f[n][3] for f in frames], g["off"])
    sc.frame_set(1)
    print(f"animated: {n_rigid} rigid parts, {n_fol} followers, {n_cyl} cylinders (reshaped + spawned), "
          f"{len(tl.glow)} glowing elements; {tl.n} frames at {sc.render.fps} fps", flush=True)
    return st, tl, by, mesh_of, made


def setup_view():
    sc = bpy.context.scene
    objs = [o for o in sc.objects if o.type == "MESH" and not o.hide_render]
    pts = [o.matrix_world @ mathutils.Vector(c) for o in objs for c in o.bound_box]
    lo = mathutils.Vector([min(p[i] for p in pts) for i in range(3)])
    hi = mathutils.Vector([max(p[i] for p in pts) for i in range(3)])
    c, size = (lo + hi) / 2, max(hi - lo)
    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    sc.collection.objects.link(cam)
    cam.location = c + mathutils.Vector((-0.9, -1.25, 0.85)).normalized() * size * 1.35
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 40
    sc.camera = cam
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy, sun.rotation_euler = 3.5, (0.7, 0.2, -0.6)
    sc.collection.objects.link(sun)
    w = bpy.data.worlds.new("world")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    sc.world = w
    sc.render.engine = "BLENDER_EEVEE"
    sc.view_settings.view_transform = "Standard"
    sc.render.resolution_x, sc.render.resolution_y = 1800, 1100


def boxes(tl, by, mesh_of, made, frames):
    """{frame: {part: [box (mm), visible, kind]}} of what Blender draws - for playback_check P3."""
    sc = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    out = {}
    cache = {}
    for k in frames:
        sc.frame_set(k + 1)
        dg.update()
        rows = {}
        targets = [(n, made[n], "cyl") for n in made] + \
                  [(n, mesh_of[n], "mesh") for n in by if n not in made and mesh_of.get(n) is not None
                   and (n in tl.track or tl.body_of(n) is not None)]
        for n, o, kind in targets:
            if o.name not in cache:
                v = np.empty(len(o.data.vertices) * 3)
                o.data.vertices.foreach_get("co", v)
                cache[o.name] = v.reshape(-1, 3)
            m = np.array(o.evaluated_get(dg).matrix_world)
            p = cache[o.name] @ m[:3, :3].T + m[:3, 3]
            rows[n] = [*(p.min(0) / MM), *(p.max(0) / MM), 0 if o.hide_render else 1, kind]
        out[k] = rows
    return out


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    st, tl, by, mesh_of, made = build()
    setup_view()
    if "--check" in argv:
        ref = json.load(open(os.path.join(OUT, "playback_ref.json")))
        json.dump(boxes(tl, by, mesh_of, made, [int(k) for k in ref["frames"]]),
                  open(os.path.join(OUT, "blender_boxes.json"), "w"))
        print("wrote", os.path.join(OUT, "blender_boxes.json"), flush=True)
    if "--render" in argv:
        i = argv.index("--render")
        bpy.context.scene.frame_set(int(argv[i + 1]) + 1)
        bpy.context.scene.render.filepath = os.path.abspath(argv[i + 2])
        bpy.ops.render.render(write_still=True)
        print("rendered", argv[i + 2], flush=True)
    if "--save" in argv or not bpy.app.background:
        path = os.path.join(OUT, "stf2_anim.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        print("saved", path, flush=True)
