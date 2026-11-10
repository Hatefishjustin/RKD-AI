from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import quote
from zipfile import ZipFile

from jsonschema import Draft202012Validator

from rkd_mvp.ai_design_option_provider import DesignOptionConfig, build_design_option_provider
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository
from rkd_mvp.ai_design_option_service import AIDesignOptionService
from rkd_mvp.ai_development_repository import SQLiteAIDevelopmentRepository
from rkd_mvp.ai_development_service import AIDevelopmentService
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
SCHEMA_PATH = ROOT / "contracts" / "v1" / "ai-development-package.schema.json"
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


class AIDevelopmentTests(unittest.TestCase):
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
        self.development_ai = AIDevelopmentService(
            SQLiteAIDevelopmentRepository(db), self.options_ai, self.root,
        )
        self.service = ApiService(MVPApp(self.store), self.files, requirement_service=self.requirements,
                                  ai_requirement_service=self.requirement_ai,
                                  ai_design_option_service=self.options_ai,
                                  ai_development_service=self.development_ai, runtime_root=self.root)
        self.files.seed_ningbo(self.service, FIXTURE_ROOT)

    def tearDown(self):
        self.requirement_ai.wait_for_idle()
        self.options_ai.wait_for_idle()
        self.development_ai.wait_for_idle()
        self.store.close()
        self.directory.cleanup()

    def prepare(self, key: str, text: str = "开放交流，入口在左侧，暖木色"):
        brief_job = self.service.submit_ai_requirement(ORG, NINGBO_PROJECT_ID, "tester",
                                                       {"natural_language": text}, f"brief-{key}")["item"]
        self.requirement_ai.wait_for_job(ORG, NINGBO_PROJECT_ID, brief_job["job_id"])
        option_set = self.service.submit_ai_design_options(ORG, NINGBO_PROJECT_ID, "tester", {},
                                                           f"options-{key}")["item"]
        self.options_ai.wait_for_set(ORG, NINGBO_PROJECT_ID, option_set["set_id"])
        status = self.service.get_ai_design_options(ORG, NINGBO_PROJECT_ID)
        option = next(item for item in status["item"]["options"] if item["strategy_id"] == "open-loop")
        adoption = self.service.adopt_ai_design_option(
            ORG, NINGBO_PROJECT_ID, "editor",
            {"option_id": option["option_id"], "expected_revision": 1, "expected_version": 0},
        )["item"]
        return option, adoption

    def generate(self, key: str, settings: dict | None = None, expected_version: int = 1):
        item = self.service.submit_ai_development(
            ORG, NINGBO_PROJECT_ID, "tester",
            {"expected_version": expected_version, "settings": settings or {}}, key,
        )["item"]
        self.development_ai.wait_for_job(ORG, NINGBO_PROJECT_ID, item["job_id"])
        return self.service.get_ai_development(ORG, NINGBO_PROJECT_ID)

    def test_schema_is_valid_draft202012(self):
        Draft202012Validator.check_schema(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_adoption_is_required(self):
        with self.assertRaises(ApiError) as error:
            self.service.submit_ai_development(ORG, NINGBO_PROJECT_ID, "tester",
                                               {"expected_version": 0, "settings": {}}, "development-no-adopt-1")
        self.assertEqual(error.exception.code, "ADOPTION_REQUIRED")

    def test_same_source_package_creates_real_files_and_known_local_quote(self):
        self.prepare("same-source")
        state = self.generate("development-known-0001",
                              {"unit_cost_net": "100", "source_label": "明确标记的测试成本"})
        current = state["item"]
        self.assertIsNotNone(current)
        self.assertEqual(current["status"], "draft")
        revision = current["revision"]
        self.assertFalse(state["formal_quote"])
        self.assertFalse(state["legacy_production_sync"])
        self.assertIsNone(self.service.get_design(ORG, NINGBO_PROJECT_ID)["item"])
        self.assertIsNone(self.service.get_production(ORG, NINGBO_PROJECT_ID)["item"])
        self.assertEqual(self.service.list_procurement_orders(ORG, NINGBO_PROJECT_ID)["items"], [])
        floor_items = [item for item in revision["quantities"] if item["cost_scope"] == "floor_net_area"]
        self.assertGreaterEqual(len(floor_items), 3)
        total = sum(Decimal(item["quantity"]) for item in floor_items)
        quote = revision["cost"]["quote"]
        self.assertEqual(Decimal(quote["quantity"]), total)
        net = (total * Decimal("100") * Decimal("1.20")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tax = (net * Decimal("0.05")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.assertEqual(Decimal(quote["sale_gross"]), net + tax)
        self.assertEqual(quote["status"], "draft")
        self.assertFalse(revision["package"]["status"]["formal_quote"])
        self.assertFalse(revision["package"]["status"]["external_effects_enabled"])
        self.assertEqual(revision["package"]["status"]["procurement_status"], "not_started")
        kinds = {item["artifact_kind"] for item in current["artifacts"]}
        self.assertEqual(kinds, {"plan_svg", "isometric_svg", "model_gltf", "development_json",
                                 "quantity_csv", "cost_html", "manifest_json", "package_zip"})
        by_kind = {item["artifact_kind"]: item for item in current["artifacts"]}
        for artifact in current["artifacts"]:
            metadata, path = self.service.get_ai_development_artifact(ORG, NINGBO_PROJECT_ID, artifact["artifact_id"])
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), metadata["sha256"])
        gltf = json.loads(self.service.get_ai_development_artifact(ORG, NINGBO_PROJECT_ID,
                                                                   by_kind["model_gltf"]["artifact_id"])[1].read_text(encoding="utf-8"))
        self.assertEqual(gltf["asset"]["version"], "2.0")
        self.assertTrue(gltf["extras"]["node_object_map"])
        self.assertIn("object_id", gltf["nodes"][0]["extras"])
        manifest = json.loads(self.service.get_ai_development_artifact(ORG, NINGBO_PROJECT_ID,
                                                                        by_kind["manifest_json"]["artifact_id"])[1].read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["files"]), 6)
        self.assertEqual(len(manifest["node_object_map"]), len(gltf["extras"]["node_object_map"]))
        with ZipFile(self.service.get_ai_development_artifact(ORG, NINGBO_PROJECT_ID,
                                                              by_kind["package_zip"]["artifact_id"])[1]) as archive:
            self.assertEqual(len(archive.namelist()), 7)
        iso = self.service.get_ai_development_artifact(ORG, NINGBO_PROJECT_ID,
                                                       by_kind["isometric_svg"]["artifact_id"])[1].read_bytes()
        self.assertIn(b"<svg", iso)

    def test_missing_unit_cost_keeps_amounts_unknown_without_zero(self):
        self.prepare("unknown-cost")
        state = self.generate("development-unknown-0001")
        revision = state["item"]["revision"]
        quote = revision["cost"]["quote"]
        self.assertEqual(quote["status"], "unknown_cost")
        self.assertIsNone(quote["cost_net"])
        self.assertIsNone(quote["sale_gross"])
        self.assertIsNone(revision["cost"]["total_project_estimate"]["value"])
        for item in revision["unknowns"]:
            self.assertIsNone(item["value"])
            self.assertEqual(item["known_status"], "unknown")

    def test_stale_adoption_version_and_idempotency_conflict_are_rejected(self):
        self.prepare("stale")
        with self.assertRaises(ApiError) as stale:
            self.service.submit_ai_development(ORG, NINGBO_PROJECT_ID, "tester",
                                               {"expected_version": 0, "settings": {}}, "development-stale-0001")
        self.assertEqual(stale.exception.code, "STALE_ADOPTION_VERSION")
        self.generate("development-idem-0001", {"unit_cost_net": "100"})
        with self.assertRaises(ApiError) as conflict:
            self.service.submit_ai_development(ORG, NINGBO_PROJECT_ID, "tester",
                                               {"expected_version": 1,
                                                "settings": {"unit_cost_net": "200"}}, "development-idem-0001")
        self.assertEqual(conflict.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_feedback_on_adopted_option_marks_package_source_outdated(self):
        option, _ = self.prepare("outdated")
        self.generate("development-outdated-0001", {"unit_cost_net": "100"})
        self.service.revise_ai_design_option(
            ORG, NINGBO_PROJECT_ID, "editor",
            {"option_id": option["option_id"], "expected_revision": 1,
             "feedback": "材质别太冷", "locks": []},
        )
        state = self.service.get_ai_development(ORG, NINGBO_PROJECT_ID)
        self.assertEqual(state["item"]["status"], "source_outdated")
        self.assertIsNotNone(state["item"]["revision"])

    def test_tampered_artifact_is_rejected(self):
        self.prepare("tamper")
        state = self.generate("development-tamper-0001", {"unit_cost_net": "100"})
        artifact = next(item for item in state["item"]["artifacts"] if item["artifact_kind"] == "plan_svg")
        _, path = self.service.get_ai_development_artifact(ORG, NINGBO_PROJECT_ID, artifact["artifact_id"])
        path.write_bytes(b"changed")
        with self.assertRaises(ApiError) as error:
            self.service.get_ai_development_artifact(ORG, NINGBO_PROJECT_ID, artifact["artifact_id"])
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")

    def test_http_status_submit_and_artifact_download(self):
        self.prepare("http")
        server = create_server(self.service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            body = json.dumps({"expected_version": 1,
                               "settings": {"unit_cost_net": "100", "source_label": "HTTP 测试价源"}}).encode("utf-8")
            connection.request("POST", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/development-production", body,
                               {"Content-Type": "application/json", "X-Organization-Id": ORG,
                                "Idempotency-Key": "development-http-000001", "Content-Length": str(len(body))})
            response = connection.getresponse()
            self.assertEqual(response.status, 202)
            job_id = json.loads(response.read())["item"]["job_id"]
            self.development_ai.wait_for_job(ORG, NINGBO_PROJECT_ID, job_id)
            state = self.service.get_ai_development(ORG, NINGBO_PROJECT_ID)
            artifact = state["item"]["artifacts"][0]
            connection.request("GET", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/development-production/artifacts/{quote(artifact['artifact_id'])}/content",
                               headers={"X-Organization-Id": ORG})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            data = response.read()
            self.assertEqual(sha256(data).hexdigest(), artifact["sha256"])
            connection.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == "__main__":
    unittest.main()
