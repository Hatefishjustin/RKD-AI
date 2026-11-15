"""W2-R4 eye-level render from the SAME frozen scene spec as the readable plan.

    blender -b --factory-startup -noaudio --python scripts/render_spatial_scene_r4.py -- \
        --scene <scene.json> --out <png> [--width 1280] [--height 800] [--samples 48]

Reads scene.json v2: enclosure (walls/partitions/openings, mm, same object ids as
the plan), presentation_furniture (CC0 glTF catalogue ids + real dimensions),
CC0 PBR material slots, presentation_cameras and lighting. Nothing is invented
from a functional-zone edge; everything not modelled stays a labelled fixture
assumption. Deterministic, local assets only, no external calls.
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


ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = Path(arg("--scene", "tmp/scene.json"))
OUT_PNG = Path(arg("--out", "tmp/render.png"))
WIDTH = int(arg("--width", "1280"))
HEIGHT = int(arg("--height", "800"))
SAMPLES = int(arg("--samples", "48"))
DATA = json.loads(SCENE_PATH.read_text(encoding="utf-8"))
PRES = DATA["presentation"]
ENC = DATA["enclosure"]
EXPR = PRES.get("expression") or {}
WINDOW_EXPR = EXPR.get("window_expression") or {}
MATERIAL_FINISH = EXPR.get("material_finish") or {}
ASSETS = ROOT / "tools" / "assets"
MANIFEST = json.loads((ROOT / "assets" / "CC0-素材清单.json").read_text(encoding="utf-8"))
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
t0 = time.time()

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"

BOUND = DATA["boundary"]
W, L, CEIL = BOUND["width_m"], BOUND["length_m"], BOUND["ceiling_m"]
used_slots: set[str] = set()
used_models: set[str] = set()
placeholders: list[str] = []
window_lights = 0
cove_segments = 0


def mm(value: float) -> float:
    return float(value) / 1000.0


def hex_rgb(value: str) -> tuple[float, float, float]:
    value = str(value or "#cccccc").lstrip("#")
    if len(value) != 6:
        return (0.8, 0.8, 0.8)
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def simple_mat(name, color, *, rough=0.7, metal=0.0, emission=None, strength=1.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = strength
    return mat


_MAT_CACHE: dict[str, object] = {}


def pbr_mat(slot: str, tint=(1.0, 1.0, 1.0), tile=0.5, rough=0.6,
            normal_strength=0.3, fallback=(0.6, 0.6, 0.6)):
    """Principled material fed by a real CC0 texture set (reuses the method in
    scripts/render_blender.py: Texture Coordinate(Object) -> Mapping -> images)."""
    key = (slot, tuple(tint), tile, rough, normal_strength)
    if key in _MAT_CACHE:
        return _MAT_CACHE[key]
    meta = (MANIFEST.get("textures") or {}).get(slot)
    folder = ASSETS / "pbr" / slot
    if not meta or not folder.is_dir():
        return simple_mat(f"fallback-{slot}", fallback, rough=rough)
    files = meta["files"]
    mat = bpy.data.materials.new(f"cc0-{slot}")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (tile, tile, tile)
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    def image_node(filename, colorspace):
        node = nt.nodes.new("ShaderNodeTexImage")
        path = folder / filename
        node.image = bpy.data.images.load(str(path), check_existing=True)
        node.image.colorspace_settings.name = colorspace
        nt.links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    if "Diffuse" in files and (folder / files["Diffuse"]["file"]).is_file():
        diffuse = image_node(files["Diffuse"]["file"], "sRGB")
        if any(abs(v - 1.0) > 1e-6 for v in tint):
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            mix.inputs[7].default_value = (*tint, 1.0)
            nt.links.new(diffuse.outputs["Color"], mix.inputs[6])
            nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
        else:
            nt.links.new(diffuse.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = (*fallback, 1.0)
    if "nor_gl" in files and (folder / files["nor_gl"]["file"]).is_file():
        normal = image_node(files["nor_gl"]["file"], "Non-Color")
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.inputs["Strength"].default_value = normal_strength
        nt.links.new(normal.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = rough
    used_slots.add(slot)
    _MAT_CACHE[key] = mat
    return mat


MATERIALS: dict[str, object] = {}
for item in PRES["materials"]:
    MATERIALS[item["slot"]] = pbr_mat(
        item["slot"], tuple(item["tint"]), item["tile"], item["rough"],
        item["normal_strength"], hex_rgb(item["hex"]))
M_WALL = MATERIALS.get("wall_plaster") or simple_mat("wall", (0.88, 0.87, 0.85))
M_FLOOR = MATERIALS.get("floor_microcement") or simple_mat("floor", (0.72, 0.70, 0.67))
def glass_mat(name: str):
    """V2: real transparent glazing — NOT an emissive white panel."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.88, 0.94, 0.98, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.06
    for socket in ("Transmission Weight", "Transmission"):
        if socket in bsdf.inputs:
            bsdf.inputs[socket].default_value = 0.94
            break
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = 1.45
    return mat


