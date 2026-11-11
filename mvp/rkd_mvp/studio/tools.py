"""Tools the agents may call. Tools compute and validate; they never decide design."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
STANDARDS_PATH = ROOT / "knowledge" / "design-standards" / "standards.v1.json"

CATALOG: list[dict] = [
    {"catalog_id": "sofa-3p", "name": "三人沙发", "category": "seat", "w_mm": 2400, "d_mm": 950, "h_mm": 780},
    {"catalog_id": "sofa-2p", "name": "双人沙发", "category": "seat", "w_mm": 1800, "d_mm": 900, "h_mm": 780},
    {"catalog_id": "armchair", "name": "单椅", "category": "seat", "w_mm": 780, "d_mm": 820, "h_mm": 760},
    {"catalog_id": "dining-table", "name": "餐桌 1.9m", "category": "table", "w_mm": 1900, "d_mm": 950, "h_mm": 750},
    {"catalog_id": "round-table", "name": "圆桌 1.2m", "category": "table", "w_mm": 1200, "d_mm": 1200, "h_mm": 750},
    {"catalog_id": "meeting-table", "name": "会议桌 1.9m", "category": "table", "w_mm": 1900, "d_mm": 900, "h_mm": 750},
    {"catalog_id": "coffee-table", "name": "茶几", "category": "table", "w_mm": 1100, "d_mm": 600, "h_mm": 380},
    {"catalog_id": "dining-chair", "name": "餐椅", "category": "seat", "w_mm": 470, "d_mm": 500, "h_mm": 820},
    {"catalog_id": "bar-stool", "name": "吧椅", "category": "seat", "w_mm": 400, "d_mm": 400, "h_mm": 700},
    {"catalog_id": "reception-desk", "name": "接待台", "category": "desk", "w_mm": 700, "d_mm": 1700, "h_mm": 1050},
    {"catalog_id": "bar-counter", "name": "水吧台", "category": "desk", "w_mm": 620, "d_mm": 1800, "h_mm": 950},
    {"catalog_id": "back-cabinet", "name": "备餐柜", "category": "storage", "w_mm": 350, "d_mm": 1800, "h_mm": 2100},
    {"catalog_id": "display-wing", "name": "展墙翼", "category": "display", "w_mm": 450, "d_mm": 2300, "h_mm": 2400},
    {"catalog_id": "pedestal-round", "name": "圆展台", "category": "display", "w_mm": 700, "d_mm": 700, "h_mm": 300},
    {"catalog_id": "display-bench", "name": "展凳", "category": "display", "w_mm": 2400, "d_mm": 420, "h_mm": 420},
    {"catalog_id": "rug", "name": "地毯", "category": "soft", "w_mm": 3000, "d_mm": 2400, "h_mm": 12},
    {"catalog_id": "plant-large", "name": "大绿植", "category": "plant", "w_mm": 700, "d_mm": 700, "h_mm": 1500},
]


def load_standards(tags: list[str] | None = None) -> list[dict]:
    data = json.loads(STANDARDS_PATH.read_text(encoding="utf-8"))
    rules = data["rules"]
    if tags:
        wanted = {t.lower() for t in tags}
        rules = [r for r in rules if wanted & {t.lower() for t in r.get("applies_to", [])}
                 or wanted & {r["id"].lower()}]
    return rules


def _poly_area_mm2(poly: list[list[float]]) -> float:
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _bbox(poly: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _issue(rule: str, severity: str, objects: list[str], message: str, hint: str) -> dict:
    return {"rule_id": rule, "severity": severity, "objects": objects,
            "message": message, "hint": hint}


def check_plan(plan: dict, site: dict) -> dict:
    """Deterministic geometry check. Returns issues + metrics; never says 'good design'.

    Model output is untrusted: a malformed field becomes a structured issue so the
    orchestrator can send the draft back, instead of crashing the whole loop.
    """
    issues: list[dict] = []
    W, H = float(site["width_mm"]), float(site["height_mm"])
    for field, rule in (("zones", "GEO-005"), ("area_table", "GEO-006"),
                        ("circulation", "GEO-007")):
        value = plan.get(field)
        if value is not None and not isinstance(value, list):
            issues.append(_issue(rule, "blocker", [field],
                                 f"{field} 不是数组（实际是 {type(value).__name__}）",
                                 f"{field} 必须写成对象数组，每项是一个对象"))
    raw_zones = plan.get("zones") or []
    zones = []
    for idx, z in enumerate(raw_zones if isinstance(raw_zones, list) else []):
        if not isinstance(z, dict):
            issues.append(_issue("GEO-005", "blocker", [f"zones[{idx}]"],
                                 "分区条目不是对象", "每项都要有 id / name / polygon / area_sqm"))
            continue
        zones.append(z)
    metrics: dict[str, Any] = {"zone_count": len(zones)}

    zone_area_sum = 0.0
    boxes = []
    for z in zones:
        poly = z.get("polygon") or []
        if not isinstance(poly, list) or len(poly) < 3:
            issues.append(_issue("GEO-001", "blocker", [str(z.get("id", "?"))],
                                 "分区轮廓少于 3 个点", "补成闭合多边形"))
            continue
        if not str(z.get("name") or "").strip():
            issues.append(_issue("STD-002", "major", [str(z.get("id", "?"))],
                                 "分区没有名称", "每个分区必须有可读名称"))
        try:
            area = _poly_area_mm2(poly) / 1e6
            x0, y0, x1, y1 = _bbox(poly)
        except Exception:
            issues.append(_issue("GEO-008", "blocker", [str(z.get("id", "?"))],
                                 "轮廓坐标不是数字", "polygon 写成 [[x,y],...]，单位 mm"))
            continue
        declared = _num(z.get("area_sqm"))
        if declared and abs(area - declared) > max(0.5, declared * 0.05):
            issues.append(_issue("GEO-002", "major", [str(z.get("id", "?"))],
                                 f"面积与轮廓不符：声明 {declared:.1f} ㎡，按轮廓算 {area:.1f} ㎡",
                                 "以轮廓为准改 area_sqm"))
        zone_area_sum += area
        if x0 < -1 or y0 < -1 or x1 > W + 1 or y1 > H + 1:
            issues.append(_issue("GEO-003", "blocker", [str(z.get("id", "?"))],
                                 "分区超出场地边界", f"控制在 0–{W:.0f} / 0–{H:.0f} mm 内"))
        boxes.append((str(z.get("id", "?")), x0, y0, x1, y1))

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            ox = min(a[3], b[3]) - max(a[1], b[1])
            oy = min(a[4], b[4]) - max(a[2], b[2])
            if ox > 500 and oy > 500:
                issues.append(_issue("GEO-004", "major", [a[0], b[0]],
                                     f"两个分区范围重叠约 {ox/1000:.1f}×{oy/1000:.1f} m",
                                     "分区不应重叠；如为环游动线请用 circulation 表达"))

    raw_table = plan.get("area_table") or []
    table = []
    for idx, r in enumerate(raw_table if isinstance(raw_table, list) else []):
        if not isinstance(r, dict):
            issues.append(_issue("GEO-006", "blocker", [f"area_table[{idx}]"],
                                 "面积表条目不是对象", '每行写成 {"name":..., "area_sqm":...}'))
            continue
        table.append(r)
    table_sum = sum(_num(r.get("area_sqm")) for r in table)
    metrics.update({"zone_area_sum_sqm": round(zone_area_sum, 1),
                    "area_table_sum_sqm": round(table_sum, 1),
                    "site_area_sqm": round(W * H / 1e6, 1)})
    if table and abs(table_sum - zone_area_sum) > max(2.0, zone_area_sum * 0.03):
        issues.append(_issue("STD-003", "blocker", ["area_table"],
                             f"面积表合计 {table_sum:.1f} ㎡，与分区轮廓合计 {zone_area_sum:.1f} ㎡ 对不上",
                             "补『通道及其他』把差额说明清楚"))

    raw_circ = plan.get("circulation") or []
    for idx, c in enumerate(raw_circ if isinstance(raw_circ, list) else []):
        if not isinstance(c, dict):
            issues.append(_issue("GEO-007", "major", [f"circulation[{idx}]"],
                                 "动线条目不是对象", '写成 {"id":..., "width_mm":..., "path":...}'))
            continue
        w = _num(c.get("width_mm"))
        if w < 1200:
            issues.append(_issue("CIR-001", "major", [str(c.get("id", "?"))],
                                 f"动线净宽 {w:.0f} mm 偏窄", "主通道建议 ≥1200 mm"))

    strategy = plan.get("strategy") if isinstance(plan.get("strategy"), dict) else {}
    nonorth = strategy.get("non_orthogonal") or []
    nonorth = len(nonorth) if isinstance(nonorth, list) else 0
    metrics["non_orthogonal_count"] = nonorth
    if nonorth < 2:
        issues.append(_issue("STD-001", "blocker", ["strategy"],
                             f"非直角元素只有 {nonorth} 处", "至少 2 处：圆角、弧墙或斜置"))

    ceiling = plan.get("ceiling") if isinstance(plan.get("ceiling"), dict) else {}
    coves = ceiling.get("coves") or []
    fixtures = ceiling.get("fixtures") or []
    metrics.update({"cove_count": len(coves) if isinstance(coves, list) else 0,
                    "light_fixture_count": len(fixtures) if isinstance(fixtures, list) else 0})
    if not coves and not fixtures:
        issues.append(_issue("STD-005", "major", ["ceiling"],
                             "天花没有任何造型或灯具点位", "天花不是空白，见 STD-005"))

    return {"ok": not any(i["severity"] == "blocker" for i in issues),
            "issues": issues, "metrics": metrics}


def build_tools(project: dict) -> tuple[list[dict], dict[str, Callable[..., dict]]]:
    """Return (openai tool specs, name -> callable)."""
    site = project["site"]
    requirement = project["requirement"]

    def get_site() -> dict:
        return {"width_mm": site["width_mm"], "height_mm": site["height_mm"],
                "ceiling_mm": site["ceiling_mm"],
                "windows_north": site.get("windows_north"),
                "windows_east": site.get("windows_east"),
                "entrance": site.get("entrance"), "stair": site.get("stair"),
                "bath": site.get("bath"), "columns": site.get("columns"),
                "note": site.get("fixed_note")}

    def get_requirement() -> dict:
        return requirement

    def list_standards(tags: list[str] | None = None) -> dict:
        rules = load_standards(tags)
        return {"rules": [{"id": r["id"], "title": r["title"], "rule": r["rule"],
                           "severity": r["severity"], "checkable": r["checkable"]} for r in rules]}

    def search_catalog(query: str = "", category: str = "") -> dict:
        q = (query or "").lower()
        items = [i for i in CATALOG
                 if (not category or i["category"] == category)
                 and (not q or q in i["name"].lower() or q in i["catalog_id"])]
        return {"items": items[:20]}

    def validate_plan(plan_json: str | dict) -> dict:
        plan = plan_json if isinstance(plan_json, dict) else json.loads(plan_json)
        return check_plan(plan, site)

    handlers = {"get_site": get_site, "get_requirement": get_requirement,
                "list_standards": list_standards, "search_catalog": search_catalog,
                "validate_plan": validate_plan}

    def spec(name: str, desc: str, props: dict, required: list[str]) -> dict:
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}

    tools = [
        spec("get_site", "读取场地条件（尺寸、层高、门窗、入口、保留物、柱）", {}, []),
        spec("get_requirement", "读取老板的需求原文、必须项、约束与已知缺口", {}, []),
        spec("list_standards", "读取公司设计规范（可只取与本角色相关的条目）",
             {"tags": {"type": "array", "items": {"type": "string"},
                       "description": "角色代号，如 D2/D3/R"}}, []),
        spec("search_catalog", "按名称或类别检索家具/展具目录，拿到标准尺寸",
             {"query": {"type": "string"}, "category": {"type": "string"}}, []),
        spec("validate_plan", "对一份空间规划草案做几何与规范校验，返回问题清单与指标",
             {"plan_json": {"type": "string", "description": "草案 JSON 字符串"}}, ["plan_json"]),
    ]
    return tools, handlers
