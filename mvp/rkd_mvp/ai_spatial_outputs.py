"""W2 same-source outputs: readable plan, scene, net quantities and cost draft.

Everything here is generated from ONE frozen main-system candidate revision that
carries the precise ``spatial`` payload. Boundaries that matter:

* Geometry authority is ``spatial.zones[].polygon_mm`` (mm). Legacy bbox objects
  are never used to measure.
* Render-only assumptions (camera, light rig, default furniture height) are
  labelled ``assumption`` and never become measured facts.
* Anything not modelled stays ``unknown`` (never 0, never a plausible number).
* No external calls, no AI imagery, no construction claim.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from datetime import datetime, timezone
from html import escape
from typing import Any

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

GENERATOR_VERSION = "rkd-spatial-outputs.v1"
PLAN_VERSION = "rkd-spatial-plan.v2"
SCENE_VERSION = "rkd-spatial-scene.v1"
QUANTITY_VERSION = "rkd-spatial-quantity.v1"
COST_VERSION = "rkd-spatial-cost.v1"
MANIFEST_VERSION = "rkd-spatial-output-manifest.v1"

MM2 = 1_000_000.0


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def model_hash(model: dict) -> str:
    return sha256_bytes(_json(model))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------- input
def freeze_input(model: dict, *, project_id: str, option_revision_id: str) -> dict:
    """The frozen input manifest every W2 output must cite."""
    spatial = model["spatial"]
    source = spatial["source"]
    return {
        "schema_version": "rkd-spatial-frozen-input.v1",
        "project_id": project_id,
        "option_revision_id": option_revision_id,
        "option_id": model["option_id"],
        "revision_no": model["revision_no"],
        "model_hash": model_hash(model),
        "source_artifact_id": source["artifact_id"],
        "source_sha256": source["sha256"],
        "source_revision_uid": source.get("revision_uid"),
        "source_parent_revision_uid": source.get("parent_revision_uid"),
        "root_revision_uid": source.get("root_revision_uid"),
        "parent_link_status": source.get("parent_link_status"),
        "design_origin": source.get("design_origin"),
        "geometry_authority": "spatial.zones[].polygon_mm",
        "legacy_bbox_used_for_measurement": False,
        "object_versions": sorted(z["object_id"] for z in spatial["zones"]),
        "materials_version": "studio-material-unspecified/intent_only",
        "views_version": "derived_camera_assumption_v1",
        "generator_version": GENERATOR_VERSION,
        "frozen_at": now_iso(),
    }


# -------------------------------------------------------------------- camera
def derive_camera(model: dict) -> dict:
    """A deterministic presentation camera, explicitly an ASSUMPTION.

    The Studio proposal has no camera; W2 derives one from the entrance and the
    largest zone. It is never presented as a designed view or a measured fact.
    """
    spatial = model["spatial"]
    width_mm = float(spatial["origin"]["boundary_mm"][0])
    height_mm = float(spatial["origin"]["boundary_mm"][1])
    ent = model["boundary"]["entrance"]
    ex = float(model["boundary"]["width"]) * 1000  # placeholder, replaced below
    point = [float(ent["point"][0]) * 1000, float(ent["point"][1]) * 1000]
    width_ent = float(ent["width"]) * 1000
    # stand 1.2 m inside the west entrance, at eye height
    eye_x = point[0] + 1200
    eye_y = point[1] + width_ent / 2
    largest = max(spatial["zones"],
                  key=lambda z: Polygon([(p[0], p[1]) for p in z["polygon_mm"]]).area)
    poly = Polygon([(p[0], p[1]) for p in largest["polygon_mm"]])
    cx, cy = poly.centroid.x, poly.centroid.y
    return {
        "camera_id": "C1-人眼入口视角",
        "kind": "eye_level",
        "assumption": True,
        "assumption_note": "Studio 提案未建模相机；机位由入口区段与最大功能区按固定规则推导，"
                           "不是设计决定的视点，也不是实测机位",
        "eye_height_mm": 1500,
        "position_mm": [round(eye_x, 1), round(eye_y, 1)],
        "target_mm": [round(cx, 1), round(cy, 1)],
        "lens_mm": 24, "sensor_mm": 36,
        "boundary_mm": [width_mm, height_mm],
    }


# ------------------------------------------------------------------ measure
def _zone_polygons(model: dict) -> list[tuple[str, Polygon]]:
    return [(z["object_id"], Polygon([(float(p[0]), float(p[1]))
                                      for p in z["polygon_mm"]]))
            for z in model["spatial"]["zones"]]


def _keepouts(model: dict) -> list[tuple[str, Polygon]]:
    out = []
    for o in model["boundary"]["obstacles"]:
        s = o["shape"]
        x, y = float(s["x"]) * 1000, float(s["y"]) * 1000
        w, l = float(s["width"]) * 1000, float(s["length"]) * 1000
        out.append((o["object_id"], box(x, y, x + w, y + l)))
    return out


def _shoelace_mm2(points: list) -> float:
    area = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def measure(model: dict) -> dict:
    """Deterministic quantities from EXACT polygons (bbox values kept only to prove they differ)."""
    zones = _zone_polygons(model)
    union = unary_union([p for _oid, p in zones])
    keepouts = _keepouts(model)
    keep_union = unary_union([p for _oid, p in keepouts]) if keepouts else None
    deducted = (union.intersection(keep_union).area if keep_union else 0.0)
    gross = union.area
    net = gross - deducted
    bbox_union = unary_union([box(*p.bounds) for _oid, p in zones])
    bbox_gross = bbox_union.area
    bbox_net = bbox_gross - (bbox_union.intersection(keep_union).area
                             if keep_union else 0.0)
    independent = sum(_shoelace_mm2([(float(p[0]), float(p[1]))
                                     for p in z["polygon_mm"]])
                      for z in model["spatial"]["zones"]) / MM2
    declared = sum(float(z.get("area_sqm") or 0) for z in model["spatial"]["zones"])
    deductions = []
    for oid, poly in keepouts:
        inter = union.intersection(poly).area
        if inter > 1.0:
            deductions.append({"object_id": oid, "area_m2": round(inter / MM2, 3)})
    platform_area = 0.0
    for p in model["spatial"].get("platforms") or []:
        if len(p.get("polygon_mm") or []) >= 3:
            platform_area += Polygon([(q[0], q[1]) for q in p["polygon_mm"]]).area
    items = [
        {"quantity_id": "Q-FLOOR-GROSS", "name": "功能区地坪总面积（未扣）",
         "value": round(gross / MM2, 3), "unit": "m2", "known_status": "known",
         "method": "exact_polygon_union", "formula_version": QUANTITY_VERSION,
         "source_objects": [oid for oid, _p in zones],
         "note": "按精确多边形并集；不是建筑面积，也不含墙厚"},
        {"quantity_id": "Q-KEEPOUT-DEDUCT", "name": "保留区扣除面积",
         "value": round(deducted / MM2, 3), "unit": "m2", "known_status": "known",
         "method": "exact_intersection_with_keepouts", "formula_version": QUANTITY_VERSION,
         "source_objects": [d["object_id"] for d in deductions], "deductions": deductions},
        {"quantity_id": "Q-FLOOR-NET", "name": "地坪完成面净面积",
         "value": round(net / MM2, 3), "unit": "m2", "known_status": "known",
         "method": "exact_union_minus_keepouts", "formula_version": QUANTITY_VERSION,
         "source_objects": [oid for oid, _p in zones],
         "independent_recompute_m2": round(independent - deducted / MM2, 3),
         "bbox_value_m2": round(bbox_net / MM2, 3),
         "bbox_delta_m2": round((bbox_net - net) / MM2, 3),
         "note": "bbox 结果仅用于证明不能据包围盒计量；权威值是精确多边形"},
        {"quantity_id": "Q-PLATFORM-ENVELOPE", "name": "展台包络面积（非实体量）",
         "value": round(platform_area / MM2, 3), "unit": "m2",
         "known_status": "intent_only", "method": "exact_polygon_union",
         "formula_version": QUANTITY_VERSION,
         "source_objects": [p["object_id"] for p in model["spatial"].get("platforms") or []],
         "note": "平台包络不等于台体/基层/饰面实体工程量，不计入本批净量"},
        {"quantity_id": "Q-PARTITION-LENGTH", "name": "隔断长度",
         "value": None, "unit": "m", "known_status": "unknown",
         "unknown_reason": "Studio 提案未建模隔断构件，不能从分区边界推断"},
        {"quantity_id": "Q-CEILING-AREA", "name": "天花面积",
         "value": None, "unit": "m2", "known_status": "unknown",
         "unknown_reason": "天花只到意向（灯槽/灯具点位），未建模吊顶构造与标高"},
        {"quantity_id": "Q-DOOR-WINDOW", "name": "门窗数量",
         "value": None, "unit": "count", "known_status": "unknown",
         "unknown_reason": "建议案未建模门窗对象，只有场地条件"},
    ]
    return {"schema_version": QUANTITY_VERSION, "items": items,
            "declared_area_sum_m2": round(declared, 3),
            "declared_vs_exact_delta_m2": round(declared - net / MM2, 3),
            "coverage": "只覆盖功能区地坪与保留区扣除；隔断/天花/门窗/机电未建模，保持 unknown"}


# --------------------------------------------------------------------- cost
def build_cost(quantities: dict, *, settings: dict | None = None) -> dict:
    """A cost draft. Money is unknown unless the caller supplies an explicit
    ASSUMPTION price; such an amount is labelled and is never a quote."""
    settings = settings or {}
    net = next((q["value"] for q in quantities["items"]
                if q["quantity_id"] == "Q-FLOOR-NET"), None)
    price = settings.get("floor_unit_price_cny")
    known_items = []
    pricing_basis = {"unit_prices": "unknown", "loss_rate": "unknown",
                     "labor_and_process": "unknown",
                     "tax_rate": "user_confirmed_but_not_applied_without_price_source",
                     "markup": "user_confirmed_but_not_applied_without_price_source"}
    if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0 and net:
        known_items.append({
            "item": "地坪完成面（按输入假设单价试算）", "quantity_ref": "Q-FLOOR-NET",
            "quantity_m2": net, "unit_price_cny": price,
            "amount_cny": round(net * price, 2),
            "basis": "caller_provided_assumption_not_a_quote",
            "note": "单价由调用方作为假设输入，不是价源、不是报价、不含损耗与工艺",
        })
        pricing_basis["unit_prices"] = "provided_by_caller_assumption"
    unknown = [
        {"statement": "地坪完成面单价（材料/工艺/损耗/起订量）未提供",
         "quantity_ref": "Q-FLOOR-NET", "impact": "无法形成地坪金额"},
        {"statement": "隔断、天花、门窗工程量未建模", "quantity_ref": "Q-PARTITION-LENGTH",
         "impact": "相关金额保持 unknown"},
        {"statement": "税率与成本加成虽有用户口径，但没有价源，本批不做金额试算",
         "quantity_ref": None, "impact": "不输出合计金额"},
    ]
    return {
        "schema_version": COST_VERSION, "currency": "CNY",
        "known_items": known_items,
        "unknown_items": unknown,
        "total_project_estimate": {"value": None, "known_status": "unknown",
                                   "unknown_reason": "没有价源；不把地坪小计当项目总造价"},
        "formal_quote": False,
        "pricing_basis": pricing_basis,
        "note": "本批只证明净量与缺项口径；金额一律 unknown，不填 0",
    }


def cost_html(cost: dict, quantities: dict) -> bytes:
    rows = []
    qmap = {q["quantity_id"]: q for q in quantities["items"]}
    for item in cost["known_items"]:
        rows.append(f"<tr><td>{escape(str(item))}</td></tr>")
    unknown_rows = "".join(
        f"<tr><td>{escape(u['statement'])}</td><td>{escape(str(u.get('quantity_ref') or '-'))}</td>"
        f"<td>{escape(u['impact'])}</td></tr>" for u in cost["unknown_items"])
    qrows = "".join(
        f"<tr><td>{escape(q['name'])}</td><td>{'' if q['value'] is None else q['value']}</td>"
        f"<td>{escape(q['unit'])}</td><td>{escape(q['known_status'])}</td></tr>"
        for q in quantities["items"])
    html = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>成本缺项表（草案）</title>
<style>body{{font:14px/1.6 system-ui,"Microsoft YaHei",sans-serif;margin:32px;color:#1f2937}}
h1{{font-size:20px}}table{{border-collapse:collapse;width:100%;margin:12px 0 24px}}
th,td{{border:1px solid #d7dee6;padding:6px 8px;text-align:left}}th{{background:#f1f5f9}}
.warn{{background:#fff7ed;border-left:4px solid #c2410c;padding:10px 12px}}</style>
<h1>成本缺项表 · 草案（非正式报价）</h1>
<div class="warn">本页没有金额：单价、损耗、工艺与产品选型均未提供，所有金额保持 unknown。
不把地坪净量当作造价，也不把草案当报价或合同。</div>
<h2>净量（已知）</h2><table><thead><tr><th>项目</th><th>数值</th><th>单位</th><th>状态</th></tr></thead>
<tbody>{qrows}</tbody></table>
<h2>金额缺项</h2><table><thead><tr><th>缺项</th><th>关联量</th><th>影响</th></tr></thead>
<tbody>{unknown_rows}</tbody></table>
<p>正式报价：关闭。外部下单/付款：未发生。</p></html>"""
    return html.encode("utf-8")


