"""Versioned L1 geometry for AI design candidates.

This geometry engine is deliberately independent from showroom-layout.v1:
it supports an entrance on any side, obstacles, multiple circulation corridors,
functional zones, display objects, and partitions. It does not require every
zone to touch one bottom strip. All checks are deterministic and do not claim
code, fire, accessibility, or construction compliance.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any

from shapely.geometry import Point, box

SCHEMA_VERSION = "rkd-ai-design-option.v1"
RULE_VERSION = "ai-design-geometry.v1"
SUPPORTED_KINDS = {"functional_zone", "display_object", "partition", "entrance_marker", "obstacle"}


class GeometryError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def number(value: Any, field: str, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation, TypeError) as error:
        raise GeometryError(400, "INVALID_GEOMETRY_VALUE", f"{field}不是有效数字") from error
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise GeometryError(400, "INVALID_GEOMETRY_VALUE", f"{field}超出有效范围")
    return result


def text(value: Decimal) -> str:
    return format(value, "f")


def shape_box(shape: dict[str, Any], field: str):
    x, y = number(shape.get("x"), f"{field}.x"), number(shape.get("y"), f"{field}.y")
    width = number(shape.get("width"), f"{field}.width", True)
    length = number(shape.get("length"), f"{field}.length", True)
    return box(float(x), float(y), float(x + width), float(y + length))


def _check(code: str, status: str, message: str) -> dict[str, str]:
    return {"code": code, "status": status, "message": message}


def validate_model(raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise GeometryError(400, "INVALID_DESIGN_MODEL", "候选模型版本无效")
    boundary = raw.get("boundary")
    if not isinstance(boundary, dict):
        raise GeometryError(400, "INVALID_BOUNDARY", "边界格式无效")
    width = number(boundary.get("width"), "边界宽度", True)
    length = number(boundary.get("length"), "边界长度", True)
    if width > 500 or length > 500:
        raise GeometryError(400, "BOUNDARY_TOO_LARGE", "边界超过 500m")
    boundary_shape = box(0, 0, float(width), float(length))
    entrance = boundary.get("entrance")
    if not isinstance(entrance, dict) or entrance.get("side") not in {"left", "right", "top", "bottom"}:
        raise GeometryError(400, "INVALID_ENTRANCE", "入口方向无效")
    point = entrance.get("point")
    if not isinstance(point, list) or len(point) != 2:
        raise GeometryError(400, "INVALID_ENTRANCE", "入口点无效")
    entrance_point = Point(float(number(point[0], "入口 X")), float(number(point[1], "入口 Y")))
    if not boundary_shape.boundary.intersects(entrance_point.buffer(0.001)):
        raise GeometryError(422, "ENTRANCE_OUT_OF_BOUNDS", "入口点不在边界上")
    entrance_width = number(entrance.get("width"), "入口宽度", True)
    if entrance_width < Decimal("0.8"):
        raise GeometryError(422, "ENTRANCE_TOO_NARROW", "入口有效宽度小于 0.8m")

    objects = raw.get("objects")
    if not isinstance(objects, list) or len(objects) < 3:
        raise GeometryError(400, "INVALID_OBJECT_SET", "候选至少应包含三个对象")
    object_shapes: dict[str, Any] = {}
    ids: set[str] = set()
    for obj in objects:
        if not isinstance(obj, dict) or obj.get("kind") not in SUPPORTED_KINDS:
            raise GeometryError(400, "INVALID_OBJECT", "对象类型无效")
        object_id = str(obj.get("object_id", ""))
        if not object_id or object_id in ids:
            raise GeometryError(400, "DUPLICATE_OBJECT_ID", "对象 ID 缺失或重复")
        ids.add(object_id)
        if not isinstance(obj.get("shape"), dict):
            raise GeometryError(400, "INVALID_OBJECT_SHAPE", f"{object_id} 几何格式无效")
        geom = shape_box(obj["shape"], object_id)
        if not boundary_shape.covers(geom):
            raise GeometryError(422, "OBJECT_OUT_OF_BOUNDS", f"{obj.get('name', object_id)} 超出边界")
        object_shapes[object_id] = geom

    obstacles = boundary.get("obstacles")
    if not isinstance(obstacles, list):
        raise GeometryError(400, "INVALID_OBSTACLES", "障碍集合格式无效")
    obstacle_shapes = []
    for obstacle in obstacles:
        geom = shape_box(obstacle.get("shape", {}), "obstacle")
        if not boundary_shape.covers(geom):
            raise GeometryError(422, "OBSTACLE_OUT_OF_BOUNDS", "障碍超出边界")
        obstacle_shapes.append(geom)

    circulation = raw.get("circulation")
    if not isinstance(circulation, dict) or circulation.get("kind") not in {"loop", "branch"}:
        raise GeometryError(400, "INVALID_CIRCULATION", "动线类型无效")
    min_width = number(circulation.get("min_width"), "动线最小宽度", True)
    segments = circulation.get("segments")
    if not isinstance(segments, list) or len(segments) < 2:
        raise GeometryError(400, "INVALID_CIRCULATION", "动线至少包含两个区段")
    segment_shapes: dict[str, Any] = {}
    for segment in segments:
        segment_id = str(segment.get("segment_id", ""))
        geom = shape_box(segment.get("shape", {}), segment_id or "path")
        if not segment_id or segment_id in segment_shapes:
            raise GeometryError(400, "DUPLICATE_PATH_ID", "动线区段 ID 缺失或重复")
        if not boundary_shape.covers(geom):
            raise GeometryError(422, "PATH_OUT_OF_BOUNDS", "动线超出边界")
        if min(Decimal(str(segment["shape"]["width"])), Decimal(str(segment["shape"]["length"]))) < min_width:
            raise GeometryError(422, "PATH_BOTTLENECK", "动线存在窄于配置值的瓶颈")
        segment_shapes[segment_id] = geom
        for obstacle_shape in obstacle_shapes:
            if geom.intersection(obstacle_shape).area > 1e-9:
                raise GeometryError(422, "PATH_BLOCKED_BY_OBSTACLE", "动线被障碍阻断")
    connections = circulation.get("connections")
    if not isinstance(connections, list) or not connections:
        raise GeometryError(400, "PATH_DISCONNECTED", "动线缺少连接关系")
    adjacency: dict[str, set[str]] = {segment_id: set() for segment_id in segment_shapes}
    for pair in connections:
        if not isinstance(pair, list) or len(pair) != 2 or pair[0] not in segment_shapes or pair[1] not in segment_shapes:
            raise GeometryError(400, "INVALID_PATH_CONNECTION", "动线连接引用了不存在的区段")
        first, second = segment_shapes[pair[0]], segment_shapes[pair[1]]
        shared = first.boundary.intersection(second.boundary).length
        overlap = first.intersection(second).area
        if shared < 0.2 and overlap <= 1e-9:
            raise GeometryError(422, "PATH_DISCONNECTED", "动线区段仅有孤立连接或断开")
        adjacency[pair[0]].add(pair[1]); adjacency[pair[1]].add(pair[0])
    visited, stack = set(), [next(iter(segment_shapes))]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node); stack.extend(adjacency[node] - visited)
    if visited != set(segment_shapes):
        raise GeometryError(422, "PATH_DISCONNECTED", "存在不可达动线区段")
    if not any(geom.boundary.intersects(entrance_point.buffer(0.001)) for geom in segment_shapes.values()):
        raise GeometryError(422, "ENTRANCE_NOT_CONNECTED", "入口没有接入动线")
    circulation_union = None
    for geom in segment_shapes.values():
        circulation_union = geom if circulation_union is None else circulation_union.union(geom)

    functional = [obj for obj in objects if obj.get("kind") == "functional_zone"]
    if len(functional) < 3:
        raise GeometryError(400, "FUNCTIONAL_ZONES_REQUIRED", "候选至少应包含三个功能区")
    for obj in objects:
        object_id, geom = obj["object_id"], object_shapes[obj["object_id"]]
        for obstacle_shape in obstacle_shapes:
            if geom.intersection(obstacle_shape).area > 1e-9:
                raise GeometryError(422, "OBJECT_OBSTACLE_OVERLAP", f"{obj['name']} 与障碍冲突")
        if obj.get("kind") in {"display_object", "partition", "entrance_marker"}:
            parent_id = obj.get("parent_object_id")
            if parent_id and parent_id in object_shapes and not object_shapes[parent_id].covers(geom):
                raise GeometryError(422, "CHILD_OUTSIDE_PARENT", f"{obj['name']} 超出所属对象")
            continue
        if circulation_union is not None and geom.intersection(circulation_union).area > 1e-9:
            raise GeometryError(422, "ZONE_BLOCKS_CIRCULATION", f"{obj['name']} 侵占动线")
        if circulation_union is not None and geom.boundary.intersection(circulation_union.boundary).length < 0.5:
            raise GeometryError(422, "ZONE_NO_PATH_ACCESS", f"{obj['name']} 没有足够的动线连接区段")
        min_area = Decimal(str(obj.get("min_area_m2", "1")))
        if Decimal(str(obj["shape"]["width"])) * Decimal(str(obj["shape"]["length"])) < min_area:
            raise GeometryError(422, "ZONE_AREA_TOO_SMALL", f"{obj['name']} 面积小于需求")
    for index, first in enumerate(objects):
        if first.get("kind") not in {"functional_zone", "entrance_marker"}:
            continue
        for second in objects[index + 1:]:
            if second.get("kind") not in {"functional_zone", "entrance_marker"}:
                continue
            if object_shapes[first["object_id"]].intersection(object_shapes[second["object_id"]]).area > 1e-9:
                raise GeometryError(422, "OBJECT_OVERLAP", f"{first['name']} 与 {second['name']} 重叠")

    checks = [
        _check("BOUNDARY", "passed", "边界、对象与动线均在声明范围内"),
        _check("OBSTACLES", "passed", "对象与动线避让已声明障碍"),
        _check("NON_OVERLAP", "passed", "功能区之间无面积重叠"),
        _check("PATH_CONNECTED", "passed", "动线区段连接且入口可达"),
        _check("PATH_WIDTH", "passed", "动线瓶颈宽度满足本次输入"),
        _check("ZONE_ACCESS", "passed", "各功能区具有足够的动线连接区段"),
        _check("MIN_AREA", "passed", "功能区满足声明的最小面积"),
        _check("OBJECT_IDS", "passed", "对象 ID 稳定且唯一"),
    ]
    professional = [
        _check("SITE", "unknown", "几何边界为测试或人工参数，未经现场核验"),
        _check("FIRE", "unknown", "通路检查不等于消防、疏散或无障碍合规"),
        _check("STRUCTURE", "unknown", "分区不是墙体或专业构件，未生成施工图"),
    ]
    validation = {"rule_version": RULE_VERSION, "status": "passed", "hard_checks": checks,
                  "professional_checks": professional, "publication_status": "not_approved"}
    return raw, validation


def structure_signature(model: dict[str, Any]) -> dict[str, Any]:
    objects = []
    for obj in model.get("objects", []):
        if obj.get("kind") not in {"functional_zone", "display_object", "partition", "entrance_marker"}:
            continue
        shape = obj["shape"]
        objects.append({
            "object_id": obj["object_id"], "kind": obj["kind"],
            "x": str(number(shape["x"], "x")), "y": str(number(shape["y"], "y")),
            "width": str(number(shape["width"], "width")), "length": str(number(shape["length"], "length")),
            "material_id": obj.get("material_id"),
        })
    circulation = model.get("circulation", {})
    return {
        "entrance_side": model.get("boundary", {}).get("entrance", {}).get("side"),
        "path_kind": circulation.get("kind"),
        "segment_count": len(circulation.get("segments", [])),
        "objects": sorted(objects, key=lambda item: item["object_id"]),
        "relationships": sorted(f"{item.get('type')}:{item.get('source')}->{item.get('target')}"
                                for item in model.get("relationships", [])),
    }


def candidates_are_structurally_different(first: dict[str, Any], second: dict[str, Any]) -> bool:
    a, b = structure_signature(first), structure_signature(second)
    return a != b


def render_svg(model: dict[str, Any]) -> bytes:
    """Draw a concept plan the way a real designer's floor plan reads.

    Walls, a recessed entrance, a service counter, real furniture outlines,
    partitions, a visual focus, dimensions, a legend and a title block are all
    derived from the versioned model objects and their ``properties``. This is
    still a concept plan: it never claims to be a construction drawing.
    """
    boundary = model["boundary"]
    width = float(number(boundary["width"], "width", True))
    length = float(number(boundary["length"], "length", True))
    scale = min(58.0, 700.0 / max(width, 1.0), 430.0 / max(length, 1.0))
    ml, mt, legend_w, mr, title_h, mb = 48.0, 58.0, 196.0, 24.0, 66.0, 16.0
    pw, ph = width * scale, length * scale
    w, h = ml + pw + mr + legend_w, mt + ph + title_h + mb
    strategy = model.get("strategy", {})
    strategy_id = escape(str(strategy.get("strategy_id", "concept"))[:40])
    source_kind = escape(str(model.get("source_kind", "unknown")))
    role_fill = {"foyer": "#f3f0e8", "primary_display": "#eef2f4", "deep_talk": "#f0ece6",
                 "buffer": "#f6f7f5", "service": "#eceef0"}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.2f} {h:.2f}" role="img" aria-label="真实模型概念平面">',
        '<defs>',
        '<pattern id="floorHatch" width="0.24" height="0.24" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="0.24" stroke="#d8dee3" stroke-width="0.012"/></pattern>',
        '<pattern id="islandHatch" width="0.18" height="0.18" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="0.18" stroke="#9aa8b4" stroke-width="0.02"/></pattern>',
        '<marker id="flowArrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="5" markerHeight="5" orient="auto">'
        '<path d="M0,0 L8,4 L0,8 z" fill="#8a6a3c"/></marker>',
        '</defs>',
        f'<rect width="{w:.2f}" height="{h:.2f}" fill="#ffffff"/>',
        f'<rect x="10" y="10" width="{w - 20:.2f}" height="{h - 20:.2f}" fill="none" stroke="#c9d2da" stroke-width="1"/>',
        # Overall dimension lines, in metres.
        f'<line x1="{ml}" y1="{mt - 16}" x2="{ml + pw:.2f}" y2="{mt - 16}" stroke="#7c8894" stroke-width="0.7"/>',
        f'<text x="{ml + pw / 2:.2f}" y="{mt - 21}" text-anchor="middle" font-size="10" fill="#4c5a68">{width:g} m</text>',
        f'<line x1="{ml - 18}" y1="{mt}" x2="{ml - 18}" y2="{mt + ph:.2f}" stroke="#7c8894" stroke-width="0.7"/>',
        f'<text x="{ml - 23}" y="{mt + ph / 2:.2f}" text-anchor="middle" font-size="10" fill="#4c5a68" transform="rotate(-90 {ml - 23} {mt + ph / 2:.2f})">{length:g} m</text>',
        f'<g transform="translate({ml},{mt}) scale({scale})">',
        f'<rect x="0" y="0" width="{width}" height="{length}" fill="#fdfdfc"/>',
        f'<rect x="0" y="0" width="{width}" height="{length}" fill="url(#floorHatch)" opacity="0.5"/>',
    ]
    # Circulation: pale corridors with a dashed directional centre line.
    circulation = model.get("circulation", {})
    for segment in circulation.get("segments", []):
        shape = segment["shape"]
        x, y = float(shape["x"]), float(shape["y"])
        sw, sl = float(shape["width"]), float(shape["length"])
        parts.append(f'<rect x="{x}" y="{y}" width="{sw}" height="{sl}" fill="#e9eef1" stroke="#cdd6dc" stroke-width="0.012"/>')
        if sw >= sl:
            parts.append(f'<line x1="{x + 0.15:.3f}" y1="{y + sl / 2:.3f}" x2="{x + sw - 0.15:.3f}" y2="{y + sl / 2:.3f}" '
                         f'stroke="#b08a52" stroke-width="0.018" stroke-dasharray="0.16 0.12" marker-end="url(#flowArrow)"/>')
        else:
            parts.append(f'<line x1="{x + sw / 2:.3f}" y1="{y + 0.15:.3f}" x2="{x + sw / 2:.3f}" y2="{y + sl - 0.15:.3f}" '
                         f'stroke="#b08a52" stroke-width="0.018" stroke-dasharray="0.16 0.12" marker-end="url(#flowArrow)"/>')
    # Functional zones: quiet material fills with Chinese labels and area.
    for obj in model.get("objects", []):
        if obj.get("kind") != "functional_zone":
            continue
        shape = obj["shape"]
        x, y = float(shape["x"]), float(shape["y"])
        ow, ol = float(shape["width"]), float(shape["length"])
        props = obj.get("properties") or {}
        role = str(props.get("zone_role") or "primary_display")
        fill = role_fill.get(role, "#f2f4f5")
        parts.append(f'<rect x="{x}" y="{y}" width="{ow}" height="{ol}" fill="{fill}" stroke="#9aa6b1" stroke-width="0.014"/>')
        label = escape(str(obj.get("name", obj["object_id"]))[:22])
        area = ow * ol
        font = min(0.24, max(0.11, ow / max(5.0, len(label) * 0.8)))
        # Zone name at the top, area at the bottom; the middle stays free for
        # furniture outlines instead of stacking overlapping labels.
        parts.append(f'<text x="{x + ow / 2:.3f}" y="{y + 0.32:.3f}" text-anchor="middle" font-size="{font:.3f}" fill="#2b3a49">{label}</text>')
        parts.append(f'<text x="{x + ow / 2:.3f}" y="{y + ol - 0.16:.3f}" text-anchor="middle" font-size="0.15" fill="#71808e">{area:.1f} m²</text>')
        if props.get("sequence_role"):
            parts.append(f'<text x="{x + ow - 0.08:.3f}" y="{y + 0.62:.3f}" text-anchor="end" font-size="0.13" fill="#8a6a3c">{escape(str(props["sequence_role"]))}</text>')
    # Walls / screens and obstacles.
    for obj in model.get("objects", []):
        if obj.get("kind") != "partition":
            continue
        shape = obj["shape"]
        x, y = float(shape["x"]), float(shape["y"])
        ow, ol = float(shape["width"]), float(shape["length"])
        parts.append(f'<rect x="{x}" y="{y}" width="{ow}" height="{ol}" fill="#4e5b66" stroke="#34414c" stroke-width="0.012"/>')
        props = obj.get("properties") or {}
        if props.get("wall_type") == "curved_intent":
            parts.append(f'<path d="M {x + ow / 2:.3f} {y:.3f} Q {x + ow / 2 + 0.5:.3f} {y + ol / 2:.3f} {x + ow / 2:.3f} {y + ol:.3f}" '
                         f'fill="none" stroke="#4e5b66" stroke-width="0.03"/>')
    for obstacle in boundary.get("obstacles", []):
        shape = obstacle["shape"]
        parts.append(f'<rect x="{float(shape["x"])}" y="{float(shape["y"])}" width="{float(shape["width"])}" '
                     f'height="{float(shape["length"])}" fill="#606b76" stroke="#34414c" stroke-width="0.02"/>')
    # Furniture and展具 outlines, driven by furniture_type / focal flag.
    for obj in model.get("objects", []):
        if obj.get("kind") != "display_object":
            continue
        shape = obj["shape"]
        x, y = float(shape["x"]), float(shape["y"])
        ow, ol = float(shape["width"]), float(shape["length"])
        props = obj.get("properties") or {}
        ftype = str(props.get("furniture_type") or "display_case")
        cx, cy = x + ow / 2, y + ol / 2
        if ftype in {"table_chairs", "sofa"}:
            parts.append(f'<rect x="{x + ow * 0.18:.3f}" y="{y + ol * 0.28:.3f}" width="{ow * 0.64:.3f}" height="{ol * 0.44:.3f}" '
                         f'rx="0.08" fill="#ffffff" stroke="#5d6a76" stroke-width="0.018"/>')
            for dx, dy in ((0.12, 0.12), (0.88, 0.12), (0.12, 0.88), (0.88, 0.88), (0.5, 0.1), (0.5, 0.9)):
                parts.append(f'<circle cx="{x + ow * dx:.3f}" cy="{y + ol * dy:.3f}" r="{min(ow, ol) * 0.09:.3f}" fill="none" stroke="#5d6a76" stroke-width="0.016"/>')
        elif ftype == "plant":
            parts.append(f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{min(ow, ol) * 0.42:.3f}" fill="#dfe9dc" stroke="#6f8a6b" stroke-width="0.018"/>')
            parts.append(f'<circle cx="{cx - 0.1:.3f}" cy="{cy - 0.08:.3f}" r="0.06" fill="#8ba685"/>')
            parts.append(f'<circle cx="{cx + 0.12:.3f}" cy="{cy + 0.1:.3f}" r="0.05" fill="#8ba685"/>')
        elif ftype in {"storage", "pantry"}:
            parts.append(f'<rect x="{x}" y="{y}" width="{ow}" height="{ol}" fill="#e7eaec" stroke="#5d6a76" stroke-width="0.018"/>')
            parts.append(f'<line x1="{x}" y1="{y}" x2="{x + ow:.3f}" y2="{y + ol:.3f}" stroke="#aab4bd" stroke-width="0.012"/>')
        elif ftype == "light_feature":
            parts.append(f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{min(ow, ol) * 0.4:.3f}" fill="none" stroke="#b89352" stroke-width="0.02" stroke-dasharray="0.1 0.08"/>')
        else:
            parts.append(f'<rect x="{x}" y="{y}" width="{ow}" height="{ol}" fill="url(#islandHatch)" stroke="#5d6a76" stroke-width="0.02"/>')
        if ftype == "reception_desk":
            for index in range(3):
                parts.append(f'<circle cx="{x + ow * (0.2 + index * 0.3):.3f}" cy="{y + ol + 0.16:.3f}" r="0.09" fill="none" stroke="#5d6a76" stroke-width="0.016"/>')
        if props.get("focal"):
            parts.append(f'<rect x="{x - 0.1:.3f}" y="{y - 0.1:.3f}" width="{ow + 0.2:.3f}" height="{ol + 0.2:.3f}" '
                         f'fill="none" stroke="#a8732f" stroke-width="0.03" stroke-dasharray="0.12 0.06"/>')
        # Real floor plans label furniture by symbol and legend, not by stacking
        # a text label on every chair. Only the visual focus gets a short tag.
        if props.get("focal"):
            label = escape(str(obj.get("name", "视觉焦点"))[:12])
            parts.append(f'<text x="{cx:.3f}" y="{y + ol + 0.24:.3f}" text-anchor="middle" font-size="0.15" fill="#a8732f">{label}</text>')
    # Entrance markers and a recessed entrance door with a swing arc.
    for obj in model.get("objects", []):
        if obj.get("kind") != "entrance_marker":
            continue
        shape = obj["shape"]
        x, y = float(shape["x"]), float(shape["y"])
        ow, ol = float(shape["width"]), float(shape["length"])
        parts.append(f'<rect x="{x}" y="{y}" width="{ow}" height="{ol}" fill="#f7f2e7" stroke="#8a6a3c" stroke-width="0.02"/>')
        parts.append(f'<text x="{x + ow / 2:.3f}" y="{y + ol / 2:.3f}" text-anchor="middle" font-size="0.14" fill="#8a6a3c">门斗</text>')
    entrance = boundary["entrance"]
    ex, ey = float(entrance["point"][0]), float(entrance["point"][1])
    side = str(entrance.get("side", "left"))
    door = 0.9
    if side in {"left", "right"}:
        dx = 0 if side == "left" else width
        parts.append(f'<rect x="{dx - 0.12:.3f}" y="{ey - door / 2:.3f}" width="0.24" height="{door}" fill="#ffffff"/>')
        direction = 1 if side == "left" else -1
        parts.append(f'<line x1="{dx:.3f}" y1="{ey - door / 2:.3f}" x2="{dx + direction * door:.3f}" y2="{ey - door / 2:.3f}" stroke="#354557" stroke-width="0.025"/>')
        parts.append(f'<path d="M {dx + direction * door:.3f} {ey - door / 2:.3f} A {door} {door} 0 0 {1 if side == "left" else 0} {dx:.3f} {ey + door / 2:.3f}" '
                     f'fill="none" stroke="#8a9aa8" stroke-width="0.014" stroke-dasharray="0.08 0.06"/>')
        label_x = 0.35 if side == "left" else width - 0.35
        anchor = "start" if side == "left" else "end"
        parts.append(f'<text x="{label_x:.3f}" y="{ey + door / 2 + 0.45:.3f}" text-anchor="{anchor}" font-size="0.2" fill="#8f3b2c">主入口 MAIN ENTRY</text>')
    else:
        dy = 0 if side == "bottom" else length
        parts.append(f'<rect x="{ex - door / 2:.3f}" y="{dy - 0.12:.3f}" width="{door}" height="0.24" fill="#ffffff"/>')
        parts.append(f'<text x="{ex:.3f}" y="{dy + 0.5:.3f}" text-anchor="middle" font-size="0.2" fill="#8f3b2c">主入口 MAIN ENTRY</text>')
    # Structural boundary drawn last, as a thick double line.
    parts.append(f'<rect x="0" y="0" width="{width}" height="{length}" fill="none" stroke="#2f3b46" stroke-width="0.075"/>')
    parts.append(f'<rect x="0.12" y="0.12" width="{width - 0.24}" height="{length - 0.24}" fill="none" stroke="#2f3b46" stroke-width="0.016"/>')
    parts.append('</g>')
    # North arrow.
    # Keep the north arrow inside the legend column, clear of its heading.
    nx, ny = ml + pw + mr + legend_w - 34, mt + ph - 54
    parts.append(f'<circle cx="{nx}" cy="{ny + 14}" r="14" fill="#ffffff" stroke="#7c8894" stroke-width="1"/>')
    parts.append(f'<path d="M {nx} {ny + 2} L {nx - 5} {ny + 22} L {nx} {ny + 18} L {nx + 5} {ny + 22} Z" fill="#354557"/>')
    parts.append(f'<text x="{nx}" y="{ny - 4}" text-anchor="middle" font-size="10" fill="#354557">N</text>')
    # Legend panel.
    lx = ml + pw + mr
    parts.append(f'<text x="{lx}" y="{mt + 4}" font-size="12" font-weight="600" fill="#2b3a49">图例 LEGEND</text>')
    legend = [
        ("#2f3b46", "墙体 / 结构", "solid"),
        ("#e9eef1", "主通道 / 动线", "solid"),
        ("#f3f0e8", "前厅形象区", "solid"),
        ("#eef2f4", "主展示区", "solid"),
        ("#f0ece6", "深度洽谈区", "solid"),
        ("#4e5b66", "片墙 / 隔断", "solid"),
        ("#f7f2e7", "入口门斗", "solid"),
        ("#dfe9dc", "景观绿植", "solid"),
    ]
    for index, (color, label, _) in enumerate(legend):
        y = mt + 22 + index * 20
        parts.append(f'<rect x="{lx}" y="{y}" width="16" height="11" fill="{color}" stroke="#8b98a4" stroke-width="0.7"/>')
        parts.append(f'<text x="{lx + 23}" y="{y + 10}" font-size="10.5" fill="#43536a">{label}</text>')
    note_y = mt + 22 + len(legend) * 20 + 8
    parts.append(f'<text x="{lx}" y="{note_y}" font-size="10" fill="#8a6836">概念平面 · 非施工图</text>')
    parts.append(f'<text x="{lx}" y="{note_y + 15}" font-size="10" fill="#8a6836">几何边界为测试参数</text>')
    parts.append(f'<text x="{lx}" y="{note_y + 30}" font-size="10" fill="#8a6836">专业复核：待办</text>')
    # Title block.
    ty = mt + ph + 18
    parts.append(f'<line x1="{ml}" y1="{ty - 8}" x2="{w - 24:.2f}" y2="{ty - 8}" stroke="#c9d2da" stroke-width="1"/>')
    parts.append(f'<text x="{ml}" y="{ty + 8}" font-size="13" font-weight="600" fill="#2b3a49">室内展厅概念平面 · CONCEPT FLOOR PLAN</text>')
    parts.append(f'<text x="{ml}" y="{ty + 26}" font-size="10.5" fill="#5c6b79">方案 {strategy_id} · 来源 {source_kind} · 比例 1:100（示意） · 单位 mm / 标注 m</text>')
    parts.append(f'<text x="{ml}" y="{ty + 42}" font-size="10" fill="#8a6836">设计由真实模型完成，程序负责几何校验与制图；未通过专业审签，不用于施工。</text>')
    parts.append('</svg>')
    return "\n".join(parts).encode("utf-8")


def object_diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    old = {item["object_id"]: item for item in before.get("objects", [])}
    new = {item["object_id"]: item for item in after.get("objects", [])}
    changes: list[dict[str, Any]] = []
    for object_id in sorted(set(old) | set(new)):
        if object_id not in old:
            changes.append({"object_id": object_id, "field": "object", "before": None, "after": new[object_id], "reason": "新增对象"})
        elif object_id not in new:
            changes.append({"object_id": object_id, "field": "object", "before": old[object_id], "after": None, "reason": "移除对象"})
        else:
            for field in ("shape", "material_id", "locked", "properties"):
                if old[object_id].get(field) != new[object_id].get(field):
                    changes.append({"object_id": object_id, "field": field, "before": old[object_id].get(field),
                                    "after": new[object_id].get(field), "reason": "反馈驱动的候选修订"})
    for field in ("entrance", "kind", "min_width"):
        old_value = before.get("boundary", {}).get(field, before.get("circulation", {}).get(field))
        new_value = after.get("boundary", {}).get(field, after.get("circulation", {}).get(field))
        if old_value != new_value:
            changes.append({"object_id": "boundary" if field == "entrance" else "circulation", "field": field,
                            "before": old_value, "after": new_value, "reason": "反馈驱动的候选修订"})
    return changes
