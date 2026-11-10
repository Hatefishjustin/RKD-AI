"""Complete, verified local snapshots. Restore only to a new isolated directory.

The archive preserves a consistent SQLite image, every referenced runtime file,
and an executable application baseline. No running database is ever replaced.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import subprocess
import time
import uuid
import zipfile


class BackupRejected(RuntimeError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _name(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise BackupRejected("unsafe archive path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise BackupRejected("unsafe archive path")
    if any(part.endswith((" ", ".")) or part.split(".")[0].upper() in
           {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
           for part in path.parts):
        raise BackupRejected("unsafe Windows archive path")
    return path.as_posix()


def _tables(db):
    return [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _inventory(db):
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
        raise BackupRejected("database integrity check failed")
    tables, files = {}, {}
    for table in _tables(db):
        rows = [dict(row) for row in db.execute(f"SELECT * FROM {_identifier(table)}")]
        encoded = sorted(json.dumps(row, sort_keys=True, ensure_ascii=True) for row in rows)
        tables[table] = {"rows": len(rows), "sha256": _sha("\n".join(encoded).encode())}
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({_identifier(table)})")}
        location = "storage_key" if "storage_key" in columns else "relative_path" if "relative_path" in columns else None
        if location:
            if not {"sha256", "size_bytes"} <= columns:
                raise BackupRejected(f"unmapped file metadata: {table}")
            for row in rows:
                path = _name(str(row[location]).replace("\\", "/"))
                info = {"sha256": row["sha256"], "size_bytes": row["size_bytes"]}
                if path in files and files[path] != info:
                    raise BackupRejected("conflicting file references")
                files[path] = info
    return tables, files


def application_files(root):
    """Use Git's ignore rules; include uncommitted code and bundled seed inputs."""
    root = Path(root).resolve()
    roots = {"mvp", "scripts", "web", "contracts", "fixtures", "docs"}
    root_files = {"requirements.lock", ".gitignore", "AGENTS.md", "PROJECT_STATUS.md", "新对话交接文件.md"}
    if (root / ".git").exists():
        result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                cwd=root, capture_output=True, check=True)
        candidates = {item.decode("utf-8") for item in result.stdout.split(b"\0") if item}
    else:
        # A restored application baseline deliberately has no .git directory.
        # It must still be possible to back up the recovered installation.
        candidates = {path.relative_to(root).as_posix() for folder in roots for path in (root / folder).rglob("*") if path.is_file()}
        candidates.update(name for name in root_files if (root / name).is_file())
    candidates.update(path.relative_to(root).as_posix() for path in (root / "web/dist").rglob("*") if path.is_file())
    return sorted(name for name in candidates if (PurePosixPath(name).parts[0] in roots or name in root_files)
                  and not {"node_modules", "__pycache__", ".venv"}.intersection(PurePosixPath(name).parts)
                  and not PurePosixPath(name).name.startswith(".env") and not name.endswith((".pyc", ".tsbuildinfo")))


