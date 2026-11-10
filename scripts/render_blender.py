"""Blender 4.2 scene for design option A — reads 方案A_设计数据.json, renders one view.

    blender -b --factory-startup -noaudio --python scripts/render_blender.py -- \
        --json <path> --out <png> --width 1280 --height 800 --samples 96

Geometry and materials come from the same JSON that draws the 1:100 plan, so the
render cannot drift from the drawing. Units: metres (JSON is in mm).
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

# ------------------------------------------------------------------ args
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name: str, default: str) -> str:
    if name in argv:
        return argv[argv.index(name) + 1]
    return default


JSON_PATH = Path(arg("--json", "var/deliverables/ningbo-xiecheng/2026-11-10/方案A_设计数据.json"))
OUT_PNG = Path(arg("--out", "tmp/render_a.png"))
WIDTH = int(arg("--width", "1280"))
HEIGHT = int(arg("--height", "800"))
SAMPLES = int(arg("--samples", "96"))
VIEW = arg("--view", "entrance")

DATA = json.loads(JSON_PATH.read_text(encoding="utf-8"))
t_start = time.time()

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"

MM = 0.001


def P(v: float) -> float:
    return v * MM


# ------------------------------------------------------------------ mesh helpers
def _link(name: str, verts, faces, mat, smooth_faces=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    if mat is not None:
        ob.data.materials.append(mat)
    if smooth_faces:
        for poly in me.polygons:
            poly.use_smooth = True
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    return ob


def prism(name, poly, z0, z1, mat, smooth_faces=False, bevel=0.0):
    n = len(poly)
    verts = [(x, y, z0) for x, y in poly] + [(x, y, z1) for x, y in poly]
    faces = [tuple(range(n)), tuple(range(2 * n - 1, n - 1, -1))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, j + n, i + n))
    ob = _link(name, verts, faces, mat, smooth_faces)
    if smooth_faces:
        for poly in ob.data.polygons:
            poly.use_smooth = abs(poly.normal.z) < 0.55
    if bevel > 0:
        mod = ob.modifiers.new("bev", "BEVEL")
        mod.width = bevel
        mod.segments = 2
        mod.limit_method = "ANGLE"
        mod.angle_limit = math.radians(40)
    return ob


def add_box(name, cx, cy, z0, z1, sx, sy, mat, rot=0.0, bevel=0.008, smooth_faces=False):
    c, s = math.cos(rot), math.sin(rot)
    pts = []
    for dx, dy in ((-sx / 2, -sy / 2), (sx / 2, -sy / 2), (sx / 2, sy / 2), (-sx / 2, sy / 2)):
        pts.append((cx + dx * c - dy * s, cy + dx * s + dy * c))
    return prism(name, pts, z0, z1, mat, smooth_faces=smooth_faces, bevel=bevel)


def add_cyl(name, cx, cy, z0, z1, r, mat, seg=48, smooth_faces=True):
    poly = [(cx + r * math.cos(2 * math.pi * i / seg), cy + r * math.sin(2 * math.pi * i / seg))
            for i in range(seg)]
    return prism(name, poly, z0, z1, mat, smooth_faces=smooth_faces, bevel=0.0)


def add_ico(name, cx, cy, cz, r, mat, scale=(1, 1, 1), subdiv=2, rot=0.0):
    bm = bmesh.new()
    mat_t = Matrix.Translation((cx, cy, cz)) @ Matrix.Rotation(rot, 4, "Z") @ Matrix.Diagonal(
        (r * scale[0], r * scale[1], r * scale[2], 1.0))
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0, matrix=mat_t)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    if mat is not None:
        ob.data.materials.append(mat)
    for poly in me.polygons:
        poly.use_smooth = True
    return ob


def rrect_poly(x0, y0, x1, y1, r, seg=14):
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = []
    specs = [((x1 - r, y0 + r), -90), ((x1 - r, y1 - r), 0), ((x0 + r, y1 - r), 90), ((x0 + r, y0 + r), 180)]
    for (cx, cy), a0 in specs:
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def at(x, y, rot, lx=0.0, ly=0.0):
    c, s = math.cos(rot), math.sin(rot)
    return x + lx * c - ly * s, y + lx * s + ly * c


# ------------------------------------------------------------------ materials
def new_mat(name, base, rough=0.5, metal=0.0, **extra):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*base, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    for k, v in extra.items():
        if k in b.inputs:
            b.inputs[k].default_value = v
    return m, nt, b


def mat_cement(name, base, rough=0.42, scale=38.0, bump=0.35, var=0.030):
    m, nt, b = new_mat(name, base, rough)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 6.0
    noise.inputs["Roughness"].default_value = 0.6
    bmp = nt.nodes.new("ShaderNodeBump")
    bmp.inputs["Strength"].default_value = bump
    bmp.inputs["Distance"].default_value = 0.004
    big = nt.nodes.new("ShaderNodeTexNoise")
    big.inputs["Scale"].default_value = 0.9
    big.inputs["Detail"].default_value = 3.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (base[0] * (1 - var), base[1] * (1 - var), base[2] * (1 - var), 1)
    ramp.color_ramp.elements[1].color = (min(1, base[0] * (1 + var)), min(1, base[1] * (1 + var)),
                                         min(1, base[2] * (1 + var)), 1)
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(coord.outputs["Object"], big.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], bmp.inputs["Height"])
    nt.links.new(bmp.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(big.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    return m


def mat_wood(name, base, dark, grain=6.0, rough=0.62):
    m, nt, b = new_mat(name, base, rough)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.0, 1.0, 1.0)
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "X"
    wave.inputs["Scale"].default_value = grain * 1.45
    wave.inputs["Distortion"].default_value = 0.22
    wave.inputs["Detail"].default_value = 2.0
    wave.inputs["Detail Scale"].default_value = 1.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.30
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[1].color = (*base, 1)
    # fine pore streaks on top of the band grain
    pore = nt.nodes.new("ShaderNodeTexNoise")
    pore.inputs["Scale"].default_value = 260.0
    pore.inputs["Detail"].default_value = 6.0
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "FLOAT"
    mix.inputs["Factor"].default_value = 0.14
    bmp = nt.nodes.new("ShaderNodeBump")
    bmp.inputs["Strength"].default_value = 0.16
    bmp.inputs["Distance"].default_value = 0.0035
    for key, val in (("Specular IOR Level", 0.28),):
        if key in b.inputs:
            b.inputs[key].default_value = val
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], wave.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], pore.inputs["Vector"])
    nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(wave.outputs["Fac"], mix.inputs[2])
    nt.links.new(pore.outputs["Fac"], mix.inputs[3])
    nt.links.new(mix.outputs[0], bmp.inputs["Height"])
    nt.links.new(bmp.outputs["Normal"], b.inputs["Normal"])
    return m


def mat_stone(name, base=(0.86, 0.83, 0.78), rough=0.18):
    m, nt, b = new_mat(name, base, rough)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.2
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.55
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (base[0] * 0.90, base[1] * 0.90, base[2] * 0.89, 1)
    ramp.color_ramp.elements[1].color = (min(1, base[0] * 1.03), min(1, base[1] * 1.03), min(1, base[2] * 1.02), 1)
    bmp = nt.nodes.new("ShaderNodeBump")
    bmp.inputs["Strength"].default_value = 0.10
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(noise.outputs["Fac"], bmp.inputs["Height"])
    nt.links.new(bmp.outputs["Normal"], b.inputs["Normal"])
    return m


def mat_fabric(name, base, rough=0.92):
    m, nt, b = new_mat(name, base, rough)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 260.0
    noise.inputs["Detail"].default_value = 2.0
    bmp = nt.nodes.new("ShaderNodeBump")
    bmp.inputs["Strength"].default_value = 0.30
    bmp.inputs["Distance"].default_value = 0.002
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], bmp.inputs["Height"])
    nt.links.new(bmp.outputs["Normal"], b.inputs["Normal"])
    for key, val in (("Sheen Weight", 0.35), ("Sheen Roughness", 0.6)):
        if key in b.inputs:
            b.inputs[key].default_value = val
    return m


def mat_emit(name, color, strength):
    m, nt, b = new_mat(name, color, 1.0)
    if "Emission Color" in b.inputs:
        b.inputs["Emission Color"].default_value = (*color, 1.0)
        b.inputs["Emission Strength"].default_value = strength
    return m


def mat_glass():
    m, nt, b = new_mat("glass", (0.85, 0.92, 0.94), 0.04)
    for key, val in (("Transmission Weight", 1.0), ("IOR", 1.46)):
        if key in b.inputs:
            b.inputs[key].default_value = val
    return m


M_CEILING = mat_cement("ceiling_paint", (0.925, 0.915, 0.895), rough=0.85, scale=120.0, bump=0.05, var=0.008)
M_WALL = mat_cement("wall_paint", (0.905, 0.885, 0.855), rough=0.80, scale=90.0, bump=0.06, var=0.010)
M_FLOOR = mat_cement("floor_microcement", (0.375, 0.352, 0.322), rough=0.52, scale=13.0, bump=0.85, var=0.13)
M_OAK = mat_wood("oak", (0.505, 0.375, 0.268), (0.315, 0.215, 0.140))
M_WALNUT = mat_wood("walnut", (0.265, 0.170, 0.110), (0.135, 0.082, 0.050), grain=5.0, rough=0.55)
M_STONE = mat_stone("stone", base=(0.655, 0.622, 0.570), rough=0.30)
M_FABRIC = mat_fabric("fabric", (0.66, 0.575, 0.47))
M_FABRIC2 = mat_fabric("fabric_light", (0.73, 0.68, 0.60))
M_BRONZE, _, _ = new_mat("bronze", (0.71, 0.52, 0.33), rough=0.32, metal=1.0)
M_BLACK, _, _ = new_mat("black_metal", (0.045, 0.045, 0.05), rough=0.42, metal=0.7)
M_GLASS = mat_glass()
M_PLANT, _, _ = new_mat("leaf", (0.11, 0.20, 0.09), rough=0.62)
M_POT, _, _ = new_mat("pot", (0.32, 0.30, 0.28), rough=0.55)
M_WHITE, _, _ = new_mat("gloss_white", (0.90, 0.90, 0.88), rough=0.22)
M_SHADOW, _, _ = new_mat("shadow_gap", (0.10, 0.085, 0.07), rough=0.85)
M_PED = mat_stone("stone_dark", base=(0.50, 0.47, 0.435), rough=0.30)
M_STONEW = mat_stone("stone_warm", base=(0.72, 0.66, 0.58), rough=0.35)
M_STRIP = mat_emit("light_strip", (1.0, 0.78, 0.52), 1.9)
M_SKY = mat_emit("sky_panel", (0.88, 0.93, 1.0), 2.6)
M_SOFFIT = mat_cement("soffit_paint", (0.885, 0.870, 0.840), rough=0.85, scale=120.0, bump=0.05, var=0.008)

# ------------------------------------------------------------------ ground / ceiling
W, H, CEIL = P(DATA["site"]["width"]), P(DATA["site"]["height"]), P(DATA["site"]["ceiling"])
add_box("floor_slab", W / 2, H / 2, -0.12, 0.0, W, H, M_FLOOR, bevel=0.0)
add_box("ceiling_slab", W / 2, H / 2, CEIL, CEIL + 0.12, W, H, M_CEILING, bevel=0.0)

# ------------------------------------------------------------------ perimeter walls
T = 0.2
NZ = (0.9, 2.7)  # window sill / head


def wall_seg(name, x0, y0, x1, y1, z0, z1, mat, bevel=0.004):
    add_box(name, (x0 + x1) / 2, (y0 + y1) / 2, z0, z1, abs(x1 - x0) or T, abs(y1 - y0) or T, mat,
            bevel=bevel)


north_windows = [(P(a), P(b)) for a, b in DATA["fixed"]["windows_north"]]
east_windows = [(P(a), P(b)) for a, b in DATA["fixed"]["windows_east"]]

# north wall (y = H - 100)
yn = H - T / 2
edges = [(0.0, north_windows[0][0])]
for i in range(len(north_windows) - 1):
    edges.append((north_windows[i][1], north_windows[i + 1][0]))
edges.append((north_windows[-1][1], W))
for i, (a, b) in enumerate(edges):
    if b - a > 0.01:
        wall_seg(f"n_wall_{i}", a, yn, b, yn, 0, CEIL, M_WALL)
for i, (a, b) in enumerate(north_windows):
    wall_seg(f"n_sill_{i}", a, yn, b, yn, 0, NZ[0], M_WALL)
    wall_seg(f"n_head_{i}", a, yn, b, yn, NZ[1], CEIL, M_WALL)

# east wall (x = W - 100)
xe = W - T / 2
edges = [(0.0, east_windows[0][0])]
for i in range(len(east_windows) - 1):
    edges.append((east_windows[i][1], east_windows[i + 1][0]))
edges.append((east_windows[-1][1], H))
for i, (a, b) in enumerate(edges):
    if b - a > 0.01:
        wall_seg(f"e_wall_{i}", xe, a, xe, b, 0, CEIL, M_WALL)
for i, (a, b) in enumerate(east_windows):
    wall_seg(f"e_sill_{i}", xe, a, xe, b, 0, NZ[0], M_WALL)
    wall_seg(f"e_head_{i}", xe, a, xe, b, NZ[1], CEIL, M_WALL)

# south + west walls, with the entrance opening on the west
wall_seg("s_wall", 0, T / 2, W, T / 2, 0, CEIL, M_WALL)
ent = DATA["fixed"]["entrance"]
wall_seg("w_wall_a", T / 2, 0, T / 2, P(ent[1]), 0, CEIL, M_WALL)
wall_seg("w_wall_b", T / 2, P(ent[2]), T / 2, H, 0, CEIL, M_WALL)
wall_seg("w_wall_head", T / 2, P(ent[1]), T / 2, P(ent[2]), P(2300), CEIL, M_WALL)

# window glazing + aluminium frame grid, set 80 mm back from the interior face
def window_grid(prefix, horizontal, a, b, pos, inward):
    """horizontal=True: window runs along X (north wall). inward = -1 for +Y walls."""
    span = b - a
    bays = max(1, round(span / 1.35))
    gpos = pos + inward * 0.08
    if horizontal:
        add_box(f"{prefix}_glass", (a + b) / 2, gpos, NZ[0], NZ[1], span, 0.014, M_GLASS, bevel=0.0)
        add_box(f"{prefix}_fr_b", (a + b) / 2, gpos, NZ[0], NZ[0] + 0.06, span, 0.07, M_BLACK, bevel=0.0)
        add_box(f"{prefix}_fr_t", (a + b) / 2, gpos, NZ[1] - 0.06, NZ[1], span, 0.07, M_BLACK, bevel=0.0)
        add_box(f"{prefix}_tr", (a + b) / 2, gpos, 2.24, 2.29, span, 0.06, M_BLACK, bevel=0.0)
        for k in range(bays + 1):
            mx = a + span * k / bays
            add_box(f"{prefix}_m{k}", mx, gpos, NZ[0], NZ[1], 0.055, 0.06, M_BLACK, bevel=0.0)
    else:
        add_box(f"{prefix}_glass", gpos, (a + b) / 2, NZ[0], NZ[1], 0.014, span, M_GLASS, bevel=0.0)
        add_box(f"{prefix}_fr_b", gpos, (a + b) / 2, NZ[0], NZ[0] + 0.06, 0.07, span, M_BLACK, bevel=0.0)
        add_box(f"{prefix}_fr_t", gpos, (a + b) / 2, NZ[1] - 0.06, NZ[1], 0.07, span, M_BLACK, bevel=0.0)
        add_box(f"{prefix}_tr", gpos, (a + b) / 2, 2.24, 2.29, 0.06, span, M_BLACK, bevel=0.0)
        for k in range(bays + 1):
            my = a + span * k / bays
            add_box(f"{prefix}_m{k}", gpos, my, NZ[0], NZ[1], 0.06, 0.055, M_BLACK, bevel=0.0)


for i, (a, b) in enumerate(north_windows):
    window_grid(f"n{i}", True, a, b, yn, -1)
for i, (a, b) in enumerate(east_windows):
    window_grid(f"e{i}", False, a, b, xe, -1)

# ------------------------------------------------------------------ internal walls
for w in DATA["walls"]:
    x0, y0, x1, y1 = P(w["x0"]), P(w["y0"]), P(w["x1"]), P(w["y1"])
    t = P(w["t"])
    h = P(w["h"])
    if w["mat"] == "glass":
        if abs(y1 - y0) < 1e-6:
            add_box(f"gl_{w['id']}", (x0 + x1) / 2, y0, 0, h, abs(x1 - x0), 0.02, M_GLASS, bevel=0.0)
            add_box(f"glf_{w['id']}", (x0 + x1) / 2, y0, h - 0.04, h, abs(x1 - x0), 0.05, M_BLACK, bevel=0.0)
            add_box(f"glb_{w['id']}", (x0 + x1) / 2, y0, 0, 0.05, abs(x1 - x0), 0.05, M_BLACK, bevel=0.0)
        else:
            add_box(f"gl_{w['id']}", x0, (y0 + y1) / 2, 0, h, 0.02, abs(y1 - y0), M_GLASS, bevel=0.0)
            add_box(f"glf_{w['id']}", x0, (y0 + y1) / 2, h - 0.04, h, 0.05, abs(y1 - y0), M_BLACK, bevel=0.0)
            add_box(f"glb_{w['id']}", x0, (y0 + y1) / 2, 0, 0.05, 0.05, abs(y1 - y0), M_BLACK, bevel=0.0)
    else:
        mat = M_WALNUT if w["mat"] == "walnut" else M_WALL
        if abs(y1 - y0) < 1e-6:
            add_box(f"w_{w['id']}", (x0 + x1) / 2, y0, 0, h, abs(x1 - x0), t, mat, bevel=0.005)
        else:
            add_box(f"w_{w['id']}", x0, (y0 + y1) / 2, 0, h, t, abs(y1 - y0), mat, bevel=0.005)

# ------------------------------------------------------------------ curved brand wall
arc = DATA["brand_arc"]
cx, cy, r = P(arc["cx"]), P(arc["cy"]), P(arc["r"])
a0, a1 = math.radians(arc["a0"]), math.radians(arc["a1"])
half = P(arc["t"]) / 2
outer = [(cx + (r + half) * math.cos(a0 + (a1 - a0) * i / 48),
          cy + (r + half) * math.sin(a0 + (a1 - a0) * i / 48)) for i in range(49)]
inner = [(cx + (r - half) * math.cos(a1 - (a1 - a0) * i / 48),
          cy + (r - half) * math.sin(a1 - (a1 - a0) * i / 48)) for i in range(49)]
prism("brand_arc_wall", outer + inner, 0.0, P(arc["h"]), M_WALNUT, smooth_faces=True, bevel=0.0)
# glowing reveal behind the curve
prism("brand_arc_glow", outer + inner, P(arc["h"]) + 0.005, P(arc["h"]) + 0.02, M_STRIP, smooth_faces=True)

# ------------------------------------------------------------------ island (three rounded tiers)
for key in ("base", "mid", "top"):
    t = DATA["island"][key]
    poly = rrect_poly(P(t["x0"]), P(t["y0"]), P(t["x1"]), P(t["y1"]), P(t["r"]))
    mat = M_STONE if t["mat"] == "stone" else M_OAK
    prism(f"island_{key}", poly, 0.0, P(t["h"]), mat, smooth_faces=True, bevel=0.006)
    if key == "top":  # 20 mm bronze reveal so stone and oak read as two materials
        prism("island_top_reveal", poly, P(t["h"]) - 0.034, P(t["h"]) - 0.014, M_BRONZE,
              smooth_faces=True)
    # recessed shadow line under the next tier (very thin, warm dark)
    if key != "top":
        prism(f"island_{key}_gap", poly, P(t["h"]) - 0.006, P(t["h"]) + 0.001, M_SHADOW, smooth_faces=True)

# ------------------------------------------------------------------ cove (rounded ceiling recess + strip)
cove = DATA["cove"]
cpx0, cpy0, cpx1, cpy1 = P(cove["x0"]), P(cove["y0"]), P(cove["x1"]), P(cove["y1"])
cr = P(cove["r"])
panel = rrect_poly(cpx0 + 0.20, cpy0 + 0.20, cpx1 - 0.20, cpy1 - 0.20, cr - 0.20)
prism("cove_panel", panel, CEIL - 0.16, CEIL - 0.02, M_SOFFIT, smooth_faces=True, bevel=0.004)
ring_outer = rrect_poly(cpx0 + 0.02, cpy0 + 0.02, cpx1 - 0.02, cpy1 - 0.02, cr - 0.02)
ring_inner = rrect_poly(cpx0 + 0.17, cpy0 + 0.17, cpx1 - 0.17, cpy1 - 0.17, cr - 0.17)
prism("cove_glow", ring_outer + ring_inner[::-1], CEIL - 0.035, CEIL - 0.012, M_STRIP, smooth_faces=False)

# ------------------------------------------------------------------ pedestals + products
for i, pod in enumerate(DATA["pedestals"], start=1):
    px, py, pr = P(pod["x"]), P(pod["y"]), P(pod["r"])
    z = P(DATA["island"]["top"]["h"])
    add_cyl(f"pod_{i}", px, py, z, z + P(pod["h"]), pr, M_PED)
    add_cyl(f"pod_base_{i}", px, py, z, z + 0.022, pr * 0.86, M_BRONZE)

Z0 = P(DATA["island"]["top"]["h"]) + P(300)


def add_lathe(name, cx, cy, z0, profile, mat, steps=48, close_top=False):
    """Surface of revolution from a (radius, height) profile in metres."""
    bm = bmesh.new()
    ring = []
    for r, z in profile:
        ring.append(bm.verts.new((max(r, 0.0008), 0.0, z)))
    edges = [bm.edges.new((ring[i], ring[i + 1])) for i in range(len(ring) - 1)]
    bmesh.ops.spin(bm, geom=ring + edges, axis=(0, 0, 1), cent=(0, 0, 0),
                   dvec=(0, 0, 0), angle=2 * math.pi, steps=steps, use_merge=True)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0015)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(cx, cy, z0))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    ob.data.materials.append(mat)
    for poly in me.polygons:
        poly.use_smooth = True
    return ob


M_CLAY = mat_cement("clay", (0.52, 0.30, 0.20), rough=0.55, scale=90.0, bump=0.10, var=0.05)
M_CLAY2 = mat_cement("clay_pale", (0.74, 0.70, 0.62), rough=0.62, scale=90.0, bump=0.10, var=0.05)

# P1 tall bottle vase
add_lathe("prod_vase", P(10250), P(7700), Z0,
          [(0.001, 0.0), (0.105, 0.0), (0.125, 0.02), (0.128, 0.10), (0.10, 0.22),
           (0.062, 0.34), (0.058, 0.40), (0.072, 0.44), (0.070, 0.455)], M_CLAY)
# P2 upright stone sample
add_box("prod_stone_base", P(14750), P(7700), Z0, Z0 + 0.03, 0.46, 0.26, M_BRONZE, bevel=0.004)
add_box("prod_stone_slab", P(14750), P(7700), Z0 + 0.03, Z0 + 0.58, 0.44, 0.07, M_STONE, bevel=0.006)
# P3 bronze bowl
add_lathe("prod_bowl", P(10250), P(9500), Z0,
          [(0.001, 0.0), (0.12, 0.0), (0.175, 0.035), (0.200, 0.10), (0.204, 0.12)], M_BRONZE)
# P4 stacked fabric samples
for k in range(4):
    add_box(f"prod_swatch_{k}", P(14750) + 0.006 * k, P(9500) - 0.004 * k, Z0 + 0.026 * k,
            Z0 + 0.026 * (k + 1), 0.30 - 0.012 * k, 0.21 - 0.008 * k,
            M_FABRIC if k % 2 == 0 else M_CLAY2, rot=math.radians(4 * k), bevel=0.002)

# ------------------------------------------------------------------ furniture# ------------------------------------------------------------------ furniture
def f_sofa(it, name, mat):
    x, y = P(it["x"]), P(it["y"])
    w, d, h = P(it["w"]), P(it["d"]), P(it["h"])
    rot = math.radians(it.get("rot", 0))
    add_box(f"{name}_base", x, y, 0.09, h - 0.16, w, d, mat, rot=rot, bevel=0.02)
    bx, by = at(x, y, rot, 0, d / 2 - 0.10)
    add_box(f"{name}_back", bx, by, h - 0.30, h, w, 0.20, mat, rot=rot, bevel=0.03)
    for side in (-1, 1):
        ax, ay = at(x, y, rot, side * (w / 2 - 0.09), 0)
        add_box(f"{name}_arm{side}", ax, ay, h - 0.36, h - 0.06, 0.18, d, mat, rot=rot, bevel=0.03)
    for i in range(3):
        cx_, cy_ = at(x, y, rot, -w / 3 + i * w / 3, -0.02)
        add_box(f"{name}_cush{i}", cx_, cy_, h - 0.18, h - 0.08, w / 3 - 0.03, d - 0.24, mat, rot=rot, bevel=0.03)
    for i, (dx, dy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        lx, ly = at(x, y, rot, dx * (w / 2 - 0.10), dy * (d / 2 - 0.10))
        add_box(f"{name}_leg{i}", lx, ly, 0.0, 0.10, 0.05, 0.05, M_BLACK, rot=rot, bevel=0.004)


def f_chair(it, name, mat, shell=True):
    x, y = P(it["x"]), P(it["y"])
    w, d, h = P(it["w"]), P(it["d"]), P(it["h"])
    rot = math.radians(it.get("rot", 0))
    add_box(f"{name}_seat", x, y, h - 0.46, h - 0.38, w, d, mat, rot=rot, bevel=0.02)
    bx, by = at(x, y, rot, 0, d / 2 - 0.035)
    add_box(f"{name}_back", bx, by, h - 0.42, h, w, 0.07, mat, rot=rot, bevel=0.02)
    for i, (dx, dy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        lx, ly = at(x, y, rot, dx * (w / 2 - 0.045), dy * (d / 2 - 0.045))
        add_box(f"{name}_leg{i}", lx, ly, 0.0, h - 0.44, 0.032, 0.032, M_BLACK, rot=rot, bevel=0.003)


def f_table(it, name, mat, top=0.05, leg=0.06):
    x, y = P(it["x"]), P(it["y"])
    w, d, h = P(it["w"]), P(it["d"]), P(it["h"])
    rot = math.radians(it.get("rot", 0))
    add_box(f"{name}_top", x, y, h - top, h, w, d, mat, rot=rot, bevel=0.008)
    for i, (dx, dy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        lx, ly = at(x, y, rot, dx * (w / 2 - leg), dy * (d / 2 - leg))
        add_box(f"{name}_leg{i}", lx, ly, 0.0, h - top, leg, leg, mat, rot=rot, bevel=0.004)


def f_round(it, name, mat):
    x, y = P(it["x"]), P(it["y"])
    w, h = P(it["w"]), P(it["h"])
    add_cyl(f"{name}_top", x, y, h - 0.045, h, w / 2, mat)
    add_cyl(f"{name}_ped", x, y, 0.0, h - 0.045, w / 5, mat, seg=32)
    add_cyl(f"{name}_foot", x, y, 0.0, 0.02, w / 3.2, M_BLACK, seg=32)


def f_bay(it, name):
    x, y = P(it["x"]), P(it["y"])
    w, d, h = P(it["w"]), P(it["d"]), P(it["h"])
    rot = math.radians(it.get("rot", 0))
    # recessed dark plinth so the wall wing does not look like it floats on the floor
    add_box(f"{name}_plinth", x, y, 0.0, 0.10, w - 0.05, d - 0.04, M_SHADOW, rot=rot, bevel=0.0)
    add_box(f"{name}_body", x, y, 0.10, h - 0.03, w, d, M_OAK, rot=rot, bevel=0.006)
    add_box(f"{name}_cap", x, y, h - 0.03, h, w + 0.02, d + 0.02, M_BRONZE, rot=rot, bevel=0.003)
    for side in (-1, 1):
        for edge in (-1, 1):
            ex, ey = at(x, y, rot, 0, edge * (d / 2 - 0.012))
            add_box(f"{name}_edge{side}{edge}", ex, ey, 0.10, h - 0.03, w + 0.014, 0.024, M_BLACK, rot=rot, bevel=0.0)
    # framed artwork on both faces
    for side in (-1, 1):
        for k, (dy, hh) in enumerate(((-0.55, 0.85), (0.55, 0.85))):
            fx, fy = at(x, y, rot, side * (w / 2 + 0.02), dy)
            add_box(f"{name}_art{side}{k}", fx, fy, 1.15, 1.15 + hh, 0.012, 0.62,
                    M_FABRIC2 if (k + side) % 2 else M_WALNUT, rot=rot, bevel=0.004)


def f_plant(it, name):
    x, y = P(it["x"]), P(it["y"])
    hh = P(it["h"])
    add_cyl(f"{name}_pot", x, y, 0.0, 0.42, 0.24, M_POT, seg=32)
    add_cyl(f"{name}_soil", x, y, 0.40, 0.43, 0.22, M_PLANT, seg=32)
    for k in range(5):
        ang = k * 1.26
        add_ico(f"{name}_leaf{k}", x + 0.10 * math.cos(ang), y + 0.10 * math.sin(ang),
                0.62 + 0.10 * k, 0.30 - 0.02 * k, M_PLANT,
                scale=(1.0, 1.0, 0.72), rot=ang)
    add_cyl(f"{name}_stem", x, y, 0.42, hh * 0.62, 0.028, M_POT, seg=12)


BUILDERS = {
    "sofa": lambda it, n: f_sofa(it, n, M_FABRIC),
    "armchair": lambda it, n: f_sofa({**it, "w": it["w"], "d": it["d"]}, n, M_FABRIC2),
    "chair": lambda it, n: f_chair(it, n, M_OAK if it.get("mat") == "oak" else M_FABRIC),
    "table": lambda it, n: f_table(it, n, M_WALNUT if it.get("mat") == "walnut" else M_OAK),
    "desk": lambda it, n: f_table(it, n, M_OAK, top=0.06, leg=0.08),
    "coffee": lambda it, n: f_table(it, n, M_STONE, top=0.05, leg=0.05),
    "counter": lambda it, n: (f_table(it, n, M_STONE, top=0.06, leg=0.10),
                              add_box(f"{n}_front", P(it["x"]), P(it["y"]), 0.0, P(it["h"]) - 0.06,
                                      P(it["w"]), P(it["d"]) * 0.9, M_WALNUT, bevel=0.006)),
    "cabinet": lambda it, n: add_box(f"{n}_body", P(it["x"]), P(it["y"]), 0.0, P(it["h"]),
                                     P(it["w"]), P(it["d"]), M_WALNUT, bevel=0.006),
    "bench": lambda it, n: (add_box(f"{n}_top", P(it["x"]), P(it["y"]), P(it["h"]) - 0.06, P(it["h"]),
                                    P(it["w"]), P(it["d"]), M_OAK, bevel=0.02),
                            [add_box(f"{n}_l{i}", *at(P(it["x"]), P(it["y"]), 0,
                                                      sx * (P(it["w"]) / 2 - 0.15), 0), 0.0,
                                     P(it["h"]) - 0.06, 0.05, 0.05, M_BLACK)
                             for i, sx in enumerate((-1, 1))]),
    "stool": lambda it, n: (add_cyl(f"{n}_seat", P(it["x"]), P(it["y"]), P(it["h"]) - 0.05,
                                    P(it["h"]), P(it["w"]) / 2, M_BRONZE, seg=32),
                            add_cyl(f"{n}_col", P(it["x"]), P(it["y"]), 0.0, P(it["h"]) - 0.05,
                                    0.03, M_BLACK, seg=16),
                            add_cyl(f"{n}_base", P(it["x"]), P(it["y"]), 0.0, 0.02,
                                    P(it["w"]) / 2.6, M_BLACK, seg=32)),
    "round": lambda it, n: f_round(it, n, M_WALNUT),
    "bay": lambda it, n: f_bay(it, n),
    "plant": lambda it, n: f_plant(it, n),
    "rug": lambda it, n: add_box(f"{n}_rug", P(it["x"]), P(it["y"]), 0.002, 0.014,
                                 P(it["w"]), P(it["d"]), M_FABRIC2, bevel=0.002),
}


def build_furniture():
    counts = {}
    for idx, it in enumerate(DATA["furniture"]):
        kind = it["kind"]
        fn = BUILDERS.get(kind)
        if fn is None:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        fn(it, f"f{idx}_{kind}")
    return counts


FURN_COUNTS = build_furniture()

# ------------------------------------------------------------------ sanitary ware (simple massing)
for i, fx in enumerate(DATA["fixtures"]):
    x, y = P(fx["x"]), P(fx["y"])
    w, d = P(fx["w"]), P(fx["d"])
    if fx["kind"] == "wc":
        add_box(f"wc_tank_{i}", x + d / 2 - 0.10, y, 0.0, 0.78, 0.20, w, M_WHITE, bevel=0.02)
        add_cyl(f"wc_bowl_{i}", x - 0.05, y, 0.0, 0.40, min(w, d) / 2.6, M_WHITE, seg=28)
    elif fx["kind"] == "vanity":
        add_box(f"vanity_{i}", x, y, 0.0, 0.82, w, d, M_WALNUT, bevel=0.006)
        add_box(f"vanity_top_{i}", x, y, 0.82, 0.86, w + 0.02, d + 0.02, M_STONE, bevel=0.004)
    elif fx["kind"] == "basin":
        add_cyl(f"basin_{i}", x, y, 0.86, 0.99, min(w, d) / 2, M_WHITE, seg=28)
    elif fx["kind"] == "shower":
        add_box(f"shower_tray_{i}", x, y, 0.0, 0.06, w, d, M_STONE, bevel=0.01)
        add_box(f"shower_glass_{i}", x + w / 2, y, 0.06, 2.0, 0.012, d, M_GLASS, bevel=0.0)

# ------------------------------------------------------------------ tabletop props
add_cyl("tray_dining", P(14400), P(3300), 0.75, 0.765, 0.30, M_BRONZE, seg=40)
add_cyl("bowl_dining", P(14400), P(3300), 0.765, 0.83, 0.18, M_WHITE, seg=32)
for k in range(3):
    add_box(f"mag_{k}", P(8400), P(2800) - 0.13 + 0.02 * k, 0.38 + 0.012 * k, 0.392 + 0.012 * k,
            0.34, 0.26, M_FABRIC2, rot=math.radians(-6 + 5 * k), bevel=0.002)
add_cyl("vase_coffee", P(10600), P(2600), 0.38, 0.55, 0.075, M_STONEW, seg=28)
add_box("tray_coffee", P(22000), P(10500), 0.38, 0.395, 0.42, 0.30, M_BRONZE, bevel=0.004)
add_box("desk_lamp", P(560), P(9800) + 0.55, 1.05, 1.42, 0.14, 0.14, M_BRONZE, bevel=0.01)
add_cyl("desk_bowl", P(560), P(9800) - 0.55, 1.05, 1.09, 0.14, M_WHITE, seg=32)

# ------------------------------------------------------------------ lighting
world = bpy.data.worlds.new("W")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.60, 0.69, 0.83, 1.0)
bg.inputs["Strength"].default_value = 0.72


def add_area(name, loc, sx, sy, power, color=(1.0, 0.86, 0.70), direction=(0, 0, -1), portal=False):
    ld = bpy.data.lights.new(name, "AREA")
    ld.shape = "RECTANGLE"
    ld.size, ld.size_y = sx, sy
    ld.energy = power
    ld.color = color
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    ob.rotation_euler = Vector(direction).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(ob)
    if portal:
        ld.cycles.is_portal = True
    return ob


def add_spot(name, loc, target, power, angle=40, color=(1.0, 0.84, 0.66), radius=0.05):
    ld = bpy.data.lights.new(name, "SPOT")
    ld.energy = power
    ld.spot_size = math.radians(angle)
    ld.spot_blend = 0.65
    ld.color = color
    ld.shadow_soft_size = radius
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(ob)
    return ob


# daylight
sun_data = bpy.data.lights.new("sun", "SUN")
sun_data.energy = 3.4
sun_data.angle = math.radians(1.6)
sun_data.color = (1.0, 0.94, 0.84)
sun = bpy.data.objects.new("sun", sun_data)
sun.location = (W * 0.6, H + 3.0, 5.5)
sun.rotation_euler = Vector((0.26, -1.0, -0.42)).to_track_quat("-Z", "Y").to_euler()
scene.collection.objects.link(sun)

# bright sky plane just outside every window: reads as daylight, lights the room
for i, (a, b) in enumerate(north_windows):
    add_box(f"n_sky_{i}", (a + b) / 2, H + 0.30, 0.10, 2.95, (b - a) + 0.5, 0.02, M_SKY, bevel=0.0)
for i, (a, b) in enumerate(east_windows):
    add_box(f"e_sky_{i}", W + 0.30, (a + b) / 2, 0.10, 2.95, 0.02, (b - a) + 0.5, M_SKY, bevel=0.0)

# interior downlights
add_area("ceil_1", (P(6800), P(13200), CEIL - 0.04), 5.0, 2.4, 62, direction=(0, 0, -1))
add_area("ceil_2", (P(19800), P(10500), CEIL - 0.04), 4.0, 3.2, 58, direction=(0, 0, -1))
add_area("ceil_3", (P(13500), P(3600), CEIL - 0.04), 5.0, 2.4, 56, direction=(0, 0, -1))
add_area("ceil_4", (P(3000), P(10800), CEIL - 0.04), 3.6, 3.2, 62, direction=(0, 0, -1))
add_area("ceil_ma", (P(2500), P(15600), CEIL - 0.04), 3.2, 2.4, 34, direction=(0, 0, -1))
add_area("ceil_mb", (P(23900), P(15500), CEIL - 0.04), 3.0, 2.4, 30, direction=(0, 0, -1))
add_area("ceil_lounge", (P(22000), P(10800), CEIL - 0.04), 3.6, 2.6, 45, direction=(0, 0, -1))

# island fill: lights the horizontal oak rings that sit outside the cove
add_area("island_fill", (P(12500), P(8600), CEIL - 0.26), 6.2, 4.2, 34, direction=(0, 0, -1),
         color=(1.0, 0.90, 0.78))

# soft up-light so the white ceiling reads as painted plaster, not a dark slab
add_area("ceil_bounce", (W * 0.45, H * 0.48, 2.30), 7.0, 9.0, 15,
         color=(1.0, 0.94, 0.86), direction=(0, 0, 1))

# track spots on the island pedestals + gallery bays
for i, (sx_, sy_) in enumerate(DATA["lights"]["spots"]):
    add_spot(f"spot_{i}", (P(sx_), P(sy_) - 0.55, CEIL - 0.28), (P(sx_), P(sy_), 0.80), 95, angle=26)

# pendants over the dining table
for i, (px, py) in enumerate(DATA["lights"]["pendants"]):
    add_cyl(f"pend_{i}_cord", P(px), P(py), 2.05, CEIL, 0.006, M_BLACK, seg=8)
    add_cyl(f"pend_{i}_shade", P(px), P(py), 1.86, 2.05, 0.13, M_BRONZE, seg=32)
    add_cyl(f"pend_{i}_bulb", P(px), P(py), 1.85, 1.87, 0.10, M_STRIP, seg=32)
    add_spot(f"pend_{i}_light", (P(px), P(py), 1.84), (P(px), P(py), 0.0), 30, angle=110)

# track rail
add_spot("wash_brand", (P(2700), P(11800), CEIL - 0.10), (P(2700), P(13200), 1.60), 70, angle=62)
add_spot("wash_mat", (P(19900), P(4000), CEIL - 0.10), (P(20800), P(4000), 1.50), 55, angle=58)
add_spot("wash_gallery", (P(9500), P(15000), CEIL - 0.10), (P(9500), P(16600), 1.50), 80, angle=70)

add_box("track_rail", P(13200), P(14300), CEIL - 0.055, CEIL - 0.025, P(14800), 0.04, M_BLACK, bevel=0.0)

# ------------------------------------------------------------------ camera
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 30.0
cam_data.sensor_width = 36.0
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

if VIEW == "entrance":
    eye = Vector((5.05, 10.55, 1.52))
    target = Vector((10.7, 8.95, 1.12))
elif VIEW == "island":
    eye = Vector((6.4, 5.6, 1.60))
    target = Vector((12.5, 8.6, 1.15))
else:
    eye = Vector((17.5, 15.0, 2.2))
    target = Vector((11.0, 8.6, 0.9))

cam.location = eye
cam.rotation_euler = (target - eye).to_track_quat("-Z", "Y").to_euler()

# ------------------------------------------------------------------ render settings
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.02
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 6
scene.cycles.diffuse_bounces = 3
scene.cycles.glossy_bounces = 3
scene.cycles.transmission_bounces = 4
scene.cycles.transparent_max_bounces = 4
scene.cycles.caustics_reflective = False
scene.cycles.caustics_refractive = False
scene.render.resolution_x = WIDTH
scene.render.resolution_y = HEIGHT
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.filepath = str(OUT_PNG)
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
except Exception:
    scene.view_settings.view_transform = "Filmic"
scene.view_settings.exposure = 0.06

t_build = time.time() - t_start
bpy.ops.render.render(write_still=True)
print(json.dumps({
    "status": "ok",
    "out": str(OUT_PNG),
    "build_s": round(t_build, 1),
    "total_s": round(time.time() - t_start, 1),
    "objects": len(scene.objects),
    "furniture": FURN_COUNTS,
    "camera": {"eye": list(eye), "target": list(target), "lens": cam_data.lens},
    "samples": SAMPLES, "size": [WIDTH, HEIGHT],
}, ensure_ascii=False))
