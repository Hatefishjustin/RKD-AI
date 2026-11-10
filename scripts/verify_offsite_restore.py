"""Restore a verified NAS archive on Windows into a new loopback-only cluster."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mvp'))


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));return probe.getsockname()[1]


def main():
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from rkd_mvp.postgres_backup import restore_postgres_backup
    from rkd_mvp.postgres_store import postgres_connection_factory,PostgresStore
    from rkd_mvp.postgres_api_service import PostgresApiService
    from rkd_mvp.models import TenantContext
    directory=ROOT/'var/backups/nas'
    latest=json.loads((directory/'latest-success.json').read_text(encoding='utf-8'))
    archive=Path(latest['archive']).resolve()
    if not latest['passed'] or not archive.is_relative_to(directory.resolve()) or hashlib.sha256(archive.read_bytes()).hexdigest()!=latest['sha256']:
        raise RuntimeError('Missing or changed verified offsite archive')
    output=ROOT/'var/evidence/m5-offsite'/('restore-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+secrets.token_hex(3))
    output.mkdir(parents=True)
    report={'passed':False,'at':datetime.now(timezone.utc).isoformat(),'archive':str(archive),'sha256':latest['sha256'],'existing_runtime_replaced':False,'bind':'127.0.0.1'}
    binary=ROOT/'var/tools/postgresql-17.11-5/pgsql/bin'
    cluster=output/'cluster';password_file=output/'init-password'
    owner_password=secrets.token_urlsafe(32);app_password=secrets.token_urlsafe(32)
    port=free_port();api_port=free_port();running=False;process=None
    def dsn(database,role='rkd_recovery'):
        return make_conninfo(host='127.0.0.1',port=port,dbname=database,user=role,password=owner_password if role=='rkd_recovery' else app_password)
    def command(*args):
        with (output/'lifecycle.log').open('a',encoding='utf-8') as log:
            subprocess.run([str(binary/args[0]),*map(str,args[1:])],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90)
    try:
        password_file.write_text(owner_password,encoding='utf-8')
        command('initdb.exe','-D',cluster,'-U','rkd_recovery','--pwfile',password_file,'--auth=scram-sha-256','--encoding=UTF8','--locale=C')
        password_file.unlink()
        command('pg_ctl.exe','-D',cluster,'-l',output/'postgres.log','-w','-t','45','-o',f'-h 127.0.0.1 -p {port}','start');running=True
        with closing(postgres_connection_factory(dsn('postgres'),application_role=False)()) as db:
            db.execute('CREATE DATABASE rkd_restored TEMPLATE template0')
            db.execute(sql.SQL('CREATE ROLE rkd_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION PASSWORD {}').format(sql.Literal(app_password)))
        restored=restore_postgres_backup(archive,dsn('rkd_restored'),output/'restored',binary,application_role='rkd_app')
        store=PostgresStore(postgres_connection_factory(dsn('rkd_restored','rkd_app')))
        service=PostgresApiService(store,output/'restored/runtime');projects=service.list_projects('org-local')['items']
        verified=0
        for project in projects:
            with store.tenant_transaction(TenantContext('org-local',project['project_id'],'offsite-recovery')) as db:
                for table in ('file_asset','spatial_artifact','estimate_artifact','design_artifact','production_artifact','change_artifact'):
                    column='storage_key' if table=='file_asset' else 'relative_path'
                    for name,digest,size in db.execute(sql.SQL('SELECT {},sha256,size_bytes FROM rkd.{}').format(sql.Identifier(column),sql.Identifier(table))).fetchall():
                        data=(output/'restored/runtime'/name).read_bytes()
                        assert len(data)==size and hashlib.sha256(data).hexdigest()==digest
                        verified+=1
        assert verified==restored['runtime_files_verified']
        with closing(postgres_connection_factory(dsn('rkd_restored'),application_role=False)()) as db:
            assert db.execute('SELECT count(*) FROM rkd.auth_session').fetchone()[0]==0
        env={**os.environ,'RKD_POSTGRES_DSN':dsn('rkd_restored','rkd_app'),'RKD_POSTGRES_RUNTIME':str(output/'restored/runtime'),'RKD_TEAM_PORT':str(api_port),'RKD_PUBLIC_ORIGIN':f'http://127.0.0.1:{api_port}'}
        with (output/'archived-api.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,str(output/'restored/application/mvp/run_team_api.py')],env=env,cwd=output/'restored/application',stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            origin=f'http://127.0.0.1:{api_port}'
            ready=False
            for _ in range(60):
                try:
                    with urllib.request.urlopen(origin+'/api/health/ready',timeout=2) as response:ready=response.status==200
                    if ready:break
                except OSError:time.sleep(.5)
            assert ready
            config=json.load(urllib.request.urlopen(origin+'/api/v1/auth/config',timeout=3));assert config['initialized']
            try:urllib.request.urlopen(origin+'/api/v1/projects',timeout=3)
            except urllib.error.HTTPError as error:assert error.code==401
            else:raise AssertionError('anonymous access after recovery')
        report.update(passed=True,restored=restored,projects_verified=len(projects),files_verified=verified,archived_api_ready=True,restored_auth_initialized=True,anonymous_rejected=True,source_engine='PostgreSQL 16 NAS',target_engine='PostgreSQL 17 Windows')
    except Exception as error:
        report['error_type']=type(error).__name__
    finally:
        if process is not None:
            process.terminate();process.wait(timeout=20)
        if running:command('pg_ctl.exe','-D',cluster,'-m','fast','-w','stop')
        if password_file.exists():password_file.unlink()
        report['recovery_cluster_stopped']=running
        (output/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        (directory/'latest-recovery-attempt.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if report['passed']:(directory/'latest-recovery-success.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
