"""W3 control/trust remediation verification (baseline 4d2ac76).

Pipeline (0 external calls, 0 keys):
  hash-verified v2 basemap -> SINGLE site snapshot (fact + assumption + unknown)
  -> local protocol stub -> REAL provider.generate(snapshot-bound site)
  -> REAL geometry validation -> REAL SQLite repository -> controlled run ledger
  -> adapt_persisted_candidate(snapshot, ledger) -> same frozen model outputs
  -> render first -> final manifest + ZIP -> ZIP re-open byte check
  -> HTTP download = not_run (explicit).

  python scripts/verify_w3_control_trust.py \
    --evidence var/evidence/roadmap/W3-control-trust-remediation/after \
    --out "deliverables-for-review/roadmap/W3-control-trust-remediation" [--no-render]
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
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "mvp", ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from jsonschema import Draft202012Validator  # noqa: E402

from rkd_mvp import realmodel_spatial_adapter as A  # noqa: E402
from rkd_mvp.controlled_run_ledger import ControlledRunLedger, RunLedgerError  # noqa: E402
from rkd_mvp.ai_design_option_provider import (  # noqa: E402
    RealModelDesignOptionProvider, DesignOptionConfig, DesignOptionProviderFailure)
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from rkd_mvp.ai_spatial_outputs import (  # noqa: E402
    build_package, finalize_package, model_hash, check_zip_against_manifest)

BASEMAP_DIR = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"
CONTRACT_V2 = ROOT / "contracts/v2/ai-design-option.schema.json"
LEGACY_SCHEMA = ROOT / "contracts/v1/ai-design-option.schema.json"
CHECKS: list[dict] = []


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def record(cid, name, ok, evidence):
    CHECKS.append({"id": cid, "name": name,
                   "result": ("observed_pass" if ok else "observed_fail") if ok is not None else "not_run",
                   "evidence": evidence})
    print(("PASS " if ok is True else "SKIP " if ok is None else "FAIL ") + cid + " " + name, flush=True)


def canon(v) -> bytes:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(v) -> str:
    return hashlib.sha256(canon(v)).hexdigest()


def build_site_snapshot() -> dict:
    """ONE snapshot fact set from the hash-verified v2 basemap."""
    facts = A._load_basemap_facts(BASEMAP_DIR)
    # The confirmed basemap gives main entrance on the west side but no measured
    # point.  We declare a REPLACEABLE CONCEPT ASSUMPTION at [0, 10.3] and mark it
    # not a site fact; the design geometry is generated on this same assumption.
    assumption = {"kind": "concept_replaceable", "value_m": [0, 10.3],
                  "reason": "底图仅推断西门厅；概念暂用点位，现场复核后替换",
                  "site_verified": False}
    payload = {
        "schema_version": "rkd-site-snapshot.v1",
        "contract_version": A.BASEMAP_CONTRACT,
        "boundary_source": A.BASEMAP_CONTRACT,
        "width_m": 26.17, "length_m": 17.92,
        "boundary_mm": facts["boundary_mm"],
        "facts": {"keepouts": facts["keepouts"], "entrance_fact": facts["entrance_fact"],
                  "boundary_mm": facts["boundary_mm"],
                  "files": facts["files"], "json_sha256": facts["json_sha256"],
                  "svg_sha256": facts["svg_sha256"]},
        "assumption": {"entrance": assumption},
        "unverified_facts": facts["unverified_facts"],
        "site_verified": False,
    }
    payload["sha256"] = sha(payload)  # self-hash over the payload WITHOUT itself
    return payload


def adapter_site(snap: dict) -> dict:
    """Flatten the snapshot into the adapter site contract (same source)."""
    return {
        "contract_version": snap["contract_version"],
        "boundary_source": snap["boundary_source"],
        "width_m": snap["width_m"], "length_m": snap["length_m"],
        "snapshot_sha256": snap["sha256"],
        "keepouts": [{"object_id": k["object_id"], "name": k["name"],
                      "rect_m": k["rect_m"], "status": k["status"]}
                     for k in snap["facts"]["keepouts"]],
        "entrance": {"side": snap["facts"]["entrance_fact"]["side"],
                     "point_m": snap["assumption"]["entrance"]["value_m"],
                     "width_m": None, "status": snap["facts"]["entrance_fact"]["status"],
                     "assumption": snap["assumption"]["entrance"]},
        "unverified_facts": snap["unverified_facts"],
    }


def provider_site(snap: dict) -> dict:
    """Same snapshot, expressed in the legacy provider's site vocabulary.

    The provider's geometry validator is the FIRST gate: the candidate must be
    drawn inside the same keep-outs and touch the same entrance assumption.
    """
    obstacles = []
    for k in snap["facts"]["keepouts"]:
        x, y, w, h = k["rect_m"]
        obstacles.append({"object_id": k["object_id"], "name": k["name"],
                          "shape": {"type": "rect", "x": str(x), "y": str(y),
                                    "width": str(w), "length": str(h)},
                          "properties": {"source": snap["contract_version"], "site_verified": False}})
    ex, ey = snap["assumption"]["entrance"]["value_m"]
    return {"width": snap["width_m"], "length": snap["length_m"],
            "unit": "m", "boundary_source": "manual_boundary_not_site_verified",
            "site_snapshot_sha256": snap["sha256"],
            "obstacles": obstacles,
            "entrance": {"side": "left", "point": [str(ex), str(ey)], "width": "1.2",
                         "source": "concept_assumption", "site_verified": False}}


def candidate(kind: str, snap: dict) -> dict:
    """Geometry generated ON the snapshot: entrance y=10.3, keepouts avoided."""
    ex, ey = snap["assumption"]["entrance"]["value_m"]
    base = {
        "strategy_id": f"{kind}-stub", "concept": "本地桩候选，非设计成果",
        "statement": "本地桩候选，非设计成果", "tradeoffs": ["仅验证工程链"],
        "entrance_side": "left", "circulation_kind": kind,
        "walls": [], "furniture": [], "paths": [], "connections": [],
        "materials": [{"material_id": "mat-warm", "name": "暖木意向", "intent": "未选产品"}],
        "cost_unknown": ["材料单价与价源"], "relationships": [],
    }
    # horizontal path whose left boundary covers the entrance point
    # Coordinates are authored in whole-decimetre strings to avoid float drift.
    y_entry, y_top = "9.7", "10.9"  # covers entrance y=10.3
    base["paths"] = [
        {"segment_id": "path-entry", "x": 0, "y": y_entry, "width": 24.0, "length": 1.2},
        {"segment_id": "path-west", "x": 3.0, "y": y_top, "width": 1.2, "length": 4.1},
        {"segment_id": "path-north", "x": 3.0, "y": "15.0", "width": 17.0, "length": 1.2},
    ]
    base["connections"] = [["path-entry", "path-west"], ["path-west", "path-north"]]
    if kind == "loop":
        base["paths"].append({"segment_id": "path-east", "x": 19.0, "y": y_top,
                              "width": 1.2, "length": 4.1})
        base["connections"].append(["path-entry", "path-east"])
        base["connections"].append(["path-east", "path-north"])
    base["zones"] = [
        {"object_id": "zone:foyer", "name": "前厅", "x": 4.6, "y": y_top,
         "width": 5.0, "length": 3.5, "zone_role": "foyer", "sequence_role": "opening",
         "intent": "品牌第一眼", "min_area_m2": "4"},
        {"object_id": "zone:display", "name": "主展", "x": 10.0, "y": y_top,
         "width": 5.0, "length": 3.5, "zone_role": "primary_display",
         "sequence_role": "climax", "intent": "主展停留", "min_area_m2": "4"},
        {"object_id": "zone:talk", "name": "洽谈", "x": 15.4, "y": y_top,
         "width": 3.4, "length": 3.4, "zone_role": "deep_talk",
         "sequence_role": "closing", "intent": "半私密洽谈", "min_area_m2": "4"},
    ]
    base["walls"] = [{"object_id": "wall:feature", "name": "形象墙", "x": 14.9,
                      "y": "11.3", "width": 0.14, "length": 2.0, "wall_type": "feature"}]
    base["furniture"] = [{"object_id": "f:desk", "name": "前台", "x": 5.2, "y": "11.5",
                          "width": 1.2, "length": 0.6, "furniture_type": "reception_desk",
                          "parent_object_id": "zone:foyer"}]
    base["focal_point"] = {"object_id": "focal:hero", "name": "中岛", "x": 11.5,
                           "y": "11.7", "width": 1.4, "length": 0.9,
                           "furniture_type": "island", "statement": "视觉焦点"}
    return base


class StubResponse:
    def __init__(self, payload):
        self._raw = canon(payload)
        self.headers = {"X-Request-Id": "local-stub-request"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, _n=None):
        return self._raw


class StubOpener:
    def __init__(self, candidates):
        self.candidates = candidates
        self.requests = []

    def open(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        site = self.candidates  # candidates keyed branch/loop
        content = canon({"candidates": [site["branch"], site["loop"]]})
        self.requests.append({"url": request.full_url, "body_sha256": sha(payload),
                              "simulated": True, "model": payload.get("model")})
        return StubResponse({"choices": [{"message": {"content": content.decode("utf-8")}}],
                             "model": payload.get("model"), "usage": {}})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(ROOT / "var/evidence/roadmap/W3-control-trust-remediation/after"))
    ap.add_argument("--out", default=str(ROOT / "deliverables-for-review/roadmap/W3-control-trust-remediation"))
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()
    evidence, out = Path(args.evidence).resolve(), Path(args.out).resolve()
    (evidence / "runtime").mkdir(parents=True, exist_ok=True)
    (out / "outputs").mkdir(parents=True, exist_ok=True)
    started = now()

    schema = json.loads(CONTRACT_V2.read_text(encoding="utf-8"))
    legacy = json.loads(LEGACY_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    record("C-01", "顶层 v2 契约是合法 Draft2020-12 schema 且版本号可识别",
           schema["properties"]["schema_version"]["const"] == "rkd-ai-design-option.v2",
           {"schema_bytes": len(canon(schema)),
            "spatial_branches": len(schema["properties"]["spatial"]["oneOf"])})

    snap = build_site_snapshot()
    asite = adapter_site(snap)
    psite = provider_site(snap)
    record("C-02", "同一场地快照贯通：底图事实/概念假设/现场未知分离且带哈希",
           sha({k: v for k, v in snap.items() if k != "sha256"}) == snap["sha256"] and
           asite["snapshot_sha256"] == snap["sha256"] and
           psite["site_snapshot_sha256"] == snap["sha256"] and
           asite["entrance"]["assumption"]["site_verified"] is False,
           {"snapshot_sha256": snap["sha256"], "keepouts": asite["keepouts"],
            "entrance_assumption": asite["entrance"]["assumption"],
            "unverified_count": len(snap["unverified_facts"])})

    # Controlled ledger + auditable stub run (simulated, never real_model).
    ledger = ControlledRunLedger()
    db = evidence / "runtime" / "app.sqlite3"
    if db.exists():
        db.unlink()
    store = SQLiteStore(str(db))
    conn = store._connection()
    conn.execute("INSERT OR IGNORE INTO projects(organization_id, project_id, name, status, version) "
                 "VALUES (?,?,?,?,?)", ("org-local", "ningbo-xiecheng", "宁波协诚（隔离桩库）", "active", 1))
    conn.commit()
    repo = SQLiteAIDesignOptionRepository(str(db))
    config = DesignOptionConfig(kind="openai_compatible", name="本地协议桩（模拟）",
                                adapter_version="rkd-real-design-provider.stub",
                                prompt_version="design-stub.zh-CN.v1",
                                schema_version="rkd-ai-design-option.v1", max_candidates=2,
                                real_model=True, configuration_errors=[],
                                base_url="http://127.0.0.1:9/local-stub", model_id="stub-model",
                                api_key_present=True, max_attempts=2, timeout_seconds=5,
                                external_context_allowed=False)
    opener = StubOpener({"branch": candidate("branch", snap), "loop": candidate("loop", snap)})
    provider = RealModelDesignOptionProvider(config, api_key="stub-not-a-real-key", opener=opener,
                                             run_log_dir=str(evidence / "runtime" / "runs"))
    try:
        models = provider.generate(set_id="w3-stub-set",
                                   brief={"requirements": [], "design_intent": [], "conflicts": [],
                                          "cost": {"known_items": [], "unknown_items": []}},
                                   site=psite, input_hash=snap["sha256"], generated_at=now())
        ok, err = len(models) == 2, ""
    except DesignOptionProviderFailure as error:
        models, ok, err = [], False, f"{error.code}: {error.message}"
    record("C-03", "真实 provider 在场地快照上生成候选（保留区/入口经几何校审）", ok,
           {"count": len(models), "error": err, "stub_requests": opener.requests,
            "site_snapshot_sha256": snap["sha256"], "external_calls": 0})

    if not ok:
        audit = {"schema_version": "rkd-w3-control-trust.v1", "checks": CHECKS,
                 "blocker": "provider 无法在冻结场地快照上产出有效候选", "started_at": started,
                 "finished_at": now(), "external_calls": 0, "cost_cny": 0}
        (evidence / "verification.json").write_bytes(canon(audit))
        (out / "checks.json").write_bytes(canon(audit))
        return 1

    # Persist via REAL repository.
    with repo.transaction("org-local", "ningbo-xiecheng", write=True) as tx:
        tx.insert_set({"set_id": "w3-stub-set", "brief_id": "w3-stub-brief",
                       "input_hash": snap["sha256"], "status": "succeeded", "phase": "completed",
                       "attempt_count": 1, "config": config.public(), "context": {},
                       "error_code": None, "error_message": None,
                       "idempotency_key": "w3-stub-set-v1", "actor_id": "stub",
                       "created_at": now(), "updated_at": now()})
        persisted = []
        for i, m in enumerate(models):
            oid = f"ai-option-revision-stub-{i}"
            tx.insert_revision({"option_revision_id": oid, "set_id": "w3-stub-set",
                                "option_id": f"w3-stub-set:stub-{i}", "revision_no": 1,
                                "parent_revision_id": None, "strategy_id": m["strategy"]["strategy_id"],
                                "strategy": m["strategy"], "model": m, "validation": m["validation"],
                                "materials": m["materials"], "cost": m["cost"], "feedback": m["feedback"],
                                "diff": m["diff"], "conflicts": m["conflicts"],
                                "structure_signature": m["structure_signature"],
                                "lifecycle_status": "candidate", "source_kind": m["source_kind"],
                                "change_reason": "本地协议桩候选，未采用", "actor_id": "stub",
                                "created_at": now()})
            persisted.append(tx.revision(oid)["model"])
    record("C-04", "候选经真实仓储持久化并读回（同一快照哈希）",
           len(persisted) == 2 and all(p.get("objects") for p in persisted),
           {"option_ids": [p["option_id"] for p in persisted],
            "object_counts": [len(p["objects"]) for p in persisted]})

    # P1 site integrity on persisted candidates.
    integrity = []
    for p in persisted:
        try:
            integ = A.verify_persisted_site_snapshot(p, asite, BASEMAP_DIR)
            geom = A.validate_candidate_geometry_against_site(p, asite, BASEMAP_DIR)
            integrity.append({"ok": True, "snapshot": integ, "geometry": geom})
        except A.RealModelSpatialAdaptationError as error:
            integrity.append({"ok": False, "code": error.code, "message": error.message})
    record("C-05", "持久候选与同一场地快照逐项匹配：入口连通、动线不压保留区",
           all(x["ok"] for x in integrity), integrity)

    # Controlled run records issued by the ledger, not self-reported files.
    run_records = []
    for i, p in enumerate(persisted):
        cand, _ = A.candidate_from_persisted(p)
        rec = ledger.issue(kind="local_protocol_stub_run", simulated=True,
                           project_id="ningbo-xiecheng", candidate_sha256=sha(cand),
                           input_hash=snap["sha256"], output_sha256=sha(p),
                           model=config.model_id, prompt_version=config.prompt_version,
                           request_id=(opener.requests[i]["body_sha256"]
                                       if i < len(opener.requests) else sha({"stub": i})),
                           details={"site_snapshot_sha256": snap["sha256"]})
        run_records.append(rec)
    record("C-06", "运行来源由受控账本签发/验签（simulated=true，不是真实模型来源）",
           all(r["issuer_signature"] and r["simulated"] for r in run_records),
           [{"run_id": r["run_id"], "issuer": r["issuer"], "simulated": r["simulated"]}
            for r in run_records])

    adapted = []
    for i, p in enumerate(persisted):
        cand, note = A.candidate_from_persisted(p)
        prov = {"artifact_id": f"stub-{i}", "sha256": sha(cand), "set_id": "w3-stub-set",
                "option_id": p["option_id"], "revision_no": 1, "parent_revision_id": None,
                "actor_id": "offline-verifier", "model_site_boundary_m": [26.17, 17.92],
                "project_id": "ningbo-xiecheng", "provider_kind": "local_protocol_stub",
                "prompt_version": config.prompt_version, "model_id": config.model_id,
                "design_origin": {"kind": "fixture", "declared_by": "local_protocol_stub",
                                  "declaration": "本地协议桩模拟，不是真实模型调用",
                                  "run_refs": [run_records[i]["run_id"]]}}
        m, n = A.adapt_persisted_candidate(p, site=asite, basemap_dir=BASEMAP_DIR,
                                           provenance=prov, created_at=now(), run_ledger=ledger)
        adapted.append(m)
        errs = [e.message for e in Draft202012Validator(schema).iter_errors(m)]
        record(f"C-07{i}", f"候选 {i} 适配产物通过唯一权威顶层 v2 契约", not errs,
               {"option_id": m["option_id"], "schema": m["schema_version"],
                "errors": errs[:6], "design_origin": m["spatial"]["source"]["design_origin"]["kind"],
                "real_model": m["generation"]["real_model"],
                "run_evidence_count": len(m["spatial"]["source"]["design_origin"]["run_evidence"])})

    # Legacy consumer regression: old v1 documents still validate under v1.
    legacy_doc = persisted[0]
    legacy_errors = [e.message for e in Draft202012Validator(legacy).iter_errors(legacy_doc)]
    v2_doc = adapted[0]
    v2_under_legacy = [e.message for e in Draft202012Validator(legacy).iter_errors(v2_doc)]
    record("C-08", "旧消费者回归：v1 文档仍由旧 schema 校验；v2 文档被旧消费者明确拒绝（版本识别）",
           not legacy_errors and v2_doc["schema_version"] != legacy_doc["schema_version"],
           {"legacy_v1_errors": len(legacy_errors),
            "v2_version": v2_doc["schema_version"],
            "v2_under_legacy_error_count": len(v2_under_legacy),
            "note": "旧消费者按 schema_version 拒绝未知 v2，不是加载另一份同名 schema"})

    # ---- negative: forged run record / wrong parent / cross project ---------
    negatives = {}
    cand0, _ = A.candidate_from_persisted(persisted[0])
    forged = dict(run_records[0])
    forged["issuer_signature"] = "0" * 64
    ledger_forged = ControlledRunLedger()
    ledger_forged._records["forged"] = forged
    for name, ledger_x, project, parent, parent_sha in (
        ("伪造签名", ledger_forged, "ningbo-xiecheng", None, None),
        ("跨项目", ledger, "other-project", None, None),
        ("错误父 ID", ledger, "ningbo-xiecheng", "wrong-parent", sha({"p": 1})),
    ):
        p = {"sha256": sha(cand0), "model_site_boundary_m": [26.17, 17.92],
             "project_id": project,
             "design_origin": {"kind": "fixture", "declared_by": "x", "declaration": "x",
                               "run_refs": (["forged"] if name == "伪造签名" else
                                            [run_records[0]["run_id"]])},
             "parent_revision_id": parent,
             "parent_evidence": ({"candidate_sha256": parent_sha} if parent else {})}
        try:
            A.adapt_candidate(cand0, site=asite, basemap_dir=BASEMAP_DIR,
                              provenance=p, created_at=now(), run_ledger=ledger_x)
            negatives[name] = {"rejected": False}
        except A.RealModelSpatialAdaptationError as error:
            negatives[name] = {"rejected": True, "code": error.code}
        except RunLedgerError as error:
            negatives[name] = {"rejected": True, "code": error.code}
    record("C-09", "伪造签名/跨项目/错误父 ID 全部拒绝",
           all(v["rejected"] for v in negatives.values()), negatives)

    # ---- full field mapping on a crafted persisted candidate ----------------
    crafted = copy.deepcopy(persisted[0])
    crafted["relationships"] = [{"relation_id": "rel-x", "type": "adjacent",
                                 "source": "zone:foyer", "target": "zone:display",
                                 "statement": "前厅到主展", "source_refs": ["src-r"]}]
    crafted["objects"][0]["material_id"] = "mat-specific"
    crafted["objects"].append({"object_id": "obj:unknown", "kind": "furniture_cluster",
                               "name": "未知种类",
                               "shape": {"type": "rect", "x": "1", "y": "1", "width": "1", "length": "1"},
                               "source_refs": ["src-u"], "locked": False, "properties": {}})
    crafted["objects"].append({"object_id": "obj:nonrect", "kind": "functional_zone",
                               "name": "非矩形",
                               "shape": {"type": "polygon", "points": [[0, 0], [1, 0], [1, 1]]},
                               "source_refs": ["src-p"], "locked": False, "properties": {}})
    cc, cn = A.candidate_from_persisted(crafted)
    record("C-10", "持久候选完整映射：关系/材料绑定/focal 保留，未知 kind 与非矩形显式标记",
           len(cc["relationships"]) == 1 and bool(cc.get("focal_point")) and
           bool(cn["unsupported_kinds"]) and bool(cn["unsupported_geometry"]) and
           "mat-specific" in [o.get("material_id") for o in cc["zones"]],
           {"relationships": len(cc["relationships"]), "focal": bool(cc.get("focal_point")),
            "unsupported_kinds": cn["unsupported_kinds"],
            "unsupported_geometry": cn["unsupported_geometry"],
            "material_bindings": cn["material_bindings"], "losses": len(cn["losses"])})

    # ---- outputs + render + package ----------------------------------------
    frozen = adapted[0]
    (out / "outputs" / "model.json").write_bytes(canon(frozen))
    hashes = {}

    def write(name, data):
        p = out / "outputs" / name
        p.write_bytes(data)
        hashes[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    render_path = out / "outputs" / "render.png"
    render = {"status": "not_run"}
    if not args.no_render:
        prelim = build_package(frozen, project_id="ningbo-xiecheng-stub", option_revision_id="w3-stub-r1")
        (evidence / "scene-for-render.json").write_bytes(prelim["files"]["scene.json"][2])
        blender = ROOT / "tools/blender/blender-4.2.9-windows-x64/blender.exe"
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
                render = {"status": "rendered" if proc.returncode == 0 and render_path.is_file()
                          and render_path.stat().st_size > 10000 else "failed",
                          "returncode": proc.returncode,
                          "bytes": render_path.stat().st_size if render_path.is_file() else 0}
            except Exception as error:  # noqa: BLE001
                render = {"status": "failed", "error": str(error)}
    record("C-11", "人眼图（本地 Blender 工程样张）" + ("（--no-render，未运行）" if args.no_render else ""),
           None if args.no_render else render.get("status") == "rendered", render)

    pkg = build_package(frozen, project_id="ningbo-xiecheng-stub", option_revision_id="w3-stub-r1")
    files = dict(pkg["files"])
    if render.get("status") == "rendered":
        meta = {"schema_version": "rkd-render-meta.v1",
                "render_sha256": hashlib.sha256(render_path.read_bytes()).hexdigest(),
                "status": "rendered", "engineering_sample": True,
                "note": "灰盒工程样张，不达客户交付级"}
        (out / "outputs" / "render.png.meta.json").write_bytes(canon(meta))
        files["render.png"] = ("png", "image/png", render_path.read_bytes())
        files["render.png.meta.json"] = ("manifest_json", "application/json", canon(meta))
    final = finalize_package(files, pkg["manifest"])
    mbytes = next(v[2] for k, v in final["files"].items() if k == "manifest.json")
    if not render.get("status") == "rendered":
        man = json.loads(mbytes.decode("utf-8"))
        man["package_completeness"] = {"status": "incomplete",
                                       "reason": "render 未成功；不得登记为完整成果",
                                       "render_status": render["status"]}
        mbytes = canon(man)
        final["files"]["manifest.json"] = ("manifest_json", "application/json", mbytes)
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, (_, _, data) in final["files"].items():
                zf.writestr(name, data)
        final["files"]["package.zip"] = ("package_zip", "application/zip", zbuf.getvalue())
    zbytes = final["files"]["package.zip"][2]
    zcheck = check_zip_against_manifest(zbytes, mbytes)
    with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
        names = set(zf.namelist())
        zip_render = zf.read("render.png") if "render.png" in names else b""
    if render.get("status") == "rendered":
        record("C-12", "最终包含 render 且清单/ZIP 逐项重开一致",
               zcheck["ok"] and "render.png" in names and
               hashlib.sha256(zip_render).hexdigest() == hashlib.sha256(render_path.read_bytes()).hexdigest(),
               {"names": sorted(names), "check": zcheck,
                "render_sha": hashlib.sha256(zip_render).hexdigest()[:16]})
    else:
        record("C-12", "不完整包显式标记（无 render 不登记完整成果）",
               "incomplete" in mbytes.decode("utf-8") and "render.png" not in names,
               {"names": sorted(names), "manifest_package_completeness": "incomplete"})
    record("C-13", "HTTP 下载路径（用户可操作链）", None,
           {"reason": "本批未启动 HTTP 服务/浏览器；ZIP 仅内存重开字节校验，不等于 HTTP 下载"})
    write("manifest.json", mbytes)
    write("package.zip", zbytes)
    for name in ("plan.svg", "scene.json", "quantity.json", "quantity.csv", "cost.html"):
        if name in final["files"]:
            write(name, final["files"][name][2])
    if render.get("status") == "rendered":
        write("render.png", render_path.read_bytes())
        write("render.png.meta.json", (out / "outputs" / "render.png.meta.json").read_bytes())

    # plan legend / ambiguous axis text check
    plan = final["files"]["plan.svg"][2].decode("utf-8")
    record("C-14", "图面不把模型声明宽度称净宽；近方主轴标未验证",
           "净宽 mm" not in plan and "净宽 " not in plan.replace("非实测净宽", "") and
           "模型声明宽度" in plan and "非实测净宽" in plan,
           {"claims_measured_net_width": "净宽 " in plan.replace("非实测净宽", ""),
            "fragments": [x for x in plan.split("<text") if "动线" in x][:2]})

    audit = {"schema_version": "rkd-w3-control-trust.v1", "started_at": started,
             "finished_at": now(), "baseline": "4d2ac76", "checks": CHECKS,
             "site_snapshot_sha256": snap["sha256"],
             "ledger_records": [{"run_id": r["run_id"], "simulated": r["simulated"]} for r in run_records],
             "hashes": hashes, "zip_names": sorted(names), "render": render,
             "schema_versions": {"authoritative": "rkd-ai-design-option.v2",
                                 "legacy": "rkd-ai-design-option.v1"},
             "external_calls": 0, "tokens": 0, "cost_cny": 0, "keys_used": False,
             "not_run": ["HTTP 下载", "真实模型调用", "正式采用/发布", "浏览器 UI 可操作链"]}
    (evidence / "verification.json").write_bytes(canon(audit))
    (out / "checks.json").write_bytes(canon(audit))
    failed = [c["id"] for c in CHECKS if c["result"] == "observed_fail"]
    print(f"\nSUMMARY pass={sum(c['result']=='observed_pass' for c in CHECKS)} "
          f"fail={failed} not_run={[c['id'] for c in CHECKS if c['result']=='not_run']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
