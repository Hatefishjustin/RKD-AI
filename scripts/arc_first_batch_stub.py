"""LOCAL MODEL STUB DATA for the ARC first-batch engineering checks.

!! THIS IS NOT AN AI DESIGN RESULT AND NOT A HUMAN-WRITTEN DESIGN SCHEME !!
These are deterministic, explicitly-labelled test fixtures that stand in for a
model channel so the ENGINEERING loop (contract -> geometry -> feedback ->
version -> gate) can be exercised without any external call or key. They prove
flow control only. No design value is claimed, AD01-AD08 are untouched.

The area table is computed from geometry (shoelace / shapely union), matching
the single program-computed accounting basis in studio/geometry.py.
"""
from __future__ import annotations

import copy
import json
from typing import Any

SITE = {
    "width_mm": 26170, "height_mm": 17920, "ceiling_mm": 3000,
    "source": "阶段1 底图（DXF 26169.58×17920.17 与 A3 尺寸链一致）",
    "windows_north": [[2688, 8154], [8778, 14228], [14867, 20317]],
    "windows_east": [[231, 3037], [5742, 8273]],
    "entrance": [0, 10300, 1800],
    "stair": [0, 0, 2400, 8000],
    "bath": [22000, 2600, 26170, 7300],
    "columns": 0,
    "fixed_note": "楼梯、卫生间湿区、北向与东向窗带保留；未发现结构柱。",
}

REQUIREMENT = {
    "text": "这是我们集团的样品展厅，要做成能带客户看、能坐下来谈的地方，不要像仓库摆货。"
            "第一眼进来要看到品牌，然后要有一条能一路看过去的产品序列，中间要有一个能停下来的重点。"
            "客户来谈事要有安静的洽谈空间。前台和茶水要有，楼梯和卫生间保留不动。",
    "must_have": ["品牌第一眼", "产品序列", "一个可以停下来的重点展台", "洽谈空间",
                  "前台接待 + 茶水服务", "保留楼梯与卫生间"],
    "constraints": {"budget_cny": 600000, "budget_note": "含税；机电与消防改造不在范围内",
                    "ceiling_mm": 3000, "style": "现代轻奢，暖木 + 哑光金属",
                    "existing_rooms_to_keep": ["楼梯（西南 2.4×8.0m）", "卫生间湿区"]},
    "unknowns": ["协诚的主营产品清单（资料里没有，展品只能做示意）"],
}

# zone layouts are genuinely different (topology / position / sizes), not a rename
_LAYOUTS: dict[str, list[dict]] = {
    "A": [
        {"id": "ZA1", "name": "品牌序厅", "role": "arrival",
         "polygon": [[0, 8600], [5400, 8600], [5400, 13500], [1600, 13500], [0, 11900]]},
        {"id": "ZA2", "name": "中央中岛", "role": "island",
         "polygon": [[9000, 6200], [16000, 6200], [16000, 11000], [9000, 11000]]},
        {"id": "ZA3", "name": "北光廊", "role": "gallery",
         "polygon": [[5400, 13300], [21800, 13300], [21800, 17700], [5400, 17700]]},
        {"id": "ZA4", "name": "南生活场景", "role": "scene",
         "polygon": [[5400, 1800], [20400, 1800], [20400, 5200], [5400, 5200]]},
        {"id": "ZA5", "name": "东洽谈", "role": "meeting",
         "polygon": [[19400, 7600], [26100, 7600], [26100, 13300], [19400, 13300]]},
        {"id": "ZA6", "name": "水吧服务", "role": "service",
         "polygon": [[2400, 1800], [5400, 1800], [5400, 6100], [2400, 6100]]},
    ],
    "B": [
        {"id": "ZB1", "name": "入口门厅", "role": "arrival",
         "polygon": [[0, 8600], [4200, 8600], [4200, 13500], [1200, 13500], [0, 12300]]},
        {"id": "ZB2", "name": "一轴主展", "role": "gallery",
         "polygon": [[4200, 8500], [17500, 8500], [17500, 14000], [4200, 14000]]},
        {"id": "ZB3", "name": "东端中岛", "role": "island",
         "polygon": [[18300, 7800], [24000, 7800], [24000, 11500], [18300, 11500]]},
        {"id": "ZB4", "name": "南场景带", "role": "scene",
         "polygon": [[4200, 1800], [17500, 1800], [17500, 7600], [4200, 7600]]},
        {"id": "ZB5", "name": "北洽谈", "role": "meeting",
         "polygon": [[17500, 14200], [26100, 14200], [26100, 17700], [17500, 17700]]},
        {"id": "ZB6", "name": "茶水服务", "role": "service",
         "polygon": [[2400, 1800], [4200, 1800], [4200, 6100], [2400, 6100]]},
    ],
}

_ROUTES = {
    "A": [[100, 11000], [8000, 11000], [17500, 11000], [17500, 6000], [8000, 5200]],
    "B": [[100, 11000], [4200, 11000], [12000, 11000], [20000, 11000], [21000, 9500]],
}


def _shoelace(poly: list[list[float]]) -> float:
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0 / 1e6


def design_scope_sqm() -> float:
    site = round(SITE["width_mm"] * SITE["height_mm"] / 1e6, 3)
    stair = (SITE["stair"][2] - SITE["stair"][0]) * (SITE["stair"][3] - SITE["stair"][1]) / 1e6
    bath = (SITE["bath"][2] - SITE["bath"][0]) * (SITE["bath"][3] - SITE["bath"][1]) / 1e6
    return round(site - stair - bath, 3)


