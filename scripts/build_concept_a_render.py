"""Build the concept-A 3D scene from the same DESIGN data used by the plan,
render it, and write the image. One data model, two outputs."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import concept_a as design  # noqa: E402
import render3d as r3  # noqa: E402

OUT = design.OUT


def rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


MAT = {key: rgb(value["color"]) for key, value in design.MATERIALS.items()}
W, H, CEIL = design.W, design.H, design.CEILING


def wall_run_horizontal(x0, x1, y0, thickness, z0, z1, color, out, boxes, emissive=0.0):
    out.extend(r3.box_faces(x0, y0 - thickness / 2, z0, x1, y0 + thickness / 2, z1, color, emissive))
    if z1 > 1.2:
        boxes.append((x0, y0 - thickness / 2, z0, x1, y0 + thickness / 2, z1))


def build():
    faces: list = []
    boxes: list = []
    floor_c = MAT["floor"]
    wall_c = MAT["wall"]

    # floor (slightly darker toward the south, handled by lighting)
    faces.append(([(0, 0, 0), (W, 0, 0), (W, H, 0), (0, H, 0)], floor_c, 0.0))
    boxes.append((-1, -1, -0.4, W + 1, H + 1, 0.0))

    # ceiling with a large recess above the island
    faces.append(([(0, 0, CEIL), (W, 0, CEIL), (W, H, CEIL), (0, H, CEIL)], (0.96, 0.94, 0.90), 0.13))

    # ---- perimeter
    t = 200.0
    # south wall
    wall_run_horizontal(0, W, 100, t, 0, CEIL, wall_c, faces, boxes)
    # north wall with the three 5400 glazing bands
    bands = [(0, 2688), (8154, 8778), (14228, 14867), (20317, W)]
    for x0, x1 in bands:
        wall_run_horizontal(x0, x1, H - 100, t, 0, CEIL, wall_c, faces, boxes)
    for x0, x1 in ((2688, 8154), (8778, 14228), (14867, 20317)):
        wall_run_horizontal(x0, x1, H - 100, t, 0, 900, wall_c, faces, boxes)
        wall_run_horizontal(x0, x1, H - 100, t, 2700, CEIL, wall_c, faces, boxes)
        faces.append(([(x0, H - 190, 900), (x1, H - 190, 900), (x1, H - 190, 2700), (x0, H - 190, 2700)],
                      (1.0, 0.98, 0.94), 1.0))

    # west wall with the entrance opening
    for y0, y1 in ((0, 10300), (12100, H)):
        faces.extend(r3.box_faces(0, y0, 0, t, y1, CEIL, wall_c))
        boxes.append((0, y0, 0, t, y1, CEIL))
    faces.append(([(0, 10300, 0), (t, 10300, 0), (t, 10300, 2700), (0, 10300, 2700)], wall_c, 0.0))
    faces.append(([(0, 12100, 0), (t, 12100, 0), (t, 12100, 2700), (0, 12100, 2700)], wall_c, 0.0))

    # east wall with the two window bands
    east_bands = [(0, 231), (3037, 5742), (8273, H)]
    for y0, y1 in east_bands:
        faces.extend(r3.box_faces(W - t, y0, 0, W, y1, CEIL, wall_c))
        boxes.append((W - t, y0, 0, W, y1, CEIL))
    for y0, y1 in ((231, 3037), (5742, 8273)):
        faces.extend(r3.box_faces(W - t, y0, 0, W, y1, 900, wall_c))
        faces.extend(r3.box_faces(W - t, y0, 2700, W, y1, CEIL, wall_c))
        faces.append(([(W - 150, y0, 900), (W - 150, y1, 900), (W - 150, y1, 2700), (W - 150, y0, 2700)],
                      (1.0, 0.98, 0.94), 0.85))

    # ---- partitions and feature walls
    glass = (0.78, 0.85, 0.88)
    for x0, y0, length, thickness, height, material in design.WALLS:
        if material == "glass":
            if length > thickness:
                faces.extend(r3.box_faces(x0, y0 - thickness / 2, 0, x0 + length, y0 + thickness / 2,
                                          height, glass, 0.10))
                boxes.append((x0, y0 - thickness / 2, 0, x0 + length, y0 + thickness / 2, height))
            else:
                faces.extend(r3.box_faces(x0 - thickness / 2, y0, 0, x0 + thickness / 2, y0 + length,
                                          height, glass, 0.10))
                boxes.append((x0 - thickness / 2, y0, 0, x0 + thickness / 2, y0 + length, height))
        else:
            color = MAT["walnut"] if material == "walnut" else MAT["wall"]
            if length > thickness:
                faces.extend(r3.box_faces(x0, y0 - thickness / 2, 0, x0 + length, y0 + thickness / 2,
                                          height, color))
                boxes.append((x0, y0 - thickness / 2, 0, x0 + length, y0 + thickness / 2, height))
            else:
                faces.extend(r3.box_faces(x0 - thickness / 2, y0, 0, x0 + thickness / 2, y0 + length,
                                          height, color))
                boxes.append((x0 - thickness / 2, y0, 0, x0 + thickness / 2, y0 + length, height))

    # ---- island: three stepped tiers
    for index, (key, shade) in enumerate((("base", 0.88), ("mid", 0.98), ("top", 1.0))):
        x0, y0, x1, y1, z1 = design.ISLAND[key]
        z0 = 0.0
        color = MAT["stone"] if key == "top" else tuple(min(1.0, c * shade) for c in MAT["oak"])
        faces.extend(r3.box_faces(x0, y0, z0, x1, y1, z1, color))
        boxes.append((x0, y0, z0, x1, y1, z1))
        # recessed bronze reveal at the tier base
        faces.extend(r3.box_faces(x0 - 20, y0 - 20, z1 - 60, x1 + 20, y1 + 20, z1 - 20,
                                  MAT["bronze"], 0.05))

    for px, py, pr in design.PEDESTALS:
        faces.extend(r3.prism_faces(px, py, 720, 760, pr / 2 * 1.04, 16, MAT["bronze"]))
        faces.extend(r3.prism_faces(px, py, 760, 1100, pr / 2, 16, (0.95, 0.94, 0.90)))
        boxes.append((px - pr / 2, py - pr / 2, 720, px + pr / 2, py + pr / 2, 1080))

    # ---- furniture massing
    for item in design.FURNITURE:
        kind = item["kind"]
        cx, cy, w, d, h = item["x"], item["y"], item["w"], item["d"], item["h"]
        color = MAT.get(item.get("mat", "oak"), MAT["oak"])
        x0, x1 = cx - w / 2, cx + w / 2
        y0, y1 = cy - d / 2, cy + d / 2
        if kind == "rug":
            faces.append(([(x0, y0, 6), (x1, y0, 6), (x1, y1, 6), (x0, y1, 6)],
                          tuple(c * 0.92 for c in color), 0.0))
        elif kind == "plant":
            faces.extend(r3.prism_faces(cx, cy, 0, h, w * 0.42, 12, MAT["plant"]))
            boxes.append((cx - w / 2, cy - d / 2, 0, cx + w / 2, cy + d / 2, h))
        elif kind in {"sofa", "armchair"}:
            faces.extend(r3.box_faces(x0, y0, 0, x1, y1, h * 0.42, color))
            faces.extend(r3.box_faces(x0, y1 - 200, h * 0.42, x1, y1, h, color))
            boxes.append((x0, y0, 0, x1, y1, h))
        elif kind == "chair":
            faces.extend(r3.box_faces(x0, y0, 0, x1, y1, h * 0.45, color))
            faces.extend(r3.box_faces(x0, y1 - 90, h * 0.45, x1, y1, h, color))
            boxes.append((x0, y0, 0, x1, y1, h))
        elif kind == "table":
            faces.extend(r3.box_faces(x0, y0, h - 60, x1, y1, h, MAT["walnut"]))
            faces.extend(r3.box_faces(x0 + 120, y0 + 120, 0, x1 - 120, y1 - 120, h - 60, MAT["bronze"]))
            boxes.append((x0, y0, 0, x1, y1, h))
        elif kind == "round":
            faces.extend(r3.prism_faces(cx, cy, h - 50, h, w / 2, 24, MAT["walnut"]))
            faces.extend(r3.prism_faces(cx, cy, 0, h - 50, w / 6, 12, MAT["bronze"]))
            boxes.append((x0, y0, 0, x1, y1, h))
        elif kind in {"coffee", "desk", "counter", "cabinet", "bench", "bay"}:
            faces.extend(r3.box_faces(x0, y0, 0, x1, y1, h, color))
            boxes.append((x0, y0, 0, x1, y1, h))
        elif kind == "stool":
            faces.extend(r3.prism_faces(cx, cy, 0, h, w / 2, 12, color))
            boxes.append((x0, y0, 0, x1, y1, h))

    # ---- light fixtures (emissive)
    cx0, cy0, cx1, cy1, z, _k = design.LIGHTS["cove"]
    faces.append(([(cx0, cy0, z - 40), (cx1, cy0, z - 40), (cx1, cy1, z - 40), (cx0, cy1, z - 40)],
                  (1.0, 0.93, 0.82), 0.10))
    for (ax, ay, bx, by) in ((cx0, cy0, cx1, cy0 + 90), (cx0, cy1 - 90, cx1, cy1),
                             (cx0, cy0, cx0 + 90, cy1), (cx1 - 90, cy0, cx1, cy1)):
        faces.extend(r3.box_faces(ax, ay, 2700, bx, by, 2755, (1.0, 0.89, 0.72), 0.95))
    for sx in design.LIGHTS["spots_x"]:
        faces.extend(r3.prism_faces(sx, 14200, 2870, 2900, 90, 10, (1.0, 0.94, 0.84), 0.9))
    for px, py in design.LIGHTS["pendants"]:
        faces.extend(r3.box_faces(px - 260, py - 70, 2320, px + 260, py + 70, 2360,
                                  (1.0, 0.92, 0.78), 0.85))

    # ---- presentation detail: products on the pedestals, brand panel, light slots
    product_colors = [(0.86, 0.84, 0.80), (0.62, 0.44, 0.28), (0.52, 0.55, 0.54), (0.90, 0.88, 0.84)]
    for index, (px, py, pr) in enumerate(design.PEDESTALS):
        color = product_colors[index % len(product_colors)]
        faces.extend(r3.box_faces(px - 190, py - 190, 1100, px + 190, py + 190, 1100 + 300 + index * 40, color))
        boxes.append((px - 190, py - 190, 1100, px + 190, py + 190, 1400))
    # recessed brand panel on the arrival wall (faces the entrance)
    faces.extend(r3.box_faces(1250, 8480, 700, 4350, 8560, 2400, (0.32, 0.22, 0.16)))
    # ceiling light slots running east-west
    for ly in (5800, 9600, 13400):
        faces.extend(r3.box_faces(6800, ly - 40, 2950, 18200, ly + 40, 2975, (1.0, 0.94, 0.84), 0.85))
    # long bench cushion tone + a couple of tall vases for scale
    for vx, vy in ((7200, 14500), (18600, 14200)):
        faces.extend(r3.prism_faces(vx, vy, 0, 900, 180, 12, (0.84, 0.80, 0.74)))

    sun_occluders = list(boxes)
    lights = [
        {"window_sun": True, "axis": 1, "wall": H - 120, "dir": (0.18, -1.0, -0.20),
         "z0": 250, "z1": 2880, "bands": [(2688, 8154), (8778, 14228), (14867, 20317)],
         "color": (1.0, 0.94, 0.82), "power": 2.6, "occluders": sun_occluders},
        {"pos": (6000, H - 400, 2100), "color": (1.0, 0.94, 0.86), "power": 0.75, "radius": 6.0},
        {"pos": (12500, H - 400, 2100), "color": (1.0, 0.94, 0.86), "power": 0.85, "radius": 6.0},
        {"pos": (19000, H - 400, 2100), "color": (1.0, 0.94, 0.86), "power": 0.70, "radius": 5.5},
        {"pos": (12500, 8600, 2800), "color": (1.0, 0.78, 0.55), "power": 0.60, "radius": 2.4},
        {"pos": (12500, 8600, 400), "color": (1.0, 0.90, 0.78), "power": 0.35, "radius": 5.0},
        {"pos": (11000, 15200, 2700), "color": (1.0, 0.84, 0.64), "power": 0.45, "radius": 2.2},
        {"pos": (14400, 3300, 2320), "color": (1.0, 0.85, 0.66), "power": 0.30, "radius": 2.0},
    ]
    return faces, boxes, lights


def main() -> int:
    width = int(sys.argv[1]) if len(sys.argv) > 1 else 1600
    height = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    faces, boxes, lights = build()
    camera = r3.Camera(eye=(19900, 4600, 1680), target=(10600, 12000, 1380), fov_deg=58)
    image = r3.render(faces, boxes, camera, width, height, supersample=2,
                      lights=lights, ambient=(0.30, 0.28, 0.25), exposure=0.92)
    target = OUT / "03_方案A_效果图_01.png"
    r3.save_png(image, target)
    print(json.dumps({"image": str(target), "size": [width, height], "faces": len(faces),
                      "boxes": len(boxes)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
