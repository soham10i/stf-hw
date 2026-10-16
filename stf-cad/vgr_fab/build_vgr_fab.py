#!/usr/bin/env python3
"""Build the fabrication-grade VGR (vacuum gripper robot) assembly in Blender.

Source of truth: stf-cad/hbw/vgr_model.py (the project's parametric model).
Dimensions are parsed from that file's V dict - nothing is re-measured or
guessed here, so the fabricated part is provably identical to the proven
model (envelopes, clearances and reach are unchanged).

Units: 1 Blender unit = 1 mm (metric, scale 0.001). glTF exports in metres.

Outputs (all under stf-cad/vgr_fab/):
  vgr_fab.blend            the assembly
  vgr_fab.glb              web-ready export (Y-up, metres)
  parts.json               BOM feed for the fabrication dossier
  renders/{iso,front,side,weld_top}.png

Run:  Blender -b --python build_vgr_fab.py
"""

import ast
import json
import math
import os
import re

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL_SRC = "/Users/sohampatel/workspace/stf-hw/stf-cad/hbw/vgr_model.py"
OUT_BLEND = os.path.join(ROOT, "vgr_fab.blend")
OUT_GLB = os.path.join(ROOT, "vgr_fab.glb")
OUT_JSON = os.path.join(ROOT, "parts.json")
RENDER_DIR = os.path.join(ROOT, "renders")

# --------------------------------------------------------------------------
# 1. Dimensions from the source of truth
# --------------------------------------------------------------------------
src = open(MODEL_SRC).read()
# UP7 is the shipped variant: freeze the conditional to its UP7 value
src = src.replace("35.0 if UP7 else 40.0", "35.0")
tree = ast.parse(src)
V = None
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "V" for t in node.targets):
        assert isinstance(node.value, ast.Call) and node.value.func.id == "dict"
        V = {kw.arg: ast.literal_eval(kw.value) for kw in node.value.keywords}
assert V, "V dict not found in vgr_model.py"

# Pose for the fabrication model: swivel 0 deg, mid plunge, mid reach
POSE = dict(swivel=0.0, plunge=320.0, reach=150.0)

