import json
from http.client import HTTPConnection
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.sqlite_store import SQLiteStore


class ApiServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(ApiService(), port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = {"X-Organization-Id": "org-api", **(headers or {})}
        encoded = None
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(encoded))
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        result = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, result

    def test_health_and_project_creation(self):
        status, body = self.request("GET", "/api/health/live", headers={})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        status, project = self.request("POST", "/api/v1/projects", {"name": "API Demo"})
        self.assertEqual(status, 201)
        self.project_id = project["project_id"]
        status, page = self.request("GET", "/api/v1/projects")
        self.assertEqual(status, 200)
        self.assertTrue(any(item["project_id"] == self.project_id for item in page["items"]))

    def test_command_requires_idempotency_and_uses_gateway(self):
        status, project = self.request("POST", "/api/v1/projects", {"name": "Command Demo"})
        self.assertEqual(status, 201)
        path = f"/api/v1/projects/{project['project_id']}/commands"
        request = {"command_type": "CreateRequirementDraft", "target_id": "requirement_api", "expected_version": 0, "payload": {"goal": "api"}}
        status, _ = self.request("POST", path, request)
        self.assertEqual(status, 400)
        status, accepted = self.request("POST", path, request, {"Idempotency-Key": "api-idempotency-0001"})
        self.assertEqual(status, 202)
        self.assertEqual(accepted["status"], "accepted")
        status, duplicate = self.request("POST", path, request, {"Idempotency-Key": "api-idempotency-0001"})
        self.assertEqual(status, 202)
        self.assertEqual(duplicate["command_id"], accepted["command_id"])

    def test_cross_tenant_artifact_is_not_visible(self):
        service = self.server.RequestHandlerClass.service
        context = service.app.context(organization_id="org-owner", project_id="project-owner")
        service.app.bootstrap(context)
        result = service.app.run_happy_path(context)
        path = f"/api/v1/projects/{context.project_id}/artifacts/{result['artifact_ids'][0]}"
        status, _ = self.request("GET", path, headers={"X-Organization-Id": "org-other"})
        self.assertEqual(status, 404)

    def test_api_state_and_idempotency_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "api.sqlite3"
            first_store = SQLiteStore(db_path)
            first = ApiService(MVPApp(first_store))
            project = first.create_project("org-persistent", "Persistent API")
            request = {
                "command_type": "CreateRequirementDraft",
                "target_id": "requirement-persistent",
                "expected_version": 0,
                "payload": {"goal": "survive restart"},
            }
            accepted = first.submit_command("org-persistent", project["project_id"], "user-1", request, "persistent-api-key-0001")
            first_store.close()

            second_store = SQLiteStore(db_path)
            second = ApiService(MVPApp(second_store))
            self.assertTrue(any(item["project_id"] == project["project_id"] for item in second.list_projects("org-persistent")["items"]))
            duplicate = second.submit_command("org-persistent", project["project_id"], "user-1", {**request, "expected_version": 999}, "persistent-api-key-0001")
            self.assertEqual(duplicate["status"], "duplicate")
            self.assertEqual(duplicate["command_id"], accepted["command_id"])
            second_store.close()

    def test_local_identity_header_is_required(self):
        status, body = self.request("GET", "/api/v1/projects", headers={"X-Organization-Id": ""})
        self.assertEqual(status, 401)
        self.assertEqual(body["error_code"], "UNAUTHORIZED")


if __name__ == "__main__":
    unittest.main()
