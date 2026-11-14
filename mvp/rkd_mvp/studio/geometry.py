"""Deterministic geometry & area reconciliation for studio spatial plans.

ARC-02 remediation. This is NOT a new weak validator for a new role: it replaces
the bounding-box / self-reported-width logic inside tools.check_plan(), reusing
the project's locked geometry library (shapely==2.1.2, see requirements.lock).

Area model (single program-computed accounting, millimetres in / sqm out):

    site_area_sqm        outer frame of the source drawing (reference ONLY)
    reserved_area_sqm    stair / bathroom / other locked keep-out rectangles
    design_scope_sqm     site_area - reserved_area   (what may actually be laid out)
    zone_area_sum_sqm    real union area of zone polygons (geometry, not declared)
    unallocated_sqm      design_scope - zone_area_sum
    area_table_sum_sqm   sum of the model's area table (a claim, not a computation)

The area table must reconcile against design_scope_sqm, NOT against the sum of
functional-zone outlines. Unallocated space is allowed while exploring but is
always computed and shown; a plan that hides it is never called complete.

Everything the program cannot verify is reported as unknown/unsupported in
`checks`; nothing is silently assumed valid. Design value is never judged here.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from shapely.geometry import Polygon, LineString, box, Point
    from shapely.affinity import rotate as _rotate
    from shapely.ops import unary_union

    GEOMETRY_ENGINE = "shapely-2.1.2"
    _SHAPELY = True
except Exception:  # pragma: no cover - explicit, never a silent downgrade
    GEOMETRY_ENGINE = "unavailable"
    _SHAPELY = False

# Tolerances are declared, not hidden, and never replace professional judgement.
AREA_ABS_TOL_SQM = 0.75          # absolute reconciliation tolerance
AREA_REL_TOL = 0.01              # 1% of design scope
GEOM_TOL_MM = 2.0                # coordinate snap / boundary tolerance
OVERLAP_TOL_SQM = 0.05           # >0.05 sqm real intersection is an overlap
MIN_CLEAR_WIDTH_MM = 900         # contract minimum; also used for bottlenecks
ENTRANCE_REACH_TOL_MM = 1200     # how close a route must come to the entry band
ZONE_ROUTE_TOL_MM = 400          # route end must land in / beside a zone


# --------------------------------------------------------------------- helpers
def _num(v: Any, default: float | None = None) -> float | None:
    try:
        f = float(v)
        if not math.isfinite(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _issue(rule: str, severity: str, objects: list[str], message: str,
           hint: str, path: str = "") -> dict:
    return {"rule_id": rule, "severity": severity, "objects": objects,
            "message": message, "hint": hint, "path": path}


def _polygon(raw: Any) -> tuple[Polygon | None, str]:
    """Return (shapely polygon, error). Never accepts a degenerate/self-crossing ring."""
    if not isinstance(raw, list) or len(raw) < 3:
        return None, "轮廓少于 3 个点"
    pts: list[tuple[float, float]] = []
    for i, p in enumerate(raw):
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return None, f"polygon[{i}] 不是 [x,y]"
        x, y = _num(p[0]), _num(p[1])
        if x is None or y is None:
            return None, f"polygon[{i}] 坐标不是有限数字"
        pts.append((x, y))
    try:
        poly = Polygon(pts)
    except Exception as exc:  # pragma: no cover
        return None, f"无法构造多边形：{type(exc).__name__}"
    if poly.is_empty or poly.area <= 0:
        return None, "零面积或退化轮廓"
    if not poly.is_valid or not poly.exterior.is_simple:
        return None, "多边形自交或环非法"
    return poly, ""


def _rect(raw: Any) -> Polygon | None:
    """site keep-out rectangles are [x0,y0,x1,y1] in mm."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    vals = [_num(v) for v in raw]
    if any(v is None for v in vals):
        return None
    x0, y0, x1, y1 = vals  # type: ignore[misc]
    if x1 <= x0 or y1 <= y0:
        return None
    return box(x0, y0, x1, y1)


def _sqm(area_mm2: float) -> float:
    return round(area_mm2 / 1e6, 3)


