"""W2-R4 表达收口 V1：分层可读平面（几何 / 短编号 / 注释与索引）。

架构师 review-next.md V1 指出：入口处门号、机位、红色动线及数值压叠；
"北光廊""南生活场景"等文字与对象框交叉；墙边白色文字与洞口文字对比不足；
"文字可读"自动断言只证明字符串存在。

本模块把三类内容分开：
  * layer-geometry   纯几何：分区面、墙、洞口、平台、保留区、家具轮廓、动线、灯位、视锥
  * layer-ids        短编号徽标（白底深字、带引线、自动避让），不再压在几何线上
  * layer-annotations 留白处的名称标签 + 图内精简索引 + 完整说明移到 plan-index.json

并补一条可闭合的受控尺寸链（总尺寸 → 关键空间 → 开口定位），站表与闭合校验
写进 plan-index.json。全部尺寸标注明确为人工测试假设，不是施工定位尺寸。

旧路径（presentation=None）仍走 ai_spatial_outputs.build_plan_svg 的原逻辑，
不受本模块影响。
"""
from __future__ import annotations

import math
from html import escape
from typing import Any

from shapely.geometry import Polygon

from .ai_spatial_outputs import (
    GENERATOR_VERSION, PRESENTATION_VERSION, _fmt_mm, model_hash,
    rounded_polygon_2d,
)

PLAN_LAYERS_VERSION = "rkd-spatial-plan-layers.v1"
PLAN_INDEX_VERSION = "rkd-spatial-plan-index.v1"

# 图面文字对比：不再使用白字压深色墙；所有徽标/标签为白底深字
INK = "#1f2937"
MUTED = "#475569"
ACCENT = "#1e3a8a"
WARN = "#9a3412"
CELL = 16.0


