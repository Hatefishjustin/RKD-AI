"""Actual full application recovery, including archived-code HTTP and restarts."""
from contextlib import closing
import copy
import hashlib
import io
import json
from pathlib import Path
import zipfile

from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.account_repository import PostgresAccountRepository
from rkd_mvp.api_service import ApiError
from rkd_mvp.local_backup import BackupRejected
from rkd_mvp.models import TenantContext
from rkd_mvp.postgres_api_service import PostgresApiService
from rkd_mvp.postgres_backup import create_postgres_backup, restore_postgres_backup, _inventory
from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory
from postgres_api_probe import PostgresApiProbe


class PostgresRecoveryProbe:
    def __init__(self, root, evidence, source_dsn, app_dsn, password):
        self.root, self.evidence = root, evidence
        self.source_dsn, self.app_dsn, self.password = source_dsn, app_dsn, password
        self.binary = root / "var/tools/postgresql-17.11-5/pgsql/bin"
        self.source_factory = postgres_connection_factory(source_dsn, application_role=False)
        self.report = {"passed":False, "source_unchanged":False, "existing_runtime_replaced":False}
        self.api = None
        self.daily_api = None

    def prepare(self):
        from rkd_mvp.design_rules import DEFAULT_PROGRAM
        self.org, self.project = "org-local", "identity-project"
        self.store = PostgresStore(postgres_connection_factory(self.app_dsn))
        service = PostgresApiService(self.store, self.evidence)
        auth = AccountIdentityProvider(None, repository=PostgresAccountRepository(self.store))
        self.old_token, _ = auth.login("migration-test", self.password, "recovery-source")
        identity = auth.authenticate({"Cookie":"rkd_session=" + self.old_token})
        viewer = auth.create_user(identity, {"username":"recovery-viewer", "display_name":"Recovery read only", "password":self.password})
        auth.set_member(identity, self.project, {"user_id":viewer['user_id'], "role":"viewer"})
        self.viewer_id = viewer['user_id']
        fixture = self.root / "fixtures/ningbo-xiecheng/2026-09"
        content = (fixture / "source/20260721宁波协诚集团样品展厅装修预算.xls").read_bytes()
        upload = service.initiate_upload(self.org, self.project, {"filename":"recovery-source.xls", "size_bytes":len(content)})
        service.receive_upload(self.org, self.project, upload['upload_id'], io.BytesIO(content), len(content))
        asset = service.complete_upload(self.org, self.project, upload['upload_id'], hashlib.sha256(content).hexdigest())
        extract = json.loads((fixture / "derived/budget-source-extract.json").read_text(encoding="utf-8"))
        with self.store.tenant_transaction(TenantContext(self.org,self.project,"setup")) as db:
            db.execute("UPDATE rkd.file_asset SET source_ref=%s WHERE file_id=%s", (extract['source']['asset_id'],asset['file_id']))
        estimate = service.estimate_service.seed_ningbo(self.org, self.project, fixture)
        service.export_estimate(self.org,self.project,estimate['estimate_id'],identity.actor_id)
        self.estimate_id = estimate['estimate_id']
        job = service.task_service.ensure_ningbo_seed(self.org,self.project,fixture)
        self.job_id = job['job_id']
        issues = service.list_issues(self.org,self.project)['items']
        service.record_issue_disposition(self.org,self.project,issues[0]['issue_id'],
                                        {"expected_version":1,"status":"in_review","reason":"Recovery evidence"},identity.actor_id)
        service.create_spatial_revision(self.org,self.project,{"width":"10","length":"5","pricing":{"unit_cost_net":"100"}},identity.actor_id)
        service.create_spatial_revision(self.org,self.project,{"width":"12","length":"5","expected_revision":1,"pricing":{"unit_cost_net":"100"}},identity.actor_id)
        program = copy.deepcopy(DEFAULT_PROGRAM)
        program['width'] = "16"
        change = service.create_change(self.org,self.project,identity.actor_id,
                    {"title":"Recovery structured change","reason":"Test boundary review","description":"Isolated recovery test only","design_program":program},"recovery-change-create-0001")
        change = service.analyze_change(self.org,self.project,change['change_id'],identity.actor_id,{"expected_version":change['version']},"recovery-change-analyze-0001")
        accepted = service.accept_change(self.org,self.project,change['change_id'],identity.actor_id,
                    {"expected_version":change['version'],"conclusion":"accepted","checklist":["Test dimensions reviewed"],"evidence_ref":"local://recovery/test"},"recovery-change-accept-0001")
        self.accepted = accepted
        self.change = service.reproduce_change(self.org,self.project,change['change_id'],identity.actor_id,{"expected_version":accepted['version']},"recovery-change-apply-0001")
        production = service.get_production(self.org,self.project)['item']
        self.order_id = production['procurement']['order_id']
        order = service.get_procurement_order(self.org,self.project,self.order_id)
        self.receipt = {"receiver":"Isolated test receiver","evidence_ref":"local://recovery/receipt","lines":[{"line_id":order['lines'][0]['line_id'],"quantity":"6"}]}
        self.received = service.receive_procurement(self.org,self.project,self.order_id,identity.actor_id,self.receipt,"recovery-receipt-key-0001")
        service.initiate_upload(self.org,self.project,{"filename":"incomplete.pdf","size_bytes":25})
        self.production = production
        self.report['prepared'] = {"quote_gross":production['quote']['sale_gross'],"quantity":production['quote']['quantity'],
                                   "estimate_lines":len(estimate['lines']),"issues":len(issues),"accounts":2}
        with closing(self.source_factory()) as db:
            db.execute("SET TIME ZONE 'UTC'")
            self.source_before = _inventory(db)

    def recover(self):
        archive = self.evidence / "postgres-complete.zip"
        backup = create_postgres_backup(self.source_dsn,self.evidence,archive,self.root,self.binary)
        (self.evidence / "postgres-backup-manifest.json").write_text(json.dumps(backup,ensure_ascii=False,indent=2),encoding="utf-8")
        owner_info = conninfo_to_dict(self.source_dsn)
        with closing(self.source_factory()) as db:
            db.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier("rkd_full_restore")))
        self.target_dsn = make_conninfo(**{**owner_info,"dbname":"rkd_full_restore"})
        self.target_app_dsn = make_conninfo(**{**conninfo_to_dict(self.app_dsn),"dbname":"rkd_full_restore"})
        destination = self.evidence / "postgres-restored"
        # Corruption must fail before even creating the PostgreSQL schema.
        corrupted = self.evidence / "postgres-corrupted.zip"
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(corrupted,"x",zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "database/rkd.dump":
                    data = (b"X" if data[:1] != b"X" else b"Y") + data[1:]
                target.writestr(info,data)
        try:
            restore_postgres_backup(corrupted,self.target_dsn,self.evidence / "corrupt-restored",self.binary,application_role="rkd_app")
        except BackupRejected:
            with closing(postgres_connection_factory(self.target_dsn,application_role=False)()) as db:
                assert db.execute("SELECT to_regnamespace('rkd') IS NULL").fetchone()[0]
            self.report['corrupt_before_database_write'] = True
        else:
            raise AssertionError("corrupt PostgreSQL archive accepted")
        restored = restore_postgres_backup(archive,self.target_dsn,destination,self.binary,application_role="rkd_app")
        assert restored['sessions_invalidated'] >= 1 and restored['uploads_require_reupload'] == 1
        self.report['restored'] = restored
        try:
            restore_postgres_backup(archive,self.target_dsn,self.evidence / "refuse-second-restore",self.binary,application_role="rkd_app")
        except BackupRejected:
            self.report['nonempty_database_refused'] = True
        else:
            raise AssertionError("nonempty recovery target accepted")
        try:
            restore_postgres_backup(archive,self.target_dsn,destination,self.binary,application_role="rkd_app")
        except BackupRejected:
            self.report['existing_directory_refused'] = True
        else:
            raise AssertionError("existing runtime overwritten")
        # A normal application role may not silently create a partial RLS backup.
        try:
            create_postgres_backup(self.target_app_dsn,destination / "runtime",self.evidence / "partial-rls.zip",self.root,self.binary,baseline_files=[])
        except BackupRejected:
            self.report['partial_rls_backup_refused'] = True
        else:
            raise AssertionError("non-owner backup accepted")
        with closing(self.source_factory()) as db:
            db.execute("SET TIME ZONE 'UTC'")
            assert _inventory(db) == self.source_before
        self.report['source_unchanged'] = True
        with closing(postgres_connection_factory(self.target_dsn,application_role=False)()) as db:
            # The two catalogues must keep explicit EXECUTE grants only after
            # restoring a dump that deliberately excludes machine-specific ACLs.
            assert db.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace, LATERAL aclexplode(p.proacl) a WHERE n.nspname='rkd' AND p.prosecdef AND a.grantee=0 AND a.privilege_type='EXECUTE'").fetchone()[0] == 0
        self.api = PostgresApiProbe(destination / "application",self.evidence / "recovered-http",self.target_app_dsn,destination / "runtime")
        self.api.evidence.mkdir()
        self.api.start()
        self.api.auth_headers = {"Cookie":"rkd_session=" + self.old_token}
        assert self.api.request("GET","/api/v1/projects")[0] == 401
        status,data = self.api.request("POST","/api/v1/auth/login",{"username":"migration-test","password":self.password})
        assert status == 200
        session = json.loads(data)
        self.api.auth_headers = {"Cookie":self.api.last_response_headers['Set-Cookie'].split(';',1)[0],"X-CSRF-Token":session['csrf_token']}
        self.verify_http()
        self.api.stop()
        self.api.start()
        self.verify_http()
        self.report['archived_code_api_restart'] = True
        self.report['isolated_restore_passed'] = True

    def verify_http(self):
        prefix = "/api/v1/projects/" + self.project
        for suffix in ("", "/files", "/jobs", "/issues", "/estimates", "/spatial", "/requirements", "/design", "/production", "/procurement/orders", "/changes", "/members"):
            assert self.api.request("GET",prefix + suffix)[0] == 200,suffix
        assert json.loads(self.api.request("GET",prefix + "/production")[1])['item'] == self.production
        assert json.loads(self.api.request("GET",prefix + "/changes/" + self.change['change_id'])[1]) == self.change
        restored_store = PostgresStore(postgres_connection_factory(self.target_app_dsn))
        service = PostgresApiService(restored_store,self.api.runtime_root)
        # Idempotency fingerprints and original actors must survive recovery.
        replay = service.reproduce_change(self.org,self.project,self.change['change_id'],"ignored-replay-actor",
                         {"expected_version":self.accepted['version']},"recovery-change-apply-0001")
        assert replay == self.change
        assert service.receive_procurement(self.org,self.project,self.order_id,"ignored-replay-actor",self.receipt,"recovery-receipt-key-0001") == self.received
        assert len(service.get_procurement_order(self.org,self.project,self.order_id)['receipts']) == 1
        routes = {"file_asset":"files","spatial_artifact":"spatial/artifacts","estimate_artifact":"estimates/artifacts",
                  "design_artifact":"design/artifacts","production_artifact":"production/artifacts","change_artifact":"changes/artifacts"}
        downloads = 0
        with restored_store.tenant_transaction(TenantContext(self.org,self.project,"test")) as db:
            for table,route in routes.items():
                id_column = "file_id" if table == "file_asset" else "artifact_id"
                records = db.execute(sql.SQL("SELECT {},sha256,size_bytes FROM rkd.{}").format(sql.Identifier(id_column),sql.Identifier(table))).fetchall()
                for identifier,digest,size in records:
                    status,content = self.api.request("GET",prefix + "/" + route + "/" + identifier + "/content")
                    assert status == 200 and len(content) == size and hashlib.sha256(content).hexdigest() == digest,(table,identifier,status)
                    downloads += 1
        status,data = self.api.request("POST","/api/v1/auth/login",{"username":"recovery-viewer","password":self.password})
        assert status == 200
        viewer_session = json.loads(data)
        headers = {"Cookie":self.api.last_response_headers['Set-Cookie'].split(';',1)[0],"X-CSRF-Token":viewer_session['csrf_token']}
        assert self.api.request("PATCH",prefix,{"name":"denied","expected_version":0},headers=headers)[0] == 403
        self.report['http'] = {"download_hashes_verified":downloads,"old_session_refused":True,"passwords_roles_preserved":True,
                               "receipt_idempotency_preserved":True,"reproduction_idempotency_preserved":True}

    def finish(self):
        if self.daily_api:
            self.daily_api.finish()
        if self.api:
            self.api.finish()
        (self.evidence / "postgres-recovery-verification.json").write_text(json.dumps(self.report,ensure_ascii=False,indent=2),encoding="utf-8")

    def recover_daily(self, source_dsn):
        """Recover the actual imported daily snapshot, including all 74 files."""
        archive = self.evidence / "postgres-daily-complete.zip"
        backup = create_postgres_backup(source_dsn,self.root / "var",archive,self.root,self.binary)
        (self.evidence / "postgres-daily-backup-manifest.json").write_text(json.dumps(backup,ensure_ascii=False,indent=2),encoding="utf-8")
        with closing(self.source_factory()) as db:
            db.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier("rkd_daily_restore")))
        target = make_conninfo(**{**conninfo_to_dict(source_dsn),"dbname":"rkd_daily_restore"})
        self.daily_app_dsn = make_conninfo(**{**conninfo_to_dict(self.app_dsn),"dbname":"rkd_daily_restore"})
        destination = self.evidence / "postgres-daily-restored"
        restored = restore_postgres_backup(archive,target,destination,self.binary,application_role="rkd_app")
        source_factory = postgres_connection_factory(source_dsn,application_role=False)
        with closing(source_factory()) as db:
            db.execute("SET TIME ZONE 'UTC'")
            assert _inventory(db)[0] == backup['tables']
        self.daily_expected_files = backup['runtime_files']
        self.daily_api = PostgresApiProbe(destination / "application",self.evidence / "daily-recovered-http",self.daily_app_dsn,destination / "runtime")
        self.daily_api.evidence.mkdir()
        self.daily_api.start()
        self.verify_daily_http()
        self.daily_api.stop()
        self.daily_api.start()
        self.verify_daily_http()
        self.report['daily_recovery'] = {**restored, "projects_http":self.daily_project_count,
                "files_http":self.daily_expected_files,"source_unchanged":True,"archived_api_restart":True}

    def verify_daily_http(self):
        status,data = self.daily_api.request("GET","/api/v1/projects")
        assert status == 200
        projects = json.loads(data)['items']
        self.daily_project_count = len(projects)
        downloads = 0
        store = PostgresStore(postgres_connection_factory(self.daily_app_dsn))
        routes = {"file_asset":"files","spatial_artifact":"spatial/artifacts","estimate_artifact":"estimates/artifacts",
                  "design_artifact":"design/artifacts","production_artifact":"production/artifacts","change_artifact":"changes/artifacts"}
        for project in projects:
            prefix = "/api/v1/projects/" + project['project_id']
            for suffix in ("", "/files", "/jobs", "/issues", "/estimates", "/spatial", "/requirements", "/design", "/production", "/procurement/orders", "/changes"):
                assert self.daily_api.request("GET",prefix + suffix)[0] == 200,(prefix,suffix)
            originals = {item['file_id']:item['download_url'] for item in json.loads(self.daily_api.request("GET",prefix + "/files")[1])['items']}
            with store.tenant_transaction(TenantContext(project['organization_id'],project['project_id'],"test")) as db:
                for table,route in routes.items():
                    id_column = "file_id" if table == "file_asset" else "artifact_id"
                    records = db.execute(sql.SQL("SELECT {},sha256,size_bytes FROM rkd.{}").format(sql.Identifier(id_column),sql.Identifier(table))).fetchall()
                    for identifier,digest,size in records:
                        url = originals[identifier] if table == "file_asset" else prefix + "/" + route + "/" + identifier + "/content"
                        status,content = self.daily_api.request("GET",url)
                        assert status == 200 and len(content) == size and hashlib.sha256(content).hexdigest() == digest,(table,identifier,status)
                        downloads += 1
        assert downloads == self.daily_expected_files,(downloads,self.daily_expected_files)
