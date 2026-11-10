from __future__ import annotations

"""Read-only SQLite snapshot -> empty PostgreSQL database rehearsal.

This is a deliberately explicit mapping, not an SQL dialect translator.  All
rows are compared after type conversion before the PostgreSQL commit.  Active
sessions/login counters are invalidated, and unsupported legacy state fails
closed instead of disappearing during import.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from .postgres_store import ConnectionFactory


TABLES = (
    ("projects", "project"),
    ("file_uploads", "file_upload"), ("file_assets", "file_asset"),
    ("project_decisions", "project_decision"), ("jobs", "job"),
    ("job_attempts", "job_attempt"), ("issues", "issue"), ("issue_actions", "issue_action"),
    ("estimates", "estimate"), ("estimate_revisions", "estimate_revision"),
    ("estimate_lines", "estimate_line"), ("calculation_runs", "calculation_run"),
    ("spatial_units", "spatial_unit"), ("geometry_revisions", "geometry_revision"),
    ("quantity_items", "quantity_item"), ("spatial_artifacts", "spatial_artifact"),
    ("spatial_quotes", "spatial_quote"), ("spatial_audit", "spatial_audit"),
    ("estimate_artifacts", "estimate_artifact"), ("requirements", "requirement"),
    ("requirement_revisions", "requirement_revision"), ("design_revisions", "design_revision"),
    ("design_artifacts", "design_artifact"),
    ("production_settings", "production_settings"), ("production_revisions", "production_revision"),
    ("production_artifacts", "production_artifact"), ("procurement_orders", "procurement_order"),
    ("procurement_order_lines", "procurement_order_line"), ("material_receipts", "material_receipt"),
    ("material_receipt_lines", "material_receipt_line"), ("material_allocations", "material_allocation"),
    ("procurement_events", "procurement_event"), ("change_requests", "change_request"),
    ("change_artifacts", "change_artifact"), ("change_acceptances", "change_acceptance"),
    ("change_events", "change_event"), ("auth_users", "auth_user"),
    ("auth_memberships", "auth_membership"), ("auth_audit", "auth_audit"),
    ("review_tasks", "review_task"), ("review_checklists", "review_checklist"), ("review_positions", "review_position"), ("review_position_members", "review_position_member"),
    ("ai_requirement_jobs", "ai_requirement_job"), ("ai_requirement_runs", "ai_requirement_run"),
    ("ai_requirement_briefs", "ai_requirement_brief"),
    ("ai_design_option_sets", "ai_design_option_set"),
    ("ai_design_option_revisions", "ai_design_option_revision"),
    ("ai_design_option_adoptions", "ai_design_option_adoption"),
    ("ai_design_option_artifacts", "ai_design_option_artifact"),
    ("ai_development_jobs", "ai_development_job"),
    ("ai_development_revisions", "ai_development_revision"),
    ("ai_development_artifacts", "ai_development_artifact"),
    ("ai_source_extractions", "ai_source_extraction"),
    ("ai_technical_deliveries", "ai_technical_delivery"),
    ("ai_technical_artifacts", "ai_technical_artifact"),
)
PARENTS = {
    "job_attempts": ("jobs", ("job_id",)),
    "estimate_lines": ("estimate_revisions", ("estimate_id", "revision_no")),
    "spatial_quotes": ("geometry_revisions", ("geometry_revision_id",)),
    "design_artifacts": ("design_revisions", ("design_revision_id",)),
    "procurement_order_lines": ("procurement_orders", ("order_id",)),
    "material_receipt_lines": ("material_receipts", ("receipt_id",)),
    "change_artifacts": ("change_requests", ("change_id",)),
    "production_artifacts": ("production_revisions", ("production_revision_id",)),
}
BOOLS = {"is_admin", "active", "external_effects_enabled", "source_scope_conflict", "real_model"}
TIMES = {"created_at", "updated_at", "started_at", "finished_at", "lease_until", "received_at"}
JSON_FIELDS = {
    "value", "output", "detail", "source_summary", "source_notes", "assumptions",
    "result", "warnings", "deductions", "pricing", "content", "source_refs",
    "model", "validation", "payload", "baseline", "proposal", "impact", "checklist", "details",
    "settings", "quantities", "quote", "procurement",
    "context_manifest", "request", "config", "usage", "cost", "error", "brief",
    "context", "strategy", "materials", "feedback", "diff", "conflicts", "structure_signature",
    "settings", "baseline", "package", "quantities", "objects", "unknowns", "view_mapping",
    # 014 professional delivery: SQLite *_json columns map to PG jsonb columns.
    "record", "handover", "source_extraction_ids",
}


SUPPORTED_SNAPSHOT_VERSIONS = tuple(range(14, 25))


class ImportRejected(RuntimeError):
    pass


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _digest(rows: list[dict[str, Any]]) -> str:
    encoded = sorted(json.dumps(_canonical(row), sort_keys=True, ensure_ascii=True, separators=(",", ":")) for row in rows)
    return hashlib.sha256("\n".join(encoded).encode()).hexdigest()


class SQLitePostgresImporter:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self.connection_factory = connection_factory

    def run(self, snapshot: str | Path, runtime_root: str | Path) -> dict[str, Any]:
        from psycopg import sql
        from psycopg.types.json import Jsonb

        source_path = Path(snapshot).resolve()
        root = Path(runtime_root).resolve()
        source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        try:
            source.execute("BEGIN")
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ImportRejected("SQLite integrity check failed")
            table_names = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            known = {name for name, _ in TABLES} | {"schema_migrations", "mvp_state", "auth_sessions", "auth_login_limits"}
            if table_names - known:
                raise ImportRejected(f"unmapped SQLite tables: {sorted(table_names - known)}")
            data = {name: [dict(row) for row in source.execute(f'SELECT * FROM "{name}"')] if name in table_names else [] for name, _ in TABLES}
            state_row = source.execute("SELECT payload FROM mvp_state WHERE state_id=1").fetchone() if "mvp_state" in table_names else None
            state = json.loads(state_row[0]) if state_row else {}
            unsupported = [name for name, value in state.items() if value and name not in {"projects", "audit"}]
            if unsupported:
                raise ImportRejected(f"non-empty legacy snapshot domains require explicit adapters: {unsupported}")
            audit = []
            for row in state.get("audit", []):
                audit.append({**{key: value for key, value in row.items() if key != "context"},
                              "organization_id": row["context"]["organization_id"],
                              "project_id": row["context"]["project_id"], "actor_id": row["context"]["actor_id"]})
            discarded_sessions = source.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] if "auth_sessions" in table_names else 0
            version = source.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            if version not in SUPPORTED_SNAPSHOT_VERSIONS:
                raise ImportRejected(f"unsupported source schema version: {version}")

            converted: dict[str, list[dict[str, Any]]] = {}
            for name, target in TABLES:
                rows = []
                for original in data[name]:
                    row = dict(original)
                    if name in PARENTS:
                        parent, keys = PARENTS[name]
                        matches = [p for p in data[parent] if all(p[key] == row[key] for key in keys)]
                        if len(matches) != 1:
                            raise ImportRejected(f"missing/ambiguous parent scope for {name}")
                        row.update({key: matches[0][key] for key in ("organization_id", "project_id")})
                        if name == "material_receipt_lines":
                            row["order_id"] = matches[0]["order_id"]
                    mapped = {}
                    for key, value in row.items():
                        target_key = key[:-5] if key.endswith("_json") and name not in {"review_tasks", "review_checklists"} else key
                        if key.endswith("_json") and name not in {"review_tasks", "review_checklists"}:
                            value = json.loads(value) if value is not None else None
                        elif key in {"storage_key", "relative_path"} and value is not None:
                            # Runtime archives use portable paths. Windows source
                            # rows can contain backslashes; normalize the target
                            # reference without changing the source DB or bytes.
                            from .local_backup import _name, BackupRejected
                            try:
                                value = _name(value.replace("\\", "/"))
                            except (BackupRejected, AttributeError) as error:
                                raise ImportRejected("unsafe runtime path in source metadata") from error
                        elif key in BOOLS:
                            if value not in (0, 1):
                                raise ImportRejected(f"invalid boolean in {name}.{key}")
                            value = bool(value)
                        elif key in TIMES and value is not None:
                            value = datetime.fromisoformat(value)
                            if value.tzinfo is None:
                                raise ImportRejected(f"timestamp without timezone in {name}.{key}")
                        mapped[target_key] = value
                    rows.append(mapped)
                converted[target] = rows
            converted["audit_event"] = []
            for row in audit:
                row["created_at"] = datetime.fromisoformat(row["created_at"])
                converted["audit_event"].append(row)

            # Verify actual stored bytes before touching the target database.
            files = []
            for target, rows in converted.items():
                for row in rows:
                    location = row.get("storage_key", row.get("relative_path"))
                    if location is None:
                        continue
                    path = (root / location).resolve()
                    if not path.is_relative_to(root) or not path.is_file():
                        raise ImportRejected(f"missing or unsafe runtime file for {target}")
                    with path.open("rb") as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    if digest != row["sha256"] or path.stat().st_size != row["size_bytes"]:
                        raise ImportRejected(f"file hash/size mismatch for {target}")
                    files.append({"table": target, "relative_path": location, "sha256": digest, "size_bytes": path.stat().st_size})

            connection = self.connection_factory()
            try:
                connection.execute("BEGIN")
                connection.execute("SELECT pg_advisory_xact_lock(7241150202)")
                target_tables = (*converted, "organization", "auth_session", "auth_login_limit", "auth_login_throttle")
                connection.execute(sql.SQL("LOCK TABLE {} IN EXCLUSIVE MODE").format(
                    sql.SQL(",").join(sql.Identifier("rkd", name) for name in sorted(target_tables))))
                for target in target_tables:
                    if connection.execute(sql.SQL("SELECT EXISTS(SELECT 1 FROM rkd.{})").format(sql.Identifier(target))).fetchone()[0]:
                        raise ImportRejected(f"target table {target} is not empty; overwrite refused")
                organizations = sorted({row["organization_id"] for rows in converted.values() for row in rows})
                for org in organizations:
                    connection.execute("INSERT INTO rkd.organization(organization_id,name) VALUES (%s,%s)", (org, org))
                report = {}
                for target, rows in converted.items():
                    for row in rows:
                        columns = list(row)
                        values = [Jsonb(row[key]) if key in JSON_FIELDS else row[key] for key in columns]
                        connection.execute(sql.SQL("INSERT INTO rkd.{} ({}) VALUES ({})").format(
                            sql.Identifier(target), sql.SQL(",").join(map(sql.Identifier, columns)),
                            sql.SQL(",").join(sql.Placeholder() for _ in columns)), values)
                    if rows:
                        columns = list(rows[0])
                        cursor = connection.execute(sql.SQL("SELECT {} FROM rkd.{}").format(
                            sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(target)))
                        actual = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    else:
                        actual = []
                    expected_hash, actual_hash = _digest(rows), _digest(actual)
                    if len(rows) != len(actual) or expected_hash != actual_hash:
                        raise ImportRejected(f"row reconciliation failed for {target}")
                    report[target] = {"rows": len(rows), "sha256": actual_hash}
                # Catch file changes during the database copy before commit.
                for entry in files:
                    with (root / entry["relative_path"]).open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                            raise ImportRejected("runtime file changed during import")
                connection.commit()
                return {"source_schema_version": version, "tables": report, "files": files,
                        "sessions_invalidated": discarded_sessions, "rows_verified": sum(item["rows"] for item in report.values()),
                        "mode": "rehearsal_target_only", "runtime_cutover": False}
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
        finally:
            source.close()
