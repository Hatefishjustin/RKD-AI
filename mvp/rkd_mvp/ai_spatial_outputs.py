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

GENERATOR_VERSION = "rkd-spatial-outputs.v4"
PLAN_VERSION = "rkd-spatial-plan.v4"
SCENE_VERSION = "rkd-spatial-scene.v2"
QUANTITY_VERSION = "rkd-spatial-quantity.v4"
COST_VERSION = "rkd-spatial-cost.v4"
MANIFEST_VERSION = "rkd-spatial-output-manifest.v3"
FINISH_SCOPE_VERSION = "rkd-spatial-finish-scope.v3"
PRESENTATION_VERSION = "rkd-spatial-presentation-fixture.v1"

MM2 = 1_000_000.0

# finish_scope 单位契约：坐标只接受 mm，面积只接受 m2，不做静默换算。
FINISH_SCOPE_COORD_UNITS = {"mm"}
FINISH_SCOPE_AREA_UNITS = {"m2"}
FINISH_SCOPE_DEDUCTION_BASES = {"keepouts_within_scope", "none"}
MAX_COORD_MM = 1_000_000.0        # 单点坐标绝对值上限（1 km），挡住 NaN/inf 与明显错单位
INDEPENDENT_TOL_M2 = 0.001        # 两条计量路径允许的最大差值（1e-3 ㎡）


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
def freeze_input(model: dict, *, project_id: str, option_revision_id: str,
                 presentation: dict | None = None) -> dict:
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
        "views_version": ("presentation_fixture_assumption_v1" if presentation
                          else "derived_camera_assumption_v1"),
        "presentation_version": (presentation or {}).get("schema_version"),
        "presentation_declared_by": (presentation or {}).get("declared_by"),
        "presentation_assumption": bool(presentation),
        "presentation_not_ai_design": True,
        "asset_manifest_sha256": (presentation or {}).get("asset_manifest_sha256"),
        "generator_version": GENERATOR_VERSION,
        "frozen_at": now_iso(),
    }


# -------------------------------------------------------------------- camera
def derive_camera(model: dict, presentation: dict | None = None) -> dict:
    """A deterministic presentation camera, explicitly an ASSUMPTION.

    The Studio proposal has no camera; W2 derives one from the entrance and the
    largest zone. In R4 an explicitly declared fixture camera may replace it —
    still an assumption, never a designed view or a measured fact. A camera
    change must never change a quantity.
    """
    spatial = model["spatial"]
    width_mm = float(spatial["origin"]["boundary_mm"][0])
    height_mm = float(spatial["origin"]["boundary_mm"][1])
    if presentation and presentation.get("cameras"):
        cam = presentation["cameras"][0]
        return {
            "camera_id": cam["object_id"],
            "kind": "eye_level", "assumption": True,
            "presentation_camera": True,
            "assumption_note": "机位来自人工测试假设样板（presentation.cameras[0]），"
                               "不是设计决定的视点，也不是实测机位；只改机位不改工程量",
            "eye_height_mm": cam["eye_height_mm"],
            "position_mm": list(cam["position_mm"]),
            "target_mm": list(cam["target_mm"]),
            "lens_mm": cam["lens_mm"], "sensor_mm": 36,
            "boundary_mm": [width_mm, height_mm],
        }
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


# ------------------------------------------------- independent area (no Shapely)
def _scanline_intervals(points: list, x: float) -> list[tuple[float, float]]:
    """Interior y-intervals of one polygon at abscissa x (even-odd crossings)."""
    crossings: list[float] = []
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        if x1 == x2:
            continue
        if min(x1, x2) < x < max(x1, x2):
            crossings.append(y1 + (y2 - y1) * (x - x1) / (x2 - x1))
    crossings.sort()
    return [(crossings[i], crossings[i + 1]) for i in range(0, len(crossings) - 1, 2)]


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for low, high in sorted(intervals):
        if out and low <= out[-1][1] + 1e-9:
            out[-1][1] = max(out[-1][1], high)
        else:
            out.append([low, high])
    return [(a, b) for a, b in out]


def _subtract(intervals: list[tuple[float, float]],
              holes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result = list(intervals)
    for hole_low, hole_high in holes:
        nxt: list[tuple[float, float]] = []
        for low, high in result:
            if hole_high <= low or hole_low >= high:
                nxt.append((low, high))
                continue
            if low < hole_low:
                nxt.append((low, hole_low))
            if hole_high < high:
                nxt.append((hole_high, high))
        result = nxt
    return result


def _length(intervals: list[tuple[float, float]]) -> float:
    return sum(high - low for low, high in intervals)


def _segments(points: list) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    n = len(points)
    return [((float(points[i][0]), float(points[i][1])),
             (float(points[(i + 1) % n][0]), float(points[(i + 1) % n][1])))
            for i in range(n)]


def _segment_cross_x(a: tuple, b: tuple) -> float | None:
    """两线段真实相交处的 x（含端点接触）；平行/共线返回 None。"""
    (x1, y1), (x2, y2) = a
    (x3, y3), (x4, y4) = b
    denom = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if denom == 0:
        return None
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / denom
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / denom
    if -1e-12 <= t <= 1 + 1e-12 and -1e-12 <= u <= 1 + 1e-12:
        return x1 + t * (x2 - x1)
    return None


def _event_abscissae(polys: list[list[list[float]]]) -> list[float]:
    """条带必须切开的所有 x：顶点 + 边与边的交点。

    只在顶点 x 处切条带是不够的：斜边与扣除区边界相交处，条带内的截面长度
    不再是 x 的线性函数，中点采样会系统性偏差（三角形扣 4.5㎡ 会被算成 6㎡）。
    把交点的 x 也当作断点后，每个条带内截面长度对 x 线性，中点值即精确积分。
    """
    xs: set[float] = set()
    edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for poly in polys:
        pts = [(float(p[0]), float(p[1])) for p in poly]
        if len(pts) < 3:
            continue
        xs.update(x for x, _ in pts)
        edges.extend(_segments(pts))
    for index, (a1, a2) in enumerate(edges):
        low_a, high_a = min(a1[0], a2[0]), max(a1[0], a2[0])
        for b1, b2 in edges[index + 1:]:
            low_b, high_b = min(b1[0], b2[0]), max(b1[0], b2[0])
            if max(low_a, low_b) > min(high_a, high_b):
                continue  # x 区间不相交，不可能有交点
            x = _segment_cross_x((a1, a2), (b1, b2))
            if x is not None and math.isfinite(x):
                xs.add(x)
    return sorted(xs)


def scanline_area(polys: list[list[list[float]]]) -> float:
    """Exact area of the UNION of polygons by vertical-strip integration.

    Deliberately independent of Shapely: strips are cut at every vertex abscissa
    AND every edge-edge crossing, so the slice length is linear inside a strip
    and the mid-point value integrates exactly. No GEOS predicate is reused.
    """
    xs = _event_abscissae(polys)
    total = 0.0
    for a, b in zip(xs, xs[1:]):
        if b - a <= 1e-9:
            continue
        mid = (a + b) / 2.0
        intervals: list[tuple[float, float]] = []
        for poly in polys:
            intervals.extend(_scanline_intervals(poly, mid))
        total += (b - a) * _length(_merge(intervals))
    return total


def scanline_area_minus(polys: list[list[list[float]]],
                        holes: list[list[list[float]]]) -> float:
    """Union(polys) minus Union(holes), same exact strip method.

    Holes never double-deduct (intervals are merged before subtraction) and the
    crossing abscissae of holes against polygon edges are strip breakpoints too.
    """
    if not holes:
        return scanline_area(polys)
    xs = _event_abscissae(polys + holes)
    total = 0.0
    for a, b in zip(xs, xs[1:]):
        if b - a <= 1e-9:
            continue
        mid = (a + b) / 2.0
        inside: list[tuple[float, float]] = []
        for poly in polys:
            inside.extend(_scanline_intervals(poly, mid))
        holes_at: list[tuple[float, float]] = []
        for poly in holes:
            holes_at.extend(_scanline_intervals(poly, mid))
        total += (b - a) * _length(_subtract(_merge(inside), _merge(holes_at)))
    return total


def _polygon_pts(obj: dict) -> list[list[float]]:
    raw = obj.get("polygon_mm")
    if not isinstance(raw, list):
        raise ValueError("polygon_mm 必须是坐标数组")
    pts: list[list[float]] = []
    for index, point in enumerate(raw):
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ValueError(f"polygon_mm[{index}] 必须是 [x, y]")
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError) as error:
            raise ValueError(f"polygon_mm[{index}] 坐标不是数值") from error
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"polygon_mm[{index}] 坐标不是有限数值（NaN/inf）")
        if abs(x) > MAX_COORD_MM or abs(y) > MAX_COORD_MM:
            raise ValueError(f"polygon_mm[{index}] 坐标超出 ±{MAX_COORD_MM:.0f} mm，疑似单位错误")
        pts.append([x, y])
    return pts


