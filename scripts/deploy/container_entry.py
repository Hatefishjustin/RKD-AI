"""Trusted deployment commands. Never prints credentials or creates user passwords."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT))


def connection(role):
    from psycopg.conninfo import make_conninfo
    password = Path("/run/secrets/" + ("owner_password" if role == "rkd_owner" else "app_password")).read_text().strip()
    return make_conninfo(host="127.0.0.1", port=int(os.environ.get("RKD_POSTGRES_PORT", "15432")),
                         dbname="rkd_team", user=role, password=password)


def initialize(source=None, runtime=None, owner_dsn=None, app_password=None):
    import hashlib
    from psycopg import sql
    from rkd_mvp.local_backup import _inventory
    from rkd_mvp.postgres_import import SQLitePostgresImporter
    from rkd_mvp.postgres_migrations import PostgresMigrationRunner
    from rkd_mvp.postgres_store import postgres_connection_factory
    source = Path(source or "/rkd/import/runtime").resolve()
    runtime = Path(runtime or os.environ["RKD_POSTGRES_RUNTIME"]).resolve()
    factory = postgres_connection_factory(owner_dsn or connection("rkd_owner"), application_role=False)
    # Refuse to adopt or overwrite any pre-existing database or runtime.
    with closing(factory()) as db:
        if db.execute("SELECT to_regnamespace('rkd') IS NOT NULL").fetchone()[0]:
            raise RuntimeError("database already initialized; import refused")
    runtime.mkdir(parents=True, exist_ok=True)
    if any(runtime.iterdir()):
        raise RuntimeError("runtime is not empty; import refused")
    with closing(sqlite3.connect((source / "app.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        _, files = _inventory(db)
    for name, expected in files.items():
        original = (source / name).resolve()
        if not original.is_relative_to(source) or not original.is_file() or original.is_symlink():
            raise RuntimeError("unsafe or missing source file")
        if original.stat().st_size != expected['size_bytes'] or hashlib.sha256(original.read_bytes()).hexdigest() != expected['sha256']:
            raise RuntimeError("source file verification failed")
    PostgresMigrationRunner(factory).apply()
    report = SQLitePostgresImporter(factory).run(source / "app.sqlite3", source)
    # All referenced bytes passed the importer's own recheck before copying.
    for name in files:
        destination = runtime / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != files[name]['sha256']:
            raise RuntimeError("copied file verification failed; candidate remains unpublished")
    if app_password is None:
        app_password = Path("/run/secrets/app_password").read_text().strip()
    with closing(factory()) as db:
        # A fresh, distinct application role owns no database/schema/table.
        if db.execute("SELECT 1 FROM pg_roles WHERE rolname='rkd_app'").fetchone():
            raise RuntimeError("application role already exists; refusing to adopt it")
        db.execute(sql.SQL("CREATE ROLE rkd_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}").format(sql.Literal(app_password)))
        db.execute("GRANT USAGE ON SCHEMA rkd TO rkd_app")
        names = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='rkd' AND tablename<>'schema_migration'").fetchall()
        for (name,) in names:
            db.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON rkd.{} TO rkd_app").format(sql.Identifier(name)))
        db.execute("GRANT EXECUTE ON FUNCTION rkd.list_project_summaries(),rkd.list_account_project_roles(text) TO rkd_app")
        db.commit()
    (runtime / "deployment-import.json").write_text(json.dumps({**report,"copied_files":len(files),"authoritative_cutover":False},indent=2),encoding="utf-8")
    if getattr(os, "geteuid", lambda: -1)() == 0:
        for directory, folders, names in os.walk(runtime):
            os.chown(directory,10001,10001)
            os.chmod(directory,0o700)
            for name in names:
                os.chown(Path(directory)/name,10001,10001)
                os.chmod(Path(directory)/name,0o600)
    print(json.dumps({"initialized":True,"files_verified":len(files),"tables_imported":len(report['tables']),"authoritative_cutover":False}))


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if command == "initialize":
        initialize()
        return
    os.environ["RKD_POSTGRES_DSN"] = connection("rkd_app")
    if command == "accounts":
        from scripts.manage_accounts import main as accounts
        sys.argv = ["manage_accounts.py", "--postgres"]
        accounts()
    elif command == "serve":
        import runpy
        runpy.run_path(str(ROOT / "mvp/run_team_api.py"), run_name="__main__")
    else:
        raise RuntimeError("unknown deployment command")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Exception/driver messages can contain secrets. Inspect via a trusted
        # terminal locally; never put them in Docker's shared log stream.
        raise SystemExit("deployment failed: " + type(error).__name__) from None
