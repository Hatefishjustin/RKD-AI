"""Offline, deterministic adapter: real-model OUTPUT SHAPE -> versioned spatial.

WHY THIS EXISTS
---------------
``RealModelDesignOptionProvider._to_model`` emits a valid
``rkd-ai-design-option.v1`` document whose objects are metric (m) rectangles,
but it does NOT emit a ``spatial`` section.  The W2 same-source generator
(``ai_spatial_outputs.build_package``) can only consume a model that carries
``spatial.zones[].polygon_mm``.  That gap is why a real-model candidate could
never be drawn / rendered / measured from the same frozen model.

This module closes that gap WITHOUT inventing a design, WITHOUT a network call
and WITHOUT re-labelling provenance:

* input is the *shape* the real model returns (see REAL_DESIGN_OUTPUT_SHAPE);
* every coordinate is converted m -> mm exactly (Decimal x1000, never float
  guessing);
* a metric rectangle becomes a four-corner polygon and is labelled
  ``rect_four_corner_from_metric_rect`` with
  ``non_rectangular_capability=false`` -- this is the same rectangle, NOT a
  claim of real non-rectangular design ability;
* ``wall_type=curved_intent`` is a semantic intention only: NO arc/curve
  geometry is generated;
* W2 manual enclosure / material / furniture expression is NOT imported here;
* missing geometry, specs, prices or verified site facts stay ``unknown``
  (``value=None``), never 0;
* the site must be the user-confirmed v2 basemap, re-checked by file SHA and
  boundary.  A ``manual_boundary_not_site_verified`` test boundary is rejected.

No external calls, no key reads, no writes outside the caller's evidence dir.
The caller (service / verifier) decides whether anything is ever committed.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

# --- versions (all additive; nothing existing is renamed) -------------------
ADAPTER_VERSION = "rkd-realmodel-spatial-adapter.v1"
SPATIAL_VERSION = "rkd-realmodel-spatial.v1"
MAPPING_VERSION = "realmodel-output-to-spatial.v1"
VOCAB_VERSION = "rkd-design-vocab.v1"
BASEMAP_CONTRACT = "rkd-site-basemap.v2"
GEOMETRY_RULE_VERSION = "rkd-realmodel-adapter-geometry.v1"
MM_PER_M = Decimal("1000")

# The user-confirmed v2 basemap, bound by the confirmation card and re-verified
# byte-for-byte on every adapter run (see reconcile_site).
CONFIRMED_BASEMAP_FILES = {
    "阶段1_底图核对.pdf": (3346417, "7a8c212b84d1c01001291fc62145a729f6a90d293c8fe92bb3213fd221aad35b"),
    "阶段1_底图核对.html": (9890, "7a927286ad003af1afd1c2ace678dc8d4485004e5d711e2d6280d6a8cca46d1c"),
    "01_真实场地底图.svg": (45225, "bfa02621c86f300e51c3a88669b45a2c730cda5071eb80f0f37b1b7ff0fc3023"),
    "底图数据.json": (8894, "195a2a78d7400e019c3b64043eaf2736810c80cc648299ec3e51c725a6ff31e7"),
    "00_原始平面图_正向.png": (363414, "6a3840dfc731848694c972c30c9209a2f855dadd54555c6349afc448e459488b"),
}
CONFIRMED_BOUNDARY_MM = (26170, 17920)

# --- versioned vocabularies -------------------------------------------------
# zone_role: real-model enum -> canonical spatial role.  Anything else is
# 'unknown' with a ledger row; it is NEVER silently coerced to a default.
ZONE_ROLE_VOCAB = {
    "foyer": "arrival",
    "primary_display": "primary_display",
    "deep_talk": "negotiation",
    "buffer": "transition",
    "service": "service",
}
# furniture_type: real-model enum -> canonical catalog family.  Specs are not
# implied: w_mm/d_mm always come from the model rect, catalog is a family label.
FURNITURE_TYPE_VOCAB = {
    "reception_desk": "reception_desk",
    "island": "island",
    "table_chairs": "table_chairs",
    "sofa": "sofa",
    "plant": "plant",
    "display_case": "display_case",
    "storage": "storage",
    "pantry": "pantry",
    "service_counter": "service_counter",
    "light_feature": "light_feature",
}
WALL_TYPE_VOCAB = {"solid", "screen", "curved_intent", "feature"}
SEQUENCE_ROLE_VOCAB = {"opening", "development", "climax", "rest", "closing"}


class RealModelSpatialAdaptationError(Exception):
    """Deterministic rejection BEFORE any document is handed downstream."""

    def __init__(self, code: str, message: str, *, stage: str = "adaptation") -> None:
        self.code, self.message, self.stage = code, message, stage
        super().__init__(f"{code}: {message}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _dec(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise RealModelSpatialAdaptationError("INVALID_NUMBER", f"{field} 不是数字", stage="unit")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise RealModelSpatialAdaptationError("INVALID_NUMBER", f"{field} 不是有效数字", stage="unit")
    if not d.is_finite():
        raise RealModelSpatialAdaptationError("INVALID_NUMBER", f"{field} 非有限数", stage="unit")
    return d


def _m_to_mm(value: Any, field: str) -> float:
    """Exact metre -> millimetre conversion.  Millimetre output is integral here."""
    d = _dec(value, field) * MM_PER_M
    if d != d.to_integral_value():
        raise RealModelSpatialAdaptationError("SUB_MM_PRECISION", f"{field} 小于 1mm，无法无损转 mm", stage="unit")
    return int(d)


def _rect_polygon_mm(rect: dict, field: str) -> list[list[float]]:
    """Four corners of a METRIC RECT -- the same rectangle, never a new shape."""
    if not isinstance(rect, dict) or str(rect.get("type") or "rect") != "rect":
        raise RealModelSpatialAdaptationError("UNSUPPORTED_GEOMETRY",
                                              f"{field} 不是 rect，适配器不凭空生成其它几何", stage="geometry")
    x = _m_to_mm(rect.get("x", 0), f"{field}.x")
    y = _m_to_mm(rect.get("y", 0), f"{field}.y")
    w = _m_to_mm(rect.get("width", 0), f"{field}.width")
    h = _m_to_mm(rect.get("length", 0), f"{field}.length")
    if w <= 0 or h <= 0:
        raise RealModelSpatialAdaptationError("DEGENERATE_RECT", f"{field} 宽或长为非正数", stage="geometry")
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _mm_shape(poly: list[list[float]]) -> dict[str, str]:
    """Legacy rect shape (m) from a four-corner mm rectangle; bbox projection only."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)

    def m(v: float) -> str:
        d = (Decimal(str(v)) / MM_PER_M).quantize(Decimal("0.001")).normalize()
        return format(d, "f")

    return {"type": "rect", "x": m(x0), "y": m(y0),
            "width": m(x1 - x0), "length": m(y1 - y0)}


