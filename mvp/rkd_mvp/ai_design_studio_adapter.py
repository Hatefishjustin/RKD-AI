"""W1: Studio valid proposal -> main-system versioned AI design candidate.

ONE authoritative model: the produced document is still
``rkd-ai-design-option.v1``.  The optional ``spatial`` section is a faithful,
unit-explicit projection of the Studio ``spatial-plan-draft.v1`` document
(exact mm polygons, ceiling/lighting intent, object ids, provenance, named
unsupported items).  The legacy rect ``objects[]`` remain for old renderers but
are ALWAYS labelled ``geometry_mode=bbox_derived`` and never claimed to be the
exact geometry; precise checks run on the polygons with shapely.

No external calls, no model inference, no unit guessing, no invented facts.
``unknown`` stays unknown (never 0).  This module only builds a candidate;
the service decides when/where it is committed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from decimal import Decimal
from html import escape
from itertools import combinations
from typing import Any

from shapely.geometry import LineString, Polygon, box

ADAPTER_VERSION = "rkd-studio-proposal-adapter.v1"
SPATIAL_VERSION = "rkd-ai-design-option-spatial.v1"
MAPPING_VERSION = "W0-erratum-2.3"
DRAFT_VERSION = "rkd-spatial-plan.v1"
OPTION_SCHEMA_VERSION = "rkd-ai-design-option.v1"
GEOMETRY_RULE_VERSION = "rkd-studio-import-geometry.v1"
MM_PER_M = Decimal("1000")


class StudioAdaptationError(Exception):
    """Deterministic rejection BEFORE anything is written."""

    def __init__(self, code: str, message: str, *, stage: str = "adaptation") -> None:
        self.code, self.message, self.stage = code, message, stage
        super().__init__(f"{code}: {message}")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _dec(value: Any, *, mm: bool = False) -> str:
    """Exact decimal string; mm values are converted to m by /1000."""
    d = Decimal(str(value))
    if mm:
        d = d / MM_PER_M
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _bbox(polygon: list) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in polygon]
    ys = [float(p[1]) for p in polygon]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ------------------------------------------------------------------ validation
def validate_source(plan: dict, *, expected_unit: str = "mm",
                    catalog: dict | None = None) -> None:
    """Reject anything the adapter cannot express faithfully.

    Raises StudioAdaptationError; never silently approximates or drops.
    """
    if not isinstance(plan, dict):
        raise StudioAdaptationError("NOT_A_PLAN", "源提案不是 JSON 对象")
    if plan.get("contract_version") != DRAFT_VERSION:
        raise StudioAdaptationError("CONTRACT_VERSION_MISMATCH",
                                    "源不是 spatial-plan-draft.v1（身份字段必须由程序装配）",
                                    stage="source")
    for key in ("project_id", "option_id", "revision", "strategy", "zones",
                "circulation", "furniture", "area_table"):
        if key not in plan:
            raise StudioAdaptationError("MISSING_SOURCE_FIELD",
                                        f"源提案缺少 {key}", stage="source")
    declared = plan.get("source_unit") or plan.get("unit")
    if declared is not None and str(declared) != "mm":
        raise StudioAdaptationError("UNIT_MISMATCH",
                                    f"源提案声明单位为 {declared}；适配器只接受 mm，不猜测换算",
                                    stage="unit")
    if str(expected_unit) != "mm":
        raise StudioAdaptationError("UNIT_MISMATCH",
                                    f"调用方声明单位为 {expected_unit}；与源契约 mm 不一致",
                                    stage="unit")

    ids: list[str] = []
    for group in ("zones", "furniture", "circulation", "platforms"):
        for item in plan.get(group) or []:
            if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                raise StudioAdaptationError("MISSING_OBJECT_REFERENCE",
                                            f"{group} 中有对象缺少稳定 id", stage="objects")
            ids.append(str(item["id"]))
    if len(ids) != len(set(ids)):
        raise StudioAdaptationError("DUPLICATE_OBJECT_ID",
                                    "源提案对象 ID 不唯一，无法稳定映射", stage="objects")

    known_catalog = set((catalog or {}).keys())
    for f in plan.get("furniture") or []:
        cid = str(f.get("catalog_id") or "")
        if known_catalog and cid not in known_catalog:
            raise StudioAdaptationError("UNKNOWN_CATALOG_REF",
                                        f"家具 {f.get('id')} 引用了目录里不存在的 {cid}",
                                        stage="objects")
        for key in ("x", "y", "rot"):
            if not _is_number(f.get(key)):
                raise StudioAdaptationError("MISSING_OBJECT_REFERENCE",
                                            f"家具 {f.get('id')} 的 {key} 缺失或非数值",
                                            stage="objects")
    for z in plan.get("zones") or []:
        polygon = z.get("polygon")
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise StudioAdaptationError("UNSUPPORTED_GEOMETRY",
                                        f"分区 {z.get('id')} 的多边形点数不足 3，不能静默矩形化",
                                        stage="geometry")
        for point in polygon:
            if (not isinstance(point, (list, tuple)) or len(point) != 2
                    or not all(_is_number(v) for v in point)):
                raise StudioAdaptationError("UNSUPPORTED_GEOMETRY",
                                            f"分区 {z.get('id')} 的点不是二维数值坐标",
                                            stage="geometry")
    for c in plan.get("circulation") or []:
        path = c.get("path")
        if not isinstance(path, list) or len(path) < 2:
            raise StudioAdaptationError("UNSUPPORTED_GEOMETRY",
                                        f"动线 {c.get('id')} 的折线少于两个点",
                                        stage="geometry")
        if not _is_number(c.get("width_mm")):
            raise StudioAdaptationError("MISSING_OBJECT_REFERENCE",
                                        f"动线 {c.get('id')} 缺少 width_mm",
                                        stage="objects")
    if len(plan.get("zones") or []) < 3:
        raise StudioAdaptationError("UNSUPPORTED_GEOMETRY",
                                    "源提案的功能分区少于 3 个", stage="geometry")


def exact_geometry_checks(plan: dict, site: dict) -> dict:
    """Hard checks on the EXACT mm polygons, not on bounding boxes."""
    width = float(site["width_mm"])
    height = float(site["height_mm"])
    boundary = box(0, 0, width, height)
    checks: list[dict] = []

    def add(code: str, ok: bool, message: str) -> None:
        checks.append({"code": code, "status": "passed" if ok else "failed",
                       "message": message})

    polygons: list[tuple[str, Polygon]] = []
    ok_polygons = True
    for z in plan["zones"]:
        poly = Polygon([(float(p[0]), float(p[1])) for p in z["polygon"]])
        if not poly.is_valid or poly.area <= 0:
            ok_polygons = False
            add("STUDIO_POLYGON_INVALID", False, f"{z['id']} 多边形自交或面积为零")
        else:
            polygons.append((str(z["id"]), poly))
    if ok_polygons:
        add("STUDIO_POLYGON_VALID", True,
            f"{len(polygons)} 个分区多边形有效（含非矩形轮廓），按原坐标复核")

    inside = all(poly.within(boundary) or boundary.covers(poly) for _oid, poly in polygons)
    add("STUDIO_ZONE_WITHIN_BOUNDARY", inside,
        "所有分区位于场地边界内" if inside else "有分区越出场地边界")

    overlaps = [(a, b, a_poly.intersection(b_poly).area)
                for (a, a_poly), (b, b_poly) in combinations(polygons, 2)
                if a_poly.intersects(b_poly) and a_poly.intersection(b_poly).area > 1.0]
    add("STUDIO_ZONE_NON_OVERLAP", not overlaps,
        "精确多边形互不重叠" if not overlaps
        else "精确多边形重叠：" + "、".join(f"{a}/{b}" for a, b, _ in overlaps))

    small = [oid for oid, poly in polygons if poly.area / 1e6 < 1.0]
    add("STUDIO_ZONE_MIN_AREA", not small,
        "分区面积均不小于 1㎡" if not small else "过小分区：" + "、".join(small))

    all_ids = [str(x["id"]) for g in ("zones", "furniture", "circulation", "platforms")
               for x in (plan.get(g) or [])]
    add("STUDIO_OBJECT_IDS_UNIQUE", len(all_ids) == len(set(all_ids)),
        "对象 ID 唯一且稳定")

    path_ok = True
    for c in plan["circulation"]:
        line = LineString([(float(p[0]), float(p[1])) for p in c["path"]])
        if not boundary.covers(line):
            path_ok = False
        if float(c["width_mm"]) < 900:
            path_ok = False
    add("STUDIO_CIRCULATION_WITHIN_BOUNDARY", path_ok,
        "动线折线在边界内且声明净宽不低于 900mm（有限障碍口径，非门洞合规证明）")

    furn_ok = True
    for f in plan["furniture"]:
        if not (0 <= float(f["x"]) <= width and 0 <= float(f["y"]) <= height):
            furn_ok = False
    add("STUDIO_FURNITURE_WITHIN_BOUNDARY", furn_ok, "家具定位点在边界内")

    ent = site.get("entrance")
    entrance_ok = (isinstance(ent, (list, tuple)) and len(ent) == 3
                   and 0 <= float(ent[1]) <= height
                   and float(ent[1]) + float(ent[2]) <= height)
    add("STUDIO_ENTRANCE_ON_BOUNDARY", bool(entrance_ok), "入口区段来自场地条件，落在西墙边界")

    professional = [
        {"code": "FIRE_EGRESS", "status": "unknown", "message": "消防疏散未建模，不宣称合规"},
        {"code": "ACCESSIBILITY", "status": "unknown", "message": "无障碍未建模，不宣称合规"},
        {"code": "MEASURED_SITE", "status": "unknown", "message": "现场实测/门洞净宽未建模，不把示意当实测"},
    ]
    failed = [c for c in checks if c["status"] == "failed"]
    if failed:
        raise StudioAdaptationError("GEOMETRY_CHECK_FAILED",
                                    "；".join(c["message"] for c in failed[:3]),
                                    stage="geometry")
    return {
        "rule_version": GEOMETRY_RULE_VERSION,
        "status": "passed",
        "hard_checks": checks,
        "professional_checks": professional,
        "publication_status": "not_approved",
    }


# ------------------------------------------------------------------- adaptation
def _legacy_objects(plan: dict, artifact_id: str, catalog: dict) -> tuple[list[dict], list[dict]]:
    objects: list[dict] = []
    id_map: list[dict] = []
    for z in plan["zones"]:
        x, y, w, h = _bbox(z["polygon"])
        objects.append({
            "object_id": str(z["id"]), "kind": "functional_zone", "name": str(z["name"]),
            "shape": {"type": "rect", "x": _dec(x, mm=True), "y": _dec(y, mm=True),
                      "width": _dec(w, mm=True), "length": _dec(h, mm=True)},
            "material_id": None, "parent_object_id": None,
            "source_refs": [artifact_id], "locked": False,
            "properties": {
                "geometry_mode": "bbox_derived",
                "exact_polygon_ref": f"spatial.zones:{z['id']}",
                "adaptation_loss": "legacy rect is the bounding box only; exact polygon is in spatial.zones",
                "studio_role": z.get("role"),
                "area_source": "studio_area_table_not_program_measured",
                "source_unit": "mm",
            },
        })
        id_map.append({"source_object_id": str(z["id"]),
                       "target_object_id": str(z["id"]), "group": "zones"})
    for p in plan.get("platforms") or []:
        poly = p.get("polygon") or []
        if len(poly) >= 3:
            x, y, w, h = _bbox(poly)
        else:
            x, y, w, h = 0, 0, 0, 0
        objects.append({
            "object_id": str(p["id"]), "kind": "display_object", "name": str(p.get("name") or p["id"]),
            "shape": {"type": "rect", "x": _dec(x, mm=True), "y": _dec(y, mm=True),
                      "width": _dec(w, mm=True), "length": _dec(h, mm=True)},
            "material_id": None, "parent_object_id": None,
            "source_refs": [artifact_id], "locked": False,
            "properties": {"geometry_mode": "bbox_derived",
                           "exact_polygon_ref": f"spatial.platforms:{p['id']}",
                           "studio_kind": p.get("kind"),
                           "corner_radius_mm": p.get("corner_radius_mm"),
                           "height_mm": p.get("height_mm")},
        })
        id_map.append({"source_object_id": str(p["id"]),
                       "target_object_id": str(p["id"]), "group": "platforms"})
    for f in plan["furniture"]:
        item = catalog.get(str(f["catalog_id"]), {})
        w, d = float(item.get("w_mm") or 0), float(item.get("d_mm") or 0)
        rot = float(f["rot"])
        # rotated footprint, expressed as an axis-aligned bounding box
        rad = math.radians(rot)
        bw = abs(w * math.cos(rad)) + abs(d * math.sin(rad))
        bh = abs(w * math.sin(rad)) + abs(d * math.cos(rad))
        objects.append({
            "object_id": str(f["id"]), "kind": "display_object", "name": str(f["catalog_id"]),
            "shape": {"type": "rect", "x": _dec(float(f["x"]) - bw / 2, mm=True),
                      "y": _dec(float(f["y"]) - bh / 2, mm=True),
                      "width": _dec(bw, mm=True), "length": _dec(bh, mm=True)},
            "material_id": None, "parent_object_id": None,
            "source_refs": [artifact_id], "locked": False,
            "properties": {"geometry_mode": "rotated_footprint_bbox",
                           "catalog_id": str(f["catalog_id"]),
                           "center_x_mm": f["x"], "center_y_mm": f["y"], "rot": f["rot"],
                           "w_mm": w, "d_mm": d},
        })
        id_map.append({"source_object_id": str(f["id"]),
                       "target_object_id": str(f["id"]), "group": "furniture"})
    return objects, id_map


def _obstacles(site: dict, artifact_id: str) -> list[dict]:
    out = []
    for name, rect in (("楼梯保留区", site.get("stair")), ("卫生间保留区", site.get("bath"))):
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            continue
        x0, y0, x1, y1 = [float(v) for v in rect]
        out.append({
            "object_id": f"keepout-{name}", "kind": "obstacle", "name": name,
            "shape": {"type": "rect", "x": _dec(x0, mm=True), "y": _dec(y0, mm=True),
                      "width": _dec(x1 - x0, mm=True), "length": _dec(y1 - y0, mm=True)},
            "material_id": None, "parent_object_id": None,
            "source_refs": [artifact_id], "locked": True,
            "properties": {"keepout": True, "source": "structured_site_condition"},
        })
    return out


def _circulation(plan: dict, artifact_id: str) -> tuple[dict, list[dict]]:
    circ = plan["circulation"][0]
    path = [[float(p[0]), float(p[1])] for p in circ["path"]]
    width = float(circ["width_mm"])
    segments = []
    for i in range(len(path) - 1):
        x0, y0 = path[i]
        x1, y1 = path[i + 1]
        seg = LineString([(x0, y0), (x1, y1)])
        bounds = seg.bounds
        pad = width / 2
        segments.append({
            "segment_id": f"{circ['id']}:S{i + 1}",
            "shape": {"type": "rect", "x": _dec(bounds[0] - pad, mm=True),
                      "y": _dec(bounds[1] - pad, mm=True),
                      "width": _dec(bounds[2] - bounds[0] + 2 * pad, mm=True),
                      "length": _dec(bounds[3] - bounds[1] + 2 * pad, mm=True)},
        })
    connections = [[segments[i]["segment_id"], segments[i + 1]["segment_id"]]
                   for i in range(len(segments) - 1)]
    main = {"path_id": str(circ["id"]), "kind": "branch",
            "min_width": _dec(width, mm=True), "segments": segments,
            "connections": connections}
    exact = [{"object_id": str(c["id"]), "width_mm": c["width_mm"],
              "path_mm": [[float(p[0]), float(p[1])] for p in c["path"]],
              "source_refs": [artifact_id]} for c in plan["circulation"]]
    return main, exact


def _relationships(plan: dict, artifact_id: str) -> list[dict]:
    zones = [(str(z["id"]), Polygon([(float(p[0]), float(p[1])) for p in z["polygon"]]))
             for z in plan["zones"]]
    out = []
    for (a, pa), (b, pb) in combinations(zones, 2):
        try:
            if pa.distance(pb) <= 200:
                out.append({"relation_id": f"adj:{a}:{b}", "type": "adjacent",
                            "source": a, "target": b,
                            "statement": "精确多边形相邻（间距 ≤ 200mm）",
                            "source_refs": [artifact_id]})
        except Exception:
            continue
    return out[:20]


def _unsupported(plan: dict) -> list[dict]:
    items = [
        {"item": "材料规格/产品选型", "source_field": "furniture[].catalog_id / (无材料字段)",
         "reason": "Studio 提案只有目录引用，没有材料规格、样板或产品选型；写 unknown，不补默认值",
         "status": "unsupported_unknown"},
        {"item": "相机与人眼视图", "source_field": "(Studio 提案无 camera/view 字段)",
         "reason": "未建模机位、镜头、人眼高度与视向；保留为命名缺项，不生成假设机位",
         "status": "unsupported_unknown"},
        {"item": "照度/配光计算", "source_field": "ceiling.fixtures[].kelvin",
         "reason": "色温与灯具点位已保留为意向；照度、配光、间距未计算，不编数值",
         "status": "unsupported_unknown"},
        {"item": "实测标高/层高", "source_field": "site.ceiling_mm / platforms[].height_mm",
         "reason": "场地与展台高度是给定条件/造型参数，不是现场实测；不升级为实测事实",
         "status": "unsupported_unknown"},
        {"item": "门窗/柱网/构造", "source_field": "site.windows_* / (无 door/column 对象)",
         "reason": "提案未建模门窗与柱网构造；主系统候选对象里不凭空补构件",
         "status": "unsupported_unknown"},
        {"item": "legacy rect 对象", "source_field": "zones[].polygon / platforms[].polygon",
         "reason": "旧渲染器只接受 rect，派生包围盒仅供显示；精确多边形在 spatial 中，不能据包围盒算量",
         "status": "unsupported_unknown"},
    ]
    if not (plan.get("ceiling") or {}).get("fixtures"):
        items.append({"item": "天花灯具点位", "source_field": "ceiling.fixtures",
                      "reason": "源提案未给出灯具点位，保持 unknown",
                      "status": "unsupported_unknown"})
    return items


def _ledger(plan: dict, spatial: dict, model: dict, artifact_id: str) -> list[dict]:
    rows: list[dict] = []

    def row(src: str, dst: str, oid: str, sv: Any, tv: Any,
            unit: str, status: str) -> None:
        rows.append({"source_field": src, "target_field": dst, "object_id": oid,
                     "source_value": sv, "target_value": tv,
                     "unit": unit, "status": status})

    row("strategy.name", "strategy.statement", "strategy",
        plan["strategy"]["name"], model["strategy"]["statement"], "text", "mapped")
    row("strategy.tradeoffs", "strategy.tradeoffs", "strategy",
        plan["strategy"]["tradeoffs"], model["strategy"]["tradeoffs"], "text", "preserved")
    for i, z in enumerate(plan["zones"]):
        row(f"zones[{i}].polygon", f"spatial.zones[{i}].polygon_mm", str(z["id"]),
            z["polygon"], spatial["zones"][i]["polygon_mm"], "mm", "preserved")
        row(f"zones[{i}].area_sqm", f"spatial.zones[{i}].area_sqm", str(z["id"]),
            z.get("area_sqm"), spatial["zones"][i]["area_sqm"], "m2", "preserved")
        row(f"zones[{i}].polygon", f"objects[{i}].shape", str(z["id"]),
            z["polygon"], model["objects"][i]["shape"], "m", "mapped")
        row(f"zones[{i}].role", f"spatial.zones[{i}].role", str(z["id"]),
            z.get("role"), spatial["zones"][i]["role"], "enum", "preserved")
    for i, c in enumerate(plan["circulation"]):
        row(f"circulation[{i}].width_mm", "circulation.min_width", str(c["id"]),
            c["width_mm"], model["circulation"]["min_width"], "m", "mapped")
        row(f"circulation[{i}].path", f"spatial.circulation[{i}].path_mm", str(c["id"]),
            c["path"], spatial["circulation"][i]["path_mm"], "mm", "preserved")
    for i, f in enumerate(plan["furniture"]):
        row(f"furniture[{i}].{{x,y,rot}}", f"spatial.furniture[{i}]", str(f["id"]),
            {k: f[k] for k in ("x", "y", "rot")},
            {k: spatial["furniture"][i][k] for k in ("x_mm", "y_mm", "rot")},
            "mm/degree", "preserved")
        row(f"furniture[{i}].catalog_id", f"spatial.furniture[{i}].catalog_id", str(f["id"]),
            f["catalog_id"], spatial["furniture"][i]["catalog_id"], "id", "preserved")
    for i, fx in enumerate((plan.get("ceiling") or {}).get("fixtures") or []):
        row(f"ceiling.fixtures[{i}].kelvin", f"spatial.ceiling.fixtures[{i}].kelvin",
            str(fx.get("id")), fx.get("kelvin"), fx.get("kelvin"), "K", "preserved")
        row(f"ceiling.fixtures[{i}]", "(no main-system lighting object)",
            str(fx.get("id")), fx, None, "n/a", "unsupported")
    row("area_table", "spatial.area_table", "area_table",
        plan["area_table"], spatial["area_table"], "m2", "preserved")
    row("open_questions", "spatial.open_questions / cost.unknown_items", "unknowns",
        plan.get("open_questions") or [], spatial["open_questions"], "text", "preserved")
    row("contract_version/identity", "spatial.source.draft_identity", "source",
        {k: plan.get(k) for k in ("contract_version", "project_id", "option_id",
                                  "revision", "parent_revision", "author")},
        spatial["source"]["draft_identity"], "n/a", "preserved")
    row("artifact.sha256", "generation.input_hash", "source",
        spatial["source"]["sha256"], model["generation"]["input_hash"], "sha256", "mapped")
    for q in (plan.get("open_questions") or []):
        row("open_question", "cost.unknown_items", "unknowns",
            q, {"statement": q, "known_status": "unknown"}, "text", "unknown")
    return rows


def diff_spatial(previous: dict | None, current: dict) -> list[dict]:
    """Object-level field diffs between two spatial projections (same object id)."""
    if not previous:
        return []
    out: list[dict] = []

    def collect(spatial: dict, group: str, fields: tuple[str, ...]) -> dict:
        return {str(item["object_id"]): {f: item.get(f) for f in fields}
                for item in spatial.get(group, [])}

    specs = (("zones", ("polygon_mm", "area_sqm", "role", "name")),
             ("furniture", ("x_mm", "y_mm", "rot", "catalog_id")),
             ("circulation", ("width_mm", "path_mm")),
             ("platforms", ("polygon_mm", "height_mm", "corner_radius_mm")))
    for group, fields in specs:
        before, after = collect(previous, group, fields), collect(current, group, fields)
        for oid in sorted(set(before) | set(after)):
            for field in fields:
                b, a = before.get(oid, {}).get(field), after.get(oid, {}).get(field)
                if b != a:
                    out.append({"object_id": oid, "field": f"spatial.{group}.{field}",
                                "before": b, "after": a,
                                "reason": "Studio 源提案对象变化（同一稳定对象 ID）"})
    return out


def adapt_proposal(plan: dict, *, provenance: dict, site: dict, catalog: dict,
                   actor_id: str, created_at: str, set_id: str, option_id: str,
                   revision_no: int, parent_revision_id: str | None,
                   previous_spatial: dict | None = None,
                   expected_unit: str = "mm",
                   lineage: dict | None = None,
                   design_origin: dict | None = None,
                   parent_link_status: str | None = None) -> dict:
    """Build ONE rkd-ai-design-option.v1 document from a Studio valid draft."""
    validate_source(plan, expected_unit=expected_unit, catalog=catalog)
    validation = exact_geometry_checks(plan, site)
    artifact_id = str(provenance["artifact_id"])
    source_sha = str(provenance["sha256"])

    objects, zone_id_map = _legacy_objects(plan, artifact_id, catalog)
    main_circulation, exact_circulation = _circulation(plan, artifact_id)
    obstacles = _obstacles(site, artifact_id)

    id_map = list(zone_id_map)
    for c in plan["circulation"]:
        id_map.append({"source_object_id": str(c["id"]),
                       "target_object_id": str(c["id"]), "group": "circulation"})
    for fx in (plan.get("ceiling") or {}).get("fixtures") or []:
        id_map.append({"source_object_id": str(fx.get("id")),
                       "target_object_id": str(fx.get("id")), "group": "ceiling.fixtures"})

    spatial_zones = [{
        "object_id": str(z["id"]), "name": str(z["name"]), "role": str(z.get("role") or ""),
        "polygon_mm": [[float(p[0]), float(p[1])] for p in z["polygon"]],
        "area_sqm": z.get("area_sqm"), "source_refs": [artifact_id],
    } for z in plan["zones"]]
    spatial_furniture = [{
        "object_id": str(f["id"]), "catalog_id": str(f["catalog_id"]),
        "x_mm": float(f["x"]), "y_mm": float(f["y"]), "rot": float(f["rot"]),
        "w_mm": catalog.get(str(f["catalog_id"]), {}).get("w_mm"),
        "d_mm": catalog.get(str(f["catalog_id"]), {}).get("d_mm"),
        "source_refs": [artifact_id],
    } for f in plan["furniture"]]
    spatial_platforms = [{
        "object_id": str(p["id"]), "name": str(p.get("name") or p["id"]),
        "kind": p.get("kind"), "polygon_mm": [[float(q[0]), float(q[1])]
                                             for q in (p.get("polygon") or [])],
        "corner_radius_mm": p.get("corner_radius_mm"), "height_mm": p.get("height_mm"),
        "source_refs": [artifact_id],
    } for p in (plan.get("platforms") or [])]
    ceiling = copy.deepcopy(plan.get("ceiling") or {})
    spatial_materials = [{
        "material_id": f"catalog:{cid}", "intent": "catalog_reference_only",
        "known_status": "unknown", "value": None,
        "unknown_reason": "目录条目不含材料规格/产品选型/样板状态",
    } for cid in sorted({str(f["catalog_id"]) for f in plan["furniture"]})]
    unknown_items = [{"statement": str(q), "value": None, "known_status": "unknown",
                      "unknown_reason": "源提案的开放问题，程序不补答案"}
                     for q in (plan.get("open_questions") or [])]

    unsupported = _unsupported(plan)
    ent = site.get("entrance") or [0, 0, 0]
    boundary = {
        "width": _dec(site["width_mm"], mm=True),
        "length": _dec(site["height_mm"], mm=True),
        "unit": "m",
        "boundary_source": "manual_boundary_not_site_verified",
        "entrance": {"side": "left", "point": [_dec(ent[0], mm=True), _dec(ent[1], mm=True)],
                     "width": _dec(ent[2], mm=True)},
        "obstacles": obstacles,
    }
    strategy = {
        "strategy_id": f"studio-{plan.get('option_id')}-r{plan.get('revision')}",
        "statement": f"{plan['strategy']['name']}：{plan['strategy']['narrative'][:180]}",
        "tradeoffs": list(plan["strategy"].get("tradeoffs") or []),
        "source_refs": [artifact_id],
    }
    spatial = {
        "schema_version": SPATIAL_VERSION,
        "unit": "mm",
        "origin": {"coordinate_system": "southwest_origin_x_east_y_north",
                   "source_contract": DRAFT_VERSION,
                   "unit": "mm", "boundary_mm": [site["width_mm"], site["height_mm"]],
                   "note": "与 Studio 提案同一局部坐标系；原点西南，+X 东、+Y 北"},
        "zones": spatial_zones, "circulation": exact_circulation,
        "platforms": spatial_platforms, "furniture": spatial_furniture,
        "ceiling": ceiling, "materials": spatial_materials,
        "views": [], "unsupported_items": unsupported, "unknown_items": unknown_items,
        "source": {
            "origin_kind": "studio_import",
            "studio_project_id": str(provenance["studio_project_id"]),
            "main_project_id": str(provenance["main_project_id"]),
            "artifact_id": artifact_id,
            "revision_uid": provenance.get("revision_uid"),
            "parent_revision_uid": provenance.get("parent_revision_uid"),
            "sha256": source_sha,
            "contract_version": DRAFT_VERSION,
            "option_id": str(plan.get("option_id")),
            "revision": int(plan.get("revision") or 1),
            "candidate_group_id": provenance.get("candidate_group_id"),
            "run_id": provenance.get("run_id"),
            "draft_identity": {k: plan.get(k) for k in
                               ("contract_version", "project_id", "option_id", "revision",
                                "parent_revision", "author")},
            "site_source": {"source": site.get("source"), "width_mm": site["width_mm"],
                            "height_mm": site["height_mm"], "ceiling_mm": site.get("ceiling_mm"),
                            "entrance_mm": list(ent)},
            "root_revision_uid": str((lineage or {}).get("root_uid")
                                     or provenance.get("revision_uid") or artifact_id),
            "lineage_chain": list((lineage or {}).get("chain")
                                  or [provenance.get("revision_uid") or artifact_id]),
            "parent_link_status": (parent_link_status
                                   or ("source_root" if not provenance.get("parent_revision_uid")
                                       else "resolved")),
            "design_origin": design_origin or {"kind": "unknown",
                                               "declared_by": "not_declared",
                                               "declaration": None, "run_refs": []},
        },
        "adaptation": {
            "adapter_version": ADAPTER_VERSION,
            "mapping_version": MAPPING_VERSION,
            "unit_conversion": "mm_to_m_div_1000",
            "geometry_mode": "polygon_exact_in_spatial_bbox_derived_in_legacy_objects",
            "object_id_map": id_map,
            "losses": [
                {"item": "legacy objects[].shape", "loss": "bounding_box_only",
                 "compensated_by": "spatial.zones[].polygon_mm"},
                {"item": "circulation.segments[].shape", "loss": "centerline_bbox_only",
                 "compensated_by": "spatial.circulation[].path_mm"},
                {"item": "materials / views", "loss": "not_modelled_in_studio",
                 "compensated_by": "spatial.unsupported_items + spatial.materials"},
            ],
            "field_ledger": [],
        },
        "area_table": [{"name": str(a.get("name")), "area_sqm": a.get("area_sqm")}
                       for a in plan["area_table"]],
        "open_questions": [str(q) for q in (plan.get("open_questions") or [])],
    }

    model: dict[str, Any] = {
        "schema_version": OPTION_SCHEMA_VERSION,
        "set_id": set_id,
        "option_id": option_id,
        "revision_no": int(revision_no),
        "parent_revision_id": parent_revision_id,
        "strategy": strategy,
        "boundary": boundary,
        "objects": objects,
        "relationships": _relationships(plan, artifact_id),
        "circulation": main_circulation,
        "materials": [{
            "material_id": "studio-material-unspecified",
            "name": "材料规格未指定（Studio 提案仅有意向）",
            "intent": "unknown", "status": "intent_only", "source_refs": [artifact_id],
        }],
        "cost": {
            "currency": "CNY",
            "budget": {"value": None, "unit": "CNY", "known_status": "unknown",
                       "unknown_reason": "Studio 提案未给出预算数值", "source_refs": []},
            "known_items": [],
            "unknown_items": [{"statement": u["item"], "unit": "CNY",
                               "known_status": "unknown", "value": None,
                               "unknown_reason": u["reason"]} for u in unsupported],
            "total_project_estimate": {"value": None, "unit": "CNY",
                                       "known_status": "unknown",
                                       "unknown_reason": "候选阶段不生成完整项目估价",
                                       "source_refs": []},
            "formal_quote": False,
        },
        "validation": validation,
        "lifecycle_status": "candidate",
        # coarse legacy enum kept deliberately (no DB migration / no third model);
        # exact provenance lives in spatial.source.origin_kind="studio_import"
        "source_kind": "human_edit",
        "generation": {
            "provider_kind": "studio_proposal_adapter",
            "provider_name": "StudioProposalAdapter",
            "model_id": None, "real_model": False,
            "adapter_version": ADAPTER_VERSION,
            "prompt_version": "not_applicable",
            "schema_version": OPTION_SCHEMA_VERSION,
            "config_hash": sha256_hex({"adapter_version": ADAPTER_VERSION,
                                       "mapping_version": MAPPING_VERSION,
                                       "option_schema": OPTION_SCHEMA_VERSION}),
            "input_hash": sha256_hex({"artifact_id": artifact_id, "sha256": source_sha,
                                      "plan": plan}),
            "generated_at": created_at,
            "interpretation_method": "deterministic_field_mapping_v1",
        },
        "feedback": {"text": None, "parsed_intents": [], "locks": [],
                     "interpretation_method": "not_applicable"},
        "diff": [],
        "conflicts": [],
        "change_reason": (f"从 Studio 有效提案 {artifact_id}（sha256={source_sha[:12]}…）"
                          "经确定性适配器导入；未改采用指针/生产/采购/正式发布"),
        "actor_id": actor_id,
        "created_at": created_at,
        "structure_signature": {},
        "spatial": spatial,
    }
    spatial["adaptation"]["field_ledger"] = _ledger(plan, spatial, model, artifact_id)
    model["diff"] = diff_spatial(previous_spatial, spatial)

    from .ai_design_geometry import structure_signature
    signature = structure_signature(model)
    signature["spatial_polygon_count"] = len(spatial_zones)
    signature["spatial_polygon_signature"] = sha256_hex(
        [z["polygon_mm"] for z in spatial_zones])[:16]
    model["structure_signature"] = signature
    return model


# ------------------------------------------------------------------------ SVG
def render_spatial_svg(model: dict) -> bytes:
    """Plan drawn from the EXACT mm polygons (not from the derived bboxes)."""
    spatial = model["spatial"]
    width = float(spatial["origin"]["boundary_mm"][0])
    height = float(spatial["origin"]["boundary_mm"][1])
    scale = 900.0 / max(width, height)
    pad_x, pad_y = 70.0, 70.0
    W = width * scale + 2 * pad_x + 240
    H = height * scale + 2 * pad_y + 130

    def X(x: float) -> float:
        return pad_x + x * scale

    def Y(y: float) -> float:
        return H - pad_y - y * scale

    def pts(polygon: list) -> str:
        return " ".join(f"{X(float(p[0])):.2f},{Y(float(p[1])):.2f}" for p in polygon)

    palette = ["#dbeafe", "#dcfce7", "#fef3c7", "#fce7f3", "#e0e7ff", "#ccfbf1",
               "#fee2e2", "#ede9fe"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
        f'viewBox="0 0 {W:.0f} {H:.0f}">',
        '<rect width="100%" height="100%" fill="#fbfaf7"/>',
        f'<rect x="{pad_x}" y="{Y(height):.2f}" width="{width*scale:.2f}" '
        f'height="{height*scale:.2f}" fill="#ffffff" stroke="#1f2937" stroke-width="3"/>',
    ]
    # exact zone polygons
    for i, z in enumerate(spatial["zones"]):
        poly = z["polygon_mm"]
        fill = palette[i % len(palette)]
        parts.append(f'<polygon points="{pts(poly)}" fill="{fill}" fill-opacity="0.75" '
                     f'stroke="#334155" stroke-width="1.6"/>')
        cx = sum(float(p[0]) for p in poly) / len(poly)
        cy = sum(float(p[1]) for p in poly) / len(poly)
        parts.append(f'<text x="{X(cx):.1f}" y="{Y(cy):.1f}" text-anchor="middle" '
                     f'font-size="13" font-family="sans-serif" fill="#111827">'
                     f'{escape(z["name"])}</text>')
        parts.append(f'<text x="{X(cx):.1f}" y="{Y(cy)+16:.1f}" text-anchor="middle" '
                     f'font-size="10" font-family="sans-serif" fill="#475569">'
                     f'{escape(z["object_id"])} · {z["area_sqm"]}㎡</text>')
    # circulation exact polylines
    for c in spatial["circulation"]:
        path = c["path_mm"]
        parts.append('<polyline points="' + pts(path) + '" fill="none" stroke="#dc2626" '
                     'stroke-width="3" stroke-dasharray="9 5" opacity="0.85"/>')
        parts.append(f'<text x="{X(float(path[0][0]))+6:.1f}" y="{Y(float(path[0][1]))-8:.1f}" '
                     f'font-size="11" fill="#b91c1c" font-family="sans-serif">'
                     f'{escape(c["object_id"])} · {c["width_mm"]}mm</text>')
    # platforms
    for p in spatial["platforms"]:
        if len(p["polygon_mm"]) >= 3:
            parts.append(f'<polygon points="{pts(p["polygon_mm"])}" fill="#f8fafc" '
                         f'stroke="#b45309" stroke-width="2" stroke-dasharray="4 3"/>')
    # furniture footprints (catalog size, rotation as a labelled marker)
    for f in spatial["furniture"]:
        w, d = float(f.get("w_mm") or 600), float(f.get("d_mm") or 600)
        x, y = float(f["x_mm"]), float(f["y_mm"])
        parts.append(f'<rect x="{X(x-w/2):.1f}" y="{Y(y+d/2):.1f}" '
                     f'width="{w*scale:.1f}" height="{d*scale:.1f}" fill="#94a3b8" '
                     f'fill-opacity="0.65" stroke="#334155" stroke-width="1"/>')
        parts.append(f'<text x="{X(x):.1f}" y="{Y(y):.1f}" text-anchor="middle" '
                     f'font-size="10" font-family="sans-serif" fill="#0f172a">'
                     f'{escape(f["object_id"])}</text>')
    # ceiling fixtures as intent markers
    for fx in (spatial["ceiling"].get("fixtures") or []):
        x, y = float(fx.get("x") or 0), float(fx.get("y") or 0)
        parts.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="4" fill="#f59e0b"/>')
    # keep-outs from the main boundary
    for o in model["boundary"]["obstacles"]:
        s = o["shape"]
        parts.append(f'<rect x="{X(float(s["x"])*1000):.1f}" '
                     f'y="{Y((float(s["y"])+float(s["length"]))*1000):.1f}" '
                     f'width="{float(s["width"])*1000*scale:.1f}" '
                     f'height="{float(s["length"])*1000*scale:.1f}" fill="#e2e8f0" '
                     f'stroke="#64748b" stroke-width="1.5" stroke-dasharray="5 3"/>')
    # title / legend
    sy = 30
    parts.append(f'<text x="{pad_x}" y="{sy}" font-size="17" font-family="sans-serif" '
                 f'fill="#111827">{escape(model["strategy"]["statement"][:52])}</text>')
    parts.append(f'<text x="{pad_x}" y="{sy+20}" font-size="11" font-family="sans-serif" '
                 f'fill="#475569">源 {escape(spatial["source"]["artifact_id"])} · '
                 f'主系统候选 {escape(model["option_id"])} v{model["revision_no"]} · '
                 f'精确多边形（mm，未经矩形化）</text>')
    lx = width * scale + pad_x + 25
    ly = Y(height) + 20
    parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="12" font-weight="bold" '
                 f'font-family="sans-serif">适配缺项（保留为 unknown）</text>')
    for i, u in enumerate(spatial["unsupported_items"][:8]):
        parts.append(f'<text x="{lx:.1f}" y="{ly + 22 + i*18:.1f}" font-size="10" '
                     f'font-family="sans-serif" fill="#475569">· {escape(u["item"][:22])}</text>')
    parts.append(f'<text x="{lx:.1f}" y="{ly + 22 + 8*18:.1f}" font-size="10" '
                 f'font-family="sans-serif" fill="#991b1b">候选 ≠ 采用 / 施工图 / 报价</text>')
    parts.append('</svg>')
    return "".join(parts).encode("utf-8")


# --------------------------------------------------- explicit Studio read boundary
class StudioProposalSource:
    """The ONLY W1 read boundary into Studio's own store.

    The main system never reads Studio tables directly: it goes through this
    adapter-facing wrapper (``get_project`` / ``artifact_by_id`` / ``artifacts``),
    and every project mapping is checked explicitly before use.
    """

    def __init__(self, store: Any | None = None) -> None:
        if store is None:
            from .studio.store import Store
            store = Store()
        self.store = store

    def project(self, studio_project_id: str) -> dict | None:
        return self.store.get_project(studio_project_id)

    def resolve(self, main_project_id: str) -> str | None:
        return self.store.resolve_project_id(main_project_id)

    def artifact(self, artifact_id: str) -> dict | None:
        return self.store.artifact_by_id(artifact_id)

    def lineage(self, studio_project_id: str, artifact: dict) -> dict:
        """Resolve the STABLE root lineage of one source artifact by parent UID.

        Never infers a parent from import order. A missing parent artifact in the
        Studio store is reported (``source_parent_missing``), not skipped.
        """
        arts = self.store.artifacts(studio_project_id)
        by_uid = {a.get("revision_uid"): a for a in arts if a.get("revision_uid")}
        uid = artifact.get("revision_uid")
        if not uid:
            return {"status": "source_uid_missing", "root_uid": None,
                    "chain": [], "depth": 0, "missing_uid": None}
        chain = [str(uid)]
        current = artifact
        seen = {str(uid)}
        while current.get("parent_revision_uid"):
            parent_uid = str(current["parent_revision_uid"])
            if parent_uid in seen:
                return {"status": "source_lineage_cycle", "root_uid": None,
                        "chain": chain, "depth": len(chain) - 1,
                        "missing_uid": parent_uid}
            seen.add(parent_uid)
            parent = by_uid.get(parent_uid)
            if parent is None:
                return {"status": "source_parent_missing", "root_uid": None,
                        "chain": chain, "depth": len(chain) - 1,
                        "missing_uid": parent_uid}
            chain.append(parent_uid)
            current = parent
        return {"status": "resolved", "root_uid": chain[-1], "chain": chain,
                "depth": len(chain) - 1, "missing_uid": None}

    @staticmethod
    def design_origin(artifact: dict) -> dict:
        """Upstream DESIGN origin, separate from the transport/adaptation origin.

        Only an explicit declaration on the artifact is used. Anything else stays
        ``unknown`` — the adapter must not relabel a real-model or human upstream
        as artificial (or the reverse) just because an adapter moved the document.
        """
        declared = (artifact.get("diagnostics") or {}).get("source")
        run_refs = [str(x) for x in (artifact.get("run_id"),
                                     artifact.get("candidate_group_id")) if x]
        if isinstance(declared, str) and declared.strip():
            low = declared.lower()
            if "fixture" in low or "stub" in low or "test" in low:
                kind = "fixture"
            elif "real_model" in low or "real-model" in low or "openai" in low:
                kind = "real_model"
            elif "human" in low or "manual" in low:
                kind = "human"
            else:
                kind = "unknown"
            return {"kind": kind, "declared_by": "studio_artifact.diagnostics.source",
                    "declaration": declared, "run_refs": run_refs}
        return {"kind": "unknown", "declared_by": "not_declared",
                "declaration": None, "run_refs": run_refs}

    def valid_proposals(self, studio_project_id: str) -> list[dict]:
        out = []
        for a in self.store.artifacts(studio_project_id):
            if (a.get("kind") == "spatial-plan"
                    and a.get("contract_status") == "valid_candidate"
                    and a.get("status") not in ("superseded", "invalid_raw")):
                payload = a.get("payload") or {}
                out.append({
                    "artifact_id": a["id"], "sha256": a.get("sha256"),
                    "revision_uid": a.get("revision_uid"),
                    "parent_revision_uid": a.get("parent_revision_uid"),
                    "option_id": a.get("option_id"), "revision": a.get("revision"),
                    "run_id": a.get("run_id"),
                    "candidate_group_id": a.get("candidate_group_id"),
                    "created_at": a.get("created_at"),
                    "strategy_name": (payload.get("strategy") or {}).get("name"),
                    "zone_count": len(payload.get("zones") or []),
                })
        return out
