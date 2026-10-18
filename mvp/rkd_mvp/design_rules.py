from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from typing import Any

from shapely.geometry import box


RULE_VERSION = "showroom-strip-layout.v1"
DEFAULT_PROGRAM = {
    "scenario": "showroom",
    "boundary_source": "test_parameters_not_site_verified",
    "width": "12", "length": "8", "aisle_width": "1.5",
    "zones": [
        {"zone_id": "reception", "name": "接待区", "min_area_m2": "12"},
        {"zone_id": "display", "name": "展示区", "min_area_m2": "24"},
        {"zone_id": "discussion", "name": "洽谈区", "min_area_m2": "12"},
    ],
}


class DesignError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def number(value: Any, field: str, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation) as error:
        raise DesignError(400, "INVALID_DESIGN_VALUE", f"{field}不是有效数字") from error
    if not result.is_finite() or result < 0 or (positive and result == 0) or result > 100000:
        raise DesignError(400, "INVALID_DESIGN_VALUE", f"{field}超出有效范围")
    # All geometry is stored on a millimetre grid; reject rather than silently move it.
    if result != result.quantize(Decimal("0.001")):
        raise DesignError(400, "INVALID_DESIGN_VALUE", f"{field}最多保留三位小数")
    return result


def text(value: Decimal) -> str:
    return format(value, "f")