def _validated_cut_items(allocation: dict, conflicts: list[dict],
                         parsed: list[dict]) -> tuple[bool, str, list[dict], float]:
    """A FREE-TEXT declaration is never a disambiguation rule.

    The only way to keep two different materials on the SAME layer is to supply
    an explicit, structurally described disjoint allocation that is ACTUALLY
    CUT: each piece must be a valid polygon, pieces must not overlap, their union
    must be exactly the conflicting region (no invented extra area), and each
    piece must stay inside the source faces it cites. Returns the replacement
    area records; the caller then measures those, not the overlapping originals.
    """
    if allocation.get("method") != "explicit_disjoint_cut":
        return False, "material_allocation.method 必须是 explicit_disjoint_cut", [], 0.0
    if not isinstance(allocation.get("declared_by"), str) or not allocation["declared_by"].strip():
        return False, "material_allocation.declared_by 必须标明来源", [], 0.0
    cuts = allocation.get("cuts")
    if not isinstance(cuts, list) or not cuts:
        return False, "material_allocation.cuts 必须是非空数组", [], 0.0
    by_id = {a["object_id"]: a for a in parsed}
    conflict_ids = {oid for c in conflicts for oid in c["objects"]}
    allowed_materials = {by_id[oid]["material_id"] for oid in conflict_ids
                         if oid in by_id}
    source_union = unary_union([
        Polygon([(x, y) for x, y in by_id[oid]["polygon_mm"]])
        for oid in sorted(conflict_ids) if oid in by_id])
    items: list[dict] = []
    seen: set[str] = set()
    for index, cut in enumerate(cuts):
        if not isinstance(cut, dict):
            return False, f"cuts[{index}] 必须是对象", [], 0.0
        oid = str(cut.get("object_id") or "")
        if not oid or oid in seen or oid in by_id:
            return False, f"cuts[{index}].object_id 必须非空、唯一且不得与原对象重名", [], 0.0
        seen.add(oid)
        material_id = str(cut.get("material_id") or "")
        if not material_id or material_id not in allowed_materials:
            return False, (f"cuts[{index}].material_id 必须是参与冲突的材料之一 "
                           f"{sorted(allowed_materials)}"), [], 0.0
        sources = cut.get("source_object_ids")
        if (not isinstance(sources, list) or not sources
                or any(s not in conflict_ids for s in sources)):
            return False, f"cuts[{index}].source_object_ids 必须引用参与冲突的原对象", [], 0.0
        try:
            pts = _polygon_pts(cut)
        except ValueError as error:
            return False, f"cuts[{index}]：{error}", [], 0.0
        if len(pts) < 3:
            return False, f"cuts[{index}] 多边形少于 3 点", [], 0.0
        poly = Polygon([(x, y) for x, y in pts])
        if not poly.is_valid or poly.area <= 0:
            return False, f"cuts[{index}] 不是有效简单多边形", [], 0.0
        src_union = unary_union([
            Polygon([(x, y) for x, y in by_id[s]["polygon_mm"]])
            for s in sources if s in by_id])
        if poly.difference(src_union).area > 1.0:      # > 1 mm² 即视为凭空扩面
            return False, f"cuts[{index}] 超出所引用原材料的几何范围", [], 0.0
        items.append({
            "object_id": oid, "name": str(cut.get("name") or oid),
            "polygon_mm": pts, "material_id": material_id,
            "material_name": cut.get("material_name") or material_id,
            "material_spec_status": cut.get("spec_status") or "unknown",
            "unit": "m2", "layer": str(cut.get("layer") or "floor_finish"),
            "declared_area_m2": round(poly.area / MM2, 4),
            "from_material_allocation": True,
        })
    for index, first in enumerate(items):
        pa = Polygon([(x, y) for x, y in first["polygon_mm"]])
        for second in items[index + 1:]:
            pb = Polygon([(x, y) for x, y in second["polygon_mm"]])
            if pa.intersection(pb).area > 1.0:
                return False, (f"裁切面 {first['object_id']} 与 {second['object_id']} "
                               "仍重叠，不是互斥分配"), [], 0.0
    cut_union = unary_union(
        [Polygon([(x, y) for x, y in item["polygon_mm"]]) for item in items])
    delta_m2 = cut_union.symmetric_difference(source_union).area / MM2
    if delta_m2 > 1e-5:
        return False, (f"裁切并集与冲突区域不等价（对称差 {delta_m2:.6f} ㎡），"
                       "不得据此消歧"), [], delta_m2
    return True, "", items, delta_m2


