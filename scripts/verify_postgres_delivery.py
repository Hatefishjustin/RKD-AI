"""Real PostgreSQL integration evidence for the 014 professional-delivery tables.

Provisions an isolated, loopback-only PG cluster (never a Windows service),
builds an isolated SQLite snapshot that actually contains source-extraction,
technical-delivery and artifact rows plus their bytes, imports it into a fresh
PG database, and verifies jsonb round-trips, RLS tenant isolation, the
PostgreSQL repository branch, and per-file SHA-256/size reconciliation.

No daily SQLite database, NAS, or existing evidence is modified.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from rkd_mvp.models import TenantContext, now_iso  # noqa: E402
from rkd_mvp.postgres_import import SQLitePostgresImporter  # noqa: E402
from rkd_mvp.postgres_migrations import PostgresMigrationRunner  # noqa: E402
from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory  # noqa: E402
from rkd_mvp.professional_delivery import PostgresAIProfessionalDeliveryRepository  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402

ORG = "org-delivery-live"
PROJECT = "project-delivery-live"
STAMP = "2026-11-09"


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def command(run_root: Path, binary: Path, *args) -> None:
    with (run_root / "lifecycle.log").open("a", encoding="utf-8") as log:
        result = subprocess.run([str(binary / args[0]), *map(str, args[1:])], cwd=ROOT,
                                stdout=log, stderr=subprocess.STDOUT, timeout=90)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed; see lifecycle.log")


def build_snapshot(runtime_root: Path) -> dict:
    """Create a real schema-24 SQLite snapshot with delivery rows and bytes."""
    database = runtime_root / "app.sqlite3"
    store = SQLiteStore(database)
    store.close()
    created = now_iso()
    file_bytes = b"\n".join([b"RKD AI source note", b"line 2: entrance on the left", b"line 3: warm wood intent"])
    file_sha = hashlib.sha256(file_bytes).hexdigest()
    artifact_dir = runtime_root / "projects" / "ai-technical-delivery" / "delivery-live"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for index, (kind, filename) in enumerate((
            ("technical_plan_svg", "technical-plan.svg"),
            ("material_schedule_csv", "material-schedule.csv"),
            ("handover_json", "handover.json"))):
        data = f"<rkd kind='{kind}' object='dev:zone-1'/>\n".encode("utf-8")
        (artifact_dir / filename).write_bytes(data)
        artifacts.append({
            "artifact_id": f"artifact-live-{index}", "delivery_id": "delivery-live-1",
            "organization_id": ORG, "project_id": PROJECT, "artifact_kind": kind,
            "filename": filename, "content_type": "text/plain",
            "relative_path": (artifact_dir / filename).relative_to(runtime_root).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "created_at": created,
        })
    raw_file = runtime_root / "projects" / "raw" / "file-live-1"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_bytes(file_bytes)
    record = {
        "schema_version": "rkd-ai-source-extraction.v1", "extraction_id": "extraction-live-1",
        "file_id": "file-live-1", "filename": "source-note.txt", "file_sha256": file_sha,
        "size_bytes": len(file_bytes), "extractor_kind": "plain_text",
        "extractor_version": "rkd-source-content.v1", "status": "extracted", "status_reason": None,
        "segment_count": 2, "segments": [
            {"segment_id": "seg-001", "locator": "line:1-2", "text": "RKD AI source note\nline 2: entrance on the left",
             "char_start": 0, "char_end": 48},
            {"segment_id": "seg-002", "locator": "line:3-3", "text": "line 3: warm wood intent",
             "char_start": 49, "char_end": 73},
        ], "text_sha256": hashlib.sha256("RKD AI source note\nline 2: entrance on the left\nline 3: warm wood intent".encode()).hexdigest(),
        "warnings": [], "truncated": False,
        "content_policy": "local_only_not_sent_to_model_without_explicit_approval",
        "created_at": created,
    }
    handover = {
        "schema_version": "rkd-ai-technical-handover.v1", "delivery_id": "delivery-live-1",
        "production_revision_id": "revision-live-1", "option_revision_id": "option-live-1",
        "adoption_version": 1, "input_hash": "a" * 64,
        "supported_scope": [{"statement": "功能分区净地坪面积", "status": "supported"}],
        "unsupported_scope": [{"statement": "材料规格", "known_status": "unknown", "value": None}],
        "review_tasks": [{"role": "材料/室内专业", "status": "pending"}],
        "object_ids": ["dev:zone-1"], "status": {"publication_status": "not_approved"},
    }
    with closing(sqlite3.connect(database)) as db:
        db.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (ORG, PROJECT, "交付联调项目", "active", 1))
        db.execute(
            "INSERT INTO file_assets(file_id,organization_id,project_id,filename,kind,content_type,size_bytes,"
            "sha256,storage_key,source_kind,source_ref,format_status,created_at,revision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("file-live-1", ORG, PROJECT, "source-note.txt", "local_upload", "text/plain", len(file_bytes),
             file_sha, raw_file.relative_to(runtime_root).as_posix(), "local_upload", "live",
             "signature_checked", created, 1))
        db.execute(
            "INSERT INTO ai_source_extractions(extraction_id,organization_id,project_id,file_id,file_sha256,"
            "filename,size_bytes,extractor_kind,extractor_version,status,status_reason,segment_count,"
            "text_sha256,record_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("extraction-live-1", ORG, PROJECT, "file-live-1", file_sha, "source-note.txt",
             len(file_bytes), "plain_text", "rkd-source-content.v1", "extracted", None, 2,
             record["text_sha256"], _json(record), created))
        db.execute(
            "INSERT INTO ai_technical_deliveries(delivery_id,organization_id,project_id,production_revision_id,"
            "option_revision_id,adoption_version,input_hash,status,handover_json,source_extraction_ids_json,"
            "idempotency_key,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("delivery-live-1", ORG, PROJECT, "revision-live-1", "option-live-1", 1, "a" * 64,
             "draft", _json(handover), _json(["extraction-live-1"]), "delivery-live-key", "live", created))
        for artifact in artifacts:
            db.execute(
                "INSERT INTO ai_technical_artifacts(artifact_id,delivery_id,organization_id,project_id,"
                "artifact_kind,filename,content_type,relative_path,sha256,size_bytes,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (artifact["artifact_id"], artifact["delivery_id"], ORG, PROJECT, artifact["artifact_kind"],
                 artifact["filename"], artifact["content_type"], artifact["relative_path"],
                 artifact["sha256"], artifact["size_bytes"], created))
        db.commit()
    return {"database": database, "record": record, "handover": handover, "artifacts": artifacts}


def main() -> int:
    started = time.monotonic()
    run_root = ROOT / "var" / "evidence" / "postgres-delivery" / STAMP / (
        "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3))
    run_root.mkdir(parents=True)
    binary = ROOT / "var/tools/postgresql-17.11-5/pgsql/bin"
    cluster = run_root / "cluster"
    runtime_root = run_root / "runtime"
    runtime_root.mkdir()
    password_file = run_root / "init-password"
    owner_password = secrets.token_urlsafe(32)
    app_password = secrets.token_urlsafe(32)
    password_file.write_text(owner_password, encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    args = dict(host="127.0.0.1", port=port, user="rkd_migration", password=owner_password)
    owner_dsn = make_conninfo(dbname="postgres", **args)
    checks: dict = {}
    running = False
    snapshot = build_snapshot(runtime_root)
    try:
        command(run_root, binary, "initdb.exe", "-D", cluster, "-U", "rkd_migration",
                "--pwfile", password_file, "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C")
        password_file.unlink()
        command(run_root, binary, "pg_ctl.exe", "-D", cluster, "-l", run_root / "postgres.log",
                "-w", "-t", "45", "-o", f"-h 127.0.0.1 -p {port}", "start")
        running = True
        db_name = "rkd_delivery_live"
        with psycopg.connect(owner_dsn, autocommit=True) as db:
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
        owner = postgres_connection_factory(make_conninfo(dbname=db_name, **args), application_role=False)
        applied = PostgresMigrationRunner(owner).apply()
        checks["migrations_applied"] = list(applied)
        assert applied == tuple(range(1, 15)), applied
        with owner() as db:
            db.execute(sql.SQL("CREATE ROLE rkd_delivery_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}")
                       .format(sql.Literal(app_password)))
            db.execute("GRANT USAGE ON SCHEMA rkd TO rkd_delivery_app")
            tables = [row[0] for row in db.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='rkd' AND tablename<>'schema_migration'").fetchall()]
            for table in tables:
                db.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON rkd.{} TO rkd_delivery_app")
                           .format(sql.Identifier(table)))
            db.commit()
        app_factory = postgres_connection_factory(
            make_conninfo(dbname=db_name, host="127.0.0.1", port=port,
                          user="rkd_delivery_app", password=app_password), application_role=False)

        report = SQLitePostgresImporter(owner).run(snapshot["database"], runtime_root)
        checks["import"] = {
            "source_schema_version": report["source_schema_version"],
            "ai_source_extraction_rows": report["tables"]["ai_source_extraction"]["rows"],
            "ai_technical_delivery_rows": report["tables"]["ai_technical_delivery"]["rows"],
            "ai_technical_artifact_rows": report["tables"]["ai_technical_artifact"]["rows"],
            "files_verified": len(report["files"]), "rows_verified": report["rows_verified"],
            "mode": report["mode"],
        }
        assert report["source_schema_version"] == 24
        assert report["tables"]["ai_source_extraction"]["rows"] == 1
        assert report["tables"]["ai_technical_delivery"]["rows"] == 1
        assert report["tables"]["ai_technical_artifact"]["rows"] == 3

        with owner() as db:
            record = db.execute("SELECT record FROM rkd.ai_source_extraction").fetchone()[0]
            handover = db.execute("SELECT handover FROM rkd.ai_technical_delivery").fetchone()[0]
            extraction_ids = db.execute("SELECT source_extraction_ids FROM rkd.ai_technical_delivery").fetchone()[0]
            status = db.execute("SELECT record->>'status' FROM rkd.ai_source_extraction").fetchone()[0]
            policies = [row[0] for row in db.execute(
                "SELECT polname FROM pg_policy WHERE polrelid IN "
                "('rkd.ai_source_extraction'::regclass,'rkd.ai_technical_delivery'::regclass,"
                "'rkd.ai_technical_artifact'::regclass) ORDER BY polname").fetchall()]
            rls = db.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='rkd' AND c.relname IN "
                "('ai_source_extraction','ai_technical_delivery','ai_technical_artifact') AND c.relrowsecurity").fetchone()[0]
        assert isinstance(record, dict) and record == snapshot["record"], "jsonb record round-trip failed"
        assert isinstance(handover, dict) and handover == snapshot["handover"], "jsonb handover round-trip failed"
        assert extraction_ids == ["extraction-live-1"]
        assert status == "extracted"
        assert rls == 3 and len(policies) == 3, (rls, policies)
        checks["jsonb_round_trip"] = {"record_is_dict": True, "handover_is_dict": True,
                                      "status_from_jsonb": status, "rls_tables": rls, "policies": policies}

        for artifact in snapshot["artifacts"]:
            data = (runtime_root / artifact["relative_path"]).read_bytes()
            assert len(data) == artifact["size_bytes"]
            assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
        checks["artifact_bytes_verified"] = len(snapshot["artifacts"])

        # RLS: the narrow application role sees only its own tenant scope.
        with app_factory() as db:
            db.execute("BEGIN")
            db.execute("SELECT set_config('rkd.organization_id',%s,true),set_config('rkd.project_id',%s,true)",
                       (ORG, PROJECT))
            same = db.execute("SELECT count(*) FROM rkd.ai_source_extraction").fetchone()[0]
            seen = db.execute("SELECT record->>'status' FROM rkd.ai_source_extraction").fetchone()[0]
            db.rollback()
            db.execute("BEGIN")
            db.execute("SELECT set_config('rkd.organization_id',%s,true),set_config('rkd.project_id',%s,true)",
                       (ORG, "project-other"))
            other = db.execute("SELECT count(*) FROM rkd.ai_source_extraction").fetchone()[0]
            db.rollback()
        assert same == 1 and seen == "extracted" and other == 0, (same, seen, other)
        checks["rls_tenant_isolation"] = {"own_scope_rows": same, "other_project_rows": other}

        # PostgreSQL repository branch: real insert + jsonb/timestamptz placeholders.
        store = PostgresStore(app_factory)
        repository = PostgresAIProfessionalDeliveryRepository(store)
        extra = dict(snapshot["record"])
        extra["extraction_id"] = "extraction-live-2-" + uuid4().hex[:8]
        extra["file_id"] = "file-live-2-" + uuid4().hex[:8]
        extra["file_sha256"] = hashlib.sha256(extra["file_id"].encode()).hexdigest()
        extra["created_at"] = now_iso()
        with repository.transaction(ORG, PROJECT, write=True) as tx:
            tx.insert_extraction(extra)
        with repository.transaction(ORG, PROJECT) as tx:
            found = tx.extraction_by_key(extra["file_id"], extra["file_sha256"])
            listed = tx.extractions()
        assert found and found["record"] == extra
        assert any(item["record"]["extraction_id"] == extra["extraction_id"] for item in listed)
        checks["postgres_repository"] = {"insert_and_read_back": True, "extractions": len(listed)}
        with app_factory() as db:
            db.execute("BEGIN")
            db.execute("SELECT set_config('rkd.organization_id',%s,true),set_config('rkd.project_id',%s,true)",
                       (ORG, PROJECT))
            try:
                db.execute("INSERT INTO rkd.ai_source_extraction(extraction_id,organization_id,project_id,"
                           "file_id,file_sha256,filename,size_bytes,extractor_kind,extractor_version,status,"
                           "segment_count,record,created_at) VALUES "
                           "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())",
                           ("forged-" + uuid4().hex[:8], "foreign-org", PROJECT, "f", "b" * 64,
                            "f.txt", 1, "plain_text", "rkd-source-content.v1", "extracted", 0,
                            Jsonb({"x": 1})))
                forged_rejected = False
            except psycopg.errors.InsufficientPrivilege:
                forged_rejected = True
            db.rollback()
        assert forged_rejected
        checks["forged_tenant_write_rejected"] = True

        result = {"schema_version": "rkd-postgres-delivery-verification.v1",
                  "checked_at": datetime.now(timezone.utc).isoformat(),
                  "scope": "014 professional delivery tables on a real isolated PostgreSQL 17 cluster",
                  "bind": "127.0.0.1", "port": port, "database": db_name,
                  "checks": checks, "passed": True,
                  "duration_seconds": round(time.monotonic() - started, 2),
                  "boundaries": ["isolated loopback cluster only; no daily SQLite cutover and no NAS change",
                                 "engineering evidence only; AD01—AD08 remain 0/8"]}
    except BaseException as error:
        result = {"schema_version": "rkd-postgres-delivery-verification.v1",
                  "checked_at": datetime.now(timezone.utc).isoformat(),
                  "passed": False, "error": f"{type(error).__name__}: {error}", "checks": checks}
        raise
    finally:
        if running:
            try:
                command(run_root, binary, "pg_ctl.exe", "-D", cluster, "-w", "-t", "45", "-m", "fast", "stop")
            except Exception as error:  # keep the evidence even if shutdown fails
                checks["shutdown_error"] = str(error)
        (run_root / "verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"evidence": str(run_root / "verification.json"),
                          "passed": result.get("passed"), "checks": checks}, ensure_ascii=False, indent=2), flush=True)
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