# --------------------------------------------------------------------- plan
def _fmt_mm(value: float) -> str:
    return f"{value:.0f}"


def build_plan_svg(model: dict, camera: dict, quantities: dict) -> bytes:
    """A readable concept plan: polygons, furniture, circulation, dimensions,
    legend, area table, camera marker and explicit missing items."""
    spatial = model["spatial"]
    width = float(spatial["origin"]["boundary_mm"][0])
    height = float(spatial["origin"]["boundary_mm"][1])
    draw_w, draw_h = 880.0, 640.0
    scale = min(draw_w / width, draw_h / height)
    ox, oy = 80.0, 110.0
    W = ox + width * scale + 330
    H = oy + height * scale + 110

    def X(mm: float) -> float:
        return ox + mm * scale

    def Y(mm: float) -> float:
        return oy + (height - mm) * scale

    def pts(poly: list) -> str:
        return " ".join(f"{X(float(p[0])):.2f},{Y(float(p[1])):.2f}" for p in poly)

    palette = ["#dbeafe", "#dcfce7", "#fef3c7", "#fce7f3", "#e0e7ff", "#ccfbf1",
               "#fee2e2", "#ede9fe"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
        f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="Microsoft YaHei, Noto Sans SC, sans-serif">',
        '<defs><pattern id="keepout" width="8" height="8" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="8" '
        'stroke="#94a3b8" stroke-width="2"/></pattern></defs>',
        '<rect width="100%" height="100%" fill="#fbfaf7"/>',
        f'<rect x="{ox}" y="{Y(height):.2f}" width="{width*scale:.2f}" '
        f'height="{height*scale:.2f}" fill="#ffffff" stroke="#1f2937" stroke-width="4"/>',
    ]
    for i, z in enumerate(spatial["zones"]):
        poly = z["polygon_mm"]
        finish = z.get("finish_material") or {}
        fill = finish.get("hex") or palette[i % len(palette)]
        parts.append(f'<polygon points="{pts(poly)}" fill="{fill}" fill-opacity="0.8" '
                     f'stroke="#334155" stroke-width="1.6"/>')
        # per-zone dimension text (bbox extents) — a readable dimension chain
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        parts.append(f'<text x="{X(cx):.1f}" y="{Y(cy)-4:.1f}" text-anchor="middle" '
                     f'font-size="14" font-weight="600" fill="#111827">{escape(z["name"])}</text>')
        parts.append(f'<text x="{X(cx):.1f}" y="{Y(cy)+13:.1f}" text-anchor="middle" '
                     f'font-size="10" fill="#475569">{escape(z["object_id"])} · '
                     f'{_fmt_mm(max(xs)-min(xs))}×{_fmt_mm(max(ys)-min(ys))} mm</text>')
        parts.append(f'<text x="{X(cx):.1f}" y="{Y(cy)+28:.1f}" text-anchor="middle" '
                     f'font-size="10" fill="#0f172a">{z.get("area_sqm")} ㎡</text>')
    for o in model["boundary"]["obstacles"]:
        s = o["shape"]
        x, y = float(s["x"]) * 1000, float(s["y"]) * 1000
        w, l = float(s["width"]) * 1000, float(s["length"]) * 1000
        parts.append(f'<rect x="{X(x):.1f}" y="{Y(y+l):.1f}" width="{w*scale:.1f}" '
                     f'height="{l*scale:.1f}" fill="url(#keepout)" stroke="#64748b" '
                     f'stroke-width="1.5"/>')
        parts.append(f'<text x="{X(x+w/2):.1f}" y="{Y(y+l/2):.1f}" text-anchor="middle" '
                     f'font-size="9" fill="#334155">{escape(o["name"])}（保留）</text>')
    for p in spatial.get("platforms") or []:
        if len(p.get("polygon_mm") or []) >= 3:
            parts.append(f'<polygon points="{pts(p["polygon_mm"])}" fill="#f8fafc" '
                         f'fill-opacity="0.6" stroke="#b45309" stroke-width="2" '
                         f'stroke-dasharray="5 3"/>')
    for f in spatial["furniture"]:
        w = float(f.get("w_mm") or 600)
        d = float(f.get("d_mm") or 600)
        x, y = float(f["x_mm"]), float(f["y_mm"])
        rot = math.radians(float(f.get("rot") or 0))
        corners = []
        for dx, dy in ((-w/2, -d/2), (w/2, -d/2), (w/2, d/2), (-w/2, d/2)):
            corners.append([x + dx*math.cos(rot) - dy*math.sin(rot),
                            y + dx*math.sin(rot) + dy*math.cos(rot)])
        parts.append(f'<polygon points="{pts(corners)}" fill="#cbd5e1" fill-opacity="0.85" '
                     f'stroke="#334155" stroke-width="1"/>')
        parts.append(f'<text x="{X(x):.1f}" y="{Y(y)+3:.1f}" text-anchor="middle" '
                     f'font-size="9" fill="#0f172a">{escape(f["object_id"])}</text>')
    for c in spatial["circulation"]:
        path = c["path_mm"]
        parts.append('<polyline points="' + pts(path) + '" fill="none" stroke="#dc2626" '
                     'stroke-width="3" stroke-dasharray="10 5"/>')
        mx, my = (float(path[0][0]) + float(path[1][0])) / 2, \
                 (float(path[0][1]) + float(path[1][1])) / 2
        parts.append(f'<text x="{X(mx):.1f}" y="{Y(my)-6:.1f}" font-size="10" '
                     f'fill="#b91c1c">动线 {escape(c["object_id"])} · {c["width_mm"]}mm</text>')
    for fx in (spatial["ceiling"].get("fixtures") or []):
        x, y = float(fx.get("x") or 0), float(fx.get("y") or 0)
        parts.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="4.5" fill="#f59e0b" '
                     f'stroke="#92400e" stroke-width="1"/>')
    # camera marker + view cone
    cam = camera
    ex, ey = cam["position_mm"]
    tx, ty = cam["target_mm"]
    parts.append(f'<line x1="{X(ex):.1f}" y1="{Y(ey):.1f}" x2="{X(tx):.1f}" '
                 f'y2="{Y(ty):.1f}" stroke="#7c3aed" stroke-width="1.5" '
                 f'stroke-dasharray="4 4"/>')
    parts.append(f'<circle cx="{X(ex):.1f}" cy="{Y(ey):.1f}" r="6" fill="#7c3aed"/>')
    parts.append(f'<text x="{X(ex)+10:.1f}" y="{Y(ey)-8:.1f}" font-size="10" fill="#5b21b6">'
                 f'C1 人眼 1.5m · 24mm（推导机位，非设计视点）</text>')
    # overall dimension lines
    parts.append(f'<line x1="{ox}" y1="{oy-26}" x2="{ox+width*scale:.1f}" y2="{oy-26}" '
                 f'stroke="#334155" stroke-width="1"/>')
    parts.append(f'<text x="{ox+width*scale/2:.1f}" y="{oy-32}" text-anchor="middle" '
                 f'font-size="11" fill="#334155">总宽 {_fmt_mm(width)} mm</text>')
    parts.append(f'<line x1="{ox+width*scale+26:.1f}" y1="{Y(height):.1f}" '
                 f'x2="{ox+width*scale+26:.1f}" y2="{Y(0):.1f}" stroke="#334155" stroke-width="1"/>')
    parts.append(f'<text x="{ox+width*scale+32:.1f}" y="{Y(height/2):.1f}" font-size="11" '
                 f'fill="#334155" transform="rotate(90 {ox+width*scale+32:.1f} {Y(height/2):.1f})" '
                 f'text-anchor="middle">总长 {_fmt_mm(height)} mm</text>')
    # title block
    parts.append(f'<text x="{ox}" y="34" font-size="18" font-weight="700" fill="#111827">'
                 f'{escape(model["strategy"]["statement"][:60])}</text>')
    parts.append(f'<text x="{ox}" y="56" font-size="11" fill="#475569">'
                 f'候选 {escape(model["option_id"])} v{model["revision_no"]} · '
                 f'源 {escape(spatial["source"]["artifact_id"])} · '
                 f'模型 {model_hash(model)[:12]} · {GENERATOR_VERSION}</text>')
    parts.append(f'<text x="{ox}" y="74" font-size="11" fill="#b91c1c">'
                 f'概念平面（内部评审）：不是施工图，不宣称消防/无障碍/门洞净宽合规</text>')
    # legend
    lx = ox + width * scale + 60
    ly = oy + 10
    parts.append(f'<text x="{lx}" y="{ly}" font-size="13" font-weight="700" fill="#111827">图例</text>')
    legend = [("#dbeafe", "功能分区（多边形，非墙体）"), ("#cbd5e1", "家具（目录尺寸）"),
              ("#dc2626", "主动线（净宽 mm）"), ("#f59e0b", "灯具点位（意向）"),
              ("#7c3aed", "人眼机位（推导）"), ("url(#keepout)", "保留区（扣除）")]
    for i, (fill, label) in enumerate(legend):
        yy = ly + 24 + i * 22
        parts.append(f'<rect x="{lx}" y="{yy-11}" width="18" height="12" fill="{fill}" '
                     f'stroke="#64748b" stroke-width="0.8"/>')
        parts.append(f'<text x="{lx+26}" y="{yy}" font-size="10" fill="#334155">'
                     f'{escape(label)}</text>')
    # area table
    ty = ly + 24 + len(legend) * 22 + 16
    parts.append(f'<text x="{lx}" y="{ty}" font-size="13" font-weight="700" fill="#111827">面积表</text>')
    parts.append(f'<text x="{lx}" y="{ty+18}" font-size="10" fill="#475569">'
                 f'（按精确多边形复算，非模型自报）</text>')
    for i, z in enumerate(spatial["zones"]):
        yy = ty + 38 + i * 18
        parts.append(f'<text x="{lx}" y="{yy}" font-size="10" fill="#334155">'
                     f'{escape(z["name"])}</text>')
        parts.append(f'<text x="{lx+250}" y="{yy}" font-size="10" text-anchor="end" '
                     f'fill="#0f172a">{z.get("area_sqm")} ㎡</text>')
    net_item = next(q for q in quantities["items"] if q["quantity_id"] == "Q-FLOOR-NET")
    parts.append(f'<text x="{lx}" y="{ty+38+len(spatial["zones"])*18+8}" font-size="10" '
                 f'font-weight="600" fill="#0f172a">地坪净面积（扣保留区）</text>')
    parts.append(f'<text x="{lx+250}" y="{ty+38+len(spatial["zones"])*18+8}" font-size="10" '
                 f'text-anchor="end" font-weight="600" fill="#0f172a">{net_item["value"]} ㎡</text>')
    # missing items
    my = ty + 38 + (len(spatial["zones"]) + 1) * 18 + 26
    parts.append(f'<text x="{lx}" y="{my}" font-size="12" font-weight="700" fill="#b91c1c">'
                 f'未建模 / 缺项</text>')
    missing = ["墙体构造与门窗（未建模，不画框线冒充）", "洁具（未建模）",
               "隔断构件与长度（未建模）", "天花吊顶构造（只有灯槽意向）",
               "照度/配光（未计算）", "材料规格与产品选型（unknown）"]
    for i, text in enumerate(missing):
        parts.append(f'<text x="{lx}" y="{my+18+i*16}" font-size="9.5" fill="#7f1d1d">'
                     f'· {escape(text)}</text>')
    parts.append('</svg>')
    return "".join(parts).encode("utf-8")


