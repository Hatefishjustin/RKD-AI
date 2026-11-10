import hashlib
import json
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import unittest

from rkd_mvp.api_service import ApiError, ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.estimate_service import EstimateService
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID
from rkd_mvp.sqlite_store import SQLiteStore
from rkd_mvp.api_server import create_server
import threading
from unittest.mock import patch
from rkd_mvp.estimate_repository import SQLiteEstimateTransaction


FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "ningbo-xiecheng" / "2026-09"


class M1EstimateExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = SQLiteStore(root / "app.sqlite3")
        self.files = FileService(root / "app.sqlite3", root)
        self.estimates = EstimateService(root / "app.sqlite3")
        self.service = ApiService(MVPApp(self.store), self.files, estimate_service=self.estimates)
        self.files.seed_ningbo(self.service, FIXTURE_ROOT)
        self.estimate = self.estimates.seed_ningbo("org-local", NINGBO_PROJECT_ID, FIXTURE_ROOT)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_export_is_real_and_bound_to_revision(self):
        exported = self.service.export_estimate("org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], "test-user")
        self.assertEqual({item["artifact_kind"] for item in exported["items"]}, {"estimate_report_html", "estimate_detail_csv"})
        for item in exported["items"]:
            metadata, path = self.service.get_estimate_artifact("org-local", NINGBO_PROJECT_ID, item["artifact_id"])
            content = path.read_bytes()
            self.assertGreater(len(content), 100)
            self.assertEqual(metadata["size_bytes"], len(content))
            self.assertEqual(metadata["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(metadata["revision_no"], self.estimate["revision_no"])
        again = self.service.export_estimate("org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], "test-user")
        self.assertEqual([item["artifact_id"] for item in again["items"]], [item["artifact_id"] for item in exported["items"]])
        html_item = next(item for item in exported["items"] if item["artifact_kind"] == "estimate_report_html")
        self.assertIn("预算试算", self.service.get_estimate_artifact("org-local", NINGBO_PROJECT_ID, html_item["artifact_id"])[1].read_text(encoding="utf-8"))
        updated = self.estimates.calculate("org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], {"expected_revision": self.estimate["revision_no"], "trial_tax_rate": "0.05", "construction_cost_markup": "0.20", "design_cost_markup": "0.60", "design_cost_net": None}, "test-user")
        self.assertEqual(updated["revision_no"], self.estimate["revision_no"] + 1)
        with self.estimates._db() as connection:
            statuses = connection.execute("SELECT status FROM estimate_artifacts WHERE estimate_id = ? AND revision_no = ?", (self.estimate["estimate_id"], self.estimate["revision_no"])).fetchall()
        self.assertEqual({row["status"] for row in statuses}, {"superseded"})

    def test_artifact_is_project_scoped(self):
        exported = self.service.export_estimate("org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], "test-user")
        with self.assertRaises(ApiError):
            self.service.get_estimate_artifact("other-org", NINGBO_PROJECT_ID, exported["items"][0]["artifact_id"])

    def test_changed_same_size_bytes_are_rejected_on_download_and_reexport(self):
        exported = self.service.export_estimate("org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], "test")
        metadata, path = self.service.get_estimate_artifact("org-local", NINGBO_PROJECT_ID, exported["items"][0]["artifact_id"])
        path.write_bytes(b"X" * metadata["size_bytes"])
        with self.assertRaises(ApiError) as error:
            self.service.get_estimate_artifact("org-local", NINGBO_PROJECT_ID, metadata["artifact_id"])
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")
        with self.assertRaises(ApiError) as error:
            self.service.export_estimate("org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], "test")
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")

    def test_failed_export_rolls_back_rows_and_retry_preserves_old_files(self):
        previous = self.service.export_estimate("org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], "test")
        old = {item["artifact_id"]: self.service.get_estimate_artifact("org-local", NINGBO_PROJECT_ID, item["artifact_id"])[1].read_bytes() for item in previous["items"]}
        self.estimates.calculate("org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], {"expected_revision": 1, "design_cost_net": "1000"}, "test")
        original = SQLiteEstimateTransaction.query
        calls = []
        def failure(tx, operation, params=()):
            if operation == "insert_artifact":
                calls.append(1)
                if len(calls) == 2:
                    raise RuntimeError("late export write failure")
            return original(tx, operation, params)
        with patch.object(SQLiteEstimateTransaction, "query", failure):
            with self.assertRaises(RuntimeError):
                self.service.export_estimate("org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], "test")
        with self.estimates._db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM estimate_artifacts WHERE revision_no=2").fetchone()[0], 0)
        latest = self.service.export_estimate("org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], "test")
        self.assertEqual(len(latest["items"]), 2)
        for artifact, data in old.items():
            self.assertEqual(self.service.get_estimate_artifact("org-local", NINGBO_PROJECT_ID, artifact)[1].read_bytes(), data)

    def test_http_export_and_download_return_real_bytes(self):
        server = create_server(self.service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            path = f"/api/v1/projects/{NINGBO_PROJECT_ID}/estimates/{self.estimate['estimate_id']}/export"
            connection.request("POST", path, headers={"X-Organization-Id": "org-local"})
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 201)
            artifact = payload["items"][0]
            connection.close()
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            download_path = f"/api/v1/projects/{NINGBO_PROJECT_ID}/estimates/artifacts/{artifact['artifact_id']}/content"
            connection.request("GET", download_path, headers={"X-Organization-Id": "org-local"})
            response = connection.getresponse()
            content = response.read()
            self.assertEqual(response.status, 200)
            self.assertEqual(len(content), artifact["size_bytes"])
            self.assertEqual(hashlib.sha256(content).hexdigest(), artifact["sha256"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