def _is_other_row(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in ("通道", "其他", "其它", "未分配", "circulation", "other", "unallocated"))


def _has_non_right_angle(poly: Polygon) -> bool:
    """A real non-orthogonal edge in the polygon ring (not a text claim)."""
    coords = list(poly.exterior.coords)
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        dx, dy = x2 - x1, y2 - y1
        if dx and dy and abs(dx) > GEOM_TOL_MM and abs(dy) > GEOM_TOL_MM:
            return True
    return False


# ------------------------------------------------------------------- main check
def check_geometry(plan: dict, site: dict, catalog: dict[str, dict] | None = None) -> dict:
    """Full structural-free geometric check. Returns ok / issues / metrics / checks.

    `catalog` maps catalog_id -> {w_mm,d_mm,...}; when omitted, catalog references
    are reported as unsupported rather than assumed to be 600x600 boxes.
    """
    issues: list[dict] = []
    checks: dict[str, Any] = {}
    metrics: dict[str, Any] = {"geometry_engine": GEOMETRY_ENGINE}

    if not _SHAPELY:
        issues.append(_issue("GEO-000", "blocker", ["geometry"],
                             "几何引擎 shapely 不可用，无法进行真实几何校验",
                             "在 .venv 中安装 requirements.lock 锁定的 shapely==2.1.2；不可用时不降级放行"))
        return {"ok": False, "issues": issues, "metrics": metrics,
                "checks": {"geometry_engine": "unavailable"}}

    W, H = _num(site.get("width_mm")), _num(site.get("height_mm"))
    if W is None or H is None or W <= 0 or H <= 0:
        issues.append(_issue("GEO-000", "blocker", ["site"],
                             "场地宽高缺失或非正数", "site 需要 width_mm / height_mm"))
        return {"ok": False, "issues": issues, "metrics": metrics, "checks": checks}
    site_poly = box(0, 0, W, H)
    site_area = _sqm(site_poly.area)
    metrics["site_area_sqm"] = site_area

    # ---- reserved / locked keep-out conditions (stair, bath) -----------------
    reserved: list[tuple[str, Polygon]] = []
    for key, label in (("stair", "楼梯"), ("bath", "卫生间")):
        r = _rect(site.get(key))
        if r is not None:
            reserved.append((label, r))
        else:
            checks[f"reserved_{key}"] = "unknown"  # not silently "checked"
    if site.get("columns") in (None, ""):
        checks["columns"] = "unknown"
    else:
        checks["columns"] = "unsupported"  # no column geometry in this contract
    checks["doors_windows_geometry"] = "unsupported"  # contract has no door/window objects
    checks["ceiling_expression"] = "data_only"  # sketch does not draw ceiling; see STD-005 note

    reserved_union = unary_union([r for _, r in reserved]) if reserved else None
    reserved_area = _sqm(reserved_union.area) if reserved_union is not None else 0.0
    metrics["reserved_area_sqm"] = reserved_area
    design_scope_mm2 = site_poly.area - (reserved_union.area if reserved_union is not None else 0.0)
    design_scope = _sqm(design_scope_mm2)
    metrics["design_scope_sqm"] = design_scope
    checks["reserved_area_accounting"] = "checked" if reserved else "unknown"

    # ---- zones: real polygons, real intersections ----------------------------
    raw_zones = plan.get("zones")
    if not isinstance(raw_zones, list):
        issues.append(_issue("GEO-005", "blocker", ["zones"],
                             f"zones 不是数组（实际是 {type(raw_zones).__name__}）",
                             "zones 必须是对象数组", "/zones"))
        raw_zones = []
    zone_geoms: list[tuple[str, Polygon]] = []
    non_orthogonal_object_ids: list[str] = []
    for idx, z in enumerate(raw_zones):
        path = f"/zones/{idx}"
        if not isinstance(z, dict):
            issues.append(_issue("GEO-005", "blocker", [f"zones[{idx}]"],
                                 "分区条目不是对象", "每项要有 id/name/role/polygon/area_sqm", path))
            continue
        oid = str(z.get("id", f"zones[{idx}]"))
        poly, err = _polygon(z.get("polygon"))
        if poly is None:
            issues.append(_issue("GEO-001" if "点" in err else "GEO-010", "blocker", [oid],
                                 f"分区轮廓非法：{err}",
                                 "用合法、非自交、正面积的闭合多边形，单位 mm", path + "/polygon"))
            continue
        if not str(z.get("name") or "").strip():
            issues.append(_issue("STD-002", "major", [oid], "分区没有名称",
                                 "每个分区必须有可读名称", path + "/name"))
        # out of bounds (real geometry, not bbox)
        outside = poly.difference(site_poly).area
        if outside > GEOM_TOL_MM * GEOM_TOL_MM:
            issues.append(_issue("GEO-003", "blocker", [oid],
                                 f"分区越界，超出场地 {_sqm(outside)}㎡",
                                 f"控制在 0–{W:.0f} / 0–{H:.0f} mm 内", path + "/polygon"))
        # locked keep-out collision
        if reserved_union is not None:
            hit = poly.intersection(reserved_union).area
            if hit > OVERLAP_TOL_SQM * 1e6:
                labels = [lab for lab, r in reserved if poly.intersection(r).area > OVERLAP_TOL_SQM * 1e6]
                issues.append(_issue("LOCK-001", "blocker", [oid] + labels,
                                     f"分区占用保留条件（{'、'.join(labels) or '保留区'}）{_sqm(hit)}㎡",
                                     "保留楼梯/卫生间不得被分区覆盖；请在设计范围外表达", path + "/polygon"))
        # declared vs real area
        declared = _num(z.get("area_sqm"))
        real = _sqm(poly.area)
        if declared is None:
            issues.append(_issue("GEO-002", "major", [oid], "area_sqm 缺失",
                                 "给出目标面积；程序以轮廓复算值为准", path + "/area_sqm"))
        elif abs(real - declared) > max(0.5, declared * 0.05):
            issues.append(_issue("GEO-002", "major", [oid],
                                 f"面积与轮廓不符：声明 {declared:.1f}㎡，按轮廓算 {real:.1f}㎡",
                                 "以轮廓复算值改 area_sqm", path + "/area_sqm"))
        if _has_non_right_angle(poly):
            non_orthogonal_object_ids.append(oid)
        zone_geoms.append((oid, poly))

    # real pairwise intersection (NOT bounding boxes)
    for i in range(len(zone_geoms)):
        for j in range(i + 1, len(zone_geoms)):
            a_id, a = zone_geoms[i]
            b_id, b = zone_geoms[j]
            inter = a.intersection(b).area
            if inter > OVERLAP_TOL_SQM * 1e6:
                issues.append(_issue("GEO-004", "blocker", [a_id, b_id],
                                     f"两个分区实际相交 {_sqm(inter)}㎡",
                                     "分区不应重叠；通道请用 circulation 或独立分区表达",
                                     "/zones"))
    zone_union = unary_union([p for _, p in zone_geoms]) if zone_geoms else None
    zone_area = _sqm(zone_union.area) if zone_union is not None else 0.0
    metrics["zone_count"] = len(zone_geoms)
    metrics["zone_area_sum_sqm"] = zone_area  # kept for A1 _qc compatibility
    unallocated_mm2 = max(0.0, design_scope_mm2 - (zone_union.area if zone_union is not None else 0.0))
    unallocated = _sqm(unallocated_mm2)
    metrics["unallocated_sqm"] = unallocated

    # ---- platforms (rounded / stepped claims are real objects) ---------------
    for idx, p in enumerate(plan.get("platforms") or []):
        if not isinstance(p, dict):
            continue
        oid = str(p.get("id", f"platforms[{idx}]"))
        poly, err = _polygon(p.get("polygon"))
        if poly is None:
            issues.append(_issue("GEO-001", "blocker", [oid], f"展台轮廓非法：{err}",
                                 "补合法多边形", f"/platforms/{idx}/polygon"))
            continue
        if poly.difference(site_poly).area > GEOM_TOL_MM * GEOM_TOL_MM:
            issues.append(_issue("GEO-003", "blocker", [oid], "展台越界",
                                 "移回场地内", f"/platforms/{idx}/polygon"))
        cr = _num(p.get("corner_radius_mm"), 0) or 0
        if cr > 0 or p.get("kind") in ("rounded", "polygon", "stepped") or _has_non_right_angle(poly):
            non_orthogonal_object_ids.append(oid)
    for c in ((plan.get("ceiling") or {}).get("coves") or []) if isinstance(plan.get("ceiling"), dict) else []:
        if isinstance(c, dict):
            poly, _ = _polygon(c.get("polygon"))
            if poly is not None and _has_non_right_angle(poly):
                non_orthogonal_object_ids.append(str(c.get("id", "cove")))
    metrics["non_orthogonal_geometry_objects"] = sorted(set(non_orthogonal_object_ids))

    # ---- area table: reconcile against DESIGN SCOPE, not zone outlines -------
    raw_table = plan.get("area_table")
    if not isinstance(raw_table, list):
        issues.append(_issue("GEO-006", "blocker", ["area_table"],
                             f"area_table 不是数组（实际是 {type(raw_table).__name__}）",
                             '写成对象数组 {"name":..., "area_sqm":...}', "/area_table"))
        raw_table = []
    table_sum = 0.0
    other_declared = 0.0
    functional_declared = 0.0
    for idx, r in enumerate(raw_table):
        path = f"/area_table/{idx}"
        if not isinstance(r, dict):
            issues.append(_issue("GEO-006", "blocker", [f"area_table[{idx}]"],
                                 "面积表条目不是对象", '每行写成 {"name":..., "area_sqm":...}', path))
            continue
        v = _num(r.get("area_sqm"))
        if v is None:
            issues.append(_issue("GEO-006", "blocker", [f"area_table[{idx}]"],
                                 "area_sqm 不是数字", "填数字，单位㎡", path + "/area_sqm"))
            continue
        table_sum += v
        if _is_other_row(str(r.get("name") or "")):
            other_declared += v
        else:
            functional_declared += v
    metrics["area_table_sum_sqm"] = round(table_sum, 3)
    metrics["area_table_functional_declared_sqm"] = round(functional_declared, 3)
    metrics["area_table_other_declared_sqm"] = round(other_declared, 3)
    metrics["computed_unallocated_sqm"] = unallocated
    metrics["area_reconciliation_basis"] = "design_scope_sqm"

    tol = max(AREA_ABS_TOL_SQM, design_scope * AREA_REL_TOL)
    metrics["area_reconciliation_tolerance_sqm"] = round(tol, 3)
    gap_scope = abs(table_sum - design_scope)
    metrics["area_reconciliation_gap_sqm"] = round(gap_scope, 3)
    if raw_table and gap_scope > tol:
        issues.append(_issue("AREA-002", "blocker", ["area_table"],
                             f"面积表合计 {table_sum:.1f}㎡ 与可布置范围 {design_scope:.1f}㎡ 不符"
                             f"（差额 {gap_scope:.1f}㎡；外框 {site_area:.1f}㎡ 含保留 {reserved_area:.1f}㎡，不能等同计价面积）",
                             f"面积表合计应对齐可布置范围 {design_scope:.1f}㎡；功能区 {zone_area:.1f}㎡ 之外"
                             f"的 {unallocated:.1f}㎡ 用一行显式列出并说明用途", "/area_table"))
    # unallocated must be explicitly accounted for, never hidden
    other_gap = abs(other_declared - unallocated)
    metrics["unallocated_declaration_gap_sqm"] = round(other_gap, 3)
    metrics["layout_complete"] = bool(raw_table) and gap_scope <= tol and other_gap <= tol
    if unallocated > tol and other_gap > tol:
        issues.append(_issue("AREA-001", "major", ["area_table"],
                             f"仍有 {unallocated:.1f}㎡ 未分配/通道面积未显式对账"
                             f"（已声明 {other_declared:.1f}㎡，缺 {abs(unallocated - other_declared):.1f}㎡）",
                             "探索阶段允许未分配，但必须在面积表单列一行写明真实数值与用途；"
                             "不允许隐藏后标记为完整布局", "/area_table"))
    if zone_area > 0 and abs(functional_declared - zone_area) > max(1.0, zone_area * 0.05):
        issues.append(_issue("AREA-003", "major", ["area_table"],
                             f"面积表功能区行合计 {functional_declared:.1f}㎡ 与程序从轮廓复算的 {zone_area:.1f}㎡ 不符",
                             "功能区行按程序复算值填写；差额归到通道/未分配行", "/area_table"))

    # ---- circulation: real paths, entry reach, bottlenecks ------------------
    raw_circ = plan.get("circulation")
    if not isinstance(raw_circ, list):
        raw_circ = []
    checks["circulation_paths"] = "checked" if raw_circ else "unsupported"
    zone_union_for_route = zone_union
    obstacles = [r for _, r in reserved]
    for idx, c in enumerate(raw_circ):
        path = f"/circulation/{idx}"
        if not isinstance(c, dict):
            issues.append(_issue("GEO-007", "major", [f"circulation[{idx}]"],
                                 "动线条目不是对象", '写成 {"id","width_mm","path"}', path))
            continue
        oid = str(c.get("id", f"circulation[{idx}]"))
        pts = c.get("path")
        if not isinstance(pts, list) or len(pts) < 2:
            issues.append(_issue("CIR-002", "blocker", [oid], "动线路径点少于 2 个",
                                 "path 至少两个 [x,y] 点", path + "/path"))
            continue
        coords = []
        ok = True
        for p in pts:
            if not isinstance(p, (list, tuple)) or len(p) != 2 or _num(p[0]) is None or _num(p[1]) is None:
                ok = False
                break
            coords.append((float(p[0]), float(p[1])))
        if not ok:
            issues.append(_issue("GEO-007", "blocker", [oid], "动线坐标非法",
                                 "path 写成 [[x,y],...]，单位 mm", path + "/path"))
            continue
        line = LineString(coords)
        if not line.is_simple or line.length <= 0:
            issues.append(_issue("CIR-002", "blocker", [oid], "动线自交或零长度",
                                 "改成不自交的连续路径", path + "/path"))
        width = _num(c.get("width_mm"))
        if width is None:
            issues.append(_issue("CIR-001", "major", [oid], "width_mm 缺失",
                                 "给出声明净宽；程序仍会按几何复算净宽", path + "/width_mm"))
            width = 0.0
        if width < MIN_CLEAR_WIDTH_MM:
            issues.append(_issue("CIR-001", "major", [oid],
                                 f"声明净宽 {width:.0f} mm 低于 {MIN_CLEAR_WIDTH_MM} mm",
                                 "主通道建议 ≥1200 mm", path + "/width_mm"))
        # real geometric bottleneck: sample the route, measure nearest obstacle/zone edge
        half = max(width, MIN_CLEAR_WIDTH_MM) / 2.0
        band = line.buffer(half, cap_style=2)
        if reserved_union is not None and band.intersection(reserved_union).area > 0:
            labels = [lab for lab, r in reserved if band.intersection(r).area > 0]
            issues.append(_issue("CIR-003", "blocker", [oid] + labels,
                                 f"动线实际穿过保留条件（{'、'.join(labels)}），净宽不足",
                                 "绕开保留楼梯/卫生间，或明确设置门斗连接", path + "/path"))
        # measured clear width along sampled points (not the self-reported number)
        measured = []
        for frac in (i / 20 for i in range(21)):
            pt = line.interpolate(frac * line.length, normalized=False) if line.length else Point(coords[0])
            nearest = min([pt.distance(r) for r in obstacles] or [float("inf")])
            if math.isfinite(nearest):
                measured.append(2 * nearest)
        if measured:
            metrics[f"measured_clear_width_mm::{oid}"] = round(min(measured), 1)
            if min(measured) < MIN_CLEAR_WIDTH_MM:
                issues.append(_issue("CIR-003", "major", [oid],
                                     f"沿动线实测最小净宽 {min(measured):.0f} mm，低于 {MIN_CLEAR_WIDTH_MM} mm",
                                     "按几何拓宽通路或移开障碍；仅调 width_mm 自报值无效", path + "/path"))
        # entry reachability
        ent = site.get("entrance")
        entry_band = None
        if isinstance(ent, (list, tuple)) and len(ent) == 3:
            ex, ey, elen = _num(ent[0]), _num(ent[1]), _num(ent[2])
            if None not in (ex, ey, elen) and elen and elen > 0:
                entry_band = box(ex - 50, ey, ex + 50, ey + elen)
        checks["entry_band"] = "checked" if entry_band is not None else "unknown"
        if entry_band is not None and line.distance(entry_band) > ENTRANCE_REACH_TOL_MM:
            issues.append(_issue("CIR-004", "blocker", [oid],
                                 "动线没有连接到场地入口区段（入口不可达）",
                                 "让主动线起点落在入口门斗/入口带内", path + "/path"))
        # route must actually serve zones (disconnected route counterexample)
        if zone_union_for_route is not None and zone_union_for_route.area > 0:
            d0 = zone_union_for_route.distance(Point(coords[0]))
            d1 = zone_union_for_route.distance(Point(coords[-1]))
            on_route = line.intersection(zone_union_for_route).length > 0
            if not on_route and min(d0, d1) > ZONE_ROUTE_TOL_MM:
                issues.append(_issue("CIR-002", "blocker", [oid],
                                     "动线与全部分区断开，未连接任何功能区（断路）",
                                     "把动线接入至少一个分区，并标明入口→分区的连续路径", path + "/path"))

    # ---- furniture: catalog reference, real size, rotated footprint ---------
    raw_furn = plan.get("furniture")
    if not isinstance(raw_furn, list):
        raw_furn = []
    if catalog is None:
        checks["furniture_catalog"] = "unsupported"
    else:
        checks["furniture_catalog"] = "checked"
    for idx, f in enumerate(raw_furn):
        path = f"/furniture/{idx}"
        if not isinstance(f, dict):
            issues.append(_issue("FUR-000", "blocker", [f"furniture[{idx}]"],
                                 "家具条目不是对象", "每项要有 id/catalog_id/x/y", path))
            continue
        oid = str(f.get("id", f"furniture[{idx}]"))
        cid = str(f.get("catalog_id") or "")
        x, y = _num(f.get("x")), _num(f.get("y"))
        rot = _num(f.get("rot"), 0) or 0
        if x is None or y is None:
            issues.append(_issue("FUR-000", "blocker", [oid], "家具坐标缺失或非数字",
                                 "给出 x/y，单位 mm", path))
        if catalog is None:
            if not cid:
                issues.append(_issue("FUR-001", "blocker", [oid], "缺少 catalog_id，且目录未提供",
                                     "必须引用真实家具目录条目；未知尺寸不得用 600×600 默认框代替", path + "/catalog_id"))
            continue
        item = catalog.get(cid)
        if not item:
            issues.append(_issue("FUR-001", "blocker", [oid],
                                 f"catalog_id「{cid}」不在家具目录中（无效对象引用）",
                                 "从 search_catalog 返回的真实目录条目中选 catalog_id", path + "/catalog_id"))
            continue
        w, d = _num(item.get("w_mm")), _num(item.get("d_mm"))
        if w is None or d is None or w <= 0 or d <= 0:
            checks[f"furniture_size::{oid}"] = "unknown"
            continue
        # a self-declared size conflicting with the catalog is an error, not a free override
        for field, real in (("w_mm", w), ("d_mm", d)):
            given = _num(f.get(field))
            if given is not None and abs(given - real) > 1.0:
                issues.append(_issue("FUR-002", "major", [oid],
                                     f"家具 {field} 自报 {given:.0f}mm 与目录实际 {real:.0f}mm 不符",
                                     "按目录实际尺寸落位；尺寸变化应由目录版本表达", path + "/" + field))
        if x is not None and y is not None:
            footprint = box(-w / 2, -d / 2, w / 2, d / 2)
            if rot:
                footprint = _rotate(footprint, rot, origin=(0, 0), use_radians=False)
            from shapely.affinity import translate as _translate
            footprint = _translate(footprint, xoff=x, yoff=y)
            metrics[f"furniture_footprint_sqm::{oid}"] = _sqm(footprint.area)
            if footprint.difference(site_poly).area > GEOM_TOL_MM * GEOM_TOL_MM:
                issues.append(_issue("GEO-003", "blocker", [oid],
                                     "家具按目录实际尺寸（含旋转占地）后越界",
                                     "移回场地内；不要用 600×600 默认框掩盖真实占地", path))
            if reserved_union is not None and footprint.intersection(reserved_union).area > 0:
                issues.append(_issue("LOCK-001", "blocker", [oid],
                                     "家具旋转占地侵入保留条件", "移出保留区", path))
    metrics["furniture_count"] = len(raw_furn)

    # ---- non-orthogonal claims must correspond to real geometry -------------
    strategy = plan.get("strategy") if isinstance(plan.get("strategy"), dict) else {}
    claims = strategy.get("non_orthogonal")
    claims = claims if isinstance(claims, list) else []
    metrics["non_orthogonal_claim_count"] = len(claims)
    geometric = sorted(set(non_orthogonal_object_ids))
    metrics["non_orthogonal_geometry_count"] = len(geometric)
    if len(geometric) < len(claims):
        issues.append(_issue("STD-001", "major", ["strategy"],
                             f"声明 {len(claims)} 处非直角造型，但只有 {len(geometric)} 个对象"
                             f"（{', '.join(geometric) or '无'}）在几何上真的含非直角边/圆角",
                             "每条声明绑定具体分区/展台/灯槽 id，并在 polygon 或 corner_radius 中体现；"
                             "该阈值是启发式，不作设计通过判据", "/strategy/non_orthogonal"))
    elif claims:
        checks["non_orthogonal_claims"] = "checked"
    else:
        checks["non_orthogonal_claims"] = "checked"

    # ---- ceiling: check DATA, never infer absence from what the sketch draws --
    ceiling = plan.get("ceiling") if isinstance(plan.get("ceiling"), dict) else {}
    coves = ceiling.get("coves") if isinstance(ceiling.get("coves"), list) else []
    fixtures = ceiling.get("fixtures") if isinstance(ceiling.get("fixtures"), list) else []
    metrics["cove_count"] = len(coves)
    metrics["light_fixture_count"] = len(fixtures)
    if not coves and not fixtures:
        issues.append(_issue("STD-005", "major", ["ceiling"],
                             "模型数据里没有任何天花造型或灯具点位",
                             "先检查 ceiling.coves / ceiling.fixtures 数据；草案缩略图未绘制天花，"
                             "不能仅凭图面推断数据存在与否。天花覆盖率 60% 属未确认启发式，不作判据",
                             "/ceiling"))

    # ---- preserved objects / locks: explicit coverage statement -------------
    preserved_ids = [str(z.get("id")) for z in (raw_zones if isinstance(raw_zones, list) else [])
                     if isinstance(z, dict) and any(k in str(z.get("id", "")).lower()
                                                    for k in ("stair", "bath", "lock", "preserve", "keep"))]
    checks["preserved_objects_in_model"] = "checked" if preserved_ids else "unsupported"
    metrics["preserved_object_ids"] = preserved_ids
    checks["stair_bath_keepout_geometry"] = "checked" if reserved else "unknown"
    checks["door_window_lock_geometry"] = "unsupported"
    checks["fire_egress_accessibility"] = "unsupported"
    checks["note"] = ("程序只检查已表达的几何与锁定；门/窗/柱网/消防疏散/无障碍未在契约中建模，"
                      "一律 unsupported，不视为通过，也不推断设计或专业合规")

    ok = not any(i["severity"] == "blocker" for i in issues)
    return {"ok": ok, "issues": issues, "metrics": metrics, "checks": checks}