def normalize_finish_scope(scope: dict | None) -> dict | None:
    """Validate an explicitly declared material-face / paving scope.

    The scope must carry its own provenance: it is the only thing that may turn
    a geometric zone union into a supported finish quantity. Being a manual
    fixture does not excuse it from the contract:

    * coordinates are mm; areas are m2 — anything else is rejected, never silently
      converted (``unit='m'`` / ``unit='ft2'`` used to be accepted and measured
      as if millimetres);
    * every polygon must be finite and a valid simple polygon;
    * object ids must be present and unique; material references are required;
    * overlapping faces of the SAME material on the SAME layer need an explicit
      ``overlap_declaration`` (union, no double counting);
    * overlapping faces of DIFFERENT materials on the SAME layer are a CONFLICT:
      free-text declaration cannot decide which material covers which square
      metre, and ``_finish_quantity`` must never add the two unions into a
      ``known`` total. Only an explicit, geometrically disjoint cut
      (``material_allocation``) that is actually applied may resolve it;
    * genuinely different construction layers are measured as separate groups,
      and their sum is never labelled a single-layer floor net area.
    """
    if scope is None:
        return None
    if not isinstance(scope, dict):
        raise ValueError("finish_scope 必须是对象")
    unit = scope.get("unit") or "mm"
    if not isinstance(unit, str) or unit not in FINISH_SCOPE_COORD_UNITS:
        raise ValueError(
            f"finish_scope.unit 只支持 {sorted(FINISH_SCOPE_COORD_UNITS)}（收到 {unit!r}）；"
            "本批不做单位静默换算")
    deduction_basis = scope.get("deduction_basis") or "keepouts_within_scope"
    if deduction_basis not in FINISH_SCOPE_DEDUCTION_BASES:
        raise ValueError(
            f"finish_scope.deduction_basis 必须是 {sorted(FINISH_SCOPE_DEDUCTION_BASES)}"
            f"（收到 {deduction_basis!r}）；扣除口径必须明确")
    areas = scope.get("areas")
    if not isinstance(areas, list) or not areas:
        raise ValueError("finish_scope.areas 必须是非空数组")
    declared_by = scope.get("declared_by")
    if not isinstance(declared_by, str) or not declared_by:
        raise ValueError("finish_scope.declared_by 必须标明来源（人工/夹具/依据）")
    overlap_declaration = scope.get("overlap_declaration")
    if overlap_declaration is not None and not isinstance(overlap_declaration, str):
        raise ValueError("finish_scope.overlap_declaration 必须是说明文字")
    parsed = []
    seen_ids: set[str] = set()
    for index, area in enumerate(areas):
        if not isinstance(area, dict):
            raise ValueError(f"finish_scope.areas[{index}] 必须是对象")
        try:
            pts = _polygon_pts(area)
        except ValueError as error:
            raise ValueError(f"finish_scope.areas[{index}]：{error}") from error
        if len(pts) < 3:
            raise ValueError(f"finish_scope.areas[{index}] 多边形少于 3 点")
        object_id = str(area.get("object_id") or f"FA{index + 1}")
        if object_id in seen_ids:
            raise ValueError(f"finish_scope 内 object_id 重复：{object_id}")
        seen_ids.add(object_id)
        area_unit = area.get("unit") or "m2"
        if not isinstance(area_unit, str) or area_unit not in FINISH_SCOPE_AREA_UNITS:
            raise ValueError(
                f"finish_scope.areas[{index}].unit 只支持 "
                f"{sorted(FINISH_SCOPE_AREA_UNITS)}（收到 {area_unit!r}）")
        material = area.get("material_ref") or {}
        if not isinstance(material, dict):
            raise ValueError(f"finish_scope.areas[{index}].material_ref 必须是对象")
        if not material.get("material_id") and area.get("material_id"):
            material = {"material_id": area.get("material_id"),
                        "name": area.get("material_name"),
                        "spec_status": area.get("material_spec_status")}
        if not material.get("material_id"):
            raise ValueError(f"finish_scope.areas[{index}] 缺少 material_ref.material_id")
        polygon = Polygon([(x, y) for x, y in pts])
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError(
                f"finish_scope.areas[{index}] 不是有效简单多边形（自交/退化），"
                "不能作为计量依据")
        parsed.append({
            "object_id": object_id,
            "name": str(area.get("name") or f"材料面 {index + 1}"),
            "polygon_mm": pts,
            "material_id": str(material["material_id"]),
            "material_name": material.get("name"),
            "material_spec_status": material.get("spec_status") or "unknown",
            "unit": area_unit,
            "layer": str(area.get("layer") or "floor_finish"),
            "declared_area_m2": round(polygon.area / MM2, 4),
        })
    def _overlaps(items: list[dict]) -> list[dict]:
        found = []
        for index, first in enumerate(items):
            for second in items[index + 1:]:
                if first["layer"] != second["layer"]:
                    continue
                pa = Polygon([(x, y) for x, y in first["polygon_mm"]])
                pb = Polygon([(x, y) for x, y in second["polygon_mm"]])
                if not pa.intersects(pb):
                    continue
                shared = pa.intersection(pb).area / MM2
                if shared > 1e-6:
                    found.append({
                        "layer": first["layer"],
                        "objects": [first["object_id"], second["object_id"]],
                        "material_ids": [first["material_id"], second["material_id"]],
                        "overlap_m2": round(shared, 4),
                        "mixed_material": first["material_id"] != second["material_id"],
                    })
        return found

    declared = bool(isinstance(overlap_declaration, str) and overlap_declaration.strip())
    raw_overlaps = _overlaps(parsed)
    same_material = [o for o in raw_overlaps if not o["mixed_material"]]
    mixed = [o for o in raw_overlaps if o["mixed_material"]]
    # 同材同层：沿用原契约，不给说明就拒绝（W2C2-C1-06 回归护栏）
    if same_material and not declared:
        detail = "；".join(f"{o['layer']}:{'+'.join(o['objects'])}={o['overlap_m2']}㎡"
                          for o in same_material)
        raise ValueError(
            "同层材料面重叠但未声明，不能无说明重复相加：" + detail
            + "。请合并为一块，或用 overlap_declaration 说明叠层语义")

    allocation_applied = None
    allocation_rejected = None
    if mixed:
        allocation = scope.get("material_allocation")
        if isinstance(allocation, dict):
            ok, reason, cut_items, delta = _validated_cut_items(allocation, mixed, parsed)
            if ok:
                conflict_ids = {oid for o in mixed for oid in o["objects"]}
                kept = [a for a in parsed if a["object_id"] not in conflict_ids]
                parsed = kept + cut_items
                allocation_applied = {
                    "declared_by": allocation["declared_by"],
                    "method": "explicit_disjoint_cut",
                    "declaration": allocation.get("declaration"),
                    "cut_count": len(cut_items),
                    "cut_ids": [c["object_id"] for c in cut_items],
                    "replaced_object_ids": sorted(conflict_ids),
                    "coverage_symmetric_difference_m2": round(delta, 8),
                    "note": "裁切面已实际替换重叠原面，几何互斥且等价覆盖，不是文字声明",
                }
                raw_overlaps = _overlaps(parsed)
                same_material = [o for o in raw_overlaps if not o["mixed_material"]]
                mixed = [o for o in raw_overlaps if o["mixed_material"]]
                if same_material and not declared:
                    raise ValueError("裁切后仍存在未声明的同材同层重叠，不能无说明重复相加")
            else:
                allocation_rejected = {"reason": reason,
                                       "note": "结构化分配未通过几何校验，按冲突待核处理"}
        else:
            allocation_rejected = {
                "reason": "没有提供 material_allocation；overlap_declaration 是自由文字，"
                          "不能作为材料分配消歧规则",
                "note": "自由文字说明只保留为留痕，不参与计量",
            }

    conflicts = [{**{k: o[k] for k in ("layer", "objects", "material_ids", "overlap_m2")},
                  "conflict_code": "SAME_LAYER_MIXED_MATERIAL_OVERLAP",
                  "declaration_is_not_disambiguation": declared,
                  "resolution_required": "合并为单一材料面，或给出结构化互斥裁切；"
                                         "否则保持 conflict/待核"}
                 for o in mixed]
    overlaps = [{k: o[k] for k in ("layer", "objects", "overlap_m2")}
                for o in raw_overlaps]
    layer_ids = sorted({a["layer"] for a in parsed})
    layer_note = (f"本切片包含 {len(layer_ids)} 个不同构造层（{'、'.join(layer_ids)}）；"
                  "各层分别计量，合计是多构造层合计，不是单层地坪净面积"
                  if len(layer_ids) > 1 else None)
    return {"schema_version": FINISH_SCOPE_VERSION,
            "kind": scope.get("kind") or "material_face_slice",
            "declared_by": declared_by,
            "declaration": scope.get("declaration"),
            "unit": unit,
            "deduction_basis": deduction_basis,
            "overlap_declaration": overlap_declaration,
            "same_layer_overlaps": overlaps,
            "same_layer_material_conflicts": conflicts,
            "material_allocation_applied": allocation_applied,
            "material_allocation_rejected": allocation_rejected,
            "layer_scope_note": layer_note,
            "site_verified": False,
            "areas": parsed}


def measure(model: dict, *, finish_scope: dict | None = None) -> dict:
    """Deterministic quantities from EXACT polygons.

    Two different things are deliberately kept apart:

    * ``Q-FLOOR-GEOMETRIC-NET`` — geometric net area of the functional zones
      (zones minus keep-outs). Computable, and NOT a finished-floor quantity.
    * ``Q-FLOOR-FINISH`` — supported finish/paving net area. Only known when an
      explicitly sourced material-face scope is supplied; otherwise unknown.

    The independent recompute never reuses the Shapely deduction value: it runs a
    vertical-strip union/subtraction over the raw vertex lists.
    """
    zones = _zone_polygons(model)
    union = unary_union([p for _oid, p in zones])
    keepouts = _keepouts(model)
    keep_polys = [p for _oid, p in keepouts]
    keep_union = unary_union(keep_polys) if keep_polys else None
    deducted = (union.intersection(keep_union).area if keep_union else 0.0)
    gross = union.area
    net = gross - deducted
    bbox_union = unary_union([box(*p.bounds) for _oid, p in zones])
    bbox_gross = bbox_union.area
    bbox_net = bbox_gross - (bbox_union.intersection(keep_union).area
                             if keep_union else 0.0)

    # independent path: raw vertices only, no Shapely geometry objects
    zone_pts = [_polygon_pts(z) for z in model["spatial"]["zones"]]
    keep_pts = []
    for o in model["boundary"]["obstacles"]:
        s = o["shape"]
        x, y = float(s["x"]) * 1000, float(s["y"]) * 1000
        w, l = float(s["width"]) * 1000, float(s["length"]) * 1000
        keep_pts.append([[x, y], [x + w, y], [x + w, y + l], [x, y + l]])
    independent_gross = scanline_area(zone_pts) / MM2
    independent_net = scanline_area_minus(zone_pts, keep_pts) / MM2

    # zone overlap: sum of zones is only equal to the union when zones are disjoint
    overlap = 0.0
    for i, (_oid_a, pa) in enumerate(zones):
        for _oid_b, pb in zones[i + 1:]:
            if pa.intersects(pb):
                overlap += pa.intersection(pb).area
    shoelace_sum = sum(_shoelace_mm2(_polygon_pts(z))
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

    scope = normalize_finish_scope(finish_scope)
    finish_item = _finish_quantity(scope, keep_pts)

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
        {"quantity_id": "Q-FLOOR-GEOMETRIC-NET", "name": "功能分区几何净面积（非完成面工程量）",
         "value": round(net / MM2, 3), "unit": "m2", "known_status": "known",
         "method": "exact_union_minus_keepouts", "formula_version": QUANTITY_VERSION,
         "engineering_status": "geometric_only_not_a_finish_quantity",
         "source_objects": [oid for oid, _p in zones],
         "independent_recompute_m2": round(independent_net, 3),
         "independent_gross_m2": round(independent_gross, 3),
         "independent_method": "vertical_strip_exact_v2",
         "independent_delta_m2": round(independent_net - net / MM2, 4),
         "sum_of_zones_m2": round(shoelace_sum, 3),
         "zone_overlap_m2": round(overlap / MM2, 3),
         "bbox_value_m2": round(bbox_net / MM2, 3),
         "bbox_delta_m2": round((bbox_net - net) / MM2, 3),
         "note": "功能分区并集减保留区；可计算但不等于铺装/饰面完成面范围，"
                 "不得直接流入已知工程量或正式报价。bbox 结果仅证明不能据包围盒计量"},
        finish_item,
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
            "finish_scope": scope,
            "coverage": "只覆盖功能区几何面积与保留区扣除，以及可选的、显式标注来源的材料面切片；"
                        "同层异材重叠按 conflict 待核，不产 known 总量/试算，除非给出"
                        "结构化互斥裁切并实际替换原面；不同构造层分别计量，合计不叫单层净面积；"
                        "隔断/天花/门窗/机电未建模，保持 unknown"}