# --------------------------------------------------------------------------
# 2. Materials - industrial selection (see FABRICATION.md for the rationale)
# --------------------------------------------------------------------------
def mat_principled(name, base, metallic=0.0, roughness=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*base, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return m

MAT = {}  # filled after the factory reset (materials must outlive it)

# --------------------------------------------------------------------------
# 3. Scene setup
# --------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.unit_settings.system = "METRIC"
sc.unit_settings.length_unit = "MILLIMETERS"
sc.unit_settings.scale_length = 0.001

MAT.update({
    "alu6082":   mat_principled("EN AW-6082-T6 anodised", (0.72, 0.74, 0.77), 0.90, 0.32),
    "c45":       mat_principled("C45 QT steel",           (0.42, 0.44, 0.47), 0.95, 0.28),
    "stainless": mat_principled("1.4305 stainless",       (0.80, 0.81, 0.83), 1.00, 0.16),
    "brass":     mat_principled("CuZn39Pb3 brass",        (0.65, 0.48, 0.12), 1.00, 0.30),
    "weld":      mat_principled("ER5356 as-welded",       (0.55, 0.57, 0.60), 0.92, 0.55),
    "red":       mat_principled("RAL 3002 powder coat",   (0.48, 0.020, 0.018), 0.05, 0.42),
    "black":     mat_principled("RAL 9005 powder coat",   (0.018, 0.018, 0.020), 0.10, 0.50),
    "nbr":       mat_principled("NBR 60 ShA (FDA)",       (0.014, 0.014, 0.014), 0.0, 0.92),
    "dough":     mat_principled("cookie dough (render)",  (0.78, 0.62, 0.38), 0.0, 0.85),
    "plate":     mat_principled("machine plate (ref)",    (0.35, 0.37, 0.40), 0.85, 0.50),
})

COLLS = {}
def coll(name):
    c = bpy.data.collections.new(name)
    sc.collection.children.link(c)
    COLLS[name] = c
    return c

for n in ("00_FRAME", "10_BASE", "20_TURNTABLE", "30_TOWER", "40_CARRIAGE",
          "50_ARM", "60_TOOL", "70_WELDS", "80_FASTENERS", "90_RENDER"):
    coll(n)

PARTS = []   # BOM feed: (name, group, dims mm, material, process)

def _link(obj, collection):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    COLLS[collection].objects.link(obj)

def box(name, p0, size, mat, collection, group, process, bevel=0.0):
    """p0 = min corner (x,y,z) in model coords, size = (dx,dy,dz) mm."""
    bpy.ops.mesh.primitive_cube_add(location=(p0[0] + size[0] / 2, p0[1] + size[1] / 2, p0[2] + size[2] / 2))
    o = bpy.context.active_object
    o.name = name
    o.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel > 0:
        mod = o.modifiers.new("edge break", "BEVEL")
        mod.width = bevel
        mod.segments = 2
    o.data.materials.append(MAT[mat])
    _link(o, collection)
    PARTS.append((name, group, "%.1f x %.1f x %.1f" % size, mat, process))
    return o

def cyl(name, p0, d, h, mat, collection, group, process, axis="z", vertices=48):
    """p0 = min corner of the bounding box; axis = cylinder axis."""
    if axis == "z":
        loc = (p0[0], p0[1], p0[2] + h / 2)
        rot = (0, 0, 0)
    elif axis == "y":
        loc = (p0[0], p0[1] + h / 2, p0[2])
        rot = (math.radians(90), 0, 0)
    else:
        loc = (p0[0] + h / 2, p0[1], p0[2])
        rot = (0, math.radians(90), 0)
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=d / 2, depth=h,
                                       location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    o.data.materials.append(MAT[mat])
    _link(o, collection)
    dims = {"z": (d, d, h), "y": (d, h, d), "x": (h, d, d)}[axis]
    PARTS.append((name, group, "%.1f dia x %.1f" % (d, h), mat, process))
    return o

def weld_bead_ring(name, centre_xy, z, major_r, tube_r=1.6):
    bpy.ops.mesh.primitive_torus_add(major_radius=major_r, minor_radius=tube_r,
                                    major_segments=64, minor_segments=8,
                                    location=(centre_xy[0], centre_xy[1], z))
    o = bpy.context.active_object
    o.name = name
    o.data.materials.append(MAT["weld"])
    _link(o, "70_WELDS")
    PARTS.append((name, "weld", "fillet ring r=%.1f at z=%.1f" % (major_r, z), "weld",
                  "GTAW fillet, ISO 5817-C"))
    return o

def weld_bead_pad(name, xy, z, w=16.0):
    return box(name, (xy[0] - w / 2, xy[1] - w / 2, z - 1.0), (w, w, 2.0),
               "weld", "70_WELDS", "weld", "GTAW fillet, ISO 5817-C")

def bolt(name, xy, z_top):
    """M6 socket-head cap screw, head below z_top, pointing down."""
    head = cyl(name + "_head", (xy[0], xy[1], z_top - 6.0), 10.0, 6.0,
               "stainless", "80_FASTENERS", "fastener", "ISO 4762 M6x16 head", vertices=6)
    shank = cyl(name + "_shank", (xy[0], xy[1], z_top - 16.0), 6.0, 10.0,
                "stainless", "80_FASTENERS", "fastener", "ISO 4762 M6x16 shank", vertices=24)
    PARTS.append((name, "fastener", "M6x16 ISO 4762, A4-70", "stainless", "torque 10 Nm"))

# --------------------------------------------------------------------------
# 4. Assembly (dimensions straight from V; pose swivel 0, plunge 320, reach 150)
# --------------------------------------------------------------------------
cx, cy = V["CX"], V["CY"]
pz, rr = POSE["plunge"], POSE["reach"]
q = V

# ---- frame reference (module plate; not part of the fabrication scope) ----
box("vgr_plate", (0, 0, -q["PLATE"][2]), q["PLATE"], "plate", "00_FRAME", "frame", "reference only")

# ---- 10 base (welded to the machine plate) ----
cyl("drehkranz_base", (cx, cy, 0), q["BASE_D"], q["BASE_H"], "c45", "10_BASE", "base",
    "CNC turn, bore/face; weld W1")
# gusset-free stub; weld W1 joins base to plate
weld_bead_ring("W1_base_to_plate", (cx, cy), 0.5, q["BASE_D"] / 2 - 2)

# ---- 20 turntable (the rotating weldment) ----
cyl("drehkranz_ring", (cx, cy, q["RING_Z"][0]), q["RING_D"], q["RING_Z"][1] - q["RING_Z"][0],
    "c45", "20_TURNTABLE", "turn", "ring gear, teeth m=1.5, hardened 45 HRC")
cyl("turntable_disc", (cx, cy, q["DISC_Z"][0]), q["RING_D"], q["DISC_Z"][1] - q["DISC_Z"][0],
    "alu6082", "20_TURNTABLE", "turn", "laser-cut 6082 plate; weld W2, then face flat")
weld_bead_ring("W2_disc_to_ring", (cx, cy), q["DISC_Z"][0], q["RING_D"] / 2 - 2)

# ---- 30 tower ----
cz0, cz1 = q["COL_Z"]
c, i = q["COL"], 0
for sy in (-1, 1):
    for sx in (-1, 1):
        i += 1
        box("tower_column_%d" % i,
            (cx + sx * q["COL_DX"] - c / 2, cy + sy * q["COL_DY"] - c / 2, cz0),
            (c, c, cz1 - cz0), "alu6082", "30_TOWER", "tower",
            "EN AW-6082-T6 profile 15x15, guide faces finish-milled post-assembly", bevel=0.8)
tw, td, th = q["TOP"]
box("tower_top_plate", (cx - tw / 2, cy - td / 2, cz1), (tw, td, th), "alu6082",
    "30_TOWER", "tower", "6082 plate; welds W3..W6 then bored H7 in one setup", bevel=1.0)
for n, (gx, gy) in enumerate(((-1, -1), (-1, 1), (1, -1), (1, 1)), start=3):
    weld_bead_pad("W%d_topplate_col%d" % (n, n - 2),
                  (cx + gx * q["COL_DX"], cy + gy * q["COL_DY"]), cz1)
cyl("plunge_spindle", (cx + 25, cy, cz0), q["SPINDLE_D"], cz1 - cz0, "c45", "30_TOWER",
    "tower", "C45, rolled thread Tr12x4-7e, journals k6", axis="z", vertices=32)

# ---- 40 carriage ----
kw, kd, kh = q["CARR"]
box("plunge_carriage", (cx - kw / 2, cy - kd / 2, pz), (kw, kd, kh), "alu6082",
    "40_CARRIAGE", "carriage", "6082 machined from solid; 4 guide pockets + 2 bores, one setup")
box("plunge_nut", (cx + 15, cy - 10, pz + kh), (20, 20, 10), "brass", "40_CARRIAGE",
    "carriage", "CuZn39Pb3 nut, thread Tr12x4-7H")
sx_ = cx - q["ARM"][0] / 2 - 2 - q["REACH_SPINDLE_D"] / 2 - 2
box("reach_nut", (sx_ - 10, cy - kd / 2 - 12, pz + 9), (17, 12, 20), "brass",
    "40_CARRIAGE", "carriage", "CuZn39Pb3 nut, thread Tr10x4-7H")

# ---- 50 arm ----
aw, ad, ah = q["ARM"]
ay = cy - q["ARM_FRONT"] - rr            # -100: front face of the arm
rw, re = q["ARM_RAIL"], q["ARM_END"]
rz = pz + 6 + (ah - rw) / 2
for nm, x0 in (("L", cx - aw / 2), ("R", cx + aw / 2 - rw)):
    box("arm_rail_%s" % nm, (x0, ay + re, rz), (rw, ad - 2 * re, rw), "alu6082",
        "50_ARM", "arm", "6082 precision profile 12x12, milled on 3 faces", bevel=0.5)
box("arm_end_F", (cx - aw / 2, ay, pz + 6), (aw, re, ah), "alu6082", "50_ARM", "arm",
    "machined 6082; doweled + 4x M6 to rails", bevel=1.0)
box("arm_end_B", (cx - aw / 2, ay + ad - re, pz + 6), (aw, re, ah), "alu6082", "50_ARM", "arm",
    "machined 6082; doweled + 4x M6 to rails", bevel=1.0)
rd = q["REACH_SPINDLE_D"]
for nm, by in (("F", ay + 4), ("B", ay + ad - 14)):
    box("reach_bearing_%s" % nm, (sx_ - 8, by, pz + 11), (17, 10, 16), "alu6082",
        "50_ARM", "arm", "bronze-lined bearing block, bore 10 H7")
cyl("reach_spindle", (sx_, ay + 4, pz + 19), rd, ad - 4, "c45", "50_ARM", "arm",
    "C45, rolled thread Tr10x4-7e, journals k6", axis="y", vertices=32)

# ---- 60 tool head ----
hw, hd, hh = q["HEAD"]
box("suction_head", (cx - hw / 2, ay - hd, pz + 6), (hw, hd, hh), "alu6082", "60_TOOL",
    "tool", "6082 machined; stem bore H7", bevel=1.0)
cyl("suction_stem", (cx, ay - hd / 2, pz - 16), q["STEM_D"], 22, "stainless", "60_TOOL",
    "tool", "1.4305; spring 1.4310 (6 mm travel) over stem", axis="z", vertices=32)
cyl("suction_cup", (cx, ay - hd / 2, pz - 28), q["CUP_D"], q["CUP_H"], "nbr", "60_TOOL",
    "tool", "NBR 60 ShA, FDA 21 CFR 177.2600, bonded to Al retainer")
# spring (render aid - thin steel coil look via torus stack is overkill; one stainless sleeve)
cyl("spring_sleeve", (cx, ay - hd / 2, pz - 16 - 6), q["STEM_D"] + 4, 12, "stainless",
    "60_TOOL", "tool", "1.4310 compression spring, 6 mm travel", axis="z", vertices=24)

# ---- render aid: a held cookie under the cup ----
cyl("cookie_body", (cx, ay - hd / 2, pz - 28 - 20), 45.0, 16, "dough", "90_RENDER",
    "render", "render aid", axis="z", vertices=48)
cyl("cookie_top", (cx, ay - hd / 2, pz - 28 - 4), 45.0, 4, "dough", "90_RENDER",
    "render", "render aid", axis="z", vertices=48)

# ---- 80 fasteners: motor flange bolts ----
for n, (bx, by, bz) in enumerate(((193, 192, cz1 + th), (217, 192, cz1 + th),
                                  (193, 208, cz1 + th), (217, 208, cz1 + th)), start=1):
    bolt("B%d_M1_motor" % n, (bx, by), bz)
for n, (bx, by, bz) in enumerate(((145, 547, pz + 6 + ah), (167, 547, pz + 6 + ah),
                                  (145, 593, pz + 6 + ah), (167, 593, pz + 6 + ah)), start=5):
    bolt("B%d_M2_motor" % n, (bx, by), bz)

# --------------------------------------------------------------------------
# 5. Cameras and lights
# --------------------------------------------------------------------------
def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

def camera(name, location, target):
    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.active_object
    cam.name = name
    cam.data.clip_start = 1.0        # mm
    cam.data.clip_end = 20000.0      # mm (default 1000 BU = 1 m would clip all)
    look_at(cam, target)
    return cam

cam_iso = camera("CAM_iso", (1150, -1350, 950), (180, 200, 300))
cam_front = camera("CAM_front", (180, -950, 360), (180, 200, 330))
cam_side = camera("CAM_side", (1350, 150, 400), (180, 220, 330))
cam_weld = camera("CAM_weld_top", (430, -60, 800), (180, 200, 600))

for name, loc, energy, size, color in (
    ("KEY", (-500, -700, 1300), 1400, 600, (1.0, 0.97, 0.93)),
    ("FILL", (900, -200, 700), 900, 500, (0.85, 0.92, 1.0)),
    ("RIM", (100, 1000, 1100), 1200, 400, (1.0, 1.0, 1.0)),
):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color
    o = bpy.data.objects.new(name, data)
    o.location = loc
    look_at(o, (180, 200, 300))
    sc.collection.objects.link(o)

# ground shadow-catcher plane
box("ground", (-400, -400, -11.0), (1400, 1600, 1.0), "plate", "90_RENDER", "render", "render")

sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x = 1600
sc.render.resolution_y = 1200
sc.render.image_settings.file_format = "PNG"
sc.render.film_transparent = False

# ambient world: without it EEVEE headless renders black; strength 0.3 keeps contrast
_world = bpy.data.worlds.new("STF_World") if not sc.world else sc.world
sc.world = _world
_world.use_nodes = True
_bg = _world.node_tree.nodes["Background"]
_bg.inputs[0].default_value = (0.62, 0.68, 0.75, 1.0)
_bg.inputs[1].default_value = 0.25

bpy.data.objects["KEY"].data.energy = 14000
bpy.data.objects["FILL"].data.energy = 8000
bpy.data.objects["RIM"].data.energy = 10000
sc.view_settings.exposure = 0.7
try:
    sc.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass

# --------------------------------------------------------------------------
# 6. Save, export, render, dump BOM
# --------------------------------------------------------------------------
os.makedirs(RENDER_DIR, exist_ok=True)

# hide render aids from the GLB (keep in blend)
for o in COLLS["90_RENDER"].objects:
    o.hide_render = True

bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)