def outside_mat(name: str):
    """V2: labelled LOCAL sky/horizon gradient behind the glazing (assumption).

    Low-strength emission, never a bright white板；透过透明玻璃看到的是柔和
    天空与地平线色带，不是被发光板盖住的窗口细节。
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    output = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 0.34
    coord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.33, 0.34, 0.36, 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.50, 0.63, 0.78, 1.0)
    band = ramp.color_ramp.elements.new(0.24)
    band.color = (0.43, 0.49, 0.56, 1.0)
    nt.links.new(coord.outputs["Generated"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], output.inputs["Surface"])
    return mat


M_GLASS = glass_mat("window-glass-transparent-v2")
M_OUTSIDE = outside_mat("labelled-local-sky-horizon-assumption")
M_FRAME = simple_mat("window-frame-bronze", (0.17, 0.19, 0.21), rough=0.38, metal=0.6)
M_JOINT = simple_mat("material-joint-line", (0.41, 0.40, 0.38), rough=0.9)
M_SKIRT = simple_mat("skirting-edge-trim", (0.33, 0.31, 0.29), rough=0.75)
M_STRIP = simple_mat("cove-emissive", (1.0, 0.86, 0.66),
                     emission=(1.0, 0.84, 0.62), strength=2.2)
M_KEEP = simple_mat("keepout", (0.38, 0.40, 0.42), rough=0.9)
M_PLACEHOLDER = simple_mat("placeholder", (0.86, 0.72, 0.42), rough=0.8)
M_BRAND = simple_mat("brand-panel-abstract", (0.42, 0.30, 0.22), rough=0.6)


def box(name: str, x: float, y: float, w: float, d: float, z0: float, z1: float,
        mat, rot_deg: float = 0.0):
    """A correct 8-vertex prism: 4 corners at z0, the same 4 at z1, 6 quad faces.

    The legacy sample interleaved z0/z1 per corner and produced bow-tie top and
    bottom faces (which render as black holes). Fixed here.
    """
    rad = math.radians(rot_deg)
    corners = []
    for dx, dy in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)):
        corners.append((x + dx * math.cos(rad) - dy * math.sin(rad),
                        y + dx * math.sin(rad) + dy * math.cos(rad)))
    verts = [(cx, cy, z0) for cx, cy in corners] + \
            [(cx, cy, z1) for cx, cy in corners]
    faces = [(3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    bpy.context.collection.objects.link(ob)
    return ob


def prism(name: str, polygon_m: list, z0: float, z1: float, mat):
    pts = [(float(p[0]), float(p[1])) for p in polygon_m]
    n = len(pts)
    if n < 3:
        return None
    signed = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
                 for i in range(n))
    if signed < 0:
        pts.reverse()                     # keep the top face normal pointing +Z
    verts = [(x, y, z0) for x, y in pts] + [(x, y, z1) for x, y in pts]
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
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


def rounded_polygon(points_m, radius_m, segments: int = 8):
    """Same quadratic-Bezier corner rounding as ai_spatial_outputs.

    rounded_polygon_2d (metres here, mm there). Keeps the platform top flat
    while expressing the model's corner_radius_mm in both outputs.
    """
    pts = [(float(p[0]), float(p[1])) for p in points_m]
    n = len(pts)
    if n < 3 or radius_m <= 0:
        return [list(p) for p in pts]
    out = []
    for i in range(n):
        px, py = pts[(i - 1) % n]
        cx, cy = pts[i]
        nx, ny = pts[(i + 1) % n]
        v1x, v1y, v2x, v2y = px - cx, py - cy, nx - cx, ny - cy
        l1, l2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
        if l1 < 1e-6 or l2 < 1e-6:
            out.append([cx, cy])
            continue
        r = min(radius_m, l1 * 0.45, l2 * 0.45)
        ax, ay = cx + v1x / l1 * r, cy + v1y / l1 * r
        bx, by = cx + v2x / l2 * r, cy + v2y / l2 * r
        for j in range(segments + 1):
            t = j / segments
            out.append([(1 - t) ** 2 * ax + 2 * (1 - t) * t * cx + t ** 2 * bx,
                        (1 - t) ** 2 * ay + 2 * (1 - t) * t * cy + t ** 2 * by])
    return out


def area_light(name, location, target, energy, size, color=(1.0, 0.95, 0.86)):
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.size = size
    data.color = color
    ob = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(ob)
    ob.location = location
    ob.rotation_euler = (Vector(target) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
    # 面光源本体不对相机可见，否则窗洞里会出现一整块纯白发光面（V2 目检发现）。
    try:
        ob.visible_camera = False
    except AttributeError:
        pass
    return ob


def kelvin_rgb(kelvin: float) -> tuple[float, float, float]:
    k = max(1800.0, min(8000.0, float(kelvin)))
    t = (k - 2700.0) / (6500.0 - 2700.0)
    return (1.0, 0.86 + 0.12 * max(0.0, min(1.0, t)),
            0.70 + 0.30 * max(0.0, min(1.0, t)))


# ----------------------------------------------------------------- floor / zones
box("floor-base", W / 2, L / 2, W, L, -0.12, 0.0, M_FLOOR)
for zone in DATA["zones"]:
    mat = MATERIALS.get(zone.get("material_slot")) or M_FLOOR
    prism(f"zone-{zone['object_id']}", zone["polygon_m"], 0.0, 0.02, mat)
for keep in DATA["keepouts"]:
    box(f"keepout-{keep['object_id']}", keep["x_m"] + keep["w_m"] / 2,
        keep["y_m"] + keep["l_m"] / 2, keep["w_m"], keep["l_m"],
        0.0, 0.30, M_KEEP)
rounded_platforms = []
for platform in DATA["platforms"]:
    # 模型明确标注 rounded + corner_radius_mm：平面与三维用同一圆角轮廓算法，
    # 顶面保持平整，不再退化成直角方块或全边倒角造成的"软垫"体块。
    outline = (rounded_polygon(platform["polygon_m"], platform["corner_radius_m"])
               if platform.get("corner_radius_m") else platform["polygon_m"])
    if platform.get("corner_radius_m"):
        rounded_platforms.append({"object_id": platform["object_id"],
                                  "radius_m": platform["corner_radius_m"]})
    prism(f"platform-{platform['object_id']}", outline, 0.02,
          max(0.08, platform.get("height_m") or 0.1),
          MATERIALS.get("stone") or M_KEEP)

# ------------------------------------------------- walls / openings (same ids)
openings_by_wall: dict[str, list] = {}
for opening in ENC["openings"]:
    openings_by_wall.setdefault(opening["wall_object_id"], []).append(opening)

for wall in ENC["walls"] + ENC["partitions"]:
    (x1, y1), (x2, y2) = [[mm(v) for v in p] for p in wall["segment_mm"]]
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length <= 0:
        continue
    ux, uy = dx / length, dy / length
    angle = math.degrees(math.atan2(uy, ux))
    thickness = mm(wall["thickness_mm"])
    height = mm(wall["height_mm"])
    mat = MATERIALS.get(wall["material_slot"]) or M_WALL
    holes = []
    for op in openings_by_wall.get(wall["object_id"], []):
        cx, cy = mm(op["center_mm"][0]), mm(op["center_mm"][1])
        t = (cx - x1) * ux + (cy - y1) * uy
        half = mm(op["width_mm"]) / 2
        holes.append((max(0.0, t - half), min(length, t + half), op))
    breaks = sorted({0.0, length, *[v for h in holes for v in h[:2]]})
    for a, b in zip(breaks, breaks[1:]):
        if b - a < 1e-4:
            continue
        mid = (a + b) / 2
        cx, cy = x1 + ux * mid, y1 + uy * mid
        matched = next((h for h in holes if h[0] - 1e-6 <= mid <= h[1] + 1e-6), None)
        if matched is None:
            box(f"wall-{wall['object_id']}-{a:.2f}", cx, cy, b - a, thickness,
                0.0, height, mat, angle)
            continue
        op = matched[2]
        sill, head = mm(op["sill_mm"]), mm(op["sill_mm"] + op["height_mm"])
        if sill > 0.01:
            box(f"sill-{op['object_id']}", cx, cy, b - a, thickness, 0.0, sill, mat, angle)
        if head < height - 0.01:
            box(f"head-{op['object_id']}", cx, cy, b - a, thickness, head, height, mat, angle)
        if op["kind"] == "window":
            # ---------------------------------------------------------- V2 窗表现
            frame_w = mm(WINDOW_EXPR.get("frame_width_mm", 60))
            mullions = max(0, int(WINDOW_EXPR.get("mullion_count", 1)))
            opening_w, opening_h = b - a, head - sill
            zc = (sill + head) / 2
            inward = Vector((W / 2 - cx, L / 2 - cy, 0.0))
            if inward.length < 1e-3:
                inward = Vector((-uy, ux, 0.0))
            inward.normalize()
            outward = Vector((-inward.x, -inward.y, 0.0))
            frame_d = thickness + 2 * frame_w
            # 透明玻璃内移到墙外侧；发光板已移除，不再掩盖窗洞细节
            gx = cx + outward.x * (thickness / 2 - 0.03)
            gy = cy + outward.y * (thickness / 2 - 0.03)
            box(f"glass-{op['object_id']}", gx, gy,
                max(0.2, opening_w - 2 * frame_w), 0.012,
                sill + frame_w, head - frame_w, M_GLASS, angle)
            for suffix, z0, z1 in (("top", head - frame_w, head),
                                  ("bottom", sill, sill + frame_w)):
                box(f"frame-{suffix}-{op['object_id']}", cx, cy,
                    opening_w, frame_d, z0, z1, M_FRAME, angle)
            for side, sign in (("left", -1), ("right", 1)):
                off = sign * (opening_w / 2 - frame_w / 2)
                box(f"frame-{side}-{op['object_id']}", cx + ux * off, cy + uy * off,
                    frame_w, frame_d, sill, head, M_FRAME, angle)
            for k in range(1, mullions + 1):
                off = -opening_w / 2 + k * opening_w / (mullions + 1)
                box(f"mullion-{k}-{op['object_id']}", cx + ux * off, cy + uy * off,
                    frame_w * 0.8, thickness * 0.7,
                    sill + frame_w, head - frame_w, M_FRAME, angle)
            # 窗台板让 200mm 墙厚形成的洞口深度可辨
            box(f"reveal-sill-{op['object_id']}",
                cx + inward.x * 0.05, cy + inward.y * 0.05,
                opening_w, thickness * 0.9, sill - 0.03, sill + 0.02, M_WALL, angle)
            # 窗外：明确标注的本地程序化天空/地平线渐变，不是现场照片
            ex = cx + outward.x * (thickness / 2 + 1.8)
            ey = cy + outward.y * (thickness / 2 + 1.8)
            box(f"outside-{op['object_id']}", ex, ey, opening_w * 2.4, 0.02,
                max(0.0, sill - 0.6), min(CEIL, head + 1.4), M_OUTSIDE, angle)
            # 采光方向仍只来自这个已建模窗洞口；强度按版本化表达输入缩放
            light_pos = Vector((cx, cy, zc)) + inward * 0.25
            target = Vector((cx, cy, zc)) + inward * 4.0
            energy_scale = float(WINDOW_EXPR.get("window_light_energy_scale", 0.5))
            energy = 180.0 * energy_scale * max(1.0, opening_w) * max(0.8, opening_h)
            area_light(f"window-light-{op['object_id']}", light_pos, target,
                       energy, max(1.2, opening_w), color=(0.86, 0.92, 1.0))
            window_lights += 1
        else:
            # 半开的门扇（oak/walnut 材质），让门洞在效果图里可辨认
            leaf = MATERIALS.get("oak") or M_WALL
            box(f"door-leaf-{op['object_id']}",
                cx - ux * (b - a) / 2, cy - uy * (b - a) / 2,
                b - a, 0.045, 0.0, min(head, 2.3), leaf, angle + 78)

# --------------------------------------------- V2 材质收边 / 接缝（版本化表达输入）
floor_finish = MATERIAL_FINISH.get("mat-floor-microcement") or {}
joint_spacing = mm(floor_finish.get("joint_spacing_mm", 1200))
joint_width = mm(floor_finish.get("joint_width_mm", 4))
skirt_h = mm(floor_finish.get("edge_trim_mm", 80))
joint_count = 0
panel_joint_count = 0
if joint_spacing > 0.05:
    gx = joint_spacing
    while gx < W - 0.01:
        box(f"floor-joint-x-{joint_count}", gx, L / 2, joint_width, L,
            0.021, 0.023, M_JOINT)
        joint_count += 1
        gx += joint_spacing
    gy = joint_spacing
    while gy < L - 0.01:
        box(f"floor-joint-y-{joint_count}", W / 2, gy, W, joint_width,
            0.021, 0.023, M_JOINT)
        joint_count += 1
        gy += joint_spacing
for wall in ENC["walls"] + ENC["partitions"]:
    (x1, y1), (x2, y2) = [[mm(v) for v in p] for p in wall["segment_mm"]]
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    angle = math.degrees(math.atan2(uy, ux))
    thickness = mm(wall["thickness_mm"])
    height = mm(wall["height_mm"])
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    inward = Vector((W / 2 - cx, L / 2 - cy, 0.0))
    if inward.length < 1e-3:
        inward = Vector((nx, ny, 0.0))
    inward.normalize()
    off = thickness / 2 + 0.008
    if wall.get("kind") == "perimeter":
        box(f"skirting-{wall['object_id']}", cx + inward.x * off, cy + inward.y * off,
            length, 0.014, 0.0, skirt_h, M_SKIRT, angle)
    if wall["material_slot"] in ("oak", "walnut"):
        key = "mat-oak" if wall["material_slot"] == "oak" else "mat-walnut"
        spec = MATERIAL_FINISH.get(key) or {}
        spacing = mm(spec.get("joint_spacing_mm", 600))
        width = mm(spec.get("joint_width_mm", 6))
        t = spacing
        while t < length - 0.05:
            px, py = x1 + ux * t, y1 + uy * t
            box(f"panel-joint-{wall['object_id']}-{int(t * 100)}",
                px + inward.x * off, py + inward.y * off,
                width, 0.005, 0.0, height, M_JOINT, angle)
            panel_joint_count += 1
            t += spacing

# --------------------------------------------------------------- ceiling / light
box("ceiling-slab", W / 2, L / 2, W, L, CEIL, CEIL + 0.12, M_WALL)
for fx in DATA["lighting"]["fixtures"]:
    x, y = fx["position_m"]
    area_light(f"fixture-{fx['object_id']}", (x, y, CEIL - 0.18),
               (x, y, 0.0), 120.0, 0.55, color=kelvin_rgb(fx["kelvin"]))
    box(f"fixture-body-{fx['object_id']}", x, y, 0.13, 0.13,
        CEIL - 0.09, CEIL - 0.02,
        simple_mat(f"fixture-emit-{fx['object_id']}", (1.0, 0.92, 0.78),
                   emission=(1.0, 0.9, 0.75), strength=3.0))
for cove in DATA["lighting"]["coves"]:
    poly = cove["polygon_m"]
    for i, (ax, ay) in enumerate(poly):
        bx, by = poly[(i + 1) % len(poly)]
        length = math.hypot(bx - ax, by - ay)
        if length < 0.05:
            continue
        box(f"cove-{cove['object_id']}-{i}", (ax + bx) / 2, (ay + by) / 2,
            length, 0.08, CEIL - 0.05, CEIL - 0.025, M_STRIP,
            math.degrees(math.atan2(by - ay, bx - ax)))
        cove_segments += 1
# 弱室内补光：明确是假设照明，不冒充窗光或照度合规
area_light("assumption-fill-light", (W * 0.5, L * 0.5, CEIL - 0.45),
           (W * 0.5, L * 0.5, 0.0), 42.0, max(W, L) * 0.45,
           color=(1.0, 0.96, 0.90))

# ------------------------------------------------------------------- CC0 models
TEMPLATES: dict[str, dict] = {}


def load_template(asset_id: str):
    if asset_id in TEMPLATES:
        return TEMPLATES[asset_id]
    path = ASSETS / "models" / asset_id / f"{asset_id}.gltf"
    if not path.is_file():
        TEMPLATES[asset_id] = None
        return None
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not meshes:
        TEMPLATES[asset_id] = None
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for ob in meshes:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    mn = Vector((1e9, 1e9, 1e9))
    mx = Vector((-1e9, -1e9, -1e9))
    for corner in ob.bound_box:
        world = ob.matrix_world @ Vector(corner)
        for i in range(3):
            mn[i] = min(mn[i], world[i])
            mx[i] = max(mx[i], world[i])
    cx, cy = (mn.x + mx.x) / 2, (mn.y + mx.y) / 2
    for vertex in ob.data.vertices:
        vertex.co.x -= cx
        vertex.co.y -= cy
        vertex.co.z -= mn.z
    ob.hide_render = True
    ob.hide_viewport = True
    TEMPLATES[asset_id] = {"object": ob, "dims": (mx.x - mn.x, mx.y - mn.y, mx.z - mn.z)}
    return TEMPLATES[asset_id]


origin_counts: dict[str, int] = {}
procedural_names: list[str] = []
for item in DATA["presentation_furniture"]:
    name = item["object_id"]
    x, y, z_offset = item["position_m"]
    rotation = float(item["rotation_deg"])
    asset_id = item.get("asset_id")
    origin_kind = item.get("origin_kind") or "cc0_expression_asset"
    origin_counts[origin_kind] = origin_counts.get(origin_kind, 0) + 1
    if not asset_id:
        dims = item.get("asset_dimensions_mm") or [600, 600, 750]
        w, d, h = mm(dims[0]), mm(dims[1]), mm(dims[2] or 750)
        z0 = 0.02 + z_offset
        if origin_kind == "procedural_expression":
            # V3：程序化展墙 / 展台 / 品牌板，替代原来的黄色占位盒；
            # 明确标为人工表达假设，不是 CC0 资产、不是源方案对象。
            is_panel = ("BRAND" in name or "display-wing" in str(item.get("catalog_id"))
                        or h > 1.2)
            if is_panel:
                box(f"expr-panel-{name}", x, y, w, max(d, 0.10),
                    z0, z0 + h, M_BRAND, rotation)
                box(f"expr-band-{name}", x, y, w * 0.62, max(d, 0.10) + 0.012,
                    z0 + h * 0.44, z0 + h * 0.58,
                    MATERIALS.get("stone") or M_WALL, rotation)
                box(f"expr-base-{name}", x, y, w * 1.08, max(d, 0.10) * 1.15,
                    z0, z0 + 0.07, MATERIALS.get("walnut") or M_WALL, rotation)
            else:
                box(f"expr-pedestal-{name}", x, y, w, d,
                    z0, z0 + h - 0.05, MATERIALS.get("oak") or M_WALL, rotation)
                box(f"expr-cap-{name}", x, y, w * 1.06, d * 1.06,
                    z0 + h - 0.05, z0 + h, MATERIALS.get("stone") or M_WALL, rotation)
            procedural_names.append(name)
        else:
            placeholders.append(name)
            box(f"placeholder-{name}", x, y, w, d,
                z0, z0 + h, M_PLACEHOLDER, rotation)
        continue
    template = load_template(asset_id)
    if template is None:
        placeholders.append(name)
        box(f"placeholder-{name}", x, y, 0.6, 0.6, 0.02 + z_offset,
            0.75 + z_offset, M_PLACEHOLDER, rotation)
        continue
    target_w = mm((item.get("asset_dimensions_mm") or [600])[0] or 600)
    scale = target_w / max(template["dims"][0], 1e-4)
    ob = template["object"].copy()
    ob.data = template["object"].data
    ob.name = f"asset-{name}-{asset_id}"
    bpy.context.collection.objects.link(ob)
    ob.hide_render = False
    ob.hide_viewport = False
    ob.location = (x, y, 0.02 + z_offset)
    ob.rotation_euler = (0.0, 0.0, math.radians(rotation))
    ob.scale = (scale, scale, scale)
    used_models.add(asset_id)

# -------------------------------------------------------------------- world / sun
world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.72, 0.80, 0.90, 1.0)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.45
sun = DATA["lighting"]["sun"]
bpy.ops.object.light_add(type="SUN", location=(W * 0.5, L + 8, 9))
sun_ob = bpy.context.active_object
sun_ob.data.energy = sun["energy"] * 0.6  # 主采光来自模型窗口，太阳只是弱的假设补光
sun_ob.rotation_euler = (math.radians(90 - sun["elevation_deg"]), 0,
                         math.radians(sun["azimuth_deg"]))

# ------------------------------------------------------------------------ camera
cam_spec = DATA["presentation_cameras"][0]
cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = cam_spec["lens_mm"]
cam = bpy.data.objects.new("Camera", cam_data)
bpy.context.collection.objects.link(cam)
cam.location = Vector(cam_spec["position_m"])
direction = Vector(cam_spec["target_m"]) - cam.location
cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
scene.camera = cam

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
scene.view_settings.exposure = float(WINDOW_EXPR.get("exposure_ev", -0.30))

bpy.ops.render.render(write_still=True)
meta = {
    "engine": "CYCLES-CPU", "samples": SAMPLES, "width": WIDTH, "height": HEIGHT,
    "seconds": round(time.time() - t0, 2), "scene": SCENE_PATH.name,
    "presentation": True, "image_count": 1,
    "assets": {"license": "CC0 1.0 (Poly Haven)",
               "manifest_sha256": DATA["assets"]["manifest_sha256"],
               "textures_used": sorted(used_slots), "models_used": sorted(used_models),
               "placeholders": placeholders},
    "lights": {"window_area_lights": window_lights,
               "fixture_lights": len(DATA["lighting"]["fixtures"]),
               "cove_segments": cove_segments, "sun": True,
               "assumption_fill_light": 1,
               "note": "窗光来自已建模窗洞口；灯具/灯槽来自模型天花意向；"
                       "太阳与弱补光为假设照明，未做照度/配光计算，不宣称合规"},
    "camera": {"object_id": cam_spec["object_id"],
               "eye_height_m": mm(cam_spec["eye_height_mm"]),
               "lens_mm": cam_spec["lens_mm"], "assumption": True},
    "enclosure": {"walls": len(ENC["walls"]), "partitions": len(ENC["partitions"]),
                  "openings": len(ENC["openings"])},
    "rounded_platforms": rounded_platforms,
    "expression": {
        "schema_version": EXPR.get("schema_version"),
        "declared_by": EXPR.get("declared_by"),
        "window_expression": {
            "glass_kind": WINDOW_EXPR.get("glass_kind"),
            "frame_width_mm": WINDOW_EXPR.get("frame_width_mm"),
            "reveal_depth_mm": WINDOW_EXPR.get("reveal_depth_mm"),
            "outside_environment": WINDOW_EXPR.get("outside_environment"),
            "outside_note": WINDOW_EXPR.get("outside_note"),
            "exposure_ev": scene.view_settings.exposure,
            "window_light_energy_scale": WINDOW_EXPR.get("window_light_energy_scale"),
            "outside_panels": window_lights,
            "emissive_glass_panels": 0,
        },
        "material_finish_applied": {
            "materials": sorted(MATERIAL_FINISH),
            "floor_joint_lines": joint_count,
            "wood_panel_joint_lines": panel_joint_count,
            "skirting_segments": sum(1 for w in ENC["walls"]),
            "note": "示意纹理比例/分缝/收边，参数来自版本化表达输入，不是材料规格或施工排版",
        },
        "origin_counts": origin_counts,
        "procedural_expression_objects": procedural_names,
        "engineering_quantity_effect": 0,
        "note": "V2 窗光/材质与 V3 陈设均为人工表达假设；新增陈设不进入工程量",
    },
    "assumptions": DATA.get("render_assumptions") or [],
    "disclaimer": DATA.get("presentation_disclaimer"),
}
Path(str(OUT_PNG) + ".meta.json").write_text(
    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"engine": meta["engine"], "seconds": meta["seconds"],
                  "textures": sorted(used_slots), "models": sorted(used_models),
                  "window_lights": window_lights}, ensure_ascii=False))