def valid_proposal(option: str = "A") -> dict:
    """A contract-compliant MODEL PROPOSAL (no identity / decision fields)."""
    zones = copy.deepcopy(_LAYOUTS[option])
    for z in zones:
        z["area_sqm"] = round(_shoelace(z["polygon"]), 3)
    functional = round(sum(z["area_sqm"] for z in zones), 3)
    unallocated = round(design_scope_sqm() - functional, 3)
    return {
        "strategy": {
            "name": "环岛漫游" if option == "A" else "一轴到底",
            "narrative": ("进门先被斜切品牌墙引到中央，再绕着中岛走一圈看完产品序列，"
                          "最后在南侧坐下洽谈；东侧玻璃隔断放深度洽谈。"
                          if option == "A" else
                          "从入口沿一条主轴一路看过去，东端中岛作为可停下来的高潮，"
                          "南侧是连续生活场景带，北侧留给安静洽谈。"),
            "tradeoffs": ["主展台居中，四周都能看" if option == "A" else "主轴清晰，序列感强",
                          "环游占掉较多通道面积" if option == "A" else "横向分格较多"],
            "non_orthogonal": [f"{zones[0]['id']}:入口斜切品牌墙", "P1:三级圆角中岛"],
        },
        "zones": zones,
        "circulation": [{"id": f"C{option}1", "width_mm": 2000,
                         "path": copy.deepcopy(_ROUTES[option])}],
        "platforms": [{"id": "P1", "name": "中央圆角中岛" if option == "A" else "东端圆角中岛",
                       "kind": "rounded", "corner_radius_mm": 1180, "height_mm": 720,
                       "polygon": ([[9000, 6200], [16000, 6200], [16000, 11000], [9000, 11000]]
                                   if option == "A" else
                                   [[18300, 7800], [24000, 7800], [24000, 11500], [18300, 11500]])}],
        "ceiling": {
            "strategy": "环形灯槽洗台面，北光廊轨道射灯洗翼墙",
            "coves": [{"id": "CV1", "band_mm": 200, "kelvin": 2700,
                       "polygon": ([[8400, 5600], [16600, 5600], [16600, 11600], [8400, 11600]]
                                   if option == "A" else
                                   [[18100, 7400], [24200, 7400], [24200, 11700], [18100, 11700]])}],
            "fixtures": [
                {"id": "L1", "type": "spot", "x": 10250, "y": 7700, "kelvin": 2700},
                {"id": "L2", "type": "spot", "x": 14750, "y": 7700, "kelvin": 3000},
                {"id": "L3", "type": "downlight", "x": 13000, "y": 14500, "kelvin": 3000},
            ],
        },
        "furniture": [
            {"id": "F1", "catalog_id": "sofa-3p", "x": 8400, "y": 4050, "rot": 0},
            {"id": "F2", "catalog_id": "dining-table", "x": 14400, "y": 3300, "rot": 0},
            {"id": "F3", "catalog_id": "display-wing", "x": 9500, "y": 16350, "rot": -12},
        ],
        "area_table": ([{"name": z["name"], "area_sqm": z["area_sqm"]} for z in zones]
                       + [{"name": "通道及其他/未分配", "area_sqm": unallocated}]),
        "open_questions": ["协诚的产品清单缺失，展品只能做示意"],
        "standards_cited": ["STD-001", "STD-003", "STD-005"],
    }


def review_issues() -> list[dict]:
    """Structured review: each issue names a real object id."""
    return [
        {"issue_id": "I1", "candidate": "A", "severity": "major",
         "objects": ["CA1"], "rule_id": "CIR-001",
         "evidence": "主动线声明净宽 2000mm，但南段缺少收口",
         "suggest": "把主动线净宽调到 2100mm 并复核瓶颈"},
        {"issue_id": "I2", "candidate": "A", "severity": "major",
         "objects": ["F3"], "rule_id": "STD-001",
         "evidence": "展墙翼斜置 -12°，与斜切品牌墙不成同一轴线",
         "suggest": "把展墙翼旋到 -15° 形成连续斜线"},
        {"issue_id": "I3", "candidate": "B", "severity": "minor",
         "objects": ["ZB5"], "rule_id": "STD-004",
         "evidence": "北洽谈区没有对应视线",
         "suggest": "本轮只深化 A，B 保持候选"},
        {"issue_id": "I4", "candidate": "A", "severity": "minor",
         "objects": ["L1"], "rule_id": "STD-005",
         "evidence": "重点射灯色温未统一",
         "suggest": "把 L1 色温统一到 3000K"},
        {"issue_id": "I5", "candidate": "A", "severity": "minor",
         "objects": ["CV1"], "rule_id": "STD-005",
         "evidence": "环形灯槽色温未标注统一值",
         "suggest": "把 CV1 色温统一到 3000K"},
    ]


def revision_payload(issues: list[dict] | None = None) -> dict:
    """Whitelisted patch + per-issue responses (the preferred revision path)."""
    issues = issues or review_issues()
    responses = []
    for i in issues:
        accept = i["issue_id"] != "I3"
        responses.append({
            "issue_id": i["issue_id"],
            "action": "accept" if accept else "reject",
            "change": i["suggest"] if accept else "",
            "reason": "" if accept else "B 不在本轮深化范围，保留为可比较候选",
        })
    patch = [
        {"op": "update", "group": "circulation", "id": "CA1",
         "fields": {"width_mm": 2100}},
        {"op": "update", "group": "furniture", "id": "F3", "fields": {"rot": -15}},
        {"op": "update", "group": "ceiling.fixtures", "id": "L1",
         "fields": {"kelvin": 3000}},
        {"op": "update", "group": "ceiling.coves", "id": "CV1",
         "fields": {"kelvin": 3000}},
    ]
    return {"responses": responses, "patch": patch}


def as_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
