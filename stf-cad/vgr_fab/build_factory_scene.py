#!/usr/bin/env python3
"""Build the polished full-factory Blender scene from STF_Factory.gltf.

Source of truth: stf-cad/STF_Factory.gltf (the generated geometry the web twin
serves). This script imports it, upgrades the flat vertex-colour materials to
industrial PBR materials, lights it as a product-visualisation scene, renders
three views and exports a web-ready GLB with the same geometry.

Run:  Blender -b --python build_factory_scene.py
"""

import os

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = "/Users/sohampatel/workspace/stf-hw/stf-cad/STF_Factory.gltf"
OUT_BLEND = os.path.join(ROOT, "factory_scene.blend")
OUT_GLB = os.path.join(ROOT, "factory_scene.glb")
RENDER_DIR = os.path.join(ROOT, "renders")

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.unit_settings.system = "METRIC"
sc.unit_settings.length_unit = "MILLIMETERS"
sc.unit_settings.scale_length = 0.001

# ---------------------------------------------------------------- import
bpy.ops.import_scene.gltf(filepath=SRC)
imported = list(bpy.data.objects)
meshes = [o for o in imported if o.type == "MESH"]
print("STF_IMPORT meshes=%d materials=%d" % (len(meshes), len(bpy.data.materials)))

# The file is standard glTF Y-up with coordinates in micrometre numbers, and
# this importer leaves the axes untouched (zero rotations, raw Y-up data) - in
# Blender the factory lies on its back. Convert the whole import to Z-up mm in
# one shot per mesh:  world' = S(0.001) x Rx(+90 deg) x world,  then bake.
import math
from mathutils import Matrix

S_MM = Matrix.Scale(0.001, 4)
RX90 = Matrix.Rotation(math.radians(-90), 4, "X")

for o in [o for o in imported if o.type == "MESH"]:
    mw = S_MM @ RX90 @ o.matrix_world
    o.parent = None
    o.matrix_world = mw

for o in [o for o in imported if o.type == "EMPTY"]:
    bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

# measure the import (diagnostic: tells us the working scale)
mins = Vector((1e18, 1e18, 1e18))
maxs = Vector((-1e18, -1e18, -1e18))
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        mins = Vector(map(min, mins, w))
        maxs = Vector(map(max, maxs, w))
size = maxs - mins
print("STF_BBOX min=%s max=%s size=%s" % (tuple(round(v, 1) for v in mins),
                                          tuple(round(v, 1) for v in maxs),
                                          tuple(round(v, 1) for v in size)))

# ------------------------------------------------- industrial PBR materials
def upgrade(mat):
    """Map the exported colour-name materials to industrial PBR."""
    name = (mat.name or "").lower()
    base = mat.diffuse_color
    r, g, b = base[0], base[1], base[2]
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if not bsdf:
        return
    def setp(inp, val):
        if inp in bsdf.inputs:
            bsdf.inputs[inp].default_value = val
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if "cf3a" in name or "e049" in name:            # ft red
        setp("Metallic", 0.15); setp("Roughness", 0.35)
    elif lum < 0.10:                                 # near-black -> coated steel/rubber
        setp("Metallic", 0.6); setp("Roughness", 0.45)
    elif "1b8f52" in name:                           # PCB green
        setp("Metallic", 0.1); setp("Roughness", 0.55)
    elif lum > 0.85:                                 # whites/creams -> polymer
        setp("Metallic", 0.0); setp("Roughness", 0.6)
    else:                                            # greys -> aluminium/steel
        setp("Metallic", 0.9); setp("Roughness", 0.35)

for m in bpy.data.materials:
    upgrade(m)

# ------------------------------------------------------------ organisation
fab = bpy.data.collections.new("STF_FACTORY")
sc.collection.children.link(fab)
for o in meshes:
    for c in list(o.users_collection):
        c.objects.unlink(o)
    fab.objects.link(o)

# ---------------------------------------------------------- floor + backdrop
floor_mat = bpy.data.materials.new("floor polymer")
floor_mat.use_nodes = True
fbsdf = floor_mat.node_tree.nodes["Principled BSDF"]
fbsdf.inputs["Base Color"].default_value = (0.16, 0.17, 0.19, 1)
fbsdf.inputs["Roughness"].default_value = 0.7
bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, mins.z - 2))
floor = bpy.context.active_object
floor.name = "STF_floor"
floor.scale = (size.x * 1.6, size.y * 1.6, 1)
floor.data.materials.append(floor_mat)

# ------------------------------------------------------------------ cameras
def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

