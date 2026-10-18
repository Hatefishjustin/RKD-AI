from pathlib import Path
import json
import tempfile
import unittest

from rkd_mvp.api_service import ApiService, ApiError
from rkd_mvp.engine import MVPApp
from rkd_mvp.design_rules import DEFAULT_PROGRAM
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID
from rkd_mvp.requirement_service import RequirementService
from rkd_mvp.sqlite_store import SQLiteStore


FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "ningbo-xiecheng" / "2026-09"


class M3RequirementDraftTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = SQLiteStore(root / "app.sqlite3")
        self.files = FileService(root / "app.sqlite3", root)
        self.requirements = RequirementService(root / "app.sqlite3")
        self.service = ApiService(MVPApp(self.store), self.files, requirement_service=self.requirements)
        self.files.seed_ningbo(self.service, FIXTURE_ROOT)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_rule_based_draft_binds_decisions_and_files(self):
        self.assertIsNone(self.service.get_requirement("org-local", NINGBO_PROJECT_ID)["item"])
        created = self.service.create_requirement_draft("org-local", NINGBO_PROJECT_ID, "test-user", {})["item"]
        self.assertEqual(created["revision_no"], 1)
        self.assertEqual(created["status"], "draft_unconfirmed")
        self.assertEqual(created["source_kind"], "rule_based_draft")
        self.assertEqual(created["content"]["generation_method"], "rule_based_from_project_decisions_and_source_files")
        self.assertEqual(created["content"]["budget"]["contract_target_gross_cny"], "600000.00")
        self.assertIn("mep", created["content"]["scope"]["excluded_scopes"])
        self.assertGreaterEqual(len(created["source_refs"]), 12)
        repeated = self.service.create_requirement_draft("org-local", NINGBO_PROJECT_ID, "test-user", {})["item"]
        self.assertEqual(repeated["revision_no"], 1)
        self.assertEqual(repeated["input_hash"], created["input_hash"])
        edited = self.service.update_requirement("org-local", NINGBO_PROJECT_ID, "test-user", {"expected_revision": 1, "design_program": DEFAULT_PROGRAM, "design_notes": "隔离测试草稿，非现场尺寸", "change_reason": "保存受限场景"})["item"]
        self.assertEqual(edited["source_refs"], created["source_refs"])
        self.assertEqual(edited["content"]["budget"], created["content"]["budget"])
        self.assertEqual(edited["content"]["scope"], created["content"]["scope"])
        design = self.service.create_design("org-local", NINGBO_PROJECT_ID, "test-user", {"expected_revision": 0, "requirement_revision_no": 2, "change_reason": "测试来源交接"})["item"]
        snapshot = next(a for a in design["artifacts"] if a["artifact_kind"] == "model_json")
        output = self.service.get_design_artifact("org-local", NINGBO_PROJECT_ID, snapshot["artifact_id"])[1]
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["requirement"]["source_refs"], created["source_refs"])

    def test_cross_project_read_is_rejected(self):
        with self.assertRaises(ApiError):
            self.service.get_requirement("other-org", NINGBO_PROJECT_ID)


if __name__ == "__main__":
    unittest.main()
