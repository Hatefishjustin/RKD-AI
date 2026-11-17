"""W3 trust remediation verification (baseline 2253899).

One real pipeline, no external calls:
  hash-verified v2 basemap -> SINGLE site snapshot (two named digests)
  -> protocol stub captures the EXACT request -> real provider.generate
  -> real SQLite repository -> controlled run service (observes the exchange)
  -> same-run adapter with site gate + projection consistency
  -> v2 contract + old/new consumer dispatch
  -> real service adoption gate (not_validated refused)
  -> delivery package (complete / incomplete) re-opened against its manifest
  -> HTTP download = not_run.

  python scripts/verify_w3_trust_remediation.py \
      --evidence var/evidence/roadmap/W3-trust-remediation/after \
      --out deliverables-for-review/roadmap/W3-trust-remediation [--no-render]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import re
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
from rkd_mvp import site_snapshot as SS  # noqa: E402
from rkd_mvp.admission import (ContractRegistry, UnsupportedSchemaVersion, admit_document,  # noqa: E402
                               legacy_consumer_validate)
from rkd_mvp.ai_design_option_provider import (DesignOptionConfig, DesignOptionProviderFailure,  # noqa: E402
                                               RealModelDesignOptionProvider,
                                               build_design_option_provider)
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository  # noqa: E402
from rkd_mvp.ai_design_option_service import AIDesignOptionService  # noqa: E402
from rkd_mvp.ai_spatial_outputs import (assert_complete_package, build_delivery_package,  # noqa: E402
                                        check_zip_against_manifest)
from rkd_mvp.controlled_run_ledger import ControlledRunService, RunLedgerError  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from w3_trust_findings import CapturingOpener, candidate  # noqa: E402

BASEMAP_DIR = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"
CONTRACT_V2 = ROOT / "contracts/v2/ai-design-option.schema.json"
LEGACY_SCHEMA = ROOT / "contracts/v1/ai-design-option.schema.json"
CHECKS: list[dict] = []
PROJECT = "ningbo-xiecheng"


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha(value) -> str:
    return hashlib.sha256(canon(value)).hexdigest()


def record(cid: str, name: str, ok, evidence) -> None:
    CHECKS.append({"id": cid, "name": name,
                   "result": ("observed_pass" if ok else "observed_fail") if ok is not None else "not_run",
                   "evidence": evidence})
    print(("PASS " if ok is True else "SKIP " if ok is None else "FAIL ") + cid + " " + name, flush=True)


def message_payload(body: dict) -> dict:
    for message in body.get("messages") or []:
        if message.get("role") == "user":
            try:
                return json.loads(message.get("content") or "{}")
            except ValueError:
                return {}
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(ROOT / "var/evidence/roadmap/W3-trust-remediation/after"))
    ap.add_argument("--out", default=str(ROOT / "deliverables-for-review/roadmap/W3-trust-remediation"))
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()
    evidence = Path(args.evidence).resolve()
    out = Path(args.out).resolve()
    (evidence / "runtime").mkdir(parents=True, exist_ok=True)
    (out / "outputs").mkdir(parents=True, exist_ok=True)
    started = now()
    run_slug = started.replace(":", "").replace("+", "_").replace("-", "")
    service_dir = evidence / "runtime" / "runservice" / run_slug

    # ---- D-01 one snapshot, two separately named digests --------------------
    facts = A._load_basemap_facts(BASEMAP_DIR)
    snap = SS.build_snapshot(facts=facts, entrance_point_m=[0, 10.3],
                             entrance_reason="底图仅推断西门厅；概念暂用点位，现场复核后替换")
    shape = SS.verify_snapshot_shape(snap)
    moved = SS.build_snapshot(facts=facts, entrance_point_m=[0, 9.4],
                              entrance_reason="改入口，用于验证摘要随数据变化")
    record("D-01", "场地快照：完整快照摘要与底图文件摘要分开命名、可重算、随入口变化",
           shape["site_snapshot_sha256"] == snap["sha256"] and
           snap["sha256"] != snap["basemap_files_sha256"] and
           moved["sha256"] != snap["sha256"] and
           snap["basemap_files_sha256"] == facts["basemap_files_sha256"],
           {"site_snapshot_sha256": snap["sha256"],
            "basemap_files_sha256": snap["basemap_files_sha256"],
            "moved_entrance_sha256": moved["sha256"],
            "unverified_count": shape["unverified_count"], "keepouts": shape["keepouts"],
            "site_verified": snap["site_verified"]})

    psite, asite = SS.provider_site(snap), SS.adapter_site(snap)

    # ---- real provider call through a capture stub -------------------------
    opener = CapturingOpener({"branch": candidate("branch", 10.3),
                              "loop": candidate("loop", 10.3)})
    exchanges: list[dict] = []

    def on_exchange(**kwargs):
        exchanges.append(kwargs)

    service = ControlledRunService(service_dir)
    config = DesignOptionConfig(kind="openai_compatible", name="本地协议桩（模拟）",
                                adapter_version="rkd-real-design-provider.stub",
                                prompt_version="design-stub.zh-CN.v1",
                                schema_version="rkd-ai-design-option.v1", max_candidates=2,
                                real_model=True, configuration_errors=[],
                                base_url="http://127.0.0.1:9/local-stub", model_id="stub-model",
                                api_key_present=True, max_attempts=2, timeout_seconds=5,
                                external_context_allowed=False)
    provider = RealModelDesignOptionProvider(config, api_key="stub-not-a-real-key", opener=opener,
                                             run_log_dir=str(evidence / "runtime" / "runs"),
                                             on_exchange=on_exchange)
    brief = {"requirements": [], "design_intent": [], "conflicts": [],
             "cost": {"known_items": [], "unknown_items": []}}
    try:
        models = provider.generate(set_id="w3-stub-set", brief=brief, site=psite,
                                   input_hash=snap["sha256"], generated_at=now())
        provider_error = ""
    except DesignOptionProviderFailure as error:
        models, provider_error = [], f"{error.code}: {error.message}"

    # ---- D-02 the ACTUAL request body --------------------------------------
    request = (opener.requests[0]["body"] if opener.requests else {})
    payload = message_payload(request)
    boundary = payload.get("boundary") or {}
    entrance = boundary.get("entrance") or {}
    point = entrance.get("point")
    body_text = json.dumps(request, ensure_ascii=False)
    snapshot_block = payload.get("site_snapshot") or {}
    fixed_example = any(token in body_text for token in
                        ("legal_path_example", "12x8", "12 x 8", "12, 1.0", "12,1.0"))
    record("D-02", "实际模型请求：携带入口点、完整快照、保留区与两套摘要；无固定 12x8 示例",
           point is not None and abs(float(point[1]) - 10.3) < 1e-6 and
           boundary.get("site_snapshot_sha256") == snap["sha256"] and
           boundary.get("basemap_files_sha256") == snap["basemap_files_sha256"] and
           len(snapshot_block.get("keepouts") or []) == 2 and
           bool(snapshot_block.get("unverified_facts")) and not fixed_example,
           {"messages": len(request.get("messages") or []),
            "request_sha256": opener.requests[0]["body_sha256"] if opener.requests else None,
            "request_bytes": opener.requests[0]["body_bytes"] if opener.requests else 0,
            "entrance_point": point, "boundary_snapshot": boundary.get("site_snapshot_sha256"),
            "boundary_basemap": boundary.get("basemap_files_sha256"),
            "snapshot_keepouts": len(snapshot_block.get("keepouts") or []),
            "snapshot_unverified": len(snapshot_block.get("unverified_facts") or []),
            "ships_fixed_12x8_example": fixed_example})

    if not models:
        audit = {"schema_version": "rkd-w3-trust-remediation.v2", "checks": CHECKS,
                 "blocker": provider_error or "provider 未产出候选", "started_at": started,
                 "finished_at": now(), "external_calls": 0, "cost_cny": 0}
        (evidence / "verification.json").write_bytes(canon(audit))
        (out / "checks.json").write_bytes(canon(audit))
        return 1

    record("D-03", "候选是 v2 且带同一快照摘要（provider 不再以 v1 承载场地）",
           all(model["schema_version"] == "rkd-ai-design-option.v2" and
               model["site_snapshot"]["sha256"] == snap["sha256"] and
               model["site_snapshot"]["basemap_files_sha256"] == snap["basemap_files_sha256"]
               for model in models),
           [{"option_id": model["option_id"], "schema": model["schema_version"],
             "snapshot": model["site_snapshot"]["sha256"],
             "basemap": model["site_snapshot"]["basemap_files_sha256"]} for model in models])

    # ---- persist through the REAL repository -------------------------------
    db = evidence / "runtime" / "app.sqlite3"
    if db.exists():
        db.unlink()
    store = SQLiteStore(str(db))
    conn = store._connection()
    conn.execute("INSERT OR IGNORE INTO projects(organization_id, project_id, name, status, version) "
                 "VALUES (?,?,?,?,?)", ("org-local", PROJECT, "宁波协诚（隔离桩库）", "active", 1))
    conn.commit()
    repo = SQLiteAIDesignOptionRepository(str(db))
    persisted: list[dict] = []
    with repo.transaction("org-local", PROJECT, write=True) as tx:
        tx.insert_set({"set_id": "w3-stub-set", "brief_id": "w3-stub-brief",
                       "input_hash": snap["sha256"], "status": "succeeded", "phase": "completed",
                       "attempt_count": 1, "config": config.public(), "context": {},
                       "error_code": None, "error_message": None,
                       "idempotency_key": "w3-stub-set-v1", "actor_id": "stub",
                       "created_at": now(), "updated_at": now()})
        for i, model in enumerate(models):
            oid = f"ai-option-revision-stub-{i}"
            tx.insert_revision({"option_revision_id": oid, "set_id": "w3-stub-set",
                                "option_id": f"w3-stub-set:stub-{i}", "revision_no": 1,
                                "parent_revision_id": None,
                                "strategy_id": model["strategy"]["strategy_id"],
                                "strategy": model["strategy"], "model": model,
                                "validation": model["validation"], "materials": model["materials"],
                                "cost": model["cost"], "feedback": model["feedback"],
                                "diff": model["diff"], "conflicts": model["conflicts"],
                                "structure_signature": model["structure_signature"],
                                "lifecycle_status": "candidate", "source_kind": model["source_kind"],
                                "change_reason": "本地协议桩候选，未采用", "actor_id": "stub",
                                "created_at": now()})
            persisted.append(tx.revision(oid)["model"])
    record("D-04", "候选经真实 SQLite 仓储写入并读回，读回文档仍绑定同一快照摘要",
           len(persisted) == 2 and all(p["site_snapshot"]["sha256"] == snap["sha256"] and
                                       p["schema_version"] == "rkd-ai-design-option.v2"
                                       for p in persisted),
           [{"option_id": p["option_id"], "snapshot": p["site_snapshot"]["sha256"],
             "objects": len(p["objects"])} for p in persisted])

    # ---- controlled run service: observe, register, issue ------------------
    observations = [service.observe_exchange(project_id=PROJECT, **item) for item in exchanges]
    run_refs: list[str] = []
    for i, model in enumerate(persisted):
        cand, _ = A.candidate_from_persisted(model)
        service.register_revision(project_id=PROJECT, revision_id=f"ai-option-revision-stub-{i}",
                                  candidate_sha256=sha(cand))
        record_row = service.issue(observation=observations[min(i, len(observations) - 1)],
                                   project_id=PROJECT, candidate_sha256=sha(cand),
                                   input_hash=snap["sha256"], output_sha256=sha(model),
                                   model=config.model_id, prompt_version=config.prompt_version,
                                   site_snapshot_sha256=snap["sha256"],
                                   basemap_files_sha256=snap["basemap_files_sha256"],
                                   details={"transport_note": "本地协议桩，非真实模型"})
        run_refs.append(record_row["run_id"])
    verifier = service.verifier()
    issued = service.export_public()
    record("D-05", "运行记录由受控服务观测实际请求/响应后签发：simulated、绑定同一快照、不是真实模型",
           all(r["simulated"] is True and r["kind"] == "local_protocol_stub_run" and
               r["site_snapshot_sha256"] == snap["sha256"] and
               r["basemap_files_sha256"] == snap["basemap_files_sha256"] and
               bool(r["issuer_signature"]) for r in issued),
           [{"run_id": r["run_id"], "kind": r["kind"], "simulated": r["simulated"],
             "transport": r["transport"], "request_sha256": r["request_sha256"][:16],
             "site_snapshot_sha256": r["site_snapshot_sha256"][:16],
             "issuer_id": r["issuer_id"]} for r in issued])

    # ---- same-run adaptation with the site gate ---------------------------
    adapted: list[dict] = []
    adapt_errors: list[str] = []
    for i, model in enumerate(persisted):
        cand, _ = A.candidate_from_persisted(model)
        prov = {"artifact_id": f"stub-{i}", "sha256": sha(cand), "set_id": "w3-stub-set",
                "option_id": model["option_id"], "revision_no": 1, "parent_revision_id": None,
                "actor_id": "offline-verifier", "model_site_boundary_m": [26.17, 17.92],
                "project_id": PROJECT, "provider_kind": "local_protocol_stub",
                "prompt_version": config.prompt_version, "model_id": config.model_id,
                "site_snapshot_sha256": snap["sha256"],
                "design_origin": {"kind": "fixture", "declared_by": "local_protocol_stub",
                                  "declaration": "本地协议桩模拟，不是真实模型调用",
                                  "run_refs": [run_refs[i]]}}
        try:
            doc, note = A.adapt_persisted_candidate(model, site=asite, basemap_dir=BASEMAP_DIR,
                                                    provenance=prov, created_at=now(),
                                                    run_verifier=verifier)
            adapted.append(doc)
        except A.RealModelSpatialAdaptationError as error:
            adapt_errors.append(f"{error.code}: {error.message}")
    record("D-06", "同一运行适配成功：场地门槛与源/legacy/spatial 投影一致性均执行",
           len(adapted) == 2 and not adapt_errors,
           {"adapted": len(adapted), "errors": adapt_errors,
            "integrity": [(doc.get("spatial", {}).get("source", {}).get("site_snapshot_sha256")
                           or "") for doc in adapted]})

    # ---- D-07 circulation rectangles are reversible -----------------------
    zero, mismatch, rows = [], [], []
    if adapted:
        spatial = {c["object_id"]: c for c in adapted[0]["spatial"]["circulation"]}
        legacy = {s["segment_id"]: s for s in adapted[0]["circulation"]["segments"]}
        for sid, path in spatial.items():
            shape = (legacy.get(sid) or {}).get("shape") or {}
            width = float(shape.get("width") or 0) * 1000
            length = float(shape.get("length") or 0) * 1000
            declared = path.get("declared_rect_mm") or []
            if width <= 0 or length <= 0:
                zero.append(sid)
            if [round(width), round(length)] != [declared[2], declared[3]]:
                mismatch.append(sid)
            rows.append({"segment_id": sid, "axis": path.get("axis"),
                         "declared_rect_mm": declared,
                         "legacy_mm": [round(width), round(length)],
                         "area_m2": round(width * length / 1_000_000, 4)})
    record("D-07", "纵向/横向动线的 legacy 矩形零宽为零、与源矩形逐项相等（含面积）",
           bool(rows) and not zero and not mismatch and
           any(row["axis"] == "vertical" for row in rows) and
           any(row["axis"] == "horizontal" for row in rows),
           {"zero_dimension": zero, "mismatched": mismatch, "segments": rows})

    # ---- D-08 source forgery / arbitrary parent / rogue service -----------
    cand0, _ = A.candidate_from_persisted(persisted[0])
    attempts: dict[str, dict] = {}
    for name, kwargs in (("未登记父链", {"parent_revision_id": "invented-parent-uid"}),
                         ("跨项目", {})):
        try:
            target_project = PROJECT if name != "跨项目" else "other-project"
            service.issue(observation=observations[0], project_id=target_project,
                          candidate_sha256=sha(cand0), input_hash=snap["sha256"],
                          output_sha256=sha({"o": name}), model=config.model_id,
                          prompt_version=config.prompt_version,
                          site_snapshot_sha256=snap["sha256"],
                          basemap_files_sha256=snap["basemap_files_sha256"], **kwargs)
            attempts[name] = {"rejected": False}
        except RunLedgerError as error:
            attempts[name] = {"rejected": True, "code": error.code}
    try:
        rogue = ControlledRunService(evidence / "runtime" / "rogue-service" / run_slug)
        rogue.verifier().verify(run_refs[0], project_id=PROJECT,
                                candidate_sha256=sha(cand0))
        attempts["自建服务验签"] = {"rejected": False}
    except RunLedgerError as error:
        attempts["自建服务验签"] = {"rejected": True, "code": error.code}
    try:
        A.adapt_candidate(cand0, site=asite, basemap_dir=BASEMAP_DIR,
                          provenance={"sha256": sha(cand0), "model_site_boundary_m": [26.17, 17.92],
                                      "project_id": PROJECT, "site_snapshot_sha256": snap["sha256"],
                                      "design_origin": {"kind": "real_model", "declared_by": "forger",
                                                        "declaration": "self", "run_refs": [run_refs[0]]}},
                          created_at=now(), run_verifier=verifier)
        attempts["桩记录冒充真实"] = {"rejected": False}
    except A.RealModelSpatialAdaptationError as error:
        attempts["桩记录冒充真实"] = {"rejected": True, "code": error.code}
    record("D-08", "未登记父链/跨项目/自建服务/桩记录冒充真实 全部拒绝",
           all(value.get("rejected") for value in attempts.values()), attempts)

    # ---- D-09 contract dispatch: old consumer vs new consumer -------------
    v2_doc = adapted[0] if adapted else {}
    v2_errors = [e.message for e in Draft202012Validator(
        json.loads(CONTRACT_V2.read_text(encoding="utf-8"))).iter_errors(v2_doc)]
    legacy_schema = json.loads(LEGACY_SCHEMA.read_text(encoding="utf-8"))
    synthetic_config = DesignOptionConfig(kind="synthetic", name="本地合成（非真实 AI）",
                                          adapter_version="rkd-design-option-provider.v1",
                                          prompt_version="design-option-strategy.zh-CN.v1",
                                          schema_version="rkd-ai-design-option.v1",
                                          max_candidates=2, real_model=False,
                                          configuration_errors=[])
    synthetic = build_design_option_provider(synthetic_config)
    v1_doc = synthetic.generate(
        set_id="w3-synth-set", brief=brief,
        site={"width": 12, "length": 8, "unit": "m",
              "boundary_source": "test_parameters_not_site_verified"},
        input_hash=sha({"synthetic": True}), generated_at=now())[0]
    v1_errors = [e.message for e in Draft202012Validator(legacy_schema).iter_errors(v1_doc)]
    old_consumer_code = ""
    try:
        legacy_consumer_validate(v2_doc)
    except UnsupportedSchemaVersion as error:
        old_consumer_code = error.code
    new_consumer_ok = ContractRegistry().validate(v2_doc) is v2_doc
    record("D-09", "版本分发：旧消费者对 v2 明确报不支持版本，新消费者读写 v2，v1 文档仍通过",
           not v2_errors and not v1_errors and old_consumer_code == "UNSUPPORTED_SCHEMA_VERSION"
           and new_consumer_ok,
           {"v2_errors": v2_errors[:3], "v1_errors": v1_errors[:3],
            "old_consumer_code": old_consumer_code,
            "old_consumer_versions": ContractRegistry(versions=("rkd-ai-design-option.v1",)).supported_versions,
            "new_consumer_versions": ContractRegistry().supported_versions})

    # ---- D-10 real service adoption gate ----------------------------------
    gate = {}
    try:
        svc = AIDesignOptionService(repo, lambda *_: None, lambda *_: {}, evidence / "runtime" / "svc",
                                    config=config, provider=None, start_workers=False,
                                    basemap_dir=BASEMAP_DIR, run_verifier=verifier)
        gate["registry_versions"] = svc.registry.supported_versions
        # v2 through the REAL consumer validation entry
        # A provider-produced v2 document, not the adapter projection.
        checked = svc._validate_candidate(copy.deepcopy(models[0]), brief=brief, config=config,
                                          input_hash=snap["sha256"])
        gate["v2_accepted_by_service"] = checked["schema_version"] == "rkd-ai-design-option.v2"
        gate["admission"] = admit_document(adapted[0], site=asite, basemap_dir=BASEMAP_DIR,
                                           run_verifier=verifier)
        # adoption refuses a revision whose admission is not_validated
        with repo.transaction("org-local", PROJECT, write=True) as tx:
            tx.insert_revision({"option_revision_id": "gate-rev", "set_id": "w3-stub-set",
                                "option_id": "gate-option", "revision_no": 1,
                                "parent_revision_id": None, "strategy_id": "gate",
                                "strategy": models[0]["strategy"], "model": models[0],
                                "validation": {"status": "passed",
                                               "admission": {"status": "not_validated",
                                                             "adoptable": False,
                                                             "blockers": ["隔离测试"]}},
                                "materials": models[0]["materials"], "cost": models[0]["cost"],
                                "feedback": models[0]["feedback"], "diff": [], "conflicts": [],
                                "structure_signature": models[0]["structure_signature"],
                                "lifecycle_status": "candidate", "source_kind": models[0]["source_kind"],
                                "change_reason": "gate", "actor_id": "verifier",
                                "created_at": now()})
        try:
            svc.adopt("org-local", PROJECT, "verifier", {"option_id": "gate-option",
                                                         "expected_revision": 1,
                                                         "expected_version": 0})
            gate["not_validated_rejected"] = False
            gate["adopt_error"] = ""
        except Exception as error:  # noqa: BLE001
            gate["not_validated_rejected"] = getattr(error, "code", "") == "ADMISSION_NOT_VALIDATED"
            gate["adopt_error"] = f"{getattr(error, 'code', type(error).__name__)}"
    except Exception as error:  # noqa: BLE001
        gate["error"] = f"{type(error).__name__}: {error}"
    record("D-10", "真实服务入口：注册表支持 v2、v2 经服务校验、未验证候选被采用闸口拒绝",
           bool(gate.get("v2_accepted_by_service")) and
           gate.get("not_validated_rejected") is True and
           "rkd-ai-design-option.v2" in (gate.get("registry_versions") or []),
           gate)

    # ---- D-11 admission on the adapted document ----------------------------
    try:
        admission = admit_document(adapted[0], site=asite, basemap_dir=BASEMAP_DIR,
                                   run_verifier=verifier)
        tampered = copy.deepcopy(adapted[0])
        tampered["site_snapshot"]["sha256"] = sha({"not": "this site"})
        tampered_admission = admit_document(tampered, site=asite, basemap_dir=BASEMAP_DIR,
                                           run_verifier=verifier)
    except Exception as error:  # noqa: BLE001
        admission = {"error": str(error)}
        tampered_admission = {}
    record("D-11", "准入党：同源候选 admitted/site_bound，改动快照摘要后不可采用",
           admission.get("status") == "admitted" and admission.get("adoptable") is True and
           admission.get("site_bound") is True and
           tampered_admission.get("adoptable") is False,
           {"admission": {k: admission.get(k) for k in ("status", "adoptable", "scope",
                                                        "site_snapshot_sha256", "blockers")},
            "tampered": {k: tampered_admission.get(k) for k in ("status", "adoptable", "blockers")}})

    # ---- D-12 package: complete (render) and incomplete --------------------
    render_path = out / "outputs" / "render.png"
    render = {"status": "not_run"}
    if not args.no_render:
        scene = build_delivery_package(adapted[0], project_id="ningbo-xiecheng-stub",
                                       option_revision_id="w3-stub-r1",
                                       render_status="pending")["build"]
        (evidence / "scene-for-render.json").write_bytes(canon(scene["scene"]))
        blender = ROOT / "tools/blender/blender-4.2.9-windows-x64/blender.exe"
        if blender.is_file():
            env = dict(os.environ)
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
                env.pop(key, None)
            cmd = [str(blender), "-b", "--factory-startup", "-noaudio", "--python",
                   str(ROOT / "scripts/render_spatial_scene.py"), "--",
                   "--scene", str(evidence / "scene-for-render.json"),
                   "--out", str(render_path), "--width", "1280", "--height", "800", "--samples", "48"]
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=300, env=env)
                render = {"status": "rendered" if proc.returncode == 0 and render_path.is_file()
                          and render_path.stat().st_size > 10000 else "failed",
                          "returncode": proc.returncode,
                          "bytes": render_path.stat().st_size if render_path.is_file() else 0}
            except Exception as error:  # noqa: BLE001
                render = {"status": "failed", "error": str(error)}
    record("D-12", "人眼图（本地 Blender 工程样张）" + ("（--no-render 未运行）" if args.no_render else ""),
           None if args.no_render else render.get("status") == "rendered", render)

    render_bytes = render_path.read_bytes() if render.get("status") == "rendered" else None
    complete = build_delivery_package(adapted[0], project_id="ningbo-xiecheng-stub",
                                      option_revision_id="w3-stub-r1",
                                      render_bytes=render_bytes,
                                      render_status=render.get("status", "not_run"))
    incomplete = build_delivery_package(adapted[0], project_id="ningbo-xiecheng-stub",
                                        option_revision_id="w3-stub-r1",
                                        render_status="not_run")
    def archive_names(zip_bytes: bytes) -> list[str]:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            return sorted(archive.namelist())

    complete_names = archive_names(complete["zip_bytes"])
    incomplete_names = archive_names(incomplete["zip_bytes"])
    record("D-13", "完整包：render 在 ZIP 内、清单逐项一致、可登记为完整",
           (None if render.get("status") != "rendered" else
            complete["zip_check"]["ok"] and complete["complete"] and
            complete["registration"]["ok"] and "render.png" in complete_names and
            "package.zip" not in complete_names),
           {"names": complete_names, "check": complete["zip_check"]["problems"],
            "render_status": render.get("status"),
            "registration_ok": complete["registration"]["ok"],
            "manifest_sha256": hashlib.sha256(complete["manifest_bytes"]).hexdigest(),
            "zip_sha256": hashlib.sha256(complete["zip_bytes"]).hexdigest(),
            "render_sha256": (hashlib.sha256(render_bytes).hexdigest() if render_bytes else None)})
    record("D-14", "不完整包：同样通过清单校验，但显式 incomplete 且不能冒充完整",
           incomplete["zip_check"]["ok"] and not incomplete["complete"] and
           incomplete["registration"]["ok"] is False and
           incomplete["completeness"]["status"] == "incomplete" and
           "package.zip" not in incomplete_names,
           {"names": incomplete_names, "check": incomplete["zip_check"]["problems"],
            "completeness": incomplete["completeness"],
            "registration_ok": incomplete["registration"]["ok"]})
    record("D-15", "HTTP 下载路径（用户可操作链）", None,
           {"reason": "本批未启动 HTTP 服务/浏览器；ZIP 仅内存重开字节校验，不等于 HTTP 下载"})

    # ---- outputs -----------------------------------------------------------
    frozen = adapted[0]
    written: dict[str, dict] = {}

    def write(name: str, data: bytes) -> None:
        (out / "outputs" / name).write_bytes(data)
        written[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    write("model.json", canon(frozen))
    write("manifest.json", complete["manifest_bytes"])
    write("package.zip", complete["zip_bytes"])
    for name, (_, _, data) in complete["files"].items():
        if name in {"manifest.json", "package.zip"}:
            continue
        write(name, data)
    (out / "outputs" / "package-incomplete.zip").write_bytes(incomplete["zip_bytes"])
    (out / "outputs" / "manifest-incomplete.json").write_bytes(incomplete["manifest_bytes"])
    write("request-payload.json", canon(request))
    write("site-snapshot.json", canon(snap))

    plan = complete["files"]["plan.svg"][2].decode("utf-8")
    record("D-16", "图面不把模型声明宽度称净宽；近方主轴标未验证",
           "净宽 mm" not in plan and "模型声明宽度" in plan and "非实测净宽" in plan,
           {"fragments": re.findall(r"主动线[^<]{0,40}", plan)[:2]})

    # ---- D-17 the same digests reach the delivered manifest inside the ZIP --
    with zipfile.ZipFile(io.BytesIO(complete["zip_bytes"])) as archive:
        inner_manifest = json.loads(archive.read("manifest.json"))
        inner_model = json.loads(archive.read("model.json"))
    inner_site = inner_manifest.get("site_snapshot") or {}
    record("D-17", "成果清单与模型均携带同一场地快照/底图文件摘要，与请求和运行记录逐项相等",
           inner_site.get("sha256") == snap["sha256"] and
           inner_site.get("basemap_files_sha256") == snap["basemap_files_sha256"] and
           inner_model.get("site_snapshot", {}).get("sha256") == snap["sha256"] and
           inner_model.get("site_snapshot", {}).get("basemap_files_sha256") == snap["basemap_files_sha256"] and
           all(r["site_snapshot_sha256"] == snap["sha256"] for r in service.export_public()),
           {"manifest_site_snapshot_sha256": inner_site.get("sha256"),
            "manifest_basemap_files_sha256": inner_site.get("basemap_files_sha256"),
            "model_site_snapshot_sha256": (inner_model.get("site_snapshot") or {}).get("sha256"),
            "request_site_snapshot_sha256": boundary.get("site_snapshot_sha256"),
            "snapshot_sha256": snap["sha256"],
            "basemap_files_sha256": snap["basemap_files_sha256"]})

    audit = {"schema_version": "rkd-w3-trust-remediation.v2", "baseline": "2253899",
             "started_at": started, "finished_at": now(), "checks": CHECKS,
             "site_snapshot_sha256": snap["sha256"],
             "basemap_files_sha256": snap["basemap_files_sha256"],
             "run_records": [{"run_id": r["run_id"], "kind": r["kind"],
                              "simulated": r["simulated"], "issuer_id": r["issuer_id"],
                              "request_sha256": r["request_sha256"],
                              "site_snapshot_sha256": r["site_snapshot_sha256"]} for r in service.export_public()],
             "hashes": written, "render": render,
             "external_calls": 0, "tokens": 0, "cost_cny": 0, "keys_used": False,
             "not_run": ["HTTP 下载", "真实模型调用", "正式采用/发布", "浏览器 UI 可操作链"]}
    (evidence / "verification.json").write_bytes(canon(audit))
    (out / "checks.json").write_bytes(canon(audit))
    failed = [c["id"] for c in CHECKS if c["result"] == "observed_fail"]
    print(f"\nSUMMARY pass={sum(c['result'] == 'observed_pass' for c in CHECKS)} "
          f"fail={failed} not_run={[c['id'] for c in CHECKS if c['result'] == 'not_run']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