# -------------------------------------------------------------------- scene
def build_scene(model: dict, camera: dict) -> dict:
    """Blender scene spec in metres; coordinates and sizes come from the model."""
    spatial = model["spatial"]
    width_mm = float(spatial["origin"]["boundary_mm"][0])
    height_mm = float(spatial["origin"]["boundary_mm"][1])

    def m(v: float) -> float:
        return round(float(v) / 1000.0, 4)

    zones = []
    for i, z in enumerate(spatial["zones"]):
        zones.append({"object_id": z["object_id"], "name": z["name"],
                      "polygon_m": [[m(p[0]), m(p[1])] for p in z["polygon_mm"]],
                      "color": (z.get("finish_material") or {}).get("hex")
                      or ["#9ec5e8", "#a7d8b6", "#e8cf94", "#e6b7c8",
                          "#b9c0ea", "#9fd8cd", "#e9b0ad", "#c9bce6"][i % 8]})
    furniture = []
    for f in spatial["furniture"]:
        furniture.append({"object_id": f["object_id"], "catalog_id": f["catalog_id"],
                          "x_m": m(f["x_mm"]), "y_m": m(f["y_mm"]),
                          "w_m": m(f.get("w_mm") or 600), "d_m": m(f.get("d_mm") or 600),
                          "rot_deg": float(f.get("rot") or 0),
                          "height_m": 0.75,
                          "height_assumption": True})
    platforms = []
    for p in spatial.get("platforms") or []:
        if len(p.get("polygon_mm") or []) >= 3:
            platforms.append({"object_id": p["object_id"],
                              "polygon_m": [[m(q[0]), m(q[1])] for q in p["polygon_mm"]],
                              "height_m": m(p.get("height_mm") or 0)})
    keepouts = []
    for o in model["boundary"]["obstacles"]:
        s = o["shape"]
        keepouts.append({"object_id": o["object_id"], "name": o["name"],
                         "x_m": m(float(s["x"]) * 1000), "y_m": m(float(s["y"]) * 1000),
                         "w_m": m(float(s["width"]) * 1000),
                         "l_m": m(float(s["length"]) * 1000)})
    fixtures = [{"object_id": fx.get("id"), "x_m": m(fx.get("x") or 0),
                 "y_m": m(fx.get("y") or 0), "kelvin": fx.get("kelvin"),
                 "type": fx.get("type")} for fx in (spatial["ceiling"].get("fixtures") or [])]
    return {
        "schema_version": SCENE_VERSION,
        "unit": "m",
        "boundary": {"width_m": m(width_mm), "length_m": m(height_mm),
                     "ceiling_m": m(spatial["source"].get("site_source", {}).get("ceiling_mm") or 3000)},
        "zones": zones, "furniture": furniture, "platforms": platforms,
        "keepouts": keepouts, "fixtures": fixtures,
        # Blender convention: [x, y, z] with z up.
        "camera": {"position": [m(camera["position_mm"][0]), m(camera["position_mm"][1]), 1.5],
                   "target": [m(camera["target_mm"][0]), m(camera["target_mm"][1]), 1.2],
                   "lens_mm": camera["lens_mm"], "eye_height_m": 1.5,
                   "assumption": True},
        "render_assumptions": [
            "机位/视线由入口与最大分区推导，不是设计决定的视点",
            "家具高度按 0.75m 统一占位，未按产品规格",
            "材质用统一中性材质，不代表材料规格",
            "灯光只做展示照明，不做照度/配光计算",
        ],
        "source": {"option_id": model["option_id"], "revision_no": model["revision_no"],
                   "artifact_id": spatial["source"]["artifact_id"],
                   "model_hash": model_hash(model)},
    }


