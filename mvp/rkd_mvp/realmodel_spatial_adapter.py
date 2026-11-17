"""Offline, deterministic adapter: real-model OUTPUT -> versioned spatial (v2).

v2 remediation over dcc11f7 (see W3-adapter-architect/review-and-remediation.md):

* R01 keep-outs / entrance / unknown facts are EXTRACTED from the hash-verified
  ``底图数据.json`` + ``01_真实场地底图.svg`` and caller parameters are
  reconciled item by item.  A caller can no longer empty keep-outs or rename an
  assumption into a site fact.
* R02 provenance is verified: declared candidate SHA must equal the real bytes,
  ``real_model`` claims require an on-disk run record with matching hashes and
  consistent ``generation.real_model``; fixture/human/unknown stay labelled and
  a fabricated parent is rejected.
* R04 circulation centreline follows the rectangle's real main axis; ambiguous
  square-ish segments are declared unknown; ``branch``/``loop`` is preserved.
* R06 ``diff_spatial`` covers geometry, materials, source/site/semantic/parent
  and object add/remove, with explicit change kinds.
* R03 ``adapt_persisted_candidate`` consumes an ALREADY PERSISTED
  ``rkd-ai-design-option.v1`` document (objects[].shape / circulation.segments),
  not a hand-written raw response shape.

No network, no key reads, no invented geometry, no ``unknown`` -> 0.
The caller decides whether anything is ever committed.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

ADAPTER_VERSION = "rkd-realmodel-spatial-adapter.v3"
TOP_LEVEL_VERSION = "rkd-ai-design-option.v2"   # unique authoritative contract revision
OUTPUT_SPATIAL_VERSION = "rkd-realmodel-spatial.v2"
SPATIAL_VERSION = OUTPUT_SPATIAL_VERSION  # backwards alias for prior verifiers
MAPPING_VERSION = "realmodel-output-to-spatial.v2"
VOCAB_VERSION = "rkd-design-vocab.v1"
GEOMETRY_RULE_VERSION = "rkd-realmodel-adapter-geometry.v2"
BASEMAP_CONTRACT = "rkd-site-basemap.v2"
MM_PER_M = Decimal("1000")
AXIS_AMBIGUOUS_RATIO = Decimal("1.2")

CONFIRMED_BASEMAP_FILES = {
    "阶段1_底图核对.pdf": (3346417, "7a8c212b84d1c01001291fc62145a729f6a90d293c8fe92bb3213fd221aad35b"),
    "阶段1_底图核对.html": (9890, "7a927286ad003af1afd1c2ace678dc8d4485004e5d711e2d6280d6a8cca46d1c"),
    "01_真实场地底图.svg": (45225, "bfa02621c86f300e51c3a88669b45a2c730cda5071eb80f0f37b1b7ff0fc3023"),
    "底图数据.json": (8894, "195a2a78d7400e019c3b64043eaf2736810c80cc648299ec3e51c725a6ff31e7"),
    "00_原始平面图_正向.png": (363414, "6a3840dfc731848694c972c30c9209a2f855dadd54555c6349afc448e459488b"),
}
CONFIRMED_BOUNDARY_MM = (26170, 17920)

ZONE_ROLE_VOCAB = {
    "foyer": "arrival", "primary_display": "primary_display", "deep_talk": "negotiation",
    "buffer": "transition", "service": "service",
}
FURNITURE_TYPE_VOCAB = {
    "reception_desk": "reception_desk", "island": "island", "table_chairs": "table_chairs",
    "sofa": "sofa", "plant": "plant", "display_case": "display_case", "storage": "storage",
    "pantry": "pantry", "service_counter": "service_counter", "light_feature": "light_feature",
}
WALL_TYPE_VOCAB = {"solid", "screen", "curved_intent", "feature"}
SEQUENCE_ROLE_VOCAB = {"opening", "development", "climax", "rest", "closing"}
RUN_RECORD_KINDS = {"real_model_run", "local_protocol_stub_run", "human_edit", "fixture_run"}


class RealModelSpatialAdaptationError(Exception):
    def __init__(self, code: str, message: str, *, stage: str = "adaptation") -> None:
        self.code, self.message, self.stage = code, message, stage
        super().__init__(f"{code}: {message}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _m_to_mm(value: Any, field: str) -> int:
    d = _dec(value, field) * MM_PER_M
    if d != d.to_integral_value():
        raise RealModelSpatialAdaptationError("SUB_MM_PRECISION", f"{field} 小于 1mm，拒绝", stage="unit")
    return int(d)


def _rect_polygon_mm(rect: dict, field: str) -> list[list[int]]:
    if not isinstance(rect, dict) or str(rect.get("type") or "rect") != "rect":
        raise RealModelSpatialAdaptationError("UNSUPPORTED_GEOMETRY",
                                              f"{field} 不是 rect，不凭空生成其它几何", stage="geometry")
    x, y = _m_to_mm(rect.get("x", 0), f"{field}.x"), _m_to_mm(rect.get("y", 0), f"{field}.y")
    w, h = _m_to_mm(rect.get("width", 0), f"{field}.width"), _m_to_mm(rect.get("length", 0), f"{field}.length")
    if w <= 0 or h <= 0:
        raise RealModelSpatialAdaptationError("DEGENERATE_RECT", f"{field} 宽或长为非正数", stage="geometry")
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _mm_shape(poly: list[list[float]]) -> dict[str, str]:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)

    def m(v: float) -> str:
        return format((Decimal(str(v)) / MM_PER_M).quantize(Decimal("0.001")).normalize(), "f")

    return {"type": "rect", "x": m(x0), "y": m(y0), "width": m(x1 - x0), "length": m(y1 - y0)}


def _require_within(poly: list[list[float]], boundary_mm: list[int], label: str) -> None:
    for x, y in poly:
        if x < 0 or y < 0 or x > boundary_mm[0] or y > boundary_mm[1]:
            raise RealModelSpatialAdaptationError(
                "OBJECT_OUTSIDE_BOUNDARY",
                f"{label} 坐标 ({x},{y})mm 越出确认底图 {boundary_mm[0]}x{boundary_mm[1]}mm", stage="geometry")


def _shoelace_m2(poly: list[list[float]]) -> float:
    area2 = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        area2 += x1 * y2 - x2 * y1
    return abs(area2) / 2.0 / 1_000_000.0


def _row(src: str, dst: str, oid: str, sv: Any, tv: Any, unit: str, status: str) -> dict:
    if status not in {"mapped", "preserved", "unknown", "unsupported"}:
        raise ValueError("bad ledger status")
    return {"source_field": src, "target_field": dst, "object_id": oid, "source_value": sv,
            "target_value": tv, "unit": unit, "status": status}


# ------------------------------------------------------- R01: basemap facts
def _svg_rects(svg_text: str) -> list[tuple[int, int, int, int, str]]:
    """(x, y, width, height, attrs) for every <rect> in the confirmed SVG."""
    out = []
    for match in re.finditer(r"<rect\s+([^>]*?)/?>", svg_text):
        attrs = dict(re.findall(r'(\w[\w-]*)="([^"]*)"', match.group(1)))
        try:
            out.append((int(attrs["x"]), int(attrs["y"]), int(attrs["width"]),
                        int(attrs["height"]), match.group(1)))
        except (KeyError, ValueError):
            continue
    return out


def _load_basemap_facts(basemap_dir: Any) -> dict:
    """Extract boundary, keep-outs and entrance fact from hashed files only."""
    from pathlib import Path

    base = Path(basemap_dir)
    files = []
    for name, (size, digest) in CONFIRMED_BASEMAP_FILES.items():
        path = base / name
        if not path.is_file():
            raise RealModelSpatialAdaptationError("BASEMAP_FILE_MISSING", f"缺少已确认底图文件 {name}", stage="basemap")
        raw = path.read_bytes()
        if len(raw) != size or sha256_bytes(raw) != digest:
            raise RealModelSpatialAdaptationError(
                "BASEMAP_SHA_MISMATCH",
                f"{name} 字节/SHA 与用户确认的 v2 绑定不一致（{len(raw)}/{sha256_bytes(raw)[:12]}）", stage="basemap")
        files.append({"name": name, "bytes": size, "sha256": digest})
    try:
        data = json.loads((base / "底图数据.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RealModelSpatialAdaptationError("BASEMAP_JSON_INVALID", f"底图数据.json 不可解析：{error}", stage="basemap")
    if str(data.get("contract_version") or "") != BASEMAP_CONTRACT:
        raise RealModelSpatialAdaptationError("BASEMAP_CONTRACT_MISMATCH", "底图数据.json 契约版本不是 v2", stage="basemap")
    svg_text = (base / "01_真实场地底图.svg").read_text(encoding="utf-8")

    # boundary: JSON declared metres + SVG outer rect, must agree exactly
    bw, bh = _m_to_mm(data.get("boundary", {}).get("width_m"), "basemap.boundary.width_m"), \
             _m_to_mm(data.get("boundary", {}).get("length_m"), "basemap.boundary.length_m")
    if (bw, bh) != CONFIRMED_BOUNDARY_MM:
        raise RealModelSpatialAdaptationError("BASEMAP_BOUNDARY_MISMATCH",
                                              f"底图数据.json 边界 {bw}x{bh} 与绑定不一致", stage="basemap")
    svg_boundary = [(x, y, w, h) for x, y, w, h, attrs in _svg_rects(svg_text)
                    if 'fill="#fbfcfd"' in attrs and 'stroke="#e3e8ec"' in attrs]
    if not any(x == 0 and y == 0 and w == bw and h == bh for x, y, w, h in svg_boundary):
        raise RealModelSpatialAdaptationError("BASEMAP_SVG_BOUNDARY_MISMATCH",
                                              "SVG 外轮廓矩形与 JSON 边界不一致", stage="basemap")

    # keep-outs: SVG machine-readable rects matched BY DIMENSION to the JSON
    # element text (labels sit far from their rects, so text proximity is
    # unreliable).  The dimension match is the deterministic binding key.
    labels = {"楼梯": "keepout-stair", "卫生间湿区": "keepout-bath"}
    elements_by_label = {}
    for label in labels:
        element = next((e for e in data.get("elements", [])
                        if isinstance(e, dict) and label in str(e.get("element", ""))), None)
        if not element:
            raise RealModelSpatialAdaptationError("BASEMAP_KEEPOUT_ELEMENT_MISSING",
                                                  f"JSON 缺少 {label} 元素", stage="basemap")
        dims = re.findall(r"(\d+(?:\.\d+)?)\s*[×x]\s*(\d+(?:\.\d+)?)\s*m", str(element.get("detail", "")))
        if not dims:
            raise RealModelSpatialAdaptationError("BASEMAP_KEEPOUT_DIMENSION_MISSING",
                                                  f"JSON {label} 无尺寸文本", stage="basemap")
        elements_by_label[label] = (element, (float(dims[0][0]), float(dims[0][1])))
    keepouts = []
    used = set()
    for x, y, w, h, attrs in _svg_rects(svg_text):
        w_m, h_m = w / 1000, h / 1000
        label = next((lab for lab, (_el, (dw, dh)) in elements_by_label.items()
                      if lab not in used and abs(dw - w_m) <= 0.01 and abs(dh - h_m) <= 0.01), None)
        if not label:
            continue
        used.add(label)
        element, _dims = elements_by_label[label]
        site_y = bh - (y + h)  # SVG y is top-down; site +Y is north
        rect_m = [x / 1000, site_y / 1000, w_m, h_m]
        keepouts.append({"object_id": labels[label], "name": f"{label}（保留）",
                         "rect_m": rect_m, "status": str(element.get("status") or "解析确认"),
                         "source_field": f"01_真实场地底图.svg rect({x},{y},{w},{h}) + 底图数据.json elements[{label}]",
                         "site_verified": False})
    if {k["object_id"] for k in keepouts} != set(labels.values()):
        raise RealModelSpatialAdaptationError("BASEMAP_KEEPOUT_SET_MISMATCH",
                                              f"提取保留区集合不完整：{[k['object_id'] for k in keepouts]}", stage="basemap")

    # entrance: west-side inference is a basemap FACT with unverified status;
    # the SVG arrow position is an inferred, replaceable concept assumption.
    entrance_element = next((e for e in data.get("elements", [])
                             if isinstance(e, dict) and "主入口" in str(e.get("element", ""))), None)
    if not entrance_element:
        raise RealModelSpatialAdaptationError("BASEMAP_ENTRANCE_ELEMENT_MISSING", "JSON 缺少主入口元素", stage="basemap")
    arrow = re.search(r'<path\s+d="M\s+(\d+)\s+(\d+)\s+L\s+(\d+)\s+(\d+)"[^>]*>[\s\S]{0,200}?主入口', svg_text)
    arrow_y = bh - int(arrow.group(2)) if arrow else None
    entrance_fact = {"side": "left", "site_verified": False,
                     "status": str(entrance_element.get("status") or "待现场复核"),
                     "inferred_point_m": [0, arrow_y / 1000] if arrow_y is not None else None,
                     "point_known_status": "unknown", "width_m": None, "width_known_status": "unknown",
                     "source_field": "底图数据.json elements[主入口位置] + SVG 箭头（推断·待复核）"}
    unverified = []
    for e in data.get("elements", []):
        if isinstance(e, dict) and "复核" in str(e.get("status", "")):
            unverified.append(str(e.get("element") or ""))
    for i in range(int(data.get("counts", {}).get("unresolved_topology_items") or 0)):
        unverified.append(f"拓扑复核标记#{i + 1}")
    return {"contract_version": BASEMAP_CONTRACT, "boundary_mm": [bw, bh],
            # file-byte digest only; NOT a site snapshot digest
            "basemap_files_sha256": sha256_hex({f["name"]: f["sha256"] for f in files}),
            "boundary_sha256": sha256_hex({f["name"]: f["sha256"] for f in files}),  # legacy alias
            "files": files, "keepouts": keepouts, "entrance_fact": entrance_fact,
            "unverified_facts": unverified, "site_verified": False,
            "json_sha256": next(f["sha256"] for f in files if f["name"] == "底图数据.json"),
            "svg_sha256": next(f["sha256"] for f in files if f["name"] == "01_真实场地底图.svg")}


def reconcile_site(basemap_dir: Any, site: dict) -> dict:
    """R01: reconcile caller site against hashed basemap facts, fail closed."""
    facts = _load_basemap_facts(basemap_dir)
    if str(site.get("contract_version") or "") != BASEMAP_CONTRACT:
        raise RealModelSpatialAdaptationError("BASEMAP_CONTRACT_MISMATCH", "site.contract_version 不是 v2", stage="basemap")
    if str(site.get("boundary_source") or "") != BASEMAP_CONTRACT:
        raise RealModelSpatialAdaptationError(
            "SITE_BOUNDARY_MISMATCH",
            f"输入边界来源={site.get('boundary_source') or '缺失'}；不接受测试边界替代", stage="basemap")
    bw, bh = _m_to_mm(site.get("width_m"), "site.width_m"), _m_to_mm(site.get("length_m"), "site.length_m")
    if (bw, bh) != tuple(facts["boundary_mm"]):
        raise RealModelSpatialAdaptationError("SITE_BOUNDARY_MISMATCH",
                                              f"输入边界 {bw}x{bh} 与确认底图不一致", stage="basemap")

    # keep-outs: exact set and exact coordinates, no missing/extra/misplaced
    caller_keepouts = site.get("keepouts")
    if not isinstance(caller_keepouts, list):
        raise RealModelSpatialAdaptationError("KEEPOUT_MISSING", "site.keepouts 缺失", stage="basemap")
    by_id_fact = {k["object_id"]: k for k in facts["keepouts"]}
    by_id_caller: dict[str, dict] = {}
    for k in caller_keepouts:
        if not isinstance(k, dict) or not k.get("object_id"):
            raise RealModelSpatialAdaptationError("KEEPOUT_INVALID", "保留区对象缺少 object_id", stage="basemap")
        oid = str(k["object_id"])
        if oid in by_id_caller:
            raise RealModelSpatialAdaptationError("KEEPOUT_DUPLICATE", f"保留区重复：{oid}", stage="basemap")
        by_id_caller[oid] = k
    if set(by_id_caller) != set(by_id_fact):
        raise RealModelSpatialAdaptationError("KEEPOUT_SET_MISMATCH",
                                              f"保留区集合不符：调用者 {sorted(by_id_caller)} vs 底图 {sorted(by_id_fact)}",
                                              stage="basemap")
    for oid, fact in by_id_fact.items():
        cr = by_id_caller[oid].get("rect_m")
        if not (isinstance(cr, (list, tuple)) and len(cr) == 4):
            raise RealModelSpatialAdaptationError("KEEPOUT_RECT_INVALID", f"{oid} 缺少 rect_m", stage="basemap")
        got = [_m_to_mm(cr[0], f"{oid}.x"), _m_to_mm(cr[1], f"{oid}.y"),
               _m_to_mm(cr[2], f"{oid}.w"), _m_to_mm(cr[3], f"{oid}.h")]
        exp = [_m_to_mm(v, f"{oid}.exp") for v in fact["rect_m"]]
        if got != exp:
            raise RealModelSpatialAdaptationError("KEEPOUT_MISPLACED",
                                                  f"{oid} 坐标 {got}mm 与底图 {exp}mm 不符", stage="basemap")

    # entrance: side must match; a different point needs an explicit replaceable
    # concept assumption; claiming site_verified / fact is rejected.
    caller_ent = site.get("entrance") or {}
    if str(caller_ent.get("side") or "") != facts["entrance_fact"]["side"]:
        raise RealModelSpatialAdaptationError("ENTRANCE_SIDE_CONFLICT",
                                              "入口方位与底图西门厅推断不一致", stage="basemap")
    if caller_ent.get("site_verified") is True or caller_ent.get("is_fact") is True:
        raise RealModelSpatialAdaptationError("ENTRANCE_FACT_CONFLICT",
                                              "入口未现场实测，不得标为底图事实", stage="basemap")
    point = caller_ent.get("point_m")
    assumption = caller_ent.get("assumption") or {}
    fact_point = facts["entrance_fact"]["inferred_point_m"]
    point_m = [float(_dec(point[0], "entrance.x")), float(_dec(point[1], "entrance.y"))] \
        if isinstance(point, (list, tuple)) and len(point) == 2 else None
    if point_m is not None and fact_point is not None and abs(point_m[1] - fact_point[1]) > 0.001:
        if not (isinstance(assumption, dict) and assumption.get("kind") == "concept_replaceable"
                and assumption.get("reason")):
            raise RealModelSpatialAdaptationError(
                "ENTRANCE_ASSUMPTION_UNDECLARED",
                f"入口点 {point_m} 与底图推断 {fact_point} 不同，必须声明 concept_replaceable 假设及理由", stage="basemap")

    caller_unverified = {str(u) for u in (site.get("unverified_facts") or [])}
    required = {u for u in facts["unverified_facts"] if "拓扑复核标记" not in u}
    missing = required - caller_unverified
    if missing:
        raise RealModelSpatialAdaptationError("UNVERIFIED_FACTS_MISMATCH",
                                              f"调用者遗漏底图未核项：{sorted(missing)[:4]}", stage="basemap")

    # SNAPSHOT BINDING: the declared snapshot digest must equal a rebuild from
    # the same entrance assumption + basemap facts.  A digest cannot be asserted
    # independently of the data it claims to cover.
    from . import site_snapshot as SS
    try:
        snapshot = SS.snapshot_from_site(site, facts)
    except SS.SiteSnapshotError as error:
        raise RealModelSpatialAdaptationError(error.code, error.message, stage="basemap") from error
    declared_assumption = (site.get("site_snapshot") or {}).get("entrance_assumption") \
        if isinstance(site.get("site_snapshot"), dict) else None
    if declared_assumption and point_m is not None:
        declared_point = declared_assumption.get("value_m")
        if declared_point is not None and (
                abs(float(declared_point[0]) - point_m[0]) > 1e-6 or
                abs(float(declared_point[1]) - point_m[1]) > 1e-6):
            raise RealModelSpatialAdaptationError(
                "ENTRANCE_DECLARATION_CONFLICT",
                f"site.entrance.point_m={point_m} 与快照入口 {declared_point} 不一致", stage="basemap")
    return {**facts,
            "site_snapshot": snapshot,
            "site_snapshot_sha256": snapshot["sha256"],
            "basemap_files_sha256": snapshot["basemap_files_sha256"],
            "entrance": {"side": facts["entrance_fact"]["side"], "point_m": point_m,
                         "width_m": caller_ent.get("width_m") or 1.8,  # declared assumption, site_verified=false
                         "status": facts["entrance_fact"]["status"],
                         "site_verified": False,
                         "point_source": ("basemap_inferred" if fact_point is not None and point_m == fact_point
                                          else "caller_concept_assumption"),
                         "assumption": assumption},
            "unverified_facts": sorted(caller_unverified | set(facts["unverified_facts"]))}


# ------------------------------------------------------- R02: source evidence
def verify_source(provenance: dict, candidate: dict, *, run_verifier=None,
                  site_snapshot_sha256: str | None = None) -> dict:
    """Verify provenance against the CONTROLLED RUN SERVICE, not caller JSON.

    ``run_verifier`` must be the read-only capability produced by
    ``ControlledRunService.verifier()``.  A caller-built ledger, a dict or any
    duck-typed object is rejected (``RUN_VERIFIER_UNTRUSTED``): a signature over
    caller-supplied bytes proves nothing about a real model call.

    With no verifier (or no matching issued run id) an unverifiable source stays
    ``unknown`` and a ``real_model`` claim is rejected.  A candidate SHA / record
    SHA computed by the caller is NOT authenticity evidence.
    """
    try:
        from .controlled_run_ledger import RunLedgerError, assert_trusted_verifier
    except ImportError:  # loaded by path in an offline repro harness
        import sys as _sys
        from pathlib import Path as _Path
        _here = str(_Path(__file__).resolve().parent)
        if _here not in _sys.path:
            _sys.path.insert(0, _here)
        from controlled_run_ledger import RunLedgerError, assert_trusted_verifier

    prov = provenance or {}
    origin = prov.get("design_origin") or {}
    declared_kind = str(origin.get("kind") or "unknown")
    if declared_kind not in {"real_model", "human", "fixture", "unknown"}:
        raise RealModelSpatialAdaptationError("DESIGN_ORIGIN_INVALID", "design_origin.kind 非法", stage="source")
    candidate_sha = sha256_hex(candidate)
    declared_sha = str(prov.get("sha256") or "")
    if declared_sha != candidate_sha:
        raise RealModelSpatialAdaptationError("CANDIDATE_SHA_MISMATCH",
                                              f"provenance.sha256={declared_sha[:12]} 与候选实际 {candidate_sha[:12]} 不符",
                                              stage="source")
    frame = prov.get("model_site_boundary_m")
    if not (isinstance(frame, (list, tuple)) and len(frame) == 2) or \
            (_m_to_mm(frame[0], "frame.w"), _m_to_mm(frame[1], "frame.h")) != CONFIRMED_BOUNDARY_MM:
        raise RealModelSpatialAdaptationError("MODEL_FRAME_UNKNOWN_OR_MISMATCH",
                                              "模型原生边界必须提供且与确认 v2 底图一致", stage="basemap")

    project_id = str(prov.get("project_id") or "unknown_project")
    run_refs = [str(r) for r in (origin.get("run_refs") or [])]
    parent = prov.get("parent_revision_id")
    parent_evidence = prov.get("parent_evidence") or {}
    parent_candidate_sha = (str(parent_evidence.get("candidate_sha256") or "")
                            if isinstance(parent_evidence, dict) else "")
    if parent and not parent_candidate_sha:
        raise RealModelSpatialAdaptationError("PARENT_UNVERIFIED",
                                              f"父修订 {parent} 未提供父候选摘要", stage="source")

    prov_snapshot = str(prov.get("site_snapshot_sha256") or "")
    if site_snapshot_sha256 is not None and prov_snapshot != str(site_snapshot_sha256):
        raise RealModelSpatialAdaptationError(
            "SOURCE_SNAPSHOT_MISMATCH",
            f"来源声明的场地快照 {prov_snapshot[:12] or '缺失'} 与本次适配快照 "
            f"{str(site_snapshot_sha256)[:12]} 不符；不得把别的场地的运行挂到本候选",
            stage="source")

    verified_records: list[dict] = []
    verifier = None
    if run_verifier is None:
        if declared_kind == "real_model" or run_refs:
            raise RealModelSpatialAdaptationError(
                "RUN_VERIFIER_ABSENT",
                "未注入受控服务验证能力；自报运行记录/摘要不能作为真实性证据", stage="source")
    else:
        try:
            verifier = assert_trusted_verifier(run_verifier)
        except RunLedgerError as error:
            raise RealModelSpatialAdaptationError(error.code, error.message, stage="source") from error
        for ref in run_refs:
            try:
                rec = verifier.verify(
                    ref, project_id=project_id, candidate_sha256=candidate_sha,
                    site_snapshot_sha256=(str(site_snapshot_sha256) if site_snapshot_sha256 else None),
                    parent_revision_id=parent,
                    parent_candidate_sha256=parent_candidate_sha or None)
            except RunLedgerError as error:
                raise RealModelSpatialAdaptationError(error.code, error.message, stage="source") from error
            verified_records.append(rec)

    if declared_kind == "real_model":
        if not verified_records:
            raise RealModelSpatialAdaptationError(
                "DESIGN_ORIGIN_UNVERIFIED",
                "real_model 声明没有受控服务可核验的真实运行记录", stage="source")
        if any(r.get("simulated") is not False or r.get("kind") != "real_model_run"
               for r in verified_records):
            raise RealModelSpatialAdaptationError("RUN_RECORD_NOT_REAL",
                                                  "运行记录不是非模拟真实模型运行", stage="source")
        if parent and not verifier.revision_registered(project_id, str(parent)):
            raise RealModelSpatialAdaptationError(
                "PARENT_UNREGISTERED",
                f"父修订 {parent} 未经持久仓储登记；任意父链不能算已解析", stage="source")
        kind, origin_kind, generation_real_model = "real_model", "real_model_output", True
    elif declared_kind == "unknown" and verified_records:
        # Evidence exists but provenance cannot be safely promoted: stay unknown.
        kind, origin_kind, generation_real_model = "unknown", "unknown_origin", False
    else:
        kind = declared_kind
        origin_kind = {"fixture": "fixture_shape", "human": "human_edited", "unknown": "unknown_origin"}[kind]
        generation_real_model = False

    parent_verified = bool(verifier) and bool(verified_records) and parent is not None and \
        verifier.revision_registered(project_id, str(parent))
    run_evidence = [{
        "run_id": r["run_id"], "kind": r["kind"], "simulated": r["simulated"],
        "issuer": r["issuer"], "issuer_id": r.get("issuer_id"),
        "admission_scope": r.get("admission_scope"),
        "project_id": r["project_id"],
        "candidate_sha256": r["candidate_sha256"], "input_hash": r["input_hash"],
        "output_sha256": r["output_sha256"], "model": r["model"],
        "prompt_version": r["prompt_version"],
        "site_snapshot_sha256": r.get("site_snapshot_sha256"),
        "basemap_files_sha256": r.get("basemap_files_sha256"),
        "transport": r.get("transport"), "request_sha256": r.get("request_sha256"),
        "response_sha256": r.get("response_sha256"),
        "parent_revision_id": r.get("parent_revision_id"),
        "parent_candidate_sha256": r.get("parent_candidate_sha256"),
        "signature_present": bool(r.get("issuer_signature")),
    } for r in verified_records]
    return {
        "kind": kind, "origin_kind": origin_kind, "generation_real_model": generation_real_model,
        "candidate_sha256": candidate_sha, "run_refs": run_refs, "run_evidence": run_evidence,
        "project_id": project_id, "parent_revision_id": parent,
        "parent_verified": parent_verified,
        "declared_by": str(origin.get("declared_by") or "not_declared"),
        "declaration": origin.get("declaration"),
        "site_snapshot_sha256": prov_snapshot or None,
        "diff_baseline": ("source_parent" if parent_verified else
                          ("unknown_missing_parent" if parent else "none_root")),
        "source_verification_note": ("受控服务观测实际请求/响应后签发并验签；自报文件/哈希不作为证据"
                                     if verified_records else
                                     "无可核验运行记录；来源未升级为真实"),
    }


# ------------------------------------------------------- R04: axis-aware path
def path_centreline(poly: list[list[int]], segment_id: str) -> dict:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    wd, hd = Decimal(w), Decimal(h)
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    if wd >= hd * AXIS_AMBIGUOUS_RATIO:
        return {"axis": "horizontal", "axis_known_status": "model_declared",
                "path_mm": [[min(xs), cy], [max(xs), cy]], "width_mm": h}
    if hd >= wd * AXIS_AMBIGUOUS_RATIO:
        return {"axis": "vertical", "axis_known_status": "model_declared",
                "path_mm": [[cx, min(ys)], [cx, max(ys)]], "width_mm": w}
    return {"axis": "ambiguous_unknown", "axis_known_status": "unknown",
            "path_mm": [[cx, cy], [cx, cy]], "footprint_polygon_mm": poly, "width_mm": min(w, h),
            "unknown_reason": f"{segment_id} 近方形（{w}x{h}mm），主轴不可判定，不猜测方向"}


# ------------------------------------------------------- R04b: reversible rect
def axis_preserving_rect_mm(declared_bbox: list[int], axis: dict,
                            segment_id: str) -> list[int]:
    """Rebuild the legacy rectangle from centreline + width, direction-aware.

    The 2253899 adapter always rebuilt a HORIZONTAL rectangle from the
    centreline, so a vertical 1.2x4.1 m path became ``width=0, length=1.2``.
    This reconstructs along the declared axis and proves the result equals the
    source rectangle; any mismatch fails closed instead of emitting a
    degenerate shape.
    """
    x, y, w, h = (int(v) for v in declared_bbox)
    orientation = str(axis.get("axis") or "")
    if orientation == "horizontal":
        xs = [p[0] for p in axis["path_mm"]]
        ys = [p[1] for p in axis["path_mm"]]
        rebuilt = [min(xs), (min(ys) + max(ys) - int(axis["width_mm"])) // 2,
                   max(xs) - min(xs), int(axis["width_mm"])]
    elif orientation == "vertical":
        xs = [p[0] for p in axis["path_mm"]]
        ys = [p[1] for p in axis["path_mm"]]
        rebuilt = [(min(xs) + max(xs) - int(axis["width_mm"])) // 2, min(ys),
                   int(axis["width_mm"]), max(ys) - min(ys)]
    else:
        rebuilt = [x, y, w, h]
    if rebuilt[2] <= 0 or rebuilt[3] <= 0:
        raise RealModelSpatialAdaptationError(
            "LEGACY_RECT_DEGENERATE",
            f"{segment_id} 的 legacy 矩形退化为 {rebuilt}；拒绝输出零宽/零长动线", stage="geometry")
    if rebuilt != [x, y, w, h]:
        raise RealModelSpatialAdaptationError(
            "LEGACY_RECT_NOT_REVERSIBLE",
            f"{segment_id} 由中心线重构的矩形 {rebuilt} 与源矩形 {[x, y, w, h]} 不一致", stage="geometry")
    return rebuilt


# ------------------------------------------------------- main adaptation
def adapt_candidate(candidate: dict, *, site: dict, basemap_dir: Any,
                    provenance: dict, created_at: str, run_verifier=None) -> dict:
    if not isinstance(candidate, dict):
        raise RealModelSpatialAdaptationError("NOT_A_CANDIDATE", "候选不是 JSON 对象", stage="source")
    recon = reconcile_site(basemap_dir, site)
    source = verify_source(provenance, candidate, run_verifier=run_verifier,
                           site_snapshot_sha256=recon["site_snapshot_sha256"])
    kind = source["kind"]
    ledger: list[dict] = []
    unknowns: list[dict] = []
    unsupported: list[dict] = []
    semantic: list[dict] = []
    id_map: list[dict] = []
    seen: set[str] = set()

    def unique_oid(raw: Any, prefix: str) -> str:
        oid = str(raw or f"{prefix}:{len(seen)}").strip()
        if not oid or oid in seen:
            raise RealModelSpatialAdaptationError("DUPLICATE_OBJECT_ID", f"对象 ID 重复或为空：{oid}", stage="objects")
        seen.add(oid)
        return oid

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
                             "unknown_reason": f"zone_role={raw_role!r} 不在 {VOCAB_VERSION}"})
        ledger.append(_row(f"zones[{oid}].rect(m)", f"spatial.zones[{oid}].polygon_mm", oid,
                           {k: z.get(k) for k in ("x", "y", "width", "length")}, poly, "m->mm", "mapped"))
        ledger.append(_row(f"zones[{oid}].zone_role", f"spatial.zones[{oid}].role", oid, raw_role, role,
                           "enum", "mapped" if role != "unknown" else "unknown"))
        seq = str(z.get("sequence_role") or "")
        if seq:
            if seq not in SEQUENCE_ROLE_VOCAB:
                unknowns.append({"item": f"sequence_role:{oid}", "value": None, "known_status": "unknown",
                                 "unknown_reason": f"sequence_role={seq!r} 不在词表"})
            semantic.append({"object_id": oid, "kind": "sequence_role", "value": seq, "geometry": False})
        if str(z.get("intent") or ""):
            semantic.append({"object_id": oid, "kind": "intent", "value": str(z["intent"]), "geometry": False})
        zones.append({"object_id": oid, "name": str(z.get("name") or oid), "role": role,
                      "polygon_mm": poly, "area_sqm": round(_shoelace_m2(poly), 4),
                      "source_refs": [str(x) for x in (z.get("source_refs") or [])],
                      "geometry_mode": "rect_four_corner_from_metric_rect", "non_rectangular_capability": False,
                      "raw_zone_role": raw_role, "declared_min_area_m2": z.get("min_area_m2"),
                      "material_binding": str(z["material_id"]) if z.get("material_id") else None})
        id_map.append({"source_object_id": oid, "target_object_id": oid, "group": "zones"})

    circulation = []
    for i, p in enumerate(candidate.get("paths") or []):
        if not isinstance(p, dict):
            continue
        poly = _rect_polygon_mm(p, f"path[{i}]")
        _require_within(poly, recon["boundary_mm"], f"path[{i}]")
        sid = str(p.get("segment_id") or f"path:{i}")
        axis = path_centreline(poly, sid)
        xs, ys = [q[0] for q in poly], [q[1] for q in poly]
        declared_rect = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
        item = {"object_id": sid, "path_mm": axis["path_mm"], "width_mm": axis["width_mm"],
                "axis": axis["axis"], "axis_known_status": axis["axis_known_status"],
                "declared_rect_mm": declared_rect,
                "width_known_status": "model_declared_unverified",
                "path_representation": "rect_axis_centerline_from_metric_rect",
                "source_refs": [str(x) for x in (p.get("source_refs") or [])]}
        if "footprint_polygon_mm" in axis:
            item["footprint_polygon_mm"] = axis["footprint_polygon_mm"]
        if "unknown_reason" in axis:
            item["unknown_reason"] = axis["unknown_reason"]
            unknowns.append({"item": f"path_axis:{sid}", "value": None, "known_status": "unknown",
                             "unknown_reason": axis["unknown_reason"]})
        circulation.append(item)
        ledger.append(_row(f"paths[{sid}].rect(m)", f"spatial.circulation[{sid}].path_mm", sid,
                           {k: p.get(k) for k in ("x", "y", "width", "length")}, axis["path_mm"], "m->mm", "mapped"))
        id_map.append({"source_object_id": sid, "target_object_id": sid, "group": "circulation"})
    if len(circulation) < 2:
        raise RealModelSpatialAdaptationError("CIRCULATION_INSUFFICIENT", "动线区段少于 2，拒绝", stage="geometry")
    circulation_ids = {c["object_id"] for c in circulation}
    connections = []
    for pair in candidate.get("connections") or []:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
            continue
        a, b = str(pair[0]), str(pair[1])
        if a not in circulation_ids or b not in circulation_ids:
            raise RealModelSpatialAdaptationError("CONNECTION_UNKNOWN_SEGMENT",
                                                  f"连接引用未知动线段：{a}-{b}", stage="geometry")
        connections.append([a, b])
    circulation_kind = str(candidate.get("circulation_kind") or "")
    if circulation_kind not in {"branch", "loop"}:
        raise RealModelSpatialAdaptationError("CIRCULATION_KIND_UNKNOWN",
                                              "动线类型必须是 branch 或 loop，不猜测", stage="geometry")

    furniture = []

    def add_furniture(f: dict, prefix: str) -> None:
        if not isinstance(f, dict):
            return
        oid = unique_oid(f.get("object_id"), prefix)
        poly = _rect_polygon_mm(f, f"furniture:{oid}")
        _require_within(poly, recon["boundary_mm"], f"furniture:{oid}")
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        w_mm, d_mm = max(xs) - min(xs), max(ys) - min(ys)
        raw_type = str(f.get("furniture_type") or "")
        family = FURNITURE_TYPE_VOCAB.get(raw_type, "unknown")
        if family == "unknown":
            unknowns.append({"item": f"furniture_type:{oid}", "value": None, "known_status": "unknown",
                             "unknown_reason": f"furniture_type={raw_type!r} 不在词表"})
        item = {"object_id": oid, "catalog_id": f"realmodel:{family}", "x_mm": cx, "y_mm": cy,
                "w_mm": w_mm, "d_mm": d_mm, "rot": 0,
                "rotation_source": "not_in_model_output_assumed_axis_aligned", "catalog_spec_known": False,
                "source_refs": [str(x) for x in (f.get("source_refs") or [])],
                "material_binding": str(f["material_id"]) if f.get("material_id") else None}
        if f.get("statement"):
            item["statement"] = str(f["statement"])
        intended = f.get("parent_object_id") or f.get("intended_parent")
        if intended:
            item["intended_parent"] = str(intended)
            semantic.append({"object_id": oid, "kind": "intended_parent", "value": str(intended), "geometry": False})
        if f.get("focal") or prefix == "focal":
            item["focal"] = True
        furniture.append(item)
        id_map.append({"source_object_id": oid, "target_object_id": oid, "group": "furniture"})
        ledger.append(_row(f"furniture[{oid}].rect(m)", f"spatial.furniture[{oid}].{{x_mm,y_mm,w_mm,d_mm}}", oid,
                           {k: f.get(k) for k in ("x", "y", "width", "length")},
                           {"x_mm": cx, "y_mm": cy, "w_mm": w_mm, "d_mm": d_mm}, "m->mm", "mapped"))

    for f in candidate.get("furniture") or []:
        add_furniture(f, "f")
    focal = candidate.get("focal_point")
    if isinstance(focal, dict):
        add_furniture(focal, "focal")
    for b in candidate.get("entrance_buffers") or []:
        if isinstance(b, dict):
            unsupported.append({"item": f"entrance_buffer:{b.get('object_id') or 'buffer'}",
                                "source_field": "entrance_buffers[]", "status": "unsupported_unknown",
                                "reason": "入口由底图事实表达，门斗仅语义，不生成几何"})

    platforms = []
    if isinstance(focal, dict):
        platforms.append({"object_id": str(focal.get("object_id") or "focal:hero"),
                          "name": str(focal.get("name") or "视觉焦点"), "kind": "focal_island",
                          "polygon_mm": _rect_polygon_mm(focal, "focal_point"),
                          "corner_radius_mm": None, "height_mm": None,
                          "source_refs": [str(x) for x in (focal.get("source_refs") or [])]})

    for i, w in enumerate(candidate.get("walls") or []):
        if not isinstance(w, dict):
            continue
        oid = unique_oid(w.get("object_id"), "wall")
        raw_type = str(w.get("wall_type") or "")
        if raw_type not in WALL_TYPE_VOCAB:
            unknowns.append({"item": f"wall_type:{oid}", "value": None, "known_status": "unknown",
                             "unknown_reason": f"wall_type={raw_type!r} 不在词表"})
        entry = {"object_id": oid, "kind": "partition_intent", "wall_type": raw_type, "geometry": None,
                 "arc_geometry_generated": False, "curved_intent_semantic_only": raw_type == "curved_intent"}
        unsupported.append({"item": f"{'curve_wall' if raw_type == 'curved_intent' else 'partition'}:{oid}",
                            "source_field": f"walls[{i}].wall_type", "status": "unsupported_unknown",
                            "reason": ("curved_intent 仅语义意图，未输出曲线几何，不生成弧墙" if raw_type == "curved_intent"
                                       else "片墙仅意向，生成器不据分区边凭空造墙实体")})
        semantic.append(entry)
        ledger.append(_row(f"walls[{i}].wall_type", f"spatial.semantic_intents[{oid}]", oid, raw_type,
                           entry, "enum", "unsupported"))
    for r in candidate.get("relationships") or []:
        if isinstance(r, dict):
            semantic.append({"kind": "relationship", "value": r, "geometry": False,
                             "relation_id": r.get("relation_id"),
                             "source_refs": list(r.get("source_refs") or [])})
            ledger.append(_row(f"relationships[{r.get('relation_id')}]", "spatial.semantic_intents.relationship",
                               str(r.get("relation_id") or ""), r, r, "preserved"))
    if candidate.get("narrative"):
        semantic.append({"kind": "narrative", "value": candidate["narrative"], "geometry": False})
        ledger.append(_row("strategy.narrative", "spatial.semantic_intents.narrative", "strategy",
                           candidate["narrative"], candidate["narrative"], "preserved"))
    # Field-level provenance from the persisted-candidate conversion: nothing is
    # silently dropped; every unsupported kind/geometry is visible downstream.
    mapping_ledger = list(candidate.get("field_ledger") or [])
    for row in mapping_ledger:
        ledger.append({**row, "stage": "persisted_candidate_conversion"})
    source_revision = candidate.get("source_revision") or {}
    for u in (candidate.get("mapping_losses") or []):
        if u.get("status") in {"unsupported_unknown", "unknown"}:
            unsupported.append({"item": str(u.get("item") or "unmapped"),
                                "source_field": "persisted_candidate_conversion",
                                "reason": str(u.get("loss") or u.get("status")),
                                "status": "unsupported_unknown"})

    materials = []
    for m in candidate.get("materials") or []:
        if not isinstance(m, dict):
            continue
        materials.append({"material_id": str(m.get("material_id") or "mat-unknown"),
                          "name": str(m.get("name") or "材料意向"), "intent": str(m.get("intent") or "仅方向"),
                          "status": "intent_only", "known_status": "unknown", "value": None,
                          "source_refs": [str(x) for x in (m.get("source_refs") or [])]})
    for u in candidate.get("cost_unknown") or []:
        unknowns.append({"item": str(u), "value": None, "known_status": "unknown",
                         "unknown_reason": "模型指出的成本缺项，不填 0"})
        ledger.append(_row("cost_unknown[]", "spatial.unknown_items[]", "cost", str(u), None, "CNY", "unknown"))
    for fact in recon["unverified_facts"]:
        if fact not in [u["item"] for u in unknowns]:
            unknowns.append({"item": fact, "value": None, "known_status": "unknown",
                             "unknown_reason": "确认底图标注待现场复核；概念假设可替换，不升级为实测"})
    unsupported.extend([
        {"item": "材料规格/产品/价源", "source_field": "materials[].intent", "status": "unsupported_unknown",
         "reason": "仅氛围意向，value=None，不填 0"},
        {"item": "相机/人眼视点", "source_field": "(模型输出无 camera)", "status": "unsupported_unknown",
         "reason": "机位由生成器按入口与最大分区推导并标假设"},
        {"item": "照度/配光", "source_field": "(无 fixtures)", "status": "unsupported_unknown", "reason": "不编数值"},
        {"item": "实测标高/门窗/柱网/洁具", "source_field": "(底图待复核)", "status": "unsupported_unknown",
         "reason": "不据矩形边凭空补构件"},
        {"item": "非矩形几何能力", "source_field": "objects[].shape=rect", "status": "unsupported_unknown",
         "reason": "四角化只是同一矩形，不等于真实多边形/曲面设计能力"},
    ])

    obstacles = []
    for k in recon["keepouts"]:
        x, y, w, h = [str(_dec(v, "keepout")) for v in k["rect_m"]]
        obstacles.append({"object_id": k["object_id"], "kind": "obstacle", "name": k["name"],
                          "shape": {"type": "rect", "x": x, "y": y, "width": w, "length": h},
                          "material_id": None, "parent_object_id": None,
                          "source_refs": [BASEMAP_CONTRACT], "locked": True,
                          "properties": {"keepout": True, "source": k["source_field"],
                                         "site_verified": False, "status": k["status"]}})

    prov = provenance or {}
    artifact_id = str(prov.get("artifact_id") or "offline-adapter-input")
    source_sha = source["candidate_sha256"]
    statement = str(candidate.get("concept") or candidate.get("statement") or
                    (candidate.get("strategy") or {}).get("statement") or "候选适配，非设计成果")
    model = {
        "schema_version": TOP_LEVEL_VERSION,
        "set_id": str(prov.get("set_id") or "offline-set"),
        "option_id": str(prov.get("option_id") or f"{artifact_id}:{candidate.get('strategy_id', 'candidate')}"),
        "revision_no": int(prov.get("revision_no") or 1), "parent_revision_id": source["parent_revision_id"],
        "strategy": {"strategy_id": str(candidate.get("strategy_id") or (candidate.get("strategy") or {}).get("strategy_id")
                                       or "candidate"),
                     "statement": statement[:2000],
                     "tradeoffs": [str(x) for x in (candidate.get("tradeoffs") or
                                                    (candidate.get("strategy") or {}).get("tradeoffs") or [])][:8],
                     "source_refs": [artifact_id]},
        "boundary": {"width": str(Decimal(recon["boundary_mm"][0]) / MM_PER_M),
                     "length": str(Decimal(recon["boundary_mm"][1]) / MM_PER_M), "unit": "m",
                     "boundary_source": BASEMAP_CONTRACT,
                     "entrance": {"side": recon["entrance"]["side"],
                                  "point": [str(recon["entrance"]["point_m"][0]), str(recon["entrance"]["point_m"][1])]
                                  if recon["entrance"]["point_m"] else ["0", "0"],
                                  "width": str(recon["entrance"]["width_m"]),
                                  "site_verified": False, "status": recon["entrance"]["status"],
                                  "point_source": recon["entrance"]["point_source"],
                                  "assumption": recon["entrance"]["assumption"],
                                  "basemap_inferred_point_m": recon["entrance_fact"]["inferred_point_m"]},
                     "obstacles": obstacles},
        "objects": [], "relationships": [],
        "circulation": {"path_id": f"main-{circulation_kind}", "kind": circulation_kind,
                        "min_width": "1.0", "segments": [], "connections": connections},
        "materials": materials,
        "cost": {"currency": "CNY",
                 "budget": {"value": None, "unit": "CNY", "known_status": "unknown",
                            "unknown_reason": "候选阶段不生成完整估价", "source_refs": []},
                 "known_items": [], "unknown_items": unknowns,
                 "total_project_estimate": {"value": None, "unit": "CNY", "known_status": "unknown",
                                            "unknown_reason": "候选阶段不生成完整项目估价", "source_refs": []},
                 "formal_quote": False},
        "validation": {"rule_version": GEOMETRY_RULE_VERSION, "status": "not_checked",
                       "hard_checks": [], "professional_checks": [], "publication_status": "not_approved"},
        "lifecycle_status": "candidate", "source_kind": "synthetic_design_adapter",
        "generation": {"provider_kind": str(prov.get("provider_kind") or "offline_adapter_input"),
                       "provider_name": "RealModelSpatialAdapter", "model_id": prov.get("model_id"),
                       "real_model": source["generation_real_model"],
                       "adapter_version": ADAPTER_VERSION, "prompt_version": str(prov.get("prompt_version") or "offline"),
                       "schema_version": TOP_LEVEL_VERSION,
                       "config_hash": sha256_hex({"adapter": ADAPTER_VERSION, "mapping": MAPPING_VERSION,
                                                  "vocab": VOCAB_VERSION}),
                       "input_hash": sha256_hex({"candidate": candidate,
                                                 "site_snapshot_sha256": recon["site_snapshot_sha256"]}),
                       "generated_at": created_at,
                       "interpretation_method": "deterministic_field_mapping_v2"},
        "feedback": {"text": None, "parsed_intents": [], "locks": [], "interpretation_method": "not_applicable_offline"},
        "diff": [], "conflicts": [],
        "change_reason": "v2 离线适配：底图结构化对账 + 来源证据核验；未调用模型、未生成设计",
        "actor_id": str(prov.get("actor_id") or "offline-adapter"), "created_at": created_at,
        "structure_signature": {},
        "site_snapshot": {"schema_version": recon["site_snapshot"]["schema_version"],
                          "contract": recon["contract_version"],
                          "sha256": recon["site_snapshot_sha256"],
                          "basemap_files_sha256": recon["basemap_files_sha256"],
                          "boundary_mm": recon["boundary_mm"],
                          "site_verified": False,
                          "unverified_facts": recon["unverified_facts"],
                          "entrance_fact": recon["entrance_fact"],
                          "entrance_assumption": recon["site_snapshot"]["entrance_assumption"],
                          "entrance_resolved": recon["entrance"]},
        "source_revision": source_revision,
        "mapping_losses": list(candidate.get("mapping_losses") or []),
        "spatial": {
            "schema_version": SPATIAL_VERSION, "unit": "mm",
            "origin": {"coordinate_system": "site-local-southwest-origin-x-east-y-north",
                       "source_shape": "RealModelDesignOptionProvider candidate / persisted option",
                       "unit": "mm", "boundary_mm": recon["boundary_mm"],
                       "note": "与确认 v2 底图同一局部坐标系；四角化不增加形状信息"},
            "zones": zones, "circulation": circulation, "platforms": platforms, "furniture": furniture,
            "ceiling": {"fixtures": [], "status": "unknown",
                        "note": "模型未输出灯具/色温；W2 人工天花表达未导入"},
            "materials": materials, "views": [],
            "unsupported_items": unsupported, "unknown_items": unknowns,
            "source": {
                "origin_kind": source["origin_kind"], "artifact_id": artifact_id, "sha256": source_sha,
                "contract_version": BASEMAP_CONTRACT,
                "design_origin": {"kind": kind, "declared_by": source["declared_by"],
                                  "declaration": source["declaration"], "run_refs": source["run_refs"],
                                  "run_evidence": source["run_evidence"]},
                "site_source": {"source": BASEMAP_CONTRACT, "boundary_mm": recon["boundary_mm"],
                                "site_snapshot_sha256": recon["site_snapshot_sha256"],
                                "basemap_files_sha256": recon["basemap_files_sha256"],
                                "json_sha256": recon["json_sha256"], "svg_sha256": recon["svg_sha256"],
                                "site_verified": False, "unverified_facts": recon["unverified_facts"],
                                "keepouts": recon["keepouts"], "entrance_fact": recon["entrance_fact"],
                                "entrance_assumption": recon["entrance"]},
                "basemap_contract": BASEMAP_CONTRACT,
                "site_snapshot_sha256": recon["site_snapshot_sha256"],
                "basemap_files_sha256": recon["basemap_files_sha256"],
                "boundary_mm": recon["boundary_mm"], "site_verified": False,
                "declared_by": source["declared_by"], "run_refs": source["run_refs"],
                "parent_revision_uid": source["parent_revision_id"],
                "parent_link_status": ("resolved" if source["parent_verified"] else
                                       ("source_parent_not_imported" if source["parent_revision_id"] else "source_root")),
            },
            "adaptation": {
                "adapter_version": ADAPTER_VERSION, "mapping_version": MAPPING_VERSION,
                "vocab_version": VOCAB_VERSION, "unit_conversion": "m_to_mm_x1000_exact",
                "geometry_mode": "rect_four_corner_from_metric_rect", "non_rectangular_capability": False,
                "expression_source": "real_model_output_only_no_w2_manual_expression",
                "basemap_reconciliation": {"files": recon["files"], "status": "verified_each_item",
                                           "confirmed_contract": BASEMAP_CONTRACT,
                                           "keepouts_checked": len(recon["keepouts"]),
                                           "entrance_status": recon["entrance"]["status"]},
                "source_verification": {"kind": kind, "candidate_sha256": source_sha,
                                        "run_evidence_count": len(source["run_evidence"]),
                                        "generation_real_model": source["generation_real_model"],
                                        "parent_verified": source["parent_verified"],
                                        "project_id": source.get("project_id"),
                                        "site_snapshot_sha256": recon["site_snapshot_sha256"],
                                        "basemap_files_sha256": recon["basemap_files_sha256"],
                                        "run_evidence": source["run_evidence"],
                                        "note": source["source_verification_note"]},
                "source_revision": source_revision,
                "object_id_map": id_map,
                "losses": [
                    {"item": "zones[].polygon_mm", "loss": "same_rectangle_four_corners_only"},
                    {"item": "narrative/sequence/intent/relationships", "loss": "semantic_only_not_geometry"},
                    {"item": "walls incl. curved_intent", "loss": "no_wall_or_arc_geometry"},
                    {"item": "material specs/prices/camera/illuminance/height", "loss": "not_in_model_output"},
                ] + list(candidate.get("mapping_losses") or []),
                "mapping_losses": list(candidate.get("mapping_losses") or []),
                "field_ledger": ledger, "diff_baseline": source["diff_baseline"],
            },
            "semantic_intents": semantic,
            "area_table": [{"name": z["name"], "area_sqm": z["area_sqm"]} for z in zones],
            "open_questions": sorted({str(u["item"]) for u in unknowns}),
        },
    }

    # legacy objects[] / segments[] from the SAME rects (bbox_derived only)
    legacy = []
    for z in zones:
        legacy.append({"object_id": z["object_id"], "kind": "functional_zone", "name": z["name"],
                       "shape": _mm_shape(z["polygon_mm"]), "material_id": None, "parent_object_id": None,
                       "source_refs": z["source_refs"], "locked": False,
                       "properties": {"geometry_mode": "bbox_derived",
                                      "exact_polygon_ref": f"spatial.zones:{z['object_id']}",
                                      "zone_role": z["raw_zone_role"], "non_rectangular_capability": False}})
    for f in furniture:
        poly = [[f["x_mm"] - f["w_mm"] / 2, f["y_mm"] - f["d_mm"] / 2],
                [f["x_mm"] + f["w_mm"] / 2, f["y_mm"] - f["d_mm"] / 2],
                [f["x_mm"] + f["w_mm"] / 2, f["y_mm"] + f["d_mm"] / 2],
                [f["x_mm"] - f["w_mm"] / 2, f["y_mm"] + f["d_mm"] / 2]]
        legacy.append({"object_id": f["object_id"], "kind": "display_object", "name": f["catalog_id"],
                       "shape": _mm_shape(poly), "material_id": None, "parent_object_id": None,
                       "source_refs": f["source_refs"], "locked": False,
                       "properties": {"geometry_mode": "bbox_derived", "catalog_id": f["catalog_id"],
                                      "intended_parent": f.get("intended_parent")}})
    for e in semantic:
        if e.get("kind") != "partition_intent":
            continue
        w = next((w for w in (candidate.get("walls") or [])
                  if isinstance(w, dict) and str(w.get("object_id")) == e["object_id"]), None)
        if not w:
            continue
        legacy.append({"object_id": e["object_id"], "kind": "partition",
                       "name": str(w.get("name") or e["object_id"]),
                       "shape": _mm_shape(_rect_polygon_mm(w, f"wall:{e['object_id']}")),
                       "material_id": None, "parent_object_id": None, "source_refs": [], "locked": False,
                       "properties": {"geometry_mode": "bbox_derived", "wall_type": e["wall_type"],
                                      "arc_geometry_generated": False}})
    for b in candidate.get("entrance_buffers") or []:
        if isinstance(b, dict):
            legacy.append({"object_id": str(b.get("object_id") or "entrance:buffer"), "kind": "entrance_marker",
                           "name": str(b.get("name") or "入口门斗"),
                           "shape": _mm_shape(_rect_polygon_mm(b, "entrance_buffer")),
                           "material_id": None, "parent_object_id": None, "source_refs": [], "locked": False,
                           "properties": {"geometry_mode": "bbox_derived", "semantic_only": True}})
    model["objects"] = legacy
    # Legacy circulation is derived from the SAME source rectangle, along its
    # declared axis, and proven reversible.  No zero-width degenerates.
    model["circulation"]["segments"] = []
    for c in circulation:
        rect = axis_preserving_rect_mm(c["declared_rect_mm"], c, c["object_id"])
        x, y, w, h = rect
        model["circulation"]["segments"].append({
            "segment_id": c["object_id"],
            "shape": _mm_shape([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]),
            "properties": {
                "geometry_mode": "axis_preserving_rect",
                "axis": c["axis"], "axis_known_status": c["axis_known_status"],
                "declared_rect_mm": rect,
                "source_rect_mm": list(c["declared_rect_mm"]),
                "exact_path_ref": f"spatial.circulation:{c['object_id']}",
                "width_known_status": "model_declared_unverified",
            }})
    return model


# ------------------------------------------------------- R03: persisted candidate
def candidate_from_persisted(model: dict) -> tuple[dict, dict]:
    """Read an already-persisted rkd-ai-design-option.v1 document into the adapter shape.

    The authoritative geometry is objects[].shape (metres) exactly as the
    provider stored it.  Returns (candidate_shape, derivation_note).
    """
    if not isinstance(model, dict) or str(model.get("schema_version") or "") not in {
            "rkd-ai-design-option.v1", TOP_LEVEL_VERSION}:
        raise RealModelSpatialAdaptationError("PERSISTED_SCHEMA_MISMATCH",
                                              "输入不是已持久化的 rkd-ai-design-option 候选", stage="source")
    gen = model.get("generation") or {}
    model_sha = sha256_hex(model)
    source_revision = {"option_id": model.get("option_id"),
                       "revision_no": model.get("revision_no"),
                       "model_sha256": model_sha,
                       "parent_revision_id": model.get("parent_revision_id")}
    cand: dict[str, Any] = {
        "strategy_id": (model.get("strategy") or {}).get("strategy_id") or "persisted",
        "concept": (model.get("strategy") or {}).get("statement") or "已持久化候选",
        "tradeoffs": list((model.get("strategy") or {}).get("tradeoffs") or []),
        "zones": [], "walls": [], "furniture": [], "paths": [], "connections": [],
        "circulation_kind": (model.get("circulation") or {}).get("kind"),
        "materials": [], "cost_unknown": [],
        "relationships": [dict(r) for r in (model.get("relationships") or []) if isinstance(r, dict)],
        "narrative": dict((model.get("strategy") or {}).get("narrative") or {}),
        "source_revision": source_revision,
        "field_ledger": [],
        "mapping_losses": [],
    }
    # Per-object material bindings from the authoritative materials list.
    material_index = {str(m.get("material_id")): m for m in (model.get("materials") or [])
                      if isinstance(m, dict)}
    losses: list[dict] = []
    unsupported_kinds: list[dict] = []
    unsupported_geometry: list[dict] = []
    bound_materials: set[str] = set()

    def ledger(src: str, dst: str, oid: str, sv: Any, tv: Any, status: str) -> None:
        cand["field_ledger"].append({"source_field": src, "target_field": dst, "object_id": oid,
                                     "source_value": sv, "target_value": tv,
                                     "unit": "enum", "status": status})

    for obj in model.get("objects") or []:
        if not isinstance(obj, dict):
            losses.append({"item": "非对象条目", "reason": "objects[] 含非 JSON 对象", "status": "unknown"})
            continue
        oid = str(obj.get("object_id") or "")
        shape = obj.get("shape")
        if not isinstance(shape, dict) or str(shape.get("type") or "rect") != "rect":
            unsupported_geometry.append({"object_id": oid, "kind": obj.get("kind"),
                                         "shape_type": (shape or {}).get("type") if isinstance(shape, dict) else None,
                                         "reason": "非矩形几何，适配器不凭空生成形状"})
            losses.append({"item": f"geometry:{oid}", "source_value": shape,
                           "target_value": None, "status": "unsupported_unknown"})
            ledger(f"objects[{oid}].shape", "(不生成几何)", oid, shape, None, "unsupported")
            continue
        props = obj.get("properties") or {}
        base = {"object_id": oid, "name": obj.get("name"),
                "x": shape.get("x"), "y": shape.get("y"),
                "width": shape.get("width"), "length": shape.get("length"),
                "source_refs": list(obj.get("source_refs") or [])}
        # Object-level material id wins over strategy-level intent.
        mat_id = obj.get("material_id") or props.get("material_id")
        if mat_id:
            bound_materials.add(str(mat_id))
            base["material_id"] = str(mat_id)
        kind = str(obj.get("kind") or "")
        if kind == "functional_zone":
            cand["zones"].append({**base, "zone_role": props.get("zone_role"),
                                  "sequence_role": props.get("sequence_role"), "intent": props.get("intent"),
                                  "min_area_m2": obj.get("min_area_m2")})
            ledger(f"objects[{oid}].properties", f"zones[{oid}].role/intent", oid, props, props, "preserved")
        elif kind == "partition":
            cand["walls"].append({**base, "wall_type": props.get("wall_type", "screen")})
        elif kind == "display_object":
            # focal objects keep their focal structure instead of becoming a
            # plain display_object (the previous version lost that fact).
            is_focal = bool(props.get("focal")) or oid.startswith("focal:")
            entry = {**base, "furniture_type": props.get("furniture_type"),
                     "intended_parent": props.get("intended_parent"),
                     "focal": is_focal, "statement": props.get("statement")}
            if is_focal:
                cand["focal_point"] = entry
                ledger(f"objects[{oid}].properties.focal", f"focal_point[{oid}]", oid,
                       True, True, "preserved")
            else:
                cand["furniture"].append(entry)
        elif kind == "entrance_marker":
            cand.setdefault("entrance_buffers", []).append(base)
        else:
            unsupported_kinds.append({"object_id": oid, "kind": kind,
                                      "reason": "未知对象种类；不猜测映射，不静默丢弃"})
            losses.append({"item": f"kind:{oid}", "source_value": kind,
                           "target_value": None, "status": "unsupported_unknown"})
            ledger(f"objects[{oid}].kind", "(unsupported)", oid, kind, None, "unsupported")
    for seg in (model.get("circulation") or {}).get("segments") or []:
        if isinstance(seg, dict) and isinstance(seg.get("shape"), dict):
            cand["paths"].append({"segment_id": seg.get("segment_id"), **seg["shape"]})
    cand["connections"] = [list(p) for p in ((model.get("circulation") or {}).get("connections") or [])]
    for mat in model.get("materials") or []:
        if isinstance(mat, dict):
            cand["materials"].append({"material_id": mat.get("material_id"), "name": mat.get("name"),
                                      "intent": mat.get("intent"), "source_refs": mat.get("source_refs") or []})
    for mid in sorted(bound_materials - set(material_index)):
        losses.append({"item": f"material_binding:{mid}", "source_value": mid,
                       "target_value": None, "status": "unknown",
                       "reason": "对象引用了主材料表不存在的 material_id"})
    for u in (((model.get("cost") or {}).get("unknown_items")) or []):
        if isinstance(u, dict) and u.get("statement"):
            cand["cost_unknown"].append(str(u["statement"]))
    if not cand["relationships"]:
        losses.append({"item": "relationships", "source_value": model.get("relationships"),
                       "target_value": [], "status": "unknown",
                       "reason": "源候选无关系对象，目标不虚构关系"})
    cand["mapping_losses"] = [
        {"item": l.get("item"), "loss": l.get("reason") or l.get("status"),
         "source_value": l.get("source_value"), "target_value": l.get("target_value"),
         "status": l.get("status"), "stage": "persisted_candidate_conversion"}
        for l in losses]
    note = {"source": "persisted_rkd-ai-design-option.v1",
            "source_revision": source_revision,
            "objects_read": len(model.get("objects") or []),
            "segments_read": len(cand["paths"]),
            "relationships_read": len(cand["relationships"]),
            "material_bindings": sorted(bound_materials),
            "focal_mapped": bool(cand.get("focal_point")),
            "unsupported_kinds": unsupported_kinds,
            "unsupported_geometry": unsupported_geometry,
            "losses": losses,
            "field_ledger_count": len(cand["field_ledger"]),
            "provider_kind": gen.get("provider_kind"), "real_model": gen.get("real_model"),
            "generated_at": gen.get("generated_at"),
            "option_id": model.get("option_id"), "revision_no": model.get("revision_no")}
    return cand, note


def verify_persisted_site_snapshot(model: dict, site: dict, basemap_dir: Any) -> dict:
    """P1: prove the persisted candidate was GENERATED on the same site snapshot.

    Checks the declared snapshot digest, boundary frame, entrance point and every
    keep-out obstacle against the hash-verified site.  A candidate drawn on a
    test boundary, on another snapshot or with a different entrance must fail
    here, not be silently re-bound later.
    """
    recon = reconcile_site(basemap_dir, site)
    snap = model.get("site_snapshot") or {}
    declared = str(snap.get("sha256") or "")
    if not declared:
        raise RealModelSpatialAdaptationError(
            "PERSISTED_SNAPSHOT_MISSING", "持久候选没有场地快照摘要；不能证明与本场地同源", stage="site")
    if declared != recon["site_snapshot_sha256"]:
        raise RealModelSpatialAdaptationError(
            "PERSISTED_SNAPSHOT_MISMATCH",
            f"持久候选快照 {declared[:12]} 与本次场地快照 {recon['site_snapshot_sha256'][:12]} 不符",
            stage="site")
    declared_basemap = str(snap.get("basemap_files_sha256") or "")
    if declared_basemap != recon["basemap_files_sha256"]:
        raise RealModelSpatialAdaptationError(
            "PERSISTED_BASEMAP_MISMATCH",
            f"持久候选底图文件摘要 {declared_basemap[:12]} 与确认底图 {recon['basemap_files_sha256'][:12]} 不符",
            stage="site")
    b = model.get("boundary") or {}
    bw, bh = _m_to_mm(b.get("width"), "persisted.width"), _m_to_mm(b.get("length"), "persisted.length")
    if (bw, bh) != tuple(recon["boundary_mm"]):
        raise RealModelSpatialAdaptationError("PERSISTED_FRAME_MISMATCH",
                                              f"持久候选边界 {bw}x{bh} 与场地快照 {recon['boundary_mm']} 不符",
                                              stage="site")
    ent = b.get("entrance") or {}
    ep = ent.get("point") or []
    if len(ep) != 2:
        raise RealModelSpatialAdaptationError("PERSISTED_ENTRANCE_MISSING", "持久候选没有入口点", stage="site")
    ex, ey = _m_to_mm(ep[0], "entrance.x"), _m_to_mm(ep[1], "entrance.y")
    expected = recon["entrance"].get("point_m")
    if not expected:
        raise RealModelSpatialAdaptationError("SITE_ENTRANCE_ASSUMPTION_MISSING", "场地快照没有入口假设", stage="site")
    if (ex, ey) != (_m_to_mm(expected[0], "site.x"), _m_to_mm(expected[1], "site.y")):
        raise RealModelSpatialAdaptationError("PERSISTED_ENTRANCE_MISMATCH",
                                              f"持久候选入口 ({ex},{ey})mm 与场地快照假设不符；不得静默重绑",
                                              stage="site")
    # Obstacles in the persisted candidate must be EXACTLY the snapshot keep-outs.
    got = {}
    for o in b.get("obstacles") or []:
        sh = o.get("shape") or {}
        got[str(o.get("object_id"))] = tuple(_m_to_mm(sh.get(k), f"obstacle.{k}")
                                             for k in ("x", "y", "width", "length"))
    expected_obs = {}
    for k in recon["keepouts"]:
        expected_obs[str(k["object_id"])] = tuple(_m_to_mm(v, "keepout") for v in k["rect_m"])
    if got != expected_obs:
        raise RealModelSpatialAdaptationError("PERSISTED_KEEPOUT_MISMATCH",
                                              f"持久候选保留区 {got} 与场地快照 {expected_obs} 不符", stage="site")
    return {"boundary_mm": [bw, bh], "entrance_mm": [ex, ey], "keepouts": got,
            "site_snapshot_sha256": recon["site_snapshot_sha256"],
            "basemap_files_sha256": recon["basemap_files_sha256"],
            "declared_snapshot_sha256": declared,
            "status": "matched"}


def validate_candidate_geometry_against_site(model: dict, site: dict, basemap_dir: Any) -> dict:
    """P1: no circulation segment may overlap a confirmed keep-out, and every
    segment must touch the declared entrance.  Conflicts are hard failures."""
    recon = reconcile_site(basemap_dir, site)
    obstacles = [tuple(_m_to_mm(v, "keepout") for v in k["rect_m"]) for k in recon["keepouts"]]
    overlaps: list[dict] = []
    for seg in (model.get("circulation") or {}).get("segments") or []:
        sh = seg.get("shape") or {}
        if str(sh.get("type") or "rect") != "rect":
            raise RealModelSpatialAdaptationError("PERSISTED_GEOMETRY_UNSUPPORTED",
                                                  "持久候选动线段不是 rect，几何能力不足", stage="site")
        sx, sy, sw, sl = (_m_to_mm(sh.get(k), f"seg.{k}") for k in ("x", "y", "width", "length"))
        for i, (ox, oy, ow, ol) in enumerate(obstacles):
            iw = min(sx + sw, ox + ow) - max(sx, ox)
            ih = min(sy + sl, oy + ol) - max(sy, oy)
            if iw > 0 and ih > 0:
                overlaps.append({"segment_id": seg.get("segment_id"), "keepout_index": i,
                                 "overlap_mm2": iw * ih})
    if overlaps:
        raise RealModelSpatialAdaptationError("CIRCULATION_BLOCKED_BY_KEEPOUT",
                                              f"动线与确认底图保留区交叠：{overlaps[:3]}", stage="site")
    # entrance must lie on at least one segment boundary
    expected = recon["entrance"].get("point_m")
    if not expected:
        raise RealModelSpatialAdaptationError("SITE_ENTRANCE_ASSUMPTION_MISSING", "场地快照没有入口假设", stage="site")
    ex, ey = _m_to_mm(expected[0], "site.x"), _m_to_mm(expected[1], "site.y")
    connected = False
    for seg in (model.get("circulation") or {}).get("segments") or []:
        sh = seg.get("shape") or {}
        sx, sy = _m_to_mm(sh.get("x", 0), "seg.x"), _m_to_mm(sh.get("y", 0), "seg.y")
        sw, sl = _m_to_mm(sh.get("width", 0), "seg.w"), _m_to_mm(sh.get("length", 0), "seg.l")
        if sx <= ex <= sx + sw and sy <= ey <= sy + sl:
            connected = True
            break
    if not connected:
        raise RealModelSpatialAdaptationError("ENTRANCE_NOT_CONNECTED_TO_SNAPSHOT",
                                              f"入口 ({ex},{ey})mm 未落在任何动线段上", stage="site")
    return {"overlaps": [], "entrance_connected": True,
            "segments_checked": len((model.get("circulation") or {}).get("segments") or []),
            "keepouts_checked": len(obstacles)}


def verify_geometry_projection_consistency(model: dict) -> dict:
    """P1: source rect, legacy objects/segments and spatial projection must agree.

    Covers every circulation segment (horizontal / vertical / near-square),
    every zone and every furniture/partition projection: same rectangle, same
    identity, no zero-width degenerate, connections refer to existing segments.
    """
    spatial = model.get("spatial") or {}
    checks: list[dict] = []
    legacy_by_id = {str(o.get("object_id")): o for o in (model.get("objects") or [])}
    paths = {str(c.get("object_id")): c for c in (spatial.get("circulation") or [])}
    segments = {str(s.get("segment_id")): s for s in ((model.get("circulation") or {}).get("segments") or [])}
    problems: list[dict] = []

    def bbox_of_shape(shape: dict) -> list[int]:
        x = _m_to_mm(shape.get("x"), "shape.x")
        y = _m_to_mm(shape.get("y"), "shape.y")
        w = _m_to_mm(shape.get("width"), "shape.width")
        h = _m_to_mm(shape.get("length"), "shape.length")
        return [x, y, w, h]

    for sid, path in paths.items():
        segment = segments.get(sid)
        if not segment:
            problems.append({"item": sid, "problem": "legacy_segment_missing"})
            continue
        declared = [int(v) for v in path.get("declared_rect_mm") or []]
        legacy = bbox_of_shape(segment.get("shape") or {})
        source = [int(v) for v in (segment.get("properties") or {}).get("source_rect_mm") or []]
        if legacy[2] <= 0 or legacy[3] <= 0:
            problems.append({"item": sid, "problem": "legacy_zero_dimension", "rect": legacy})
        if not (declared == legacy == source):
            problems.append({"item": sid, "problem": "rect_mismatch",
                             "declared": declared, "legacy": legacy, "source": source})
        checks.append({"item": sid, "axis": path.get("axis"), "rect": legacy,
                       "area_m2": round(legacy[2] * legacy[3] / 1_000_000, 4)})
    for zid, zone in {str(z.get("object_id")): z for z in (spatial.get("zones") or [])}.items():
        legacy = legacy_by_id.get(zid)
        if not legacy:
            problems.append({"item": zid, "problem": "legacy_zone_missing"})
            continue
        poly = zone.get("polygon_mm") or []
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        expected = [int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))]
        got = bbox_of_shape(legacy.get("shape") or {})
        if got != expected:
            problems.append({"item": zid, "problem": "zone_rect_mismatch",
                             "spatial": expected, "legacy": got})
    for fur in spatial.get("furniture") or []:
        fid = str(fur.get("object_id"))
        legacy = legacy_by_id.get(fid)
        if not legacy:
            problems.append({"item": fid, "problem": "legacy_furniture_missing"})
            continue
        expected = [round(fur["x_mm"] - fur["w_mm"] / 2), round(fur["y_mm"] - fur["d_mm"] / 2),
                    int(fur["w_mm"]), int(fur["d_mm"])]
        got = bbox_of_shape(legacy.get("shape") or {})
        if got != expected:
            problems.append({"item": fid, "problem": "furniture_rect_mismatch",
                             "spatial": expected, "legacy": got})
    ids = set(paths)
    for pair in (model.get("circulation") or {}).get("connections") or []:
        if len(pair) != 2 or pair[0] not in ids or pair[1] not in ids:
            problems.append({"item": list(pair), "problem": "connection_unknown_segment"})
    if problems:
        raise RealModelSpatialAdaptationError(
            "GEOMETRY_PROJECTION_INCONSISTENT",
            f"源矩形/legacy/spatial 投影不一致：{problems[:4]}", stage="geometry")
    return {"segments": checks, "zones": len(spatial.get("zones") or []),
            "furniture": len(spatial.get("furniture") or []),
            "connections": len((model.get("circulation") or {}).get("connections") or []),
            "status": "consistent"}


def adapt_persisted_candidate(model: dict, *, site: dict, basemap_dir: Any,
                              provenance: dict, created_at: str, run_verifier=None
                              ) -> tuple[dict, dict]:
    """Persisted candidate -> adapt.  Site integrity is ALWAYS enforced.

    The 2253899 ``skip_site_integrity`` switch is gone: a caller could bypass the
    only site gate and still get an adoptable document.  Isolated negatives must
    use ``verify_persisted_site_snapshot`` directly and mark their output
    ``not_validated``; they never travel through this function.
    """
    integrity = verify_persisted_site_snapshot(model, site, basemap_dir)
    geometry = validate_candidate_geometry_against_site(model, site, basemap_dir)
    cand, note = candidate_from_persisted(model)
    adapted = adapt_candidate(cand, site=site, basemap_dir=basemap_dir,
                              provenance=provenance, created_at=created_at,
                              run_verifier=run_verifier)
    # Source / legacy / spatial projections are compared on the ADAPTED
    # document, where all three actually exist.
    consistency = verify_geometry_projection_consistency(adapted)
    integrity["geometry"] = geometry
    integrity["projections"] = consistency
    note["adapter_version"] = ADAPTER_VERSION
    note["candidate_sha256"] = sha256_hex(cand)
    note["spatial_model_hash"] = sha256_hex(adapted)
    note["site_snapshot_integrity"] = integrity
    note["site_snapshot_sha256"] = integrity["site_snapshot_sha256"]
    note["basemap_files_sha256"] = integrity["basemap_files_sha256"]
    return adapted, note


# ------------------------------------------------------- R06: full diff
def diff_spatial(previous: dict | None, current: dict) -> list[dict]:
    """Field-level reconciliation of two spatial projections, stable object ids.

    Covers geometry, roles, materials, source/site/parent, semantics and object
    add/remove.  ``object_removed`` is always reported as a loss.
    """
    if not previous:
        return []
    out: list[dict] = []

    def scalar_diff(path: str, before: Any, after: Any, reason: str) -> None:
        if before != after:
            out.append({"field": path, "before": before, "after": after,
                        "change_kind": "changed", "reason": reason})

    def group_map(sp: dict, group: str) -> dict:
        return {str(item.get("object_id") or item.get("material_id") or item.get("id") or i): item
                for i, item in enumerate(sp.get(group) or []) if isinstance(item, dict)}

    # nested dict sections are expanded to subfields so provenance/site/parent
    # changes are individually reconcilable (R06), not hidden in a blob diff.
    for group in ("source", "adaptation", "ceiling", "origin"):
        pv, cv = previous.get(group), current.get(group)
        if isinstance(pv, dict) and isinstance(cv, dict):
            for field in sorted(set(pv) | set(cv)):
                scalar_diff(f"spatial.{group}.{field}", pv.get(field), cv.get(field),
                            "来源/场地/父链/适配分组的子字段变化")
        else:
            scalar_diff(f"spatial.{group}", pv, cv, "该分组整体变化")
    for group in ("area_table", "unsupported_items", "unknown_items", "open_questions"):
        scalar_diff(f"spatial.{group}", previous.get(group), current.get(group), "该分组整体变化")
    for field in ("schema_version", "unit"):
        scalar_diff(f"spatial.{field}", previous.get(field), current.get(field), "空间段版本/单位变化")

    object_groups = ("zones", "circulation", "platforms", "furniture", "materials", "semantic_intents")
    for group in object_groups:
        before_map, after_map = group_map(previous, group), group_map(current, group)
        for oid in sorted(set(before_map) | set(after_map)):
            if oid not in after_map:
                out.append({"object_id": oid, "field": f"spatial.{group}.<object>",
                            "before": before_map[oid], "after": None, "change_kind": "object_removed",
                            "reason": "对象在上一版存在、当前版丢失，按损失报告"})
                continue
            if oid not in before_map:
                out.append({"object_id": oid, "field": f"spatial.{group}.<object>",
                            "before": None, "after": after_map[oid], "change_kind": "object_added",
                            "reason": "新增对象"})
                continue
            a, b = before_map[oid], after_map[oid]
            for field in sorted(set(a) | set(b)):
                scalar_diff(f"spatial.{group}.{oid}.{field}", a.get(field), b.get(field),
                            "同一稳定对象 ID 的字段变化")
    return out
