"""W3 R1 永久回归：必须经真实应用/API 组合根执行（ApiService 公共方法）。

覆盖 GPT-6 Astra R1 追加要求：
  * 真实组合根创建并注入 ControlledDesignRuntime（全仓唯一生产注入点，
    两个组合根 ApiService / PostgresApiService 都在启动期接线）；
  * 用户 API submit -> 场地快照 -> 受控 provider -> SQLite 候选 -> 适配/准入
    -> adopt 全链路；
  * 真实模型配置未注入 runtime 不得回退旧路径 / 产生无法采用候选；
  * 启动配置不完整清晰失败；
  * 反馈路径不支持时明确拒绝且原修订不变；
  * 成果登记/下载经 ApiService 公共 API 覆盖完整、无渲染、失败、取消四态，
    并核对 ZIP 字节与 manifest；无渲染只标 preview_incomplete。

测试只调用 ApiService 的公共方法与组合根构造参数（transport opener / renderer
作为组合根依赖注入，与生产注入点一致），不调用任何私有 helper 代替产品入口。
所有模型交换均为本地协议桩，simulated=True，无付费外部调用、无真实密钥。
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import time
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "mvp", ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rkd_mvp.ai_design_option_provider import DesignOptionConfig  # noqa: E402
from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider  # noqa: E402
from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository  # noqa: E402
from rkd_mvp.ai_requirement_service import AIRequirementService  # noqa: E402
from rkd_mvp.api_service import ApiError, ApiService  # noqa: E402
from rkd_mvp.controlled_design_runtime import ControlledRuntimeSetupError  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.postgres_api_service import PostgresApiService  # noqa: E402
from rkd_mvp.requirement_service import RequirementService  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from w3_trust_findings import CapturingOpener, candidate  # noqa: E402

ORG = "org-local"
PROJECT = NINGBO_PROJECT_ID
FIXTURE = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"


def real_config(*, complete: bool = True) -> DesignOptionConfig:
    return DesignOptionConfig(
        kind="openai_compatible", name="本地协议桩（模拟）", adapter_version="stub",
        prompt_version="pv", schema_version="rkd-ai-design-option.v1", max_candidates=2,
        real_model=True,
        configuration_errors=[] if complete else ["RKD_AI_MODEL 未配置"],
        base_url="http://127.0.0.1:9/stub" if complete else None,
        model_id="stub-model" if complete else None,
        api_key_present=complete, max_attempts=2, timeout_seconds=5,
        external_context_allowed=False)


def unconfigured_config() -> DesignOptionConfig:
    return DesignOptionConfig(
        kind="unconfigured", name="未配置", adapter_version="stub", prompt_version="pv",
        schema_version="rkd-ai-design-option.v1", max_candidates=2, real_model=False,
        configuration_errors=["设计候选模型通道未配置"])


def stub_opener() -> CapturingOpener:
    return CapturingOpener({"branch": candidate("branch", 10.3),
                            "loop": candidate("loop", 10.3)})


def ok_renderer(scene_path, out_png, width, height, samples):
    out_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"W3-composition-stub" * 40)
    return {"engine": "stub-renderer", "width": width, "height": height, "samples": samples}


class FailingRenderer:
    def __call__(self, *args, **kwargs):
        raise RuntimeError("stub render failure")


class BlockingRenderer:
    def __init__(self) -> None:
        self.release = threading.Event()

    def __call__(self, *args, **kwargs):
        self.release.wait(timeout=15)
        return {"engine": "blocking-stub"}


class CompositionRootTests(unittest.TestCase):
    """All cases drive the REAL ApiService composition root and public API."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.db = self.root / "app.sqlite3"
        self.store = SQLiteStore(self.db)
        self.files = FileService(self.db, self.root)
        self.requirements = RequirementService(self.db)
        req_cfg = AIProviderConfig(
            kind="synthetic", name="本地合成需求通道（非真实 AI）", model_id=None,
            base_url=None, api_key_present=False, adapter_version="rkd-model-provider.v1",
            prompt_version="requirement-understanding.zh-CN.v1",
            schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
            max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
            real_model=False, configuration_errors=[])
        self.requirement_ai = AIRequirementService(
            SQLiteAIRequirementRepository(self.db), self.requirements, config=req_cfg,
            provider_factory=lambda config: build_provider(config))

    def tearDown(self):
        try:
            self.requirement_ai.wait_for_idle()
        except Exception:  # noqa: BLE001
            pass
        self.store.close()
        self.directory.cleanup()

    def build_service(self, *, config, opener=None, controlled_runtime=None,
                      renderer=ok_renderer):
        """The ONLY service construction path used by these tests: the real
        ApiService composition root with dependency seams injected there."""
        return ApiService(
            MVPApp(self.store), self.files, requirement_service=self.requirements,
            ai_requirement_service=self.requirement_ai, runtime_root=self.root,
            design_option_config=config, design_transport_opener=opener,
            controlled_runtime=controlled_runtime, spatial_renderer=renderer)

    def brief(self, service):
        item = service.submit_ai_requirement(
            ORG, PROJECT, "tester", {"natural_language": "开放交流，入口在左侧，暖木色"},
            "brief-composition-0001")["item"]
        self.requirement_ai.wait_for_job(ORG, PROJECT, item["job_id"])

    def options(self, service, key="options-composition-001"):
        item = service.submit_ai_design_options(ORG, PROJECT, "tester", {}, key)["item"]
        service.ai_design_option_service.wait_for_set(ORG, PROJECT, item["set_id"])
        return service.get_ai_design_options(ORG, PROJECT)

    def adopted_option(self, service):
        self.brief(service)
        state = self.options(service)
        option = state["item"]["options"][0]
        service.adopt_ai_design_option(ORG, PROJECT, "tester", {
            "option_id": option["option_id"], "expected_revision": 1, "expected_version": 0})
        return option

    # ------------------------------------------------------------ R1 happy path
    def test_real_composition_root_generates_and_adopts_through_controlled_chain(self):
        service = self.build_service(config=real_config(), opener=stub_opener())
        self.files.seed_ningbo(service, FIXTURE)
        self.assertIsNotNone(service.controlled_design_runtime,
                             "真实组合根必须创建受控运行时")
        self.assertIs(service.ai_design_option_service.controlled_runtime,
                      service.controlled_design_runtime,
                      "受控运行时必须注入真实设计服务")
        self.brief(service)
        state = self.options(service)
        self.assertEqual(state["sets"][0]["status"], "succeeded")
        option = state["item"]["options"][0]
        model = option["model"]
        self.assertEqual(model["schema_version"], "rkd-ai-design-option.v2")
        self.assertTrue(model.get("spatial"))
        self.assertFalse(model["generation"]["real_model"])
        self.assertEqual(model["spatial"]["source"]["design_origin"]["kind"], "fixture")
        runs = service.controlled_design_runtime.run_service.export_public()
        self.assertTrue(runs)
        self.assertTrue(all(r["simulated"] is True and
                            r["kind"] == "local_protocol_stub_run" for r in runs))
        result = service.adopt_ai_design_option(ORG, PROJECT, "tester", {
            "option_id": option["option_id"], "expected_revision": 1,
            "expected_version": 0})
        self.assertEqual(result["item"]["status"], "adopted_draft")
        self.assertFalse(result["formal_approval"])

    # ------------------------------------------------------- R1 missing runtime
    def test_real_model_config_without_runtime_fails_clearly(self):
        service = self.build_service(config=real_config(), opener=stub_opener())
        self.files.seed_ningbo(service, FIXTURE)
        # Remove only the injected runtime from the real service to emulate an
        # unwired composition; submit must fail closed, never fall back.
        service.ai_design_option_service.controlled_runtime = None
        self.brief(service)
        with self.assertRaises(ApiError) as error:
            service.submit_ai_design_options(
                ORG, PROJECT, "tester", {}, "options-no-runtime-001")
        self.assertEqual(error.exception.code, "CONTROLLED_RUNTIME_REQUIRED")
        self.assertEqual(service.get_ai_design_options(ORG, PROJECT)["item"], None)

    # -------------------------------------------------- R1 incomplete at startup
    def test_incomplete_real_config_fails_at_composition_root(self):
        with self.assertRaises(ControlledRuntimeSetupError) as error:
            self.build_service(config=real_config(complete=False), opener=stub_opener())
        self.assertEqual(error.exception.code, "DESIGN_CONFIG_INCOMPLETE")

    def test_unconfigured_does_not_create_controlled_runtime(self):
        service = self.build_service(config=unconfigured_config(), opener=stub_opener())
        self.assertIsNone(service.controlled_design_runtime)

    # --------------------------------------------------------- R1 feedback gate
    def test_unsupported_feedback_rejected_and_original_revision_preserved(self):
        service = self.build_service(config=real_config(), opener=stub_opener())
        self.files.seed_ningbo(service, FIXTURE)
        option = self.adopted_option(service)
        before = service.get_ai_design_options(ORG, PROJECT)["item"]["options"][0]
        with self.assertRaises(ApiError) as error:
            service.revise_ai_design_option(ORG, PROJECT, "tester", {
                "option_id": option["option_id"], "expected_revision": 1,
                "feedback": "把中岛移到右侧", "locks": []})
        self.assertEqual(error.exception.code, "CONTROLLED_FEEDBACK_PATH_UNSUPPORTED")
        after = service.get_ai_design_options(ORG, PROJECT)["item"]["options"][0]
        self.assertEqual(after["option_revision_id"], before["option_revision_id"])
        self.assertEqual(after["revision_no"], 1)
        self.assertTrue(after["validation"]["controlled"]["admission"]["adoptable"])

    # ------------------------------------------- R5 via real API: four states
    def _output_request(self, option, settings, key):
        return {"option_revision_id": option["option_revision_id"],
                "expected_version": 1, "settings": settings}, key

    def wait_output(self, service, job_id, timeout=10.0):
        """Poll the PUBLIC status API until the job reaches a terminal state."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = service.get_ai_spatial_outputs(ORG, PROJECT, job_id=job_id)["job"]
            if job and job["status"] in {"succeeded", "failed", "cancelled"}:
                return job
            time.sleep(0.02)
        self.fail(f"输出任务 {job_id} 未在 {timeout}s 内结束")

    def test_output_registration_and_download_four_states(self):
        service = self.build_service(config=real_config(), opener=stub_opener(),
                                     renderer=ok_renderer)
        self.files.seed_ningbo(service, FIXTURE)
        option = self.adopted_option(service)

        # complete
        request, key = self._output_request(option, {"render": True}, "out-complete-0001")
        pending = service.submit_ai_spatial_outputs(ORG, PROJECT, "tester", request, key)["item"]
        job = self.wait_output(service, pending["job_id"])
        self.assertEqual(job["status"], "succeeded")
        state = service.get_ai_spatial_outputs(ORG, PROJECT, job_id=job["job_id"])
        revision_id = state["revision"]["production_revision_id"]
        meta, data = service.get_ai_spatial_output_file(ORG, PROJECT, revision_id, "package.zip")
        self.assertTrue(meta["complete"])
        self.assertEqual(meta["delivery_status"], "complete")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest_bytes = archive.read("manifest.json")
            self.assertNotIn("package.zip", archive.namelist())
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        self.assertTrue(manifest["files"])
        for entry in manifest["files"]:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(hashlib.sha256(archive.read(entry["filename"])).hexdigest(),
                                 entry["sha256"])
        self.assertIn(b"PK", data[:2])

        # no render -> preview only
        request, key = self._output_request(option, {"render": False}, "out-preview-0002")
        pending2 = service.submit_ai_spatial_outputs(ORG, PROJECT, "tester", request, key)["item"]
        job2 = self.wait_output(service, pending2["job_id"])
        self.assertEqual(job2["status"], "succeeded")
        rev2 = service.get_ai_spatial_outputs(ORG, PROJECT, job_id=job2["job_id"])["revision"]["production_revision_id"]
        meta2, data2 = service.get_ai_spatial_output_file(ORG, PROJECT, rev2, "package.zip")
        self.assertFalse(meta2["complete"])
        self.assertEqual(meta2["delivery_status"], "preview_incomplete")
        with zipfile.ZipFile(io.BytesIO(data2)) as archive:
            manifest2 = json.loads(archive.read("manifest.json").decode("utf-8"))
        self.assertEqual(manifest2["package_completeness"]["status"], "incomplete")

        # render failed -> no complete package registered.
        # Reuse the same persisted option through a fresh composition root over
        # the SAME store (public root construction), with a failing renderer.
        fail_service = ApiService(
            MVPApp(self.store), self.files, requirement_service=self.requirements,
            ai_requirement_service=self.requirement_ai, runtime_root=self.root,
            design_option_config=real_config(), design_transport_opener=stub_opener(),
            spatial_renderer=FailingRenderer())
        request, key = self._output_request(option, {"render": True}, "out-failed-0003")
        pending_failed = fail_service.submit_ai_spatial_outputs(ORG, PROJECT, "tester", request, key)["item"]
        failed = self.wait_output(fail_service, pending_failed["job_id"])
        self.assertEqual(failed["status"], "failed")
        self.assertIn(failed["error_code"], {"RENDER_FAILED", "SPATIAL_OUTPUT_FAILED"})
        self.assertIsNone(fail_service.get_ai_spatial_outputs(
            ORG, PROJECT, job_id=pending_failed["job_id"])["revision"])

        # cancel while rendering -> terminal cancelled, no complete package
        blocking = BlockingRenderer()
        cancel_service = ApiService(
            MVPApp(self.store), self.files, requirement_service=self.requirements,
            ai_requirement_service=self.requirement_ai, runtime_root=self.root,
            design_option_config=real_config(), design_transport_opener=stub_opener(),
            spatial_renderer=blocking)
        request, key = self._output_request(option, {"render": True}, "out-cancel-0004")
        pending = cancel_service.submit_ai_spatial_outputs(ORG, PROJECT, "tester", request, key)["item"]
        cancelled = cancel_service.cancel_ai_spatial_output(ORG, PROJECT, pending["job_id"])["item"]
        self.assertEqual(cancelled["status"], "cancelled")
        blocking.release.set()
        cancel_service.ai_spatial_output_service.wait_for_idle()
        # Cancellation is terminal for THIS job: no complete package registered.
        self.assertIsNone(cancel_service.get_ai_spatial_outputs(
            ORG, PROJECT, job_id=pending["job_id"])["revision"])

    # ------------------------------------------- PostgreSQL composition root
    def test_postgres_composition_root_wires_runtime_and_fails_closed(self):
        """第二个真实生产组合根：PG 版启动路径同样接线且 fail-closed。

        只覆盖启动期组合（配置 -> 受控运行时 -> 设计服务注入）与失败分支；
        PG 数据面需要活动实例，本机未测，记 not_run，不用桩冒充已跑通。
        """
        class NoDatabase:
            """store 只在请求处理时使用；启动装配不需要连接。"""

            def connection(self, **_kwargs):
                raise RuntimeError("postgres not available in this test")

        root = Path(tempfile.mkdtemp(dir=self.root))
        with self.assertRaises(ControlledRuntimeSetupError) as caught:
            PostgresApiService(NoDatabase(), root,
                               design_option_config=real_config(complete=False))
        self.assertEqual(caught.exception.code, "DESIGN_CONFIG_INCOMPLETE")

        service = PostgresApiService(NoDatabase(), root, design_option_config=real_config(),
                                     design_transport_opener=stub_opener())
        self.assertIsNotNone(service.controlled_design_runtime)
        self.assertIs(service.ai_design_option_service.controlled_runtime,
                      service.controlled_design_runtime)

        unconfigured = PostgresApiService(NoDatabase(), root,
                                          design_option_config=unconfigured_config())
        self.assertIsNone(unconfigured.controlled_design_runtime,
                          "未配置通道不得凭空创建受控运行时")


if __name__ == "__main__":
    unittest.main()
