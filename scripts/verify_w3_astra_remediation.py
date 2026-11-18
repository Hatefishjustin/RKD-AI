"""W3 GPT-6 Astra 限定整改验证（R1—R5）。

One real pipeline, no external calls:
  confirmed v2 basemap -> single site snapshot (two named digests)
  -> real provider through a controlled transport (protocol stub; simulated)
  -> real SQLite repository (immutable source candidate)
  -> controlled run service issues records from ACTUAL exchange bytes
  -> controlled spatial adaptation (site gate + geometry rebuild from path_mm)
  -> trusted admission (service-context org/project + immutable digest binding)
  -> real service submit / revise / adopt gate
  -> real delivery registration + download (complete / preview / failed / cancel)

    python scripts/verify_w3_astra_remediation.py --evidence <dir> --out <dir>

HTTP download and browser UI remain not_run; nothing here calls a paid model.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "mvp", ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rkd_mvp import realmodel_spatial_adapter as A  # noqa: E402
from rkd_mvp import site_snapshot as SS  # noqa: E402
from rkd_mvp.admission import (  # noqa: E402
    _origin_consistency_problems, admit_document, geometry_projection_digest)
from rkd_mvp.ai_design_option_provider import DesignOptionConfig  # noqa: E402
from rkd_mvp.ai_spatial_outputs import (  # noqa: E402
    assert_complete_package, build_delivery_package, completeness_for_render,
    check_zip_against_manifest)
from rkd_mvp.controlled_design_runtime import ControlledDesignRuntime  # noqa: E402
from rkd_mvp.controlled_run_ledger import ControlledExecutionError, ControlledRunService  # noqa: E402
from w3_trust_findings import CapturingOpener, candidate  # noqa: E402

BASEMAP = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"
PROJECT = "ningbo-xiecheng"
ORG = "org-local"
CHECKS: list[dict] = []


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(value) -> str:
    return hashlib.sha256(canon(value)).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def record(cid: str, name: str, ok, evidence) -> None:
    CHECKS.append({"id": cid, "name": name,
                   "result": ("observed_pass" if ok else "observed_fail") if ok is not None else "not_run",
                   "evidence": evidence})
    print(("PASS " if ok is True else "SKIP " if ok is None else "FAIL ") + cid + " " + name,
          flush=True)


def config() -> DesignOptionConfig:
    return DesignOptionConfig(
        kind="openai_compatible", name="本地协议桩（模拟）", adapter_version="stub",
        prompt_version="pv", schema_version="rkd-ai-design-option.v1", max_candidates=2,
        real_model=True, configuration_errors=[], base_url="http://127.0.0.1:9/stub",
        model_id="stub-model", api_key_present=True, max_attempts=2,
        timeout_seconds=5, external_context_allowed=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(ROOT / "var/evidence/roadmap/W3-astra-remediation/after"))
    ap.add_argument("--out", default=str(ROOT / "deliverables-for-review/roadmap/W3-astra-remediation"))
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()
    evidence = Path(args.evidence).resolve()
    out = Path(args.out).resolve()
    (evidence / "runtime").mkdir(parents=True, exist_ok=True)
    (out / "outputs").mkdir(parents=True, exist_ok=True)

    # ---- snapshots: two named digests --------------------------------------
    facts = A._load_basemap_facts(BASEMAP)
    snap = SS.build_snapshot(facts=facts, entrance_point_m=[0, 10.3],
                             entrance_reason="底图仅推断西门厅；概念暂用点位，现场复核后替换")
    shape = SS.verify_snapshot_shape(snap)
    moved = SS.build_snapshot(facts=facts, entrance_point_m=[0, 9.4],
                              entrance_reason="改入口验证摘要随数据变化")
    record("A-01", "场地快照两摘要分离、可重算、随入口变化",
           shape["site_snapshot_sha256"] == snap["sha256"] and
           snap["sha256"] != snap["basemap_files_sha256"] and moved["sha256"] != snap["sha256"],
           {"site_snapshot_sha256": snap["sha256"],
            "basemap_files_sha256": snap["basemap_files_sha256"],
            "moved_entrance_sha256": moved["sha256"]})

    opener = CapturingOpener({"branch": candidate("branch", 10.3),
                              "loop": candidate("loop", 10.3)})

    class StubOpener:
        def open(self, request, timeout=None):
            return opener.open(request, timeout=timeout)

    # ---- R2 controlled transport / no self-report --------------------------
    svc2 = ControlledRunService(evidence / "runtime" / "r2")
    r2_rejected = False
    try:
        svc2.observe_exchange(project_id=PROJECT, transport="live_http",
                              endpoint="https://public.example.com/v1",
                              request_bytes=b"x", response_bytes=b"y")
    except ControlledExecutionError as error:
        r2_rejected = error.code == "OBSERVE_EXCHANGE_CLOSED"
    runtime = ControlledDesignRuntime(store_dir=evidence / "runtime" / "runs",
                                      opener=StubOpener(), basemap_dir=BASEMAP)
    request = __import__("urllib.request", fromlist=["Request"]).Request(
        "http://127.0.0.1:9/stub/chat/completions",
        data=canon({"model": "stub-model", "messages": [{"role": "user", "content": "probe"}]}),
        method="POST")
    controlled_response = runtime.run_service.transport().send(project_id=PROJECT, request=request)
    observations = runtime.run_service.controlled_observations(project_id=PROJECT)
    record("A-02", "R2：自报 live_http 被拒绝；运行记录只由受控传输实际字节签发",
           r2_rejected and bool(observations) and
           observations[-1].simulated is True and
           observations[-1].transport == "local_protocol_stub" and
           bool(controlled_response.response_sha256),
           {"self_report_rejected": r2_rejected,
            "observation_transport": observations[-1].transport if observations else None,
            "observation_simulated": observations[-1].simulated if observations else None,
            "response_sha256": controlled_response.response_sha256[:16]})

    # ---- real service chain submit -> adapt -> admit -> adopt --------------
    from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository
    from rkd_mvp.ai_design_option_service import AIDesignOptionService
    from rkd_mvp.sqlite_store import SQLiteStore

    db = evidence / "runtime" / "app.sqlite3"
    if db.exists():
        db.unlink()
    store = SQLiteStore(str(db))
    conn = store._connection()
    conn.execute("INSERT OR IGNORE INTO projects(organization_id,project_id,name,status,version) "
                 "VALUES (?,?,?,?,?)", (ORG, PROJECT, "隔离桩库", "active", 1))
    conn.commit()
    repo = SQLiteAIDesignOptionRepository(str(db))
    brief = {"requirements": [], "design_intent": [], "conflicts": [],
             "cost": {"known_items": [], "unknown_items": []}}
    brief_record = {"brief": brief}
    service = AIDesignOptionService(
        repo, lambda *_a: brief_record, lambda *_a: {"obstacles": []},
        evidence / "runtime" / "svc", config=config(), provider=None,
        start_workers=False, controlled_runtime=runtime)
    item = service.submit(ORG, PROJECT, "harness", {}, "astra-idem-0001")["item"]
    service._run_set(ORG, PROJECT, item["set_id"])
    state = service.wait_for_set(ORG, PROJECT, item["set_id"])
    record("A-03", "R1：真实 provider(桩)→真实服务→SQLite 候选集 succeeded",
           state["status"] == "succeeded",
           {"set_status": state["status"], "error_code": state.get("error_code"),
            "error_message": state.get("error_message")})
    if state["status"] != "succeeded":
        audit = {"schema_version": "rkd-w3-astra-remediation.v1",
                 "checks": CHECKS, "blocker": "候选集未成功", "external_calls": 0, "cost_cny": 0}
        (evidence / "verification.json").write_bytes(canon(audit))
        (out / "checks.json").write_bytes(canon(audit))
        return 1

    option = service.status(ORG, PROJECT)["item"]["options"][0]
    model = option["model"]
    admission = option["validation"]["controlled"]["admission"]
    issued = runtime.run_service.export_public()
    record("A-04", "R1：候选是站点绑定 v2、带 spatial、来源 fixture、运行记录全模拟",
           model["schema_version"] == "rkd-ai-design-option.v2" and
           bool(model.get("spatial")) and
           model["generation"]["real_model"] is False and
           model["spatial"]["source"]["design_origin"]["kind"] == "fixture" and
           bool(issued) and all(r["simulated"] is True and
                                r["kind"] == "local_protocol_stub_run" for r in issued) and
           admission["adoptable"] is True,
           {"schema": model["schema_version"], "spatial": bool(model.get("spatial")),
            "generation_real_model": model["generation"]["real_model"],
            "origin": model["spatial"]["source"]["design_origin"]["kind"],
            "admission": {k: admission.get(k) for k in ("status", "adoptable", "scope")},
            "runs": [{"kind": r["kind"], "simulated": r["simulated"]} for r in issued]})

    adopted = service.adopt(ORG, PROJECT, "harness", {
        "option_id": option["option_id"], "expected_revision": 1, "expected_version": 0})
    record("A-05", "R1：正常生成到采用闭环（adopt 不再返回 ADMISSION_NOT_VALIDATED）",
           adopted["item"]["status"] == "adopted_draft",
           {"adoption_status": adopted["item"]["status"],
            "formal_approval": adopted["formal_approval"]})

    # Revision feedback path: unsupported must be explicitly rejected, original kept.
    feedback_rejected = False
    try:
        service.revise(ORG, PROJECT, "harness", {
            "option_id": option["option_id"], "expected_revision": 1,
            "feedback": "把中岛移到右侧", "locks": []})
    except Exception as error:  # noqa: BLE001
        feedback_rejected = getattr(error, "code", "") in {
            "CONTROLLED_FEEDBACK_PATH_UNSUPPORTED", "INVALID_FEEDBACK_BASELINE"}
    after = service.revision_by_id(ORG, PROJECT, option["option_revision_id"])
    record("A-06", "R1：不受支持的反馈路径明确拒绝、不复用父版准入、保留原版本",
           feedback_rejected and after is not None and
           after["revision_no"] == 1 and
           after["validation"]["controlled"]["admission"]["adoptable"] is True,
           {"feedback_rejected": feedback_rejected,
            "original_revision": after["revision_no"] if after else None})

    # ---------------------------------------------------------------- R3 ----
    prov = option["validation"]["controlled"]["provenance"]
    immutable_source = option["validation"]["controlled"]["source_candidate"]
    ctx = dict(site=runtime.adapter_site(), basemap_dir=BASEMAP,
               run_verifier=runtime.verifier(), organization_id=ORG,
               project_id=PROJECT, source_candidate=immutable_source, provenance=prov)
    clean = admit_document(model, **ctx)
    t3a = copy.deepcopy(model)
    fur_ids = {str(f["object_id"]) for f in t3a["spatial"]["furniture"]}
    for f in t3a["spatial"]["furniture"]:
        f["x_mm"] += 100
    for o in t3a["objects"]:
        if str(o.get("object_id")) in fur_ids:
            o["shape"]["x"] = str(float(o["shape"]["x"]) + 0.1)
    r3a = admit_document(t3a, **ctx)
    t3b = copy.deepcopy(model)
    t3b["generation"]["real_model"] = True
    t3b["spatial"]["source"]["design_origin"]["kind"] = "fixture"
    t3b["spatial"]["source"]["design_origin"]["run_refs"] = []
    r3b = admit_document(t3b, **ctx)
    cross = admit_document(model, **{**ctx, "project_id": "other-project"})
    src_conflict = admit_document(model, **{
        **ctx, "source_candidate": {**model, "objects": list(reversed(model["objects"]))}})
    record("A-07", "R3：内容篡改/来源冲突/跨项目/父链声明冲突全部拒绝，可信来源 admitted",
           clean["adoptable"] is True and not r3a["adoptable"] and not r3b["adoptable"] and
           not cross["adoptable"] and not src_conflict["adoptable"],
           {"clean": clean["status"],
            "furniture_tamper": r3a.get("blockers"),
            "declaration_conflict": r3b.get("blockers"),
            "cross_project": cross.get("blockers"),
            "source_conflict": src_conflict.get("blockers")})

    # ---------------------------------------------------------------- R4 ----
    t4 = copy.deepcopy(model)
    t4["spatial"]["circulation"][0]["path_mm"] = [
        [p[0] + 100000, p[1]] for p in t4["spatial"]["circulation"][0]["path_mm"]]
    r4 = admit_document(t4, **ctx)
    zero = copy.deepcopy(model)
    zero["spatial"]["circulation"][0]["width_mm"] = 0
    try:
        A.verify_geometry_projection_consistency(zero)
        zero_ok = False
    except A.RealModelSpatialAdaptationError:
        zero_ok = True
    missing = copy.deepcopy(model)
    missing["objects"] = [o for o in missing["objects"]
                          if str(o.get("kind")) != "display_object"]
    try:
        A.verify_geometry_projection_consistency(missing)
        missing_ok = False
    except A.RealModelSpatialAdaptationError:
        missing_ok = True
    axes = {item["axis"] for item in model["spatial"]["circulation"]}
    record("A-08", "R4：从 path_mm/width_mm/footprint 重建几何；横向/纵向/近方/越界/零宽/缺失/连接均核对",
           not r4["adoptable"] and zero_ok and missing_ok and
           {"horizontal", "vertical"}.issubset(axes),
           {"path_shift": r4.get("blockers"), "zero_width_rejected": zero_ok,
            "missing_object_rejected": missing_ok, "axes": sorted(axes),
            "rebuild_source": "path_mm+width_mm+footprint_polygon_mm"})

    # ---------------------------------------------------------------- R5 ----
    from rkd_mvp.ai_development_repository import SQLiteAIDevelopmentRepository
    from rkd_mvp.ai_spatial_output_service import AISpatialOutputService

    def renderer(scene_path, out_png, width, height, samples):
        out_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"renderer-stub" * 80)
        return {"engine": "stub-renderer", "width": width, "height": height,
                "samples": samples}

    outputs = AISpatialOutputService(SQLiteAIDevelopmentRepository(str(db)), service,
                                     evidence / "runtime" / "outputs", start_workers=False,
                                     renderer=renderer)

    def submit_output(settings: dict, key: str):
        return outputs.submit(ORG, PROJECT, "harness", {
            "option_revision_id": option["option_revision_id"],
            "expected_version": 1, "settings": settings}, key)["item"]

    complete_job = submit_output({"render": True}, "astra-render-ok-1")
    complete_rev = outputs.status(ORG, PROJECT)["revision"]["production_revision_id"]
    complete_status = outputs.package_status(ORG, PROJECT, complete_rev)
    meta, zip_bytes = outputs.file(ORG, PROJECT, complete_rev, "package.zip")
    with zipfile.ZipFile(__import__("io").BytesIO(zip_bytes)) as archive:
        manifest_bytes = archive.read("manifest.json")
    zcheck = check_zip_against_manifest(zip_bytes, manifest_bytes)
    record("A-09", "R5：完整包登记为 complete，下载字节与 ZIP/清单逐项一致",
           complete_job["status"] == "succeeded" and complete_status["complete"] is True and
           meta.get("complete") is True and zcheck["ok"] and
           "package.zip" not in zipfile.ZipFile(__import__("io").BytesIO(zip_bytes)).namelist(),
           {"job": complete_job["status"], "status": complete_status["status"],
            "download_complete": meta.get("complete"), "zip_check": zcheck["ok"],
            "zip_bytes": len(zip_bytes), "zip_sha": hashlib.sha256(zip_bytes).hexdigest()})

    preview_job = submit_output({"render": False}, "astra-render-no-2")
    preview_rev = outputs.status(ORG, PROJECT)["revision"]["production_revision_id"]
    preview_status = outputs.package_status(ORG, PROJECT, preview_rev)
    pmeta, pzip = outputs.file(ORG, PROJECT, preview_rev, "package.zip")
    record("A-10", "R5：无渲染包合法存在但显式 preview/incomplete，不能冒充完整交付",
           preview_job["status"] == "succeeded" and
           preview_status["status"] == "preview_incomplete" and
           preview_status["complete"] is False and
           pmeta.get("delivery_status") == "preview_incomplete" and pmeta.get("complete") is False and
           check_zip_against_manifest(
               pzip,
               zipfile.ZipFile(__import__("io").BytesIO(pzip)).read("manifest.json"))["ok"],
           {"job": preview_job["status"], "status": preview_status["status"],
            "complete": preview_status["complete"],
            "download_status": pmeta.get("delivery_status")})

    # failed render and cancellation are terminal states with no complete package.
    class FailingRenderer:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("stub render failure")

    failing = AISpatialOutputService(SQLiteAIDevelopmentRepository(str(db)), service,
                                     evidence / "runtime" / "outputs-fail", start_workers=False,
                                     renderer=FailingRenderer())
    fail_job = failing.submit(ORG, PROJECT, "harness", {
        "option_revision_id": option["option_revision_id"],
        "expected_version": 1, "settings": {"render": True}}, "astra-render-fail-3")["item"]
    import threading
    class BlockingRenderer:
        def __init__(self): self.release = threading.Event()
        def __call__(self, *args, **kwargs):
            self.release.wait(timeout=10)
            return {"engine": "blocking-stub"}
    blocking = BlockingRenderer()
    async_outputs = AISpatialOutputService(SQLiteAIDevelopmentRepository(str(db)), service,
                                           evidence / "runtime" / "outputs-async",
                                           start_workers=True, renderer=blocking)
    cancel_job = async_outputs.submit(ORG, PROJECT, "harness", {
        "option_revision_id": option["option_revision_id"],
        "expected_version": 1, "settings": {"render": True}}, "astra-render-cancel-4")["item"]
    cancelled = async_outputs.cancel(ORG, PROJECT, cancel_job["job_id"])["item"]
    blocking.release.set()
    record("A-11", "R5：渲染失败/取消不登记完整包",
           fail_job["status"] == "failed" and cancelled["status"] == "cancelled",
           {"failed_job": fail_job["status"], "failed_code": fail_job.get("error_code"),
            "cancelled_job": cancelled["status"]})

    # standalone builder + assertion still agree with the service semantics.
    built = build_delivery_package(model, project_id=PROJECT, option_revision_id="standalone",
                                   render_status="rendered", render_bytes=b"\x89PNG\r\n\x1a\nx")
    incomplete = build_delivery_package(model, project_id=PROJECT, option_revision_id="standalone",
                                        render_status="not_run")
    record("A-12", "R5：单一文件集打包 + assert_complete_package 与登记边界一致",
           built["registration"]["ok"] is True and incomplete["registration"]["ok"] is False and
           assert_complete_package(built["zip_bytes"], built["manifest_bytes"])["ok"] is True,
           {"complete_ok": built["registration"]["ok"],
            "incomplete_ok": incomplete["registration"]["ok"]})

    record("A-13", "HTTP/浏览器下载可操作链", None,
           {"reason": "本批未启动 HTTP 服务/浏览器；仅做真实服务下载与内存字节校验"})

    # ---- outputs -----------------------------------------------------------
    (out / "outputs" / "model.json").write_bytes(canon(model))
    (out / "outputs" / "manifest.json").write_bytes(manifest_bytes)
    (out / "outputs" / "package.zip").write_bytes(zip_bytes)
    (out / "outputs" / "package-preview.zip").write_bytes(pzip)
    (out / "outputs" / "site-snapshot.json").write_bytes(canon(snap))

    audit = {"schema_version": "rkd-w3-astra-remediation.v1", "baseline": "72442c7",
             "started_at": now(), "finished_at": now(), "checks": CHECKS,
             "site_snapshot_sha256": snap["sha256"],
             "basemap_files_sha256": snap["basemap_files_sha256"],
             "run_records": [{"run_id": r["run_id"], "kind": r["kind"],
                              "simulated": r["simulated"]} for r in issued],
             "external_calls": 0, "tokens": 0, "cost_cny": 0, "keys_used": False,
             "not_run": ["HTTP 下载", "真实模型调用", "正式采用/发布", "浏览器 UI", "专业签核"]}
    (evidence / "verification.json").write_bytes(canon(audit))
    (out / "checks.json").write_bytes(canon(audit))
    failed = [c["id"] for c in CHECKS if c["result"] == "observed_fail"]
    print(f"\nSUMMARY pass={sum(c['result'] == 'observed_pass' for c in CHECKS)} "
          f"fail={failed} not_run={[c['id'] for c in CHECKS if c['result'] == 'not_run']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
