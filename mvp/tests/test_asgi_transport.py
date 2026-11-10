"""Security and byte-flow regression through the real ASGI stack."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.asgi_app import create_app
from rkd_mvp.api_service import ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.file_service import FileService
from rkd_mvp.sqlite_store import SQLiteStore


class ASGITransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = SQLiteStore(self.root / "app.sqlite3")
        self.service = ApiService(MVPApp(self.store), file_service=FileService(self.root / "app.sqlite3", self.root))
        self.service.create_project("org-local", "Alpha", "alpha")
        self.service.create_project("org-local", "Beta", "beta")
        self.auth = AccountIdentityProvider(self.root / "app.sqlite3")
        self.password = "Transport verification passphrase 2026"
        self.auth.bootstrap("admin", "Administrator", self.password)
        self.static = self.root / "dist"
        self.static.mkdir()
        (self.static / "index.html").write_text("<html>工作台</html>", encoding="utf-8")
        self.app = create_app(self.service, self.auth, self.static, "https://nas.example")
        self.client = TestClient(self.app, base_url="https://nas.example")

    def tearDown(self):
        self.client.close()
        self.store.close()
        self.temp.cleanup()

    def login(self, username="admin"):
        response = self.client.post("/api/v1/auth/login", json={"username":username,"password":self.password})
        self.assertEqual(response.status_code, 200, response.text)
        self.client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return response

    def test_operations_admin_only_redaction_and_stale_probe(self):
        path = '/api/v1/operations/status'
        self.assertEqual(self.client.get(path).status_code, 401)
        self.login()
        directory = self.root / 'operations'
        directory.mkdir()
        keys = ('application_ready','private_https_route','app_container','database_container','disk_space','backup_recent','latest_backup_attempt')
        (directory / 'latest-backup-success.json').write_text(json.dumps({'snapshot_at': datetime.now(timezone.utc).isoformat(), 'archive': '/secret/private-path'}))
        def health(at):
            (directory / 'health.json').write_text(json.dumps({'at':at.isoformat(),'checks':dict.fromkeys(keys,True)}))
        with patch.dict('os.environ', {'RKD_OPERATIONS_STATUS_DIR': str(directory)}):
            health(datetime.now(timezone.utc))
            response = self.client.get(path)
            self.assertTrue(response.json()['passed'])
            self.assertNotIn('private-path', response.text)
            health(datetime.now(timezone.utc)-timedelta(minutes=4))
            self.assertTrue(self.client.get(path).json()['stale'])
            self.assertFalse(self.client.get(path).json()['passed'])
            (directory / 'health.json').write_text('broken')
            self.assertFalse(self.client.get(path).json()['available'])
            self.client.post('/api/v1/auth/users',json={'username':'viewer','display_name':'Viewer','password':self.password})
            self.client.post('/api/v1/auth/logout',json={})
            self.login('viewer')
            self.assertEqual(self.client.get(path).status_code,403)

    def test_pre_review_route_requires_current_project_membership(self):
        path = '/api/v1/projects/alpha/review-readiness'
        self.assertEqual(self.client.get(path).status_code,401)
        self.login()
        result = self.client.get(path)
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json()['formal_release_allowed'])
        user=self.client.post('/api/v1/auth/users',json={'username':'reviewer','display_name':'Viewer','password':self.password}).json()
        self.client.post('/api/v1/projects/alpha/members',json={'user_id':user['user_id'],'role':'viewer'})
        self.client.post('/api/v1/auth/logout',json={})
        self.login('reviewer')
        self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(self.client.get('/api/v1/projects/beta/review-readiness').status_code,404)

    def test_review_positions_admin_changes_version_and_scope(self):
        path='/api/v1/auth/review-positions'
        self.assertEqual(self.client.get(path).status_code,401)
        self.login()
        items=self.client.get(path).json()['items']
        self.assertEqual(len(items),2)
        user=self.client.post('/api/v1/auth/users',json={'username':'review-staff','display_name':'Staff','password':self.password}).json()
        body={'name':'图纸复核岗','active':True,'expected_version':0,'user_ids':[user['user_id']]}
        self.assertEqual(self.client.patch(path+'/design_reviewer',json=body).status_code,200)
        self.assertEqual(self.client.patch(path+'/design_reviewer',json=body).status_code,409)
        self.assertEqual(self.client.patch(path+'/commercial_reviewer',json={**body,'user_ids':['foreign-user']}).status_code,400)
        self.assertEqual(self.client.get(path).json()['items'][0]['user_ids'],[user['user_id']])
        self.client.post('/api/v1/auth/logout',json={}); self.login('review-staff')
        self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.patch(path+'/design_reviewer',json={**body,'expected_version':1}).status_code,403)
        self.assertEqual(self.client.get('/api/v1/projects/alpha/review-readiness').status_code,404)

    def test_secure_cookie_forged_headers_csrf_and_exact_origin(self):
        self.assertEqual(self.client.get("/api/v1/projects", headers={"X-Organization-Id":"org-local","X-Actor-Id":"admin"}).status_code, 401)
        response = self.login()
        self.assertIn("Secure", response.headers["set-cookie"])
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        for headers in ({"Host":"evil.example"}, {"Origin":"https://evil.example"}, {"Sec-Fetch-Site":"cross-site"}, {"X-CSRF-Token":"forged"}):
            self.assertEqual(self.client.post("/api/v1/projects", json={"name":"Denied"}, headers=headers).status_code, 403)
        response = self.client.get("/api/v1/projects", headers={"X-Forwarded-Host":"evil.example","X-Forwarded-Proto":"http","X-Organization-Id":"other-org"})
        self.assertEqual(len(response.json()["items"]), 2)
        self.assertEqual(self.client.post("/api/v1/projects", json={"name":"Created"}, headers={"Origin":"https://nas.example"}).status_code, 201)
        self.assertEqual(self.client.post("/api/v1/auth/logout", json={}).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/projects").status_code, 401)

    def test_upload_download_roles_and_immediate_revocation(self):
        self.login()
        content = b"%PDF-1.4\n" + bytes(range(256)) * 8193
        upload = self.client.post("/api/v1/projects/alpha/uploads", json={"filename":"byte-test.pdf","size_bytes":len(content)}).json()
        prefix = "/api/v1/projects/alpha/uploads/" + upload["upload_id"]
        self.assertEqual(self.client.put(prefix + "/content", content=content).status_code, 200)
        asset = self.client.post(prefix + "/complete", json={"sha256":hashlib.sha256(content).hexdigest()}).json()
        url = "/api/v1/projects/alpha/files/" + asset["file_id"] + "/content"
        self.assertEqual(self.client.get(url).content, content)
        user = self.client.post("/api/v1/auth/users", json={"username":"viewer","display_name":"Viewer","password":self.password}).json()
        member_url = "/api/v1/projects/alpha/members"
        self.assertEqual(self.client.post(member_url, json={"user_id":user["user_id"],"role":"viewer"}).status_code, 200)
        admin_cookie = self.client.cookies.get("rkd_session")
        admin_csrf = self.client.headers["X-CSRF-Token"]
        self.client.cookies.clear()
        self.login("viewer")
        self.assertEqual(self.client.get(url).content, content)
        self.assertEqual(self.client.get("/api/v1/projects/beta").status_code, 404)
        self.assertEqual(self.client.patch("/api/v1/projects/alpha", json={"name":"Denied","expected_version":0}).status_code, 403)
        removed = self.client.post(member_url, json={"user_id":user["user_id"],"role":"none"}, headers={"Cookie":"rkd_session="+admin_cookie,"X-CSRF-Token":admin_csrf})
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_body_limits_missing_length_and_duplicate_authority(self):
        self.login()
        response = self.client.post("/api/v1/projects", content=b"x" * (1024*1024+1), headers={"Content-Type":"application/json"})
        self.assertEqual(response.status_code, 413)
        response = self.client.post("/api/v1/projects", content=iter([b'{"name":',b'"chunked"}']), headers={"Content-Type":"application/json"})
        self.assertEqual(response.status_code, 400)
        response = self.client.get("/api/v1/projects", headers=[("Host","nas.example"),("Host","evil.example")])
        self.assertIn(response.status_code, (400,403))
        self.assertEqual(len(self.client.get("/api/v1/projects").json()["items"]), 2)

    def test_static_traversal_exception_redaction_and_no_dev_mode(self):
        self.assertIn("工作台", self.client.get("/").text)
        self.assertEqual(self.client.get("/%2e%2e/secret.txt").status_code, 404)
        self.login()
        with patch.object(self.service, "list_projects", side_effect=RuntimeError("password=private-credential")):
            response = self.client.get("/api/v1/projects")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private-credential", response.text)
        with self.assertRaises(ValueError):
            create_app(self.service, None, self.static, "https://nas.example")
        with self.assertRaises(ValueError):
            create_app(self.service, self.auth, self.static, "http://100.73.240.73:18080")


if __name__ == "__main__":
    unittest.main()
