"""Provision an isolated loopback PostgreSQL cluster, verify, then stop it.

Never registers a Windows service or changes the application's SQLite entry.
All evidence and the recoverable test cluster remain under var/evidence/.
"""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))


def main():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from rkd_mvp.postgres_import import ImportRejected, SQLitePostgresImporter
    from rkd_mvp.postgres_migrations import PostgresMigrationRunner
    from rkd_mvp.postgres_store import postgres_connection_factory

    started = time.monotonic()
    run_root = ROOT / "var/evidence/m5-postgres" / ("run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3))
    run_root.mkdir(parents=True)
    binary = ROOT / "var/tools/postgresql-17.11-5/pgsql/bin"
    cluster = run_root / "cluster"
    password_file = run_root / "init-password"
    owner_password = secrets.token_urlsafe(32)
    app_password = secrets.token_urlsafe(32)
    password_file.write_text(owner_password, encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    connection_args = dict(host="127.0.0.1", port=port, user="rkd_migration", password=owner_password)
    owner_dsn = make_conninfo(dbname="postgres", **connection_args)
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "evidence_directory": str(run_root),
              "port": port, "bind": "127.0.0.1", "sqlite_runtime_cutover": False, "checks": {}}
    running = False
    api_probe = None
    recovery_probe = None

    def command(*args):
        # On Windows a background postgres child may inherit pipe handles from
        # pg_ctl. Write lifecycle output directly to disk so communicate()
        # cannot wait indefinitely for the server to close an inherited pipe.
        with (run_root / "lifecycle.log").open("a", encoding="utf-8") as log:
            result = subprocess.run([str(binary / args[0]), *map(str, args[1:])], cwd=ROOT,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=60)
        if result.returncode:
            raise RuntimeError(f"{args[0]} failed; see lifecycle.log")

    def create_database(name):
        with psycopg.connect(owner_dsn, autocommit=True) as db:
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        factory = postgres_connection_factory(make_conninfo(dbname=name, **connection_args), application_role=False)
        PostgresMigrationRunner(factory).apply()
        return factory

    try:
        print(f"Evidence: {run_root}", flush=True)
        command("initdb.exe", "-D", cluster, "-U", "rkd_migration", "--pwfile", password_file,
                "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C")
        password_file.unlink()
        command("pg_ctl.exe", "-D", cluster, "-l", run_root / "postgres.log", "-w", "-t", "45",
                "-o", f"-h 127.0.0.1 -p {port}", "start")
        running = True
        owner = create_database("rkd_kernel")
        with owner() as db:
            report["postgres_version"] = db.execute("SELECT version()").fetchone()[0]
            db.execute(sql.SQL("CREATE ROLE rkd_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION PASSWORD {}").format(sql.Literal(app_password)))
            db.execute("GRANT USAGE ON SCHEMA rkd TO rkd_app")
            db.execute("GRANT EXECUTE ON FUNCTION rkd.list_project_summaries(), rkd.list_account_project_roles(text) TO rkd_app")
            tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='rkd' AND tablename<>'schema_migration'").fetchall()
            for (table,) in tables:
                db.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON rkd.{} TO rkd_app").format(sql.Identifier(table)))
        app_factory = postgres_connection_factory(make_conninfo(dbname="rkd_kernel", host="127.0.0.1", port=port, user="rkd_app", password=app_password))
        spec = importlib.util.spec_from_file_location("test_postgres_live", ROOT / "mvp/integration/test_postgres_live.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.OWNER_FACTORY = owner
        module.APP_FACTORY = app_factory
        module.OWNER_DSN = make_conninfo(dbname="rkd_kernel", **connection_args)
        print("Running live RLS / concurrency / rollback / lease tests", flush=True)
        with (run_root / "live-tests.log").open("w", encoding="utf-8") as stream:
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
        report["tests"] = {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped)}
        if not result.wasSuccessful() or result.skipped:
            raise RuntimeError("live PostgreSQL tests failed; see live-tests.log")

        spec = importlib.util.spec_from_file_location("test_postgres_business_live", ROOT / "mvp/integration/test_postgres_business_live.py")
        business_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(business_module)
        business_module.APP_FACTORY = app_factory
        print("Running real project/file business workflow and concurrent byte tests", flush=True)
        with (run_root / "business-tests.log").open("w", encoding="utf-8") as stream:
            business_result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(business_module))
        report["business_tests"] = {"run": business_result.testsRun, "failures": len(business_result.failures),
                                    "errors": len(business_result.errors), "skipped": len(business_result.skipped)}
        if not business_result.wasSuccessful() or business_result.skipped:
            raise RuntimeError("PostgreSQL business tests failed; see business-tests.log")
        spec = importlib.util.spec_from_file_location("test_postgres_identity_live", ROOT / "mvp/integration/test_postgres_identity_live.py")
        identity_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(identity_module)
        identity_module.APP_FACTORY = app_factory
        print("Running real account / session / roles / concurrent login tests", flush=True)
        with (run_root / "identity-tests.log").open("w", encoding="utf-8") as stream:
            identity_result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(identity_module))
        report["identity_tests"] = {"run": identity_result.testsRun, "failures": len(identity_result.failures), "errors": len(identity_result.errors), "skipped": len(identity_result.skipped)}
        if not identity_result.wasSuccessful() or identity_result.skipped:
            raise RuntimeError("PostgreSQL identity tests failed; see identity-tests.log")
        from postgres_api_probe import PostgresApiProbe
        api_probe = PostgresApiProbe(ROOT, run_root, make_conninfo(dbname="rkd_kernel", host="127.0.0.1", port=port,
                                                                  user="rkd_app", password=app_password))
        api_probe.initial()
        api_probe.enable_accounts()
        api_probe.stop()
        api_probe.start()
        api_probe.verify_persisted()
        api_probe.report["actual_api_process_restart"] = True

        # Rehearse migration from a consistent backup obtained through a
        # read-only connection; never upgrade or replace the user's source DB.
        snapshot = run_root / "runtime-before.sqlite3"
        source_path = ROOT / "var/app.sqlite3"
        with closing(sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
        imported = create_database("rkd_import")
        print("Importing read-only SQLite snapshot and reconciling all rows / files", flush=True)
        snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        rehearsal = SQLitePostgresImporter(imported).run(snapshot, ROOT / "var")
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == snapshot_hash
        report["checks"]["source_snapshot_unchanged"] = snapshot_hash
        (run_root / "runtime-reconciliation.json").write_text(json.dumps(rehearsal, ensure_ascii=False, indent=2), encoding="utf-8")
        report["checks"]["runtime_reconciliation"] = {"passed": True, "tables": len(rehearsal["tables"]), "rows": rehearsal["rows_verified"], "files": len(rehearsal["files"])}
        try:
            SQLitePostgresImporter(imported).run(snapshot, ROOT / "var")
        except ImportRejected:
            report["checks"]["nonempty_target_refused"] = True
        else:
            raise AssertionError("import overwrote an occupied target")

        # Identity preservation and session invalidation use an isolated source
        # fixture, because the daily runtime may not yet have account tables.
        from rkd_mvp.account_identity import AccountIdentityProvider
        from rkd_mvp.models import TenantContext
        from rkd_mvp.sqlite_store import SQLiteStore
        identity_path = run_root / "identity-source.sqlite3"
        sqlite_store = SQLiteStore(identity_path)
        sqlite_store.bootstrap_project(TenantContext("org-local", "identity-project", "tester"), "Identity migration test")
        # A real saved design/BOQ/quote/order source exercises the new JSON and
        # artifact domains, instead of importing only empty new tables.
        from rkd_mvp.api_service import ApiService
        from rkd_mvp.engine import MVPApp
        from rkd_mvp.design_rules import DEFAULT_PROGRAM
        service = ApiService(MVPApp(sqlite_store))
        service.create_requirement_draft("org-local", "identity-project", "tester", {})
        requirement = service.update_requirement("org-local", "identity-project", "tester", {"expected_revision": 1, "design_program": DEFAULT_PROGRAM, "change_reason": "migration production fixture"})["item"]
        service.save_production_settings("org-local", "identity-project", "tester", {"expected_version": 0, "expected_design_revision": 0, "settings": {"unit_cost_net": "100", "source_label": "migration test only", "material_specification": "test material", "supplier_name": "test supplier", "delivery_location": "test site"}})
        service.create_design("org-local", "identity-project", "tester", {"expected_revision": 0, "requirement_revision_no": requirement["revision_no"], "change_reason": "migration production fixture"})
        production = service.get_production("org-local", "identity-project")["item"]
        sqlite_store.close()
        provider = AccountIdentityProvider(identity_path)
        identity_password = secrets.token_urlsafe(24)
        user = provider.bootstrap("migration-test", "Migration test", identity_password)
        with closing(sqlite3.connect(identity_path)) as db:
            with db:
                db.execute("INSERT INTO auth_memberships VALUES ('org-local','identity-project',?,'viewer',?)", (user["user_id"], datetime.now(timezone.utc).isoformat()))
                db.execute("INSERT INTO auth_sessions VALUES (?,?,?,1,2,1)", (secrets.token_hex(32), user["user_id"], secrets.token_hex(16)))
                for key, value in (("null", "null"), ("text", '"unknown"'), ("number", "1.25")):
                    db.execute("INSERT INTO project_decisions VALUES ('org-local','identity-project',?,?,'test','unknown',NULL,?)",
                               (key, value, datetime.now(timezone.utc).isoformat()))
        identity_factory = create_database("rkd_identity_import")
        identity_report = SQLitePostgresImporter(identity_factory).run(identity_path, run_root)
        assert identity_report["tables"]["auth_user"]["rows"] == 1
        assert identity_report["tables"]["auth_membership"]["rows"] == 1
        assert identity_report["sessions_invalidated"] == 1
        assert identity_report["tables"]["production_revision"]["rows"] == 1
        assert identity_report["tables"]["production_artifact"]["rows"] == 8
        with identity_factory() as db:
            assert db.execute("SELECT count(*) FROM rkd.auth_session").fetchone()[0] == 0
            imported_production = db.execute("SELECT quantities, quote, procurement FROM rkd.production_revision WHERE production_revision_id=%s", (production["production_revision_id"],)).fetchone()
            assert imported_production == (production["quantities"], production["quote"], production["procurement"])
        report["checks"]["identity_rows_preserved_sessions_revoked"] = True
        report["checks"]["production_chain_import_preserved"] = {"quantity": production["quote"]["quantity"], "gross": production["quote"]["sale_gross"], "artifacts": 8}

        failed_import = create_database("rkd_import_failure")
        with failed_import() as db:
            db.execute("""CREATE FUNCTION rkd.inject_identity_failure() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'injected import failure'; END $$;
                CREATE TRIGGER test_import_failure BEFORE INSERT ON rkd.auth_audit FOR EACH ROW EXECUTE FUNCTION rkd.inject_identity_failure();""")
        try:
            SQLitePostgresImporter(failed_import).run(identity_path, run_root)
        except psycopg.Error:
            with failed_import() as db:
                assert db.execute("SELECT count(*) FROM rkd.organization").fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM rkd.auth_user").fetchone()[0] == 0
            report["checks"]["late_import_failure_full_rollback"] = True
        else:
            raise AssertionError("injected import failure did not fail")

        broken_snapshot = run_root / "broken-hash.sqlite3"
        shutil.copyfile(snapshot, broken_snapshot)
        with closing(sqlite3.connect(broken_snapshot)) as db:
            with db:
                db.execute("UPDATE file_assets SET sha256=?", ("0" * 64,))
        try:
            SQLitePostgresImporter(failed_import).run(broken_snapshot, ROOT / "var")
        except ImportRejected:
            report["checks"]["changed_file_hash_refused"] = True
        else:
            raise AssertionError("file hash mismatch was accepted")

        from postgres_recovery_probe import PostgresRecoveryProbe
        recovery_probe = PostgresRecoveryProbe(ROOT,run_root,make_conninfo(dbname="rkd_identity_import",**connection_args),
                            make_conninfo(dbname="rkd_identity_import",host="127.0.0.1",port=port,user="rkd_app",password=app_password),identity_password)
        with identity_factory() as db:
            db.execute("GRANT USAGE ON SCHEMA rkd TO rkd_app")
            db.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA rkd TO rkd_app")
            db.execute("GRANT EXECUTE ON FUNCTION rkd.list_project_summaries(),rkd.list_account_project_roles(text) TO rkd_app")
        print("Backing up and restoring complete PostgreSQL application into a new database/runtime",flush=True)
        recovery_probe.prepare()
        recovery_probe.recover()
        recovery_probe.recover_daily(make_conninfo(dbname="rkd_import",**connection_args))
        report['checks']['complete_postgres_recovery'] = recovery_probe.report
        with owner() as db:
            before_start = db.execute("SELECT pg_postmaster_start_time()").fetchone()[0]
            before_events = db.execute("SELECT count(*) FROM rkd.domain_event").fetchone()[0]
        print("Restarting the isolated PostgreSQL process and verifying persisted rows", flush=True)
        command("pg_ctl.exe", "-D", cluster, "-w", "-t", "45", "-m", "fast", "restart")
        with owner() as db:
            after_start = db.execute("SELECT pg_postmaster_start_time()").fetchone()[0]
            assert before_start != after_start
            assert before_events == db.execute("SELECT count(*) FROM rkd.domain_event").fetchone()[0]
            assert db.execute("SELECT count(*) FROM rkd.schema_migration").fetchone()[0] == 14
        with imported() as db:
            assert db.execute("SELECT count(*) FROM rkd.project").fetchone()[0] == rehearsal["tables"]["project"]["rows"]
        api_probe.verify_persisted()
        recovery_probe.verify_http()
        recovery_probe.verify_daily_http()
        recovery_probe.report["actual_database_restart"] = True
        recovery_probe.report["passed"] = True
        api_probe.report["database_restart_preserves_api_data"] = True
        report["checks"]["postgres_business_api_http_and_restarts"] = True
        report["checks"]["actual_database_restart"] = {"passed": True, "events_preserved": before_events,
                                                         "before": before_start.isoformat(), "after": after_start.isoformat()}
        report["passed"] = True
    except BaseException as error:
        report["passed"] = False
        report["failure_type"] = type(error).__name__
        raise
    finally:
        if recovery_probe:
            recovery_probe.finish()
        if api_probe:
            api_probe.finish()
        if password_file.exists():
            password_file.unlink()
        if running or (cluster / "postmaster.pid").exists():
            try:
                command("pg_ctl.exe", "-D", cluster, "-w", "-t", "45", "-m", "fast", "stop")
            except (RuntimeError, subprocess.TimeoutExpired) as cleanup_error:
                report["cleanup_error"] = type(cleanup_error).__name__
                report["passed"] = False
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (run_root / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report.get("passed"), "tests": report.get("tests"), "checks": report["checks"],
                          "evidence": str(run_root)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
