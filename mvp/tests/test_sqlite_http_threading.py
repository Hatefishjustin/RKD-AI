import json
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import unittest

from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.sqlite_store import SQLiteStore


class SQLiteHttpThreadingTests(unittest.TestCase):
    def test_http_requests_use_thread_local_sqlite_connections_and_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "app.sqlite3"
            store = SQLiteStore(db_path)
            server = create_server(ApiService(MVPApp(store)), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]

                def request(method, path, body=None):
                    connection = HTTPConnection("127.0.0.1", port, timeout=3)
                    headers = {"X-Organization-Id": "org-thread"}
                    encoded = None
                    if body is not None:
                        encoded = json.dumps(body).encode("utf-8")
                        headers.update({"Content-Type": "application/json", "Content-Length": str(len(encoded))})
                    connection.request(method, path, body=encoded, headers=headers)
                    response = connection.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                    connection.close()
                    return response.status, payload

                status, project = request("POST", "/api/v1/projects", {"name": "Threaded project"})
                self.assertEqual(status, 201)
                project_id = project["project_id"]
                status, detail = request("GET", f"/api/v1/projects/{project_id}")
                self.assertEqual(status, 200)
                self.assertEqual(detail["name"], "Threaded project")
                status, updated = request(
                    "PATCH",
                    f"/api/v1/projects/{project_id}",
                    {"name": "Renamed project", "expected_version": 0},
                )
                self.assertEqual(status, 200)
                self.assertEqual(updated["version"], 1)
                status, conflict = request(
                    "PATCH",
                    f"/api/v1/projects/{project_id}",
                    {"name": "Stale edit", "expected_version": 0},
                )
                self.assertEqual(status, 409)
                self.assertEqual(conflict["error_code"], "STALE_PROJECT_VERSION")
                status, _ = request(
                    "POST",
                    f"/api/v1/projects/{project_id}/commands",
                    {"command_type": "UnsupportedCommand", "target_id": "target", "payload": {}},
                )
                self.assertEqual(status, 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                store.close()

            with closing(SQLiteStore(db_path)) as restored:
                self.assertEqual(restored.projects[("org-thread", project_id)]["name"], "Renamed project")
                migrations = restored._connection().execute("SELECT version FROM schema_migrations").fetchall()
                self.assertEqual([row[0] for row in migrations], list(range(1, 16)))
                row = restored._connection().execute(
                    "SELECT name, version FROM projects WHERE organization_id = ? AND project_id = ?",
                    ("org-thread", project_id),
                ).fetchone()
                self.assertEqual(row, ("Renamed project", 1))

    def test_project_transaction_rolls_back_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "app.sqlite3"
            store = SQLiteStore(db_path)
            service = ApiService(MVPApp(store))
            project = service.create_project("org-local", "Original")
            with self.assertRaises(RuntimeError):
                with store.transaction():
                    service.update_project(
                        "org-local",
                        project["project_id"],
                        {"name": "Not saved", "expected_version": 0},
                    )
                    raise RuntimeError("abort")
            self.assertEqual(service.get_project("org-local", project["project_id"])["name"], "Original")
            store.close()
            restored = SQLiteStore(db_path)
            self.assertEqual(restored.projects[("org-local", project["project_id"])]["name"], "Original")
            restored.close()


if __name__ == "__main__":
    unittest.main()
