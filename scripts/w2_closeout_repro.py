"""W2 收口整改同一负例：对整改前/后源码各跑一次，逐项记录真实结果。

用法（整改前）：
  RKD_VERIFY_ROOT="var/evidence/roadmap/W2-收口整改/before-code" \
  ./.venv/Scripts/python.exe scripts/w2_closeout_repro.py --label before --out <dir>
用法（整改后）：
  ./.venv/Scripts/python.exe scripts/w2_closeout_repro.py --label after --out <dir>

只读本地夹具与隔离 SQLite；0 外部模型调用、0 密钥、0 费用。
渲染用可控渲染桩（不依赖 Blender），另在 verify_w2_closeout.py 保留一次真实 Blender 链。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(os.environ.get("RKD_VERIFY_ROOT") or
            Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

CHECKS: list[dict] = []
PORT = 0
ORG = "org-local"


def record(cid: str, name: str, fn) -> None:
    try:
        ok, evidence = fn()
    except Exception as error:  # noqa: BLE001
        ok, evidence = False, {"error": f"{type(error).__name__}: {error}",
                               "trace": traceback.format_exc(limit=3).splitlines()[-3:]}
    CHECKS.append({"id": cid, "name": name,
                   "result": "observed_pass" if ok else "observed_fail",
                   "evidence": evidence})
    print(("PASS " if ok else "FAIL ") + cid + " " + name, flush=True)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ fixtures
def l_shape_model(keepouts: list[dict] | None = None) -> dict:
    """手算 L 形：毛 24㎡，1×2 扣除 2㎡，净 22㎡；包围盒 30㎡（扣后 28㎡）。"""
    zone = {"object_id": "ZL1", "name": "L 形试验分区", "role": "test",
            "polygon_mm": [[0, 0], [6000, 0], [6000, 2000], [4000, 2000],
                           [4000, 5000], [0, 5000]],
            "area_sqm": 24.0, "finish_material": {}}
    return {
        "option_id": "l-shape-fixture", "revision_no": 1,
        "strategy": {"statement": "手算 L 形试验夹具（非设计方案）"},
        "boundary": {"width": 6.0, "length": 5.0, "unit": "m",
                     "entrance": {"side": "left", "point": [0.0, 0.0], "width": 1.8},
                     "obstacles": keepouts or []},
        "spatial": {
            "schema_version": "rkd-spatial-model.v1", "unit": "mm",
            "origin": {"coordinate_system": "southwest_origin_x_east_y_north",
                       "boundary_mm": [6000, 5000]},
            "zones": [zone], "circulation": [], "platforms": [], "furniture": [],
            "ceiling": {"fixtures": []}, "materials": [],
            "source": {"origin_kind": "manual_fixture", "artifact_id": "art-l-shape",
                       "sha256": "0" * 64, "revision_uid": "uid-l-shape",
                       "design_origin": {"kind": "fixture", "declared_by": "executor",
                                         "declaration": "手算 L 形夹具，非设计成果",
                                         "run_refs": []},
                       "site_source": {"ceiling_mm": 3000}},
        },
    }


def keepout(oid: str, x: float, y: float, w: float, l: float) -> dict:
    return {"object_id": oid, "name": oid,
            "shape": {"x": x, "y": y, "width": w, "length": l}}


def find_q(quantities: dict, *ids: str) -> dict | None:
    for item in quantities.get("items") or []:
        if item.get("quantity_id") in ids:
            return item
    return None


# --------------------------------------------------------------- function tests
def f_r1_package_complete():
    """R1：同一文件集合 → 清单 + ZIP；有渲染必须打包 PNG，清单与 ZIP 完全对应。"""
    import rkd_mvp.ai_spatial_outputs as outs
    pkg = outs.build_package(l_shape_model(), project_id="p", option_revision_id="r")
    png = b"\x89PNG\r\n\x1a\n" + os.urandom(512)
    files = dict(pkg["files"])
    files["render.png"] = ("render_png", "image/png", png)
    finalize = getattr(outs, "finalize_package", None)
    if finalize is None:
        legacy = outs.finalize_files(pkg["files"], outs.add_rendered(
            pkg["manifest"], filename="render.png", png=png, render_meta={"seconds": 0}))
        zf = zipfile.ZipFile(io.BytesIO(legacy["package.zip"][2]))
        names = sorted(zf.namelist())
        return False, {"api": "finalize_files(add_rendered)", "zip_entries": names,
                       "render_in_zip": "render.png" in names,
                       "manifest_render_in_zip": "render.png" in names,
                       "note": "整改前 add_rendered 只写清单不写 ZIP"}
    built = finalize(files, pkg["manifest"])
    out = built["files"]
    manifest = built["manifest"]
    zf = zipfile.ZipFile(io.BytesIO(out["package.zip"][2]))
    entries = {i.filename: zf.read(i.filename) for i in zf.infolist()}
    listed = {e["filename"]: e for e in manifest["files"]}
    problems = []
    for name, entry in listed.items():
        if name not in entries:
            problems.append(f"清单有但 ZIP 无：{name}")
        elif sha(entries[name]) != entry["sha256"] or len(entries[name]) != entry["size_bytes"]:
            problems.append(f"字节不一致：{name}")
    extra = set(entries) - set(listed) - {"manifest.json"}
    if extra:
        problems.append(f"ZIP 有但清单没登记：{sorted(extra)}")
    check = built.get("check") or {}
    return (not problems and "render.png" in listed and "render.png" in entries
            and check.get("ok") is True), {
        "zip_entries": sorted(entries), "manifest_listed": sorted(listed),
        "problems": problems, "self_check": check}


def f_r1_no_render_no_png():
    """R1 正例：render=false 时清单不能声明 PNG，ZIP 也不能有 PNG。"""
    import rkd_mvp.ai_spatial_outputs as outs
    pkg = outs.build_package(l_shape_model(), project_id="p", option_revision_id="r")
    if not hasattr(outs, "finalize_package"):
        legacy = outs.finalize_files(pkg["files"], pkg["manifest"])
        zf = zipfile.ZipFile(io.BytesIO(legacy["package.zip"][2]))
        names = sorted(zf.namelist())
        return "render.png" not in names, {"api": "legacy", "zip_entries": names}
    built = outs.finalize_package(dict(pkg["files"]), pkg["manifest"])
    zf = zipfile.ZipFile(io.BytesIO(built["files"]["package.zip"][2]))
    names = sorted(zf.namelist())
    listed = [e["filename"] for e in built["manifest"]["files"]]
    return (not any(n.endswith(".png") for n in names)
            and not any(n.endswith(".png") for n in listed)), {
        "zip_entries": names, "manifest_listed": listed}


def f_r3_l_shape_handcheck():
    """R3：L 形手算 24/22；独立复算不能复用主算法的 deducted；完成面量不得已知。"""
    import rkd_mvp.ai_spatial_outputs as outs
    model = l_shape_model([keepout("K1", 1.0, 1.0, 1.0, 2.0)])
    qty = outs.measure(model)
    gross = find_q(qty, "Q-FLOOR-GROSS")
    net = find_q(qty, "Q-FLOOR-GEOMETRIC-NET", "Q-FLOOR-NET")
    finish = find_q(qty, "Q-FLOOR-FINISH")
    independent = (net or {}).get("independent_recompute_m2")
    return (gross and abs(gross["value"] - 24.0) < 1e-6
            and net and abs(net["value"] - 22.0) < 1e-6
            and independent is not None and abs(independent - 22.0) < 1e-3
            and (net or {}).get("engineering_status")
            == "geometric_only_not_a_finish_quantity"
            and finish is not None and finish.get("value") is None
            and finish.get("known_status") == "unknown"), {
        "gross": (gross or {}).get("value"), "net": (net or {}).get("value"),
        "net_name": (net or {}).get("name"),
        "engine_where": (net or {}).get("engineering_status"),
        "independent": independent,
        "independent_method": (net or {}).get("independent_method"),
        "finish": {"value": (finish or {}).get("value"),
                   "known_status": (finish or {}).get("known_status"),
                   "unknown_reason": (finish or {}).get("unknown_reason")},
        "quantity_ids": [i["quantity_id"] for i in qty["items"]]}


def f_r3_deduction_rules():
    """R3 负例：跨边界扣除、两扣除区相交不重复扣、完全外置扣除为 0。"""
    import rkd_mvp.ai_spatial_outputs as outs
    # 相交两个扣区：A 1×2 @ (1,1)，B 1×2 @ (1.5,1.5) 相交 0.5×1.5=0.75 → 并集 3.25
    inter = outs.measure(l_shape_model([keepout("K1", 1.0, 1.0, 1.0, 2.0),
                                       keepout("K2", 1.5, 1.5, 1.0, 2.0)]))
    # 完全外置：扣区在场地外
    outside = outs.measure(l_shape_model([keepout("K3", 20.0, 20.0, 1.0, 1.0)]))
    # 跨边界：1×2 扣区跨 L 形缺口边界（x 3.5—4.5, y 2—4），只有落在分区内的部分算扣除
    cross = outs.measure(l_shape_model([keepout("K4", 3.5, 2.0, 1.0, 2.0)]))
    ded_inter = find_q(inter, "Q-KEEPOUT-DEDUCT")["value"]
    deq_out = find_q(outside, "Q-KEEPOUT-DEDUCT")["value"]
    ded_cross = find_q(cross, "Q-KEEPOUT-DEDUCT")["value"]
    net_inter = find_q(inter, "Q-FLOOR-GEOMETRIC-NET", "Q-FLOOR-NET")["value"]
    return (abs(ded_inter - 3.25) < 1e-3 and abs(net_inter - 20.75) < 1e-3
            and abs(deq_out) < 1e-9 and abs(ded_cross - 1.0) < 1e-3), {
        "intersecting_deduct": ded_inter, "intersecting_net": net_inter,
        "expected_union_deduct": 3.25, "outside_deduct": deq_out,
        "cross_boundary_deduct": ded_cross, "expected_cross_deduct": 1.0,
        "note": "跨边界扣区只有落在分区内的 0.5×2=1.0㎡ 计入；外置扣区不产生负面积"}


def f_r3_finish_scope():
    """R3：只有显式标注来源的材料面切片才进入饰面净量；单价不能掩盖未知范围。"""
    import inspect

    import rkd_mvp.ai_spatial_outputs as outs
    measure = outs.measure
    accepts_scope = "finish_scope" in inspect.signature(measure).parameters
    scope = {"kind": "material_face_slice", "declared_by": "executor_manual_fixture",
             "declaration": "人工夹具：按手算 L 形铺装范围切片，未经现场复核",
             "unit": "mm", "deduction_basis": "keepouts_within_scope",
             "areas": [{"object_id": "FA1", "name": "试验材料面（手算夹具）",
                        "polygon_mm": [[0, 0], [6000, 0], [6000, 2000], [4000, 2000],
                                       [4000, 5000], [0, 5000]],
                        "material_ref": {"material_id": "M-CEMENT", "name": "微水泥",
                                         "spec_status": "assumption"}}]}
    qty_no_scope = measure(l_shape_model([keepout("K1", 1.0, 1.0, 1.0, 2.0)]))
    qty_scope = measure(l_shape_model([keepout("K1", 1.0, 1.0, 1.0, 2.0)]),
                        finish_scope=scope) if accepts_scope else qty_no_scope
    finish = find_q(qty_scope, "Q-FLOOR-FINISH")
    cost_scope = outs.build_cost(qty_scope, settings={"finish_scope": scope})
    cost_priced = outs.build_cost(qty_scope, settings={
        "finish_scope": scope, "material_unit_prices": {"M-CEMENT": 800}})
    cost_price_no_scope = outs.build_cost(qty_no_scope,
                                          settings={"material_unit_prices": {"M-CEMENT": 800}})
    return (accepts_scope and finish is not None and finish.get("value") is not None
            and abs(finish["value"] - 22.0) < 1e-3
            and (finish.get("basis_source") or {}).get("declared_by") == "executor_manual_fixture"
            and cost_scope["known_items"] == []
            and len(cost_priced["known_items"]) == 1
            and abs(cost_priced["known_items"][0]["amount_cny"] - 22 * 800) < 0.01
            and cost_price_no_scope["known_items"] == []), {
        "accepts_finish_scope": accepts_scope,
        "finish": {"value": (finish or {}).get("value"),
                   "known_status": (finish or {}).get("known_status"),
                   "basis_source": (finish or {}).get("basis_source"),
                   "material_groups": (finish or {}).get("material_groups")},
        "cost_without_price": cost_scope["known_items"],
        "cost_with_price": cost_priced["known_items"],
        "cost_price_but_no_scope": cost_price_no_scope["known_items"]}


# ------------------------------------------------------------------- HTTP tests
def http(method: str, path: str, body=None, extra=None):
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
        data = {"_raw": raw[:300].decode("utf-8", "replace")}
    return resp.status, data, raw


class Stack:
    """一次装配：隔离 SQLite + 真实 HTTP + 可控渲染桩。"""

    def __init__(self, runtime: Path) -> None:
        global PORT
        from arc_first_batch_stub import SITE, valid_proposal
        from rkd_mvp.ai_design_option_provider import (
            DesignOptionConfig, build_design_option_provider)
        from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository
        from rkd_mvp.ai_design_option_service import AIDesignOptionService
        from rkd_mvp.ai_design_studio_adapter import StudioProposalSource
        from rkd_mvp.ai_development_repository import SQLiteAIDevelopmentRepository
        from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider
        from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository
        from rkd_mvp.ai_requirement_service import AIRequirementService
        from rkd_mvp.ai_spatial_output_service import AISpatialOutputService
        from rkd_mvp.api_server import create_server
        from rkd_mvp.api_service import ApiService
        from rkd_mvp.engine import MVPApp
        from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID
        from rkd_mvp.requirement_service import RequirementService
        from rkd_mvp.sqlite_store import SQLiteStore
        from rkd_mvp.studio import orchestrator, validation
        from rkd_mvp.studio.store import Store

        runtime.mkdir(parents=True, exist_ok=True)
        self.runtime = runtime
        self.main_db = runtime / "app.sqlite3"
        self.studio_db = runtime / "studio.db"
        for f in (self.main_db, self.studio_db):
            if f.exists():
                f.unlink()
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.render_delay: dict[str, float] = {}
        # 隔离工作树没有 tools/blender（.gitignore 排除）。整改前代码用“渲染器是否存在”
        # 卡住提交，因此只在显式声明时放一个占位文件满足存在性检查；真正渲染由可控桩完成。
        self.placeholder_renderer = None
        if os.environ.get("RKD_PLACEHOLDER_RENDERER") == "1":
            from rkd_mvp.ai_spatial_output_service import BLENDER
            if not Path(BLENDER).exists():
                Path(BLENDER).parent.mkdir(parents=True, exist_ok=True)
                Path(BLENDER).write_bytes(b"placeholder-for-renderer-existence-check")
                self.placeholder_renderer = Path(BLENDER)

        studio = Store(self.studio_db)
        orchestrator.Studio(studio).seed_from_fixtures()
        source = StudioProposalSource(studio)
        self.arts = {}
        for letter in ("A", "B"):
            rep = validation.validate_proposal(
                valid_proposal(letter), project={"id": "ningbo-xiecheng", "site": SITE},
                option_id=letter, revision=1, parent_revision=None)
            assert rep["ok"], rep["repair_feedback"][:300]
            aid = studio.save_artifact(
                "ningbo-xiecheng", "spatial-plan", rep["plan"], "D2", option_id=letter,
                revision=1, status="valid_candidate", contract_status="valid_candidate",
                revision_uid=f"uid-w2-{letter}", run_id=f"run-w2-{letter}",
                candidate_group_id=f"group-w2-{letter}",
                input_hash_value=hashlib.sha256(
                    json.dumps(rep["plan"], sort_keys=True).encode()).hexdigest(),
                check_report_id=f"check-w2-{letter}",
                diagnostics={"source": "labelled_local_fixture"})
            self.arts[letter] = studio.artifact_by_id(aid)

        self.main_store = SQLiteStore(self.main_db)
        self.files = FileService(self.main_db, runtime)
        requirements = RequirementService(self.main_db)
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
        self.requirement_ai = AIRequirementService(
            SQLiteAIRequirementRepository(self.main_db), requirements,
            config=brief_config, provider_factory=lambda config: build_provider(config))
        self.options_ai = AIDesignOptionService(
            SQLiteAIDesignOptionRepository(self.main_db),
            lambda org, project: self.requirement_ai.status(org, project)["item"],
            lambda org, project: {"width": "12", "length": "8",
                                  "boundary_source": "test_parameters_not_site_verified",
                                  "obstacles": []},
            runtime, config=option_config,
            provider=build_design_option_provider(option_config), studio_source=source)
        self.dev_repo = SQLiteAIDevelopmentRepository(self.main_db)
        self.spatial_ai = AISpatialOutputService(
            self.dev_repo, self.options_ai, runtime, start_workers=True,
            renderer=self._renderer)
        self.service = ApiService(MVPApp(self.main_store), self.files,
                                  requirement_service=requirements,
                                  ai_requirement_service=self.requirement_ai,
                                  ai_design_option_service=self.options_ai,
                                  ai_spatial_output_service=self.spatial_ai,
                                  runtime_root=runtime, studio_source=source)
        self.files.seed_ningbo(self.service, ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09")
        self.server = create_server(self.service, port=0, static_dir=ROOT / "web" / "dist")
        PORT = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.project_id = NINGBO_PROJECT_ID
        self.base = f"/api/v1/projects/{self.project_id}/ai"

    def _renderer(self, scene_path: Path, out_png: Path, width: int, height: int,
                   samples: int) -> dict:
        """可控渲染桩：默认立即返回；wait 模式下用屏障卡住，不靠 sleep 碰运气。"""
        mode = os.environ.get("RKD_STUB_RENDER_MODE", "fast")
        if mode == "wait":
            self.entered.set()
            self.gate.wait(timeout=30)
        out_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"stub-render" * 64)
        return {"seconds": 0.0, "engine": "stub", "width": width, "height": height,
                "samples": samples, "stub": True}

    def close(self) -> None:
        try:
            self.server.shutdown(); self.server.server_close(); self.thread.join(3)
        finally:
            self.main_store.close()
            if self.placeholder_renderer and self.placeholder_renderer.exists():
                self.placeholder_renderer.unlink()

    # ---------------------------------------------------------- helpers
    def import_layout(self, letter: str) -> dict:
        code, imp, _ = http("POST", f"{self.base}/design-options/import-studio", {
            "studio_project_id": "ningbo-xiecheng",
            "studio_artifact_id": self.arts[letter]["id"],
            "expected_source_sha256": self.arts[letter]["sha256"], "expected_unit": "mm"})
        assert code == 200, imp
        return imp["item"]

    def adopt(self, revision: dict, expected_version: int | None = None) -> None:
        if expected_version is None:
            adoption = (http("GET", f"{self.base}/design-options")[1].get("adoption") or {})
            expected_version = int(adoption.get("expected_revision") or 0)
        code, data, _ = http("POST", f"{self.base}/design-options/"
                             f"{revision['option_id']}/adopt",
                             {"expected_revision": revision["revision_no"],
                              "expected_version": expected_version})
        assert code == 200, data

    def submit(self, revision: dict, key: str, **settings) -> dict:
        payload = {"option_revision_id": revision["option_revision_id"],
                   "settings": {"render": True, "width": 320, "height": 240, "samples": 8,
                                **settings}}
        return http("POST", f"{self.base}/spatial-outputs", payload,
                    {"Idempotency-Key": key})

    def wait_job(self, job_id: str, timeout: float = 30.0) -> dict:
        deadline = time.monotonic() + timeout
        last = {}
        while time.monotonic() < deadline:
            code, data, _ = http("GET", f"{self.base}/spatial-outputs?job_id={job_id}")
            jobs = data.get("jobs") or []
            match = [j for j in jobs if j["job_id"] == job_id]
            last = match[0] if match else (data.get("job") or {})
            if last.get("status") in {"succeeded", "failed", "cancelled"}:
                return last
            time.sleep(0.02)
        raise AssertionError(f"等待任务超时：{job_id} 最后状态 {last.get('status')}")

    def state(self, query: str = "") -> dict:
        return http("GET", f"{self.base}/spatial-outputs{query}")[1]


def h_r1_zip_roundtrip(stack: Stack):
    """R1：真实 HTTP 下载 ZIP，在空临时目录解压，逐个核对清单文件。"""
    rev = stack.import_layout("A")
    stack.adopt(rev)
    code, gen, _ = stack.submit(rev, "w2c-r1-zip-0001")
    job = stack.wait_job(gen["item"]["job_id"])
    state = stack.state()
    revision = state.get("revision") or {}
    if job["status"] != "succeeded" or not revision:
        return False, {"submit": code, "job": job.get("status"), "error": job.get("error_code")}
    rid = revision["production_revision_id"]
    raw_manifest = http("GET", f"{stack.base}/spatial-outputs/{rid}/files/manifest.json")[2]
    raw_zip = http("GET", f"{stack.base}/spatial-outputs/{rid}/files/package.zip")[2]
    manifest = json.loads(raw_manifest)
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "unzip"
        target.mkdir()
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
            zf.extractall(target)
        problems = []
        for entry in manifest["files"]:
            path = target / entry["filename"]
            if not path.is_file():
                problems.append(f"缺少 {entry['filename']}")
                continue
            data = path.read_bytes()
            if len(data) != entry["size_bytes"]:
                problems.append(f"大小不符 {entry['filename']}")
            if sha(data) != entry["sha256"]:
                problems.append(f"SHA 不符 {entry['filename']}")
        separate = http("GET", f"{stack.base}/spatial-outputs/{rid}/files/render.png")[2]
        zip_png = (target / "render.png")
        png_same = zip_png.is_file() and zip_png.read_bytes() == separate
    return (not problems and png_same), {
        "zip_bytes": len(raw_zip), "manifest_files": [e["filename"] for e in manifest["files"]],
        "problems": problems, "render_matches_separate_download": png_same,
        "separate_render_bytes": len(separate)}


def h_r1_render_off(stack: Stack):
    """R1 正例：render=false 走真实入口，清单与 ZIP 都不得出现 PNG。"""
    rev = stack.import_layout("B")
    stack.adopt(rev)
    code, gen, _ = stack.submit(rev, "w2c-r1-norender-0001", render=False)
    job = stack.wait_job(gen["item"]["job_id"])
    state = stack.state(f"?job_id={gen['item']['job_id']}")
    revision = state.get("revision") or {}
    if job["status"] != "succeeded" or not revision:
        return False, {"job": job.get("status"), "error": job.get("error_code")}
    rid = revision["production_revision_id"]
    manifest = json.loads(http("GET", f"{stack.base}/spatial-outputs/{rid}"
                                f"/files/manifest.json")[2])
    raw_zip = http("GET", f"{stack.base}/spatial-outputs/{rid}/files/package.zip")[2]
    names = zipfile.ZipFile(io.BytesIO(raw_zip)).namelist()
    return (not any(n.endswith(".png") for n in names)
            and not any(e["filename"].endswith(".png") for e in manifest["files"])), {
        "zip_entries": sorted(names),
        "manifest_files": [e["filename"] for e in manifest["files"]]}


def h_r2_cancel_monotone(stack: Stack):
    """R2：生成中取消为单调终态，晚到渲染不得把 cancelled 改回 running/succeeded。"""
    rev = stack.import_layout("A")
    stack.adopt(rev)
    os.environ["RKD_STUB_RENDER_MODE"] = "wait"
    stack.gate.clear(); stack.entered.clear()
    try:
        code, gen, _ = stack.submit(rev, "w2c-r2-cancel-0001")
        job_id = gen["item"]["job_id"]
        if not stack.entered.wait(timeout=20):
            return False, {"stage": "render_not_entered", "job": job_id}
        ccode, cdata, _ = http("POST", f"{stack.base}/spatial-outputs/{job_id}/cancel", {})
        cancel_ok = ccode == 200 and cdata.get("item", {}).get("status") == "cancelled"
        stack.gate.set()
        job = stack.wait_job(job_id)
        state = stack.state(f"?job_id={job_id}")
        # 晚到的阶段更新/登记不得复活任务
        again = http("POST", f"{stack.base}/spatial-outputs/{job_id}/cancel", {})
        revisions = [r for r in state.get("revisions") or [] if r["job_id"] == job_id]
        return (cancel_ok and job["status"] == "cancelled" and not revisions
                and again[0] in (200, 409)), {
            "cancel_status": ccode, "cancel_body": cdata.get("item", {}).get("status"),
            "final_status": job["status"], "final_phase": job.get("phase"),
            "revisions_registered": len(revisions), "second_cancel": again[0]}
    finally:
        os.environ["RKD_STUB_RENDER_MODE"] = "fast"
        stack.gate.set()


def h_r2_binding_matrix(stack: Stack):
    """R2：当前采用版本换版后，旧成果必须是历史预览，不得冒充当前成果。"""
    rev_a = stack.import_layout("A")
    stack.adopt(rev_a)
    _, gen_a, _ = stack.submit(rev_a, "w2c-r2-bind-a-0001")
    job_a = stack.wait_job(gen_a["item"]["job_id"])
    rev_b = stack.import_layout("B")
    stack.adopt(rev_b)
    _, gen_b, _ = stack.submit(rev_b, "w2c-r2-bind-b-0001")
    job_b = stack.wait_job(gen_b["item"]["job_id"])
    state = stack.state()
    revs = {r["job_id"]: r for r in state.get("revisions") or []}
    ra, rb = revs.get(job_a["job_id"]), revs.get(job_b["job_id"])
    if not ra or not rb:
        return False, {"jobs": [job_a["status"], job_b["status"]],
                       "revisions": list(revs), "note": "旧成果被最新成功成果覆盖"}
    current = state.get("revision") or {}
    return (ra.get("binding_status") == "historical_preview"
            and rb.get("binding_status") == "current_adopted"
            and current.get("job_id") == job_b["job_id"]
            and ra.get("option_revision_id") == rev_a["option_revision_id"]), {
        "binding_a": ra.get("binding_status"), "binding_b": rb.get("binding_status"),
        "binding_a_facts": (ra.get("package") or {}).get("binding"),
        "current_job": current.get("job_id"),
        "job_a": job_a["job_id"], "job_b": job_b["job_id"],
        "revisions_listed": len(state.get("revisions") or [])}


def h_r2_failed_then_retry(stack: Stack):
    """R2：失败不登记半份成果；显式重试关联原任务；幂等键语义清晰。"""
    rev = stack.import_layout("A")
    stack.adopt(rev)
    # 让本次渲染抛错
    original = stack.spatial_ai.renderer

    def boom(*_a, **_k):
        raise RuntimeError("stub render failure")

    stack.spatial_ai.renderer = boom
    try:
        code, gen, _ = stack.submit(rev, "w2c-r2-fail-0001")
        job_id = gen["item"]["job_id"]
        failed = stack.wait_job(job_id)
    finally:
        stack.spatial_ai.renderer = original
    state = stack.state(f"?job_id={job_id}")
    no_revision = not [r for r in state.get("revisions") or [] if r["job_id"] == job_id]
    # 同一幂等键不得偷偷重跑
    again = stack.submit(rev, "w2c-r2-fail-0001")
    reuse_same = again[1].get("reused") is True and \
        again[1]["item"]["job_id"] == job_id
    rcode, retry, _ = http("POST", f"{stack.base}/spatial-outputs/{job_id}/retry",
                           {"settings": {"render": True, "width": 320, "height": 240,
                                         "samples": 8}},
                           {"Idempotency-Key": "w2c-r2-retry-0001"})
    retried = {}
    if rcode in (200, 202):
        retried = stack.wait_job(retry["item"]["job_id"])
    config = (retry.get("item") or {}).get("config") or {}
    return (failed["status"] == "failed" and no_revision and reuse_same
            and rcode in (200, 202) and retried.get("status") == "succeeded"
            and config.get("retry_of") == job_id), {
        "failed_status": failed["status"], "failed_error": failed.get("error_code"),
        "half_registered": not no_revision, "idempotent_reuse": reuse_same,
        "retry_status_code": rcode, "retried_status": retried.get("status"),
        "retry_of": config.get("retry_of"), "original": job_id}


def h_r2_shared_table_isolation(stack: Stack):
    """R2：共用表内深化量价成果不得污染本页；本页成果也不得被它挤掉。"""
    from rkd_mvp.models import new_id, now_iso
    state_before = stack.state()
    current = state_before.get("revision") or {}
    dev_job_id = new_id("ai-development-job")
    with stack.dev_repo.transaction(ORG, stack.project_id, write=True) as tx:
        tx.insert_job({
            "job_id": dev_job_id, "option_revision_id": current.get("option_revision_id") or "x",
            "adoption_version": 0, "input_hash": "0" * 64, "status": "succeeded",
            "phase": "completed", "attempt_count": 1,
            "settings": {}, "config": {"kind": "ai_development_production"},
            "error_code": None, "error_message": None,
            "idempotency_key": f"dev-{dev_job_id}", "actor_id": "tool",
            "created_at": now_iso(), "updated_at": now_iso()})
        tx.insert_revision({
            "production_revision_id": new_id("ai-production-revision"),
            "job_id": dev_job_id,
            "option_revision_id": current.get("option_revision_id") or "x",
            "set_id": "s", "option_id": "o", "adoption_version": 0,
            "input_hash": "0" * 64, "baseline": {}, "package": {},
            "quantities": {}, "cost": {}, "objects": {}, "materials": {},
            "unknowns": [], "view_mapping": {},
            "formula_version": "ai-development-quantity.v1",
            "measurement_version": "ai-development-measurement.v1",
            "output_version": "ai-development-outputs.v1",
            "actor_id": "tool", "created_at": now_iso(),
        })
    after = stack.state()
    before_rev = current.get("production_revision_id")
    listed = after.get("revisions") or []
    after_ids = {r["production_revision_id"] for r in listed}
    foreign = [r for r in listed
               if (r.get("output_version") or "").startswith("ai-development-outputs")]
    return (bool(before_rev) and before_rev in after_ids and not foreign
            and (after.get("revision") or {}).get("production_revision_id") == before_rev), {
        "before_revision": before_rev,
        "after_revision": (after.get("revision") or {}).get("production_revision_id"),
        "revisions_listed": len(listed),
        "foreign_revisions_in_list": len(foreign),
        "note": "深化量价修订插入共用表后，本页当前成果仍须可见且其修订不得混入本页列表"}


def h_r1_missing_render(stack: Stack):
    """R1 负例：渲染没有产出文件时不得交出“成功完整包”。"""
    rev = stack.import_layout("A")
    stack.adopt(rev)
    original = stack.spatial_ai.renderer

    def no_file(scene_path, out_png, *_a):
        return {"seconds": 0.0, "engine": "stub", "wrote_file": False}

    stack.spatial_ai.renderer = no_file
    try:
        code, gen, _ = stack.submit(rev, "w2c-r1-missing-0001")
        job = stack.wait_job(gen["item"]["job_id"])
    finally:
        stack.spatial_ai.renderer = original
    state = stack.state(f"?job_id={gen['item']['job_id']}")
    registered = [r for r in state.get("revisions") or []
                  if r["job_id"] == gen["item"]["job_id"]]
    return (job["status"] == "failed" and not registered), {
        "status_code": code, "job_status": job["status"],
        "error": job.get("error_code"), "registered": len(registered)}


def h_r1_corrupt_manifest(stack: Stack):
    """R1 负例：清单字节被改动后，不得仍据其校验并交出文件。"""
    rev = stack.import_layout("B")
    stack.adopt(rev)
    code, gen, _ = stack.submit(rev, "w2c-r1-corrupt-0001")
    job = stack.wait_job(gen["item"]["job_id"])
    state = stack.state(f"?job_id={gen['item']['job_id']}")
    revision = state.get("revision") or {}
    if job["status"] != "succeeded":
        return False, {"job": job["status"], "error": job.get("error_code")}
    rid = revision["production_revision_id"]
    manifest_path = (stack.runtime / "projects" / "ai-spatial-outputs"
                     / gen["item"]["job_id"] / "manifest.json")
    original = manifest_path.read_bytes()
    tampered = json.loads(original.decode("utf-8"))
    tampered["files"] = [e for e in tampered["files"] if e["filename"] != "render.png"]
    manifest_path.write_bytes(json.dumps(tampered, ensure_ascii=False).encode("utf-8"))
    try:
        scode, body, _ = http("GET", f"{stack.base}/spatial-outputs/{rid}/files/render.png")
    finally:
        manifest_path.write_bytes(original)
    return (scode == 500 and body.get("error_code") == "MANIFEST_HASH_MISMATCH"), {
        "status": scode, "error_code": body.get("error_code"),
        "note": "清单被改动后必须拒绝，不能把未经校验的清单当可信哈希来源"}


def h_r2_reverse_order_and_restart(stack: Stack):
    """R2：A 慢 B 快反序完成；查询按 job 关联；重启只恢复本批中断任务。"""
    rev_a = stack.import_layout("A")
    rev_b = stack.import_layout("B")
    stack.adopt(rev_a)
    original = stack.spatial_ai.renderer
    slow_gate = threading.Event()

    def slow_render(scene_path, out_png, width, height, samples):
        slow_gate.wait(timeout=30)
        out_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"slow" * 64)
        return {"seconds": 0.0, "engine": "stub"}

    stack.spatial_ai.renderer = slow_render
    try:
        _, gen_a, _ = stack.submit(rev_a, "w2c-r2-order-a-0001")
        stack.spatial_ai.renderer = original
        _, gen_b, _ = stack.submit(rev_b, "w2c-r2-order-b-0001")
        job_b = stack.wait_job(gen_b["item"]["job_id"])
        slow_gate.set()
        job_a = stack.wait_job(gen_a["item"]["job_id"])
    finally:
        stack.spatial_ai.renderer = original
        slow_gate.set()
    stack.adopt(rev_b)
    state = stack.state()
    revs = {r["job_id"]: r for r in state.get("revisions") or []}
    mapped = {job_a["job_id"]: rev_a["option_revision_id"],
              job_b["job_id"]: rev_b["option_revision_id"]}
    mapped_ok = all(revs.get(j) and revs[j]["option_revision_id"] == oid
                    for j, oid in mapped.items())
    # 重启恢复：手工造一个“上一进程遗留 running”任务，只有它被标失败
    from rkd_mvp.models import new_id, now_iso
    orphan = new_id("ai-spatial-job")
    with stack.dev_repo.transaction(ORG, stack.project_id, write=True) as tx:
        tx.insert_job({"job_id": orphan, "option_revision_id": rev_a["option_revision_id"],
                       "adoption_version": 0, "input_hash": "0" * 64, "status": "running",
                       "phase": "measurement", "attempt_count": 1, "settings": {},
                       "config": {"kind": "spatial_outputs"}, "error_code": None,
                       "error_message": None, "idempotency_key": f"orphan-{orphan}",
                       "actor_id": "tool", "created_at": now_iso(),
                       "updated_at": now_iso()})
    recovered = stack.spatial_ai.recover(ORG, stack.project_id)
    after = stack.state()
    orphan_job = next((j for j in after.get("jobs") or [] if j["job_id"] == orphan), {})
    still_there = {r["job_id"] for r in after.get("revisions") or []}
    ordering = {job_a["job_id"]: job_a.get("updated_at"), job_b["job_id"]: job_b.get("updated_at")}
    return (mapped_ok and orphan in (recovered.get("recovered") or [])
            and orphan_job.get("status") == "failed"
            and orphan_job.get("error_code") == "WORKER_RESTARTED"
            and {job_a["job_id"], job_b["job_id"]} <= still_there), {
        "job_a": job_a["status"], "job_b": job_b["status"],
        "finished_order": ordering, "mapped": mapped_ok,
        "recovered": recovered.get("recovered"),
        "orphan_status": orphan_job.get("status"),
        "orphan_error": orphan_job.get("error_code"),
        "historical_bytes_readable": sorted(still_there)}


def h_r3_entry_basis(stack: Stack):
    """R3：通过真实入口冻结材料面与假设单价，成本与面积依据同页对账。"""
    rev = stack.import_layout("A")
    stack.adopt(rev)
    scope = {"kind": "material_face_slice", "declared_by": "executor_manual_fixture",
             "declaration": "人工夹具：两块手写铺装范围，未经现场复核",
             "unit": "mm", "deduction_basis": "keepouts_within_scope",
             "areas": [
                 {"object_id": "FA1", "name": "主展区材料面（夹具）",
                  "polygon_mm": [[5400, 1800], [20400, 1800], [20400, 5200], [5400, 5200]],
                  "material_ref": {"material_id": "M-A", "name": "微水泥",
                                   "spec_status": "assumption"}},
                 {"object_id": "FA2", "name": "中岛材料面（夹具）",
                  "polygon_mm": [[9000, 6200], [16000, 6200], [16000, 11000], [9000, 11000]],
                  "material_ref": {"material_id": "M-B", "name": "橡木地板",
                                   "spec_status": "assumption"}}]}
    code, gen, _ = stack.submit(rev, "w2c-r3-basis-0001", finish_scope=scope,
                                material_unit_prices={"M-A": 800})
    job = stack.wait_job(gen["item"]["job_id"])
    state = stack.state(f"?job_id={gen['item']['job_id']}")
    revision = state.get("revision") or {}
    if job["status"] != "succeeded" or not revision:
        return False, {"job": job.get("status"), "error": job.get("error_code"),
                       "message": job.get("error_message")}
    items = revision["quantities"]["items"]
    finish = find_q({"items": items}, "Q-FLOOR-FINISH")
    cost = revision["cost"]
    html = http("GET", f"{stack.base}/spatial-outputs/"
                f"{revision['production_revision_id']}/files/cost.html")[2].decode("utf-8")
    csv_text = http("GET", f"{stack.base}/spatial-outputs/"
                    f"{revision['production_revision_id']}/files/quantity.csv")[2].decode("utf-8")
    fa1 = (20400 - 5400) * (5200 - 1800) / 1e6           # 40.8 ㎡
    fb = (16000 - 9000) * (11000 - 6200) / 1e6            # 33.6 ㎡
    priced = [k for k in cost["known_items"] if k["quantity_ref"].endswith("M-A")
              or k.get("material_id") == "M-A"]
    unpriced = [k for k in cost.get("unknown_items", []) if "M-B" in json.dumps(k, ensure_ascii=False)]
    # 页面上不能一边写“本页没有金额”一边列出假设金额
    contradiction = ("本页没有金额" in html) and bool(cost["known_items"])
    return (finish is not None and abs((finish.get("value") or 0) - (fa1 + fb)) < 0.05
            and len(cost["known_items"]) == 1
            and abs(cost["known_items"][0]["amount_cny"] - fa1 * 800) < 1.0
            and bool(unpriced) and not contradiction
            and "假设" in html and "Q-FLOOR-FINISH" in csv_text), {
        "finish": {"value": (finish or {}).get("value"), "expected": round(fa1 + fb, 3),
                   "known_status": (finish or {}).get("known_status"),
                   "material_groups": (finish or {}).get("material_groups")},
        "known_items": cost["known_items"], "unpriced_groups": unpriced,
        "html_contradiction": contradiction,
        "csv_has_finish_row": "Q-FLOOR-FINISH" in csv_text}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="after")
    parser.add_argument("--out", default=str(ROOT / "var/evidence/roadmap/W2-收口整改"))
    args = parser.parse_args()
    raw_out = Path(args.out)
    out_dir = raw_out if raw_out.is_absolute() else (ROOT / raw_out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 函数级（不需要服务）
    record("W2C-R1-01", "同一文件集合生成清单与 ZIP，清单所列文件全部在 ZIP 内且字节一致",
           f_r1_package_complete)
    record("W2C-R1-02", "render=false 时清单与 ZIP 都不声明 PNG", f_r1_no_render_no_png)
    record("W2C-R3-01", "L 形手算 24/22，独立复算与主算法不同路径，完成面量保持 unknown",
           f_r3_l_shape_handcheck)
    record("W2C-R3-02", "扣除规则：相交扣区不重复扣、外置扣区为 0、跨边界只扣区内部分",
           f_r3_deduction_rules)
    record("W2C-R3-03", "材料面切片需显式来源；单价不能掩盖未知范围", f_r3_finish_scope)

    runtime = out_dir / f"runtime-{args.label}"
    stack = Stack(runtime)
    try:
        record("W2C-R1-03", "真实 HTTP 下载 ZIP→空目录解压→逐项核对清单（含 PNG 与单下载一致）",
               lambda: h_r1_zip_roundtrip(stack))
        record("W2C-R1-04", "真实入口 render=false：ZIP 与清单均无 PNG",
               lambda: h_r1_render_off(stack))
        record("W2C-R2-01", "生成中取消为单调终态，晚到渲染不得复活，失败/取消不登记半份成果",
               lambda: h_r2_cancel_monotone(stack))
        record("W2C-R2-02", "换版后旧成果标历史预览，当前成果按 job/修订查询",
               lambda: h_r2_binding_matrix(stack))
        record("W2C-R2-03", "失败后显式重试关联原任务，同一幂等键不偷偷重跑",
               lambda: h_r2_failed_then_retry(stack))
        record("W2C-R2-04", "共用表内深化量价成果不污染本页当前成果",
               lambda: h_r2_shared_table_isolation(stack))
        record("W2C-R1-05", "渲染无产出时不得交出成功完整包", lambda: h_r1_missing_render(stack))
        record("W2C-R1-06", "清单字节被改动后拒绝据其校验交付文件",
               lambda: h_r1_corrupt_manifest(stack))
        record("W2C-R2-05", "A/B 反序完成与重启恢复：按 job 关联、只恢复本批中断任务",
               lambda: h_r2_reverse_order_and_restart(stack))
        record("W2C-R3-04", "真实入口冻结材料面与假设单价；成本与面积依据同页且不矛盾",
               lambda: h_r3_entry_basis(stack))
    finally:
        stack.close()

    failed = sum(1 for c in CHECKS if c["result"] != "observed_pass")
    payload = {
        "task_id": "W2-收口整改",
        "schema_version": "rkd-w2-closeout-checks.v1",
        "label": args.label,
        "source_root": str(ROOT),
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "environment": {"python": sys.version.split()[0],
                        "renderer": "controllable stub (no Blender in repro)",
                        "stack": "isolated SQLite + real HTTP server",
                        "external_calls": 0, "keys_used": False},
        "checks": CHECKS,
        "totals": {"observed_pass": len(CHECKS) - failed, "observed_fail": failed},
        "external_calls": 0, "tokens": 0, "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
    }
    path = out_dir / f"repro-{args.label}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"label": args.label, "passed": len(CHECKS) - failed,
                      "failed": failed, "out": str(path)}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
