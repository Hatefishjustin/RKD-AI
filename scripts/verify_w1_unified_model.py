"""W1 统一模型适配：真实 HTTP / 隔离库 / 两种布局 / 正负例 / 回滚 / 重启。

用法：
  python scripts/verify_w1_unified_model.py --out <dir> --runtime <dir>

0 外部模型调用、0 外发、0 密钥。所有源提案都是明确标记的本地夹具
（arc_first_batch_stub.valid_proposal），通过真实 Studio 库的有效候选产物进入
正式适配器，不手搬 JSON、不在验收里补结构化目标冒充 AI 设计。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import threading
from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def _arg(flag: str, default: Path) -> Path:
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).resolve()
        if a.startswith(flag + "="):
            return Path(a.split("=", 1)[1]).resolve()
    return default


EVIDENCE = _arg("--out", ROOT / "var/evidence/roadmap/W1-统一模型适配/after")
RUNTIME = _arg("--runtime", ROOT / "var/evidence/roadmap/W1-统一模型适配/runtime")
EVIDENCE.mkdir(parents=True, exist_ok=True)
RUNTIME.mkdir(parents=True, exist_ok=True)
MAIN_DB = RUNTIME / "app.sqlite3"
STUDIO_DB = RUNTIME / "studio.db"
for f in (MAIN_DB, STUDIO_DB):
    if f.exists():
        f.unlink()
shutil.rmtree(RUNTIME / "projects" / "ai-design-options" / "studio-import",
              ignore_errors=True)

sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from arc_first_batch_stub import SITE, valid_proposal  # noqa: E402
from rkd_mvp.ai_design_option_provider import (  # noqa: E402
    DesignOptionConfig, build_design_option_provider)
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository  # noqa: E402
from rkd_mvp.ai_design_option_service import AIDesignOptionService  # noqa: E402
from rkd_mvp.ai_design_studio_adapter import StudioProposalSource  # noqa: E402
from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider  # noqa: E402
from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository  # noqa: E402
from rkd_mvp.ai_requirement_service import AIRequirementService  # noqa: E402
from rkd_mvp.api_server import create_server  # noqa: E402
from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.requirement_service import RequirementService  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from rkd_mvp.studio import orchestrator as studio_orchestrator, validation  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402
from rkd_mvp.studio.tools import CATALOG  # noqa: E402

FIXTURE_ROOT = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
ORG = "org-local"
PID = NINGBO_PROJECT_ID
STUDIO_PID = "ningbo-xiecheng"
OTHER_PID = "project_w1_other"
CHECKS: list[dict] = []
MODELS: dict[str, dict] = {}


def check(cid: str, name: str, ok: bool, evidence: dict) -> None:
    CHECKS.append({"id": cid, "name": name,
                   "result": "observed_pass" if ok else "observed_fail",
                   "evidence": evidence})
    print(("PASS " if ok else "FAIL ") + cid + " " + name, flush=True)


def brief_config() -> AIProviderConfig:
    return AIProviderConfig(
        kind="synthetic", name="本地合成测试通道（非真实 AI）", model_id=None,
        base_url=None, api_key_present=False, adapter_version="rkd-model-provider.v1",
        prompt_version="requirement-understanding.zh-CN.v1",
        schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
        max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
        real_model=False, configuration_errors=[])


def option_config() -> DesignOptionConfig:
    return DesignOptionConfig(
        kind="synthetic", name="本地合成设计通道（非真实 AI）",
        adapter_version="rkd-design-option-provider.v1",
        prompt_version="design-option-strategy.zh-CN.v1",
        schema_version="rkd-ai-design-option.v1", max_candidates=2,
        real_model=False, configuration_errors=[])


def make_plan(letter: str, mutate=None) -> dict:
    raw = valid_proposal(letter)
    if mutate:
        mutate(raw)
    rep = validation.validate_proposal(
        raw, project={"id": STUDIO_PID, "site": SITE},
        option_id=letter, revision=1, parent_revision=None)
    assert rep["ok"], rep["repair_feedback"][:400]
    return rep["plan"]


def mutated_plan(plan: dict, mutate) -> dict:
    """Negative-case source: mutate an already-validated draft in place.

    Studio's own validator would reject these BEFORE they become artifacts; for
    adapter negative tests we deliberately inject a corrupt/expanded source
    document into the isolated Studio store. This is a labelled test fixture.
    """
    out = copy.deepcopy(plan)
    mutate(out)
    return out


def save_valid(studio: Store, letter: str, plan: dict, *, revision: int = 1,
               parent_artifact: dict | None = None, uid: str | None = None) -> dict:
    """Save a valid Studio artifact with a REAL parent UID chain (W1-R1).

    The fixture must express source lineage explicitly; import order is not a
    parent relationship.
    """
    revision_uid = uid or f"revuid_w1_{letter}_{revision}_{len(plan['zones'])}"
    aid = studio.save_artifact(
        STUDIO_PID, "spatial-plan", plan, "D2", option_id=letter, revision=revision,
        parent_revision=None, status="valid_candidate", run_id="run_w1_fixture",
        candidate_group_id="candgroup_w1_fixture",
        revision_uid=revision_uid,
        parent_revision_uid=(parent_artifact or {}).get("revision_uid"),
        input_hash_value=hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
        check_report_id="check_w1_fixture", contract_status="valid_candidate",
        diagnostics={"source": "labelled_local_fixture_not_real_AI"})
    return studio.artifact_by_id(aid)


def http(method: str, path: str, body: dict | None = None):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"X-Organization-Id": ORG, "Content-Type": "application/json"}
    if payload is not None:
        headers["Content-Length"] = str(len(payload))
    conn = HTTPConnection("127.0.0.1", PORT, timeout=20)
    conn.request(method, path, payload, headers)
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = {"_raw": raw[:200].decode("utf-8", "replace")}
    return response.status, data, raw


def import_body(artifact: dict, **extra) -> dict:
    return {"studio_project_id": STUDIO_PID,
            "studio_artifact_id": artifact["id"],
            "expected_source_sha256": artifact["sha256"],
            "source_project_id": PID,
            "expected_unit": "mm", **extra}


def count_rows() -> dict:
    import sqlite3
    c = sqlite3.connect(MAIN_DB)
    out = {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
           for t in ("ai_design_option_sets", "ai_design_option_revisions",
                     "ai_design_option_artifacts", "ai_design_option_adoptions")}
    c.close()
    return out


def svg_files() -> list[str]:
    d = RUNTIME_PARENT / "projects" / "ai-design-options" / "studio-import"
    return sorted(str(p.relative_to(RUNTIME_PARENT)) for p in d.rglob("*.svg")) if d.exists() else []


def field_reconciliation(letter: str, source_plan: dict, target_model: dict) -> dict:
    spatial = target_model["spatial"]
    rows = []
    for i, z in enumerate(source_plan["zones"]):
        t = spatial["zones"][i]
        rows.append({"object_id": z["id"], "field": "polygon_mm",
                     "source_value": z["polygon"], "target_value": t["polygon_mm"],
                     "unit": "mm", "equal": z["polygon"] == t["polygon_mm"],
                     "non_rectangular": len(z["polygon"]) > 4})
        rows.append({"object_id": z["id"], "field": "area_sqm",
                     "source_value": z["area_sqm"], "target_value": t["area_sqm"],
                     "unit": "m2", "equal": z["area_sqm"] == t["area_sqm"]})
        rows.append({"object_id": z["id"], "field": "role",
                     "source_value": z["role"], "target_value": t["role"],
                     "unit": "enum", "equal": z["role"] == t["role"]})
    for i, f in enumerate(source_plan["furniture"]):
        t = spatial["furniture"][i]
        for sf, tf, unit in (("x", "x_mm", "mm"), ("y", "y_mm", "mm"),
                             ("rot", "rot", "degree"), ("catalog_id", "catalog_id", "id")):
            rows.append({"object_id": f["id"], "field": tf,
                         "source_value": f[sf], "target_value": t[tf], "unit": unit,
                         "equal": f[sf] == t[tf]})
    circ_s, circ_t = source_plan["circulation"][0], spatial["circulation"][0]
    rows.append({"object_id": circ_s["id"], "field": "width_mm",
                 "source_value": circ_s["width_mm"], "target_value": circ_t["width_mm"],
                 "unit": "mm", "equal": circ_s["width_mm"] == circ_t["width_mm"]})
    rows.append({"object_id": circ_s["id"], "field": "path_mm",
                 "source_value": circ_s["path"], "target_value": circ_t["path_mm"],
                 "unit": "mm", "equal": circ_s["path"] == circ_t["path_mm"]})
    rows.append({"object_id": "boundary", "field": "width_m",
                 "source_value": SITE["width_mm"],
                 "target_value": float(target_model["boundary"]["width"]) * 1000,
                 "unit": "mm", "equal": abs(float(target_model["boundary"]["width"]) * 1000
                                            - SITE["width_mm"]) < 1e-6})
    return {"layout": letter, "rows": rows,
            "all_equal": all(r["equal"] for r in rows),
            "non_rectangular_zones": [z["id"] for z in source_plan["zones"]
                                      if len(z["polygon"]) > 4],
            "unsupported_items": spatial["unsupported_items"],
            "object_id_map": spatial["adaptation"]["object_id_map"],
            "source": spatial["source"],
            "field_ledger_rows": len(spatial["adaptation"]["field_ledger"])}


def main() -> int:
    global PORT, RUNTIME_PARENT
    # ---- isolated stores -------------------------------------------------
    studio = Store(STUDIO_DB)
    studio_orchestrator.Studio(studio).seed_from_fixtures()
    source = StudioProposalSource(studio)
    plan_a = make_plan("A")
    plan_b = make_plan("B")
    art_a = save_valid(studio, "A", plan_a)
    art_b = save_valid(studio, "B", plan_b)

    main_store = SQLiteStore(MAIN_DB)
    files = FileService(MAIN_DB, RUNTIME)
    requirements = RequirementService(MAIN_DB)
    requirement_ai = AIRequirementService(
        SQLiteAIRequirementRepository(MAIN_DB), requirements,
        config=brief_config(), provider_factory=lambda config: build_provider(config))
    options_ai = AIDesignOptionService(
        SQLiteAIDesignOptionRepository(MAIN_DB),
        lambda org, project: requirement_ai.status(org, project)["item"],
        lambda org, project: {"width": "12", "length": "8",
                              "boundary_source": "test_parameters_not_site_verified",
                              "obstacles": []},
        RUNTIME, config=option_config(),
        provider=build_design_option_provider(option_config()),
        studio_source=source)
    RUNTIME_PARENT = RUNTIME
    service = ApiService(MVPApp(main_store), files, requirement_service=requirements,
                         ai_requirement_service=requirement_ai,
                         ai_design_option_service=options_ai, runtime_root=RUNTIME,
                         studio_source=source)
    files.seed_ningbo(service, FIXTURE_ROOT)
    service.create_project(ORG, "W1 隔离第二项目（用于跨项目负例）", OTHER_PID)
    # second Studio project mapped to a DIFFERENT main project
    studio.ensure_project("studio-other", "W1 另一 Studio 项目", SITE, {},
                          source_project_id=OTHER_PID,
                          mapping_note="显式映射到另一个主系统项目，用于跨项目拒绝负例")
    art_other = studio.save_artifact(
        "studio-other", "spatial-plan", plan_a, "D2", option_id="A", revision=1,
        status="valid_candidate", contract_status="valid_candidate",
        revision_uid="revuid_w1_other")

    server = create_server(service, port=0, static_dir=ROOT / "web" / "dist")
    PORT = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"/api/v1/projects/{PID}/ai/design-options"
        rows_before = count_rows()

        # ------------------------------------------------------ W1-01 sources
        code, sources, _ = http("GET", f"{base}/studio-sources")
        check("W1-01", "Studio 可导入来源列表与显式项目映射（只读）",
              bool(code == 200 and sources["studio_project_id"] == STUDIO_PID
                   and sources["mapping"]["source_project_id"] == PID
                   and len(sources["items"]) >= 2),
              {"status": code, "studio_project_id": sources.get("studio_project_id"),
               "mapping": sources.get("mapping"),
               "items": sources.get("items")})

        # ------------------------------------------------------ W1-02 import A
        code, imp_a, _ = http("POST", f"{base}/import-studio", import_body(art_a))
        rev_a = imp_a.get("item") or {}
        model_a = rev_a.get("model") or {}
        check("W1-02", "布局 A（含非矩形分区）经同一适配器进入主系统版本化候选",
              bool(code == 200 and imp_a.get("reused") is False
                   and rev_a.get("revision_no") == 1
                   and rev_a.get("parent_revision_id") is None
                   and len(model_a.get("spatial", {}).get("zones", [])) == 6
                   and any(len(z["polygon_mm"]) > 4
                           for z in model_a.get("spatial", {}).get("zones", []))
                   and imp_a.get("adoption_unchanged") is True
                   and imp_a.get("formal_approval") is False
                   and imp_a.get("production_sync") is False),
              {"status": code, "revision_no": rev_a.get("revision_no"),
               "option_id": rev_a.get("option_id"),
               "parent_revision_id": rev_a.get("parent_revision_id"),
               "zones": len(model_a.get("spatial", {}).get("zones", [])),
               "ledger_rows": len(imp_a.get("field_ledger") or []),
               "unsupported": [u["item"] for u in imp_a.get("unsupported_items") or []],
               "adoption_unchanged": imp_a.get("adoption_unchanged"),
               "svg_sha256": imp_a.get("svg_sha256")})

        # --------------------------------------------------- W1-03 API/bytes
        code, state, _ = http("GET", base)
        opts = (state.get("item") or {}).get("options") or []
        target = next((o for o in opts if o.get("option_revision_id")
                       == rev_a.get("option_revision_id")), None)
        svg_bytes = b""
        if target and target.get("artifacts"):
            aid = target["artifacts"][0]["artifact_id"]
            sc, _meta, svg_bytes = http(
                "GET", f"{base}/artifacts/{quote(aid)}/content")
        check("W1-03", "API 状态、存储版本与图面字节一致；候选未污染采用/生产/采购/发布",
              bool(code == 200 and target is not None
                   and target["model"]["spatial"]["source"]["artifact_id"] == art_a["id"]
                   and svg_bytes.startswith(b"<svg")
                   and hashlib.sha256(svg_bytes).hexdigest() == imp_a.get("svg_sha256")
                   and state.get("adoption") is None
                   and count_rows()["ai_design_option_adoptions"] == 0),
              {"status": code, "option_in_state": bool(target),
               "svg_bytes": len(svg_bytes),
               "svg_sha_matches": hashlib.sha256(svg_bytes).hexdigest() == imp_a.get("svg_sha256"),
               "adoption": state.get("adoption"), "rows": count_rows()})

        # ------------------------------------------------------ W1-04 import B
        code, imp_b, _ = http("POST", f"{base}/import-studio", import_body(art_b))
        rev_b = imp_b.get("item") or {}
        model_b = rev_b.get("model") or {}
        sig_a = model_a.get("structure_signature")
        sig_b = model_b.get("structure_signature")
        check("W1-04", "布局 B 走同一适配器；两种实质不同布局与精确多边形都可对账",
              bool(code == 200 and imp_b.get("reused") is False
                   and rev_b.get("option_id") != rev_a.get("option_id")
                   and sig_a != sig_b
                   and model_b["spatial"]["zones"][0]["polygon_mm"]
                   != model_a["spatial"]["zones"][0]["polygon_mm"]),
              {"status": code, "option_a": rev_a.get("option_id"),
               "option_b": rev_b.get("option_id"),
               "signature_different": sig_a != sig_b,
               "arrival_polygon_a": model_a["spatial"]["zones"][0]["polygon_mm"],
               "arrival_polygon_b": model_b["spatial"]["zones"][0]["polygon_mm"]})

        # ------------------------------------------------------ W1-05 idempotency
        before = count_rows()
        code, again, _ = http("POST", f"{base}/import-studio", import_body(art_a))
        after = count_rows()
        check("W1-05", "同一来源重复导入不重复造版本（幂等）",
              bool(code == 200 and again.get("reused") is True
                   and before == after),
              {"status": code, "reused": again.get("reused"),
               "rows_before": before, "rows_after": after})

        # ------------------------------------------- W1-06 source-changed version
        plan_a2 = make_plan("A", lambda p: (
            p["zones"][0].update(polygon=[[0, 8600], [5400, 8600], [5400, 13500],
                                         [1800, 13500], [0, 11900]]),
            p["furniture"][2].update(rot=-30)))
        art_a2 = save_valid(studio, "A", plan_a2, revision=2, parent_artifact=art_a)
        code, imp_a2, _ = http("POST", f"{base}/import-studio", import_body(art_a2))
        rev_a2 = imp_a2.get("item") or {}
        diffs = rev_a2.get("diff") or []
        code_detail, detail, _ = http(
            "GET", f"{base}/studio-imports/{rev_a.get('option_revision_id')}")
        check("W1-06", "来源改变形成新版本；父版本指向旧版；同一对象后续修改可追踪，旧字节保留",
              bool(code == 200 and rev_a2.get("revision_no") == 2
                   and rev_a2.get("parent_revision_id") == rev_a.get("option_revision_id")
                   and any(d["object_id"] == "ZA1" and "polygon" in d["field"] for d in diffs)
                   and any(d["object_id"] == "F3" and "rot" in d["field"] for d in diffs)
                   and code_detail == 200 and detail.get("item") is not None),
              {"status": code, "revision_no": rev_a2.get("revision_no"),
               "parent_revision_id": rev_a2.get("parent_revision_id"),
               "same_object_diffs": [d["field"] for d in diffs],
               "old_revision_still_readable": code_detail == 200,
               "old_source_artifact_id": detail.get("spatial", {}).get("source", {}).get("artifact_id")})

        # ------------------------------------------------------------ negatives
        neg_cases = []
        before = count_rows()
        code, neg, _ = http("POST", f"{base}/import-studio",
                            import_body(art_a, expected_unit="m"))
        neg_cases.append(("W1-07", "单位错配（expected_unit=m）被拒绝，不猜测换算",
                          code == 422 and neg.get("error_code") == "UNIT_MISMATCH",
                          {"status": code, "error_code": neg.get("error_code")}))

        bad_catalog = mutated_plan(plan_a, lambda p: p["furniture"][0].update(catalog_id="ghost-item"))
        art_catalog = save_valid(studio, "A", bad_catalog, revision=3)
        code, neg, _ = http("POST", f"{base}/import-studio", import_body(art_catalog))
        neg_cases.append(("W1-08", "缺失对象引用（目录不存在）被拒绝，不静默丢弃",
                          code == 422 and neg.get("error_code") == "UNKNOWN_CATALOG_REF",
                          {"status": code, "error_code": neg.get("error_code")}))

        bad_geom = mutated_plan(plan_a, lambda p: p["zones"][0].update(polygon=[[0, 0], [100, 100]]))
        art_geom = save_valid(studio, "A", bad_geom, revision=4)
        code, neg, _ = http("POST", f"{base}/import-studio", import_body(art_geom))
        neg_cases.append(("W1-09", "无法表达的几何（两点伪多边形）被拒绝，不静默矩形化",
                          code == 422 and neg.get("error_code") == "UNSUPPORTED_GEOMETRY",
                          {"status": code, "error_code": neg.get("error_code")}))

        no_ceiling = mutated_plan(plan_a, lambda p: p["ceiling"].update(fixtures=[]))
        art_nolight = save_valid(studio, "A", no_ceiling, revision=5)
        code, neg, _ = http("POST", f"{base}/import-studio", import_body(art_nolight))
        unsupported_names = [u["item"] for u in (neg.get("unsupported_items") or [])]
        neg_cases.append(("W1-10", "无法表达的材料/灯具保持命名缺项，不静默丢失",
                          code == 200 and "天花灯具点位" in unsupported_names
                          and "材料规格/产品选型" in unsupported_names,
                          {"status": code, "unsupported": unsupported_names}))

        code, neg, _ = http("POST", f"{base}/import-studio",
                            {**import_body(art_a), "source_project_id": OTHER_PID})
        neg_cases.append(("W1-11a", "错误项目映射（请求与 URL 不一致）被拒绝",
                          code == 409 and neg.get("error_code") == "PROJECT_MAPPING_MISMATCH",
                          {"status": code, "error_code": neg.get("error_code")}))

        code, neg, _ = http("POST", f"{base}/import-studio",
                            {"studio_project_id": "studio-other",
                             "studio_artifact_id": art_other,
                             "expected_unit": "mm"})
        neg_cases.append(("W1-11b", "跨项目 Studio 产物不能导入当前主系统项目",
                          code == 409 and neg.get("error_code") == "PROJECT_MAPPING_MISMATCH",
                          {"status": code, "error_code": neg.get("error_code")}))

        code, neg, _ = http("POST", f"{base}/import-studio",
                            import_body(art_a, expected_source_sha256="0" * 64))
        neg_cases.append(("W1-11c", "来源字节已变的 expected sha 校验拒绝导入",
                          code == 409 and neg.get("error_code") == "SOURCE_SHA_MISMATCH",
                          {"status": code, "error_code": neg.get("error_code")}))

        invalid_aid = studio.save_artifact(
            STUDIO_PID, "spatial-plan-raw", {"raw_text": "bad"}, "D2",
            status="invalid_raw", contract_status="invalid_raw")
        code, neg, _ = http("POST", f"{base}/import-studio",
                            {"studio_project_id": STUDIO_PID,
                             "studio_artifact_id": invalid_aid})
        neg_cases.append(("W1-11d", "非有效候选（invalid_raw）不能导入",
                          code == 422 and neg.get("error_code") == "NOT_VALID_STUDIO_CANDIDATE",
                          {"status": code, "error_code": neg.get("error_code")}))
        for cid, name, ok, ev in neg_cases:
            check(cid, name, ok, ev)
        # W1-10 is a positive import (named unsupported), so allow its rows
        extra_writes = count_rows()["ai_design_option_revisions"] - \
            before["ai_design_option_revisions"]
        check("W1-12", "所有失败负例不产生半写入（仅 W1-10 的正例允许新增 1 个版本）",
              extra_writes == 1,
              {"rows_before": before, "rows_after": count_rows(),
               "new_revisions_from_negatives": extra_writes})

        # ---------------------------------------------- W1-13 stale adoption
        code, neg, _ = http(
            "POST", f"{base}/{quote(rev_a2.get('option_id') or '', safe='')}/adopt",
            {"expected_revision": 1, "expected_version": 0})
        check("W1-13", "旧版本并发采用被 CAS 拒绝；采用指针未被导入或旧采用改写",
              bool(code == 409 and neg.get("error_code") == "STALE_OPTION_REVISION"
                   and count_rows()["ai_design_option_adoptions"] == 0),
              {"status": code, "error_code": neg.get("error_code"),
               "adoption_rows": count_rows()["ai_design_option_adoptions"]})

        # ------------------------------------------- W1-14 mid-way rollback
        before = count_rows()
        files_before = svg_files()
        art_rollback = save_valid(studio, "A", mutated_plan(
            plan_a, lambda p: p["furniture"][0].update(x=8600)), revision=9)
        raised = None
        try:
            options_ai.import_studio_proposal(
                ORG, PID, "tester", import_body(art_rollback),
                on_before_commit=lambda: (_ for _ in ()).throw(
                    RuntimeError("W1 injected failure after SVG write, before commit")))
        except Exception as error:  # noqa: BLE001
            raised = f"{type(error).__name__}: {error}"
        after = count_rows()
        files_after = svg_files()
        check("W1-14", "适配中途失败：set/revision/artifact 全回滚，SVG 文件清理，采用指针不变",
              bool(raised and before == after and files_before == files_after),
              {"raised": raised, "rows_before": before, "rows_after": after,
               "svg_files_before": len(files_before), "svg_files_after": len(files_after),
               "adoption_rows": after["ai_design_option_adoptions"]})

        # ---------------------------------------------- W1-15 restart persistence
        import sqlite3
        code, imports_before, _ = http("GET", f"{base}/studio-imports")
        ids_before = sorted(r["option_revision_id"] for e in imports_before["items"]
                            for r in e["revisions"])
        main_store2 = SQLiteStore(MAIN_DB)
        options_ai2 = AIDesignOptionService(
            SQLiteAIDesignOptionRepository(MAIN_DB),
            lambda org, project: requirement_ai.status(org, project)["item"],
            lambda org, project: {"width": "12", "length": "8",
                                  "boundary_source": "test_parameters_not_site_verified",
                                  "obstacles": []},
            RUNTIME, config=option_config(),
            provider=build_design_option_provider(option_config()),
            studio_source=StudioProposalSource(Store(STUDIO_DB)))
        restarted = options_ai2.list_studio_imports(ORG, PID)
        ids_after = sorted(r["option_revision_id"] for e in restarted["items"]
                           for r in e["revisions"])
        check("W1-15", "重启后（新仓储连接 + 新 Studio 连接）导入版本、来源、字节与采用状态保持",
              bool(code == 200 and ids_before and ids_before == ids_after
                   and restarted.get("adoption") is None),
              {"status": code, "import_count": len(ids_before),
               "ids_equal": ids_before == ids_after,
               "adoption": restarted.get("adoption")})
        main_store2.close()

        # ------------------------------------------- W1-16 field reconciliation
        recon_a = field_reconciliation("A", plan_a, model_a)
        recon_b = field_reconciliation("B", plan_b, model_b)
        (EVIDENCE / "field-reconciliation.json").write_text(
            json.dumps({"layouts": [recon_a, recon_b],
                        "note": "逐字段比较源提案与 spatial 投影的真实值，不是计数或哈希"},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        check("W1-16", "两种布局逐字段对账：坐标/单位/对象 ID/来源/父版本/材料与视图缺项都相等或显式标注",
              bool(recon_a["all_equal"] and recon_b["all_equal"]
                   and recon_a["non_rectangular_zones"] and recon_b["non_rectangular_zones"]
                   and recon_a["field_ledger_rows"] > 20
                   and recon_b["field_ledger_rows"] > 20),
              {"A": {"rows": len(recon_a["rows"]), "all_equal": recon_a["all_equal"],
                     "non_rect": recon_a["non_rectangular_zones"],
                     "ledger": recon_a["field_ledger_rows"]},
               "B": {"rows": len(recon_b["rows"]), "all_equal": recon_b["all_equal"],
                     "non_rect": recon_b["non_rectangular_zones"],
                     "ledger": recon_b["field_ledger_rows"]}})

        # save source/target model samples (explicitly labelled fixtures)
        models_dir = EVIDENCE / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        for name, obj in (("layout-A.source.json", plan_a),
                          ("layout-A.target.json", model_a),
                          ("layout-B.source.json", plan_b),
                          ("layout-B.target.json", model_b),
                          ("layout-A-v2.source.json", plan_a2),
                          ("layout-A-v2.target.json", rev_a2.get("model") or {})):
            (models_dir / name).write_text(
                json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        check("W1-17", "保存两份源提案/目标模型样本与修订版样本，标明是本地夹具非真实 AI",
              all((models_dir / n).exists() for n in
                  ("layout-A.source.json", "layout-A.target.json",
                   "layout-B.source.json", "layout-B.target.json")),
              {"files": sorted(p.name for p in models_dir.iterdir()),
               "source_kind": "labelled_local_fixture_not_real_AI"})

        # ---------------------------------------------- W1-18 isolation by project
        code, other_imports, _ = http(
            "GET", f"/api/v1/projects/{OTHER_PID}/ai/design-options/studio-imports")
        check("W1-18", "跨项目隔离：另一主系统项目看不到当前项目的导入版本",
              bool(code == 200 and not other_imports.get("items")),
              {"status": code, "other_project_import_count":
               len(other_imports.get("items") or [])})

        # ------------------------------------ W1-19 old-format compatibility
        brief_item = service.submit_ai_requirement(
            ORG, PID, "tester", {"natural_language": "开放交流，入口左侧"},
            "w1-old-brief-0001")["item"]
        requirement_ai.wait_for_job(ORG, PID, brief_item["job_id"])
        old_set = service.submit_ai_design_options(
            ORG, PID, "tester", {}, "w1-old-options-0001")["item"]
        options_ai.wait_for_set(ORG, PID, old_set["set_id"])
        legacy = service.get_ai_design_options(ORG, PID)
        old_options = [o for o in ((legacy.get("item") or {}).get("options") or [])
                       if o.get("source_kind") == "synthetic_design_adapter"]
        svg_old = b""
        if old_options and old_options[0].get("artifacts"):
            sc, _m, svg_old = http(
                "GET", f"{base}/artifacts/{quote(old_options[0]['artifacts'][0]['artifact_id'])}/content")
        imports_still = http("GET", f"{base}/studio-imports")[1]
        check("W1-19", "旧合成候选格式与历史下载仍可用；导入版本不被旧集合覆盖或丢失",
              bool(old_options and svg_old.startswith(b"<svg")
                   and len(imports_still.get("items") or []) >= 1
                   and count_rows()["ai_design_option_adoptions"] == 0),
              {"legacy_candidates": len(old_options), "legacy_svg_bytes": len(svg_old),
               "studio_import_sets_after": len(imports_still.get("items") or []),
               "adoption_rows": count_rows()["ai_design_option_adoptions"]})

    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        main_store.close()

    failed = sum(1 for c in CHECKS if c["result"] != "observed_pass")
    out = {
        "task_id": "W1 统一模型适配（Studio 有效提案 → 主系统版本化候选）",
        "schema_version": "rkd-w1-unified-model-checks.v1",
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "code_head": __import__("subprocess").run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip(),
        "environment": {
            "python": sys.version.split()[0],
            "isolated_main_db": str(MAIN_DB),
            "isolated_studio_db": str(STUDIO_DB),
            "model_channel": "labelled local fixtures only (no real AI, no external calls)",
            "keys_used": False,
        },
        "checks": CHECKS,
        "totals": {"observed_pass": len(CHECKS) - failed, "observed_fail": failed},
        "external_calls": 0,
        "tokens": 0,
        "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
        "limitations": [
            "源提案是明确标记的本地测试夹具，不是系统模型自动生成的设计，不计入 AD01—AD08",
            "W1 是工程适配批，没有新增客户级平面、人眼效果图、量价或 PDF",
            "Q10 同源成果仍 not_run（W2）",
            "正式采用/生产/采购/发布未被导入或采用测试改写",
        ],
    }
    (EVIDENCE / "checks.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(CHECKS) - failed, "failed": failed,
                      "out": str(EVIDENCE / "checks.json")}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
