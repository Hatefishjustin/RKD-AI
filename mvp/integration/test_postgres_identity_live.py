"""Account HTTP and storage boundaries against the actual non-owner PG role."""
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg

from rkd_mvp.account_identity import AccountIdentityProvider, AccountGuardedLocalIdentityProvider
from rkd_mvp.account_repository import PostgresAccountRepository, PostgresAccountTransaction
from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiError
from rkd_mvp.models import TenantContext
from rkd_mvp.postgres_api_service import PostgresApiService
from rkd_mvp.postgres_store import PostgresStore

APP_FACTORY = None


class PostgresIdentityLiveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.org = "identity-" + uuid4().hex
        self.store = PostgresStore(APP_FACTORY)
        self.service = PostgresApiService(self.store, self.root)
        for project in ("alpha", "beta"):
            self.service.create_project(self.org, project, project)
        self.auth = AccountIdentityProvider(None, repository=PostgresAccountRepository(self.store, self.org))
        self.password = "isolated test passphrase 2026"
        self.names = {role: role + "-" + uuid4().hex for role in ("admin", "manager", "editor", "viewer")}
        self.users = {"admin": self.auth.bootstrap(self.names["admin"], "Test admin", self.password, self.org)}
        token, _ = self.auth.login(self.names["admin"], self.password, "setup")
        self.admin_identity = self.auth.authenticate({"Cookie": "rkd_session=" + token})
        for role in ("manager", "editor", "viewer"):
            user = self.auth.create_user(self.admin_identity, {"username": self.names[role], "display_name": role, "password": self.password})
            self.users[role] = user
            self.auth.set_member(self.admin_identity, "alpha", {"user_id": user["user_id"], "role": role})
        self.start()
        self.addCleanup(self.stop)

    def start(self, provider=None):
        self.server = create_server(self.service, provider or self.auth, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self, method, path, body=None, session=None, extra=None):
        headers = {"Content-Type": "application/json"}
        if session:
            headers.update({"Cookie": session["cookie"], "X-CSRF-Token": session["csrf_token"]})
        headers.update(extra or {})
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=15)
        try:
            connection.request(method, path, None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            raw, status, result_headers = response.read(), response.status, dict(response.getheaders())
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                payload = raw
            return status, payload, result_headers
        finally:
            connection.close()

    def login(self, role="admin"):
        status, body, headers = self.request("POST", "/api/v1/auth/login", {"username": self.names[role], "password": self.password})
        self.assertEqual(status, 200, body)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        return {**body, "cookie": headers["Set-Cookie"].split(";", 1)[0]}

    def context(self, project="alpha"):
        return self.store.tenant_transaction(TenantContext(self.org, project, "test"))

    def test_01_real_login_forged_headers_and_storage(self):
        self.assertIsNone(self.auth.db_path)
        self.assertEqual(list(self.root.rglob("*.sqlite3")), [])
        self.assertEqual(self.request("GET", "/api/v1/projects", extra={"X-Organization-Id": self.org, "X-Actor-Id": self.users['admin']['user_id']})[0], 401)
        viewer = self.login("viewer")
        status, result, _ = self.request("GET", "/api/v1/projects", session=viewer, extra={"X-Organization-Id": "forged", "X-Actor-Id": self.users['admin']['user_id']})
        self.assertEqual(status, 200, result)
        self.assertEqual([(p["project_id"], p["role"]) for p in result["items"]], [("alpha", "viewer")])
        with self.context() as db:
            self.assertNotIn(self.password, str(db.execute("SELECT * FROM rkd.auth_user").fetchall()))
            self.assertNotIn(viewer["cookie"].split("=", 1)[1], str(db.execute("SELECT * FROM rkd.auth_session").fetchall()))
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.auth_membership").fetchone()[0], 3)
        with self.context("unassigned") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.auth_membership").fetchone()[0], 0)
        with APP_FACTORY() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.auth_user").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.list_account_project_roles(%s)", (viewer['user']['user_id'],)).fetchone()[0], 0)

    def test_02_all_business_routes_apply_roles_and_trusted_actor(self):
        viewer, editor, manager = (self.login(role) for role in ("viewer", "editor", "manager"))
        for suffix in ("", "/files", "/issues", "/requirements", "/design", "/spatial", "/production", "/estimates", "/jobs", "/procurement/orders", "/changes", "/members"):
            self.assertEqual(self.request("GET", "/api/v1/projects/beta" + suffix, session=viewer)[0], 404, suffix)
        for suffix in ("/uploads", "/requirements/drafts", "/design/revisions", "/spatial/revisions", "/procurement/orders", "/changes"):
            self.assertEqual(self.request("POST", "/api/v1/projects/alpha" + suffix, {}, viewer)[0], 403)
        self.assertEqual(self.request("POST", "/api/v1/projects/alpha/requirements/drafts", {}, editor)[0], 201)
        for suffix in ("/acceptance", "/reproduce"):
            self.assertEqual(self.request("POST", "/api/v1/projects/alpha/changes/fake" + suffix, {}, editor)[0], 403)
        self.assertEqual(self.request("PATCH", "/api/v1/projects/alpha", {"name": "Manager update", "expected_version": 0}, manager, {"X-Actor-Id": "forged"})[0], 200)
        with self.context() as db:
            actor = db.execute("SELECT actor_id FROM rkd.audit_event ORDER BY created_at DESC LIMIT 1").fetchone()[0]
            self.assertEqual(actor, self.users['manager']['user_id'])
        self.assertEqual(self.request("POST", "/api/v1/projects", {"name": "Denied"}, editor)[0], 403)
        self.assertEqual(self.request("POST", "/api/v1/auth/users", {}, manager)[0], 403)
        self.assertEqual(self.request("POST", "/api/v1/projects/alpha/commands", {}, self.login())[0], 501)

    def test_03_downloads_immediately_reauthorize_membership(self):
        data = b"%PDF-1.7\nAccount authorized bytes\n"
        upload = self.service.initiate_upload(self.org, "alpha", {"filename": "test.pdf", "size_bytes": len(data)})
        self.service.receive_upload(self.org, "alpha", upload["upload_id"], io.BytesIO(data), len(data))
        self.service.complete_upload(self.org, "alpha", upload["upload_id"], hashlib.sha256(data).hexdigest())
        spatial = self.service.create_spatial_revision(self.org, "alpha", {"width": "10", "length": "5"}, "test")
        admin, viewer = self.login(), self.login("viewer")
        url = self.request("GET", "/api/v1/projects/alpha/files", session=viewer)[1]["items"][0]["download_url"]
        self.assertNotIn("signature", url)
        artifact_url = spatial["artifacts"][0]["download_url"]
        for target in (url, artifact_url):
            self.assertEqual(self.request("GET", target, session=viewer)[0], 200)
            self.assertEqual(self.request("GET", target)[0], 401)
            self.assertEqual(self.request("GET", target.replace("/alpha/", "/beta/"), session=viewer)[0], 404)
        self.assertEqual(self.request("POST", "/api/v1/projects/alpha/members", {"user_id": self.users['viewer']['user_id'], "role": "none"}, admin)[0], 200)
        for target in (url, artifact_url):
            self.assertEqual(self.request("GET", target, session=viewer)[0], 404)
        self.assertEqual(self.request("GET", url + "?org=org-local&expires=9999999999&signature=fake")[0], 401)

    def test_04_logout_disabled_idle_and_absolute_expiration(self):
        admin, viewer = self.login(), self.login("viewer")
        self.assertEqual(self.request("POST", "/api/v1/auth/logout", {}, viewer)[0], 200)
        self.assertEqual(self.request("GET", "/api/v1/projects", session=viewer)[0], 401)
        viewer = self.login("viewer")
        self.assertEqual(self.request("PATCH", "/api/v1/auth/users/" + self.users['viewer']['user_id'], {"active": False}, admin)[0], 200)
        self.assertEqual(self.request("GET", "/api/v1/projects", session=viewer)[0], 401)
        editor, manager = self.login("editor"), self.login("manager")
        with self.context() as db:
            db.execute("UPDATE rkd.auth_session SET last_seen_at=now()-interval '1801 seconds' WHERE user_id=%s", (self.users['editor']['user_id'],))
            db.execute("UPDATE rkd.auth_session SET expires_at=now()-interval '1 second' WHERE user_id=%s", (self.users['manager']['user_id'],))
        for session in (editor, manager):
            self.assertEqual(self.request("GET", "/api/v1/projects", session=session)[0], 401)

    def test_05_csrf_host_origin_and_concurrent_failed_logins(self):
        admin = self.login()
        for extra in ({"X-CSRF-Token": ""}, {"Origin": "https://malicious.example"}):
            self.assertEqual(self.request("POST", "/api/v1/projects", {"name": "Denied"}, admin, extra)[0], 403)
        self.assertEqual(self.request("GET", "/api/v1/projects", session=admin, extra={"Host": "malicious.example"})[0], 403)
        def fail(_):
            return self.request("POST", "/api/v1/auth/login", {"username": self.names['viewer'], "password": "wrong"})[0]
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(fail, range(8)))
        self.assertEqual(sorted(statuses), [401] * 5 + [429] * 3)
        self.assertEqual(self.request("POST", "/api/v1/auth/login", {"username": self.names['viewer'], "password": self.password})[0], 429)
        with self.context() as db:
            self.assertEqual(sorted(row[0] for row in db.execute("SELECT failures FROM rkd.auth_login_throttle")), [5, 5])
            db.execute("UPDATE rkd.auth_login_throttle SET window_started_at=now()-interval '901 seconds'")
        self.login("viewer")
        self.assertEqual(self.request("POST", "/api/v1/auth/login", {}, extra={"Content-Type": "text/plain"})[0], 415)

    def test_06_account_and_membership_audit_failures_roll_back(self):
        original = PostgresAccountTransaction.query
        def fail_audit(tx, operation, params=()):
            result = original(tx, operation, params)
            if operation == "audit":
                tx.db.execute("SELECT 1/0")
            return result
        name = "rollback-" + uuid4().hex
        with patch.object(PostgresAccountTransaction, "query", fail_audit):
            with self.assertRaises(psycopg.Error):
                self.auth.create_user(self.admin_identity, {"username": name, "display_name": "Test", "password": self.password})
            with self.assertRaises(psycopg.Error):
                self.auth.set_member(self.admin_identity, "alpha", {"user_id": self.users['viewer']['user_id'], "role": "editor"})
        with self.context() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.auth_user WHERE username=%s", (name,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT role FROM rkd.auth_membership WHERE user_id=%s", (self.users['viewer']['user_id'],)).fetchone()[0], "viewer")
        self.assertEqual(self.auth.create_user(self.admin_identity, {"username": name, "display_name": "Test", "password": self.password})['username'], name)

    def test_07_bootstrap_parallel_and_foreign_organization_default_deny(self):
        other_org = "identity-" + uuid4().hex
        other = AccountIdentityProvider(None, repository=PostgresAccountRepository(self.store, other_org))
        def bootstrap(_):
            try:
                return other.bootstrap("parallel-" + uuid4().hex, "Admin", self.password, other_org)
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(bootstrap, range(2)))
        self.assertEqual(sum(isinstance(row, dict) for row in rows), 1)
        self.assertIn("ALREADY_INITIALIZED", rows)
        with self.assertRaises(ApiError):
            other.login(self.names['admin'], self.password, "test")
        with self.store.tenant_transaction(TenantContext(other_org, "alpha", "test")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.list_account_project_roles(%s)", (self.users['viewer']['user_id'],)).fetchone()[0], 0)
        self.assertEqual(len(self.auth.list_users(self.admin_identity)['items']), 4)

    def test_08_reopened_provider_persists_and_local_mode_fails_closed(self):
        viewer = self.login("viewer")
        before = self.request("GET", "/api/v1/projects", session=viewer)[1]
        self.stop()
        self.auth = AccountIdentityProvider(None, repository=PostgresAccountRepository(PostgresStore(APP_FACTORY), self.org))
        self.start()
        self.assertEqual(self.request("GET", "/api/v1/projects", session=viewer)[1], before)
        self.stop()
        self.start(AccountGuardedLocalIdentityProvider(self.auth))
        for target in ("/api/v1/projects", "/api/v1/projects/alpha/files/fake/content?signature=fake"):
            self.assertEqual(self.request("GET", target)[0], 401)
