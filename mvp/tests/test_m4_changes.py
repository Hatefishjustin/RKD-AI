from copy import deepcopy
import hashlib
import tempfile
import unittest
from pathlib import Path
import json
from http.client import HTTPConnection
import threading

from rkd_mvp.api_service import ApiError, ApiService
from rkd_mvp.api_server import create_server
from rkd_mvp.design_rules import DEFAULT_PROGRAM
from rkd_mvp.engine import MVPApp
from rkd_mvp.sqlite_store import SQLiteStore


class M4ChangeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.directory.name) / "app.sqlite3"
        self.store = SQLiteStore(self.db_path)
        self.service = ApiService(MVPApp(self.store))
        self.service.create_project("org-local", "M4 变更测试", "m4-change")
        self.service.create_project("org-local", "隔离项目", "m4-other")
        self.service.create_requirement_draft("org-local", "m4-change", "tester", {})
        self.requirement = self.service.update_requirement("org-local", "m4-change", "tester", {"expected_revision": 1, "design_program": deepcopy(DEFAULT_PROGRAM), "design_notes": "M4 测试", "change_reason": "M4 测试需求"})["item"]
        self.design = self.service.create_design("org-local", "m4-change", "tester", {"expected_revision": 0, "requirement_revision_no": self.requirement["revision_no"], "change_reason": "M4 测试设计"})["item"]
        self.geometry = self.service.create_spatial_revision("org-local", "m4-change", {"width": "10", "length": "5", "pricing": {"unit_cost_net": "100"}}, "tester")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_issue_change_impact_outputs_and_acceptance(self):
        change = self.service.create_change("org-local", "m4-change", "manager", {"title": "调整接待区材料", "reason": "现场材料不可供", "description": "替换为同等规格的本地材料", "design_revision_id": self.design["design_revision_id"], "geometry_revision_id": self.geometry["geometry_revision_id"], "quantity_delta_m2": "2.5", "cost_delta_net": "1800", "schedule_delta_days": "2"}, "m4-change-create-001")
        self.assertEqual(change["status"], "draft")
        duplicate = self.service.create_change("org-local", "m4-change", "manager", {"title": "调整接待区材料", "reason": "现场材料不可供", "description": "替换为同等规格的本地材料", "design_revision_id": self.design["design_revision_id"], "geometry_revision_id": self.geometry["geometry_revision_id"], "quantity_delta_m2": "2.5", "cost_delta_net": "1800", "schedule_delta_days": "2"}, "m4-change-create-001")
        self.assertEqual(duplicate["change_id"], change["change_id"])
        analyzed = self.service.analyze_change("org-local", "m4-change", change["change_id"], "manager", {"expected_version": 1, "notes": "影响已按当前基线计算"}, "m4-change-analyze-001")
        self.assertEqual(analyzed["status"], "analyzed")
        self.assertEqual(analyzed["impact"]["quantity_delta_m2"], "2.5")
        self.assertGreaterEqual(analyzed["impact"]["affected_artifact_count"], 6)
        self.assertEqual(len(analyzed["artifacts"]), 3)
        for artifact in analyzed["artifacts"]:
            metadata, path = self.service.get_change_artifact("org-local", "m4-change", artifact["artifact_id"])
            self.assertEqual(metadata["size_bytes"], path.stat().st_size)
            self.assertEqual(metadata["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        accepted = self.service.accept_change("org-local", "m4-change", change["change_id"], "responsible-person", {"conclusion": "accepted", "checklist": ["材料规格已核对", "影响范围已复核"], "evidence_ref": "acceptance://m4-01", "note": "允许进入本地试用施工记录"}, "m4-change-accept-001")
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["acceptances"][0]["conclusion"], "accepted")
        replay = self.service.accept_change("org-local", "m4-change", change["change_id"], "responsible-person", {"conclusion": "accepted", "checklist": ["材料规格已核对", "影响范围已复核"], "evidence_ref": "acceptance://m4-01", "note": "允许进入本地试用施工记录"}, "m4-change-accept-001")
        self.assertEqual(len(replay["acceptances"]), 1)
        self.assertEqual(replay["version"], accepted["version"])
        with self.assertRaises(ApiError) as closed:
            self.service.analyze_change("org-local", "m4-change", change["change_id"], "manager", {"expected_version": accepted["version"]}, "m4-change-analyze-after-accept")
        self.assertEqual(closed.exception.code, "CHANGE_STATE")
        with self.assertRaises(ApiError) as isolated:
            self.service.get_change("org-local", "m4-other", change["change_id"])
        self.assertEqual(isolated.exception.status, 404)

    def test_change_requires_analysis_and_survives_restart(self):
        change = self.service.create_change("org-local", "m4-change", "manager", {"title": "现场尺寸调整", "reason": "现场复测", "description": "重新确认区域尺寸"}, "m4-change-restart-001")
        with self.assertRaises(ApiError) as not_ready:
            self.service.accept_change("org-local", "m4-change", change["change_id"], "manager", {"conclusion": "accepted", "evidence_ref": "acceptance://not-ready"}, "m4-change-not-ready")
        self.assertEqual(not_ready.exception.code, "CHANGE_NOT_READY")
        self.store.close()
        restored = SQLiteStore(self.db_path)
        service = ApiService(MVPApp(restored))
        self.assertEqual(service.get_change("org-local", "m4-change", change["change_id"])["title"], "现场尺寸调整")
        restored.close()

    def test_http_change_analysis_and_acceptance(self):
        server = create_server(self.service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def request(method, path, body=None, key=None):
                connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
                headers = {"X-Organization-Id": "org-local", "Content-Type": "application/json"}
                if key:
                    headers["Idempotency-Key"] = key
                encoded = json.dumps(body).encode() if body is not None else None
                if encoded:
                    headers["Content-Length"] = str(len(encoded))
                connection.request(method, path, body=encoded, headers=headers)
                response = connection.getresponse()
                payload = json.loads(response.read().decode())
                connection.close()
                return response.status, payload

            status, change = request("POST", "/api/v1/projects/m4-change/changes", {"title": "HTTP 现场变更", "reason": "复测", "description": "更新材料规格", "design_revision_id": self.design["design_revision_id"], "geometry_revision_id": self.geometry["geometry_revision_id"]}, "http-change-create-001")
            self.assertEqual(status, 201)
            status, analyzed = request("POST", f"/api/v1/projects/m4-change/changes/{change['change_id']}/analyze", {"expected_version": 1}, "http-change-analyze-001")
            self.assertEqual(status, 200)
            self.assertEqual(analyzed["status"], "analyzed")
            artifact_id = analyzed["artifacts"][0]["artifact_id"]
            status, body = request("GET", f"/api/v1/projects/m4-change/changes/artifacts/{artifact_id}/content")
            self.assertEqual(status, 200)
            self.assertGreater(len(body) if isinstance(body, str) else len(json.dumps(body)), 0)
            status, accepted = request("POST", f"/api/v1/projects/m4-change/changes/{change['change_id']}/acceptance", {"conclusion": "accepted", "checklist": ["已核对影响"], "evidence_ref": "http://acceptance/1"}, "http-change-accept-001")
            self.assertEqual(status, 200)
            self.assertEqual(accepted["status"], "accepted")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
