from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import quote

from jsonschema import Draft202012Validator

from rkd_mvp.ai_design_option_provider import DesignOptionConfig, build_design_option_provider
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository
from rkd_mvp.ai_design_option_service import AIDesignOptionService
from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider
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
SCHEMA_PATH = ROOT / "contracts" / "v1" / "ai-design-option.schema.json"
ORG = "org-local"


def requirement_config() -> AIProviderConfig:
    return AIProviderConfig(kind="synthetic", name="本地合成测试通道（非真实 AI）", model_id=None,
                            base_url=None, api_key_present=False, adapter_version="rkd-model-provider.v1",
                            prompt_version="requirement-understanding.zh-CN.v1", schema_version="rkd-ai-design-brief.v1",
                            max_input_chars=8000, max_output_tokens=2000, timeout_seconds=20,
                            external_context_allowed=False, real_model=False, configuration_errors=[])


def option_config() -> DesignOptionConfig:
    return DesignOptionConfig(kind="synthetic", name="本地合成设计通道（非真实 AI）",
                              adapter_version="rkd-design-option-provider.v1",
                              prompt_version="design-option-strategy.zh-CN.v1",
                              schema_version="rkd-ai-design-option.v1", max_candidates=2,
                              real_model=False, configuration_errors=[])


class AIDesignOptionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        db = self.root / "app.sqlite3"
        self.store = SQLiteStore(db)
        self.files = FileService(db, self.root)
        self.requirements = RequirementService(db)
        self.requirement_ai = AIRequirementService(
            SQLiteAIRequirementRepository(db), self.requirements, config=requirement_config(),
            provider_factory=lambda config: build_provider(config),
        )
        self.options_ai = AIDesignOptionService(
            SQLiteAIDesignOptionRepository(db),
            lambda org, project: self.requirement_ai.status(org, project)["item"],
            lambda org, project: {"width": "12", "length": "8",
                                  "boundary_source": "test_parameters_not_site_verified", "obstacles": []},
            self.root, config=option_config(), provider=build_design_option_provider(option_config()),
        )
        self.service = ApiService(MVPApp(self.store), self.files, requirement_service=self.requirements,
                                  ai_requirement_service=self.requirement_ai,
                                  ai_design_option_service=self.options_ai, runtime_root=self.root)
        self.files.seed_ningbo(self.service, FIXTURE_ROOT)

    def tearDown(self):
        self.requirement_ai.wait_for_idle()
        self.options_ai.wait_for_idle()
        self.store.close()
        self.directory.cleanup()

    def brief(self, text: str, key: str):
        item = self.service.submit_ai_requirement(ORG, NINGBO_PROJECT_ID, "tester",
                                                  {"natural_language": text}, key)["item"]
        self.requirement_ai.wait_for_job(ORG, NINGBO_PROJECT_ID, item["job_id"])
        return self.requirement_ai.status(ORG, NINGBO_PROJECT_ID)["item"]

    def options(self, key: str, **extra):
        item = self.service.submit_ai_design_options(ORG, NINGBO_PROJECT_ID, "tester", extra, key)["item"]
        self.options_ai.wait_for_set(ORG, NINGBO_PROJECT_ID, item["set_id"])
        return self.service.get_ai_design_options(ORG, NINGBO_PROJECT_ID)

    def test_schema_is_valid_draft202012(self):
        Draft202012Validator.check_schema(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_two_checked_candidates_have_real_svg_and_no_production_side_effects(self):
        self.brief("开放交流，入口在左侧，暖木色，保留宽阔中心展示面", "brief-options-0001")
        state = self.options("options-0000001")
        current = state["item"]
        self.assertIsNotNone(current)
        self.assertEqual(len(current["options"]), 2)
        signatures = [json.dumps(option["structure_signature"], sort_keys=True) for option in current["options"]]
        self.assertNotEqual(signatures[0], signatures[1])
        for option in current["options"]:
            self.assertEqual(option["validation"]["status"], "passed")
            self.assertGreaterEqual(len(option["validation"]["hard_checks"]), 8)
            self.assertEqual(option["model"]["generation"]["real_model"], False)
            self.assertEqual(option["model"]["lifecycle_status"], "candidate")
            self.assertEqual(len(option["artifacts"]), 1)
            artifact = option["artifacts"][0]
            metadata, path = self.service.get_ai_design_option_artifact(ORG, NINGBO_PROJECT_ID, artifact["artifact_id"])
            data = path.read_bytes()
            self.assertEqual(sha256(data).hexdigest(), metadata["sha256"])
            self.assertIn(b"<svg", data)
        self.assertIsNone(self.service.get_design(ORG, NINGBO_PROJECT_ID)["item"])
        self.assertEqual(self.service.list_procurement_orders(ORG, NINGBO_PROJECT_ID)["items"], [])
        self.assertIsNone(state["adoption"])

    def test_opposite_briefs_change_entrance_material_and_spatial_signature(self):
        self.brief("开放交流，入口在左侧，暖木色", "brief-left-0001")
        first = self.options("options-left-0001")["item"]["options"][0]
        self.brief("安静私密洽谈，入口在右侧，冷灰色，环形动线", "brief-right-0001")
        second = self.options("options-right-0001")["item"]["options"][0]
        self.assertEqual(first["model"]["boundary"]["entrance"]["side"], "left")
        self.assertEqual(second["model"]["boundary"]["entrance"]["side"], "right")
        self.assertNotEqual(first["structure_signature"], second["structure_signature"])
        self.assertNotEqual(first["model"]["materials"][0]["material_id"], second["model"]["materials"][0]["material_id"])

    def test_feedback_changes_model_preserves_entrance_and_reports_diff(self):
        self.brief("开放交流，入口在左侧，暖木色", "brief-feedback-0001")
        state = self.options("options-feedback-0001")
        option = next(item for item in state["item"]["options"] if item["strategy_id"] == "open-loop")
        before = option["model"]
        result = self.service.revise_ai_design_option(
            ORG, NINGBO_PROJECT_ID, "editor",
            {"option_id": option["option_id"], "expected_revision": 1,
             "feedback": "更开放但保留入口", "locks": []},
        )
        revised = result["item"]["model"]
        self.assertEqual(result["item"]["revision_no"], 2)
        self.assertEqual(before["boundary"]["entrance"]["side"], revised["boundary"]["entrance"]["side"])
        before_display = next(item for item in before["objects"] if item["object_id"] == "zone:display")
        after_display = next(item for item in revised["objects"] if item["object_id"] == "zone:display")
        self.assertNotEqual(before_display["shape"]["width"], after_display["shape"]["width"])
        self.assertTrue(result["diff"])
        with self.assertRaises(ApiError) as stale:
            self.service.revise_ai_design_option(
                ORG, NINGBO_PROJECT_ID, "editor",
                {"option_id": option["option_id"], "expected_revision": 1,
                 "feedback": "材质别太冷", "locks": []},
            )
        self.assertEqual(stale.exception.code, "STALE_OPTION_REVISION")
        with self.assertRaises(ApiError) as conflict:
            self.service.revise_ai_design_option(
                ORG, NINGBO_PROJECT_ID, "editor",
                {"option_id": option["option_id"], "expected_revision": 2,
                 "feedback": "入口换右侧但保留入口", "locks": []},
            )
        self.assertEqual(conflict.exception.code, "LOCK_CONFLICT")

    def test_adoption_is_explicit_cas_and_never_triggers_production_sync(self):
        self.brief("开放交流，入口左侧", "brief-adopt-0001")
        option = self.options("options-adopt-0001")["item"]["options"][0]
        result = self.service.adopt_ai_design_option(
            ORG, NINGBO_PROJECT_ID, "editor",
            {"option_id": option["option_id"], "expected_revision": 1, "expected_version": 0},
        )
        self.assertEqual(result["item"]["status"], "adopted_draft")
        self.assertEqual(result["item"]["production_task_status"], "not_started")
        self.assertFalse(result["formal_approval"])
        self.assertFalse(result["production_sync"])
        self.assertIsNone(self.service.get_design(ORG, NINGBO_PROJECT_ID)["item"])
        self.assertEqual(self.service.list_procurement_orders(ORG, NINGBO_PROJECT_ID)["items"], [])
        with self.assertRaises(ApiError) as stale:
            self.service.adopt_ai_design_option(
                ORG, NINGBO_PROJECT_ID, "editor",
                {"option_id": option["option_id"], "expected_revision": 1, "expected_version": 0},
            )
        self.assertEqual(stale.exception.code, "STALE_ADOPTION_VERSION")

    def test_obstacle_negative_fails_set_without_partial_candidates(self):
        self.brief("开放交流，入口左侧", "brief-obstacle-0001")
        item = self.service.submit_ai_design_options(
            ORG, NINGBO_PROJECT_ID, "tester",
            {"obstacles": [{"object_id": "column-1", "name": "测试柱", "shape": {"type": "rect", "x": "4", "y": "2", "width": "2", "length": "2"}}]},
            "options-obstacle-0001",
        )["item"]
        final = self.options_ai.wait_for_set(ORG, NINGBO_PROJECT_ID, item["set_id"])
        self.assertEqual(final["status"], "failed")
        self.assertIn(final["error_code"], {"OBJECT_OBSTACLE_OVERLAP", "ZONE_BLOCKS_CIRCULATION", "PATH_BLOCKED_BY_OBSTACLE"})
        state = self.service.get_ai_design_options(ORG, NINGBO_PROJECT_ID)
        self.assertIsNone(state["item"])

    def test_unconfigured_design_channel_fails_visibly(self):
        self.brief("开放交流", "brief-unconfigured-0001")
        self.options_ai.config = DesignOptionConfig.from_public({
            **option_config().public(), "kind": "unconfigured", "name": "未配置设计候选通道",
            "configuration_errors": ["设计候选模型通道未配置"],
        })
        self.options_ai.provider = None
        item = self.service.submit_ai_design_options(ORG, NINGBO_PROJECT_ID, "tester", {}, "options-unconfigured-0001")["item"]
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["error_code"], "DESIGN_PROVIDER_NOT_CONFIGURED")
        self.assertIsNone(self.service.get_ai_design_options(ORG, NINGBO_PROJECT_ID)["item"])

    def test_http_candidate_generation_and_svg_download(self):
        self.brief("开放交流，入口左侧", "brief-http-0001")
        server = create_server(self.service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            body = b"{}"
            connection.request("POST", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/design-options", body,
                               {"Content-Type": "application/json", "X-Organization-Id": ORG,
                                "Idempotency-Key": "options-http-000001", "Content-Length": str(len(body))})
            response = connection.getresponse()
            self.assertEqual(response.status, 202)
            set_id = json.loads(response.read())["item"]["set_id"]
            self.options_ai.wait_for_set(ORG, NINGBO_PROJECT_ID, set_id)
            status = self.service.get_ai_design_options(ORG, NINGBO_PROJECT_ID)["item"]
            artifact_id = status["options"][0]["artifacts"][0]["artifact_id"]
            connection.request("GET", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/design-options/artifacts/{quote(artifact_id)}/content",
                               headers={"X-Organization-Id": ORG})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            svg = response.read()
            self.assertIn(b"<svg", svg)
            connection.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == "__main__":
    unittest.main()