def _finish_quantity(scope: dict | None, keep_pts: list) -> dict:
    """Supported finish area: EXACT geometry is the business value.

    The strip integration stays as an independent cross-check only. It used to be
    the business value itself, which turned a known-independent error on slanted
    edges into a wrong finish quantity and a wrong trial amount. When the two
    paths disagree beyond ``INDEPENDENT_TOL_M2`` this returns ``disputed`` with no
    value and no priceable groups, instead of a confidently wrong number.
    """
    if scope is None:
        return {"quantity_id": "Q-FLOOR-FINISH", "name": "地坪完成面饰面净面积",
                "value": None, "unit": "m2", "known_status": "unknown",
                "unknown_reason": "功能分区几何净面积不等于铺装/饰面范围；"
                                  "本批没有显式材料面或铺装范围依据，"
                                  "不得据此推出完成面工程量",
                "required_basis": "显式材料面切片（铺装范围 + 材料引用 + 计量单位 + 扣除依据 + 来源）"}
    basis_source = {
        "declared_by": scope["declared_by"],
        "declaration": scope["declaration"],
        "kind": scope["kind"], "unit": scope["unit"],
        "deduction_basis": scope["deduction_basis"],
        "overlap_declaration": scope.get("overlap_declaration"),
        "same_layer_overlaps": scope.get("same_layer_overlaps") or [],
        "same_layer_material_conflicts": scope.get("same_layer_material_conflicts") or [],
        "material_allocation_applied": scope.get("material_allocation_applied"),
        "allocation_applied": scope.get("material_allocation_applied"),
        "material_allocation_rejected": scope.get("material_allocation_rejected"),
        "layer_scope_note": scope.get("layer_scope_note"),
        "site_verified": False,
    }
    conflicts = scope.get("same_layer_material_conflicts") or []
    if conflicts:
        # 同层异材重叠：没有几何互斥裁切就不能决定哪块地铺哪种材料。
        # 两条几何算法都算对各自并集，也不能证明材料分配正确，因此不输出
        # known 总量、不给可试算分组、不试算金额。
        detail = "；".join(
            f"{c['layer']}:{'+'.join(c['objects'])}"
            f"({' / '.join(c['material_ids'])}) 重叠 {c['overlap_m2']}㎡"
            for c in conflicts)
        return {
            "quantity_id": "Q-FLOOR-FINISH",
            "name": "地坪完成面饰面净面积（同层异材冲突，待核）",
            "value": None, "unit": "m2", "known_status": "conflict",
            "conflict_code": "SAME_LAYER_MIXED_MATERIAL_OVERLAP",
            "method": "not_measured_pending_material_allocation",
            "formula_version": QUANTITY_VERSION,
            "source_objects": [a["object_id"] for a in scope["areas"]],
            "basis_source": basis_source,
            "same_layer_material_conflicts": conflicts,
            "material_groups": [],
            "resolution_required": "合并为单一材料面，或提供 material_allocation "
                                   "的结构化互斥裁切并实际替换原面；自由文字说明无效",
            "unknown_reason": "同层异材材料面重叠，未给出几何互斥分配：" + detail
                              + "。若按 (layer, material_id) 分别并集再相加会把同一块"
                                "地坪重复计入 known 工程量，并据此试算金额",
            "note": "冲突保留留痕，value 不填 0；本项待核，不给数值、不给试算分组",
        }
    apply_keepouts = scope["deduction_basis"] != "none"
    keep_polys = [Polygon([(x, y) for x, y in pts]) for pts in keep_pts] if apply_keepouts else []
    keep_union = unary_union(keep_polys) if keep_polys else None
    layers: dict[tuple[str, str], list[dict]] = {}
    for area in scope["areas"]:
        layers.setdefault((area["layer"], area["material_id"]), []).append(area)
    groups: list[dict] = []
    total_exact = 0.0
    worst_delta = 0.0
    for (layer, material_id), areas in sorted(layers.items()):
        polygons = [Polygon([(x, y) for x, y in area["polygon_mm"]]) for area in areas]
        merged = unary_union(polygons)
        exact = merged.area
        if keep_union is not None:
            exact -= merged.intersection(keep_union).area
        exact_m2 = max(0.0, exact / MM2)
        independent_m2 = scanline_area_minus([a["polygon_mm"] for a in areas],
                                             keep_pts if apply_keepouts else []) / MM2
        delta = independent_m2 - exact_m2
        worst_delta = max(worst_delta, abs(delta))
        total_exact += exact_m2
        groups.append({
            "layer": layer, "material_id": material_id,
            "material_name": areas[0]["material_name"],
            "material_spec_status": areas[0]["material_spec_status"],
            "area_m2": round(exact_m2, 3),
            "independent_recompute_m2": round(independent_m2, 3),
            "independent_delta_m2": round(delta, 4),
            "independent_method": "vertical_strip_exact_v2",
            "area_objects": [a["object_id"] for a in areas],
            "method": "exact_union_per_material_minus_keepouts",
        })
    disputed = worst_delta > INDEPENDENT_TOL_M2
    layer_ids = sorted({g["layer"] for g in groups})
    multi_layer = len(layer_ids) > 1
    layer_breakdown = [{"layer": layer,
                        "area_m2": round(sum(g["area_m2"] for g in groups
                                             if g["layer"] == layer), 3)}
                       for layer in layer_ids]
    if disputed:
        return {"quantity_id": "Q-FLOOR-FINISH", "name": "地坪完成面饰面净面积（按材料面切片）",
                "value": None, "unit": "m2", "known_status": "disputed",
                "method": "declared_finish_scope_minus_keepouts",
                "formula_version": QUANTITY_VERSION,
                "source_objects": [a["object_id"] for a in scope["areas"]],
                "basis_source": basis_source,
                "material_groups": groups,
                "discrepancy_m2": round(worst_delta, 4),
                "discrepancy_tolerance_m2": INDEPENDENT_TOL_M2,
                "unknown_reason": f"精确几何与独立条带复算相差 {worst_delta:.4f} ㎡，"
                                  f"超过容差 {INDEPENDENT_TOL_M2} ㎡；两条可信路径不一致时"
                                  "不输出已知饰面量，也不据此试算金额",
                "note": "材料面切片来自声明来源，未经现场复核；本项待核，不给数值"}
    return {"quantity_id": "Q-FLOOR-FINISH",
            "name": ("各构造层饰面面积合计（非单层地坪净面积）" if multi_layer
                     else "地坪完成面饰面净面积（按材料面切片）"),
            "value": round(total_exact, 3), "unit": "m2", "known_status": "known",
            "method": "exact_union_per_material_minus_keepouts",
            "formula_version": QUANTITY_VERSION,
            "quantity_kind": "multi_layer_sum" if multi_layer else "single_layer_net",
            "layer_breakdown": layer_breakdown,
            "layer_scope_note": scope.get("layer_scope_note"),
            "source_objects": [a["object_id"] for a in scope["areas"]],
            "basis_source": basis_source,
            "material_groups": groups,
            "independent_max_delta_m2": round(worst_delta, 4),
            "independent_tolerance_m2": INDEPENDENT_TOL_M2,
            "note": ("面积来自人工/夹具标注的材料面切片，未经现场复核；"
                     "材料规格与产品选型仍为假设，单价缺失时金额保持 unknown。"
                     + ("本项合计跨多个不同构造层，仅作分层计量对账，"
                        "不得当作单层地坪净面积或据此汇总单层报价。"
                        if multi_layer else ""))}