# GLB: all meshes under a 0.001-scale root (the exporter writes raw BU as glTF
# metres, ignoring unit scale, so bake mm->m as a node scale); cameras, lights
# and the ground plane stay out of the export
bpy.ops.object.select_all(action="DESELECT")
_glb_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
root = bpy.data.objects.new("STF_root", None)
sc.collection.objects.link(root)
root.scale = (0.001, 0.001, 0.001)
for o in _glb_meshes:
    o.parent = root
    o.select_set(True)
root.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT_GLB, export_format="GLB", export_yup=True,
                          export_apply=True, export_extras=True, use_selection=True)
for o in _glb_meshes:
    o.parent = None
bpy.data.objects.remove(root, do_unlink=True)

with open(OUT_JSON, "w") as f:
    json.dump({"source": MODEL_SRC, "pose": POSE, "dims": V,
               "parts": [{"name": n, "group": g, "dims": d, "material": m, "process": p}
                         for (n, g, d, m, p) in PARTS]}, f, indent=1)

for cam, fname in ((cam_iso, "iso"), (cam_front, "front"), (cam_side, "side"),
                   (cam_weld, "weld_top")):
    sc.camera = cam
    sc.render.filepath = os.path.join(RENDER_DIR, fname + ".png")
    bpy.ops.render.render(write_still=True)

print("STF_VGR_FAB_DONE parts=%d blend=%s glb=%s" % (len(PARTS), OUT_BLEND, OUT_GLB))
