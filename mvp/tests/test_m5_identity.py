import hashlib
from contextlib import closing
from http.client import HTTPConnection
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiError, ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.file_service import FileService
from rkd_mvp.sqlite_store import SQLiteStore


class M5IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "app.sqlite3"
        self.store = SQLiteStore(self.db)
        self.service = ApiService(MVPApp(self.store), file_service=FileService(self.db, self.root))
        for org, project in [("org-local", "alpha"), ("org-local", "beta"), ("other-org", "other")]:
            self.service.create_project(org, project, project)
        self.auth = AccountIdentityProvider(self.db)
        self.password = "M5 test passphrase only 2026"
        self.admin = self.auth.bootstrap("admin", "管理员", self.password)
        token, _ = self.auth.login("admin", self.password, "setup")
        identity = self.auth.authenticate({"Cookie": f"rkd_session={token}"})
        self.users = {}
        for role in ("manager", "editor", "viewer"):
            user = self.auth.create_user(identity, {"username": role, "display_name": role, "password": self.password})
            self.auth.set_member(identity, "alpha", {"user_id": user["user_id"], "role": role})
            self.users[role] = user
        data = b"%PDF-1.4\nM5 test source\n%%EOF"
        upload = self.service.initiate_upload("org-local", "alpha", {"filename": "test.pdf", "size_bytes": len(data)})
        self.service.receive_upload("org-local", "alpha", upload["upload_id"], io.BytesIO(data), len(data))
        self.file = self.service.complete_upload("org-local", "alpha", upload["upload_id"], hashlib.sha256(data).hexdigest())
        self.spatial = self.service.create_spatial_revision("org-local", "alpha", {"width": "10", "length": "5"}, "setup")
        self.start_server()

    def start_server(self):
        self.server = create_server(self.service, identity_provider=self.auth, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def tearDown(self):
        self.stop_server()
        self.store.close()
        self.temp.cleanup()

    def request(self, method, path, body=None, session=None, extra=None):
        headers = {"Content-Type": "application/json"}
        if session:
            headers.update({"Cookie": session["cookie"], "X-CSRF-Token": session["csrf_token"]})
        headers.update(extra or {})
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=8)
        connection.request(method, path, None if body is None else json.dumps(body), headers)
        response = connection.getresponse()
        raw = response.read()
        result_headers = dict(response.getheaders())
        status = response.status
        connection.close()
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            payload = raw
        return status, payload, result_headers

    def login(self, name="admin"):
        status, payload, headers = self.request("POST", "/api/v1/auth/login", {"username": name, "password": self.password})
        self.assertEqual(status, 200, payload)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        return {**payload, "cookie": headers["Set-Cookie"].split(";", 1)[0]}

    def test_ma01_real_login_rejects_forged_development_identity(self):
        for path in ("/api/v1/projects", "/api/v1/projects/alpha/files", "/api/v1/projects/alpha/changes"):
            self.assertEqual(self.request("GET", path, extra={"X-Organization-Id": "org-local", "X-Actor-Id": self.admin["user_id"]})[0], 401)
        viewer = self.login("viewer")
        status, result, _ = self.request("GET", "/api/v1/projects", session=viewer, extra={"X-Actor-Id": self.admin["user_id"], "X-Organization-Id": "other-org"})
        self.assertEqual(status, 200)
        self.assertEqual([(p["project_id"], p["role"]) for p in result["items"]], [("alpha", "viewer")])
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertNotIn(self.password, str(db.execute("SELECT * FROM auth_users").fetchall()))
            self.assertNotIn(viewer["cookie"].split("=", 1)[1], str(db.execute("SELECT * FROM auth_sessions").fetchall()))
        with self.assertRaises(ApiError):
            self.auth.bootstrap("second", "不允许", self.password)

    def test_ma02_roles_isolate_reads_writes_and_approval_paths(self):
        viewer, editor, manager = (self.login(role) for role in ("viewer", "editor", "manager"))
        for suffix in ("", "/files", "/issues", "/requirements", "/design", "/spatial", "/estimates", "/jobs", "/procurement/orders", "/changes"):
            self.assertEqual(self.request("GET", "/api/v1/projects/beta" + suffix, session=viewer)[0], 404)
        for suffix in ("/uploads", "/requirements/drafts", "/design/revisions", "/spatial/revisions", "/procurement/orders", "/changes", "/commands"):
            self.assertEqual(self.request("POST", "/api/v1/projects/alpha" + suffix, {}, viewer)[0], 403)
        self.assertEqual(self.request("POST", "/api/v1/projects/alpha/requirements/drafts", {}, editor)[0], 201)
        self.assertEqual(self.request("POST", "/api/v1/projects/alpha/changes/fake/acceptance", {}, editor)[0], 403)
        self.assertEqual(self.request("PATCH", "/api/v1/projects/alpha", {"name": "负责人编辑", "expected_version": 0}, manager)[0], 200)
        self.assertEqual(self.service.app.store.audit[-1].context.actor_id, self.users["manager"]["user_id"])
        self.assertEqual(self.request("POST", "/api/v1/projects", {"name": "无权新建"}, editor)[0], 403)
        self.assertEqual(self.request("POST", "/api/v1/projects/alpha/commands", {}, self.login())[0], 403)
        self.assertEqual(self.request("POST", "/api/v1/auth/users", {}, manager)[0], 403)

    def test_ma03_downloads_reauthorize_after_membership_revocation(self):
        admin, viewer = self.login(), self.login("viewer")
        status, files, _ = self.request("GET", "/api/v1/projects/alpha/files", session=viewer)
        self.assertEqual(status, 200)
        url = files["items"][0]["download_url"]
        self.assertNotIn("signature", url)
        artifact_url = f"/api/v1/projects/alpha/spatial/artifacts/{self.spatial['artifacts'][0]['artifact_id']}/content"
        for target in (url, artifact_url):
            self.assertEqual(self.request("GET", target, session=viewer)[0], 200)
            self.assertEqual(self.request("GET", target)[0], 401)
            self.assertEqual(self.request("GET", target.replace("/alpha/", "/beta/"), session=viewer)[0], 404)
        self.assertEqual(self.request("POST", "/api/v1/projects/alpha/members", {"user_id": self.users["viewer"]["user_id"], "role": "none"}, admin)[0], 200)
        for target in (url, artifact_url):
            self.assertEqual(self.request("GET", target, session=viewer)[0], 404)
        self.assertEqual(self.request("GET", url + "?org=org-local&expires=9999999999&signature=fake")[0], 401)

    def test_ma04_logout_disable_and_session_expiry(self):
        admin, viewer = self.login(), self.login("viewer")
        self.assertEqual(self.request("POST", "/api/v1/auth/logout", {}, viewer)[0], 200)
        self.assertEqual(self.request("GET", "/api/v1/projects", session=viewer)[0], 401)
        viewer = self.login("viewer")
        self.assertEqual(self.request("PATCH", f"/api/v1/auth/users/{self.users['viewer']['user_id']}", {"active": False}, admin)[0], 200)
        self.assertEqual(self.request("GET", "/api/v1/projects", session=viewer)[0], 401)
        editor = self.login("editor")
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE user_id = ?", (time.time() - 1801, self.users["editor"]["user_id"]))
        self.assertEqual(self.request("GET", "/api/v1/projects", session=editor)[0], 401)
        manager = self.login("manager")
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE auth_sessions SET expires_at = ? WHERE user_id = ?", (time.time() - 1, self.users["manager"]["user_id"]))
        self.assertEqual(self.request("GET", "/api/v1/projects", session=manager)[0], 401)

    def test_ma05_csrf_origin_host_and_login_throttling(self):
        admin = self.login()
        self.assertEqual(self.request("POST", "/api/v1/projects", {"name": "bad"}, admin, {"X-CSRF-Token": ""})[0], 403)
        self.assertEqual(self.request("POST", "/api/v1/projects", {"name": "bad"}, admin, {"Origin": "https://malicious.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/v1/projects", session=admin, extra={"Host": "malicious.example"})[0], 403)
        for _ in range(5):
            self.assertEqual(self.request("POST", "/api/v1/auth/login", {"username": "viewer", "password": "wrong"})[0], 401)
        self.assertEqual(self.request("POST", "/api/v1/auth/login", {"username": "viewer", "password": self.password})[0], 429)
        self.assertEqual(self.request("POST", "/api/v1/auth/login", {}, extra={"Content-Type": "text/plain"})[0], 415)
        with self.assertRaises(ValueError):
            create_server(self.service, self.auth, host="0.0.0.0", port=0)

    def test_ma06_restart_preserves_accounts_roles_sessions_and_audit(self):
        viewer = self.login("viewer")
        before = self.request("GET", "/api/v1/projects", session=viewer)[1]
        self.stop_server()
        self.store.close()
        self.store = SQLiteStore(self.db)
        self.service = ApiService(MVPApp(self.store), file_service=FileService(self.db, self.root))
        self.auth = AccountIdentityProvider(self.db)
        self.start_server()
        self.assertEqual(self.request("GET", "/api/v1/projects", session=viewer)[1], before)
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM auth_memberships").fetchone()[0], 3)
            self.assertGreater(db.execute("SELECT COUNT(*) FROM auth_audit").fetchone()[0], 6)

    def test_ma08_launcher_refuses_downgrade_after_accounts_enabled(self):
        root = Path(__file__).parents[2]
        result = subprocess.run([sys.executable, str(root / "mvp/run_api_server.py")], cwd=root,
                                env={**os.environ, "RKD_MVP_DB_PATH": str(self.db), "RKD_AUTH_MODE": "local", "RKD_MVP_PORT": "0", "PYTHONIOENCODING": "utf-8"},
                                capture_output=True, encoding="utf-8", timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("拒绝退回开发身份模式", result.stderr)
        self.assertNotIn("listening on", result.stdout)


if __name__ == "__main__":
    unittest.main()
