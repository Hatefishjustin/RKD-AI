"""W2 eye-level render from the frozen spatial scene spec.

    blender -b --factory-startup -noaudio --python scripts/render_spatial_scene.py -- \
        --scene <scene.json> --out <png> [--width 1280] [--height 800] [--samples 48]

Geometry and sizes come from the same model that draws the plan. Materials,
furniture heights and the camera are labelled assumptions in the scene JSON and
must not be read as measured facts. Deterministic: no external assets.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name: str, default: str) -> str:
    return argv[argv.index(name) + 1] if name in argv else default


SCENE_PATH = Path(arg("--scene", "tmp/scene.json"))
OUT_PNG = Path(arg("--out", "tmp/render.png"))
WIDTH = int(arg("--width", "1280"))
HEIGHT = int(arg("--height", "800"))
SAMPLES = int(arg("--samples", "48"))
DATA = json.loads(SCENE_PATH.read_text(encoding="utf-8"))
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
t0 = time.time()


def hex_rgb(value: str) -> tuple[float, float, float]:
    value = str(value or "#cccccc").lstrip("#")
    if len(value) != 6:
        return (0.8, 0.8, 0.8)
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def material(name: str, color, *, rough=0.7, metal=0.0, emission=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 4.0
    return mat


def mesh_from_polygon(name: str, polygon_m: list, z0: float, z1: float, mat):
    verts = [(x, y, z0) for x, y in polygon_m] + [(x, y, z1) for x, y in polygon_m]
    n = len(polygon_m)
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]  # bottom, top
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, j + n, i + n))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    bpy.context.collection.objects.link(ob)
    return ob


def box(name: str, x: float, y: float, w: float, d: float, z0: float, z1: float,
        mat, rot_deg: float = 0.0):
    verts = []
    for dx, dy in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)):
        rad = math.radians(rot_deg)
        rx = x + dx * math.cos(rad) - dy * math.sin(rad)
        ry = y + dx * math.sin(rad) + dy * math.cos(rad)
        verts.append((rx, ry, z0))
        verts.append((rx, ry, z1))
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (1, 5, 7, 3),
             (3, 7, 6, 2), (2, 6, 4, 0)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    bpy.context.collection.objects.link(ob)
    return ob


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"

boundary = DATA["boundary"]
W, L, CEIL = boundary["width_m"], boundary["length_m"], boundary["ceiling_m"]

# floor base
mesh_from_polygon("floor-base", [(0, 0), (W, 0), (W, L), (0, L)], -0.03, 0.0,
                  material("floor-base", (0.82, 0.80, 0.76), rough=0.85))
# zone slabs (2 cm finish) with distinct colours
for zone in DATA["zones"]:
    mesh_from_polygon(f"zone-{zone['object_id']}", zone["polygon_m"], 0.0, 0.02,
                      material(f"zone-{zone['object_id']}", hex_rgb(zone["color"]),
                               rough=0.75))
# keep-outs (30 cm kerb so they read as voids/retained zones in the image)
for k in DATA["keepouts"]:
    box(f"keepout-{k['object_id']}", k["x_m"] + k["w_m"] / 2, k["y_m"] + k["l_m"] / 2,
        k["w_m"], k["l_m"], 0.0, 0.30, material("keepout", (0.55, 0.57, 0.60), rough=0.9))
# boundary walls (12 cm) — presentation massing only
wall_mat = material("wall", (0.80, 0.79, 0.77), rough=0.92)
box("wall-south", W / 2, -0.06, W + 0.24, 0.12, 0.0, CEIL, wall_mat)
box("wall-north", W / 2, L + 0.06, W + 0.24, 0.12, 0.0, CEIL, wall_mat)
box("wall-west", -0.06, L / 2, 0.12, L, 0.0, CEIL, wall_mat)
box("wall-east", W + 0.06, L / 2, 0.12, L, 0.0, CEIL, wall_mat)
# entrance slit: carve by a dark inset on the west wall (presentation only)
ent_x = 0.0
ent_width = 1.8
ent_y = float(DATA["camera"]["position"][1]) - ent_width / 2
box("entrance", -0.07, ent_y + ent_width / 2, 0.10, ent_width, 0.0, 2.4,
    material("entrance", (0.10, 0.11, 0.13), rough=0.4))

# ceiling plane (presentation shell; lighting intent only, no construction)
mesh_from_polygon("ceiling", [(0, 0), (W, 0), (W, L), (0, L)], CEIL, CEIL + 0.02,
                  material("ceiling", (0.90, 0.89, 0.87), rough=0.95))
# furniture (uniform 0.75 m height = labelled assumption)
furn_mat = material("furniture", (0.42, 0.44, 0.47), rough=0.55)
for f in DATA["furniture"]:
    box(f"furn-{f['object_id']}", f["x_m"], f["y_m"], f["w_m"], f["d_m"],
        0.02, f["height_m"], furn_mat, rot_deg=f["rot_deg"])
# platforms
plat_mat = material("platform", (0.55, 0.42, 0.30), rough=0.55)
for p in DATA["platforms"]:
    if len(p["polygon_m"]) >= 3:
        mesh_from_polygon(f"platform-{p['object_id']}", p["polygon_m"], 0.02,
                          max(0.08, p["height_m"]), plat_mat)

# ceiling fixtures as small emissive discs
emis = material("fixture", (1.0, 0.95, 0.85), emission=(1.0, 0.93, 0.80))
for fx in DATA["fixtures"]:
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.09, location=(fx["x_m"], fx["y_m"], CEIL - 0.05))
    ob = bpy.context.active_object
    ob.name = f"fixture-{fx['object_id']}"
    ob.data.materials.append(emis)

# world + lights
world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.86, 0.89, 0.93, 1.0)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

bpy.ops.object.light_add(type="SUN", location=(W * 0.5, L + 6, 9))
sun = bpy.context.active_object
sun.data.energy = 5.0
sun.rotation_euler = (math.radians(52), 0, math.radians(200))
bpy.ops.object.light_add(type="AREA", location=(W * 0.55, L * 0.55, CEIL - 0.1))
area = bpy.context.active_object
area.data.energy = 500.0
area.data.size = max(W, L) * 0.6

# camera
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = DATA["camera"]["lens_mm"]
cam = bpy.data.objects.new("Camera", cam_data)
bpy.context.collection.objects.link(cam)
pos = Vector(DATA["camera"]["position"])
target = Vector(DATA["camera"]["target"])
cam.location = pos
direction = target - pos
cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
scene.camera = cam

# render settings — Cycles CPU, deterministic
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.render.resolution_x = WIDTH
scene.render.resolution_y = HEIGHT
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(OUT_PNG)
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Medium High Contrast"
scene.view_settings.exposure = -0.9

bpy.ops.render.render(write_still=True)
meta = {"engine": "CYCLES-CPU", "samples": SAMPLES, "width": WIDTH, "height": HEIGHT,
        "seconds": round(time.time() - t0, 2), "scene": SCENE_PATH.name,
        "assumption": "机位/材质/家具高度为渲染假设，非实测"}
Path(str(OUT_PNG) + ".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
print(json.dumps(meta, ensure_ascii=False))
