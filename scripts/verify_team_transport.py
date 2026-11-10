"""Actual candidate initializer + PostgreSQL + Uvicorn + browser and restarts."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "mvp"))
sys.path.insert(0,str(ROOT))
from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.account_repository import PostgresAccountRepository
from rkd_mvp.local_backup import create_backup, restore_backup
from rkd_mvp.models import TenantContext
from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory
from postgres_api_probe import PostgresApiProbe
from scripts.deploy.container_entry import initialize


def main():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    evidence = ROOT / "var/evidence/m5-team-transport" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-")+secrets.token_hex(3))
    evidence.mkdir(parents=True)
    print(str(evidence),flush=True)
    binary = ROOT / "var/tools/postgresql-17.11-5/pgsql/bin"
    cluster = evidence / "cluster"
    password_file = evidence / "initial-password"
    owner_password, app_password, user_password = (secrets.token_urlsafe(32) for _ in range(3))
    password_file.write_text(owner_password)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0))
        port = probe.getsockname()[1]
    connection_args = dict(host="127.0.0.1",port=port,user="rkd_owner",password=owner_password)
    owner_dsn = make_conninfo(dbname="rkd_team",**connection_args)
    app_dsn = make_conninfo(dbname="rkd_team",host="127.0.0.1",port=port,user="rkd_app",password=app_password)
    report = {"passed":False,"database":"PostgreSQL 17.11","transport":"FastAPI/Uvicorn","authoritative_cutover":False}
    api = None
    running = False

    def command(*args):
        with (evidence / "database.log").open("a",encoding="utf-8") as log:
            subprocess.run([str(binary / args[0]),*map(str,args[1:])],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)

    try:
        command("initdb.exe","-D",cluster,"-U","rkd_owner","--pwfile",password_file,"--auth=scram-sha-256","--encoding=UTF8","--locale=C")
        password_file.unlink()
        command("pg_ctl.exe","-D",cluster,"-l",evidence / "postgres.log","-w","-o",f"-h 127.0.0.1 -p {port}","start")
        running = True
        with psycopg.connect(make_conninfo(dbname="postgres",**connection_args),autocommit=True) as db:
            db.execute("CREATE DATABASE rkd_team TEMPLATE template0")
        backup = create_backup(ROOT / "var/app.sqlite3",evidence / "source.zip",ROOT)
        restore_backup(evidence / "source.zip",evidence / "source")
        initialize(evidence / "source/runtime",evidence / "runtime",owner_dsn,app_password)
        report['initializer'] = {"files":backup['runtime_files'],"snapshot_at":backup['snapshot_at'],"first_import":True}
        try:
            initialize(evidence / "source/runtime",evidence / "runtime",owner_dsn,app_password)
        except RuntimeError:
            report['existing_database_refused'] = True
        else:
            raise AssertionError("initializer overwrote existing database")
        store = PostgresStore(postgres_connection_factory(app_dsn))
        accounts = AccountIdentityProvider(None,repository=PostgresAccountRepository(store))
        assert not accounts.has_users()
        api = PostgresApiProbe(ROOT,evidence,app_dsn,evidence / "runtime",transport="asgi")
        api.start()
        assert api.request("GET","/api/v1/projects",headers={"X-Organization-Id":"org-local","X-Actor-Id":"admin"})[0] == 401
        config = json.loads(api.request("GET","/api/v1/auth/config")[1])
        assert config['mode'] == "accounts" and config['initialized'] is False
        accounts.bootstrap("team-verify-admin","Isolated verification",user_password)
        status,data = api.request("POST","/api/v1/auth/login",{"username":"team-verify-admin","password":user_password})
        assert status == 200
        api.auth_headers = {"Cookie":api.last_response_headers['Set-Cookie'].split(';',1)[0],"X-CSRF-Token":json.loads(data)['csrf_token']}
        projects = json.loads(api.request("GET","/api/v1/projects")[1])['items']
        files = []
        routes = {"file_asset":"files","spatial_artifact":"spatial/artifacts","estimate_artifact":"estimates/artifacts", "design_artifact":"design/artifacts","production_artifact":"production/artifacts","change_artifact":"changes/artifacts"}
        for project in projects:
            prefix = "/api/v1/projects/" + project['project_id']
            for suffix in ("", "/files", "/jobs", "/issues", "/estimates", "/spatial", "/requirements", "/design", "/production", "/procurement/orders", "/changes"):
                assert api.request("GET",prefix+suffix)[0] == 200,(prefix,suffix)
            with store.tenant_transaction(TenantContext(project['organization_id'],project['project_id'],"test")) as db:
                for table,route in routes.items():
                    column = "file_id" if table == "file_asset" else "artifact_id"
                    records = db.execute(sql.SQL("SELECT {},sha256,size_bytes FROM rkd.{}").format(sql.Identifier(column),sql.Identifier(table))).fetchall()
                    files.extend((prefix + "/" + route + "/" + identifier + "/content",digest,size) for identifier,digest,size in records)

        def verify_files():
            for url,digest,size in files:
                status,data = api.request("GET",url)
                assert status == 200 and len(data) == size and hashlib.sha256(data).hexdigest() == digest
        verify_files()
        assert len(files) == backup['runtime_files']
        report['projects_verified'], report['files_verified'] = len(projects), len(files)
        browser = evidence / "browser"
        browser.mkdir()
        initial_project = next((item for item in projects if item['project_id'] == "project_ningbo_xiecheng_2026"), projects[0])
        child = subprocess.run(["node",str(ROOT / "scripts/verify_m5_browser.cjs")],cwd=ROOT,
                env={**os.environ,"RKD_QA_URL":f"http://127.0.0.1:{api.port}","RKD_QA_EVIDENCE_DIR":str(browser),
                     "RKD_QA_PASSWORD":user_password,"RKD_QA_ADMIN_USERNAME":"team-verify-admin", "RKD_QA_RACE_PROJECT_ID":initial_project['project_id'],
                     "RKD_QA_VIEWER_USERNAME":"team-browser-viewer"},capture_output=True,text=True,encoding="utf-8",timeout=120)
        (evidence / "browser.log").write_text(child.stdout+child.stderr,encoding="utf-8")
        assert child.returncode == 0,"ASGI browser verification failed"
        report['browser'] = json.loads((browser / "accounts-browser.json").read_text(encoding="utf-8"))
        api.stop()
        api.start()
        verify_files()
        report['application_restart_preserves_session_and_files'] = True
        command("pg_ctl.exe","-D",cluster,"-w","restart")
        verify_files()
        report['database_restart_preserves_session_and_files'] = True
        report['passed'] = True
    except BaseException as error:
        report['failure_type'] = type(error).__name__
        raise
    finally:
        if api:
            api.finish()
        if password_file.exists():
            password_file.unlink()
        if running:
            try:
                command("pg_ctl.exe","-D",cluster,"-w","-m","fast","stop")
            except Exception as error:
                report['cleanup_failure'] = type(error).__name__
                report['passed'] = False
        (evidence / "verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"passed":report['passed'],"evidence":str(evidence)},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