def camera(name, location, target, lens=50):
    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.active_object
    cam.name = name
    cam.data.lens = lens
    cam.data.clip_start = max(size) * 0.01
    cam.data.clip_end = max(size) * 10
    look_at(cam, target)
    return cam

c = (mins + maxs) / 2
diag = size.length
cam_iso = camera("CAM_factory_iso", c + Vector((0.9, -1.15, 0.75)) * diag, c, lens=55)
cam_top = camera("CAM_factory_top", c + Vector((0.02, -0.03, 1.35)) * diag, c, lens=60)
# VGR detail: the VGR module node, else fall back to factory centre
vgr = bpy.data.objects.get("VGR")
vc = vgr.matrix_world.translation if vgr else c
cam_vgr = camera("CAM_vgr_detail", vc + Vector((0.55, -0.7, 0.45)) * diag * 0.55,
                 vc + Vector((0, 0, 0.05)) * diag, lens=70)

# ------------------------------------------------------------------- lights
def area(name, loc, energy, size_l, color, target):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size_l
    data.color = color
    o = bpy.data.objects.new(name, data)
    o.location = loc
    look_at(o, target)
    sc.collection.objects.link(o)
    return o

area("KEY", c + Vector((-0.55, -0.75, 1.25)) * diag, 1800 * diag / 1000.0,
     diag * 0.9, (1.0, 0.96, 0.90), c)
area("FILL", c + Vector((0.95, -0.25, 0.6)) * diag, 1100 * diag / 1000.0,
     diag * 0.8, (0.82, 0.90, 1.0), c)
area("RIM", c + Vector((0.1, 0.95, 0.9)) * diag, 1500 * diag / 1000.0,
     diag * 0.7, (1.0, 1.0, 1.0), c)
sun = bpy.data.lights.new("SUN_key", "SUN")
sun.energy = 1.2
sun.angle = 0.02
sun_o = bpy.data.objects.new("SUN_key", sun)
sun_o.rotation_euler = (0.65, 0.15, -0.6)
sc.collection.objects.link(sun_o)

# ------------------------------------------------------------------- render
sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x = 1920
sc.render.resolution_y = 1440
sc.render.image_settings.file_format = "PNG"
try:
    sc.eevee.taa_render_samples = 64
except AttributeError:
    pass
try:
    sc.eevee.use_raytracing = True   # EEVEE Next: real reflections for the metals
except AttributeError:
    pass
try:
    sc.view_settings.look = "AgX - Medium High Contrast"
except (TypeError, ValueError):
    pass

_world = bpy.data.worlds.new("STF_World") if not sc.world else sc.world
sc.world = _world
_world.use_nodes = True
_bg = _world.node_tree.nodes["Background"]
_bg.inputs[0].default_value = (0.75, 0.80, 0.88, 1.0)
_bg.inputs[1].default_value = 0.35

os.makedirs(RENDER_DIR, exist_ok=True)

# hide render helpers from the GLB
floor.hide_render = True
for nm in ("CAM_factory_iso", "CAM_factory_top", "CAM_vgr_detail",
           "KEY", "FILL", "RIM", "SUN_key", "STF_floor"):
    o = bpy.data.objects.get(nm)
    if o:
        o.hide_render = True

bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)

# GLB: factory meshes under a 0.001-scale root (the exporter writes raw BU as
# glTF metres, ignoring unit scale, so bake um->m as a node scale)
bpy.ops.object.select_all(action="DESELECT")
root = bpy.data.objects.new("STF_root", None)
sc.collection.objects.link(root)
root.scale = (0.001, 0.001, 0.001)
for o in meshes:
    o.parent = root
    o.select_set(True)
root.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT_GLB, export_format="GLB", export_yup=True,
                          export_apply=False, use_selection=True, export_extras=True)
for o in meshes:
    o.parent = None
bpy.data.objects.remove(root, do_unlink=True)

# restore helpers for rendering
floor.hide_render = False
for nm in ("KEY", "FILL", "RIM", "SUN_key", "STF_floor"):
    o = bpy.data.objects.get(nm)
    if o:
        o.hide_render = False

for cam, fname in ((cam_iso, "factory_iso"), (cam_top, "factory_top"),
                   (cam_vgr, "factory_vgr")):
    sc.camera = cam
    sc.render.filepath = os.path.join(RENDER_DIR, fname + ".png")
    bpy.ops.render.render(write_still=True)

print("STF_FACTORY_DONE blend=%s glb=%s" % (OUT_BLEND, OUT_GLB))