# --------------------------------------------------------------------- cost
def build_cost(quantities: dict, *, settings: dict | None = None) -> dict:
    """A cost draft. An amount is only shown when BOTH the area basis and an
    explicit ASSUMPTION unit price exist; it is never a quote."""
    settings = settings or {}
    finish = next((q for q in quantities["items"]
                   if q["quantity_id"] == "Q-FLOOR-FINISH"), None)
    groups = (finish or {}).get("material_groups") or []
    prices = settings.get("material_unit_prices")
    prices = prices if isinstance(prices, dict) else {}
    legacy_price = settings.get("floor_unit_price_cny")
    if (not prices and isinstance(legacy_price, (int, float))
            and not isinstance(legacy_price, bool) and legacy_price > 0 and groups):
        prices = {groups[0]["material_id"]: legacy_price}
    basis = {"area_basis": "unknown", "unit_prices": "unknown", "loss_rate": "unknown",
             "labor_and_process": "unknown",
             "tax_rate": "user_confirmed_but_not_applied_without_price_source",
             "markup": "user_confirmed_but_not_applied_without_price_source"}
    known_items: list[dict] = []
    unknown: list[dict] = []
    finish_status = (finish or {}).get("known_status")
    if finish_status == "disputed":
        basis["area_basis"] = "two_paths_disagree"
        unknown.append({
            "statement": "饰面面积的两条独立计量路径结果不一致（相差 "
                         f"{(finish or {}).get('discrepancy_m2')} ㎡），本批不给已知饰面量",
            "quantity_ref": "Q-FLOOR-FINISH",
            "impact": "即使给了单价也不试算金额；待核清几何后再出数"})
    elif finish_status == "conflict":
        basis["area_basis"] = "same_layer_material_conflict"
        conflicts = (finish or {}).get("same_layer_material_conflicts") or []
        basis["conflict_count"] = len(conflicts)
        unknown.append({
            "statement": "同层异材材料面重叠（"
                         + "；".join(f"{c['layer']}:{'+'.join(c['objects'])}"
                                    f"={c['overlap_m2']}㎡" for c in conflicts)
                         + "）：自由文字声明不能决定材料分配，需结构化互斥裁切或待核",
            "quantity_ref": "Q-FLOOR-FINISH",
            "impact": "不输出已知饰面量，也不给可试算分组；即使给了单价也不试算金额"})
        unknown.append({
            "statement": "材料分配冲突未解决，相关材料金额全部保持 unknown",
            "quantity_ref": "Q-FLOOR-FINISH",
            "impact": "assumption_trial_total_cny 保持 None，不填 0"})
    elif finish_status != "known" or not groups:
        basis["area_basis"] = "missing_finish_scope"
        unknown.append({"statement": "地坪完成面铺装范围/材料面未提供，面积依据 unknown",
                        "quantity_ref": "Q-FLOOR-FINISH",
                        "impact": "即使给了单价也不试算金额，避免用假设单价掩盖未知范围"})
    else:
        basis["area_basis"] = (finish.get("basis_source") or {}).get("declared_by") or "declared"
        for group in groups:
            price = prices.get(group["material_id"])
            ref = f"Q-FLOOR-FINISH/{group['material_id']}"
            if group.get("layer") and group["layer"] != "floor_finish":
                ref = f"{ref}@{group['layer']}"
            if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
                known_items.append({
                    "item": f"{group.get('material_name') or group['material_id']}"
                            f"（按输入假设单价试算）",
                    "material_id": group["material_id"],
                    "layer": group.get("layer"),
                    "quantity_ref": ref,
                    "quantity_m2": group["area_m2"], "unit_price_cny": price,
                    "amount_cny": round(group["area_m2"] * price, 2),
                    "basis": "caller_provided_assumption_not_a_quote",
                    "area_basis_source": basis["area_basis"],
                    "note": "面积来自标注来源的材料面切片；单价由调用方作为假设输入，"
                            "不是价源、不是报价、不含损耗与工艺",
                })
            else:
                unknown.append({
                    "statement": f"{group.get('material_name') or group['material_id']}"
                                 f" 没有对应价源（材料/工艺/损耗/起订量）",
                    "material_id": group["material_id"],
                    "quantity_ref": ref,
                    "impact": f"{group['area_m2']} ㎡ 的金额保持 unknown"})
        basis["unit_prices"] = ("partially_provided_by_caller_assumption" if known_items
                                else "not_provided")
    unknown.extend([
        {"statement": "隔断、天花、门窗工程量未建模", "quantity_ref": "Q-PARTITION-LENGTH",
         "impact": "相关金额保持 unknown"},
        {"statement": "税率与成本加成虽有用户口径，但没有价源，本批不做合计试算",
         "quantity_ref": None, "impact": "不输出项目合计金额"},
    ])
    return {
        "schema_version": COST_VERSION, "currency": "CNY",
        "known_items": known_items,
        "unknown_items": unknown,
        "assumption_trial_total_cny": (round(sum(i["amount_cny"] for i in known_items), 2)
                                       if known_items else None),
        "total_project_estimate": {"value": None, "known_status": "unknown",
                                   "unknown_reason": "没有价源；不把地坪小计当项目总造价"},
        "formal_quote": False,
        "pricing_basis": basis,
        "note": ("本页金额全部为调用方假设单价的试算，不是报价；" if known_items
                 else "本页没有金额：面积依据或价源缺失；") + "金额一律不填 0",
    }


def cost_html(cost: dict, quantities: dict) -> bytes:
    qmap = {q["quantity_id"]: q for q in quantities["items"]}
    known_rows = "".join(
        f"<tr><td>{escape(i['item'])}</td>"
        f"<td>{escape(str(i.get('material_id') or '-'))}</td>"
        f"<td>{i['quantity_m2']} ㎡</td><td>{i['unit_price_cny']}</td>"
        f"<td>{i['amount_cny']}</td>"
        f"<td>{escape(i.get('area_basis_source') or 'unknown')}</td></tr>"
        for i in cost["known_items"])
    unknown_rows = "".join(
        f"<tr><td>{escape(u['statement'])}</td><td>{escape(str(u.get('quantity_ref') or '-'))}</td>"
        f"<td>{escape(u['impact'])}</td></tr>" for u in cost["unknown_items"])
    qrows = "".join(
        f"<tr><td>{escape(q['name'])}</td><td>{'' if q['value'] is None else q['value']}</td>"
        f"<td>{escape(q['unit'])}</td><td>{escape(q['known_status'])}</td></tr>"
        for q in quantities["items"])
    finish = qmap.get("Q-FLOOR-FINISH") or {}
    scope = finish.get("basis_source") or {}
    if cost["known_items"]:
        headline = ("以下金额是<b>假设单价试算</b>，面积依据同时列出；不是报价、不是合同、"
                    "不含损耗/工艺/税，采购与发布未触发。")
    elif finish.get("known_status") == "disputed":
        headline = ("本页没有金额：饰面面积的两条独立计量路径不一致（相差 "
                    f"{finish.get('discrepancy_m2')} ㎡，超过容差 "
                    f"{finish.get('discrepancy_tolerance_m2')} ㎡），<b>待核</b>；"
                    "不输出已知饰面量，也不据其试算，金额一律不填 0。")
    elif finish.get("known_status") == "conflict":
        headline = ("本页没有金额：<b>同层异材材料面重叠冲突，待核</b>。"
                    "自由文字声明不能当材料分配消歧规则，两条几何算法同时算对各自并集"
                    "也不能证明分配正确；不输出已知饰面量、不给可试算分组，"
                    "即使给了假设单价也不试算，金额一律不填 0。")
    else:
        headline = ("本页没有金额：面积依据或价源缺失，所有金额保持 unknown。"
                    "不把几何净量当作造价，也不把草案当报价或合同。")
    scope_note = ("材料面来源：{}；说明：{}；现场复核：未做".format(
        escape(str(scope.get("declared_by") or "unknown")),
        escape(str(scope.get("declaration") or "未声明"))) if scope
        else "材料面来源：未提供（完成面工程量 unknown）")
    conflict_rows = "".join(
        f"<li>{escape(c['layer'])}：{escape('+'.join(c['objects']))}"
        f"（{escape(' / '.join(c['material_ids']))}）重叠 {c['overlap_m2']} ㎡</li>"
        for c in (finish.get("same_layer_material_conflicts") or []))
    conflict_note = (f'<div class="warn"><b>冲突明细（待核，不试算）</b><ul>{conflict_rows}</ul>'
                     '请合并为单一材料面，或给出结构化互斥裁切；自由文字声明无效。</div>'
                     if conflict_rows else "")
    empty_known = '<tr><td colspan="6">无（面积依据或价源缺失）</td></tr>'
    html = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>成本缺项表（草案）</title>
