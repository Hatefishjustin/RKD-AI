from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from jsonschema import Draft202012Validator

from rkd_mvp.ai_model_provider import (
    AIProviderConfig, OpenAICompatibleProvider, ProviderFailure, ProviderResult,
    SyntheticProvider, build_provider,
)
from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository
from rkd_mvp.ai_requirement_service import AIRequirementService
from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiError, ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID
from rkd_mvp.requirement_service import RequirementService
from rkd_mvp.sqlite_store import SQLiteStore

ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
SCHEMA_PATH = ROOT / "contracts" / "v1" / "ai-design-brief.schema.json"
ORG = "org-local"


def synthetic_config() -> AIProviderConfig:
    return AIProviderConfig(
        kind="synthetic", name="本地合成测试通道（非真实 AI）", model_id=None, base_url=None,
        api_key_present=False, adapter_version="rkd-model-provider.v1",
        prompt_version="requirement-understanding.zh-CN.v1",
        schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
        max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
        real_model=False, configuration_errors=[],
    )


def openai_stub_config() -> AIProviderConfig:
    base = synthetic_config()
    return AIProviderConfig(**{**base.__dict__, "kind": "openai_compatible", "name": "OpenAI-compatible 测试桩",
                               "model_id": "stub-model", "base_url": "http://127.0.0.1:9/v1",
                               "api_key_present": True, "real_model": True})


def unconfigured_config() -> AIProviderConfig:
    base = synthetic_config()
    return AIProviderConfig(**{**base.__dict__, "kind": "unconfigured", "name": "未配置真实模型通道",
                               "configuration_errors": ["RKD_AI_API_KEY 未配置"]})


class BrokenProvider:
    def __init__(self, config: AIProviderConfig) -> None:
        self.config = config

    def generate(self, **kwargs) -> ProviderResult:
        raise ProviderFailure(category="validation", code="MALFORMED_OUTPUT", message="模型输出不是可解析的任务书 JSON")


class SlowSyntheticProvider:
    def __init__(self, config: AIProviderConfig, event: threading.Event) -> None:
        self.config, self.event = config, event
        self.inner = SyntheticProvider(config)

    def generate(self, **kwargs) -> ProviderResult:
        self.event.wait(2)
        return self.inner.generate(**kwargs)


class FakeResponse:
    def __init__(self, payload: bytes, request_id: str) -> None:
        self.payload, self.headers = payload, {"X-Request-Id": request_id}

    def read(self, _size: int) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def open(self, _request, timeout: int):
        return FakeResponse(json.dumps(self.payload, ensure_ascii=False).encode("utf-8"), "stub-request-id")


class AIRequirementUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        db = self.root / "app.sqlite3"
        self.store = SQLiteStore(db)
        self.files = FileService(db, self.root)
        self.requirements = RequirementService(db)
        self.config = synthetic_config()
        self.provider = build_provider(self.config)
        self.ai = AIRequirementService(
            SQLiteAIRequirementRepository(db), self.requirements, config=self.config,
            provider_factory=lambda _config: self.provider,
        )
        self.service = ApiService(MVPApp(self.store), self.files, requirement_service=self.requirements,
                                  ai_requirement_service=self.ai)
        self.files.seed_ningbo(self.service, FIXTURE_ROOT)

    def tearDown(self):
        self.ai.wait_for_idle()
        self.store.close()
        self.directory.cleanup()

    def submit(self, text: str, key: str, **extra):
        result = self.service.submit_ai_requirement(ORG, NINGBO_PROJECT_ID, "test-user",
                                                    {"natural_language": text, **extra}, key)
        return result["item"], self.ai.wait_for_job(ORG, NINGBO_PROJECT_ID, result["item"]["job_id"])

    def test_schema_is_valid_draft202012(self):
        Draft202012Validator.check_schema(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_synthetic_job_creates_candidate_brief_without_design_or_order_side_effects(self):
        _, job = self.submit("主打开放交流，入口在左侧，暖木色，保留宽阔中心展示面", "idem-synthetic-0001")
        self.assertEqual(job["status"], "succeeded")
        state = self.service.get_ai_requirement_status(ORG, NINGBO_PROJECT_ID)
        current = state["item"]
        self.assertIsNotNone(current)
        self.assertEqual(current["brief"]["revision_no"], 1)
        self.assertFalse(current["brief"]["brief"]["generation"]["real_model"])
        self.assertEqual(current["brief"]["brief"]["lifecycle_status"], "candidate")
        self.assertEqual(current["brief"]["brief"]["validation_status"], "structural_check_passed")
        self.assertIn("开放", " ".join(item["statement"] for item in current["brief"]["brief"]["design_intent"]))
        self.assertEqual(current["runs"][0]["status"], "succeeded")
        self.assertIsNone(self.service.get_design(ORG, NINGBO_PROJECT_ID)["item"])
        self.assertEqual(self.service.list_procurement_orders(ORG, NINGBO_PROJECT_ID)["items"], [])
        self.assertGreaterEqual(len(current["brief"]["brief"]["cost"]["unknown_items"]), 2)
        self.assertIsNone(current["brief"]["brief"]["cost"]["total_project_estimate"]["value"])

    def test_opposite_requirements_produce_different_structured_briefs(self):
        _, first_job = self.submit("开放交流，入口在左侧，暖木色", "idem-opposite-0001")
        first = self.service.get_ai_requirement_status(ORG, NINGBO_PROJECT_ID)["item"]["brief"]["brief"]
        _, second_job = self.submit("安静私密洽谈，入口在右侧，冷灰色，独立隔断和环形动线", "idem-opposite-0002")
        second = self.service.get_ai_requirement_status(ORG, NINGBO_PROJECT_ID)["item"]["brief"]["brief"]
        self.assertNotEqual(first_job["input_hash"], second_job["input_hash"])
        self.assertNotEqual(
            [item["statement"] for item in first["design_intent"]],
            [item["statement"] for item in second["design_intent"]],
        )
        self.assertIn("环形", " ".join(item["statement"] for item in second["design_intent"]))

    def test_same_key_same_input_is_idempotent_and_different_input_conflicts(self):
        request = {"natural_language": "中性展厅，待补充设计方向"}
        first = self.service.submit_ai_requirement(ORG, NINGBO_PROJECT_ID, "tester", request, "idem-repeat-0001")["item"]
        self.ai.wait_for_job(ORG, NINGBO_PROJECT_ID, first["job_id"])
        repeated = self.service.submit_ai_requirement(ORG, NINGBO_PROJECT_ID, "tester", request, "idem-repeat-0001")["item"]
        self.assertEqual(first["job_id"], repeated["job_id"])
        with self.assertRaises(ApiError) as conflict:
            self.service.submit_ai_requirement(ORG, NINGBO_PROJECT_ID, "tester",
                                               {"natural_language": "完全不同的输入"}, "idem-repeat-0001")
        self.assertEqual(conflict.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_cross_project_source_is_rejected(self):
        with self.assertRaises(ApiError) as error:
            self.service.submit_ai_requirement(
                ORG, NINGBO_PROJECT_ID, "tester",
                {"natural_language": "测试来源范围", "selected_source_ids": ["file:other-project"]},
                "idem-source-0001",
            )
        self.assertEqual(error.exception.code, "UNKNOWN_SOURCE_ID")

    def test_unconfigured_real_channel_fails_visibly_without_rule_fallback(self):
        self.ai.config = unconfigured_config()
        result = self.service.submit_ai_requirement(
            ORG, NINGBO_PROJECT_ID, "tester", {"natural_language": "测试未配置通道"}, "idem-unconfigured-0001",
        )["item"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "MODEL_NOT_CONFIGURED")
        job = self.service.get_ai_requirement_job(ORG, NINGBO_PROJECT_ID, result["job_id"])["item"]
        self.assertEqual(job["runs"][0]["status"], "failed")
        self.assertEqual(job["briefs"], [])
        self.assertIsNone(self.service.get_ai_requirement_status(ORG, NINGBO_PROJECT_ID)["item"])

    def test_malformed_provider_output_fails_job_without_brief(self):
        self.provider = BrokenProvider(self.config)
        _, job = self.submit("触发畸形输出", "idem-malformed-0001")
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error_code"], "MALFORMED_OUTPUT")
        self.assertEqual(job["briefs"], [])
        self.assertEqual(job["runs"][0]["status"], "failed")

    def test_human_edit_creates_new_revision_and_rejects_stale_or_unknown_source(self):
        _, job = self.submit("开放展示，暖木色", "idem-human-edit-0001")
        current = self.service.get_ai_requirement_status(ORG, NINGBO_PROJECT_ID)["item"]
        edited = deepcopy(current["brief"]["brief"])
        edited["requirements"][0]["statement"] = "人工确认：保留中心展示面"
        saved = self.service.save_ai_requirement_brief(
            ORG, NINGBO_PROJECT_ID, "editor",
            {"job_id": job["job_id"], "expected_revision": 1, "brief": edited,
             "change_reason": "人工修正关键需求"},
        )["item"]
        self.assertEqual(saved["revision_no"], 2)
        self.assertEqual(saved["source_kind"], "human_edit")
        self.assertEqual(saved["brief"]["generation"], current["brief"]["brief"]["generation"])
        with self.assertRaises(ApiError) as stale:
            self.service.save_ai_requirement_brief(
                ORG, NINGBO_PROJECT_ID, "editor",
                {"job_id": job["job_id"], "expected_revision": 1, "brief": edited, "change_reason": "旧版本重试"},
            )
        self.assertEqual(stale.exception.code, "STALE_BRIEF_REVISION")
        invalid = deepcopy(saved["brief"])
        invalid["requirements"][0]["source_refs"] = ["unknown-source"]
        with self.assertRaises(ApiError) as unknown:
            self.service.save_ai_requirement_brief(
                ORG, NINGBO_PROJECT_ID, "editor",
                {"job_id": job["job_id"], "expected_revision": 2, "brief": invalid, "change_reason": "测试未知来源"},
            )
        self.assertEqual(unknown.exception.code, "UNKNOWN_SOURCE_ID")

    def test_late_result_after_cancel_is_discarded(self):
        event = threading.Event()
        self.provider = SlowSyntheticProvider(self.config, event)
        submitted = self.service.submit_ai_requirement(
            ORG, NINGBO_PROJECT_ID, "tester", {"natural_language": "测试迟到结果"}, "idem-cancel-0001",
        )["item"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            job = self.service.get_ai_requirement_job(ORG, NINGBO_PROJECT_ID, submitted["job_id"])["item"]
            if job["status"] == "running":
                break
            time.sleep(0.02)
        self.assertEqual(job["status"], "running")
        self.service.cancel_ai_requirement_job(ORG, NINGBO_PROJECT_ID, submitted["job_id"])
        event.set()
        self.ai.wait_for_idle()
        final = self.ai.wait_for_job(ORG, NINGBO_PROJECT_ID, submitted["job_id"])
        self.assertEqual(final["status"], "cancelled")
        self.assertEqual(final["briefs"], [])
        self.assertEqual(final["runs"][0]["status"], "late_result_discarded")

    def test_http_routes_submit_and_read_persistent_job(self):
        server = create_server(self.service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            body = json.dumps({"natural_language": "开放展示，暖木色，入口左侧"}).encode("utf-8")
            connection.request("POST", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/requirement-understanding", body,
                               {"Content-Type": "application/json", "X-Organization-Id": ORG,
                                "Idempotency-Key": "idem-http-0000001", "Content-Length": str(len(body))})
            response = connection.getresponse()
            self.assertEqual(response.status, 202)
            job_id = json.loads(response.read())["item"]["job_id"]
            self.ai.wait_for_job(ORG, NINGBO_PROJECT_ID, job_id)
            connection.request("GET", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/requirement-understanding",
                               headers={"X-Organization-Id": ORG})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIsNotNone(json.loads(response.read())["item"])
            connection.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_openai_compatible_adapter_parses_local_protocol_stub(self):
        config = openai_stub_config()
        synthetic = SyntheticProvider(config).generate(
            text="协议适配测试", manifest={"source_refs": [{"source_id": "synthetic-input", "origin_kind": "manual_input",
                                                          "locator": "request.natural_language", "content_status": "provided",
                                                          "evidence_status": "unverified"}],
                                          "project_context": {}, "source_conflicts": []},
            input_hash="a" * 64, config_hash=config.fingerprint(), generated_at="2026-11-08T00:00:00+00:00",
        )
        payload = {"choices": [{"message": {"content": json.dumps(synthetic.brief, ensure_ascii=False)}}],
                   "usage": {"prompt_tokens": 11, "completion_tokens": 22}}
        provider = OpenAICompatibleProvider(config, "stub-key", opener=FakeOpener(payload))
        result = provider.generate(
            text="协议适配测试", manifest={"source_refs": [{"source_id": "synthetic-input", "origin_kind": "manual_input",
                                                          "locator": "request.natural_language", "content_status": "provided",
                                                          "evidence_status": "unverified"}]},
            input_hash="a" * 64, config_hash=config.fingerprint(), generated_at="2026-11-08T00:00:00+00:00",
        )
        self.assertTrue(result.brief["generation"]["real_model"])
        self.assertEqual(result.usage["input_tokens"], 11)
        self.assertEqual(result.provider_request_id, "stub-request-id")


if __name__ == "__main__":
    unittest.main()