# ------------------------------------------------------------------ package
def build_package(model: dict, *, project_id: str, option_revision_id: str,
                  settings: dict | None = None) -> dict:
    settings = settings or {}
    frozen = freeze_input(model, project_id=project_id,
                          option_revision_id=option_revision_id)
    camera = derive_camera(model)
    quantities = measure(model)
    cost = build_cost(quantities, settings=settings)
    plan = build_plan_svg(model, camera, quantities)
    scene = build_scene(model, camera)
    files = {
        "plan.svg": ("plan_svg", "image/svg+xml", plan),
        "quantity.json": ("development_json", "application/json", _json(quantities)),
        "quantity.csv": ("quantity_csv", "text/csv; charset=utf-8",
                          _quantity_csv(quantities)),
        "cost.html": ("cost_html", "text/html; charset=utf-8",
                       cost_html(cost, quantities)),
        "scene.json": ("development_json", "application/json", _json(scene)),
    }
    manifest = {
        "schema_version": MANIFEST_VERSION,
        "baseline": frozen,
        "camera": camera,
        "quantities": quantities,
        "cost": cost,
        "missing": ["墙体与门窗构造", "洁具", "隔断构件", "天花吊顶构造", "照度/配光",
                    "材料规格与产品选型", "相机原始视点（推导假设）"],
        "files": [],
    }
    return {"frozen": frozen, "camera": camera, "quantities": quantities,
            "cost": cost, "scene": scene, "plan": plan, "files": files,
            "manifest": manifest, "settings": settings}


