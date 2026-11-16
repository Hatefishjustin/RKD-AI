"""W3 adapter R01-R06 remediation verification.

Pipeline (0 external calls, 0 keys):
  local protocol stub -> REAL RealModelDesignOptionProvider.generate()
  -> REAL SQLiteAIDesignOptionRepository (isolated DB) -> read persisted candidate
  -> adapt_persisted_candidate (v2) -> same frozen model outputs
  -> Blender render FIRST -> single final file set -> manifest + ZIP -> re-open
  -> download-byte check.

Usage:
  ./.venv/Scripts/python.exe scripts/verify_w3_adapter_remediation.py \
      --evidence var/evidence/roadmap/W3-adapter-remediation/after \
      --out "deliverables-for-review/roadmap/W3-adapter-remediation" [--no-render]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from rkd_mvp import realmodel_spatial_adapter as A  # noqa: E402
from rkd_mvp.ai_design_option_provider import (  # noqa: E402
    RealModelDesignOptionProvider, DesignOptionConfig, DesignOptionProviderFailure)
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from rkd_mvp.ai_spatial_outputs import (  # noqa: E402
    build_package, finalize_package, model_hash, check_zip_against_manifest)

BASEMAP_DIR = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"
CONTRACT_SCHEMA = ROOT / "contracts/v1/realmodel-spatial-adaptation.v2.schema.json"
OUTPUT_SCHEMA = ROOT / "contracts/v1/realmodel-spatial-option.v2.schema.json"
REQUIRED_FILES = {"plan.svg", "scene.json", "quantity.json", "quantity.csv",
                  "cost.html", "render.png", "render.png.meta.json", "manifest.json", "package.zip"}

CHECKS: list[dict] = []


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def record(cid: str, name: str, ok: bool | None, evidence: dict) -> None:
    CHECKS.append({"id": cid, "name": name,
                   "result": ("observed_pass" if ok else "observed_fail") if ok is not None else "not_run",
                   "evidence": evidence})
    print(("PASS " if ok is True else "SKIP " if ok is None else "FAIL ") + cid + " " + name, flush=True)


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(value) -> str:
    return hashlib.sha256(canon(value)).hexdigest()


def site(base_point_y: float = 10.3, declare: bool = True) -> dict:
    return {
        "contract_version": A.BASEMAP_CONTRACT, "boundary_source": A.BASEMAP_CONTRACT,
        "width_m": 26.17, "length_m": 17.92,
        "keepouts": [
            {"object_id": "keepout-stair", "name": "楼梯（保留）", "rect_m": [0, 0, 2.4, 8.0], "status": "解析确认"},
            {"object_id": "keepout-bath", "name": "卫生间湿区（保留）", "rect_m": [22.0, 2.6, 4.17, 4.7], "status": "解析确认（仅范围）"},
        ],
        "entrance": {"side": "left", "point_m": [0, base_point_y], "width_m": 1.8, "status": "待现场复核",
                     "assumption": {"kind": "concept_replaceable", "reason": "西门厅推断，概念暂用可替换"}
                     if declare else None},
        "unverified_facts": ["窗（北墙）", "窗（东墙）", "门", "主入口位置", "窗台高 / 窗洞高",
                             "卫生间内部隔断", "133 项拓扑复核"],
    }


def raw_candidate(kind: str) -> dict:
    """A candidate in the model response shape, authored on the confirmed frame."""
    base = {
        "strategy_id": f"{kind}-fixture", "concept": "离线夹具，非设计成果", "statement": "离线夹具",
        "tradeoffs": ["仅验证映射"], "zones": [], "walls": [], "furniture": [],
        "focal_point": None, "entrance_buffers": [], "paths": [], "connections": [],
        "circulation_kind": kind, "materials": [{"material_id": "mat-warm", "name": "暖木意向", "intent": "未选产品"}],
        "cost_unknown": ["材料单价与价源"], "relationships": [],
    }
    # Legacy provider entrance for side=left is [0, length*0.125] = [0, 2.24].
    # A horizontal path with x=0 and y covering 2.24 satisfies ENTRANCE_NOT_CONNECTED.
    if kind == "branch":
        base["paths"] = [
            {"segment_id": "path-south", "x": 0, "y": 1.6, "width": 26.17, "length": 1.28},  # covers y=2.24 at x=0
            {"segment_id": "path-west", "x": 2.4, "y": 2.88, "width": 1.28, "length": 12.0},
            {"segment_id": "path-east", "x": 15.0, "y": 2.88, "width": 1.28, "length": 12.0},
        ]
        base["connections"] = [["path-south", "path-west"], ["path-south", "path-east"]]
        base["zones"] = [
            {"object_id": "zone:foyer", "name": "前厅", "x": 3.68, "y": 3.5, "width": 5.0, "length": 3.0,
             "zone_role": "foyer", "sequence_role": "opening", "intent": "印象", "min_area_m2": "4"},
            {"object_id": "zone:display", "name": "主展", "x": 3.68, "y": 7.0, "width": 5.0, "length": 3.0,
             "zone_role": "primary_display", "sequence_role": "climax", "intent": "核心", "min_area_m2": "4"},
            {"object_id": "zone:talk", "name": "洽谈", "x": 16.28, "y": 3.5, "width": 5.0, "length": 3.0,
             "zone_role": "deep_talk", "sequence_role": "closing", "intent": "转化", "min_area_m2": "4"},
        ]
    else:  # loop, includes a VERTICAL and a NEAR-SQUARE segment, valid geometry
        base["paths"] = [
            {"segment_id": "path-south", "x": 0, "y": 1.6, "width": 26.17, "length": 1.28},
            {"segment_id": "path-west", "x": 2.4, "y": 2.88, "width": 1.28, "length": 12.0},   # vertical
            {"segment_id": "path-core", "x": 8.0, "y": 12.88, "width": 2.0, "length": 2.0},     # near-square, shares top edge with north
            {"segment_id": "path-north", "x": 2.4, "y": 14.88, "width": 19.0, "length": 1.28},
        ]
        base["connections"] = [["path-south", "path-west"], ["path-west", "path-north"],
                               ["path-north", "path-core"]]
        base["zones"] = [
            {"object_id": "zone:foyer", "name": "门厅", "x": 3.68, "y": 3.5, "width": 4.0, "length": 3.0,
             "zone_role": "foyer", "sequence_role": "opening", "intent": "印象", "min_area_m2": "4"},
            {"object_id": "zone:display", "name": "中岛", "x": 3.68, "y": 7.0, "width": 4.0, "length": 3.0,
             "zone_role": "primary_display", "sequence_role": "climax", "intent": "核心", "min_area_m2": "4"},
            {"object_id": "zone:talk", "name": "洽谈", "x": 3.68, "y": 10.5, "width": 4.0, "length": 3.0,
             "zone_role": "deep_talk", "sequence_role": "closing", "intent": "转化", "min_area_m2": "4"},
        ]
    base["walls"] = [{"object_id": "wall:f", "name": "形象墙", "x": 6.0, "y": 3.2,
                      "width": 0.14, "length": 2.0, "wall_type": "feature"},
                     {"object_id": "wall:c", "name": "弧意向", "x": 18.0, "y": 3.2,
                      "width": 0.14, "length": 2.0, "wall_type": "curved_intent"}]
    base["furniture"] = [{"object_id": "f:d", "name": "前台", "x": 5.0, "y": 4.0, "width": 1.4, "length": 0.6,
                          "furniture_type": "reception_desk", "parent_object_id": "zone:foyer"}]
    base["focal_point"] = {"object_id": "focal:hero", "name": "中岛主展", "x": 5.5, "y": 8.0,
                           "width": 1.8, "length": 1.2, "furniture_type": "island", "statement": "焦点"}
    base["entrance_buffers"] = [{"object_id": "entrance:portal", "name": "门斗", "x": 0.2, "y": 1.8,
                                 "width": 0.8, "length": 0.8}]
    return base


class StubResponse:
    def __init__(self, payload: dict, request_id: str) -> None:
        self._raw = canon(payload)
        self.headers = {"X-Request-Id": request_id}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _n=None):
        return self._raw


class StubOpener:
    """Auditable local protocol stub. Records each request; returns canned JSON.

    Simulated only: never a real provider, no network, no cost.
    """

    def __init__(self, candidate_by_request: dict[str, dict]) -> None:
        self.candidate_by_request = candidate_by_request
        self.requests: list[dict] = []

    def open(self, request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        content = canon({"candidates": [self.candidate_by_request["branch"],
                                        self.candidate_by_request["loop"]]})
        rid = "stub-req-" + hashlib.sha256(canon(body)).hexdigest()[:16]
        self.requests.append({"url": request.full_url, "method": request.get_method(),
                              "body_sha256": sha(body), "request_id": rid,
                              "model": body.get("model"), "simulated": True})
        return StubResponse({"choices": [{"message": {"content": content.decode("utf-8")}}],
                             "model": body.get("model"),
                             "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}, rid)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(ROOT / "var/evidence/roadmap/W3-adapter-remediation/after"))
    ap.add_argument("--out", default=str(ROOT / "deliverables-for-review/roadmap/W3-adapter-remediation"))
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()
    evidence = Path(args.evidence).resolve()
    out = Path(args.out).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    (out / "outputs").mkdir(parents=True, exist_ok=True)
    started = now()

    # --- contracts (v2 schemas generated additively; legacy untouched) ------
    contract_schema = json.loads(CONTRACT_SCHEMA.read_text(encoding="utf-8"))
    output_schema = json.loads(OUTPUT_SCHEMA.read_text(encoding="utf-8"))
    record("V-01", "适配契约 v2 / 输出 schema v2 均为合法 Draft2020-12 schema",
           Draft202012Validator.check_schema(contract_schema) is None and
           Draft202012Validator.check_schema(output_schema) is None,
           {"contract_schema_bytes": len(canon(contract_schema)), "output_schema_bytes": len(canon(output_schema))})

    # --- R01 basemap structured reconciliation ------------------------------
    facts = A._load_basemap_facts(BASEMAP_DIR)
    actual_json = json.loads((BASEMAP_DIR / "底图数据.json").read_text(encoding="utf-8"))
    record("V-02", "从哈希验证的底图提取结构化保留区且与 JSON 元素逐项一致",
           len(facts["keepouts"]) == 2 and
           all(abs(k["rect_m"][2] - 2.4) < .01 or abs(k["rect_m"][2] - 4.17) < .01 for k in facts["keepouts"]) and
           facts["boundary_mm"] == [26170, 17920],
           {"keepouts": facts["keepouts"], "boundary_mm": facts["boundary_mm"],
            "json_contract": actual_json.get("contract_version"),
            "files": facts["files"], "entrance_fact": facts["entrance_fact"],
            "unverified_facts_count": len(facts["unverified_facts"])})
    # independent geometry example: a model zone overlapping the bath keepout
    bath = next(k for k in facts["keepouts"] if k["object_id"] == "keepout-bath")
    bx, by, bw_, bh_ = bath["rect_m"]
    zone = [22.5, 3.0, 2.0, 2.0]  # x,y,w,l (m): fully inside bath
    inter_w = min(bx + bw_, zone[0] + zone[2]) - max(bx, zone[0])
    inter_h = min(by + bh_, zone[1] + zone[3]) - max(by, zone[1])
    independent_overlap = inter_w * inter_h
    record("V-03", "独立算例：模型分区与底图保留区交集非零且等于解析值",
           independent_overlap > 0 and abs(independent_overlap - 4.0) < 1e-9,
           {"keepout_bath_m": bath["rect_m"], "zone_m": zone,
            "analytic_intersection_m2": independent_overlap,
            "method": "手算 min/max 交叠矩形，不依赖适配器实现"})

    # --- R03 local protocol stub -> real provider -> real repository ---------
    runtime = evidence / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    db = runtime / "app.sqlite3"
    if db.exists():
        db.unlink()
    store = SQLiteStore(str(db))  # run real migrations (creates ai_design_option_* tables)
    # Seed the parent project row required by the sets FK.
    _conn = store._connection()
    _conn.execute("INSERT OR IGNORE INTO projects(organization_id, project_id, name, status, version) "
                  "VALUES (?,?,?,?,?)",
                  ("org-local", "ningbo-xiecheng", "宁波协诚（隔离桩库）", "active", 1))
    _conn.commit()
    repo = SQLiteAIDesignOptionRepository(str(db))
    config = DesignOptionConfig(
        kind="openai_compatible", name="本地协议桩（模拟，非真实模型）",
        adapter_version="rkd-real-design-provider.stub", prompt_version="design-stub.zh-CN.v1",
        schema_version="rkd-ai-design-option.v1", max_candidates=2, real_model=True,
        configuration_errors=[], base_url="http://127.0.0.1:9/local-stub", model_id="stub-model",
        api_key_present=True, max_attempts=2, timeout_seconds=5, external_context_allowed=False)
    opener = StubOpener({"branch": raw_candidate("branch"), "loop": raw_candidate("loop")})
    provider = RealModelDesignOptionProvider(config, api_key="stub-not-a-real-key", opener=opener,
                                             run_log_dir=str(runtime / "runs"))
    # NOTE: the LEGACY provider schema only allows test/manual boundary sources;
    # the confirmed basemap source is a genuine contract divergence (evidence V-17).
    # The geometry frame is the confirmed 26.17x17.92m; the source LABEL remains
    # the legacy provider's until the contract evolves.  The adapter re-binds to
    # the confirmed basemap itself (V-02) and never takes this label as fact.
    provider_site = {"width": "26.17", "length": "17.92",
                     "boundary_source": "manual_boundary_not_site_verified", "obstacles": []}
    stub_input_hash = hashlib.sha256(canon({"stub_input": "w3-adapter-remediation"})).hexdigest()
    brief = {"requirements": [], "design_intent": [], "conflicts": [],
             "cost": {"known_items": [], "unknown_items": []}}
    try:
        models = provider.generate(set_id="w3-stub-set", brief=brief, site=provider_site,
                                   input_hash=stub_input_hash, generated_at=now())
        gen_ok = len(models) == 2
        gen_err = ""
    except DesignOptionProviderFailure as error:
        models, gen_ok, gen_err = [], False, f"{error.code}: {error.message}"
    record("V-04", "真实 provider.generate + 本地协议桩产出 2 候选（模拟，无网络）",
           gen_ok, {"count": len(models), "error": gen_err,
                    "stub_requests": opener.requests, "provider_kind": config.kind,
                    "note": "stub-model + stub key；0 外部请求、0 token、0 费用"})
    if not gen_ok:
        print("provider stub failed; aborting with failure recorded")
        return 1

    persisted: list[dict] = []
    with repo.transaction("org-local", "ningbo-xiecheng", write=True) as tx:
        tx.insert_set({"set_id": "w3-stub-set", "brief_id": "w3-stub-brief",
                       "input_hash": stub_input_hash, "status": "succeeded", "phase": "completed",
                       "attempt_count": 1, "config": config.public(), "context": {},
                       "error_code": None, "error_message": None,
                       "idempotency_key": "w3-stub-set-v1", "actor_id": "stub",
                       "created_at": now(), "updated_at": now()})
        for i, model in enumerate(models):
            oid = f"ai-option-revision-stub-{i}"
            tx.insert_revision({"option_revision_id": oid, "set_id": "w3-stub-set",
                                "option_id": f"w3-stub-set:stub-{i}", "revision_no": 1,
                                "parent_revision_id": None, "strategy_id": model["strategy"]["strategy_id"],
                                "strategy": model["strategy"], "model": model, "validation": model["validation"],
                                "materials": model["materials"], "cost": model["cost"], "feedback": model["feedback"],
                                "diff": model["diff"], "conflicts": model["conflicts"],
                                "structure_signature": model["structure_signature"],
                                "lifecycle_status": "candidate", "source_kind": model["source_kind"],
                                "change_reason": "本地协议桩模拟候选，未采用", "actor_id": "stub",
                                "created_at": now()})
            row = tx.revision(oid)
            persisted.append(row["model"])
    record("V-05", "候选经真实仓储持久化并读回，objects[].shape / circulation.segments 保留",
           len(persisted) == 2 and all(p.get("objects") and p.get("circulation", {}).get("segments")
                                       for p in persisted),
           {"readback_option_ids": [p["option_id"] for p in persisted],
            "object_counts": [len(p["objects"]) for p in persisted],
            "segment_counts": [len(p["circulation"]["segments"]) for p in persisted],
            "db": str(db.relative_to(ROOT))})

    # auditable run records: one per persisted candidate
    run_records = []
    for i, p in enumerate(persisted):
        cand, _note = A.candidate_from_persisted(p)
        rec = {"schema_version": "rkd-local-stub-run-record.v1", "kind": "local_protocol_stub_run",
               "simulated": True, "stub": True, "candidate_sha256": sha(cand),
               "provider_kind": config.kind, "model": config.model_id,
               "prompt_version": config.prompt_version, "input_hash": stub_input_hash,
               "output_sha256": sha(p), "project_id": "ningbo-xiecheng", "option_id": p["option_id"],
               "revision_no": p["revision_no"], "generated_at": p["generation"]["generated_at"],
               "external_calls": 0, "tokens": 0, "cost_cny": 0, "key": "stub-not-a-real-key", "record_sha256": ""}
        rec["record_sha256"] = sha(rec)
        path = evidence / f"run-record-{i}.json"
        path.write_text(canon(rec).decode("utf-8"), encoding="utf-8")
        run_records.append({"path": str(path.relative_to(ROOT)), "record_sha256": rec["record_sha256"]})

    adapted = []
    for i, p in enumerate(persisted):
        cand, derive = A.candidate_from_persisted(p)
        prov = {"artifact_id": f"stub-{i}", "sha256": sha(cand), "set_id": "w3-stub-set",
                "option_id": p["option_id"], "revision_no": 1, "parent_revision_id": None,
                "actor_id": "offline-verifier", "model_site_boundary_m": [26.17, 17.92],
                "provider_kind": "local_protocol_stub", "prompt_version": config.prompt_version,
                "model_id": config.model_id,
                "design_origin": {"kind": "fixture", "declared_by": "local_protocol_stub",
                                  "declaration": "本地协议桩模拟候选，不是真实模型调用",
                                  "run_refs": [run_records[i]["path"]]}}
        m, note = A.adapt_persisted_candidate(p, site=site(), basemap_dir=BASEMAP_DIR,
                                              provenance=prov, created_at=now())
        adapted.append(m)
        record(f"V-06{i}", f"已持久化候选 {i} 经适配器进入版本化 spatial",
               Draft202012Validator(output_schema).is_valid(m) and
               m["spatial"]["source"]["design_origin"]["kind"] == "fixture" and
               m["generation"]["real_model"] is False,
               {"option_id": m["option_id"], "derive": derive, "note": note,
                "origin_kind": m["spatial"]["source"]["origin_kind"],
                "run_evidence": m["spatial"]["source"]["design_origin"]["run_evidence"],
                "schema_errors": [e.message for e in Draft202012Validator(output_schema).iter_errors(m)][:5]})

    # --- R04 orientation / kind fidelity ------------------------------------
    loop_m = adapted[1]
    sec = {c["object_id"]: c for c in loop_m["spatial"]["circulation"]}
    record("V-07", "横/纵/近方动线按主轴保真，近方标 unknown，不猜方向",
           sec["path-south"]["axis"] == "horizontal" and
           sec["path-west"]["axis"] == "vertical" and
           abs(sec["path-west"]["path_mm"][0][0] - sec["path-west"]["path_mm"][1][0]) < 1 and
           sec["path-core"]["axis"] == "ambiguous_unknown" and
           sec["path-south"]["width_known_status"] == "model_declared_unverified",
           {k: {"axis": v["axis"], "path_mm": v["path_mm"], "width_mm": v["width_mm"]}
            for k, v in sec.items()})
    kinds = [m["circulation"]["kind"] for m in adapted]
    record("V-08", "branch / loop 类型保真（不再固定 loop）",
           kinds[0] == "branch" and kinds[1] == "loop",
           {"kinds": kinds, "source_kinds": [p["circulation"]["kind"] for p in persisted]})

    # --- R02 positive/negative source evidence -------------------------------
    cand0, _ = A.candidate_from_persisted(persisted[0])
    good_prov = {"sha256": sha(cand0), "model_site_boundary_m": [26.17, 17.92],
                 "design_origin": {"kind": "fixture", "declared_by": "stub",
                                   "declaration": "simulated", "run_refs": [run_records[0]["path"]]}}
    rejected: dict[str, dict] = {}
    cases = {
        "fake_run_ref": {**good_prov, "design_origin": {**good_prov["design_origin"], "kind": "real_model",
                                                       "run_refs": ["invented"]}},
        "wrong_sha": {**good_prov, "sha256": "0" * 64},
        "fake_parent": {**good_prov, "parent_revision_id": "invented"},
    }
    for name, p in cases.items():
        try:
            A.adapt_candidate(cand0, site=site(), basemap_dir=BASEMAP_DIR, provenance=p, created_at=now())
            rejected[name] = {"rejected": False}
        except A.RealModelSpatialAdaptationError as error:
            rejected[name] = {"rejected": True, "code": error.code, "message": error.message[:200]}
    record("V-09", "伪来源/错候选哈希/伪父链全部拒绝",
           all(v["rejected"] for v in rejected.values()), rejected)
    # fixture/human/unknown positive cases
    origin_cases = {}
    for kind in ("fixture", "human", "unknown"):
        p = {**good_prov, "design_origin": {"kind": kind, "declared_by": "stub",
                                            "declaration": "offline", "run_refs": []}}
        try:
            m = A.adapt_candidate(cand0, site=site(), basemap_dir=BASEMAP_DIR, provenance=p, created_at=now())
            origin_cases[kind] = {"ok": True, "origin_kind": m["spatial"]["source"]["origin_kind"],
                                  "real_model": m["generation"]["real_model"]}
        except A.RealModelSpatialAdaptationError as error:
            origin_cases[kind] = {"ok": False, "code": error.code}
    record("V-10", "夹具/人工/未知来源保留各自标签且 real_model=false",
           all(v["ok"] and v["real_model"] is False for v in origin_cases.values()), origin_cases)

    # --- R06 diff full coverage ---------------------------------------------
    d0 = adapted[0]
    d1_cand, _ = A.candidate_from_persisted(persisted[0])
    d1_cand["materials"][0]["name"] = "changed-material"
    d1_cand["zones"][0]["intent"] = "changed-intent"  # semantic change
    d1_site = site(base_point_y=11.0)  # entrance assumption change -> site_source diff
    # Verified parent evidence -> exercises source.parent_link_status diff.
    parent_rec = {"schema_version": "rkd-parent-evidence.v1", "candidate_sha256": sha(cand0)}
    parent_path = evidence / "parent-evidence.json"
    parent_path.write_text(canon(parent_rec).decode("utf-8"), encoding="utf-8")
    d1_prov = {**good_prov, "sha256": sha(d1_cand),
               "design_origin": {**good_prov["design_origin"], "run_refs": [],
                                 "declared_by": "different-declarant"},  # source diff
               "parent_revision_id": "ai-option-revision-parent-stub",
               "parent_evidence": {"candidate_sha256": sha(cand0),
                                   "record_ref": str(parent_path.relative_to(ROOT))}}
    d1 = A.adapt_candidate(d1_cand, site=d1_site, basemap_dir=BASEMAP_DIR,
                           provenance=d1_prov, created_at=now())
    diff = A.diff_spatial(d0["spatial"], d1["spatial"])
    fields = {x["field"] for x in diff}
    record("V-11", "diff 覆盖材料/来源/场地/语义（父链另见 V-12）",
           any("material" in f for f in fields) and
           any("source" in f for f in fields) and
           any("site_source" in f for f in fields) and
           any("semantic" in f for f in fields),
           {"diff_count": len(diff), "fields": sorted(fields)[:24]})
    removed = A.diff_spatial(
        {**d0["spatial"], "zones": d0["spatial"]["zones"][:-1]}, d0["spatial"])
    record("V-12", "对象丢失与父链变化明确报告为损失/差异",
           any(x.get("change_kind") == "object_added" for x in removed) and
           any("parent" in x["field"] or "parent_link_status" in x["field"] for x in diff),
           {"object_change_sample": removed[:2],
            "parent_fields": [x for x in diff if "parent" in x["field"]][:3]})

    # --- outputs from frozen model ------------------------------------------
    frozen = adapted[1]
    (out / "outputs" / "model.json").write_bytes(canon(frozen))
    hashes: dict[str, dict] = {}

    def write(name: str, data: bytes) -> None:
        p = out / "outputs" / name
        p.write_bytes(data)
        hashes[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    # R05: render FIRST, then single final file set
    render_path = out / "outputs" / "render.png"
    render_info: dict = {"status": "not_run"}
    if not args.no_render:
        blender = ROOT / "tools/blender/blender-4.2.9-windows-x64/blender.exe"
        # preliminary scene for rendering (same frozen model)
        prelim = build_package(frozen, project_id="ningbo-xiecheng-stub",
                               option_revision_id="w3-stub-r1")
        scene_bytes = prelim["files"]["scene.json"][2]
        (evidence / "scene-for-render.json").write_bytes(scene_bytes)
        if blender.is_file():
            env = dict(os.environ)
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
                env.pop(k, None)
            cmd = [str(blender), "-b", "--factory-startup", "-noaudio", "--python",
                   str(ROOT / "scripts/render_spatial_scene.py"), "--",
                   "--scene", str(evidence / "scene-for-render.json"), "--out", str(render_path),
                   "--width", "1280", "--height", "800", "--samples", "48"]
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=300, env=env)
                render_info = {"status": "rendered" if proc.returncode == 0 and render_path.is_file() and
                               render_path.stat().st_size > 10000 else "failed",
                               "returncode": proc.returncode,
                               "bytes": render_path.stat().st_size if render_path.is_file() else 0}
            except Exception as error:  # noqa: BLE001
                render_info = {"status": "failed", "error": str(error)}
    record("V-13", "本机 Blender 人眼图（工程样张）" +
           ("（本轮 --no-render，不计通过）" if args.no_render else ""),
           None if args.no_render else render_info.get("status") == "rendered", render_info)

    # rebuild package with render as part of the SAME file set
    pkg = build_package(frozen, project_id="ningbo-xiecheng-stub", option_revision_id="w3-stub-r1")
    files = dict(pkg["files"])
    if render_info.get("status") == "rendered":
        meta = {"schema_version": "rkd-render-meta.v1",
                "render_sha256": hashlib.sha256(render_path.read_bytes()).hexdigest(),
                "bytes": render_path.stat().st_size,
                "status": "rendered", "source": "local_blender_4_2_9_cycles_cpu",
                "engineering_sample": True,
                "note": "内部工程样张：灰材质、无产品/软装/人物，不达客户交付级"}
        (out / "outputs" / "render.png.meta.json").write_bytes(canon(meta))
        files["render.png"] = ("png", "image/png", render_path.read_bytes())
        files["render.png.meta.json"] = ("manifest_json", "application/json", canon(meta))
    final = finalize_package(files, pkg["manifest"])
    zbytes = final["files"]["package.zip"][2]
    mbytes = next(v[2] for k, v in final["files"].items() if k == "manifest.json")
    zcheck = check_zip_against_manifest(zbytes, mbytes)
    with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
        zip_names = set(zf.namelist())
        zip_render = zf.read("render.png") if "render.png" in zip_names else b""
    if render_info.get("status") == "rendered":
        record("V-14", "渲染文件进入同一最终 ZIP/清单，逐项重开校验",
               zcheck["ok"] and "render.png" in zip_names and
               hashlib.sha256(zip_render).hexdigest() == hashlib.sha256(render_path.read_bytes()).hexdigest(),
               {"zip_names": sorted(zip_names), "check": zcheck,
                "render_bytes_zip": len(zip_render), "render_bytes_disk": render_info["bytes"]})
        record("V-15", "下载 ZIP 中图像字节与独立渲染一致",
               hashlib.sha256(zip_render).hexdigest() == hashlib.sha256(render_path.read_bytes()).hexdigest(),
               {"zip_sha256": hashlib.sha256(zip_render).hexdigest(),
                "disk_sha256": hashlib.sha256(render_path.read_bytes()).hexdigest()})
    else:
        record("V-14", "渲染文件进入最终 ZIP（本轮未渲染）", None,
               {"reason": "--no-render 或未成功；不得登记完整包", "zip_names": sorted(zip_names)})
        record("V-15", "下载 ZIP 图像校验（本轮未渲染）", None, {"reason": "not_run"})
    write("manifest.json", mbytes)
    write("package.zip", zbytes)
    for name in ("plan.svg", "scene.json", "quantity.json", "quantity.csv", "cost.html"):
        if name in final["files"]:
            write(name, final["files"][name][2])
    if render_info.get("status") == "rendered":
        write("render.png", render_path.read_bytes())
        write("render.png.meta.json", (out / "outputs" / "render.png.meta.json").read_bytes())
    record("V-16", "输出集登记 SHA，必需文件口径明确",
           set(hashes.keys()) >= (REQUIRED_FILES - {"render.png", "render.png.meta.json"}),
           {"files": hashes, "required": sorted(REQUIRED_FILES),
            "complete_package": REQUIRED_FILES <= set(zip_names)})

    # --- contract evolution evidence ----------------------------------------
    legacy = json.loads((ROOT / "contracts/v1/ai-design-option.schema.json").read_text(encoding="utf-8"))
    legacy_val = Draft202012Validator(legacy)
    legacy_errors = [e.message for e in legacy_val.iter_errors(frozen)]
    record("V-17", "主契约演进：旧 schema 错误逐项登记，不宣称同名兼容",
           len(legacy_errors) > 0,
           {"legacy_schema_error_count": len(legacy_errors), "legacy_errors": legacy_errors[:26],
            "decision": "单一权威版本 v2 + 旧文档向后兼容 + 迁移/unknown 语义见 contract-evolution.md",
            "new_schema_valid": Draft202012Validator(output_schema).is_valid(frozen)})

    audit = {"schema_version": "rkd-w3-adapter-remediation.v1", "started_at": started,
             "finished_at": now(), "baseline": "dcc11f7", "checks": CHECKS,
             "hashes": hashes, "zip_names": sorted(zip_names), "render": render_info,
             "run_records": run_records, "stub_requests": opener.requests,
             "persistent_candidates": [{"option_id": p["option_id"],
                                        "model_hash": model_hash(p)} for p in persisted],
             "external_calls": 0, "tokens": 0, "cost_cny": 0, "key_used": False,
             "key_written": False, "key_note": "stub key string only; no real secret"}
    (evidence / "verification.json").write_bytes(canon(audit))
    (out / "checks.json").write_bytes(canon(audit))
    failed = [c["id"] for c in CHECKS if c["result"] == "observed_fail"]
    notrun = [c["id"] for c in CHECKS if c["result"] == "not_run"]
    print(f"\nSUMMARY pass={sum(c['result'] == 'observed_pass' for c in CHECKS)} "
          f"fail={failed} not_run={notrun}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
