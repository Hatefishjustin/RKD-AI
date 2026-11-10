"""Complete PostgreSQL recovery to an empty database and a new runtime only.

The trusted maintenance connection must see every RLS row. pg_dump and row
reconciliation share one exported read snapshot; application credentials and
machine paths are never embedded in the portable archive.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time
import uuid
import zipfile

from .local_backup import BackupRejected, _json, _name, _sha, application_files


FORMAT = "rkd-postgres-backup.v1"


def _loopback(dsn):
    from psycopg.conninfo import conninfo_to_dict
    info = conninfo_to_dict(dsn)
    if info.get("host") not in {"127.0.0.1", "localhost"}:
        raise BackupRejected("recovery pilot requires explicit loopback PostgreSQL host")
    return info


def _maintenance(db):
    # row_security=off causes an error if a non-owner would filter any table.
    db.execute("SET row_security=off")
    db.execute("SET TIME ZONE 'UTC'")
    role = db.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
    invisible = db.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rkd' AND c.relkind='r' AND c.relrowsecurity AND NOT pg_has_role(current_user,c.relowner,'USAGE')").fetchone()[0]
    if invisible and not any(role):
        raise BackupRejected("complete backup requires an explicit maintenance role with all-row visibility")


def _inventory(db):
    from psycopg import sql
    tables, files = {}, {}
    names = [row[0] for row in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='rkd' ORDER BY tablename")]
    if "schema_migration" not in names:
        raise BackupRejected("missing PostgreSQL application schema")
    for name in names:
        records = [row[0] for row in db.execute(sql.SQL("SELECT to_jsonb(t)::text FROM rkd.{} t").format(sql.Identifier(name)))]
        tables[name] = {"rows": len(records), "sha256": _sha("\n".join(sorted(records)).encode("utf-8"))}
        columns = {row[0] for row in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='rkd' AND table_name=%s", (name,))}
        location = "storage_key" if "storage_key" in columns else "relative_path" if "relative_path" in columns else None
        if location:
            if not {"sha256", "size_bytes"} <= columns:
                raise BackupRejected("unmapped PostgreSQL file metadata")
            for encoded in records:
                row = json.loads(encoded)
                path = _name(row[location].replace("\\", "/"))
                info = {"sha256": row["sha256"], "size_bytes": row["size_bytes"]}
                if path in files and files[path] != info:
                    raise BackupRejected("conflicting PostgreSQL file references")
                files[path] = info
    return tables, files


def _client(binary, dsn, arguments):
    info = _loopback(dsn)
    # No connection string or password in argv, errors or the archive.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    for source, target in {"host":"PGHOST", "port":"PGPORT", "user":"PGUSER", "password":"PGPASSWORD", "dbname":"PGDATABASE"}.items():
        if source in info:
            env[target] = info[source]
    env["PGCONNECT_TIMEOUT"] = "10"
    result = subprocess.run([str(binary), *map(str, arguments)], env=env, capture_output=True, timeout=180)
    if result.returncode:
        # Preserve diagnostics without ever echoing credentials from the client.
        raise BackupRejected(f"{Path(binary).stem} failed (exit {result.returncode}); target retained for inspection")


def create_postgres_backup(dsn, runtime_root, output, application_root, binary_directory, *, baseline_files=None):
    from .postgres_store import postgres_connection_factory
    _loopback(dsn)
    started = time.monotonic()
    root, output, app = Path(runtime_root).resolve(), Path(output).resolve(), Path(application_root).resolve()
    if not root.is_dir() or output.exists():
        raise BackupRejected("runtime missing or backup destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.parent / (output.name + ".incomplete-" + uuid.uuid4().hex[:12])
    stage.mkdir()
    entries = {}
    manifest = {"schema_version": FORMAT, "snapshot_at": None, "database": "database/rkd.dump",
                "restore_auth_policy": "invalidate_all_sessions", "files": entries,
                "config": {"database_engine": "postgresql", "binding": "127.0.0.1", "external_effects_enabled": False,
                           "required_application_role": "non_owner_non_superuser_no_bypassrls",
                           "required_environment": ["RKD_POSTGRES_DSN", "RKD_POSTGRES_RUNTIME"]}}
    factory = postgres_connection_factory(dsn, application_role=False)
    with closing(factory()) as db:
        _maintenance(db)
        db.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = db.execute("SELECT pg_export_snapshot(),clock_timestamp(),version()").fetchone()
        manifest["snapshot_at"], manifest["postgres_version"] = snapshot[1].isoformat(), snapshot[2]
        tables, runtime_files = _inventory(db)
        manifest["tables"] = tables
        dump = stage / "rkd.dump"
        _client(Path(binary_directory) / ("pg_dump.exe" if os.name == "nt" else "pg_dump"), dsn, ["--no-password", "--format=custom", "--no-owner", "--no-privileges", "--schema=rkd", "--snapshot=" + snapshot[0], "--file", dump])
        with zipfile.ZipFile(stage / "backup.zip", "x", zipfile.ZIP_DEFLATED) as archive:
            def add(name, path, boundary, expected=None):
                name, resolved = _name(name), Path(path).resolve()
                if not resolved.is_relative_to(boundary) or not resolved.is_file():
                    raise BackupRejected("missing or unsafe backup file: " + name)
                data = resolved.read_bytes()
                info = {"sha256": _sha(data), "size_bytes": len(data)}
                if expected is not None and info != expected:
                    raise BackupRejected("backup file hash/size mismatch: " + name)
                if name.casefold() in {key.casefold() for key in entries}:
                    raise BackupRejected("duplicate archive member")
                archive.writestr(name, data)
                entries[name] = info
            add("database/rkd.dump", dump, stage)
            for name, expected in sorted(runtime_files.items()):
                add("runtime/" + name, root / name, root, expected)
            names = application_files(app) if baseline_files is None else list(baseline_files)
            for name in names:
                name = _name(name)
                add("application/" + name, app / name, app)
            manifest["runtime_files"], manifest["application_files"] = len(runtime_files), len(names)
            manifest["duration_seconds"] = round(time.monotonic() - started, 3)
            archive.writestr("manifest.json", _json(manifest).encode("utf-8"))
        db.rollback()
    # Atomic no-overwrite publication. Failed attempts retain diagnostic staging.
    os.link(stage / "backup.zip", output)
    (stage / "backup.zip").unlink()
    dump.unlink()
    stage.rmdir()
    return {"archive": str(output), "sha256": _sha(output.read_bytes()), **manifest}


def _extract(archive_path, stage):
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [_name(item.filename) for item in infos]
        if len(set(name.casefold() for name in names)) != len(names) or any(stat.S_ISLNK(item.external_attr >> 16) for item in infos):
            raise BackupRejected("duplicate or linked archive member")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema_version") != FORMAT or manifest.get("database") != "database/rkd.dump":
            raise BackupRejected("unsupported PostgreSQL archive")
        expected = manifest["files"]
        if set(names) != {"manifest.json", *expected} or any(not name.startswith(("database/", "runtime/", "application/")) for name in expected):
            raise BackupRejected("archive inventory mismatch")
        stage.mkdir(parents=True)
        for item in infos:
            if item.filename == "manifest.json":
                continue
            info = expected[item.filename]
            if item.file_size != info["size_bytes"]:
                raise BackupRejected("archive size mismatch")
            path = stage / item.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            size, digest = 0, hashlib.sha256()
            with archive.open(item) as source, path.open("xb") as target:
                while block := source.read(1024 * 1024):
                    target.write(block)
                    digest.update(block)
                    size += len(block)
            if size != info["size_bytes"] or digest.hexdigest() != info["sha256"]:
                raise BackupRejected("archive hash mismatch")
    return manifest


def restore_postgres_backup(archive_path, dsn, destination, binary_directory, *, application_role=None):
    from psycopg import sql
    from .postgres_store import postgres_connection_factory
    _loopback(dsn)
    started = time.monotonic()
    destination = Path(destination).resolve()
    if destination.exists():
        raise BackupRejected("restore directory must be new")
    stage = destination.parent / (destination.name + ".incomplete-" + uuid.uuid4().hex[:12])
    # Every archived byte is verified before touching the target database.
    manifest = _extract(archive_path, stage)
    factory = postgres_connection_factory(dsn, application_role=False)
    with closing(factory()) as db:
        _maintenance(db)
        name = db.execute("SELECT current_database()").fetchone()[0]
        if name in {"postgres", "template0", "template1"}:
            raise BackupRejected("restore requires an explicitly selected new application database")
        if db.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='rkd') OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','f'))").fetchone()[0]:
            raise BackupRejected("restore target database is not empty")
        if application_role:
            role = db.execute("SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname=%s", (application_role,)).fetchone()
            owns_database = db.execute("SELECT pg_has_role(%s,datdba,'USAGE') FROM pg_database WHERE datname=current_database()", (application_role,)).fetchone()[0]
            if not role or any(role) or owns_database:
                raise BackupRejected("application role must not own or administer the restored database")
        # Hold a database-scoped advisory lock while restoring and checking;
        # cooperating restore commands cannot race an empty-target check.
        if not db.execute("SELECT pg_try_advisory_lock(7241150301)").fetchone()[0]:
            raise BackupRejected("another recovery is running")
        # Recheck after acquiring the lock, before the external client starts.
        if db.execute("SELECT to_regnamespace('rkd') IS NOT NULL").fetchone()[0]:
            raise BackupRejected("restore target changed")
        _client(Path(binary_directory) / ("pg_restore.exe" if os.name == "nt" else "pg_restore"), dsn, ["--no-password", "--dbname=" + name, "--single-transaction", "--exit-on-error", "--no-owner", "--no-privileges", stage / "database/rkd.dump"])
        db.execute("BEGIN")
        tables, files = _inventory(db)
        if tables != manifest["tables"]:
            raise BackupRejected("restored PostgreSQL rows differ from snapshot")
        for name, info in files.items():
            if manifest["files"].get("runtime/" + name) != info:
                raise BackupRejected("restored file references differ from snapshot")
        sessions = db.execute("SELECT count(*) FROM rkd.auth_session").fetchone()[0]
        db.execute("DELETE FROM rkd.auth_session")
        db.execute("DELETE FROM rkd.auth_login_throttle")
        db.execute("DELETE FROM rkd.auth_login_limit")
        uploads = db.execute("UPDATE rkd.file_upload SET status='failed' WHERE status<>'completed'").rowcount
        # pg_restore --no-privileges removes source ACLs; explicitly protect all
        # SECURITY DEFINER functions before granting a narrow application role.
        functions = db.execute("SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='rkd' AND p.prosecdef").fetchall()
        for (function,) in functions:
            db.execute(sql.SQL("REVOKE ALL ON FUNCTION {} FROM PUBLIC").format(sql.SQL(function)))
        if application_role:
            role = sql.Identifier(application_role)
            db.execute(sql.SQL("GRANT USAGE ON SCHEMA rkd TO {}").format(role))
            for name in tables:
                if name != "schema_migration":
                    db.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON rkd.{} TO {}").format(sql.Identifier(name), role))
            db.execute(sql.SQL("GRANT EXECUTE ON FUNCTION rkd.list_project_summaries(),rkd.list_account_project_roles(text) TO {}").format(role))
        orgs = db.execute("SELECT DISTINCT organization_id FROM rkd.auth_user").fetchall()
        for (org,) in orgs:
            db.execute("INSERT INTO rkd.auth_audit(audit_id,actor_id,organization_id,action,target_id,details) VALUES (%s,'local-recovery',%s,'backup.restored','postgres-runtime',%s::jsonb)",
                       ("recovery-" + uuid.uuid4().hex, org, json.dumps({"snapshot_at":manifest['snapshot_at'], "sessions_invalidated":sessions})))
        db.commit()
    report = {"schema_version":"rkd-postgres-restore.v1", "snapshot_at":manifest['snapshot_at'],
              "restored_at":datetime.now(timezone.utc).isoformat(), "duration_seconds":round(time.monotonic()-started,3),
              "tables_verified":len(tables), "runtime_files_verified":len(files), "application_files_verified":manifest['application_files'],
              "sessions_invalidated":sessions, "uploads_require_reupload":uploads, "existing_runtime_replaced":False,
              "application_role_granted":application_role, "runtime":str(destination / 'runtime')}
    (stage / "restore-report.json").write_text(_json(report),encoding="utf-8")
    if destination.exists():
        raise BackupRejected("restore directory changed")
    stage.rename(destination)
    return report