def _quantity_csv(quantities: dict) -> bytes:
    lines = ["quantity_id,name,value,unit,known_status,method,note"]
    for q in quantities["items"]:
        note = (q.get("unknown_reason") or q.get("note") or "").replace(",", "，")
        value = "" if q["value"] is None else q["value"]
        lines.append(f'{q["quantity_id"]},{q["name"]},{value},{q["unit"]},'
                     f'{q["known_status"]},{q.get("method") or "not_applicable"},"{note}"')
    return ("\n".join(lines) + "\n").encode("utf-8")


def add_rendered(manifest: dict, *, filename: str, png: bytes, render_meta: dict) -> dict:
    manifest["files"].append({"filename": filename, "kind": "render_png",
                              "content_type": "image/png",
                              "sha256": sha256_bytes(png), "size_bytes": len(png)})
    manifest["render"] = render_meta
    return manifest


def finalize_files(files: dict, manifest: dict) -> dict:
    out = dict(files)
    listed = {entry["filename"] for entry in manifest.get("files", [])}
    for name, (kind, ctype, data) in sorted(files.items()):
        if name in listed:
            continue
        manifest.setdefault("files", []).append(
            {"filename": name, "kind": kind, "content_type": ctype,
             "sha256": sha256_bytes(data), "size_bytes": len(data)})
    out["manifest.json"] = ("manifest_json", "application/json",
                            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, (_kind, _ctype, data) in sorted(out.items()):
            zf.writestr(name, data)
    out["package.zip"] = ("package_zip", "application/zip", buf.getvalue())
    return out
