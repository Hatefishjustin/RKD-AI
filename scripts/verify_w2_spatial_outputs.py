"""W2 同源成果切片验收：两种布局、净量/成本、四种变更、下载字节与页面。

用法：python scripts/verify_w2_spatial_outputs.py --out <dir> --runtime <dir>
0 外部模型调用；渲染用本机 Blender（Cycles CPU），源是明确标记的本地夹具。
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _arg(flag: str, default: Path) -> Path:
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).resolve()
        if a.startswith(flag + "="):
            return Path(a.split("=", 1)[1]).resolve()
    return default


EVIDENCE = _arg("--out", ROOT / "var/evidence/roadmap/W2-同源成果切片/after")
RUNTIME = _arg("--runtime", ROOT / "var/evidence/roadmap/W2-同源成果切片/runtime")
EVIDENCE.mkdir(parents=True, exist_ok=True)
RUNTIME.mkdir(parents=True, exist_ok=True)
MAIN_DB = RUNTIME / "app.sqlite3"
STUDIO_DB = RUNTIME / "studio.db"
for f in (MAIN_DB, STUDIO_DB):
    if f.exists():
        f.unlink()

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
from rkd_mvp.ai_spatial_output_service import AISpatialOutputService  # noqa: E402
from rkd_mvp.ai_spatial_outputs import (  # noqa: E402
    build_package, derive_camera, sha256_bytes)
from rkd_mvp.api_server import create_server  # noqa: E402
from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.requirement_service import RequirementService  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from rkd_mvp.studio import orchestrator, validation  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402
from rkd_mvp.studio.tools import CATALOG  # noqa: E402

FIXTURE_ROOT = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
ORG = "org-local"
PID = NINGBO_PROJECT_ID
SPID = "ningbo-xiecheng"
CHECKS: list[dict] = []


def check(cid, name, ok, evidence):
    CHECKS.append({"id": cid, "name": name,
                   "result": "observed_pass" if ok else "observed_fail",
                   "evidence": evidence})
    print(("PASS " if ok else "FAIL ") + cid + " " + name, flush=True)


def http(method, path, body=None, extra=None):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"X-Organization-Id": ORG, "Content-Type": "application/json"}
    headers.update(extra or {})
    if payload is not None:
        headers["Content-Length"] = str(len(payload))
    conn = HTTPConnection("127.0.0.1", PORT, timeout=120)
    conn.request(method, path, payload, headers)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = {"_raw": raw[:200].decode("utf-8", "replace")}
    return resp.status, data, raw


def main() -> int:
    global PORT
    studio = Store(STUDIO_DB)
    orchestrator.Studio(studio).seed_from_fixtures()
    source = StudioProposalSource(studio)
    arts = {}
    for letter in ("A", "B"):
        rep = validation.validate_proposal(
            valid_proposal(letter), project={"id": SPID, "site": SITE},
            option_id=letter, revision=1, parent_revision=None)
        assert rep["ok"], rep["repair_feedback"][:300]
        aid = studio.save_artifact(
            SPID, "spatial-plan", rep["plan"], "D2", option_id=letter, revision=1,
            status="valid_candidate", contract_status="valid_candidate",
            revision_uid=f"uid-w2-{letter}", run_id=f"run-w2-{letter}",
            candidate_group_id=f"group-w2-{letter}",
            input_hash_value=hashlib.sha256(json.dumps(rep["plan"], sort_keys=True).encode()).hexdigest(),
            check_report_id=f"check-w2-{letter}",
            diagnostics={"source": "labelled_local_fixture"})
        arts[letter] = studio.artifact_by_id(aid)

    main_store = SQLiteStore(MAIN_DB)
    files = FileService(MAIN_DB, RUNTIME)
    requirements = RequirementService(MAIN_DB)
    brief_config = AIProviderConfig(
        kind="synthetic", name="本地合成测试通道（非真实 AI）", model_id=None,
        base_url=None, api_key_present=False, adapter_version="rkd-model-provider.v1",
        prompt_version="requirement-understanding.zh-CN.v1",
        schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
        max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
        real_model=False, configuration_errors=[])
    option_config = DesignOptionConfig(
        kind="synthetic", name="本地合成设计通道（非真实 AI）",
        adapter_version="rkd-design-option-provider.v1",
        prompt_version="design-option-strategy.zh-CN.v1",
        schema_version="rkd-ai-design-option.v1", max_candidates=2,
        real_model=False, configuration_errors=[])
    requirement_ai = AIRequirementService(
        SQLiteAIRequirementRepository(MAIN_DB), requirements, config=brief_config,
        provider_factory=lambda config: build_provider(config))
    options_ai = AIDesignOptionService(
        SQLiteAIDesignOptionRepository(MAIN_DB),
        lambda org, project: requirement_ai.status(org, project)["item"],
        lambda org, project: {"width": "12", "length": "8",
                              "boundary_source": "test_parameters_not_site_verified",
                              "obstacles": []},
        RUNTIME, config=option_config,
        provider=build_design_option_provider(option_config), studio_source=source)
    spatial_ai = AISpatialOutputService(
        __import__("rkd_mvp.ai_development_repository", fromlist=["SQLiteAIDevelopmentRepository"])
        .SQLiteAIDevelopmentRepository(MAIN_DB), options_ai, RUNTIME, start_workers=False)
    service = ApiService(MVPApp(main_store), files, requirement_service=requirements,
                         ai_requirement_service=requirement_ai,
                         ai_design_option_service=options_ai,
                         ai_spatial_output_service=spatial_ai, runtime_root=RUNTIME,
                         studio_source=source)
    files.seed_ningbo(service, FIXTURE_ROOT)

    server = create_server(service, port=0, static_dir=ROOT / "web" / "dist")
    PORT = server.server_port
    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"/api/v1/projects/{PID}/ai"
    models = {}
    revisions = {}
    try:
        # import + adopt A, then generate
        code, imp, _ = http("POST", f"{base}/design-options/import-studio",
                            {"studio_project_id": SPID, "studio_artifact_id": arts["A"]["id"],
                             "expected_source_sha256": arts["A"]["sha256"], "expected_unit": "mm"})
        assert code == 200, imp
        rev_a = imp["item"]
        http("POST", f"{base}/design-options/{rev_a['option_id']}/adopt",
             {"expected_revision": rev_a["revision_no"], "expected_version": 0})
        models["A"] = rev_a["model"]
        code, gen_a, _ = http("POST", f"{base}/spatial-outputs",
                              {"option_revision_id": rev_a["option_revision_id"],
                               "settings": {"render": True, "width": 960, "height": 600,
                                            "samples": 24}},
                              {"Idempotency-Key": "w2-outputs-A-0001"})
        st_a = http("GET", f"{base}/spatial-outputs")[1]
        jobs = [j for j in st_a.get("jobs") or [] if j["job_id"] == gen_a["item"]["job_id"]]
        job_a = jobs[0] if jobs else gen_a["item"]
        check("W2-01", "一个冻结的精确模型修订生成同源成果（平面/净量/成本/清单/包）",
              bool(code == 202 and job_a["status"] == "succeeded"
                   and st_a["revision"] and st_a["artifacts"]),
              {"status": code, "job_status": job_a["status"],
               "job_error": job_a.get("error_code"),
               "artifacts": [a["filename"] for a in st_a.get("artifacts") or []]})
        revision_a = st_a["revision"]

        # downloads + sha
        files_ok = {}
        for name in ("plan.svg", "render.png", "quantity.csv", "cost.html",
                     "manifest.json", "package.zip"):
            sc, meta, raw = http("GET", f"{base}/spatial-outputs/"
                                  f"{revision_a['production_revision_id']}/files/{name}")
            files_ok[name] = {"status": sc, "bytes": len(raw),
                              "sha": hashlib.sha256(raw).hexdigest()[:12]}
        manifest = json.loads(http("GET", f"{base}/spatial-outputs/"
                                    f"{revision_a['production_revision_id']}/files/manifest.json")[2])
        zc = zipfile.ZipFile(io.BytesIO(http(
            "GET", f"{base}/spatial-outputs/{revision_a['production_revision_id']}"
                    f"/files/package.zip")[2]))
        zip_names = sorted(zc.namelist())
        check("W2-02", "下载逐文件可用：平面/效果图/量/成本/清单/包，清单登记 SHA 与字节一致",
              bool(all(v["status"] == 200 and v["bytes"] > 0 for v in files_ok.values())
                   and manifest["files"] and zip_names),
              {"files": files_ok, "zip_entries": zip_names,
               "manifest_file_count": len(manifest.get("files") or [])})

        # plan content
        plan_svg = http("GET", f"{base}/spatial-outputs/"
                         f"{revision_a['production_revision_id']}/files/plan.svg")[2].decode("utf-8")
        check("W2-03", "平面包含分区/面积表/图例/尺寸/机位与未建模缺项，且标注非施工图",
              bool(all(k in plan_svg for k in ("面积表", "图例", "总宽", "C1 人眼", "未建模",
                                               "不是施工图", "ZA1", "F1"))),
              {"has_area_table": "面积表" in plan_svg, "has_legend": "图例" in plan_svg,
               "has_dimension": "总宽" in plan_svg, "has_camera": "C1 人眼" in plan_svg,
               "has_missing": "未建模" in plan_svg, "bytes": len(plan_svg)})

        q = revision_a["quantities"]["items"]
        net = next(x for x in q if x["quantity_id"] == "Q-FLOOR-NET")
        check("W2-04", "非矩形净量独立复算一致；bbox 结果故意不同且不用于计量",
              bool(abs(net["independent_recompute_m2"] - net["value"]) < 0.01
                   and abs(net["bbox_delta_m2"]) > 0.2
                   and net["method"].startswith("exact")),
              {"net": net["value"], "independent": net["independent_recompute_m2"],
               "bbox": net["bbox_value_m2"], "bbox_delta": net["bbox_delta_m2"],
               "method": net["method"]})
        check("W2-05", "成本：没有价源时金额为 unknown、不是报价；量已知而钱未知",
              bool(revision_a["cost"]["known_items"] == []
                   and revision_a["cost"]["total_project_estimate"]["value"] is None
                   and revision_a["cost"]["formal_quote"] is False),
              {"known_items": revision_a["cost"]["known_items"],
               "total": revision_a["cost"]["total_project_estimate"],
               "unknown_count": len(revision_a["cost"]["unknown_items"])})

        # second layout through the same generator
        code, imp_b, _ = http("POST", f"{base}/design-options/import-studio",
                              {"studio_project_id": SPID, "studio_artifact_id": arts["B"]["id"],
                               "expected_source_sha256": arts["B"]["sha256"], "expected_unit": "mm"})
        rev_b = imp_b["item"]
        http("POST", f"{base}/design-options/{rev_b['option_id']}/adopt",
             {"expected_revision": rev_b["revision_no"], "expected_version": 1})
        code, gen_b, _ = http("POST", f"{base}/spatial-outputs",
                              {"option_revision_id": rev_b["option_revision_id"],
                               "settings": {"render": True, "width": 960, "height": 600,
                                            "samples": 24}},
                              {"Idempotency-Key": "w2-outputs-B-0001"})
        st_b = http("GET", f"{base}/spatial-outputs")[1]
        check("W2-06", "两种不同布局由同一生成器出平面与效果图（源/模型哈希/相机可查）",
              bool(code == 202 and st_b["revision"]
                   and st_b["revision"]["baseline"]["model_hash"]
                   != revision_a["baseline"]["model_hash"]
                   and st_b["revision"]["quantities"]["items"][2]["value"]
                   != net["value"]),
              {"layout_a_net": net["value"],
               "layout_b_net": st_b["revision"]["quantities"]["items"][2]["value"]
               if st_b["revision"] else None,
               "model_hashes": [revision_a["baseline"]["model_hash"][:12],
                                (st_b["revision"] or {}).get("baseline", {}).get("model_hash", "")[:12]],
               "cameras": [revision_a["view_mapping"]["camera"]["position_mm"],
                           (st_b["revision"] or {}).get("view_mapping", {}).get("camera", {}).get("position_mm")]})

        # four controlled changes at generator level (same frozen model copy)
        model_a = models["A"]
        base_pkg = build_package(model_a, project_id=PID, option_revision_id="x")
        # 1) geometry
        geo = copy.deepcopy(model_a)
        poly = geo["spatial"]["zones"][1]["polygon_mm"]
        geo["spatial"]["zones"][1]["polygon_mm"] = [
            [poly[0][0], poly[0][1]], [poly[1][0] - 800, poly[1][1]],
            [poly[2][0] - 800, poly[2][1]], [poly[3][0], poly[3][1]]]
        geo_pkg = build_package(geo, project_id=PID, option_revision_id="x")
        # 2) material
        mat = copy.deepcopy(model_a)
        for i, z in enumerate(mat["spatial"]["zones"]):
            z["finish_material"] = {"material_id": f"M{i+1}", "name": f"材料{i+1}",
                                    "hex": ["#c8a06a", "#9fb3c8", "#c9c2b6"][i % 3],
                                    "known_status": "assumption"}
        mat_pkg = build_package(mat, project_id=PID, option_revision_id="x")
        # 3) camera only
        cam2 = derive_camera(model_a)
        cam2["position_mm"] = [cam2["position_mm"][0] + 3000, cam2["position_mm"][1]]
        cam_pkg = build_package(model_a, project_id=PID, option_revision_id="x")
        from rkd_mvp.ai_spatial_outputs import build_plan_svg, build_scene
        cam_plan = build_plan_svg(model_a, cam2, base_pkg["quantities"])
        cam_scene = build_scene(model_a, cam2)
        # 4) price only
        price_low = build_package(model_a, project_id=PID, option_revision_id="x",
                                  settings={"floor_unit_price_cny": 1000})
        price_pkg = build_package(model_a, project_id=PID, option_revision_id="x",
                                  settings={"floor_unit_price_cny": 1200})
        q0 = base_pkg["quantities"]["items"]
        q1 = geo_pkg["quantities"]["items"]
        check("W2-07", "四种受控变更：几何改平面/三维/净量；材料改材质；只改相机不改量；只改单价不改几何",
              bool(base_pkg["plan"] != geo_pkg["plan"]
                   and base_pkg["scene"] != geo_pkg["scene"]
                   and next(x for x in q1 if x["quantity_id"] == "Q-FLOOR-NET")["value"]
                   != next(x for x in q0 if x["quantity_id"] == "Q-FLOOR-NET")["value"]
                   and base_pkg["plan"] != mat_pkg["plan"]
                   and base_pkg["scene"] != mat_pkg["scene"]
                   and next(x for x in mat_pkg["quantities"]["items"]
                            if x["quantity_id"] == "Q-FLOOR-NET")["value"]
                   == next(x for x in q0 if x["quantity_id"] == "Q-FLOOR-NET")["value"]
                   and cam_plan != base_pkg["plan"] and cam_scene != base_pkg["scene"]
                   and cam_pkg["quantities"] == base_pkg["quantities"]
                   and price_pkg["quantities"] == base_pkg["quantities"]
                   and price_pkg["plan"] == base_pkg["plan"]
                   and base_pkg["cost"]["known_items"] == []
                   and price_pkg["cost"]["known_items"][0]["amount_cny"]
                   > price_low["cost"]["known_items"][0]["amount_cny"]),
              {"geometry_net": [next(x for x in q0 if x["quantity_id"] == "Q-FLOOR-NET")["value"],
                                next(x for x in q1 if x["quantity_id"] == "Q-FLOOR-NET")["value"]],
               "material_plan_changed": base_pkg["plan"] != mat_pkg["plan"],
               "material_scene_changed": base_pkg["scene"] != mat_pkg["scene"],
               "camera_plan_changed": cam_plan != base_pkg["plan"],
               "camera_quantity_same": cam_pkg["quantities"] == base_pkg["quantities"],
               "price_quantity_same": price_pkg["quantities"] == base_pkg["quantities"],
               "price_plan_same": price_pkg["plan"] == base_pkg["plan"],
               "price_amounts": [(price_low["cost"]["known_items"] or [{}])[0].get("amount_cny"),
                                 (price_pkg["cost"]["known_items"] or [{}])[0].get("amount_cny")]})
    finally:
        server.shutdown(); server.server_close(); thread.join(3)
        main_store.close()

    failed = sum(1 for c in CHECKS if c["result"] != "observed_pass")
    out = {
        "task_id": "W2 同源成果切片",
        "schema_version": "rkd-w2-spatial-checks.v1",
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "code_head": __import__("subprocess").run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                                 capture_output=True, text=True).stdout.strip(),
        "environment": {"python": sys.version.split()[0], "renderer": "blender-4.2.9 Cycles CPU",
                        "isolated_main_db": str(MAIN_DB), "isolated_studio_db": str(STUDIO_DB),
                        "model_channel": "labelled local fixtures only", "keys_used": False},
        "checks": CHECKS, "totals": {"observed_pass": len(CHECKS) - failed, "observed_fail": failed},
        "external_calls": 0, "tokens": 0, "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
    }
    (EVIDENCE / "checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(json.dumps({"passed": len(CHECKS) - failed, "failed": failed,
                      "out": str(EVIDENCE / "checks.json")}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