def _require_within(poly: list[list[float]], boundary_mm: list[int], label: str) -> None:
    max_x, max_y = boundary_mm
    for x, y in poly:
        if x < 0 or y < 0 or x > max_x or y > max_y:
            raise RealModelSpatialAdaptationError(
                "OBJECT_OUTSIDE_BOUNDARY",
                f"{label} 坐标 ({x},{y})mm 越出确认底图 {max_x}x{max_y}mm", stage="geometry")


def _shoelace_m2(poly: list[list[float]]) -> float:
    area2 = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        area2 += x1 * y2 - x2 * y1
    return abs(area2) / 2.0 / 1_000_000.0


def reconcile_site(basemap_dir: Any, site: dict) -> dict:
    """Prove the input site IS the user-confirmed v2 basemap, not a test value.

    Fails closed: any SHA/size/boundary/source mismatch raises.  This is the
    explicit '输入对账' gate the architect required; no other boundary may be
    substituted for the confirmed version.
    """
    from pathlib import Path

    base = Path(basemap_dir)
    files = []
    for name, (size, digest) in CONFIRMED_BASEMAP_FILES.items():
        path = base / name
        if not path.is_file():
            raise RealModelSpatialAdaptationError("BASEMAP_FILE_MISSING", f"缺少已确认底图文件 {name}", stage="basemap")
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if len(raw) != size or actual != digest:
            raise RealModelSpatialAdaptationError(
                "BASEMAP_SHA_MISMATCH",
                f"{name} 字节/SHA 与用户确认的 v2 绑定不一致（{len(raw)}/{actual[:12]}）", stage="basemap")
        files.append({"name": name, "bytes": size, "sha256": digest})
    if str(site.get("contract_version") or "") != BASEMAP_CONTRACT:
        raise RealModelSpatialAdaptationError("BASEMAP_CONTRACT_MISMATCH",
                                              "site.contract_version 不是 rkd-site-basemap.v2", stage="basemap")
    source = str(site.get("boundary_source") or "")
    if source != BASEMAP_CONTRACT:
        # Explicitly refuse the W2 test parameter boundary and any other source.
        raise RealModelSpatialAdaptationError(
            "SITE_BOUNDARY_MISMATCH",
            f"输入边界来源={source or '缺失'}；必须是 {BASEMAP_CONTRACT}，"
            "不接受 manual_boundary_not_site_verified 或其它测试边界", stage="basemap")
    bw = _m_to_mm(site.get("width_m"), "site.width_m")
    bh = _m_to_mm(site.get("length_m"), "site.length_m")
    if (bw, bh) != CONFIRMED_BOUNDARY_MM:
        raise RealModelSpatialAdaptationError(
            "SITE_BOUNDARY_MISMATCH",
            f"输入边界 {bw}x{bh}mm 与确认底图 {CONFIRMED_BOUNDARY_MM[0]}x{CONFIRMED_BOUNDARY_MM[1]}mm 不一致",
            stage="basemap")
    return {
        "contract_version": BASEMAP_CONTRACT,
        "boundary_mm": [bw, bh],
        "boundary_sha256": sha256_hex({f["name"]: f["sha256"] for f in files}),
        "files": files,
        "site_verified": False,
        "unverified_facts": list(site.get("unverified_facts") or []),
        "keepouts": [dict(k) for k in (site.get("keepouts") or [])],
        "entrance": dict(site.get("entrance") or {}),
    }


