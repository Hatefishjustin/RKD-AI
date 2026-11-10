"""AI-DESIGN-01c + DELIVERY-01a/01b: real source content and technical drafts."""
from __future__ import annotations

import hashlib
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
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
from rkd_mvp.professional_delivery import (AISourceExtractionService, AITechnicalDeliveryService,
                                           SQLiteAIProfessionalDeliveryRepository)
from rkd_mvp.requirement_service import RequirementService
from rkd_mvp.sqlite_store import SQLiteStore
from rkd_mvp.source_content import build_extraction

ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
ORG = "org-local"
EXTRACTION_SCHEMA = ROOT / "contracts" / "v1" / "ai-source-extraction.schema.json"
HANDOVER_SCHEMA = ROOT / "contracts" / "v1" / "ai-technical-handover.schema.json"


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


def minimal_pdf(text: str | None) -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET\n".encode("ascii") if text else b"0 0 m 100 100 l S\n"
    return b"\n".join([
        b"%PDF-1.4",
        b"1 0 obj\n<< /Type /Catalog >>\nendobj",
        b"2 0 obj\n<< /Type /Page /Contents 3 0 R >>\nendobj",
        b"3 0 obj\n<< /Length " + str(len(content)).encode() + b" >>",
        b"stream", content.rstrip(b"\n"), b"endstream\nendobj",
        b"trailer\n<< /Root 1 0 R >>\n%%EOF",
    ])


class ProfessionalDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        db = self.root / "app.sqlite3"
        self.store = SQLiteStore(db)
        self.files = FileService(db, self.root)
        self.requirements = RequirementService(db)
        repository = SQLiteAIProfessionalDeliveryRepository(db)
        self.extraction_service = AISourceExtractionService(repository, self.files)
        self.requirement_ai = AIRequirementService(
            SQLiteAIRequirementRepository(db), self.requirements, config=requirement_config(),
            provider_factory=lambda config: build_provider(config),
            extraction_service=self.extraction_service,
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
        self.technical_delivery = AITechnicalDeliveryService(
            repository, self.development_ai, self.extraction_service, self.root)
        self.service = ApiService(MVPApp(self.store), self.files, requirement_service=self.requirements,
                                  ai_requirement_service=self.requirement_ai,
                                  ai_design_option_service=self.options_ai,
                                  ai_development_service=self.development_ai,
                                  ai_source_extraction_service=self.extraction_service,
                                  ai_technical_delivery_service=self.technical_delivery,
                                  runtime_root=self.root)
        self.files.seed_ningbo(self.service, FIXTURE_ROOT)

    def tearDown(self):
        self.requirement_ai.wait_for_idle()
        self.options_ai.wait_for_idle()
        self.development_ai.wait_for_idle()
        self.store.close()
        self.directory.cleanup()

    def upload(self, filename: str, data: bytes, project_id: str = NINGBO_PROJECT_ID) -> str:
        initiated = self.files.initiate(ORG, project_id, {"filename": filename, "size_bytes": len(data),
                                                          "sha256": hashlib.sha256(data).hexdigest()})
        self.files.receive(ORG, project_id, initiated["upload_id"], io.BytesIO(data), len(data))
        return self.files.complete(ORG, project_id, initiated["upload_id"], "")["file_id"]

    def prepare_adopted_package(self, key: str):
        brief_job = self.service.submit_ai_requirement(ORG, NINGBO_PROJECT_ID, "tester",
                                                       {"natural_language": "开放交流，入口在左侧，暖木色"},
                                                       f"brief-{key}")["item"]
        self.requirement_ai.wait_for_job(ORG, NINGBO_PROJECT_ID, brief_job["job_id"])
        option_set = self.service.submit_ai_design_options(ORG, NINGBO_PROJECT_ID, "tester", {},
                                                           f"options-{key}")["item"]
        self.options_ai.wait_for_set(ORG, NINGBO_PROJECT_ID, option_set["set_id"])
        state = self.service.get_ai_design_options(ORG, NINGBO_PROJECT_ID)
        option = next(item for item in state["item"]["options"] if item["strategy_id"] == "open-loop")
        self.service.adopt_ai_design_option(
            ORG, NINGBO_PROJECT_ID, "editor",
            {"option_id": option["option_id"], "expected_revision": 1, "expected_version": 0})
        job = self.service.submit_ai_development(ORG, NINGBO_PROJECT_ID, "tester",
                                                 {"expected_version": 1, "settings": {}},
                                                 f"development-{key}")["item"]
        self.development_ai.wait_for_job(ORG, NINGBO_PROJECT_ID, job["job_id"])
        return self.service.get_ai_development(ORG, NINGBO_PROJECT_ID)["item"]["revision"]

    # --- 01c: deterministic, honest content extraction ---

    def test_new_contracts_are_valid_draft202012(self):
        for path in (EXTRACTION_SCHEMA, HANDOVER_SCHEMA):
            Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))

    def test_plain_text_extraction_has_real_locators_and_is_idempotent(self):
        file_id = self.upload("展厅需求说明.txt", "客户希望开放展示。\n入口位于左侧。\n暖木色材料意向。\n".encode("utf-8"))
        result = self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": file_id})
        record = result["item"]
        self.assertEqual(record["status"], "extracted")
        self.assertGreaterEqual(record["segment_count"], 1)
        self.assertIn("line:", record["segments"][0]["locator"])
        self.assertIn("入口位于左侧", "".join(item["text"] for item in record["segments"]))
        self.assertEqual(record["text_sha256"], hashlib.sha256(
            "\n".join(item["text"] for item in record["segments"]).encode("utf-8")).hexdigest())
        again = self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": file_id})
        self.assertEqual(again["status"], "unchanged")
        self.assertEqual(again["item"]["extraction_id"], record["extraction_id"])

    def test_pdf_text_layer_is_extracted_but_never_guessed(self):
        with_text = self.upload("site-note.pdf", minimal_pdf("Showroom 12m x 8m entry left"))
        scanned = self.upload("scanned-plan.pdf", minimal_pdf(None))
        ok = self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": with_text})["item"]
        none = self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": scanned})["item"]
        self.assertEqual(ok["status"], "extracted")
        self.assertIn("Showroom 12m x 8m", ok["segments"][0]["text"])
        self.assertIn("pdf-", ok["segments"][0]["locator"])
        self.assertEqual(none["status"], "no_extractable_text_layer")
        self.assertEqual(none["segments"], [])
        self.assertEqual(none["text_sha256"], None)

    def test_unsupported_formats_and_changed_bytes_are_rejected_honestly(self):
        binary = self.upload("sample.dwg", b"AC1015\x00\x01binary-cad-payload")
        record = self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": binary})["item"]
        self.assertEqual(record["status"], "unsupported_format")
        self.assertEqual(record["segments"], [])
        self.assertIn("不解析", record["status_reason"])
        listed = self.service.get_ai_source_extractions(ORG, NINGBO_PROJECT_ID)["items"]
        self.assertTrue(all(item["status"] != "extracted" for item in listed if item["file_id"] == binary))
        with self.assertRaises(ApiError):
            self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": ""})

    def test_cross_project_file_cannot_be_extracted(self):
        self.service.create_project(ORG, "隔离项目", "project-isolated")
        file_id = self.upload("other.txt", b"other project content", "project-isolated")
        with self.assertRaises(ApiError) as error:
            self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": file_id})
        self.assertEqual(error.exception.code, "NOT_FOUND")

    def test_extraction_enters_local_context_but_never_external_model_manifest(self):
        file_id = self.upload("需求摘录.md", "# 展厅要求\n入口在左侧，暖木色。\n".encode("utf-8"))
        self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": file_id})
        job = self.service.submit_ai_requirement(
            ORG, NINGBO_PROJECT_ID, "tester", {"natural_language": "按原件要求做开放展示"},
            "brief-with-source-content")["item"]
        self.requirement_ai.wait_for_job(ORG, NINGBO_PROJECT_ID, job["job_id"])
        manifest = job["context_manifest"]
        entry = next(item for item in manifest["source_refs"] if item["source_id"] == f"file:{file_id}")
        self.assertEqual(entry["content_status"], "content_extracted")
        self.assertEqual(entry["origin_kind"], "file_content_extraction")
        self.assertEqual(manifest["project_context"]["source_status"], "selected_content_extracted")
        self.assertTrue(any(item["source_id"] == f"file:{file_id}" for item in manifest["local_source_content"]))
        self.assertFalse(manifest["external_project_context_allowed"])
        self.assertNotIn("local_source_content", manifest["provider_manifest"])

    def test_real_model_without_external_approval_receives_no_project_context(self):
        from dataclasses import replace
        file_id = self.upload("私密需求.txt", "入口在左侧。\n".encode("utf-8"))
        self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": file_id})
        service = AIRequirementService(
            SQLiteAIRequirementRepository(self.root / "app.sqlite3"), self.requirements,
            config=replace(requirement_config(), real_model=True, kind="openai_compatible"),
            provider_factory=lambda config: build_provider(config), start_workers=False,
            extraction_service=self.extraction_service)
        manifest = service._context_manifest(ORG, NINGBO_PROJECT_ID, "tester", "按原件设计", {})
        provider_manifest = manifest["provider_manifest"]
        self.assertEqual([item["source_id"] for item in provider_manifest["source_refs"]], ["synthetic-input"])
        self.assertEqual(provider_manifest["content_reading"], "synthetic_input_only")
        self.assertNotIn("local_source_content", provider_manifest)
        self.assertEqual(provider_manifest["project_context"]["budget"]["known_status"], "unknown")

    # --- DELIVERY-01: same-source technical draft ---

    def test_technical_delivery_requires_an_adopted_development_package(self):
        with self.assertRaises(ApiError) as error:
            self.service.submit_ai_technical_delivery(ORG, NINGBO_PROJECT_ID, "tester", {},
                                                      "technical-no-development-1")
        self.assertEqual(error.exception.code, "DEVELOPMENT_REQUIRED")

    def test_same_source_technical_pack_has_seven_verified_files(self):
        file_id = self.upload("材料说明.txt", "暖木色仅示意，产品未定。\n".encode("utf-8"))
        self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": file_id})
        revision = self.prepare_adopted_package("technical-pack")
        result = self.service.submit_ai_technical_delivery(
            ORG, NINGBO_PROJECT_ID, "tester",
            {"expected_revision": revision["production_revision_id"]}, "technical-pack-0001")
        self.assertEqual(result["status"], "draft")
        state = self.service.get_ai_technical_delivery(ORG, NINGBO_PROJECT_ID)
        current = state["item"]
        self.assertEqual(current["status"], "draft")
        kinds = {item["artifact_kind"] for item in current["artifacts"]}
        self.assertEqual(kinds, {"technical_plan_svg", "detail_node_svg", "material_schedule_csv",
                                 "technical_handover_html", "handover_json", "delivery_manifest_json",
                                 "delivery_zip"})
        for artifact in current["artifacts"]:
            metadata, path = self.service.get_ai_technical_delivery_artifact(
                ORG, NINGBO_PROJECT_ID, artifact["artifact_id"])
            data = path.read_bytes()
            self.assertEqual(len(data), metadata["size_bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), metadata["sha256"])
        handover = current["delivery"]["handover"]
        Draft202012Validator(json.loads(HANDOVER_SCHEMA.read_text(encoding="utf-8"))).validate(handover)
        self.assertEqual(handover["object_ids"], [item["object_id"] for item in revision["package"]["objects"]])
        self.assertEqual(handover["production_revision_id"], revision["production_revision_id"])
        self.assertTrue(handover["source_extractions"])
        self.assertFalse(handover["status"]["construction_issue"])
        self.assertFalse(handover["status"]["formal_quote"])
        self.assertEqual(handover["status"]["publication_status"], "not_approved")
        self.assertTrue(all(item["known_status"] == "unknown" and item["value"] is None
                            for item in handover["unsupported_scope"]))
        plan = next(item for item in current["artifacts"] if item["artifact_kind"] == "technical_plan_svg")
        _, plan_path = self.service.get_ai_technical_delivery_artifact(ORG, NINGBO_PROJECT_ID, plan["artifact_id"])
        svg = plan_path.read_text(encoding="utf-8")
        self.assertIn("非施工图", svg)
        self.assertIn(revision["package"]["objects"][0]["object_id"], svg)
        zip_artifact = next(item for item in current["artifacts"] if item["artifact_kind"] == "delivery_zip")
        _, zip_path = self.service.get_ai_technical_delivery_artifact(ORG, NINGBO_PROJECT_ID, zip_artifact["artifact_id"])
        with ZipFile(zip_path) as archive:
            self.assertEqual(len(archive.namelist()), 6)

    def test_unknown_values_and_tampered_artifact_are_not_silently_accepted(self):
        self.prepare_adopted_package("technical-unknown")
        state = self.service.get_ai_technical_delivery(ORG, NINGBO_PROJECT_ID)
        self.assertIsNone(state["item"])
        result = self.service.submit_ai_technical_delivery(ORG, NINGBO_PROJECT_ID, "tester", {},
                                                           "technical-tamper-0001")
        self.assertEqual(result["status"], "draft")
        current = self.service.get_ai_technical_delivery(ORG, NINGBO_PROJECT_ID)["item"]
        csv_artifact = next(item for item in current["artifacts"] if item["artifact_kind"] == "material_schedule_csv")
        _, csv_path = self.service.get_ai_technical_delivery_artifact(ORG, NINGBO_PROJECT_ID, csv_artifact["artifact_id"])
        content = csv_path.read_text(encoding="utf-8-sig")
        self.assertIn("specification_status", content)
        self.assertIn("unknown", content)
        self.assertNotIn(",0,", content)
        csv_path.write_bytes(csv_path.read_bytes() + b"tampered")
        with self.assertRaises(ApiError) as error:
            self.service.get_ai_technical_delivery_artifact(ORG, NINGBO_PROJECT_ID, csv_artifact["artifact_id"])
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")

    def test_stale_baseline_and_repeat_submission_are_handled_explicitly(self):
        revision = self.prepare_adopted_package("technical-stale")
        with self.assertRaises(ApiError) as error:
            self.service.submit_ai_technical_delivery(
                ORG, NINGBO_PROJECT_ID, "tester", {"expected_revision": "stale-revision"},
                "technical-stale-0001")
        self.assertEqual(error.exception.code, "STALE_DEVELOPMENT_REVISION")
        first = self.service.submit_ai_technical_delivery(
            ORG, NINGBO_PROJECT_ID, "tester",
            {"expected_revision": revision["production_revision_id"]}, "technical-stale-0002")
        repeat = self.service.submit_ai_technical_delivery(
            ORG, NINGBO_PROJECT_ID, "tester",
            {"expected_revision": revision["production_revision_id"]}, "technical-stale-0002")
        self.assertEqual(first["item"]["delivery_id"], repeat["item"]["delivery_id"])
        with self.assertRaises(ApiError) as conflict:
            self.service.submit_ai_technical_delivery(
                ORG, NINGBO_PROJECT_ID, "tester",
                {"expected_revision": "another-revision"}, "technical-stale-0002")
        self.assertEqual(conflict.exception.code, "STALE_DEVELOPMENT_REVISION")

    def test_technical_pack_does_not_touch_legacy_production_or_procurement(self):
        before = self.service.get_production(ORG, NINGBO_PROJECT_ID)
        self.prepare_adopted_package("technical-isolation")
        self.service.submit_ai_technical_delivery(ORG, NINGBO_PROJECT_ID, "tester", {},
                                                  "technical-isolation-0001")
        after = self.service.get_production(ORG, NINGBO_PROJECT_ID)
        self.assertEqual(before, after)

    def test_http_extraction_technical_submission_and_download(self):
        file_id = self.upload("http-note.txt", "入口左侧。\n".encode("utf-8"))
        server = create_server(self.service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            connection = HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("POST", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/source-extractions",
                               body=json.dumps({"file_id": file_id}),
                               headers={"X-Organization-Id": ORG, "Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 201)
            self.assertEqual(json.loads(response.read())["item"]["status"], "extracted")
            connection.request("GET", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/source-extractions",
                               headers={"X-Organization-Id": ORG})
            self.assertEqual(json.loads(connection.getresponse().read())["items"][0]["segment_count"], 1)
            self.prepare_adopted_package("technical-http")
            connection.request("POST", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/technical-delivery",
                               body="{}", headers={"X-Organization-Id": ORG,
                                                   "Content-Type": "application/json",
                                                   "Idempotency-Key": "technical-http-0001"})
            self.assertEqual(connection.getresponse().status, 202)
            connection.request("GET", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/technical-delivery",
                               headers={"X-Organization-Id": ORG})
            state = json.loads(connection.getresponse().read())
            artifact = state["item"]["artifacts"][0]
            connection.request("GET", f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai/technical-delivery/artifacts/"
                                      f"{artifact['artifact_id']}/content",
                               headers={"X-Organization-Id": ORG})
            download = connection.getresponse()
            self.assertEqual(download.status, 200)
            self.assertEqual(len(download.read()), artifact["size_bytes"])
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_new_tables_and_artifacts_survive_complete_local_backup_restore(self):
        import sqlite3
        from rkd_mvp.local_backup import create_backup, restore_backup
        file_id = self.upload("backup-note.txt", "入口左侧，暖木色。\n".encode("utf-8"))
        self.service.submit_ai_source_extraction(ORG, NINGBO_PROJECT_ID, {"file_id": file_id})
        self.prepare_adopted_package("technical-backup")
        self.service.submit_ai_technical_delivery(ORG, NINGBO_PROJECT_ID, "tester", {},
                                                  "technical-backup-0001")
        archive = self.root / "complete.zip"
        manifest = create_backup(self.root / "app.sqlite3", archive, self.root, baseline_files=[])
        for table in ("ai_source_extractions", "ai_technical_deliveries", "ai_technical_artifacts"):
            self.assertIn(table, manifest["tables"])
        self.assertEqual(manifest["tables"]["ai_technical_artifacts"]["rows"], 7)
        restored = self.root / "restored"
        report = restore_backup(archive, restored)
        self.assertGreaterEqual(report["tables_verified"], 60)
        from contextlib import closing
        with closing(sqlite3.connect(restored / "runtime/app.sqlite3")) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ai_source_extractions").fetchone()[0], 1)
            rows = connection.execute("SELECT relative_path, sha256, size_bytes FROM ai_technical_artifacts").fetchall()
        self.assertEqual(len(rows), 7)
        for relative, sha256, size in rows:
            data = (restored / "runtime" / relative).read_bytes()
            self.assertEqual(len(data), size)
            self.assertEqual(hashlib.sha256(data).hexdigest(), sha256)

    def test_postgres_route_whitelist_allows_new_endpoints(self):
        from rkd_mvp.postgres_api_service import PostgresApiService
        base = f"/api/v1/projects/{NINGBO_PROJECT_ID}/ai"
        allowed = [("GET", f"{base}/source-extractions"), ("POST", f"{base}/source-extractions"),
                   ("GET", f"{base}/technical-delivery"), ("POST", f"{base}/technical-delivery"),
                   ("GET", f"{base}/technical-delivery/artifacts/artifact-1/content")]
        for method, path in allowed:
            PostgresApiService.validate_route(None, method, path)
        self.assertIn("ai_technical_delivery", PostgresApiService.runtime_info["capabilities"])
        self.assertIn("ai_source_extractions", PostgresApiService.runtime_info["capabilities"])
        with self.assertRaises(ApiError) as rejected:
            PostgresApiService.validate_route(None, "POST", f"{base}/unsupported-domain")
        self.assertEqual(rejected.exception.code, "POSTGRES_DOMAIN_NOT_CONNECTED")

    def test_postgres_migration_and_import_mapping_cover_new_tables(self):
        from rkd_mvp.postgres_migrations import discover_migrations
        from rkd_mvp.postgres_import import TABLES, SUPPORTED_SNAPSHOT_VERSIONS
        root = ROOT / "mvp" / "persistence" / "postgres"
        self.assertEqual([migration.version for migration in discover_migrations(root)], list(range(1, 15)))
        sql = (root / "014_ai_professional_delivery.sql").read_text(encoding="utf-8")
        for table in ("ai_source_extraction", "ai_technical_delivery", "ai_technical_artifact"):
            self.assertIn(f"CREATE TABLE rkd.{table}", sql)
            self.assertIn(f"ALTER TABLE rkd.{table} ENABLE ROW LEVEL SECURITY", sql)
            self.assertIn(f"CREATE POLICY {table}_scope ON rkd.{table}", sql)
        mapping = dict(TABLES)
        self.assertEqual(mapping["ai_source_extractions"], "ai_source_extraction")
        self.assertEqual(mapping["ai_technical_deliveries"], "ai_technical_delivery")
        self.assertEqual(mapping["ai_technical_artifacts"], "ai_technical_artifact")
        self.assertIn(24, SUPPORTED_SNAPSHOT_VERSIONS)

    def test_low_level_extraction_never_invents_content_for_cad_bytes(self):
        record = build_extraction(extraction_id="test-extraction", file_id="f1", filename="plan.dwg",
                                  file_sha256="a" * 64, size_bytes=32, raw=b"\x00\x01AC1015\xff\xfe",
                                  created_at="2026-11-08T00:00:00+00:00")
        self.assertEqual(record["status"], "unsupported_format")
        self.assertEqual(record["segments"], [])
        self.assertIsNone(record["text_sha256"])


if __name__ == "__main__":
    unittest.main()
