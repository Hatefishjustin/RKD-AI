"""Real child-process HTTP probe used by the PostgreSQL verifier."""
import hashlib
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import time
from uuid import uuid4


class PostgresApiProbe:
    def __init__(self, root, evidence, dsn, runtime_root=None, *, transport="reference"):
        self.root, self.evidence, self.dsn = root, evidence, dsn
        self.runtime_root = runtime_root or (evidence / "api-runtime")
        self.process = None
        self.transport = transport
        self.log = None
        self.report = {"pids": [], "requests": [], "sqlite_fallback": False}

    def start(self):
        env = {**os.environ, "RKD_POSTGRES_DSN": self.dsn,
               "RKD_POSTGRES_RUNTIME": str(self.runtime_root), "RKD_POSTGRES_PORT": "0", "PYTHONUTF8": "1"}
        env.pop("RKD_AUTH_MODE", None)
        entry = "run_postgres_api.py"
        if self.transport == "asgi":
            with socket.socket() as probe:
                probe.bind(("127.0.0.1",0))
                port = probe.getsockname()[1]
            env.update(RKD_TEAM_PORT=str(port),RKD_PUBLIC_ORIGIN=f"http://127.0.0.1:{port}")
            entry = "run_team_api.py"
        log_path = self.evidence / f"api-{len(self.report['pids']) + 1}.log"
        self.log = log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen([sys.executable, "-u", str(self.root / "mvp" / entry)],
                                        cwd=self.root, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.report["pids"].append(self.process.pid)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            text = log_path.read_text(encoding="utf-8")
            if "http://127.0.0.1:" in text:
                self.port = int(text.split("http://127.0.0.1:")[1].split()[0])
                assert self.request("GET", "/api/health/ready")[0] == 200
                return
            if self.process.poll() is not None:
                raise RuntimeError("PostgreSQL API launcher failed; see its log")
            time.sleep(0.1)
        raise RuntimeError("PostgreSQL API launcher timed out")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        if self.log:
            self.log.close()

    def request(self, method, path, body=None, *, raw=False, headers=None):
        data = body if raw else json.dumps(body or {}).encode("utf-8")
        connection = HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            connection.request(method, path, body=data if method != "GET" else None,
                               headers={"Content-Type": "application/octet-stream" if raw else "application/json", **getattr(self, "auth_headers", {}), **(headers or {})})
            response = connection.getresponse()
            self.last_response_headers = response.headers
            data = response.read()
            self.report["requests"].append({"method": method, "path": path, "status": response.status,
                                            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            return response.status, data
        finally:
            connection.close()

    def initial(self):
        self.start()
        status, data = self.request("POST", "/api/v1/projects", {"name": "PostgreSQL HTTP byte pilot", "project_id": "http-" + uuid4().hex},
                                    headers={"X-Organization-Id": "forged-organization"})
        assert status == 201
        project = json.loads(data)
        assert project["organization_id"] == "org-local"
        self.project_id = project["project_id"]
        self.prefix = "/api/v1/projects/" + self.project_id
        assert self.request("PATCH", self.prefix, {"name": "Updated project", "expected_version": 0})[0] == 200
        assert self.request("PATCH", self.prefix, {"name": "Stale update", "expected_version": 0})[0] == 409
        self.content = b"%PDF-1.7\nActual PostgreSQL HTTP bytes\n"
        for revision in (1, 2):
            status, data = self.request("POST", self.prefix + "/uploads", {"filename": "plan.pdf", "size_bytes": len(self.content),
                                         "sha256": hashlib.sha256(self.content).hexdigest()})
            assert status == 201
            upload = json.loads(data)["upload_id"]
            assert self.request("PUT", self.prefix + f"/uploads/{upload}/content", self.content, raw=True)[0] == 200
            status, data = self.request("POST", self.prefix + f"/uploads/{upload}/complete")
            assert status == 201 and json.loads(data)["revision"] == revision
        self.file_id = json.loads(data)["file_id"]
        status, data = self.request("GET", self.prefix + "/files")
        assert status == 200 and len(json.loads(data)["items"]) == 2
        assert self.request("GET", json.loads(data)["items"][0]["download_url"])[1] == self.content
        assert self.request("GET", self.prefix + "/workflows")[0] == 501
        status, data = self.request("POST", self.prefix + "/requirements/drafts")
        assert status == 201
        requirement = json.loads(data)["item"]
        assert requirement["revision_no"] == 1 and len(requirement["source_refs"]) == 2
        from rkd_mvp.design_rules import DEFAULT_PROGRAM
        request = {"expected_revision": 1, "design_program": DEFAULT_PROGRAM,
                   "design_notes": "HTTP PostgreSQL draft", "change_reason": "save program"}
        assert self.request("PATCH", self.prefix + "/requirements", request)[0] == 200
        assert self.request("PATCH", self.prefix + "/requirements", request)[0] == 409
        status, data = self.request("POST", self.prefix + "/design/revisions", {
            "expected_revision": 0, "requirement_revision_no": 2, "change_reason": "HTTP design"})
        assert status == 201
        status, data = self.request("GET", self.prefix + "/production")
        assert status == 200 and json.loads(data)["item"]["quote"]["sale_gross"] is None
        status, data = self.request("PATCH", self.prefix + "/production/settings", {"expected_version": 0,
            "expected_design_revision": 1, "settings": {"unit_cost_net": "100", "material_specification": "Floor material",
                "supplier_name": "Auto supplier", "delivery_location": "Site"}})
        assert status == 200
        original = json.loads(data)["item"]
        assert original["quote"]["sale_gross"] == "9828.00"
        self.old_artifacts = original["artifacts"]
        for artifact in self.old_artifacts:
            status, content = self.request("GET", artifact["download_url"])
            assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"]
        import copy
        program = copy.deepcopy(DEFAULT_PROGRAM)
        program["width"] = "16"
        assert self.request("PATCH", self.prefix + "/requirements", {"expected_revision": 2, "design_program": program,
                            "design_notes": "HTTP PostgreSQL 16m", "change_reason": "wider boundary"})[0] == 200
        assert self.request("POST", self.prefix + "/design/revisions", {"expected_revision": 1, "requirement_revision_no": 3,
                            "change_reason": "regenerate from current requirement"})[0] == 201
        status, data = self.request("GET", self.prefix + "/production")
        self.production = json.loads(data)["item"]
        assert status == 200 and self.production["quote"]["sale_gross"] == "13104.00"
        assert self.production["quote"]["quantity"] == "104.0000"
        for artifact in self.production["artifacts"]:
            status, content = self.request("GET", artifact["download_url"])
            assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"]
            if artifact["artifact_kind"] == "package_zip":
                (self.evidence / "postgres-production-v3.zip").write_bytes(content)
        self.report["design_production_propagation"] = {"before_area": "78.0000", "after_area": "104.0000",
            "before_gross": "9828.00", "after_gross": "13104.00", "artifacts": 8, "previous_artifacts": 8}
        program["width"] = "20"
        status, data = self.request("POST", self.prefix + "/changes", {"title": "HTTP model change", "reason": "Test review",
            "description": "Widen to20m using existing price", "design_program": program}, headers={"Idempotency-Key": "http-change-create-0001"})
        assert status == 201, data
        change = json.loads(data)
        self.change_prefix = self.prefix + "/changes/" + change["change_id"]
        status, data = self.request("POST", self.change_prefix + "/analyze", {"expected_version": change["version"]}, headers={"Idempotency-Key": "http-change-analyze-0001"})
        assert status == 200, data
        change = json.loads(data)
        assert change["impact"]["quantity_delta_m2"] == "26.0000"
        assert self.request("GET", self.prefix + "/production")[0] == 200
        status, data = self.request("POST", self.change_prefix + "/acceptance", {"expected_version": change["version"],
            "conclusion": "accepted", "checklist": ["Model and price reviewed"], "evidence_ref": "local://http/change-review"}, headers={"Idempotency-Key": "http-change-accept-0001"})
        assert status == 200, data
        change = json.loads(data)
        request = {"expected_version": change["version"]}
        headers = {"Idempotency-Key": "http-change-reproduce-0001"}
        status, data = self.request("POST", self.change_prefix + "/reproduce", request, headers=headers)
        assert status == 201, data
        self.change = json.loads(data)
        assert json.loads(self.request("POST", self.change_prefix + "/reproduce", request, headers=headers)[1]) == self.change
        self.old_artifacts += self.production["artifacts"]
        self.production = json.loads(self.request("GET", self.prefix + "/production")[1])["item"]
        assert (self.production["quote"]["quantity"], self.production["quote"]["sale_gross"]) == ("130.0000", "16380.00")
        self.change_artifacts = self.change["artifacts"]
        for artifact in self.change_artifacts:
            status, content = self.request("GET", self.prefix + "/changes/artifacts/" + artifact["artifact_id"] + "/content")
            assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"]
        for artifact in self.production["artifacts"]:
            status, content = self.request("GET", artifact["download_url"])
            assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"]
            if artifact["artifact_kind"] == "package_zip":
                (self.evidence / "postgres-change-production-v4.zip").write_bytes(content)
        self.report["change_reproduction"] = {"before_area": "104.0000", "after_area": "130.0000", "gross": "16380.00",
            "result": self.change["impact"]["reproduction"], "analysis_files": 3, "new_production_files": 8, "old_production_files": 16}
        status, data = self.request("POST", self.prefix + "/procurement/orders", {
            "supplier_name": "HTTP Supplier", "delivery_location": "HTTP Site", "lines": [
                {"item_name": "Floor A", "ordered_quantity": "10", "unit": "m2"},
                {"item_name": "Floor B", "ordered_quantity": "8", "unit": "m2"},
            ]}, headers={"Idempotency-Key": "http-procurement-order-0001"})
        assert status == 201
        order = json.loads(data)
        self.order_id = order["order_id"]
        lines = [{"line_id": row["line_id"], "quantity": row["ordered_quantity"]} for row in order["lines"]]
        order_prefix = self.prefix + "/procurement/orders/" + self.order_id
        status, data = self.request("POST", order_prefix + "/receipts", {"receiver": "Person", "evidence_ref": "local://http/receipt", "lines": lines},
                                    headers={"Idempotency-Key": "http-procurement-receipt-0001"})
        assert status == 201 and json.loads(data)["status"] == "received"
        status, data = self.request("POST", order_prefix + "/allocations", {"target_area": "Room", "recipient": "Team", "evidence_ref": "local://http/dispatch", "lines": lines},
                                    headers={"Idempotency-Key": "http-procurement-allocation-0001"})
        assert status == 201 and json.loads(data)["status"] == "allocated"
        assert len(json.loads(data)["allocations"]) == 2
        status, data = self.request("GET", "/api/v1/projects")
        assert status == 200 and self.project_id in {item["project_id"] for item in json.loads(data)["items"]}
        assert self.request("GET", self.prefix, headers={"Host": "foreign.example"})[0] == 403
        # Trusted test setup creates a real report-import task; all operations
        # below use the independently running HTTP API.
        from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory
        from rkd_mvp.task_service import TaskService
        from rkd_mvp.task_repository import PostgresTaskRepository
        from rkd_mvp.models import TenantContext
        store = PostgresStore(postgres_connection_factory(self.dsn))
        tasks = TaskService(None, repository=PostgresTaskRepository(store))
        job = tasks.ensure_ningbo_seed("org-local", self.project_id, self.root / "fixtures/ningbo-xiecheng/2026-09")
        self.job_id = job["job_id"]
        status, data = self.request("GET", self.prefix + "/jobs")
        assert status == 200 and json.loads(data)["items"][0]["status"] == "succeeded"
        status, data = self.request("GET", self.prefix + "/issues")
        assert status == 200 and len(json.loads(data)["items"]) == 5
        issue = json.loads(data)["items"][0]
        self.issue_prefix = self.prefix + "/issues/" + issue["issue_id"]
        status, data = self.request("PATCH", self.issue_prefix, {"expected_version": issue["version"], "status": "in_review", "reason": "HTTP source review"}, headers={"X-Actor-Id": "forged-manager"})
        assert status == 200 and json.loads(data)["disposition_actor_id"] == "local-user"
        assert self.request("PATCH", self.issue_prefix, {"expected_version": issue["version"], "status": "resolved", "reason": "stale"})[0] == 409
        with store.tenant_transaction(TenantContext("org-local", self.project_id, "test-setup")) as db:
            db.execute("UPDATE rkd.job SET status='retryable' WHERE job_id=%s", (self.job_id,))
        status, data = self.request("POST", self.prefix + "/jobs/" + self.job_id + "/retry", {})
        assert status == 202 and json.loads(data)["attempt_count"] == 2
        self.job = json.loads(data)
        assert self.request("POST", self.prefix + "/jobs/" + self.job_id + "/cancel", {})[0] == 409
        self.report["task_issue_http"] = {"job_id": self.job_id, "status": self.job["status"], "attempts": 2, "issues": 5, "issue_version": 2, "source_hash": self.job["input_hash"]}
        fixture = self.root / "fixtures/ningbo-xiecheng/2026-09"
        extract = json.loads((fixture / "derived/budget-source-extract.json").read_text(encoding="utf-8"))
        budget_bytes = (fixture / "source/20260721宁波协诚集团样品展厅装修预算.xls").read_bytes()
        status, data = self.request("POST", self.prefix + "/uploads", {"filename": "http-budget.xls", "size_bytes": len(budget_bytes)})
        assert status == 201
        upload_id = json.loads(data)["upload_id"]
        assert self.request("PUT", self.prefix + "/uploads/" + upload_id + "/content", budget_bytes, raw=True)[0] == 200
        status, data = self.request("POST", self.prefix + "/uploads/" + upload_id + "/complete", {"completed_sha256": hashlib.sha256(budget_bytes).hexdigest()})
        assert status == 201
        source = json.loads(data)
        with store.tenant_transaction(TenantContext("org-local", self.project_id, "test-setup")) as db:
            db.execute("UPDATE rkd.file_asset SET source_ref=%s WHERE file_id=%s", (extract["source"]["asset_id"], source["file_id"]))
        from rkd_mvp.estimate_service import EstimateService
        from rkd_mvp.estimate_repository import PostgresEstimateRepository
        estimates = EstimateService(None, repository=PostgresEstimateRepository(store), runtime_root=self.evidence / "api-runtime")
        estimate = estimates.seed_ningbo("org-local", self.project_id, fixture)
        self.estimate_prefix = self.prefix + "/estimates/" + estimate["estimate_id"]
        status, data = self.request("GET", self.estimate_prefix)
        assert status == 200 and json.loads(data)["calculation"]["result"]["source_reconciliation_difference"] == "0.00"
        status, data = self.request("POST", self.estimate_prefix + "/export", {})
        assert status == 201
        self.estimate_old_artifacts = json.loads(data)["items"]
        status, data = self.request("PATCH", self.estimate_prefix + "/lines/xls-exhibition-r004", {"expected_revision": 1, "quantity": "7.5", "change_reason": "HTTP quantity test"})
        assert status == 200 and json.loads(data)["revision_no"] == 2
        status, data = self.request("POST", self.estimate_prefix + "/calculations", {"expected_revision": 2, "design_cost_net": "1000", "change_reason": "HTTP markup and tax test"})
        assert status == 200, data
        self.estimate = json.loads(data)
        assert self.estimate["calculation"]["result"]["design_gross_sale"] == "1680.00"
        assert self.request("POST", self.estimate_prefix + "/calculations", {"expected_revision": 2})[0] == 409
        status, data = self.request("POST", self.estimate_prefix + "/export", {})
        assert status == 201
        self.estimate_artifacts = json.loads(data)["items"]
        for artifact in self.estimate_artifacts:
            status, content = self.request("GET", artifact["download_url"])
            assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"]
            (self.evidence / artifact["filename"]).write_bytes(content)
        self.report["estimate_http"] = {"revision_no": self.estimate["revision_no"], "lines": len(self.estimate["lines"]),
            "source_reconciliation_difference": "0.00", "design_gross_sale": "1680.00", "new_artifacts": 2, "old_artifacts": 2}
        spatial_request = {"width": "10", "length": "5", "expected_revision": 0, "pricing": {"unit_cost_net": "100", "cost_markup": "0.20", "trial_tax_rate": "0.05"}}
        status, data = self.request("POST", self.prefix + "/spatial/revisions", spatial_request)
        assert status == 201, data
        first = json.loads(data)
        assert first["quote"]["result"]["sale_gross"] == "6300.00"
        self.spatial_old_artifacts = first["artifacts"]
        for expected, width, cost in ((1, "12", "100"), (2, "10", "100"), (3, "10", "200")):
            spatial_request.update({"expected_revision": expected, "width": width, "pricing": {"unit_cost_net": cost, "cost_markup": "0.20", "trial_tax_rate": "0.05"}})
            status, data = self.request("POST", self.prefix + "/spatial/revisions", spatial_request)
            assert status == 201, data
        self.spatial = json.loads(data)
        assert (self.spatial["revision_no"], self.spatial["width"], self.spatial["quote"]["result"]["sale_gross"]) == (4, "10", "12600.00")
        spatial_request["expected_revision"] = 4
        assert json.loads(self.request("POST", self.prefix + "/spatial/revisions", spatial_request)[1])["geometry_revision_id"] == self.spatial["geometry_revision_id"]
        for artifact in [*self.spatial_old_artifacts, *self.spatial["artifacts"]]:
            status, content = self.request("GET", artifact["download_url"])
            assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"]
            if artifact["artifact_kind"] == "package_zip" and artifact in self.spatial["artifacts"]:
                (self.evidence / "postgres-spatial-v4.zip").write_bytes(content)
            if artifact["artifact_kind"] == "manifest_json" and artifact in self.spatial["artifacts"]:
                assert json.loads(content)["quantity_item_id"] == self.spatial["quantity_items"][0]["quantity_item_id"]
        self.report["spatial_http"] = {"revision_no": 4, "width": "10", "gross": "12600.00", "old_artifacts": 6, "new_artifacts": 6, "current_noop_reused": True}
        self.report["initial_http"] = True

    def enable_accounts(self):
        import secrets
        from rkd_mvp.account_identity import AccountIdentityProvider
        from rkd_mvp.account_repository import PostgresAccountRepository
        from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory
        provider = AccountIdentityProvider(None, repository=PostgresAccountRepository(PostgresStore(postgres_connection_factory(self.dsn))))
        password = secrets.token_urlsafe(24)
        username = "http-admin-" + uuid4().hex
        admin = provider.bootstrap(username, "HTTP isolated administrator", password)
        # The already-running local process must immediately stop serving even
        # previously signed downloads when the trusted CLI enables accounts.
        assert self.request("GET", self.prefix)[0] == 401
        assert self.request("GET", self.prefix + "/files/" + self.file_id + "/content?signature=fake")[0] == 401
        self.stop()
        downgrade = subprocess.run([sys.executable, str(self.root / "mvp/run_postgres_api.py")], cwd=self.root,
                                  env={**os.environ, "RKD_POSTGRES_DSN": self.dsn, "RKD_POSTGRES_RUNTIME": str(self.runtime_root), "RKD_POSTGRES_PORT": "0", "RKD_AUTH_MODE": "local", "PYTHONUTF8": "1"},
                                  capture_output=True, text=True, encoding="utf-8", timeout=20)
        assert downgrade.returncode != 0 and "refusing local identity downgrade" in downgrade.stderr
        self.start()
        assert self.request("GET", "/api/v1/auth/config")[0] == 200
        assert json.loads(self.request("GET", "/api/v1/auth/config")[1])["mode"] == "accounts"
        assert self.request("GET", self.prefix)[0] == 401
        status, data = self.request("POST", "/api/v1/auth/login", {"username": username, "password": password})
        assert status == 200
        session = json.loads(data)
        self.auth_headers = {"Cookie": self.last_response_headers["Set-Cookie"].split(";",1)[0], "X-CSRF-Token": session["csrf_token"]}
        identity = provider.authenticate(self.auth_headers)
        viewer_name = "http-viewer-" + uuid4().hex
        viewer = provider.create_user(identity, {"username": viewer_name, "display_name": "HTTP read only", "password": password})
        provider.set_member(identity, self.project_id, {"user_id": viewer['user_id'], "role": "viewer"})
        status, data = self.request("POST", "/api/v1/auth/login", {"username": viewer_name, "password": password})
        assert status == 200
        viewer_session = json.loads(data)
        self.viewer_headers = {"Cookie": self.last_response_headers['Set-Cookie'].split(';',1)[0], "X-CSRF-Token": viewer_session['csrf_token']}
        url = self.prefix + "/files/" + self.file_id + "/content"
        assert self.request("GET", url, headers=self.viewer_headers)[0] == 200
        assert self.request("PATCH", self.prefix, {"name":"denied", "expected_version":1}, headers=self.viewer_headers)[0] == 403
        assert self.request("POST", self.prefix + "/members", {"user_id": viewer['user_id'], "role":"none"})[0] == 200
        assert self.request("GET", url, headers=self.viewer_headers)[0] == 404
        assert self.request("POST", self.prefix + "/members", {"user_id": viewer['user_id'], "role":"viewer"})[0] == 200
        browser_evidence = self.evidence / "account-browser"
        browser_evidence.mkdir()
        # WorkBuddy/CodeBuddy sandboxes inject HTTP(S)_PROXY. Playwright's
        # request context honours it and breaks loopback acceptance, so remove
        # proxy variables for this isolated local browser process only.
        browser_env = {key: value for key, value in os.environ.items()
                       if key not in {"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                                      "ALL_PROXY", "all_proxy"}}
        browser_env.update({"RKD_QA_URL": f"http://127.0.0.1:{self.port}",
                            "RKD_QA_EVIDENCE_DIR": str(browser_evidence),
                            "RKD_QA_PASSWORD": password, "RKD_QA_ADMIN_USERNAME": username,
                            "RKD_QA_RACE_PROJECT_ID": self.project_id,
                            "RKD_QA_VIEWER_USERNAME": "browser-viewer-" + uuid4().hex})
        node = subprocess.run(["node", str(self.root / "scripts/verify_m5_browser.cjs")], cwd=self.root,
                              env=browser_env,
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        (browser_evidence / "browser.log").write_text(node.stdout + node.stderr, encoding="utf-8")
        assert node.returncode == 0, "PostgreSQL account browser verification failed"
        self.report['account_browser'] = {"passed":True, "evidence":"account-browser/accounts-browser.json"}
        self.report['identity_http'] = {"mode":"accounts", "live_local_access_revoked":True, "downgrade_refused":True, "viewer_write_refused":True, "download_membership_rechecked":True, "no_default_password":True}

    def verify_persisted(self):
        if hasattr(self, "viewer_headers"):
            assert self.request("GET", self.prefix, headers=self.viewer_headers)[0] == 200
            assert self.request("GET", "/api/v1/auth/session")[0] == 200
        status, data = self.request("GET", self.prefix)
        assert status == 200 and json.loads(data)["version"] == 1
        status, data = self.request("GET", self.prefix + "/files")
        assert status == 200 and len(json.loads(data)["items"]) == 3
        # Signed URLs are recreated for each server incarnation.
        for item in json.loads(data)["items"]:
            status, content = self.request("GET", item["download_url"])
            assert status == 200 and hashlib.sha256(content).hexdigest() == item["sha256"]
        assert not list((self.evidence / "api-runtime").rglob("*.sqlite3"))
        status, data = self.request("GET", self.prefix + "/jobs")
        assert status == 200 and json.loads(data)["items"][0] == self.job
        status, data = self.request("GET", self.issue_prefix)
        issue = json.loads(data)
        assert status == 200 and issue["version"] == 2 and len(issue["actions"]) == 1
        assert issue["actions"][0]["actor_id"] == "local-user"
        status, data = self.request("GET", self.prefix + "/spatial")
        assert status == 200 and json.loads(data)["items"][0] == self.spatial
        for artifact in [*self.spatial_old_artifacts, *self.spatial["artifacts"]]:
            status, content = self.request("GET", artifact["download_url"])
            assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"]
        assert json.loads(self.request("GET", self.estimate_prefix)[1]) == self.estimate
        for artifact in [*self.estimate_old_artifacts, *self.estimate_artifacts]:
            status, content = self.request("GET", artifact["download_url"])
            assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"]
        status, data = self.request("GET", self.prefix + "/requirements")
        requirement = json.loads(data)["item"]
        assert status == 200 and requirement["revision_no"] == 4
        assert requirement["content"]["design_notes"] == "HTTP PostgreSQL 16m"
        assert len(requirement["source_refs"]) == 2
        assert requirement["content"]["design_program"]["width"] == "20"
        assert json.loads(self.request("GET", self.change_prefix)[1]) == self.change
        for artifact in self.change_artifacts:
            status, content = self.request("GET", self.prefix + "/changes/artifacts/" + artifact["artifact_id"] + "/content")
            assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"]
        status, data = self.request("GET", self.prefix + "/production")
        assert status == 200 and json.loads(data)["item"] == self.production
        for artifact in [*self.old_artifacts, *self.production["artifacts"]]:
            status, content = self.request("GET", artifact["download_url"])
            assert status == 200 and hashlib.sha256(content).hexdigest() == artifact["sha256"]
        status, data = self.request("GET", self.prefix + "/procurement/orders/" + self.production["procurement"]["order_id"])
        assert status == 200 and json.loads(data)["source_ref"] == self.production["production_revision_id"]
        status, data = self.request("GET", self.prefix + "/procurement/orders/" + self.order_id)
        order = json.loads(data)
        assert status == 200 and order["status"] == "allocated" and len(order["allocations"]) == 2
        assert len(order["receipts"]) == 1 and len(order["receipts"][0]["lines"]) == 2

    def finish(self):
        self.stop()
        (self.evidence / "api-verification.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