def _row(src: str, dst: str, oid: str, sv: Any, tv: Any, unit: str, status: str) -> dict:
    if status not in {"mapped", "preserved", "unknown", "unsupported"}:
        raise ValueError("bad ledger status")
    return {"source_field": src, "target_field": dst, "object_id": oid,
            "source_value": sv, "target_value": tv, "unit": unit, "status": status}


def adapt_candidate(candidate: dict, *, site: dict, basemap_dir: Any,
                    provenance: dict, created_at: str) -> dict:
    """Map ONE real-model-output-shaped candidate to a versioned spatial model.

    ``provenance`` must carry an honest ``design_origin``.  For offline fixture
    runs it is ``fixture``; a ``real_model`` claim without ``run_refs`` is
    rejected (evidence-based provenance, never self-declared from shape alone).
    """
    if not isinstance(candidate, dict):
        raise RealModelSpatialAdaptationError("NOT_A_CANDIDATE", "候选不是 JSON 对象", stage="source")
    recon = reconcile_site(basemap_dir, site)

    # Frame reconciliation: a real model drawn on the OLD 12x8 m test boundary
    # must never be silently transplanted onto the confirmed v2 basemap.
    frame = provenance.get("model_site_boundary_m")
    if frame is None or not isinstance(frame, (list, tuple)) or len(frame) != 2:
        raise RealModelSpatialAdaptationError(
            "MODEL_FRAME_UNKNOWN",
            "未提供模型输出的原生边界(model_site_boundary_m)；未知来源不静默落位到 v2 底图", stage="basemap")
    fw, fh = _m_to_mm(frame[0], "model_site_boundary_m[0]"), _m_to_mm(frame[1], "model_site_boundary_m[1]")
    if (fw, fh) != tuple(CONFIRMED_BOUNDARY_MM):
        raise RealModelSpatialAdaptationError(
            "MODEL_FRAME_MISMATCH",
            f"模型原生边界 {fw}x{fh}mm 与确认 v2 底图 {CONFIRMED_BOUNDARY_MM[0]}x{CONFIRMED_BOUNDARY_MM[1]}mm 不一致；"
            "不缩放、不平移、不用测试边界替代", stage="basemap")

    origin = provenance.get("design_origin") or {}
    kind = str(origin.get("kind") or "unknown")
    if kind not in {"real_model", "human", "fixture", "unknown"}:
        raise RealModelSpatialAdaptationError("DESIGN_ORIGIN_INVALID", "design_origin.kind 非法", stage="source")
    if kind == "real_model" and not (origin.get("run_refs") or []):
        raise RealModelSpatialAdaptationError(
            "DESIGN_ORIGIN_UNVERIFIED",
            "声明 real_model 但没有 run_refs 运行证据；离线夹具不得冒称真实设计", stage="source")
    origin_kind = "real_model_output" if kind == "real_model" else "real_model_shape_fixture"

    oid_seen: set[str] = set()
    ledger: list[dict] = []
    unknowns: list[dict] = []
    unsupported: list[dict] = []
    semantic: list[dict] = []
    id_map: list[dict] = []

    def unique_oid(raw: Any, prefix: str) -> str:
        oid = str(raw or f"{prefix}:{len(oid_seen)}").strip()
        if not oid or oid in oid_seen:
            raise RealModelSpatialAdaptationError("DUPLICATE_OBJECT_ID", f"对象 ID 重复或为空：{oid}", stage="objects")
        oid_seen.add(oid)
        return oid

    # zones: metric rect -> four-corner polygon (same rectangle)
    zones = []
    for z in candidate.get("zones") or []:
        if not isinstance(z, dict):
            continue
        oid = unique_oid(z.get("object_id"), "zone")
        poly = _rect_polygon_mm(z, f"zone:{oid}")
        _require_within(poly, recon["boundary_mm"], f"zone:{oid}")
        raw_role = str(z.get("zone_role") or "")
        role = ZONE_ROLE_VOCAB.get(raw_role, "unknown")
        if role == "unknown":
            unknowns.append({"item": f"zone_role:{oid}", "value": None, "known_status": "unknown",
                             "unknown_reason": f"zone_role={raw_role!r} 不在 {VOCAB_VERSION} 词表，未擅自归类"})
        ledger.append(_row(f"zones[{oid}].x/y/width/length(m)", f"spatial.zones[{oid}].polygon_mm",
                           oid, {k: z.get(k) for k in ("x", "y", "width", "length")}, poly, "m->mm", "mapped"))
        ledger.append(_row(f"zones[{oid}].zone_role", f"spatial.zones[{oid}].role", oid,
                           raw_role, role, "enum", "mapped" if role != "unknown" else "unknown"))
        seq = str(z.get("sequence_role") or "")
        if seq:
            if seq not in SEQUENCE_ROLE_VOCAB:
                unknowns.append({"item": f"sequence_role:{oid}", "value": None, "known_status": "unknown",
                                 "unknown_reason": f"sequence_role={seq!r} 不在词表"})
            semantic.append({"object_id": oid, "kind": "sequence_role", "value": seq,
                             "geometry": False, "note": "叙事序列仅语义，不生成几何"})
        if str(z.get("intent") or ""):
            semantic.append({"object_id": oid, "kind": "intent", "value": str(z["intent"]),
                             "geometry": False, "note": "设计意图仅语义"})
        zones.append({"object_id": oid, "name": str(z.get("name") or oid), "role": role,
                      "polygon_mm": poly, "area_sqm": round(_shoelace_m2(poly), 4),
                      "source_refs": [str(x) for x in (z.get("source_refs") or [])],
                      "geometry_mode": "rect_four_corner_from_metric_rect",
                      "non_rectangular_capability": False,
                      "raw_zone_role": raw_role})
        id_map.append({"source_object_id": oid, "target_object_id": oid, "group": "zones"})

    # circulation: metric rect segment -> centreline polyline + declared width
    circulation = []
    for i, p in enumerate(candidate.get("paths") or []):
        if not isinstance(p, dict):
            continue
        poly = _rect_polygon_mm(p, f"path[{i}]")
        xs = [q[0] for q in poly]
        ys = [q[1] for q in poly]
        centre_y = (min(ys) + max(ys)) / 2
        line = [[min(xs), centre_y], [max(xs), centre_y]]
        width_mm = min(max(xs) - min(xs), max(ys) - min(ys))
        circulation.append({
            "object_id": str(p.get("segment_id") or f"path:{i}"),
            "width_mm": width_mm, "path_mm": line,
            "path_representation": "rect_centreline_from_metric_rect",
            "source_refs": [str(x) for x in (p.get("source_refs") or [])],
        })
        id_map.append({"source_object_id": str(p.get("segment_id") or f"path:{i}"),
                       "target_object_id": str(p.get("segment_id") or f"path:{i}"), "group": "circulation"})
    if len(circulation) < 2:
        raise RealModelSpatialAdaptationError("CIRCULATION_INSUFFICIENT",
                                              "模型输出的动线区段少于 2，拒绝生成", stage="geometry")

    # furniture: metric rect -> centre + size; catalog family from vocabulary
    furniture = []
    def add_furniture(f: dict, prefix: str) -> None:
        if not isinstance(f, dict):
            return
        oid = unique_oid(f.get("object_id"), prefix)
        poly = _rect_polygon_mm(f, f"furniture:{oid}")
        xs = [q[0] for q in poly]
        ys = [q[1] for q in poly]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        w_mm, d_mm = max(xs) - min(xs), max(ys) - min(ys)
        raw_type = str(f.get("furniture_type") or "")
        family = FURNITURE_TYPE_VOCAB.get(raw_type, "unknown")
        if family == "unknown":
            unknowns.append({"item": f"furniture_type:{oid}", "value": None, "known_status": "unknown",
                             "unknown_reason": f"furniture_type={raw_type!r} 不在 {VOCAB_VERSION} 词表"})
        ledger.append(_row(f"furniture[{oid}].rect(m)", f"spatial.furniture[{oid}].{{x_mm,y_mm,w_mm,d_mm}}",
                           oid, {k: f.get(k) for k in ("x", "y", "width", "length")},
                           {"x_mm": cx, "y_mm": cy, "w_mm": w_mm, "d_mm": d_mm}, "m->mm", "mapped"))
        item = {"object_id": oid, "catalog_id": f"realmodel:{family}",
                "x_mm": cx, "y_mm": cy, "w_mm": w_mm, "d_mm": d_mm, "rot": 0,
                "rotation_source": "not_in_model_output_assumed_axis_aligned",
                "catalog_spec_known": False,
                "source_refs": [str(x) for x in (f.get("source_refs") or [])]}
        intended = f.get("parent_object_id") or f.get("intended_parent")
        if intended:
            item["intended_parent"] = str(intended)   # semantic only, NOT parent_object_id
            semantic.append({"object_id": oid, "kind": "intended_parent", "value": str(intended),
                             "geometry": False, "note": "归属意图，不据此建立几何父子或工程量"})
        if f.get("focal") or prefix == "focal":
            item["focal"] = True
        furniture.append(item)
        id_map.append({"source_object_id": oid, "target_object_id": oid, "group": "furniture"})
        if family == "unknown":
            ledger.append(_row(f"furniture[{oid}].furniture_type", f"spatial.furniture[{oid}].catalog_id",
                               oid, raw_type, item["catalog_id"], "enum", "unknown"))

    for f in candidate.get("furniture") or []:
        add_furniture(f, "f")
    focal = candidate.get("focal_point")
    if isinstance(focal, dict):
        add_furniture(focal, "focal")
    for b in candidate.get("entrance_buffers") or []:
        if isinstance(b, dict):
            unsupported.append({"item": f"entrance_buffer:{b.get('object_id') or 'buffer'}",
                                "source_field": "entrance_buffers[]", "status": "unsupported_unknown",
                                "reason": "入口由底图 boundary.entrance 表达；门斗对象仅保留语义，不生成几何"})

    # platforms: focal island is a platform (same rect), nothing else invented
    platforms = []
    focal = candidate.get("focal_point") if isinstance(candidate.get("focal_point"), dict) else None
    if focal:
        platforms.append({"object_id": str(focal.get("object_id") or "focal:hero"),
                          "name": str(focal.get("name") or "视觉焦点"),
                          "kind": "focal_island",
                          "polygon_mm": _rect_polygon_mm(focal, "focal_point"),
                          "corner_radius_mm": None, "height_mm": None,
                          "source_refs": [str(x) for x in (focal.get("source_refs") or [])]})

    # walls: semantic intents only.  curved_intent NEVER becomes an arc.
    for i, w in enumerate(candidate.get("walls") or []):
        if not isinstance(w, dict):
            continue
        oid = unique_oid(w.get("object_id"), f"wall")
        raw_type = str(w.get("wall_type") or "")
        if raw_type not in WALL_TYPE_VOCAB:
            unknowns.append({"item": f"wall_type:{oid}", "value": None, "known_status": "unknown",
                             "unknown_reason": f"wall_type={raw_type!r} 不在词表"})
        entry = {"object_id": oid, "kind": "partition_intent", "wall_type": raw_type,
                 "geometry": None, "arc_geometry_generated": False,
                 "curved_intent_semantic_only": raw_type == "curved_intent"}
        if raw_type == "curved_intent":
            unsupported.append({"item": f"curve_wall:{oid}", "source_field": f"walls[{i}].wall_type",
                                "status": "unsupported_unknown",
                                "reason": "curved_intent 仅为语义意图，模型未输出曲线几何；不擅自生成弧墙"})
        else:
            unsupported.append({"item": f"partition:{oid}", "source_field": f"walls[{i}]",
                                "status": "unsupported_unknown",
                                "reason": "片墙仅有意向，生成器不据分区边凭空造墙实体"})
        semantic.append(entry)
        ledger.append(_row(f"walls[{i}].wall_type", f"spatial.semantic_intents[{oid}]",
                           oid, raw_type, entry, "enum", "unsupported"))
    for r in candidate.get("relationships") or []:
        if isinstance(r, dict):
            semantic.append({"kind": "relationship", "value": r, "geometry": False,
                             "note": "空间关系仅语义，按对象 ID 引用"})

    # materials: intent only -- no spec, no product, no price
    materials = []
    for m in candidate.get("materials") or []:
        if not isinstance(m, dict):
            continue
        materials.append({"material_id": str(m.get("material_id") or "mat-unknown"),
                          "name": str(m.get("name") or "材料意向"),
                          "intent": str(m.get("intent") or "仅方向"),
                          "status": "intent_only", "known_status": "unknown", "value": None,
                          "source_refs": [str(x) for x in (m.get("source_refs") or [])]})
    for u in candidate.get("cost_unknown") or []:
        unknowns.append({"item": str(u), "value": None, "known_status": "unknown",
                         "unknown_reason": "模型指出的成本缺项，不填 0"})
        ledger.append(_row("cost_unknown[]", "spatial.unknown_items[]", "cost",
                           str(u), None, "CNY", "unknown"))

    unsupported.extend([
        {"item": "材料规格/产品选型", "source_field": "materials[].intent",
         "status": "unsupported_unknown", "reason": "仅氛围意向，无规格、样板或价源，value=None 不填 0"},
        {"item": "相机/人眼视点", "source_field": "(模型输出无 camera 字段)",
         "status": "unsupported_unknown", "reason": "模型未输出机位；由生成器按入口与最大分区推导并标注假设，不冒充设计视点"},
        {"item": "照度/配光", "source_field": "(无 fixtures 字段)",
         "status": "unsupported_unknown", "reason": "未计算照度与配光，不编数值"},
        {"item": "实测标高/层高", "source_field": "(底图无实测标高)",
         "status": "unsupported_unknown", "reason": "层高为展示假设，不升级为现场实测"},
        {"item": "门窗/柱网/构造", "source_field": "(底图多为此类待复核)",
         "status": "unsupported_unknown", "reason": "不据示意或矩形边界凭空补构件"},
        {"item": "非矩形几何能力", "source_field": "objects[].shape=rect",
         "status": "unsupported_unknown", "reason": "四角化只是同一矩形的表示，不等于真实多边形/曲面设计能力"},
    ])

    # Keep-outs come from the CONFIRMED basemap's parsed region, expressed in the
    # same metre boundary convention the W2 measure() expects.  They are site
    # conditions, not model-generated geometry and not site-verified dimensions.
    obstacles = []
    for k in recon["keepouts"]:
        rect = k.get("rect_m")  # [x, y, width, length] in metres
        if not (isinstance(rect, (list, tuple)) and len(rect) == 4):
            raise RealModelSpatialAdaptationError("KEEPOUT_INVALID",
                                                  "底图保留区缺少 rect_m [x,y,w,l]", stage="basemap")
        x, y, w, l = [str(_dec(v, "keepout")) for v in rect]
        obstacles.append({
            "object_id": str(k.get("object_id") or "keepout"),
            "kind": "obstacle", "name": str(k.get("name") or "保留区"),
            "shape": {"type": "rect", "x": x, "y": y, "width": w, "length": l},
            "material_id": None, "parent_object_id": None,
            "source_refs": [BASEMAP_CONTRACT], "locked": True,
            "properties": {"keepout": True, "source": BASEMAP_CONTRACT,
                           "site_verified": False, "status": k.get("status", "解析确认")},
        })

    artifact_id = str(provenance.get("artifact_id") or "realmodel-shape-fixture")
    source_sha = str(provenance.get("sha256") or sha256_hex(candidate))
    model = {
        "schema_version": "rkd-ai-design-option.v1",
        "set_id": str(provenance.get("set_id") or "realmodel-shape-set"),
        "option_id": str(provenance.get("option_id") or f"{artifact_id}:{candidate.get('strategy_id', 'candidate')}"),
        "revision_no": int(provenance.get("revision_no") or 1),
        "parent_revision_id": provenance.get("parent_revision_id"),
        "strategy": {
            "strategy_id": str(candidate.get("strategy_id") or "realmodel-shape"),
            "statement": str(candidate.get("concept") or candidate.get("statement") or "真实模型形状夹具候选"),
            "tradeoffs": [str(x) for x in (candidate.get("tradeoffs") or [])][:8],
            "source_refs": [artifact_id],
        },
        "boundary": {
            "width": str(Decimal(recon["boundary_mm"][0]) / MM_PER_M),
            "length": str(Decimal(recon["boundary_mm"][1]) / MM_PER_M),
            "unit": "m", "boundary_source": BASEMAP_CONTRACT,
            "entrance": {
                "side": str(recon["entrance"].get("side") or "left"),
                "point": [str(recon["entrance"].get("point_m", [0, 10.3])[0]),
                          str(recon["entrance"].get("point_m", [0, 10.3])[1])],
                "width": str(recon["entrance"].get("width_m", 1.8)),
                "site_verified": False, "status": "待现场复核",
            },
            "obstacles": obstacles,  # confirmed-basemap keep-outs only, no invented model walls
        },
        "objects": [],  # legacy rect objects intentionally NOT populated here
        "relationships": [],
        "circulation": {"path_id": "main-loop", "kind": "loop", "min_width": "1.0",
                        "segments": [], "connections": [list(x) for x in (candidate.get("connections") or [])]},
        "materials": materials,
        "cost": {"currency": "CNY", "budget": {"value": None, "unit": "CNY", "known_status": "unknown",
                                               "unknown_reason": "候选阶段不生成完整估价", "source_refs": []},
                 "known_items": [], "unknown_items": unknowns,
                 "total_project_estimate": {"value": None, "unit": "CNY", "known_status": "unknown",
                                            "unknown_reason": "候选阶段不生成完整项目估价", "source_refs": []},
                 "formal_quote": False},
        "validation": {"rule_version": GEOMETRY_RULE_VERSION, "status": "not_checked",
                       "hard_checks": [], "professional_checks": [], "publication_status": "not_approved"},
        # Coarse legacy enum kept schema-valid; precise offline-fixture provenance
        # lives in spatial.source.origin_kind / design_origin (like the Studio adapter).
        "lifecycle_status": "candidate", "source_kind": "synthetic_design_adapter",
        "generation": {
            "provider_kind": "offline_realmodel_shape_fixture_adapter",
            "provider_name": "RealModelSpatialAdapter",
            "model_id": None, "real_model": False,
            "adapter_version": ADAPTER_VERSION, "prompt_version": "not_applicable_offline",
            "schema_version": "rkd-ai-design-option.v1", "config_hash": sha256_hex(
                {"adapter": ADAPTER_VERSION, "mapping": MAPPING_VERSION, "vocab": VOCAB_VERSION}),
            "input_hash": sha256_hex({"candidate": candidate, "site": recon}),
            "generated_at": created_at,
            "interpretation_method": "deterministic_field_mapping_v1",
        },
        "feedback": {"text": None, "parsed_intents": [], "locks": [],
                     "interpretation_method": "not_applicable_offline"},
        "diff": [], "conflicts": [],
        "change_reason": "离线确定性夹具：真实模型输出形状 -> 版本化 spatial，未调用模型、未生成设计",
        "actor_id": str(provenance.get("actor_id") or "offline-adapter"),
        "created_at": created_at,
        "structure_signature": {},
        "spatial": {
            "schema_version": SPATIAL_VERSION,
            "unit": "mm",
            "origin": {"coordinate_system": "site-local-southwest-origin-x-east-y-north",
                       "source_shape": "RealModelDesignOptionProvider candidate (metric rect)",
                       "unit": "mm", "boundary_mm": recon["boundary_mm"],
                       "note": "与用户确认的 v2 底图同一局部坐标系；矩形四角化不增加形状信息"},
            "zones": zones,
            "circulation": circulation,
            "platforms": platforms,
            "furniture": furniture,
            "ceiling": {"fixtures": [], "status": "unknown",
                        "note": "模型未输出灯具点位/色温；W2 人工天花表达未导入"},
            "materials": materials,
            "views": [],
            "unsupported_items": unsupported,
            "unknown_items": unknowns,
            "source": {
                "origin_kind": origin_kind,
                "artifact_id": artifact_id,
                "sha256": source_sha,
                "contract_version": BASEMAP_CONTRACT,
                "design_origin": {"kind": kind, "declared_by": str(origin.get("declared_by") or "not_declared"),
                                  "declaration": origin.get("declaration"),
                                  "run_refs": [str(x) for x in (origin.get("run_refs") or [])]},
                "site_source": {"source": BASEMAP_CONTRACT, "boundary_mm": recon["boundary_mm"],
                                "boundary_sha256": recon["boundary_sha256"],
                                "site_verified": False, "unverified_facts": recon["unverified_facts"],
                                "keepouts": recon["keepouts"], "entrance": recon["entrance"]},
                "basemap_contract": BASEMAP_CONTRACT,
                "boundary_sha256": recon["boundary_sha256"],
                "boundary_mm": recon["boundary_mm"],
                "site_verified": False,
                "declared_by": str(origin.get("declared_by") or "not_declared"),
                "run_refs": [str(x) for x in (origin.get("run_refs") or [])],
                "parent_revision_uid": provenance.get("parent_revision_id"),
            },
            "adaptation": {
                "adapter_version": ADAPTER_VERSION,
                "mapping_version": MAPPING_VERSION,
                "vocab_version": VOCAB_VERSION,
                "unit_conversion": "m_to_mm_x1000_exact",
                "geometry_mode": "rect_four_corner_from_metric_rect",
                "non_rectangular_capability": False,
                "expression_source": "real_model_output_shape_only_no_w2_manual_expression",
                "basemap_reconciliation": {"files": recon["files"], "status": "verified",
                                           "confirmed_contract": BASEMAP_CONTRACT},
                "object_id_map": id_map,
                "losses": [
                    {"item": "zones[].polygon_mm", "loss": "same_rectangle_four_corners_only",
                     "compensated_by": "none_required_no_shape_in_source"},
                    {"item": "narrative/sequence_role/intent/relationships",
                     "loss": "semantic_only_not_geometry", "compensated_by": "spatial.semantic_intents"},
                    {"item": "walls[].wall_type incl. curved_intent", "loss": "no_wall_or_arc_geometry",
                     "compensated_by": "spatial.unsupported_items + semantic_intents"},
                    {"item": "material specs / prices / camera / illuminance / measured height",
                     "loss": "not_in_model_output", "compensated_by": "unknown_items value=None"},
                ],
                "field_ledger": ledger,
                "diff_baseline": "unknown_missing_parent" if not provenance.get("parent_revision_id") else "source_parent",
            },
            "semantic_intents": semantic,
            "area_table": [{"name": z["name"], "area_sqm": z["area_sqm"]} for z in zones],
            "open_questions": [str(u["item"]) for u in unknowns],
        },
    }
    # Legacy objects[] and circulation.segments[] are populated from the SAME
    # rects as the spatial section so the document satisfies the main
    # ai-design-option contract.  They are explicitly bbox_derived: geometry
    # authority is spatial.zones[].polygon_mm, never these rectangles.
    legacy_objects: list[dict] = []
    for z in zones:
        legacy_objects.append({"object_id": z["object_id"], "kind": "functional_zone",
                               "name": z["name"], "shape": _mm_shape(z["polygon_mm"]),
                               "material_id": None, "parent_object_id": None,
                               "source_refs": z["source_refs"], "locked": False,
                               "properties": {"geometry_mode": "bbox_derived",
                                              "exact_polygon_ref": f"spatial.zones:{z['object_id']}",
                                              "zone_role": z["raw_zone_role"],
                                              "non_rectangular_capability": False}})
    for f in furniture:
        poly = [[f["x_mm"] - f["w_mm"] / 2, f["y_mm"] - f["d_mm"] / 2],
                [f["x_mm"] + f["w_mm"] / 2, f["y_mm"] - f["d_mm"] / 2],
                [f["x_mm"] + f["w_mm"] / 2, f["y_mm"] + f["d_mm"] / 2],
                [f["x_mm"] - f["w_mm"] / 2, f["y_mm"] + f["d_mm"] / 2]]
        legacy_objects.append({"object_id": f["object_id"], "kind": "display_object",
                               "name": f["catalog_id"], "shape": _mm_shape(poly),
                               "material_id": None, "parent_object_id": None,
                               "source_refs": f["source_refs"], "locked": False,
                               "properties": {"geometry_mode": "bbox_derived",
                                              "catalog_id": f["catalog_id"],
                                              "intended_parent": f.get("intended_parent")}})
    for e in semantic:
        if e.get("kind") != "partition_intent":
            continue
        w = next((w for w in (candidate.get("walls") or [])
                  if isinstance(w, dict) and str(w.get("object_id")) == e["object_id"]), None)
        if not w:
            continue
        wall_poly = _rect_polygon_mm(w, f"wall:{e['object_id']}")
        legacy_objects.append({"object_id": e["object_id"], "kind": "partition",
                               "name": str(w.get("name") or e["object_id"]),
                               "shape": _mm_shape(wall_poly),
                               "material_id": None, "parent_object_id": None,
                               "source_refs": [], "locked": False,
                               "properties": {"geometry_mode": "bbox_derived",
                                              "wall_type": e["wall_type"],
                                              "arc_geometry_generated": False}})
    for b in candidate.get("entrance_buffers") or []:
        if not isinstance(b, dict):
            continue
        legacy_objects.append({"object_id": str(b.get("object_id") or "entrance:buffer"),
                               "kind": "entrance_marker",
                               "name": str(b.get("name") or "入口门斗"),
                               "shape": _mm_shape(_rect_polygon_mm(b, "entrance_buffer")),
                               "material_id": None, "parent_object_id": None,
                               "source_refs": [], "locked": False,
                               "properties": {"geometry_mode": "bbox_derived",
                                              "semantic_only": True}})
    model["objects"] = legacy_objects
    model["circulation"]["segments"] = [
        {"segment_id": c["object_id"], "shape": _mm_shape(
            [[c["path_mm"][0][0], min(p[1] for p in c["path_mm"])],
             [c["path_mm"][-1][0], min(p[1] for p in c["path_mm"])],
             [c["path_mm"][-1][0], min(p[1] for p in c["path_mm"]) + c["width_mm"]],
             [c["path_mm"][0][0], min(p[1] for p in c["path_mm"]) + c["width_mm"]]])}
        for c in circulation]
    return model


def diff_spatial(previous: dict | None, current: dict) -> list[dict]:
    """Object-level field diff of two spatial projections (stable object ids)."""
    if not previous:
        return []
    out: list[dict] = []

    def collect(sp: dict, group: str, fields: tuple[str, ...]) -> dict:
        return {str(item["object_id"]): {f: item.get(f) for f in fields}
                for item in sp.get(group, [])}

    specs = (("zones", ("polygon_mm", "area_sqm", "role", "name")),
             ("furniture", ("x_mm", "y_mm", "w_mm", "d_mm", "catalog_id")),
             ("circulation", ("width_mm", "path_mm")),
             ("platforms", ("polygon_mm", "corner_radius_mm", "height_mm")))
    for group, fields in specs:
        before, after = collect(previous, group, fields), collect(current, group, fields)
        for oid in sorted(set(before) | set(after)):
            for field in fields:
                b, a = before.get(oid, {}).get(field), after.get(oid, {}).get(field)
                if b != a:
                    out.append({"object_id": oid, "field": f"spatial.{group}.{field}",
                                "before": b, "after": a, "reason": "同一稳定对象 ID 的上游输出变化"})
    return out