class LabelPlacer:
    """按留白格避让标签；所有标签中心间距至少 CELL，避免互相压叠。"""

    def __init__(self, bounds: tuple[float, float, float, float] | None = None) -> None:
        self.occupied: set[tuple[int, int]] = set()
        self.forced: list[str] = []
        # 标签不得跑出绘图区，避免压到顶部尺寸链或右侧信息栏
        self.bounds = bounds

    def place(self, ax: float, ay: float, width_px: float, *, key: str = "",
              height_px: float = 14.0) -> tuple[float, float, bool]:
        span = max(1, math.ceil(width_px / CELL))
        offsets = [
            (0, 0), (0, -22), (0, 22), (-26, 0), (26, 0),
            (-30, -24), (30, -24), (-30, 24), (30, 24),
            (0, -46), (0, 46), (-52, -34), (52, -34), (-52, 34), (52, 34),
            (0, -70), (0, 70), (-76, 0), (76, 0),
            (-70, -56), (70, -56), (-70, 56), (70, 56),
            (0, -94), (0, 94), (-98, -70), (98, -70), (-98, 70), (98, 70),
            (-120, 0), (120, 0), (-120, -92), (120, -92), (-120, 92), (120, 92),
            (-46, -78), (46, -78), (-46, 78), (46, 78),
        ]
        for dx, dy in offsets:
            px, py = ax + dx, ay + dy
            if self.bounds:
                x0, y0, x1, y1 = self.bounds
                half_w = width_px / 2 + 3
                half_h = height_px / 2 + 3
                if (px - half_w < x0 or px + half_w > x1
                        or py - half_h < y0 or py + half_h > y1):
                    continue
            gx, gy = int(px // CELL), int(py // CELL)
            cells = [(gx + i, gy + j)
                     for i in range(-1, span + 1) for j in (-1, 0, 1)]
            if any(c in self.occupied for c in cells):
                continue
            self.occupied.update(cells)
            return px, py, False
        px, py = ax + offsets[-1][0], ay + offsets[-1][1]
        gx, gy = int(px // CELL), int(py // CELL)
        self.occupied.update((gx + i, gy + j)
                             for i in range(-1, span + 1) for j in (-1, 0, 1))
        self.forced.append(key)
        return px, py, True


def _short(object_id: str, prefix: str, index: int) -> str:
    return f"{prefix}{index}"


def furniture_codes(presentation: dict) -> dict[str, str]:
    """object_id → 全局唯一短码。

    V3 新增陈设后 `R4-PROP-03` / `R4-STG-PED-03` / `R4-STG-OBJ-03` 若都取
    尾号会得到同一个 P03，既造成图面标签重叠，也会让 plan-index.json 的
    labels 互相覆盖。这里按对象类别给不同前缀并全局去重，平面与索引共用。
    """
    prefixes = (("R4-STG-PED", "D"), ("R4-STG-OBJ", "E"),
                ("R4-STG-SEAT", "S"), ("R4-STG-BRAND", "B"),
                ("R4-PROP", "P"))
    used: set[str] = set()
    out: dict[str, str] = {}
    for f in presentation["furniture"]:
        oid = f["object_id"]
        if len(oid) <= 5:
            code = oid
        else:
            prefix = "T"
            for key, value in prefixes:
                if oid.startswith(key):
                    prefix = value
                    break
            code = f"{prefix}{oid.split('-')[-1]}"
        base, suffix = code, 2
        while code in used:
            code = f"{base}{suffix}"
            suffix += 1
        used.add(code)
        out[oid] = code
    return out


def _dim_stations(model: dict, presentation: dict) -> dict:
    """总尺寸 → 关键空间 → 开口定位 的受控尺寸链站点（mm，西南原点）。"""
    width = float(model["spatial"]["origin"]["boundary_mm"][0])
    height = float(model["spatial"]["origin"]["boundary_mm"][1])
    x_points: list[tuple[float, str, str]] = [(0.0, "boundary", "场地西边界（模型边界参数）"),
                                              (width, "boundary", "场地东边界（模型边界参数）")]
    y_points: list[tuple[float, str, str]] = [(0.0, "boundary", "场地南边界（模型边界参数）"),
                                              (height, "boundary", "场地北边界（模型边界参数）")]
    walls = {w["object_id"]: w for w in presentation["walls"] + presentation["partitions"]}
    for op in presentation["openings"]:
        host = walls.get(op["wall_object_id"])
        if host is None:
            continue
        seg = host["segment_mm"]
        horizontal = abs(seg[1][1] - seg[0][1]) < abs(seg[1][0] - seg[0][0])
        cx, cy = op["center_mm"]
        basis = "manual_test_assumption:opening_position"
        if horizontal:
            x_points.append((float(cx), f"opening:{op['object_id']}", basis))
        else:
            y_points.append((float(cy), f"opening:{op['object_id']}", basis))
    for platform in model["spatial"].get("platforms") or []:
        poly = platform.get("polygon_mm") or []
        if len(poly) < 3:
            continue
        xs, ys = [float(p[0]) for p in poly], [float(p[1]) for p in poly]
        label = f"platform:{platform['object_id']}"
        x_points += [(min(xs), label, "source_model:platform_polygon"),
                     (max(xs), label, "source_model:platform_polygon")]
        y_points += [(min(ys), label, "source_model:platform_polygon"),
                     (max(ys), label, "source_model:platform_polygon")]

    def chain(points: list[tuple[float, str, str]], total: float, axis: str) -> dict:
        # 同一坐标可能来自多个依据：合并依据，不重复站点
        merged: dict[float, list[str]] = {}
        for value, kind, basis in points:
            value = round(min(max(value, 0.0), total), 1)
            merged.setdefault(value, []).append(f"{kind}｜{basis}")
        ordered = sorted(merged)
        stations = []
        for i, value in enumerate(ordered):
            delta = round(value - ordered[i - 1], 1) if i else 0.0
            stations.append({
                "id": f"{axis.upper()}{i + 1}",
                "coordinate_mm": value,
                "delta_from_previous_mm": delta,
                "basis": sorted(set(merged[value])),
                "source_kind": ("boundary" if i == 0 or i == len(ordered) - 1
                                else "model_or_manual_assumption"),
            })
        total_delta = round(sum(s["delta_from_previous_mm"] for s in stations), 1)
        return {"stations": stations, "total_mm": round(total, 1),
                "sum_delta_mm": total_delta,
                "closed": abs(total_delta - total) < 0.2,
                "axis": axis}

    return {"x": chain(x_points, width, "x"), "y": chain(y_points, height, "y"),
            "note": "受控尺寸链用于图面可读性对账：各段增量之和必须闭合到场地总尺寸。"
                    "站点来自模型边界/平台多边形或人工测试假设的洞口定位，"
                    "不是现场实测，也不是施工定位尺寸。"}


def build_plan_index(model: dict, camera: dict, quantities: dict,
                     presentation: dict) -> dict:
    """完整编号索引（与 SVG 用同一份标签字典），供对账与自动断言使用。"""
    spatial = model["spatial"]
    labels: dict[str, dict] = {}

    def put(code: str, kind: str, object_id: str, name: str, **extra) -> None:
        labels[code] = {"code": code, "kind": kind, "object_id": object_id,
                        "name": name, **extra}

    for i, z in enumerate(spatial["zones"], 1):
        xs = [float(p[0]) for p in z["polygon_mm"]]
        ys = [float(p[1]) for p in z["polygon_mm"]]
        put(f"Z{i}", "zone", z["object_id"], z["name"],
            size_mm=[_fmt_mm(max(xs) - min(xs)), _fmt_mm(max(ys) - min(ys))],
            area_sqm=z.get("area_sqm"), source="source_model:spatial.zones")
    for i, w in enumerate(presentation["walls"] + presentation["partitions"], 1):
        put(f"W{i}", "wall", w["object_id"], w["kind"],
            thickness_mm=w["thickness_mm"], height_mm=w["height_mm"],
            material_slot=w["material_slot"], source=w["source"])
    for i, op in enumerate(presentation["openings"], 1):
        put(f"O{i}", "opening", op["object_id"], op["kind"],
            width_mm=op["width_mm"], height_mm=op["height_mm"],
            sill_mm=op["sill_mm"], wall_object_id=op["wall_object_id"],
            center_mm=op["center_mm"], source=op["source"])
    codes = furniture_codes(presentation)
    for f in presentation["furniture"]:
        put(codes[f["object_id"]],
            "furniture", f["object_id"], f.get("catalog_id") or "",
            asset_id=f.get("asset_id"),
            asset_dimensions_mm=f.get("asset_dimensions_mm"),
            origin_kind=f.get("origin_kind") or "cc0_expression_asset",
            source=f.get("source"))
    put("C1", "camera", camera["camera_id"], "人眼机位（人工假设）",
        eye_height_mm=camera["eye_height_mm"], lens_mm=camera["lens_mm"],
        position_mm=camera["position_mm"], target_mm=camera["target_mm"],
        source="manual_test_assumption")
    for i, c in enumerate(spatial["circulation"], 1):
        put(f"R{i}", "circulation", c["object_id"], "主动线（意向）",
            width_mm=c.get("width_mm"), source="source_model:spatial.circulation")
    for i, o in enumerate(model["boundary"]["obstacles"], 1):
        put(f"K{i}", "keepout", o["object_id"], o.get("name") or o["object_id"],
            source="source_model:boundary.obstacles")

    expression_accounting = {
        "source_model_objects": sum(1 for v in labels.values()
                                    if v["kind"] in {"zone", "keepout", "circulation"}),
        "expression_assets": sum(1 for v in labels.values()
                                 if v["kind"] == "furniture"
                                 and v.get("origin_kind") == "cc0_expression_asset"),
        "test_staging": sum(1 for v in labels.values()
                            if v["kind"] == "furniture"
                            and v.get("origin_kind") == "test_staging"),
        "procedural_expression": sum(1 for v in labels.values()
                                     if v["kind"] == "furniture"
                                     and v.get("origin_kind") == "procedural_expression"),
        "engineering_quantity_effect": 0,
        "note": "表达资产/测试陈设/程序化表达对象只进入平面与场景表现，"
                "不进入 measure() 的工程量、材料面切片或试算金额。",
    }
    return {
        "schema_version": PLAN_INDEX_VERSION,
        "plan_layers_version": PLAN_LAYERS_VERSION,
        "presentation_version": PRESENTATION_VERSION,
        "generator_version": GENERATOR_VERSION,
        "option_id": model["option_id"], "revision_no": model["revision_no"],
        "model_hash": model_hash(model),
        "labels": labels,
        "dimension_chain": _dim_stations(model, presentation),
        "expression_accounting": expression_accounting,
        "disclaimer": presentation.get("disclaimer"),
        "note": "编号索引与平面 SVG 由同一份标签字典生成；完整说明在此，"
                "图面只保留短编号与必要引线，避免文字压叠。",
    }


def _badge(out: list[str], placer: LabelPlacer, ax: float, ay: float,
           code: str, color: str, *, key: str, width: float = 22.0) -> None:
    px, py, forced = placer.place(ax, ay, width, key=key)
    out.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{px:.1f}" y2="{py:.1f}" '
               f'stroke="{color}" stroke-width="0.7" opacity="0.75"/>')
    out.append(f'<rect x="{px - width/2:.1f}" y="{py - 7:.1f}" width="{width:.1f}" '
               f'height="14" rx="3" fill="#ffffff" stroke="{color}" '
               f'stroke-width="1" opacity="0.97"/>')
    out.append(f'<text data-anno="1" x="{px:.1f}" y="{py + 3.4:.1f}" '
               f'text-anchor="middle" font-size="9" font-weight="600" '
               f'fill="{INK}">{escape(code)}</text>')
    if forced:
        out.append(f'<!-- forced-label: {escape(key)} -->')


def _name_label(out: list[str], placer: LabelPlacer, ax: float, ay: float,
                text: str, color: str, *, key: str) -> None:
    width = min(150.0, max(46.0, len(text) * 11.0 + 10))
    px, py, _forced = placer.place(ax, ay, width, key=key)
    out.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{px:.1f}" y2="{py:.1f}" '
               f'stroke="{color}" stroke-width="0.7" stroke-dasharray="3 2" opacity="0.8"/>')
    out.append(f'<rect x="{px - width/2:.1f}" y="{py - 8.5:.1f}" width="{width:.1f}" '
               f'height="17" rx="2" fill="#ffffff" fill-opacity="0.94" '
               f'stroke="{color}" stroke-width="0.6"/>')
    out.append(f'<text data-anno="1" x="{px:.1f}" y="{py + 3.6:.1f}" '
               f'text-anchor="middle" font-size="11" font-weight="600" '
               f'fill="{INK}">{escape(text)}</text>')


