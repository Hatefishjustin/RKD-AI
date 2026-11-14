"""Explicit SQLite/PostgreSQL repositories for AI development production drafts."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from .models import TenantContext


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    if hasattr(value, "items"):
        return dict(value)
    return value


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


class _DevelopmentTransaction:
    def __init__(self, db: Any, organization_id: str, project_id: str, *, postgres: bool) -> None:
        self.db, self.scope = db, (organization_id, project_id)
        self.postgres = postgres
        self.job_table = "rkd.ai_development_job" if postgres else "ai_development_jobs"
        self.revision_table = "rkd.ai_development_revision" if postgres else "ai_development_revisions"
        self.artifact_table = "rkd.ai_development_artifact" if postgres else "ai_development_artifacts"

    @property
    def _p(self) -> str:
        return "%s" if self.postgres else "?"

    @property
    def _json_p(self) -> str:
        return "%s::jsonb" if self.postgres else "?"

    @property
    def _time_p(self) -> str:
        return "%s::timestamptz" if self.postgres else "?"

    def _time(self, value: Any) -> Any:
        return datetime.fromisoformat(value) if self.postgres and isinstance(value, str) else value

    def _json_column(self, name: str) -> str:
        return name if self.postgres else f"{name}_json"

    def _rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cursor = self.db.execute(sql, args)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    @staticmethod
    def _public_job(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for key in ("settings", "config"):
            suffix = f"{key}_json"
            data[key] = _decode(data.pop(suffix, data.pop(key, None)))
        for key in ("created_at", "updated_at"):
            data[key] = _iso(data[key])
        return data

    @staticmethod
    def _public_revision(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for key in ("baseline", "package", "quantities", "cost", "objects", "materials",
                    "unknowns", "view_mapping"):
            suffix = f"{key}_json"
            data[key] = _decode(data.pop(suffix, data.pop(key, None)))
        data["created_at"] = _iso(data["created_at"])
        return data

    @staticmethod
    def _public_artifact(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data["created_at"] = _iso(data["created_at"])
        return data

    def job_by_key(self, key: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.job_table} WHERE organization_id={self._p} AND project_id={self._p} AND idempotency_key={self._p}",
            (*self.scope, key))
        return self._public_job(rows[0]) if rows else None

    def job(self, job_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.job_table} WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p}",
            (*self.scope, job_id))
        return self._public_job(rows[0]) if rows else None

    def jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.job_table} WHERE organization_id={self._p} AND project_id={self._p} ORDER BY created_at DESC, job_id DESC LIMIT {self._p}",
            (*self.scope, limit))
        return [self._public_job(row) for row in rows]

    def insert_job(self, row: dict[str, Any]) -> None:
        columns = ("job_id", "organization_id", "project_id", "option_revision_id", "adoption_version",
                   "input_hash", "status", "phase", "attempt_count", self._json_column("settings"),
                   self._json_column("config"), "error_code", "error_message", "idempotency_key",
                   "actor_id", "created_at", "updated_at")
        values = (row["job_id"], *self.scope, row["option_revision_id"], row["adoption_version"],
                  row["input_hash"], row["status"], row["phase"], row["attempt_count"],
                  _json(row["settings"]), _json(row["config"]), row["error_code"], row["error_message"],
                  row["idempotency_key"], row["actor_id"], self._time(row["created_at"]),
                  self._time(row["updated_at"]))
        json_names = {"settings", "config", "settings_json", "config_json"}
        time_names = {"created_at", "updated_at"}
        placeholders = ",".join(self._json_p if name in json_names else self._time_p if name in time_names else self._p for name in columns)
        self.db.execute(f"INSERT INTO {self.job_table} ({','.join(columns)}) VALUES ({placeholders})", values)

    def update_job(self, job_id: str, *, status: str, phase: str, updated_at: str,
                   error_code: str | None = None, error_message: str | None = None) -> None:
        self.db.execute(
            f"UPDATE {self.job_table} SET status={self._p},phase={self._p},updated_at={self._time_p},"
            f"error_code={self._p},error_message={self._p} "
            f"WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p}",
            (status, phase, self._time(updated_at), error_code, error_message, *self.scope, job_id),
        )

    def start_job(self, job_id: str, attempt: int, now: str) -> None:
        self.db.execute(
            f"UPDATE {self.job_table} SET status='running',phase='geometry',attempt_count={self._p},"
            f"error_code=NULL,error_message=NULL,updated_at={self._time_p} "
            f"WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p} AND status='queued'",
            (attempt, self._time(now), *self.scope, job_id),
        )

    def touch_job(self, job_id: str, phase: str, now: str,
                  *, only_status: str = "running") -> bool:
        """Conditional phase update: a cancelled job can never move forward."""
        cursor = self.db.execute(
            f"UPDATE {self.job_table} SET phase={self._p},updated_at={self._time_p} "
            f"WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p} "
            f"AND status={self._p}",
            (phase, self._time(now), *self.scope, job_id, only_status),
        )
        return bool(cursor.rowcount)

    def close_job(self, job_id: str, status: str, phase: str, now: str, *,
                  error_code: str | None = None, error_message: str | None = None,
                  only_status: tuple[str, ...] = ("queued", "running")) -> bool:
        """Conditional terminal transition (succeeded/failed/cancelled)."""
        marks = ",".join(self._p for _ in only_status)
        cursor = self.db.execute(
            f"UPDATE {self.job_table} SET status={self._p},phase={self._p},"
            f"error_code={self._p},error_message={self._p},updated_at={self._time_p} "
            f"WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p} "
            f"AND status IN ({marks})",
            (status, phase, error_code, error_message, self._time(now),
             *self.scope, job_id, *only_status),
        )
        return bool(cursor.rowcount)

    def recover_running(self, now: str, active_job_ids: tuple[str, ...] = ()) -> None:
        exclusion = ""
        args: tuple[Any, ...] = ("WORKER_RESTARTED", "服务重启，深化量价任务等待显式重试", self._time(now), *self.scope)
        if active_job_ids:
            exclusion = f" AND job_id NOT IN ({','.join(self._p for _ in active_job_ids)})"
            args += active_job_ids
        self.db.execute(
            f"UPDATE {self.job_table} SET status='failed',phase='failed',error_code={self._p},error_message={self._p},"
            f"updated_at={self._time_p} WHERE organization_id={self._p} AND project_id={self._p} AND status='running'{exclusion}",
            args,
        )

    def latest_succeeded_revision(self, output_version: str | None = None) -> dict[str, Any] | None:
        """Latest revision, optionally restricted to one output contract.

        The table is shared by the development and spatial-output services, so an
        unfiltered "latest" would let one batch silently take over the other's page.
        """
        if output_version is None:
            rows = self._rows(
                f"SELECT * FROM {self.revision_table} WHERE organization_id={self._p} AND project_id={self._p} ORDER BY created_at DESC, production_revision_id DESC LIMIT 1",
                self.scope)
        else:
            rows = self._rows(
                f"SELECT * FROM {self.revision_table} WHERE organization_id={self._p} AND project_id={self._p} AND output_version={self._p} ORDER BY created_at DESC, production_revision_id DESC LIMIT 1",
                (*self.scope, output_version))
        return self._public_revision(rows[0]) if rows else None

    def revision(self, production_revision_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.revision_table} WHERE organization_id={self._p} AND project_id={self._p} AND production_revision_id={self._p}",
            (*self.scope, production_revision_id))
        return self._public_revision(rows[0]) if rows else None

    def revisions(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.revision_table} WHERE organization_id={self._p} AND project_id={self._p} ORDER BY created_at DESC LIMIT {self._p}",
            (*self.scope, limit))
        return [self._public_revision(row) for row in rows]

    def insert_revision(self, row: dict[str, Any]) -> None:
        json_fields = ("baseline", "package", "quantities", "cost", "objects", "materials", "unknowns", "view_mapping")
        columns = ("production_revision_id", "job_id", "organization_id", "project_id", "option_revision_id",
                   "set_id", "option_id", "adoption_version", "input_hash",
                   *(self._json_column(name) for name in json_fields),
                   "formula_version", "measurement_version", "output_version", "actor_id", "created_at")
        values = (row["production_revision_id"], row["job_id"], *self.scope, row["option_revision_id"],
                  row["set_id"], row["option_id"], row["adoption_version"], row["input_hash"],
                  *(_json(row[name]) for name in json_fields), row["formula_version"],
                  row["measurement_version"], row["output_version"], row["actor_id"],
                  self._time(row["created_at"]))
        json_names = set(json_fields) | {f"{name}_json" for name in json_fields}
        placeholders = ",".join(self._json_p if name in json_names else self._time_p if name == "created_at" else self._p for name in columns)
        self.db.execute(f"INSERT INTO {self.revision_table} ({','.join(columns)}) VALUES ({placeholders})", values)

    def artifact(self, artifact_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.artifact_table} WHERE organization_id={self._p} AND project_id={self._p} AND artifact_id={self._p}",
            (*self.scope, artifact_id))
        return self._public_artifact(rows[0]) if rows else None

    def artifacts(self, production_revision_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.artifact_table} WHERE organization_id={self._p} AND project_id={self._p} AND production_revision_id={self._p} ORDER BY artifact_kind",
            (*self.scope, production_revision_id))
        return [self._public_artifact(row) for row in rows]

    def insert_artifact(self, row: dict[str, Any]) -> None:
        columns = ("artifact_id", "production_revision_id", "organization_id", "project_id", "artifact_kind",
                   "filename", "content_type", "relative_path", "sha256", "size_bytes", "created_at")
        values = (row["artifact_id"], row["production_revision_id"], *self.scope, row["artifact_kind"],
                  row["filename"], row["content_type"], row["relative_path"], row["sha256"],
                  row["size_bytes"], self._time(row["created_at"]))
        placeholders = ",".join(self._time_p if name == "created_at" else self._p for name in columns)
        self.db.execute(f"INSERT INTO {self.artifact_table} ({','.join(columns)}) VALUES ({placeholders})", values)


class SQLiteAIDevelopmentRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def transaction(self, organization_id: str, project_id: str, *, write: bool = False) -> Iterator[_DevelopmentTransaction]:
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield _DevelopmentTransaction(connection, organization_id, project_id, postgres=False)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


class PostgresAIDevelopmentRepository:
    def __init__(self, store: Any) -> None:
        self.store = store

    @contextmanager
    def transaction(self, organization_id: str, project_id: str, *, write: bool = False) -> Iterator[_DevelopmentTransaction]:
        context = TenantContext(organization_id, project_id, "ai-development-worker")
        with self.store.tenant_transaction(context) as connection:
            yield _DevelopmentTransaction(connection, organization_id, project_id, postgres=True)