def area(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def normalize_program(raw: Any) -> dict:
    if not isinstance(raw, dict) or raw.get("scenario") != "showroom":
        raise DesignError(400, "INVALID_DESIGN_PROGRAM", "当前支持矩形展厅分区场景")
    boundary_source = raw.get("boundary_source")
    if boundary_source not in {"test_parameters_not_site_verified", "manual_boundary_not_site_verified"}:
        raise DesignError(400, "INVALID_DESIGN_PROGRAM", "边界来源必须明确为测试参数或人工草稿")
    width = number(raw.get("width"), "外框宽度", True)
    length = number(raw.get("length"), "外框长度", True)
    aisle = number(raw.get("aisle_width"), "预留通道宽度", True)
    if width > 500 or length > 500 or aisle >= length:
        raise DesignError(400, "INVALID_DESIGN_PROGRAM", "外框最多 500m，通道宽度必须小于外框长度")
    zones = raw.get("zones")
    if not isinstance(zones, list) or not 1 <= len(zones) <= 12:
        raise DesignError(400, "INVALID_DESIGN_PROGRAM", "分区数量必须为 1 至 12")
    normalized = []
    for item in zones:
        if not isinstance(item, dict):
            raise DesignError(400, "INVALID_DESIGN_PROGRAM", "分区格式无效")
        zone_id = str(item.get("zone_id", ""))
        name = str(item.get("name", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", zone_id) or not 1 <= len(name) <= 60:
            raise DesignError(400, "INVALID_DESIGN_PROGRAM", "分区 ID 或名称无效")
        normalized.append({"zone_id": zone_id, "name": name, "min_area_m2": text(number(item.get("min_area_m2"), "最小面积", True))})
    if len({z["zone_id"] for z in normalized}) != len(normalized):
        raise DesignError(400, "DUPLICATE_ZONE_ID", "分区 ID 不能重复")
    return {"scenario": "showroom", "boundary_source": boundary_source, "width": text(width), "length": text(length), "aisle_width": text(aisle), "zones": normalized}


def generate_model(program: dict) -> dict:
    width, length, aisle = (Decimal(program[k]) for k in ("width", "length", "aisle_width"))
    depth = length - aisle
    total_min = sum(Decimal(z["min_area_m2"]) for z in program["zones"])
    if total_min > width * depth:
        raise DesignError(422, "INSUFFICIENT_LAYOUT_AREA", "分区最小面积之和超过通道之外的可用面积")
    minimum_widths = [(Decimal(z["min_area_m2"]) / depth).quantize(Decimal("0.001"), rounding=ROUND_CEILING) for z in program["zones"]]
    extra_width = width - sum(minimum_widths)
    if extra_width < 0:
        raise DesignError(422, "INSUFFICIENT_GRID_AREA", "按毫米精度布置后可用宽度不足，请调整尺寸或最小面积")
    x = Decimal("0")
    zones = []
    for index, z in enumerate(program["zones"]):
        desired = (width * Decimal(z["min_area_m2"]) / total_min).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        available = width - x - sum(minimum_widths[index + 1:])
        allocated = min(available, max(minimum_widths[index], desired))
        end = width if index == len(program["zones"]) - 1 else x + allocated
        zones.append({"zone_id": z["zone_id"], "name": z["name"], "x": text(x), "y": text(aisle), "width": text(end - x), "length": text(depth)})
        x = end
    return validate_model(program, {"width": text(width), "length": text(length), "aisle_width": text(aisle), "zones": zones})[0]


def validate_model(program: dict, raw: Any) -> tuple[dict, dict]:
    if not isinstance(raw, dict):
        raise DesignError(400, "INVALID_DESIGN_MODEL", "布局模型格式无效")
    width, length = Decimal(program["width"]), Decimal(program["length"])
    if number(raw.get("width"), "模型宽度", True) != width or number(raw.get("length"), "模型长度", True) != length:
        raise DesignError(400, "BOUNDARY_MISMATCH", "边界尺寸应在需求中修订后重新生成")
    aisle = number(raw.get("aisle_width"), "通道宽度", True)
    if aisle < Decimal(program["aisle_width"]) or aisle >= length:
        raise DesignError(422, "AISLE_WIDTH", "通道宽度小于需求值或超出边界")
    raw_zones = raw.get("zones")
    required = {z["zone_id"]: z for z in program["zones"]}
    if not isinstance(raw_zones, list) or any(not isinstance(z, dict) for z in raw_zones):
        raise DesignError(400, "INVALID_DESIGN_MODEL", "分区格式无效")
    ids = [z.get("zone_id") for z in raw_zones]
    if any(not isinstance(zone_id, str) for zone_id in ids) or len(ids) != len(required) or set(ids) != set(required):
        raise DesignError(422, "ZONE_SET_MISMATCH", "布局分区必须与需求的稳定对象 ID 一致")
    boundary, aisle_shape = box(0, 0, float(width), float(length)), box(0, 0, float(width), float(aisle))
    prior_shapes, zones = [], []
    total = Decimal("0")
    for z in raw_zones:
        ref = required[z["zone_id"]]
        x, y = number(z.get("x"), "X"), number(z.get("y"), "Y")
        w, d = number(z.get("width"), "分区宽度", True), number(z.get("length"), "分区长度", True)
        shape = box(float(x), float(y), float(x + w), float(y + d))
        if not boundary.covers(shape):
            raise DesignError(422, "ZONE_OUT_OF_BOUNDS", f"{ref['name']}超出外框")
        if shape.intersection(aisle_shape).area > 1e-9:
            raise DesignError(422, "AISLE_BLOCKED", f"{ref['name']}侵占预留通道")
        for other_name, other_shape in prior_shapes:
            if shape.intersection(other_shape).area > 1e-9:
                raise DesignError(422, "ZONE_OVERLAP", f"{ref['name']}与{other_name}重叠")
        if w * d < Decimal(ref["min_area_m2"]):
            raise DesignError(422, "ZONE_AREA_TOO_SMALL", f"{ref['name']}面积小于需求最小值")
        if shape.boundary.intersection(aisle_shape.boundary).length < .001:
            raise DesignError(422, "ZONE_NO_AISLE_ACCESS", f"{ref['name']}未连接预留通道")
        prior_shapes.append((ref["name"], shape))
        total += w * d
        zones.append({"zone_id": ref["zone_id"], "name": ref["name"], "x": text(x), "y": text(y), "width": text(w), "length": text(d), "area_m2": area(w * d), "min_area_m2": ref["min_area_m2"]})
    model = {"schema_version": "showroom-layout.v1", "scenario": "showroom", "boundary_source": program["boundary_source"], "width": text(width), "length": text(length), "aisle_width": text(aisle), "zones": zones,
             "total_area_m2": area(width * length), "zone_area_m2": area(total), "aisle_area_m2": area(width * aisle), "unassigned_area_m2": area(width * (length - aisle) - total)}
    checks = [{"code": code, "status": "passed", "message": message} for code, message in [
        ("BOUNDARY", "分区在矩形边界内"), ("NON_OVERLAP", "分区没有面积重叠"),
        ("AISLE", "连续通道宽度满足本次输入，未被侵占"), ("MIN_AREA", "分区满足最小面积"),
        ("ACCESS", "各分区边界与预留通道连接"), ("OBJECT_IDS", "对象 ID 与需求一致")]]
    return model, {"rule_version": RULE_VERSION, "hard_checks": checks, "professional_checks": [
        {"code": "SITE", "status": "unknown", "message": "实际边界、柱网、出入口和现场条件待专业复核"},
        {"code": "FIRE", "status": "unknown", "message": "通道检查不等于消防、无障碍或疏散合规审核"},
        {"code": "STRUCTURE", "status": "unknown", "message": "分区线不代表墙体，未生成结构或机电构件"}],
        "publication_status": "not_approved"}
