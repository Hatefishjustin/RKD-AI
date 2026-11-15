"""W2-R4 同源表达验收：两布局可读平面 + 各一张人眼内部评审图。

用法：
  PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/verify_w2_r4.py \
      --out var/evidence/roadmap/W2-R4-同源表达 --runtime var/evidence/roadmap/W2-R4-同源表达/runtime
  ... --no-render   # 只调试平面/场景/契约，不跑 Blender

真实隔离 SQLite + 真实回环 HTTP + 真实本机 Blender 4.2.9 Cycles CPU；
0 外部模型调用、0 密钥、0 费用。源是明确标记的本地夹具 + 人工测试假设表达层，
不计入 AI 接替设计，不代替用户对设计的判断。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import sys
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

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
    build_package, sha256_bytes)
from rkd_mvp.api_server import create_server  # noqa: E402
from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.requirement_service import RequirementService  # noqa: E402
from rkd_mvp.spatial_presentation import normalize_presentation  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from rkd_mvp.studio import orchestrator, validation  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402
from w2_r4_fixture_presentation import build_fixture_presentation  # noqa: E402

ORG = "org-local"
PID = NINGBO_PROJECT_ID
SPID = "ningbo-xiecheng"
FIXTURE_ROOT = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
CHECKS: list[dict] = []
PORT = 0


# 验证分层：函数级 / 真实 HTTP / 真实渲染 / 浏览器 / 人工目检 必须分列，
# 不能把 not_run 或 missing_evidence 混进 observed_fail 当作产品回归。
LAYER_MAP = {
    "R4-A-SUBMIT": "http", "R4-A-ZIP": "http", "R4-B-SUBMIT": "http", "R4-B-ZIP": "http",
    "R4-01": "http", "R4-02-A": "contract", "R4-02-B": "contract",
    "R4-03-A": "contract", "R4-03-B": "contract",
    "R4-04-A": "real_render", "R4-04-B": "real_render",
    "R4-05": "function_level", "R4-06": "external_evidence",
    "R4-07": "http", "R4-08": "http",
}


def check(cid: str, name: str, ok: bool, evidence: dict,
          *, result: str | None = None, layer: str | None = None) -> None:
    """result 可显式给 not_run / missing_evidence —— 两者都不得计为产品失败。"""
    status = result or ("observed_pass" if ok else "observed_fail")
    CHECKS.append({"id": cid, "name": name, "result": status,
                   "layer": layer or LAYER_MAP.get(cid, "contract"),
                   "evidence": evidence})
    label = {"observed_pass": "PASS", "observed_fail": "FAIL",
             "not_run": "NOT_RUN", "missing_evidence": "NO_EVIDENCE"}[status]
    print(f"{label:<11} {cid} {name}", flush=True)


def http(method: str, path: str, body=None, extra=None):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"X-Organization-Id": ORG, "Content-Type": "application/json"}
    headers.update(extra or {})
    if payload is not None:
        headers["Content-Length"] = str(len(payload))
    conn = HTTPConnection("127.0.0.1", PORT, timeout=900)
    conn.request(method, path, payload, headers)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = {"_raw": raw[:200].decode("utf-8", "replace")}
    return resp.status, data, raw


def make_finish_scope(model: dict, presentation: dict) -> dict:
    """材料面切片与 presentation 的材质映射同源；不同功能区几何互斥。"""
    role_to_mat = {role: mat for mat in presentation["materials"]
                   for role in mat["zone_roles"]}
    default = presentation["materials"][0]
    areas = []
    for zone in model["spatial"]["zones"]:
        mat = role_to_mat.get(str(zone.get("role") or ""), default)
        areas.append({
            "object_id": f'FA-{zone["object_id"]}',
            "name": f'{zone["name"]} 材料面（样板假设）',
            "polygon_mm": copy.deepcopy(zone["polygon_mm"]),
            "unit": "m2", "layer": "floor_finish",
            "material_ref": {"material_id": mat["material_id"],
                             "name": mat["name"], "spec_status": "assumption"},
        })
    return {"kind": "material_face_slice",
            "declared_by": "executor_manual_fixture_w2_r4",
            "declaration": "材料面按精确分区多边形切片，材料编号与表达层材质映射同源；"
                           "人工夹具，未经现场复核",
            "unit": "mm", "deduction_basis": "keepouts_within_scope",
            "areas": areas}


def prices_for(presentation: dict, unit: float = 1000.0) -> dict:
    return {mat["material_id"]: unit for mat in presentation["materials"]}


def dump_outputs(outdir: Path, files: dict, extras: dict | None = None) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (outdir / name).write_bytes(data)
    for name, value in (extras or {}).items():
        (outdir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


def main() -> int:
    global PORT
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "var/evidence/roadmap/W2-R4-同源表达"))
    parser.add_argument("--runtime", default=None)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()
    evidence = Path(args.out).resolve()
    runtime = Path(args.runtime).resolve() if args.runtime else evidence / "runtime"
    evidence.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    main_db = runtime / "app.sqlite3"
    studio_db = runtime / "studio.db"
    for f in (main_db, studio_db):
        if f.exists():
            f.unlink()

    studio = Store(studio_db)
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
            revision_uid=f"uid-w2r4-{letter}", run_id=f"run-w2r4-{letter}",
            candidate_group_id=f"group-w2r4-{letter}",
            input_hash_value=hashlib.sha256(json.dumps(rep["plan"], sort_keys=True).encode()).hexdigest(),
            check_report_id=f"check-w2r4-{letter}",
            diagnostics={"source": "labelled_local_fixture"})
        arts[letter] = studio.artifact_by_id(aid)

    main_store = SQLiteStore(main_db)
    files = FileService(main_db, runtime)
    requirements = RequirementService(main_db)
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
        SQLiteAIRequirementRepository(main_db), requirements, config=brief_config,
        provider_factory=lambda config: build_provider(config))
    options_ai = AIDesignOptionService(
        SQLiteAIDesignOptionRepository(main_db),
        lambda org, project: requirement_ai.status(org, project)["item"],
        lambda org, project: {"width": "12", "length": "8",
                              "boundary_source": "test_parameters_not_site_verified",
                              "obstacles": []},
        runtime, config=option_config,
        provider=build_design_option_provider(option_config), studio_source=source)
    from rkd_mvp.ai_development_repository import SQLiteAIDevelopmentRepository
    spatial_ai = AISpatialOutputService(
        SQLiteAIDevelopmentRepository(main_db), options_ai, runtime,
        start_workers=False)
    service = ApiService(MVPApp(main_store), files, requirement_service=requirements,
                         ai_requirement_service=requirement_ai,
                         ai_design_option_service=options_ai,
                         ai_spatial_output_service=spatial_ai, runtime_root=runtime,
                         studio_source=source)
    files.seed_ningbo(service, FIXTURE_ROOT)
    server = create_server(service, port=0, static_dir=ROOT / "web" / "dist")
    PORT = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"/api/v1/projects/{PID}/ai"
    results: dict[str, dict] = {}
    meta_all: dict[str, dict] = {}

    try:
        for index, letter in enumerate(("A", "B")):
            code, imp, _ = http("POST", f"{base}/design-options/import-studio",
                                {"studio_project_id": SPID,
                                 "studio_artifact_id": arts[letter]["id"],
                                 "expected_source_sha256": arts[letter]["sha256"],
                                 "expected_unit": "mm"})
            assert code == 200, imp
            rev = imp["item"]
            http("POST", f"{base}/design-options/{rev['option_id']}/adopt",
                 {"expected_revision": rev["revision_no"], "expected_version": index})
            detail = options_ai.revision_by_id(ORG, PID, rev["option_revision_id"]) or {}
            model = detail.get("model") or {}
            boundary = model["spatial"]["origin"]["boundary_mm"]
            raw = build_fixture_presentation(model, letter)
            pres = normalize_presentation(raw, boundary_mm=boundary)
            scope = make_finish_scope(model, pres)
            prices = prices_for(pres)
            settings = {
                "render": not args.no_render, "width": 1120, "height": 700,
                "samples": args.samples, "presentation": pres,
                "finish_scope": scope, "material_unit_prices": prices,
            }
            code, gen, _ = http("POST", f"{base}/spatial-outputs",
                                {"option_revision_id": rev["option_revision_id"],
                                 "settings": settings},
                                {"Idempotency-Key": f"w2r4-outputs-{letter}-0001"})
            if code not in (200, 202):
                check(f"R4-{letter}-SUBMIT", f"布局 {letter} 提交同源成果", False,
                      {"status": code, "body": gen})
                continue
            job = gen["item"]
            state = http("GET", f"{base}/spatial-outputs?job_id={job['job_id']}")[1]
            revision = state.get("revision") or {}
            results[letter] = {"rev": rev, "model": model, "presentation": pres,
                               "scope": scope, "prices": prices, "settings": settings,
                               "job": job, "state": state, "revision": revision}
            check(f"R4-{letter}-SUBMIT", f"布局 {letter} 由同一生成器产出完整成果",
                  bool(job.get("status") == "succeeded" and revision
                       and state.get("artifacts")),
                  {"status": code, "job_status": job.get("status"),
                   "job_error": job.get("error_code"),
                   "message": job.get("error_message"),
                   "artifacts": [a["filename"] for a in state.get("artifacts") or []],
                   "generator": (revision.get("baseline") or {}).get("generator_version")})
            if not revision:
                continue
            rid = revision["production_revision_id"]
            downloaded = {}
            for name in ("plan.svg", "plan-index.json", "scene.json", "quantity.json",
                         "quantity.csv", "cost.html", "manifest.json", "render.png",
                         "package.zip"):
                sc, _meta, raw = http("GET", f"{base}/spatial-outputs/{rid}/files/{name}")
                if sc == 200:
                    downloaded[name] = raw
            png_meta = {}
            png_meta_path = (runtime / "projects" / "ai-spatial-outputs" / job["job_id"]
                             / "render.png.meta.json")
            if png_meta_path.is_file():
                png_meta = json.loads(png_meta_path.read_text(encoding="utf-8"))
            meta_all[letter] = png_meta
            outdir = evidence / "outputs" / f"layout-{letter}"
            dump_outputs(outdir, downloaded, {
                "model.json": model, "presentation.json": pres,
                "finish-scope.json": scope,
                "render-meta.json": png_meta,
                "source-note.json": {
                    "design_origin": "labelled_local_fixture_not_ai_design",
                    "presentation": "executor_manual_test_assumptions",
                    "site_verified": False,
                    "declaration": pres["disclaimer"],
                },
            })
            # ZIP 解压逐项核对
            zip_problems = []
            zip_names = []
            manifest = {}
            if "manifest.json" in downloaded:
                manifest = json.loads(downloaded["manifest.json"])
            if "package.zip" in downloaded:
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / "unzip"
                    target.mkdir()
                    with zipfile.ZipFile(io.BytesIO(downloaded["package.zip"])) as zc:
                        zc.extractall(target)
                        zip_names = sorted(zc.namelist())
                    for entry in manifest.get("files") or []:
                        path = target / entry["filename"]
                        if not path.is_file():
                            zip_problems.append(f"缺少 {entry['filename']}")
                            continue
                        data = path.read_bytes()
                        if len(data) != entry["size_bytes"] or sha256_bytes(data) != entry["sha256"]:
                            zip_problems.append(f"字节不符 {entry['filename']}")
                    listed = {e["filename"] for e in manifest.get("files") or []}
                    if listed - set(zip_names):
                        zip_problems.append(f"清单有但 ZIP 无：{sorted(listed - set(zip_names))}")
                    if set(zip_names) - listed - {"manifest.json"}:
                        zip_problems.append("ZIP 有未登记文件")
                    png_same = (not args.no_render and (target / "render.png").is_file()
                                and (target / "render.png").read_bytes() == downloaded.get("render.png"))
            else:
                png_same = False
            check(f"R4-{letter}-ZIP", f"布局 {letter} 完整 ZIP/下载 SHA 与 PNG 一致",
                  bool(manifest.get("files") and not zip_problems
                       and (args.no_render or png_same)),
                  {"zip_entries": zip_names, "manifest_files": len(manifest.get("files") or []),
                   "problems": zip_problems, "png_matches_zip": png_same})

        # ---------------------------------------------------------- 两布局同源
        a, b = results.get("A"), results.get("B")
        if a and b and a["revision"] and b["revision"]:
            ra, rb = a["revision"], b["revision"]
            na = next(x for x in ra["quantities"]["items"]
                      if x["quantity_id"] == "Q-FLOOR-GEOMETRIC-NET")["value"]
            nb = next(x for x in rb["quantities"]["items"]
                      if x["quantity_id"] == "Q-FLOOR-GEOMETRIC-NET")["value"]
            check("R4-01", "两种不同布局由同一生成器出平面/场景/人眼图，模型哈希与净量不同",
                  bool(ra["baseline"]["model_hash"] != rb["baseline"]["model_hash"]
                       and na != nb
                       and ra["baseline"]["generator_version"] == rb["baseline"]["generator_version"]
                       and ra["baseline"]["presentation_version"]
                       == rb["baseline"]["presentation_version"]),
                  {"layout_a_net": na, "layout_b_net": nb,
                   "model_hashes": [ra["baseline"]["model_hash"][:12],
                                    rb["baseline"]["model_hash"][:12]],
                   "generator": ra["baseline"]["generator_version"],
                   "presentation_version": ra["baseline"]["presentation_version"]})
        else:
            check("R4-01", "两种不同布局由同一生成器出平面/场景/人眼图", False,
                  {"reason": "至少一份布局未产出 revision"})

        # ---------------------------------------------------------- 平面可读
        for letter, item in results.items():
            plan = (evidence / "outputs" / f"layout-{letter}" / "plan.svg")
            if not plan.is_file():
                check(f"R4-02-{letter}", f"布局 {letter} 平面可读", False,
                      {"reason": "plan.svg 缺失"})
                continue
            text = plan.read_text(encoding="utf-8")
            pres = item["presentation"]
            required = ["面积表", "图例", "总宽", "未建模", "不是施工图",
                        "人工测试假设", pres["walls"][0]["object_id"],
                        pres["openings"][0]["object_id"],
                        pres["cameras"][0]["object_id"],
                        "材质", "CC0 家具"]
            missing = [k for k in required if k not in text]
            font_sizes = [float(v) for v in __import__("re").findall(r'font-size="([\d.]+)"', text)]
            too_small = [v for v in font_sizes if v < 8.0]
            check(f"R4-02-{letter}", f"布局 {letter} 平面含墙/洞口/家具/材料/机位/尺寸链且文字可读",
                  not missing and not too_small and len(text) > 20000,
                  {"bytes": len(text), "missing": missing,
                   "min_font_size": min(font_sizes) if font_sizes else None,
                   "too_small_count": len(too_small),
                   "has_eye_level": "人眼" in text,
                   "has_dimension": "×" in text})

        # --------------------------------------------- 平面与三维同对象 ID/尺寸
        for letter, item in results.items():
            outdir = evidence / "outputs" / f"layout-{letter}"
            if not (outdir / "scene.json").is_file() or not (outdir / "plan.svg").is_file():
                check(f"R4-03-{letter}", f"布局 {letter} 平面与三维同对象 ID", False,
                      {"reason": "scene.json / plan.svg 缺失"})
                continue
            scene = json.loads((outdir / "scene.json").read_text(encoding="utf-8"))
            plan_text = (outdir / "plan.svg").read_text(encoding="utf-8")
            enc = scene.get("enclosure") or {}
            ids_ok, size_ok = [], []
            wall_ids = [w["object_id"] for w in enc.get("walls", [])
                        + enc.get("partitions", [])]
            for wall in enc.get("walls", []) + enc.get("partitions", []):
                ids_ok.append(wall["object_id"] in plan_text
                              and wall_ids.count(wall["object_id"]) == 1)
                size_ok.append(f'{wall["thickness_mm"]:.0f}mm' in plan_text)
            for opening in enc.get("openings", []):
                ids_ok.append(opening["object_id"] in plan_text)
                size_ok.append(f'{opening["width_mm"]:.0f}×' in plan_text)
            furn = scene.get("presentation_furniture") or []
            plan_index_path = outdir / "plan-index.json"
            if plan_index_path.is_file():
                # V1 起短编号由 plan-index.json 全局唯一分配；按索引对账，
                # 不再靠调用方猜短码前缀（V3 新增陈设后旧算法会撞号）。
                pidx = json.loads(plan_index_path.read_text(encoding="utf-8"))
                codes = [v["code"] for v in pidx["labels"].values()
                         if v["kind"] == "furniture"]
                furn_ok = bool(codes) and len(codes) == len(furn) \
                    and all(code in plan_text for code in codes)
            else:
                furn_ok = all((f["object_id"] if len(f["object_id"]) <= 5
                               else "P" + f["object_id"].split("-")[-1]) in plan_text
                              for f in furn)
            zone_mat_ok = all(z.get("material_slot") for z in scene.get("zones") or [])
            check(f"R4-03-{letter}", f"布局 {letter} 围合/开口/家具在平面与三维读同一 ID 与尺寸",
                  bool(all(ids_ok) and all(size_ok) and furn_ok and zone_mat_ok
                       and scene.get("schema_version") == "rkd-spatial-scene.v2"),
                  {"walls": len(enc.get("walls") or []),
                   "partitions": len(enc.get("partitions") or []),
                   "openings": len(enc.get("openings") or []),
                   "furniture": len(furn), "ids_ok": all(ids_ok),
                   "size_labels_ok": all(size_ok), "furniture_labels_ok": furn_ok,
                   "zone_material_slots": sorted({z.get("material_slot")
                                                  for z in scene.get("zones") or []})})

        # --------------------------------------------- 真实材质/家具/灯光/机位
        for letter in meta_all:
            if args.no_render:
                # 主动不渲染：图像项为 not_run，不是产品失败，也不得算通过。
                check(f"R4-04-{letter}",
                      f"布局 {letter} 真实 CC0 材质/家具/窗光/人眼机位出图",
                      False, {"reason": "--no-render 主动跳过真实 Blender 渲染",
                              "expected_artifact": "render.png + render.png.meta.json",
                              "note": "需运行不带 --no-render 的完整验证才能判定"},
                      result="not_run", layer="real_render")
                continue
            meta = meta_all[letter]
            png = evidence / "outputs" / f"layout-{letter}" / "render.png"
            assets = meta.get("assets") or {}
            lights = meta.get("lights") or {}
            cam = meta.get("camera") or {}
            ok = bool(meta.get("presentation") and len(assets.get("textures_used") or []) >= 4
                      and len(assets.get("models_used") or []) >= 6
                      and (lights.get("window_area_lights") or 0) >= 5
                      and abs((cam.get("eye_height_m") or 0) - 1.5) < 1e-6
                      and png.is_file() and png.stat().st_size > 100_000)
            check(f"R4-04-{letter}", f"布局 {letter} 真实 CC0 材质/家具/窗光/人眼机位出图",
                  ok, {"png_bytes": png.stat().st_size if png.is_file() else 0,
                       "textures_used": assets.get("textures_used"),
                       "models_used": assets.get("models_used"),
                       "placeholders": assets.get("placeholders"),
                       "window_area_lights": lights.get("window_area_lights"),
                       "fixture_lights": lights.get("fixture_lights"),
                       "cove_segments": lights.get("cove_segments"),
                       "camera": cam, "engine": meta.get("engine"),
                       "seconds": meta.get("seconds")})

        # ------------------------------------------------ 四项同源受控变更
        if a and a["model"]:
            model = a["model"]
            pres = a["presentation"]
            scope = a["scope"]
            prices = a["prices"]
            boundary = model["spatial"]["origin"]["boundary_mm"]
            changes = evidence / "outputs" / "changes"
            base_pkg = build_package(model, project_id=PID, option_revision_id="r4-fixture",
                                     settings={"presentation": pres,
                                               "material_unit_prices": prices},
                                     finish_scope=scope)
            # 1) 改一个窗洞口尺寸
            p1 = copy.deepcopy(pres)
            for op in p1["openings"]:
                if op["object_id"] == "R4-WIN-N1":
                    op["width_mm"] = 3000.0
            p1 = normalize_presentation(p1, boundary_mm=boundary)
            pkg1 = build_package(model, project_id=PID, option_revision_id="r4-fixture",
                                 settings={"presentation": p1,
                                           "material_unit_prices": prices},
                                 finish_scope=scope)
            scene1 = pkg1["scene"]
            open1 = next(o for o in scene1["enclosure"]["openings"]
                         if o["object_id"] == "R4-WIN-N1")
            ok1 = (pkg1["plan"] != base_pkg["plan"] and pkg1["scene"] != base_pkg["scene"]
                   and open1["width_mm"] == 3000.0
                   and "R4-WIN-N1" in pkg1["plan"].decode("utf-8")
                   and "3000×1800" in pkg1["plan"].decode("utf-8")
                   and pkg1["quantities"] == base_pkg["quantities"])
            # 2) 换一项材质贴图
            p2 = copy.deepcopy(pres)
            for mat in p2["materials"]:
                if mat["material_id"] == "mat-oak":
                    mat["slot"] = "walnut"
                    mat["name"] = "玫瑰木（受控替换）"
            p2 = normalize_presentation(p2, boundary_mm=boundary)
            pkg2 = build_package(model, project_id=PID, option_revision_id="r4-fixture",
                                 settings={"presentation": p2,
                                           "material_unit_prices": prices},
                                 finish_scope=scope)
            arrival_slot = next(z["material_slot"] for z in pkg2["scene"]["zones"]
                                if z["object_id"] == "ZA1")
            ok2 = (arrival_slot == "walnut" and pkg2["plan"] != base_pkg["plan"]
                   and pkg2["scene"] != base_pkg["scene"]
                   and pkg2["quantities"] == base_pkg["quantities"]
                   and pkg2["cost"] == base_pkg["cost"])
            # 3) 只改相机
            p3 = copy.deepcopy(pres)
            p3["cameras"][0]["position_mm"][0] += 3000.0
            p3 = normalize_presentation(p3, boundary_mm=boundary)
            pkg3 = build_package(model, project_id=PID, option_revision_id="r4-fixture",
                                 settings={"presentation": p3,
                                           "material_unit_prices": prices},
                                 finish_scope=scope)
            ok3 = (pkg3["plan"] != base_pkg["plan"] and pkg3["scene"] != base_pkg["scene"]
                   and pkg3["quantities"] == base_pkg["quantities"]
                   and pkg3["cost"] == base_pkg["cost"])
            # 4) 只改假设单价
            pkg4 = build_package(model, project_id=PID, option_revision_id="r4-fixture",
                                 settings={"presentation": pres,
                                           "material_unit_prices": {k: v * 1.2
                                                                    for k, v in prices.items()}},
                                 finish_scope=scope)
            amount0 = base_pkg["cost"]["assumption_trial_total_cny"]
            amount4 = pkg4["cost"]["assumption_trial_total_cny"]
            ok4 = (pkg4["plan"] == base_pkg["plan"] and pkg4["scene"] == base_pkg["scene"]
                   and pkg4["quantities"] == base_pkg["quantities"]
                   and amount0 and amount4 and amount4 > amount0)
            check("R4-05", "四项受控变更：开口尺寸同步平面/场景且改几何不改量；换材质可追踪；"
                           "只改相机不改量；只改单价不改几何",
                  bool(ok1 and ok2 and ok3 and ok4),
                  {"opening_width_mm": open1["width_mm"],
                   "opening_quantity_unchanged": pkg1["quantities"] == base_pkg["quantities"],
                   "material_slot_after": arrival_slot,
                   "material_quantity_and_cost_unchanged":
                       pkg2["quantities"] == base_pkg["quantities"]
                       and pkg2["cost"] == base_pkg["cost"],
                   "camera_quantity_unchanged": pkg3["quantities"] == base_pkg["quantities"],
                   "price_geometry_unchanged": pkg4["quantities"] == base_pkg["quantities"]
                   and pkg4["plan"] == base_pkg["plan"],
                   "trial_amount_before_after": [amount0, amount4]})
            changes.mkdir(parents=True, exist_ok=True)
            (changes / "reconciliation.json").write_text(json.dumps({
                "zone_to_material": [{"zone_id": z["object_id"],
                                      "role": z.get("role"),
                                      "material_slot": z.get("material_slot")}
                                     for z in base_pkg["scene"]["zones"]],
                "material_groups": next(x for x in base_pkg["quantities"]["items"]
                                        if x["quantity_id"] == "Q-FLOOR-FINISH")["material_groups"],
                "trial_items": base_pkg["cost"]["known_items"],
                "trial_total_cny": amount0,
                "note": "材料面切片 → 材料编号 → CC0 贴图 slot → 分组面积 → 假设单价试算，逐行可追踪",
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            check("R4-05", "四项受控变更", False, {"reason": "布局 A 未产出模型"})

        # ---------------------------------------------------------- 入口小修
        conflict_evidence = evidence / "after" / "finish-conflict-after.json"
        regression_evidence = (evidence / "regression-second-closeout"
                               / "repro-r4-regression.json")
        missing_inputs = [str(p) for p in (conflict_evidence, regression_evidence)
                          if not p.is_file()]
        if missing_inputs:
            # 前置证据未随本次 --out 目录提供：明确标「缺证」，不与产品断言混为一类。
            check("R4-06", "入口小修：同层异材冲突不产 known 总量/试算；原 15 项回归保留",
                  False, {"status": "missing_evidence", "missing_paths": missing_inputs,
                          "note": "这是外部证据未在本次输出目录提供，不是产品回归；"
                                  "可在完整输出目录复跑或复制前置证据后重判"},
                  result="missing_evidence", layer="external_evidence")
        else:
            conflict_ok = bool(
                json.loads(conflict_evidence.read_text(encoding="utf-8")).get("all_as_expected"))
            regression = json.loads(regression_evidence.read_text(encoding="utf-8"))
            regression_ok = (regression.get("totals", {}).get("observed_pass") == 15
                             and regression.get("totals", {}).get("observed_fail") == 0)
            check("R4-06", "入口小修：同层异材冲突不产 known 总量/试算；原 15 项回归保留",
                  bool(conflict_ok and regression_ok),
                  {"conflict_after": str(conflict_evidence),
                   "conflict_all_as_expected": conflict_ok,
                   "regression": str(regression_evidence),
                   "regression_15_of_15": regression_ok},
                  layer="external_evidence")

        # ------------------------------------------ 按 ID 任务定位（不串成果）
        if a and b:
            ja, jb = a["job"]["job_id"], b["job"]["job_id"]
            sa = http("GET", f"{base}/spatial-outputs?job_id={ja}")[1]
            sb = http("GET", f"{base}/spatial-outputs?job_id={jb}")[1]
            rid_a = (a["revision"] or {}).get("production_revision_id")
            rid_b = (b["revision"] or {}).get("production_revision_id")
            check("R4-07", "按 job_id 查询只返回该任务的 revision/artifacts，不串另一布局",
                  bool((sa.get("job") or {}).get("job_id") == ja
                       and (sb.get("job") or {}).get("job_id") == jb
                       and (sa.get("revision") or {}).get("production_revision_id") == rid_a
                       and (sb.get("revision") or {}).get("production_revision_id") == rid_b
                       and rid_a != rid_b),
                  {"job_a": ja, "job_b": jb, "revision_a": rid_a, "revision_b": rid_b})
        else:
            check("R4-07", "按 job_id 任务定位", False, {"reason": "缺少任务"})

    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        main_store.close()

    # ---------------------------------------- 取消晚到 / 任务定位回归（同一 R4 代码）
    import w2_closeout_repro as base_repro  # noqa: E402
    import w2_second_closeout_repro as second  # noqa: E402
    stack = base_repro.Stack(runtime / "regression-stack")
    try:
        ok_cancel, ev_cancel = second.c2_cancel_in_gap(stack)
        ok_locate, ev_locate = second.c3_explicit_isolated(stack)
    finally:
        stack.close()
    check("R4-08", "同一 R4 服务代码：取消晚到不复活可显式重试；失败任务不借用他人成果",
          bool(ok_cancel and ok_locate),
          {"cancel_late": ev_cancel, "job_isolation": ev_locate})

    passed = sum(1 for c in CHECKS if c["result"] == "observed_pass")
    failed = sum(1 for c in CHECKS if c["result"] == "observed_fail")
    not_run = sum(1 for c in CHECKS if c["result"] == "not_run")
    missing_evidence = sum(1 for c in CHECKS if c["result"] == "missing_evidence")
    code_head = __import__("subprocess").run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True).stdout.strip()

    def layer_status(items: list[dict]) -> str:
        results = {c["result"] for c in items}
        if "observed_fail" in results:
            return "observed_fail"
        if results == {"observed_pass"}:
            return "observed_pass"
        if results <= {"not_run", "missing_evidence"}:
            return "not_run_or_missing_evidence"
        return "mixed"

    verification_layers = {}
    for layer in ("function_level", "contract", "http", "external_evidence",
                  "real_render"):
        items = [c for c in CHECKS if c.get("layer") == layer]
        verification_layers[layer] = {
            "status": layer_status(items), "checks": [c["id"] for c in items],
            "counts": {key: sum(1 for c in items if c["result"] == key)
                       for key in ("observed_pass", "observed_fail", "not_run",
                                   "missing_evidence")}}
    verification_layers["browser"] = {
        "status": "separate_script_not_run_here",
        "evidence": "var/evidence/roadmap/<batch>/browser/verification.json",
        "note": "本脚本不启动浏览器；真实 Edge 验收由 verify_w2_r4_browser.py 单独执行"}
    verification_layers["manual_visual"] = {
        "status": "reported_in_review_packet",
        "evidence": "deliverables-for-review/roadmap/<batch>/manual-visual-review.md",
        "note": "自动断言只做几何/编号/字符串对账，不代表人工目检；"
                "图面可读性、材质尺度与光照层次必须由人工看图判定并单独记录"}
    out = {
        "task_id": "W2-R4 同源表达 / 表达收口",
        "schema_version": "rkd-w2-r4-checks.v2",
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "code_head": code_head,
        "render_enabled": not args.no_render,
        "environment": {"python": sys.version.split()[0],
                        "renderer": "blender-4.2.9 Cycles CPU (local CC0 assets)"
                        if not args.no_render else "not_run",
                        "isolated_main_db": str(main_db),
                        "isolated_studio_db": str(studio_db),
                        "model_channel": "labelled local fixtures only",
                        "presentation": "executor manual test assumptions",
                        "keys_used": False},
        "checks": CHECKS,
        "totals": {"observed_pass": passed, "observed_fail": failed,
                   "not_run": not_run, "missing_evidence": missing_evidence},
        "verification_layers": verification_layers,
        "semantics": {
            "observed_fail": "真实产品断言失败，决定退出码",
            "not_run": "本运行主动跳过（如 --no-render 的真实图像项），不计失败也不计通过",
            "missing_evidence": "缺少前置/外部证据文件，不计产品回归",
            "manual_visual": "人工目检在复核包单列，绝不由自动断言代签",
        },
        "external_calls": 0, "tokens": 0, "images_generated": (0 if args.no_render
                                                               else len(meta_all)),
        "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
        "not_customer_design_approval": True,
    }
    (evidence / "checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(json.dumps({"observed_pass": passed, "observed_fail": failed,
                      "not_run": not_run, "missing_evidence": missing_evidence,
                      "exit_on": "observed_fail_only",
                      "out": str(evidence / "checks.json")}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