<style>body{{font:14px/1.6 system-ui,"Microsoft YaHei",sans-serif;margin:32px;color:#1f2937}}
h1{{font-size:20px}}table{{border-collapse:collapse;width:100%;margin:12px 0 24px}}
th,td{{border:1px solid #d7dee6;padding:6px 8px;text-align:left}}th{{background:#f1f5f9}}
.warn{{background:#fff7ed;border-left:4px solid #c2410c;padding:10px 12px}}
.scope{{background:#f8fafc;border-left:4px solid #64748b;padding:8px 12px;font-size:13px}}</style>
<h1>成本缺项表 · 草案（非正式报价）</h1>
<div class="warn">{headline}</div>
<div class="scope">{scope_note}</div>
{conflict_note}
<h2>数量（按来源标注）</h2><table><thead><tr><th>项目</th><th>数值</th><th>单位</th><th>状态</th></tr></thead>
<tbody>{qrows}</tbody></table>
<h2>假设单价试算（非报价）</h2><table><thead><tr><th>项目</th><th>材料</th><th>面积</th>
<th>假设单价</th><th>金额</th><th>面积依据来源</th></tr></thead>
<tbody>{known_rows or empty_known}</tbody></table>
<h2>金额缺项</h2><table><thead><tr><th>缺项</th><th>关联量</th><th>影响</th></tr></thead>
<tbody>{unknown_rows}</tbody></table>
<p>正式报价：关闭。外部下单/付款：未发生。</p></html>"""
    return html.encode("utf-8")


# --------------------------------------------------------------------- plan
def _fmt_mm(value: float) -> str:
    return f"{value:.0f}"


def rounded_polygon_2d(points_mm: list, radius_mm: float,
                       segments: int = 8) -> list[list[float]]:
    """Quadratic-Bezier corner rounding of a planar polygon (mm).

    The SAME rounding is used by the readable plan and by the Blender renderer,
    so ``platforms[].corner_radius_mm`` does not silently become a box in 3D.
    """
    pts = [(float(p[0]), float(p[1])) for p in points_mm]
    n = len(pts)
    if n < 3 or radius_mm <= 0:
        return [[x, y] for x, y in pts]
    out: list[list[float]] = []
    for i in range(n):
        px, py = pts[(i - 1) % n]
        cx, cy = pts[i]
        nx, ny = pts[(i + 1) % n]
        v1x, v1y = px - cx, py - cy
        v2x, v2y = nx - cx, ny - cy
        l1, l2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
        if l1 < 1e-6 or l2 < 1e-6:
            out.append([cx, cy])
            continue
        r = min(radius_mm, l1 * 0.45, l2 * 0.45)
        ax, ay = cx + v1x / l1 * r, cy + v1y / l1 * r
        bx, by = cx + v2x / l2 * r, cy + v2y / l2 * r
        for j in range(segments + 1):
            t = j / segments
            out.append([(1 - t) ** 2 * ax + 2 * (1 - t) * t * cx + t ** 2 * bx,
                        (1 - t) ** 2 * ay + 2 * (1 - t) * t * cy + t ** 2 * by])
    return out


def _plan_enclosure_parts(presentation: dict, X, Y, pts, scale: float) -> list[str]:
    """Walls / openings / partitions drawn from the SAME presentation objects
    (id + thickness + width + height) that the Blender scene consumes."""
    out: list[str] = []
    walls = presentation["walls"] + presentation["partitions"]
    by_id = {w["object_id"]: w for w in walls}
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
        out.append(f'<polygon points="{pts(poly)}" fill="{colour}" '
                   f'fill-opacity="0.92" stroke="#1c1917" stroke-width="0.8"/>')
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        out.append(f'<text x="{X(mx):.1f}" y="{Y(my):.1f}" text-anchor="middle" '
                   f'font-size="8" fill="#ffffff">{escape(w["object_id"])} '
                   f'{_fmt_mm(w["thickness_mm"])}mm</text>')
    for o in presentation["openings"]:
        host = by_id.get(o["wall_object_id"])
        if host is None:
            continue
        (x1, y1), (x2, y2) = host["segment_mm"]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux
        cx, cy = o["center_mm"]
        half_w, half_t = o["width_mm"] / 2, host["thickness_mm"] / 2 + 30
        a = [cx - ux * half_w - nx * half_t, cy - uy * half_w - ny * half_t]
        b = [cx + ux * half_w - nx * half_t, cy + uy * half_w - ny * half_t]
        c = [cx + ux * half_w + nx * half_t, cy + uy * half_w + ny * half_t]
        d = [cx - ux * half_w + nx * half_t, cy - uy * half_w + ny * half_t]
        out.append(f'<polygon points="{pts([a, b, c, d])}" fill="#ffffff" '
                   f'stroke="#1c1917" stroke-width="0.6"/>')
        if o["kind"] == "window":
            for offset in (-half_t * 0.35, half_t * 0.35):
                p1 = [cx - ux * half_w + nx * offset, cy - uy * half_w + ny * offset]
                p2 = [cx + ux * half_w + nx * offset, cy + uy * half_w + ny * offset]
                out.append(f'<line x1="{X(p1[0]):.1f}" y1="{Y(p1[1]):.1f}" '
                           f'x2="{X(p2[0]):.1f}" y2="{Y(p2[1]):.1f}" '
                           f'stroke="#0369a1" stroke-width="1.4"/>')
        else:
            hinge = [cx - ux * half_w, cy - uy * half_w]
            leaf = [hinge[0] + nx * o["width_mm"], hinge[1] + ny * o["width_mm"]]
            out.append(f'<line x1="{X(hinge[0]):.1f}" y1="{Y(hinge[1]):.1f}" '
                       f'x2="{X(leaf[0]):.1f}" y2="{Y(leaf[1]):.1f}" '
                       f'stroke="#a16207" stroke-width="1.6"/>')
            arc_end = [cx + ux * half_w, cy + uy * half_w]
            out.append(f'<path d="M {X(arc_end[0]):.1f} {Y(arc_end[1]):.1f} '
                       f'A {o["width_mm"]*scale:.1f} {o["width_mm"]*scale:.1f} 0 0 1 '
                       f'{X(leaf[0]):.1f} {Y(leaf[1]):.1f}" fill="none" '
                       f'stroke="#a16207" stroke-width="1" stroke-dasharray="3 3"/>')
        # 图上只放短编号，完整 width×height×窗台高度放到下方「门窗洞口表」，
        # 避免入口区域多组长文字互相压叠（不靠缩小字号隐藏重叠）。
        short = o["object_id"].replace("R4-", "")
        label = [cx + nx * (host["thickness_mm"] + 330),
                 cy + ny * (host["thickness_mm"] + 330)]
        out.append(f'<text x="{X(label[0]):.1f}" y="{Y(label[1]):.1f}" '
                   f'text-anchor="middle" font-size="8.5" fill="#1e3a8a">'
                   f'{escape(short)}</text>')
    return out


def _plan_furniture_parts(presentation: dict, X, Y, pts) -> list[str]:
    """Catalog furniture with REAL asset dimensions, same ids as the scene."""
    out: list[str] = []
    for f in presentation["furniture"]:
        dims = f.get("asset_dimensions_mm") or [600.0, 600.0, 750.0]
        w, d = float(dims[0]), float(dims[1])
        x, y = f["position_mm"]
        rot = math.radians(f["rotation_deg"])
        corners = []
        for dx, dy in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)):
            corners.append([x + dx * math.cos(rot) - dy * math.sin(rot),
                            y + dx * math.sin(rot) + dy * math.cos(rot)])
        stroke = "#0f766e" if not f["placeholder"] else "#b45309"
        fill = "#d1fae5" if not f["placeholder"] else "#fef3c7"
        dash = "" if not f["placeholder"] else ' stroke-dasharray="3 2"'
        out.append(f'<polygon points="{pts(corners)}" fill="{fill}" fill-opacity="0.85" '
                   f'stroke="{stroke}" stroke-width="1.1"{dash}/>')
        short = (f["object_id"] if len(f["object_id"]) <= 5
                 else "P" + f["object_id"].split("-")[-1])
        out.append(f'<text x="{X(x):.1f}" y="{Y(y)+3:.1f}" text-anchor="middle" '
                   f'font-size="8" fill="#134e4a">{escape(short)}</text>')
    return out


def build_plan_svg(model: dict, camera: dict, quantities: dict,
                   presentation: dict | None = None) -> bytes:
    """A readable concept plan: polygons, furniture, circulation, dimensions,
    legend, area table, camera marker and explicit missing items."""
    spatial = model["spatial"]
    width = float(spatial["origin"]["boundary_mm"][0])
    height = float(spatial["origin"]["boundary_mm"][1])
    draw_w, draw_h = 880.0, 640.0
    scale = min(draw_w / width, draw_h / height)
    ox, oy = 80.0, 110.0
    W = ox + width * scale + 330
    H = oy + height * scale + (330 if presentation else 110)

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
    if presentation:
        parts.extend(_plan_enclosure_parts(presentation, X, Y, pts, scale))
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
            plan_outline = (rounded_polygon_2d(p["polygon_mm"],
                                               float(p.get("corner_radius_mm") or 0))
                            if p.get("corner_radius_mm") else p["polygon_mm"])
            parts.append(f'<polygon points="{pts(plan_outline)}" fill="#f8fafc" '
                         f'fill-opacity="0.6" stroke="#b45309" stroke-width="2" '
                         f'stroke-dasharray="5 3"/>')
            if p.get("corner_radius_mm"):
                cx = sum(float(q[0]) for q in p["polygon_mm"]) / len(p["polygon_mm"])
                cy = sum(float(q[1]) for q in p["polygon_mm"]) / len(p["polygon_mm"])
                parts.append(f'<text x="{X(cx):.1f}" y="{Y(cy)+16:.1f}" '
                             f'text-anchor="middle" font-size="9" fill="#b45309">'
                             f'{escape(p["object_id"])} 圆角 R{_fmt_mm(p["corner_radius_mm"])}'
                             f'（平面/三维同一圆角轮廓）</text>')
    if presentation:
        parts.extend(_plan_furniture_parts(presentation, X, Y, pts))
    else:
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
        if not presentation:
            mx, my = (float(path[0][0]) + float(path[1][0])) / 2, \
                     (float(path[0][1]) + float(path[1][1])) / 2
            parts.append(f'<text x="{X(mx):.1f}" y="{Y(my)-6:.1f}" font-size="10" '
                         f'fill="#b91c1c">动线 {escape(c["object_id"])} · '
                         f'{c["width_mm"]}mm</text>')
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
    if not presentation:
        parts.append(f'<text x="{X(ex)+10:.1f}" y="{Y(ey)-8:.1f}" font-size="10" '
                     f'fill="#5b21b6">C1 人眼 1.5m · 24mm（推导机位，非设计视点）</text>')
    if presentation:
        vx, vy = tx - ex, ty - ey
        angle0 = math.atan2(vy, vx)
        half_angle = math.degrees(math.atan(18.0 / max(cam["lens_mm"], 1)))
        reach = min(width, height) * 0.55
        for sign in (-1, 1):
            ang = angle0 + math.radians(sign * half_angle)
            parts.append(f'<line x1="{X(ex):.1f}" y1="{Y(ey):.1f}" '
                         f'x2="{X(ex + reach * math.cos(ang)):.1f}" '
                         f'y2="{Y(ey + reach * math.sin(ang)):.1f}" '
                         f'stroke="#7c3aed" stroke-width="1" stroke-dasharray="6 4"/>')
        parts.append(f'<text x="{X(ex)+10:.1f}" y="{Y(ey)+10:.1f}" font-size="9" '
                     f'fill="#5b21b6">{escape(str(cam["camera_id"]))} · 人眼 '
                     f'{cam["eye_height_mm"]/1000:.2f}m · {cam["lens_mm"]}mm'
                     f'（人工假设机位，视锥示意）</text>')
        window_by_id = {o["object_id"]: o for o in presentation["openings"]}
        for win in presentation["lighting"]["window_opening_ids"]:
            o = window_by_id.get(win)
            if not o:
                continue
            cx, cy = o["center_mm"]
            inward = [width / 2 - cx, height / 2 - cy]
            n = math.hypot(*inward) or 1.0
            parts.append(f'<line x1="{X(cx):.1f}" y1="{Y(cy):.1f}" '
                         f'x2="{X(cx + inward[0]/n * 2200):.1f}" '
                         f'y2="{Y(cy + inward[1]/n * 2200):.1f}" '
                         f'stroke="#0284c7" stroke-width="1.4" stroke-dasharray="5 3"/>')
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
    if presentation:
        parts.append(f'<text x="{ox}" y="92" font-size="10.5" fill="#9a3412">'
                     f'表达层：墙/门窗/隔断/材质/家具/机位/灯光均为人工测试假设，'
                     f'非现场事实、非 AI 自动设计；照明示意，不宣称照度合规</text>')
    # legend
    lx = ox + width * scale + 60
    ly = oy + 10
    parts.append(f'<text x="{lx}" y="{ly}" font-size="13" font-weight="700" fill="#111827">图例</text>')
    legend = [("#dbeafe", "功能分区（多边形，非墙体）"), ("#cbd5e1", "家具（目录尺寸）"),
              ("#dc2626", "主动线（净宽 mm）"), ("#f59e0b", "灯具点位（意向）"),
              ("#7c3aed", "人眼机位（推导）"), ("url(#keepout)", "保留区（扣除）")]
    if presentation:
        circulation_width = (spatial["circulation"][0]["width_mm"]
                             if spatial.get("circulation") else "unknown")
        legend[2] = ("#dc2626", f"主动线（净宽 {circulation_width}mm）")
        legend[4] = ("#7c3aed", "人眼机位（人工假设视点）")
        legend += [("#3f3f46", "周界墙（人工假设厚度/高度）"),
                   ("#78716c", "隔断（显式对象，非分区边界）"),
                   ("#ffffff", "门洞 + 门扇弧线（宽度标注）"),
                   ("#0369a1", "窗洞口 + 窗光方向（假设）"),
                   ("#d1fae5", "CC0 家具（真实目录尺寸）"),
                   ("#fef3c7", "无对应资产：明确占位"),
                   ("#7c3aed", "人眼机位 + 视锥（人工假设）"),
                   ("#94a3b8", "灯具/灯槽意向（非照度结论）")]
        for mat in presentation["materials"]:
            legend.append((mat["hex"],
                           f'材质 {mat["name"]}（{mat["slot"]}，CC0 贴图意向）'))
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
    net_item = next(q for q in quantities["items"]
                    if q["quantity_id"] == "Q-FLOOR-GEOMETRIC-NET")
    base_y = ty + 38 + len(spatial["zones"]) * 18 + 8
    parts.append(f'<text x="{lx}" y="{base_y}" font-size="10" '
                 f'font-weight="600" fill="#0f172a">功能分区几何净面积</text>')
    parts.append(f'<text x="{lx+250}" y="{base_y}" font-size="10" '
                 f'text-anchor="end" font-weight="600" fill="#0f172a">{net_item["value"]} ㎡</text>')
    parts.append(f'<text x="{lx}" y="{base_y+14}" font-size="9" fill="#b91c1c">'
                 f'（几何量，不是铺装/完成面工程量）</text>')
    finish_item = next(q for q in quantities["items"] if q["quantity_id"] == "Q-FLOOR-FINISH")
    conflict = finish_item.get("known_status") == "conflict"
    finish_display = ("conflict/待核" if conflict else
                      finish_item["value"] if finish_item["value"] is not None else "unknown")
    parts.append(f'<text x="{lx}" y="{base_y+30}" font-size="10" fill="#0f172a">'
                 f'地坪完成面饰面净面积</text>')
    parts.append(f'<text x="{lx+250}" y="{base_y+30}" font-size="10" text-anchor="end" '
                 f'fill="#0f172a">{finish_display}'
                 f'{" ㎡" if finish_item["value"] is not None else ""}</text>')
    if conflict:
        parts.append(f'<text x="{lx}" y="{base_y+44}" font-size="9" fill="#b91c1c">'
                     f'（同层异材冲突，待核；不填 0、不试算）</text>')
    elif finish_item["value"] is None:
        parts.append(f'<text x="{lx}" y="{base_y+44}" font-size="9" fill="#b91c1c">'
                     f'（没有材料面/铺装范围依据，不填 0）</text>')
    # missing items
    my = base_y + 62
    parts.append(f'<text x="{lx}" y="{my}" font-size="12" font-weight="700" fill="#b91c1c">'
                 f'未建模 / 缺项</text>')
    if presentation:
        missing = (["墙体/门窗/隔断/材质/家具/机位为人工测试假设，非现场事实"]
                   + list(presentation["missing"])[:7])
    else:
        missing = ["墙体构造与门窗（未建模，不画框线冒充）", "洁具（未建模）",
                   "隔断构件与长度（未建模）", "天花吊顶构造（只有灯槽意向）",
                   "照度/配光（未计算）", "材料规格与产品选型（unknown）"]
    for i, text in enumerate(missing):
        parts.append(f'<text x="{lx}" y="{my+18+i*16}" font-size="9.5" fill="#7f1d1d">'
                     f'· {escape(text)}</text>')
    if presentation:
        table_y = oy + height * scale + 34
        parts.append(f'<text x="{ox}" y="{table_y}" font-size="12" font-weight="700" '
                     f'fill="#111827">门窗洞口表（人工测试假设，单位 mm；完整尺寸不压在图面上）</text>')
        for i, op in enumerate(presentation["openings"]):
            col, row = i % 2, i // 2
            tx = ox + col * 430
            ty = table_y + 20 + row * 15
            parts.append(f'<text x="{tx}" y="{ty}" font-size="9.5" fill="#334155">'
                         f'{escape(op["object_id"])} · {op["kind"]} · '
                         f'{_fmt_mm(op["width_mm"])}×{_fmt_mm(op["height_mm"])} · '
                         f'窗台 {_fmt_mm(op["sill_mm"])}</text>')
        parts.append(f'<text x="{ox}" y="{table_y + 20 + ((len(presentation["openings"])+1)//2)*15 + 8}" '
                     f'font-size="9.5" fill="#b91c1c">'
                     f'墙体厚度/高度、洞口尺寸均为人工假设，未现场复核；图上粗线为围合，不是施工墙体</text>')
    parts.append('</svg>')
    return "".join(parts).encode("utf-8")


# -------------------------------------------------------------------- scene
def build_scene(model: dict, camera: dict, presentation: dict | None = None) -> dict:
    """Blender scene spec in metres; coordinates and sizes come from the model.

    With a presentation fixture the SAME object ids and mm dimensions that draw
    the readable plan are carried into ``enclosure`` / ``presentation``; the
    renderer converts them to metres. Nothing here is invented from a zone edge.
    """
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
                              "name": p.get("name"),
                              "kind": p.get("kind"),
                              "corner_radius_m": (m(p["corner_radius_mm"])
                                                  if p.get("corner_radius_mm") else None),
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
    out = {
        "schema_version": SCENE_VERSION,
        "unit": "m",
        "boundary": {"width_m": m(width_mm), "length_m": m(height_mm),
                     "ceiling_m": m(spatial["source"].get("site_source", {}).get("ceiling_mm") or 3000)},
        "zones": zones, "furniture": furniture, "platforms": platforms,
        "keepouts": keepouts, "fixtures": fixtures,
        # Blender convention: [x, y, z] with z up.
        "camera": {"position": [m(camera["position_mm"][0]), m(camera["position_mm"][1]),
                                m(camera.get("eye_height_mm") or 1500)],
                   "target": [m(camera["target_mm"][0]), m(camera["target_mm"][1]), 1.2],
                   "lens_mm": camera["lens_mm"],
                   "eye_height_m": m(camera.get("eye_height_mm") or 1500),
                   "camera_id": camera.get("camera_id"),
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
    if presentation:
        role_to_material = {role: mat for mat in presentation["materials"]
                            for role in mat["zone_roles"]}
        default_material = presentation["materials"][0]
        for zone, source in zip(zones, spatial["zones"]):
            mat = role_to_material.get(str(source.get("role") or ""), default_material)
            zone["material_id"] = mat["material_id"]
            zone["material_slot"] = mat["slot"]
            zone["material_source"] = "presentation_fixture_assumption"
        textures = {mat["slot"]: f'pbr/{mat["slot"]}'
                    for mat in presentation["materials"]}
        asset_models = {f["asset_id"]: f'models/{f["asset_id"]}/{f["asset_id"]}.gltf'
                        for f in presentation["furniture"] if f["asset_id"]}
        out["presentation"] = presentation
        out["enclosure"] = {
            "unit": "mm",
            "walls": presentation["walls"],
            "partitions": presentation["partitions"],
            "openings": presentation["openings"],
            "note": "与平面读取同一对象 ID 与 mm 尺寸；渲染器按 /1000 转米",
        }
        out["presentation_furniture"] = [{
            **f,
            "position_m": [m(f["position_mm"][0]), m(f["position_mm"][1]),
                           f.get("z_offset_m") or 0.0],
        } for f in presentation["furniture"]]
        out["presentation_cameras"] = [{
            **c, "position_m": [m(c["position_mm"][0]), m(c["position_mm"][1]),
                               m(c["eye_height_mm"])],
            "target_m": [m(c["target_mm"][0]), m(c["target_mm"][1]), 1.2],
        } for c in presentation["cameras"]]
        out["lighting"] = {
            "window_opening_ids": presentation["lighting"]["window_opening_ids"],
            "fixtures": [{**fx, "position_m": [m(fx["position_mm"][0]),
                                               m(fx["position_mm"][1])]}
                         for fx in presentation["lighting"]["fixtures"]],
            "coves": [{**cv, "polygon_m": [[m(p[0]), m(p[1])] for p in cv["polygon_mm"]]}
                      for cv in presentation["lighting"]["coves"]],
            "sun": presentation["lighting"]["sun"],
            "note": presentation["lighting"]["note"],
        }
        out["assets"] = {"root": "tools/assets",
                         "manifest_sha256": presentation["asset_manifest_sha256"],
                         "textures": textures, "models": asset_models,
                         "license": "CC0 1.0 (Poly Haven)"}
        out["render_assumptions"] = list(presentation["assumptions"]) + [
            presentation["disclaimer"],
        ]
        out["presentation_disclaimer"] = presentation["disclaimer"]
    return out


# ------------------------------------------------------------------ package
def build_package(model: dict, *, project_id: str, option_revision_id: str,
                  settings: dict | None = None, finish_scope: dict | None = None,
                  binding: dict | None = None) -> dict:
    settings = settings or {}
    presentation = settings.get("presentation") or None
    scope = normalize_finish_scope(finish_scope if finish_scope is not None
                                   else settings.get("finish_scope"))
    frozen = freeze_input(model, project_id=project_id,
                          option_revision_id=option_revision_id,
                          presentation=presentation)
    if scope:
        frozen["finish_scope"] = {"kind": scope["kind"], "declared_by": scope["declared_by"],
                                  "declaration": scope["declaration"],
                                  "areas": [{"object_id": a["object_id"],
                                             "material_id": a["material_id"],
                                             "polygon_mm": a["polygon_mm"]}
                                            for a in scope["areas"]]}
    if binding:
        frozen["binding"] = binding
    camera = derive_camera(model, presentation)
    quantities = measure(model, finish_scope=scope)
    cost = build_cost(quantities, settings=settings)
    plan = build_plan_svg(model, camera, quantities, presentation)
    scene = build_scene(model, camera, presentation)
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
        "binding": binding or {},
        "camera": camera,
        "quantities": quantities,
        "cost": cost,
        "missing": (list(presentation["missing"]) + [presentation["disclaimer"]]
                    if presentation else
                    ["墙体与门窗构造", "洁具", "隔断构件", "天花吊顶构造", "照度/配光",
                     "材料规格与产品选型", "相机原始视点（推导假设）"]),
        "presentation": ({
            "schema_version": presentation["schema_version"],
            "declared_by": presentation["declared_by"],
            "site_verified": False, "not_ai_design": True,
            "asset_manifest_sha256": presentation["asset_manifest_sha256"],
            "counts": presentation["counts"],
            "assumptions": presentation["assumptions"],
            "disclaimer": presentation["disclaimer"],
        } if presentation else None),
        "files": [],
    }
    return {"frozen": frozen, "camera": camera, "quantities": quantities,
            "cost": cost, "scene": scene, "plan": plan, "files": files,
            "manifest": manifest, "settings": settings, "finish_scope": scope,
            "presentation": presentation}


def _quantity_csv(quantities: dict) -> bytes:
    lines = ["quantity_id,name,value,unit,known_status,method,note"]
    for q in quantities["items"]:
        note = (q.get("unknown_reason") or q.get("note") or "").replace(",", "，")
        value = "" if q["value"] is None else q["value"]
        lines.append(f'{q["quantity_id"]},{q["name"]},{value},{q["unit"]},'
                     f'{q["known_status"]},{q.get("method") or "not_applicable"},"{note}"')
    return ("\n".join(lines) + "\n").encode("utf-8")


def finalize_package(files: dict, manifest: dict) -> dict:
    """ONE file set -> manifest + ZIP.

    Registration, manifest and archive are built from the same dict, so a render
    that exists is always inside the archive and a manifest that lists a file
    always points at real bytes. The finished ZIP is then re-opened and checked
    against the manifest before anything is registered.
    """
    content = {name: tuple(value) for name, value in files.items()}
    if any(name in {"manifest.json", "package.zip"} for name in content):
        raise ValueError("内容集合不能包含 manifest.json / package.zip 自身")
    entries = []
    for name in sorted(content):
        kind, ctype, data = content[name]
        entries.append({"filename": name, "kind": kind, "content_type": ctype,
                        "sha256": sha256_bytes(data), "size_bytes": len(data)})
    manifest = dict(manifest)
    manifest["files"] = entries
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    out = dict(content)
    out["manifest.json"] = ("manifest_json", "application/json", manifest_bytes)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(out):
            zf.writestr(name, out[name][2])
    out["package.zip"] = ("package_zip", "application/zip", buf.getvalue())
    check = check_zip_against_manifest(buf.getvalue(), manifest_bytes)
    if not check["ok"]:
        raise ValueError(f"交付包自检失败：{check['problems']}")
    return {"files": out, "manifest": manifest, "check": check}


def check_zip_against_manifest(zip_bytes: bytes, manifest_bytes: bytes) -> dict:
    """Re-open the archive and compare every manifest entry byte-for-byte."""
    problems: list[str] = []
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "problems": [f"清单不是合法 JSON：{error}"], "checked": 0}
    listed = {entry.get("filename"): entry for entry in manifest.get("files") or []}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names:
                problems.append("ZIP 内没有 manifest.json")
            if zf.read("manifest.json") != manifest_bytes:
                problems.append("ZIP 内清单字节与登记清单不一致")
            for name, entry in listed.items():
                if name not in names:
                    problems.append(f"清单登记但 ZIP 缺少：{name}")
                    continue
                data = zf.read(name)
                if len(data) != entry.get("size_bytes"):
                    problems.append(f"大小不一致：{name}")
                if sha256_bytes(data) != entry.get("sha256"):
                    problems.append(f"SHA 不一致：{name}")
            extra = names - set(listed) - {"manifest.json"}
            if extra:
                problems.append(f"ZIP 有未登记文件：{sorted(extra)}")
    except zipfile.BadZipFile as error:
        problems.append(f"ZIP 无法读取：{error}")
    return {"ok": not problems, "problems": problems, "checked": len(listed),
            "zip_bytes": len(zip_bytes), "zip_sha256": sha256_bytes(zip_bytes),
            "entries": sorted(listed)}