def build_layered_plan_svg(model: dict, camera: dict, quantities: dict,
                           presentation: dict) -> bytes:
    """分层平面：几何 / 短编号 / 注释索引，带可闭合受控尺寸链。"""
    spatial = model["spatial"]
    width = float(spatial["origin"]["boundary_mm"][0])
    height = float(spatial["origin"]["boundary_mm"][1])
    scale = min(880.0 / width, 640.0 / height)
    ox, oy = 100.0, 170.0
    draw_w, draw_h = width * scale, height * scale
    lx = ox + draw_w + 60
    W = lx + 330
    H = oy + draw_h + 620

    def X(mm: float) -> float:
        return ox + mm * scale

    def Y(mm: float) -> float:
        return oy + (height - mm) * scale

    def pts(poly: list) -> str:
        return " ".join(f"{X(float(p[0])):.2f},{Y(float(p[1])):.2f}" for p in poly)

    index = build_plan_index(model, camera, quantities, presentation)
    labels = index["labels"]
    chains = index["dimension_chain"]
    placer = LabelPlacer(bounds=(ox + 8, oy + 8, ox + draw_w - 8, oy + draw_h - 8))
    geom: list[str] = []
    ids: list[str] = []
    anno: list[str] = []

    palette = ["#dbeafe", "#dcfce7", "#fef3c7", "#fce7f3", "#e0e7ff", "#ccfbf1",
               "#fee2e2", "#ede9fe"]

    # ------------------------------------------------------------ layer-geometry
    geom.append(f'<rect x="{ox}" y="{Y(height):.2f}" width="{draw_w:.2f}" '
                f'height="{draw_h:.2f}" fill="#ffffff" stroke="#1f2937" stroke-width="3"/>')
    zone_anchors: list[tuple[float, float, str, int]] = []
    for i, z in enumerate(spatial["zones"]):
        poly = z["polygon_mm"]
        fill = (z.get("finish_material") or {}).get("hex") or palette[i % len(palette)]
        geom.append(f'<polygon points="{pts(poly)}" fill="{fill}" fill-opacity="0.72" '
                    f'stroke="#334155" stroke-width="1.4"/>')
        shape = Polygon([(float(p[0]), float(p[1])) for p in poly])
        point = shape.representative_point()
        zone_anchors.append((X(point.x), Y(point.y), z["name"], i + 1))

    walls = presentation["walls"] + presentation["partitions"]
    wall_by_id = {w["object_id"]: w for w in walls}
    for w in walls:
        (x1, y1), (x2, y2) = w["segment_mm"]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux
        half = w["thickness_mm"] / 2
        poly = [[x1 + nx * half, y1 + ny * half], [x2 + nx * half, y2 + ny * half],
                [x2 - nx * half, y2 - ny * half], [x1 - nx * half, y1 - ny * half]]
        colour = "#3f3f46" if w["kind"] == "perimeter" else "#78716c"
        geom.append(f'<polygon points="{pts(poly)}" fill="{colour}" fill-opacity="0.90" '
                    f'stroke="#1c1917" stroke-width="0.7"/>')

    openings_by_wall: dict[str, list] = {}
    for op in presentation["openings"]:
        openings_by_wall.setdefault(op["wall_object_id"], []).append(op)
    for w in walls:
        (x1, y1), (x2, y2) = w["segment_mm"]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux
        half_t = w["thickness_mm"] / 2 + 30
        for op in openings_by_wall.get(w["object_id"], []):
            cx, cy = op["center_mm"]
            half_w = op["width_mm"] / 2
            a = [cx - ux * half_w - nx * half_t, cy - uy * half_w - ny * half_t]
            b = [cx + ux * half_w - nx * half_t, cy + uy * half_w - ny * half_t]
            c = [cx + ux * half_w + nx * half_t, cy + uy * half_w + ny * half_t]
            d = [cx - ux * half_w + nx * half_t, cy - uy * half_w + ny * half_t]
            geom.append(f'<polygon points="{pts([a, b, c, d])}" fill="#ffffff" '
                        f'stroke="#1c1917" stroke-width="0.6"/>')
            if op["kind"] == "window":
                for off in (-half_t * 0.35, half_t * 0.35):
                    p1 = [cx - ux * half_w + nx * off, cy - uy * half_w + ny * off]
                    p2 = [cx + ux * half_w + nx * off, cy + uy * half_w + ny * off]
                    geom.append(f'<line x1="{X(p1[0]):.1f}" y1="{Y(p1[1]):.1f}" '
                                f'x2="{X(p2[0]):.1f}" y2="{Y(p2[1]):.1f}" '
                                f'stroke="#0369a1" stroke-width="1.3"/>')
            else:
                hinge = [cx - ux * half_w, cy - uy * half_w]
                leaf = [hinge[0] + nx * op["width_mm"], hinge[1] + ny * op["width_mm"]]
                geom.append(f'<line x1="{X(hinge[0]):.1f}" y1="{Y(hinge[1]):.1f}" '
                            f'x2="{X(leaf[0]):.1f}" y2="{Y(leaf[1]):.1f}" '
                            f'stroke="#a16207" stroke-width="1.5"/>')

    for o in model["boundary"]["obstacles"]:
        s = o["shape"]
        x, y = float(s["x"]) * 1000, float(s["y"]) * 1000
        w, l = float(s["width"]) * 1000, float(s["length"]) * 1000
        geom.append(f'<rect x="{X(x):.1f}" y="{Y(y+l):.1f}" width="{w*scale:.1f}" '
                    f'height="{l*scale:.1f}" fill="url(#keepout)" stroke="#64748b" '
                    f'stroke-width="1.3"/>')
    for p in spatial.get("platforms") or []:
        if len(p.get("polygon_mm") or []) < 3:
            continue
        outline = (rounded_polygon_2d(p["polygon_mm"], float(p.get("corner_radius_mm") or 0))
                   if p.get("corner_radius_mm") else p["polygon_mm"])
        geom.append(f'<polygon points="{pts(outline)}" fill="#f8fafc" fill-opacity="0.55" '
                    f'stroke="#b45309" stroke-width="1.8" stroke-dasharray="5 3"/>')

    furniture_anchors: list[tuple[float, float, str, dict]] = []
    furniture_code_map = furniture_codes(presentation)
    for f in presentation["furniture"]:
        dims = f.get("asset_dimensions_mm") or [600.0, 600.0, 750.0]
        w, d = float(dims[0]), float(dims[1])
        x, y = f["position_mm"]
        rot = math.radians(f["rotation_deg"])
        corners = []
        for dx, dy in ((-w/2, -d/2), (w/2, -d/2), (w/2, d/2), (-w/2, d/2)):
            corners.append([x + dx*math.cos(rot) - dy*math.sin(rot),
                            y + dx*math.sin(rot) + dy*math.cos(rot)])
        origin_kind = f.get("origin_kind") or "cc0_expression_asset"
        stroke = {"cc0_expression_asset": "#0f766e", "test_staging": "#7c3aed",
                  "procedural_expression": "#b45309", "source_model": "#334155"}.get(
                      origin_kind, "#334155")
        fill = {"cc0_expression_asset": "#d1fae5", "test_staging": "#ede9fe",
                "procedural_expression": "#fef3c7", "source_model": "#cbd5e1"}.get(
                    origin_kind, "#cbd5e1")
        geom.append(f'<polygon points="{pts(corners)}" fill="{fill}" fill-opacity="0.82" '
                    f'stroke="{stroke}" stroke-width="1" '
                    f'data-origin="{escape(origin_kind)}"/>')
        code = furniture_code_map[f["object_id"]]
        furniture_anchors.append((X(x), Y(y), code, f))

    for c in spatial["circulation"]:
        geom.append('<polyline points="' + pts(c["path_mm"]) + '" fill="none" '
                    'stroke="#dc2626" stroke-width="2.6" stroke-dasharray="9 5" '
                    'opacity="0.85"/>')
    for fx in (spatial["ceiling"].get("fixtures") or []):
        geom.append(f'<circle cx="{X(float(fx.get("x") or 0)):.1f}" '
                    f'cy="{Y(float(fx.get("y") or 0)):.1f}" r="4" fill="#f59e0b" '
                    f'stroke="#92400e" stroke-width="0.8"/>')

    # 机位视锥（几何层，极淡，不再叠长说明文字）
    ex, ey = camera["position_mm"]
    tx, ty = camera["target_mm"]
    angle0 = math.atan2(ty - ey, tx - ex)
    half_angle = math.degrees(math.atan(18.0 / max(camera["lens_mm"], 1)))
    reach = min(width, height) * 0.5
    for sign in (-1, 1):
        ang = angle0 + math.radians(sign * half_angle)
        geom.append(f'<line x1="{X(ex):.1f}" y1="{Y(ey):.1f}" '
                    f'x2="{X(ex + reach*math.cos(ang)):.1f}" '
                    f'y2="{Y(ey + reach*math.sin(ang)):.1f}" '
                    f'stroke="#7c3aed" stroke-width="0.9" stroke-dasharray="5 4" '
                    f'opacity="0.55"/>')

    # --------------------------------------------------------------- layer-ids
    for ax, ay, name, i in zone_anchors:
        _badge(ids, placer, ax, ay, f"Z{i}", "#334155", key=f"Z{i}")
        _name_label(anno, placer, ax, ay, name, "#64748b", key=f"zone-name-{i}")
    for i, w in enumerate(walls, 1):
        (x1, y1), (x2, y2) = w["segment_mm"]
        ax, ay = X((x1 + x2) / 2), Y((y1 + y2) / 2)
        _badge(ids, placer, ax, ay, f"W{i}", "#3f3f46", key=f"W{i}")
    for i, op in enumerate(presentation["openings"], 1):
        cx, cy = op["center_mm"]
        host = wall_by_id[op["wall_object_id"]]
        (x1, y1), (x2, y2) = host["segment_mm"]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n, dx / n
        off = host["thickness_mm"] + 330
        _badge(ids, placer, X(cx + nx * off), Y(cy + ny * off), f"O{i}",
               "#0369a1" if op["kind"] == "window" else "#a16207", key=f"O{i}")
    for ax, ay, code, f in furniture_anchors:
        colour = {"cc0_expression_asset": "#0f766e", "test_staging": "#7c3aed",
                  "procedural_expression": "#b45309", "source_model": "#334155"}.get(
                      f.get("origin_kind") or "cc0_expression_asset", "#334155")
        _badge(ids, placer, ax, ay, code, colour, key=f"furn-{code}", width=24.0)
    _badge(ids, placer, X(ex), Y(ey), "C1", "#7c3aed", key="C1")
    for i, c in enumerate(spatial["circulation"], 1):
        path = c["path_mm"]
        mid = path[len(path) // 2]
        _badge(ids, placer, X(float(mid[0])), Y(float(mid[1])), f"R{i}",
               "#dc2626", key=f"R{i}")
    for i, o in enumerate(model["boundary"]["obstacles"], 1):
        s = o["shape"]
        cx = float(s["x"]) * 1000 + float(s["width"]) * 500
        cy = float(s["y"]) * 1000 + float(s["length"]) * 500
        _badge(ids, placer, X(cx), Y(cy), f"K{i}", "#64748b", key=f"K{i}")

    # -------------------------------------------- 受控尺寸链（几何 + 站号标注）
    chain_y = oy - 34
    x_chain = chains["x"]
    geom.append(f'<line x1="{X(0):.1f}" y1="{chain_y}" x2="{X(width):.1f}" '
                f'y2="{chain_y}" stroke="#334155" stroke-width="0.9"/>')
    for st in x_chain["stations"]:
        sx = X(st["coordinate_mm"])
        geom.append(f'<line x1="{sx:.1f}" y1="{chain_y-5}" x2="{sx:.1f}" '
                    f'y2="{chain_y+5}" stroke="#334155" stroke-width="1"/>')
        geom.append(f'<line x1="{sx:.1f}" y1="{chain_y}" x2="{sx:.1f}" '
                    f'y2="{Y(0):.1f}" stroke="#94a3b8" stroke-width="0.5" '
                    f'stroke-dasharray="3 6" opacity="0.55"/>')
    for i, st in enumerate(x_chain["stations"][1:], 1):
        prev = x_chain["stations"][i - 1]
        a, b = X(prev["coordinate_mm"]), X(st["coordinate_mm"])
        if b - a < 62:
            continue
        delta = st["delta_from_previous_mm"]
        anno.append(f'<rect x="{(a+b)/2-30:.1f}" y="{chain_y-16:.1f}" width="60" '
                    f'height="12" fill="#ffffff" opacity="0.92"/>')
        anno.append(f'<text data-anno="1" x="{(a+b)/2:.1f}" y="{chain_y-7:.1f}" '
                    f'text-anchor="middle" font-size="8.5" fill="{MUTED}">'
                    f'{_fmt_mm(delta)}</text>')
    chain_x = ox - 56
    y_chain = chains["y"]
    geom.append(f'<line x1="{chain_x}" y1="{Y(0):.1f}" x2="{chain_x}" '
                f'y2="{Y(height):.1f}" stroke="#334155" stroke-width="0.9"/>')
    for st in y_chain["stations"]:
        sy = Y(st["coordinate_mm"])
        geom.append(f'<line x1="{chain_x-5}" y1="{sy:.1f}" x2="{chain_x+5}" '
                    f'y2="{sy:.1f}" stroke="#334155" stroke-width="1"/>')
    for i, st in enumerate(y_chain["stations"][1:], 1):
        prev = y_chain["stations"][i - 1]
        a, b = Y(prev["coordinate_mm"]), Y(st["coordinate_mm"])
        if abs(b - a) < 62:
            continue
        anno.append(f'<text data-anno="1" x="{chain_x-8:.1f}" y="{(a+b)/2:.1f}" '
                    f'text-anchor="middle" font-size="8.5" fill="{MUTED}" '
                    f'transform="rotate(-90 {chain_x-8:.1f} {(a+b)/2:.1f})">'
                    f'{_fmt_mm(st["delta_from_previous_mm"])}</text>')
    anno.append(f'<text x="{ox}" y="102" font-size="10" fill="{MUTED}">'
                f'X / Y 向受控尺寸链：总宽 {_fmt_mm(width)} mm、总长 {_fmt_mm(height)} mm；'
                f'站点与闭合校验见图下方站表与 plan-index.json（人工测试假设，非施工定位）</text>')

    # ------------------------------------------------------------ 标题与右侧栏
    head: list[str] = [
        f'<text x="{ox}" y="26" font-size="18" font-weight="700" fill="#111827">'
        f'{escape(model["strategy"]["statement"][:56])}</text>',
        f'<text x="{ox}" y="46" font-size="11" fill="{MUTED}">'
        f'候选 {escape(model["option_id"])} v{model["revision_no"]} · '
        f'源 {escape(spatial["source"]["artifact_id"])} · '
        f'模型 {model_hash(model)[:12]} · {GENERATOR_VERSION} · {PLAN_LAYERS_VERSION}</text>',
        f'<text x="{ox}" y="64" font-size="11" fill="#b91c1c">'
        f'概念平面（内部评审）：不是施工图，不宣称消防/无障碍/门洞净宽合规</text>',
        f'<text x="{ox}" y="82" font-size="10.5" fill="{WARN}">'
        f'表达层：墙/门窗/隔断/材质/家具/机位/灯光均为人工测试假设，'
        f'非现场事实、非 AI 自动设计；编号索引见 plan-index.json</text>',
    ]

    legend = [
        ("#dbeafe", "功能分区（源模型多边形，非墙体）"),
        ("#3f3f46", "周界墙 / 隔断（人工假设厚度）"),
        ("#0284c7", "窗洞口 + 窗光方向（假设）"),
        ("#a16207", "门洞 + 门扇弧线"),
        ("#d1fae5", "CC0 家具（真实目录尺寸）"),
        ("#ede9fe", "测试陈设（不计工程量）"),
        ("#fef3c7", "程序化表达 / 明确占位"),
        ("#dc2626", "主动线（净宽见索引）"),
        ("#7c3aed", "人眼机位 + 视锥（假设）"),
        ("#f59e0b", "灯具点位（模型天花意向）"),
        ("url(#keepout)", "保留区（源模型扣除）"),
    ]
    for mat in presentation["materials"]:
        legend.append((mat["hex"],
                       f'材质 {mat["name"]}（{mat["slot"]}，CC0 贴图意向）'))
    right: list[str] = [f'<text x="{lx}" y="{oy+4}" font-size="13" font-weight="700" '
                        f'fill="#111827">图例（编号见索引表）</text>']
    for i, (fill, label) in enumerate(legend):
        yy = oy + 26 + i * 21
        right.append(f'<rect x="{lx}" y="{yy-10}" width="17" height="11" fill="{fill}" '
                     f'stroke="#64748b" stroke-width="0.7"/>')
        right.append(f'<text x="{lx+24}" y="{yy}" font-size="9.5" fill="{MUTED}">'
                     f'{escape(label)}</text>')
    ty = oy + 26 + len(legend) * 21 + 18
    right.append(f'<text x="{lx}" y="{ty}" font-size="13" font-weight="700" '
                 f'fill="#111827">面积表</text>')
    right.append(f'<text x="{lx}" y="{ty+16}" font-size="9.5" fill="{MUTED}">'
                 f'（精确多边形复算，非模型自报）</text>')
    for i, z in enumerate(spatial["zones"]):
        yy = ty + 34 + i * 16
        right.append(f'<text x="{lx}" y="{yy}" font-size="9.5" fill="#334155">'
                     f'{escape(z["name"])}</text>')
        right.append(f'<text x="{lx+250}" y="{yy}" font-size="9.5" text-anchor="end" '
                     f'fill="#0f172a">{z.get("area_sqm")} ㎡</text>')
    net_item = next(q for q in quantities["items"]
                    if q["quantity_id"] == "Q-FLOOR-GEOMETRIC-NET")
    base_y = ty + 34 + len(spatial["zones"]) * 16 + 10
    right.append(f'<text x="{lx}" y="{base_y}" font-size="9.5" font-weight="600">'
                 f'功能分区几何净面积</text>')
    right.append(f'<text x="{lx+250}" y="{base_y}" font-size="9.5" text-anchor="end" '
                 f'font-weight="600">{net_item["value"]} ㎡</text>')
    finish_item = next(q for q in quantities["items"]
                       if q["quantity_id"] == "Q-FLOOR-FINISH")
    conflict = finish_item.get("known_status") == "conflict"
    right.append(f'<text x="{lx}" y="{base_y+16}" font-size="9.5">地坪完成面饰面净面积</text>')
    right.append(f'<text x="{lx+250}" y="{base_y+16}" font-size="9.5" text-anchor="end">'
                 f'{"conflict/待核" if conflict else finish_item["value"] if finish_item["value"] is not None else "unknown"}'
                 f'{" ㎡" if finish_item["value"] is not None else ""}</text>')
    my = base_y + 44
    right.append(f'<text x="{lx}" y="{my}" font-size="12" font-weight="700" '
                 f'fill="#b91c1c">未建模 / 缺项</text>')
    missing = (["墙体/门窗/隔断/材质/家具/机位为人工测试假设，非现场事实"]
               + list(presentation["missing"])[:7])
    for i, text in enumerate(missing):
        right.append(f'<text x="{lx}" y="{my+17+i*15}" font-size="9" fill="#7f1d1d">'
                     f'· {escape(text)}</text>')

    # ------------------------------------------- 图下方：精简索引 / 门窗 / 站表
    table_y = oy + draw_h + 34
    lower: list[str] = []
    lower.append(f'<text x="{ox}" y="{table_y}" font-size="12" font-weight="700" '
                 f'fill="#111827">编号索引（图面只留短编号；完整尺寸与来源见 plan-index.json）</text>')
    priority = [v for v in labels.values()
                if v["kind"] in {"zone", "wall", "opening", "camera",
                                 "circulation", "keepout"}]
    for i, item in enumerate(priority):
        col, row = i % 2, i // 2
        tx = ox + col * 440
        ty2 = table_y + 20 + row * 15
        detail = item.get("object_id") or ""
        if item["kind"] == "zone":
            extra = f'{item.get("size_mm", ["", ""])[0]}×{item.get("size_mm", ["", ""])[1]} mm · {item.get("area_sqm")}㎡'
        elif item["kind"] == "wall":
            extra = (f'厚 {_fmt_mm(item.get("thickness_mm") or 0)}mm · '
                     f'高 {_fmt_mm(item.get("height_mm") or 0)}mm')
        elif item["kind"] == "opening":
            extra = f'{_fmt_mm(item.get("width_mm") or 0)}×{_fmt_mm(item.get("height_mm") or 0)} · 窗台 {_fmt_mm(item.get("sill_mm") or 0)}'
        elif item["kind"] == "camera":
            extra = f'人眼 {item.get("eye_height_mm")}mm · {item.get("lens_mm")}mm'
        elif item["kind"] == "circulation":
            extra = f'净宽 {item.get("width_mm")}mm'
        else:
            extra = item.get("name") or ""
        # 图内索引只放短编号与核心尺寸；完整来源/依据在 plan-index.json，
        # 避免长字符串横向压到第二列（V1 人工目检发现并修正）。
        lower.append(f'<text x="{tx}" y="{ty2}" font-size="9" fill="{MUTED}">'
                     f'{escape(item["code"])} = {escape(detail)}｜{escape(str(extra))}</text>')
    doors_y = table_y + 20 + ((len(priority) + 1) // 2) * 15 + 18
    lower.append(f'<text x="{ox}" y="{doors_y}" font-size="12" font-weight="700" '
                 f'fill="#111827">门窗洞口表与尺寸链站表（人工测试假设，单位 mm）</text>')
    for i, op in enumerate(presentation["openings"]):
        col, row = i % 2, i // 2
        lower.append(f'<text x="{ox + col*440}" y="{doors_y + 20 + row*15}" '
                     f'font-size="9" fill="#334155">'
                     f'{escape(op["object_id"])} · {op["kind"]} · '
                     f'{_fmt_mm(op["width_mm"])}×{_fmt_mm(op["height_mm"])} · '
                     f'窗台 {_fmt_mm(op["sill_mm"])}</text>')
    station_y = doors_y + 20 + ((len(presentation["openings"]) + 1) // 2) * 15 + 14
    stations = ([("X", s) for s in chains["x"]["stations"]]
                + [("Y", s) for s in chains["y"]["stations"]])
    for i, (axis, st) in enumerate(stations):
        col, row = i % 2, i // 2
        kind = (st["basis"][0].split("｜")[0].split(":")[0]
                if st["basis"] else "unknown")
        lower.append(f'<text x="{ox + col*440}" y="{station_y + 20 + row*15}" '
                     f'font-size="9" fill="{MUTED}">'
                     f'{axis}{st["id"]} @ {_fmt_mm(st["coordinate_mm"])} · '
                     f'Δ{_fmt_mm(st["delta_from_previous_mm"])} · '
                     f'{escape(kind[:18])}</text>')
    note_y = station_y + 20 + ((len(stations) + 1) // 2) * 15 + 12
    lower.append(f'<text x="{ox}" y="{note_y}" font-size="9.5" fill="#b91c1c">'
                 f'尺寸链闭合：ΣΔx={_fmt_mm(chains["x"]["sum_delta_mm"])} / '
                 f'总宽 {_fmt_mm(width)}；ΣΔy={_fmt_mm(chains["y"]["sum_delta_mm"])} / '
                 f'总长 {_fmt_mm(height)}（站点依据见 plan-index.json）</text>')
    lower.append(f'<text x="{ox}" y="{note_y+15}" font-size="9.5" fill="#b91c1c">'
                 f'均为受控人工测试假设，不是现场实测或施工定位尺寸；'
                 f'粗线为围合示意，不是施工墙体。</text>')

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" '
        f'font-family="Microsoft YaHei, Noto Sans SC, sans-serif" '
        f'data-plan-layers-version="{PLAN_LAYERS_VERSION}" '
        f'data-plan-metrics="{ox},{oy},{scale:.9f},{width:.1f},{height:.1f}">',
        '<defs><pattern id="keepout" width="8" height="8" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="8" '
        'stroke="#94a3b8" stroke-width="2"/></pattern></defs>',
        '<rect width="100%" height="100%" fill="#fbfaf7"/>',
        *head,
        f'<g id="layer-geometry">', *geom, '</g>',
        f'<g id="layer-ids">', *ids, '</g>',
        f'<g id="layer-annotations">', *anno, *right, *lower, '</g>',
        '</svg>',
    ]
    return "".join(svg).encode("utf-8")
