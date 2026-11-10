"""Live verification in a fresh database of RKD's isolated NAS cluster only."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "mvp"))


def main():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from rkd_mvp.postgres_migrations import PostgresMigrationRunner
    from rkd_mvp.postgres_store import postgres_connection_factory
    deployment = Path(sys.argv[1]).resolve()
    owner_password = (deployment / "secrets/owner_password").read_text().strip()
    owner_args = dict(host="127.0.0.1",port=15432,user="rkd_owner",password=owner_password)
    suffix = secrets.token_hex(5)
    database, role = "rkd_verify_"+suffix,"rkd_verify_"+suffix
    password = secrets.token_urlsafe(32)
    with psycopg.connect(make_conninfo(dbname="postgres",**owner_args),autocommit=True) as db:
        db.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database)))
    dsn = make_conninfo(dbname=database,**owner_args)
    owner = postgres_connection_factory(dsn,application_role=False)
    PostgresMigrationRunner(owner).apply()
    with closing(owner()) as db:
        version = db.execute("SELECT version()").fetchone()[0]
        db.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}").format(sql.Identifier(role),sql.Literal(password)))
        db.execute(sql.SQL("GRANT USAGE ON SCHEMA rkd TO {}").format(sql.Identifier(role)))
        db.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA rkd TO {}").format(sql.Identifier(role)))
        db.execute(sql.SQL("GRANT EXECUTE ON FUNCTION rkd.list_project_summaries(),rkd.list_account_project_roles(text) TO {}").format(sql.Identifier(role)))
        db.commit()
    app = postgres_connection_factory(make_conninfo(dbname=database,host="127.0.0.1",port=15432,user=role,password=password))
    report = {"passed":True,"postgres_version":version,"python":sys.version,"database":database,"suites":{}}
    output = deployment / "qa"
    output.mkdir(exist_ok=True)
    for name in ("test_postgres_live","test_postgres_business_live","test_postgres_identity_live"):
        spec = importlib.util.spec_from_file_location(name,ROOT / "mvp/integration" / (name+".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.OWNER_FACTORY,module.APP_FACTORY,module.OWNER_DSN = owner,app,dsn
        with (output / (name+"-pg16.log")).open("w") as stream:
            result = unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
        report['suites'][name] = {"run":result.testsRun,"errors":len(result.errors),"failures":len(result.failures),"skipped":len(result.skipped)}
        report['passed'] &= result.wasSuccessful() and not result.skipped
    (output / "pg16-live.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == "__main__":
    raise SystemExit(main())
