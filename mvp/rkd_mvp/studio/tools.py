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

    ARC-02: this now delegates to geometry.check_geometry(), which uses the
    project's locked shapely engine for real polygon validity / intersections /
    keep-out / route bottlenecks and a single area-reconciliation basis. The old
    bounding-box overlap and self-reported width checks were demonstrably wrong
    (see var/evidence/architecture-handoff/first-batch/before/reproduction.json).
    Signature and ok/issues/metrics shape stay compatible with A1's _qc().
    Model self-check via the validate_plan tool uses this same implementation.
    """
    from .geometry import check_geometry

    catalog = {c["catalog_id"]: c for c in CATALOG}
    result = check_geometry(plan, site, catalog=catalog)
    return {"ok": result["ok"], "issues": result["issues"],
            "metrics": result["metrics"], "checks": result["checks"]}


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
