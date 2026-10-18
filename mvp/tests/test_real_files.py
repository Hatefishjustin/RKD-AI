from __future__ import annotations

import hashlib
from io import BytesIO
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiService
from rkd_mvp.api_service import ApiError
from rkd_mvp.engine import MVPApp
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID
from rkd_mvp.sqlite_store import SQLiteStore


class RealFilesTests(unittest.TestCase):
    def test_http_upload_receives_bytes_and_scopes_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SQLiteStore(root / "app.sqlite3")
            files = FileService(root / "app.sqlite3", root)
            service = ApiService(MVPApp(store), files)
            project = service.create_project("org-local", "Files test")
            other = service.create_project("org-local", "Other project")
            server = create_server(service, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def request(method, path, body=b"", *, organization="org-local", content_type="application/octet-stream"):
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                connection.request(method, path, body=body, headers={
                    "X-Organization-Id": organization,
                    "Content-Type": content_type,
                    "Content-Length": str(len(body)),
                })
                response = connection.getresponse()
                result = response.read()
                status = response.status
                headers = response.headers
                connection.close()
                return status, result, headers

            prefix = f"/api/v1/projects/{project['project_id']}"
            content = b"%PDF-1.7\nreal byte payload\n"
            expected_hash = hashlib.sha256(content).hexdigest()
            try:
                def initiate(filename="drawing.pdf", sha256=expected_hash):
                    status, body, _ = request("POST", f"{prefix}/uploads", json.dumps({
                        "filename": filename, "size_bytes": len(content), "sha256": sha256,
                    }).encode(), content_type="application/json")
                    self.assertEqual(status, 201)
                    return json.loads(body)["upload_id"]

                interrupted = initiate()
                status, _, _ = request("POST", f"{prefix}/uploads/{interrupted}/complete", b"{}", content_type="application/json")
                self.assertEqual(status, 409)
                upload_id = initiate()
                status, body, _ = request("PUT", f"{prefix}/uploads/{upload_id}/content", content)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["received_sha256"], expected_hash)
                status, _, _ = request("POST", f"{prefix}/uploads/{upload_id}/complete", json.dumps({
                    "completed_sha256": "0" * 64,
                }).encode(), content_type="application/json")
                self.assertEqual(status, 409)
                status, body, _ = request("POST", f"{prefix}/uploads/{upload_id}/complete", json.dumps({
                    "completed_sha256": expected_hash,
                }).encode(), content_type="application/json")
                self.assertEqual(status, 201)
                file_id = json.loads(body)["file_id"]
                status, body, _ = request("GET", f"{prefix}/files")
                self.assertEqual(status, 200)
                listed = json.loads(body)["items"][0]
                self.assertEqual(listed["sha256"], expected_hash)
                status, body, headers = request("GET", listed["download_url"], organization="")
                self.assertEqual(status, 200)
                self.assertEqual(body, content)
                self.assertIn("attachment", headers["Content-Disposition"])
                status, _, _ = request("GET", listed["download_url"] + "bad", organization="")
                self.assertEqual(status, 401)
                status, body, headers = request("GET", f"{prefix}/files/{file_id}/content?preview=1")
                self.assertEqual(status, 200)
                self.assertEqual(body, content)
                self.assertIn("inline", headers["Content-Disposition"])
                status, _, _ = request("GET", f"/api/v1/projects/{other['project_id']}/files/{file_id}/content")
                self.assertEqual(status, 404)
                status, _, _ = request("GET", f"{prefix}/files/{file_id}/content", organization="org-other")
                self.assertEqual(status, 404)
                next_upload = initiate()
                status, _, _ = request("PUT", f"{prefix}/uploads/{next_upload}/content", content)
                self.assertEqual(status, 200)
                status, body, _ = request("POST", f"{prefix}/uploads/{next_upload}/complete", b"{}", content_type="application/json")
                self.assertEqual(status, 201)
                self.assertEqual(json.loads(body)["revision"], 2)
                status, body, _ = request("GET", f"{prefix}/files")
                self.assertEqual(status, 200)
                self.assertEqual([item["revision"] for item in json.loads(body)["items"]], [1, 2])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                store.close()

            restored = SQLiteStore(root / "app.sqlite3")
            restored_files = FileService(root / "app.sqlite3", root)
            metadata, path = restored_files.get_content("org-local", project["project_id"], file_id)
            self.assertEqual(metadata["size_bytes"], len(content))
            self.assertEqual(path.read_bytes(), content)
            restored.close()

    def test_interrupted_stream_and_declared_hash_do_not_register_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SQLiteStore(root / "app.sqlite3")
            files = FileService(root / "app.sqlite3", root)
            service = ApiService(MVPApp(store), files)
            project = service.create_project("org-local", "Interrupted test")
            project_id = project["project_id"]
            upload = service.initiate_upload("org-local", project_id, {
                "filename": "partial.pdf", "size_bytes": 8, "sha256": "0" * 64,
            })
            with self.assertRaises(ApiError) as error:
                service.receive_upload("org-local", project_id, upload["upload_id"], BytesIO(b"%PDF"), 8)
            self.assertEqual(error.exception.code, "INCOMPLETE_UPLOAD")
            self.assertEqual(files._upload("org-local", project_id, upload["upload_id"])["status"], "initiated")
            self.assertEqual(service.list_files("org-local", project_id)["items"], [])
            service.receive_upload("org-local", project_id, upload["upload_id"], BytesIO(b"%PDF-1.0"), 8)
            with self.assertRaises(ApiError) as error:
                service.complete_upload("org-local", project_id, upload["upload_id"], hashlib.sha256(b"%PDF-1.0").hexdigest())
            self.assertEqual(error.exception.code, "UPLOAD_HASH_MISMATCH")
            self.assertEqual(service.list_files("org-local", project_id)["items"], [])
            store.close()

    def test_ningbo_seed_is_verified_and_does_not_overwrite_project(self):
        fixture = Path(__file__).resolve().parents[2] / "fixtures" / "ningbo-xiecheng" / "2026-09"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SQLiteStore(root / "app.sqlite3")
            files = FileService(root / "app.sqlite3", root)
            service = ApiService(MVPApp(store), files)
            files.seed_ningbo(service, fixture)
            imported = files.list_files("org-local", NINGBO_PROJECT_ID)["items"]
            self.assertEqual(len(imported), 7)
            self.assertEqual({item["source_kind"] for item in imported}, {"seed_fixture"})
            self.assertTrue(all(files.get_content("org-local", NINGBO_PROJECT_ID, item["file_id"])[1].is_file() for item in imported))
            dwg = next(item for item in imported if item["kind"] == "cad_floor_plan_dwg")
            server = create_server(service, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request(
                    "GET", f"/api/v1/projects/{NINGBO_PROJECT_ID}/files/{dwg['file_id']}/content",
                    headers={"X-Organization-Id": "org-local"},
                )
                response = connection.getresponse()
                downloaded = response.read()
                self.assertEqual(response.status, 200)
                self.assertEqual(hashlib.sha256(downloaded).hexdigest(), dwg["sha256"])
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
            decisions = files.list_decisions("org-local", NINGBO_PROJECT_ID)["items"]
            self.assertEqual(next(item["value"] for item in decisions if item["key"] == "trial_tax_rate"), "0.05")
            service.update_project("org-local", NINGBO_PROJECT_ID, {"name": "用户修改的名称", "expected_version": 0})
            files.seed_ningbo(service, fixture)
            self.assertEqual(len(files.list_files("org-local", NINGBO_PROJECT_ID)["items"]), 7)
            self.assertEqual(service.get_project("org-local", NINGBO_PROJECT_ID)["name"], "用户修改的名称")
            store.close()
            restored = SQLiteStore(root / "app.sqlite3")
            self.assertEqual(restored.projects[("org-local", NINGBO_PROJECT_ID)]["name"], "用户修改的名称")
            restored.close()


if __name__ == "__main__":
    unittest.main()
