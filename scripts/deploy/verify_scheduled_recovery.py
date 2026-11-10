"""Restore the latest scheduled archive to a new database, without stopping live service."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "mvp"))


def main():
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory
    from rkd_mvp.postgres_api_service import PostgresApiService
    from rkd_mvp.postgres_backup import create_postgres_backup, restore_postgres_backup
    from rkd_mvp.models import TenantContext
    deployment = Path(sys.argv[1]).resolve()
    latest=json.loads((deployment/'operations/latest-backup-success.json').read_text())
    archive=Path(latest['archive']).resolve()
    if not latest['passed'] or not archive.is_relative_to(deployment/'backups'):
        raise RuntimeError('invalid latest backup')
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=latest['sha256']:
        raise RuntimeError('backup archive changed')
    output=deployment/'recovery-checks'/('scheduled-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'))
    output.mkdir(parents=True,mode=0o700)
    from nas_maintenance import pg_tools
    tools=output/'tools'
    pg_tools(tools)
    owner_password=(deployment/'secrets/owner_password').read_text().strip()
    app_password=(deployment/'secrets/app_password').read_text().strip()
    def dsn(database, owner=True):
        return make_conninfo(host='127.0.0.1',port=15432,dbname=database,
                             user='rkd_owner' if owner else 'rkd_app',password=owner_password if owner else app_password)
    source=dsn('rkd_team')
    report={'passed':False,'live_runtime_replaced':False,'live_service_stopped':False,'archive':str(archive)}
    (output/'verification.json').write_text(json.dumps(report))
    database='rkd_restore_'+secrets.token_hex(5)
    factory=postgres_connection_factory(source,application_role=False)
    with closing(factory()) as db:
        db.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(database)))
    restored=restore_postgres_backup(archive,dsn(database),output/'restored',tools,application_role='rkd_app')
    store=PostgresStore(postgres_connection_factory(dsn(database,False)))
    service=PostgresApiService(store,output/'restored/runtime')
    projects=service.list_projects('org-local')['items']
    verified=0
    tables=('file_asset','spatial_artifact','estimate_artifact','design_artifact','production_artifact','change_artifact')
    for project in projects:
        context=TenantContext('org-local',project['project_id'],'nas-recovery-verification')
        with store.tenant_transaction(context) as db:
            for table in tables:
                column='storage_key' if table=='file_asset' else 'relative_path'
                records=db.execute(sql.SQL('SELECT {},sha256,size_bytes FROM rkd.{}').format(sql.Identifier(column),sql.Identifier(table))).fetchall()
                for name,digest,size in records:
                    data=(output/'restored/runtime'/name).read_bytes()
                    assert len(data)==size and hashlib.sha256(data).hexdigest()==digest
                    verified+=1
    assert verified==restored['runtime_files_verified']
    from rkd_mvp.account_identity import AccountIdentityProvider
    from rkd_mvp.account_repository import PostgresAccountRepository
    assert AccountIdentityProvider(None,repository=PostgresAccountRepository(store)).has_users()
    with closing(postgres_connection_factory(dsn(database),application_role=False)()) as db:
        assert db.execute('SELECT count(*) FROM rkd.auth_session').fetchone()[0]==0
    # Launch the recovered application baseline, never the checkout's server.
    env={**os.environ,'RKD_POSTGRES_DSN':dsn(database,False),'RKD_POSTGRES_RUNTIME':str(output/'restored/runtime'),
         'RKD_TEAM_PORT':'18081','RKD_PUBLIC_ORIGIN':'http://127.0.0.1:18081'}
    with (output/'restored-api.log').open('w') as log:
        process=subprocess.Popen([sys.executable,str(output/'restored/application/mvp/run_team_api.py')],
                                 env=env,cwd=output/'restored/application',stdout=log,stderr=subprocess.STDOUT)
        try:
            ready=False
            for _ in range(40):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18081/api/health/ready',timeout=2) as response:
                        ready=response.status==200
                        if ready: break
                except OSError: time.sleep(.5)
            assert ready
            try: urllib.request.urlopen('http://127.0.0.1:18081/api/v1/projects',timeout=3)
            except urllib.error.HTTPError as error: assert error.code==401
            else: raise AssertionError('restored API permitted anonymous business access')
        finally:
            process.terminate()
            process.wait(timeout=15)
    report.update(passed=True,restored=restored,projects_verified=len(projects),files_verified=verified,
                  archive=str(archive),archive_sha256=latest['sha256'],
                  archived_api_ready=True,archived_api_account_guard=True,restored_auth_initialized=True)
    (output/'verification.json').write_text(json.dumps(report,indent=2))
    (deployment/'operations/latest-scheduled-recovery.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':
    main()