def create_backup(database, output, application_root, *, baseline_files=None):
    started = time.monotonic()
    database, output, app_root = Path(database).resolve(), Path(output).resolve(), Path(application_root).resolve()
    if not database.is_file() or output.exists():
        raise BackupRejected("database missing or backup destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / (output.name + ".incomplete-" + uuid.uuid4().hex[:12])
    staging.mkdir()
    snapshot = staging / "app.sqlite3"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
        source.execute("BEGIN")
        # Pin a read snapshot before copying. SQLite backup includes committed data only.
        source.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        snapshot_at = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
    entries = {}
    manifest = {"schema_version": "rkd-local-backup.v1", "snapshot_at": snapshot_at,
                "database": "runtime/app.sqlite3", "restore_auth_policy": "invalidate_all_sessions",
                "config": {"binding": "127.0.0.1", "database_engine": "sqlite", "external_effects_enabled": False},
                "files": entries}
    archive_path = staging / "backup.zip"
    with closing(sqlite3.connect(snapshot)) as db, zipfile.ZipFile(archive_path, "x", zipfile.ZIP_DEFLATED) as archive:
        db.row_factory = sqlite3.Row
        tables, runtime_files = _inventory(db)
        manifest["tables"] = tables

        def add(name, path, expected=None, boundary=None):
            name = _name(name)
            resolved = path.resolve()
            if not resolved.is_relative_to(boundary) or not resolved.is_file():
                raise BackupRejected(f"missing or unsafe file: {name}")
            data = resolved.read_bytes()
            actual = {"size_bytes": len(data), "sha256": _sha(data)}
            if expected is not None and actual != expected:
                raise BackupRejected(f"file hash/size mismatch: {name}")
            if name.casefold() in {item.casefold() for item in entries}:
                raise BackupRejected("duplicate archive path")
            archive.writestr(name, data)
            entries[name] = actual

        add("runtime/app.sqlite3", snapshot, boundary=staging)
        for name, expected in sorted(runtime_files.items()):
            add("runtime/" + name, database.parent / name, expected, database.parent)
        names = application_files(app_root) if baseline_files is None else baseline_files
        for name in names:
            name = _name(name)
            add("application/" + name, app_root / name, boundary=app_root)
        manifest["runtime_files"] = len(runtime_files)
        manifest["application_files"] = len(names)
        manifest["duration_seconds"] = round(time.monotonic() - started, 3)
        archive.writestr("manifest.json", _json(manifest).encode("utf-8"))
    if output.exists():
        raise BackupRejected("backup destination already exists")
    # On the supported Windows filesystem rename refuses an existing target.
    os.link(archive_path, output)
    archive_path.unlink()
    snapshot.unlink()
    staging.rmdir()
    return {"archive": str(output), "sha256": _sha(output.read_bytes()), **manifest}


def restore_backup(archive_path, destination):
    started = time.monotonic()
    destination = Path(destination).resolve()
    if destination.exists():
        raise BackupRejected("restore destination must be a new directory")
    staging = destination.parent / (destination.name + ".incomplete-" + uuid.uuid4().hex[:12])
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [_name(item.filename) for item in infos]
        if len({name.casefold() for name in names}) != len(names) or any(stat.S_ISLNK(item.external_attr >> 16) for item in infos):
            raise BackupRejected("duplicate or linked archive member")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema_version") != "rkd-local-backup.v1" or manifest.get("database") != "runtime/app.sqlite3":
            raise BackupRejected("unsupported backup format")
        expected_files = manifest["files"]
        if set(names) != {"manifest.json", *expected_files}:
            raise BackupRejected("archive inventory mismatch")
        if any(not name.startswith(("runtime/", "application/")) for name in expected_files):
            raise BackupRejected("unexpected archive root")
        staging.mkdir(parents=True)
        for item in infos:
            if item.filename == "manifest.json":
                continue
            expected = expected_files[item.filename]
            if item.file_size != expected["size_bytes"]:
                raise BackupRejected("archive size mismatch")
            target = staging / item.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("xb") as output:
                digest, size = hashlib.sha256(), 0
                while block := source.read(1024 * 1024):
                    digest.update(block)
                    size += len(block)
                    output.write(block)
            if size != expected["size_bytes"] or digest.hexdigest() != expected["sha256"]:
                raise BackupRejected("archive content hash mismatch")
    database = staging / "runtime/app.sqlite3"
    with closing(sqlite3.connect(database)) as db, db:
        db.row_factory = sqlite3.Row
        tables, runtime_files = _inventory(db)
        if tables != manifest["tables"]:
            raise BackupRejected("database row reconciliation failed")
        for path, expected in runtime_files.items():
            if expected_files.get("runtime/" + path) != expected:
                raise BackupRejected("database file reference mismatch")
        sessions = db.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] if "auth_sessions" in tables else 0
        for table in ("auth_sessions", "auth_login_limits"):
            if table in tables:
                db.execute(f"DELETE FROM {table}")
        # Incomplete upload streams are not persisted assets. Require re-upload.
        if "file_uploads" in tables:
            db.execute("UPDATE file_uploads SET status='failed' WHERE status != 'completed'")
        if "auth_audit" in tables:
            for row in db.execute("SELECT DISTINCT organization_id FROM auth_users").fetchall():
                db.execute("INSERT INTO auth_audit VALUES (?, ?, ?, NULL, ?, ?, ?, ?)",
                           ("recovery_" + uuid.uuid4().hex, "local-recovery", row[0], "backup.restored", "local-runtime",
                            _json({"snapshot_at": manifest["snapshot_at"], "sessions_invalidated": sessions}),
                            datetime.now(timezone.utc).isoformat()))
    report = {"schema_version": "rkd-local-restore.v1", "snapshot_at": manifest["snapshot_at"],
              "restored_at": datetime.now(timezone.utc).isoformat(), "duration_seconds": round(time.monotonic() - started, 3),
              "database": str(destination / "runtime/app.sqlite3"), "tables_verified": len(tables),
              "runtime_files_verified": len(runtime_files), "application_files_verified": manifest["application_files"],
              "sessions_invalidated": sessions, "incomplete_uploads": "require_reupload", "runtime_replaced": False}
    (staging / "restore-report.json").write_text(_json(report), encoding="utf-8")
    if destination.exists():
        raise BackupRejected("restore destination already exists")
    staging.rename(destination)
    return report
