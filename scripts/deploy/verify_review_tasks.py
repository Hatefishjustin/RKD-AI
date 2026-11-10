"""Run draft-review scenarios on new isolated PostgreSQL databases, never live accounts."""
from contextlib import closing
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'mvp')]


def main():
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from fastapi.testclient import TestClient
    from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory
    from rkd_mvp.postgres_migrations import PostgresMigrationRunner
    from rkd_mvp.postgres_api_service import PostgresApiService
    from rkd_mvp.account_repository import PostgresAccountRepository
    from rkd_mvp.account_identity import AccountIdentityProvider
    from rkd_mvp.asgi_app import create_app
    from rkd_mvp.models import TenantContext
    from mvp.tests.test_review_tasks import ReviewTaskTests
    deployment=Path(sys.argv[1]).resolve()
    owner=(deployment/'secrets/owner_password').read_text().strip()
    app=(deployment/'secrets/app_password').read_text().strip()
    def dsn(database,role):
        return make_conninfo(host='127.0.0.1',port=15432,dbname=database,user=role,password=owner if role=='rkd_owner' else app)
    databases=[]
    class PostgreSQLReviewTests(ReviewTaskTests):
        def setUp(self):
            database='rkd_review_'+secrets.token_hex(5);databases.append(database)
            with closing(postgres_connection_factory(dsn('rkd_team','rkd_owner'),application_role=False)()) as db:
                db.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(database)))
            factory=postgres_connection_factory(dsn(database,'rkd_owner'),application_role=False)
            self.assertEqual(PostgresMigrationRunner(factory).apply(),tuple(range(1,11)))
            with closing(factory()) as db:
                db.execute('GRANT USAGE ON SCHEMA rkd TO rkd_app')
                db.execute('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA rkd TO rkd_app')
                db.execute('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA rkd TO rkd_app')
            self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
            self.store=PostgresStore(postgres_connection_factory(dsn(database,'rkd_app')))
            self.service=PostgresApiService(self.store,self.root)
            self.service.create_project('org-local','Alpha','alpha');self.service.create_project('org-local','Beta','beta')
            self.auth=AccountIdentityProvider(None,repository=PostgresAccountRepository(self.store))
            self.password=secrets.token_urlsafe(24)
            self.auth.bootstrap('admin','Isolated verification',self.password)
            self.static=self.root/'dist';self.static.mkdir();(self.static/'index.html').write_text('test')
            self.app=create_app(self.service,self.auth,self.static,'https://nas.example')
            self.client=TestClient(self.app,base_url='https://nas.example')
        def tearDown(self):
            with self.store.tenant_transaction(TenantContext('foreign-org','alpha','test')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM rkd.review_task').fetchone()[0],0)
            self.client.close();self.temp.cleanup()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PostgreSQLReviewTests))
    report={'passed':result.wasSuccessful(),'tests':result.testsRun,'isolated_databases':databases,'application_role':'rkd_app','live_accounts_changed':False,'formal_release_allowed':False}
    print(json.dumps(report))
    if not result.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':main()
