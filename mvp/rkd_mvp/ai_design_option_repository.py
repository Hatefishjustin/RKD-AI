"""Explicit SQLite/PostgreSQL repositories for isolated AI design options."""
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


class _OptionTransaction:
    def __init__(self, db: Any, organization_id: str, project_id: str, *, postgres: bool) -> None:
        self.db, self.scope = db, (organization_id, project_id)
        self.postgres = postgres
        self.set_table = "rkd.ai_design_option_set" if postgres else "ai_design_option_sets"
        self.revision_table = "rkd.ai_design_option_revision" if postgres else "ai_design_option_revisions"
        self.adoption_table = "rkd.ai_design_option_adoption" if postgres else "ai_design_option_adoptions"
        self.artifact_table = "rkd.ai_design_option_artifact" if postgres else "ai_design_option_artifacts"

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
    def _public_set(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for key in ("config", "context"):
            suffix = f"{key}_json"
            data[key] = _decode(data.pop(suffix, data.pop(key, None)))
        for key in ("created_at", "updated_at"):
            data[key] = _iso(data[key])
        return data

    @staticmethod
    def _public_revision(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for key in ("strategy", "model", "validation", "materials", "cost", "feedback", "diff",
                    "conflicts", "structure_signature"):
            suffix = f"{key}_json"
            data[key] = _decode(data.pop(suffix, data.pop(key, None)))
        data["created_at"] = _iso(data["created_at"])
        return data

    @staticmethod
    def _public_artifact(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data["created_at"] = _iso(data["created_at"])
        return data

    def set_by_key(self, key: str) -> dict[str, Any] | None:
        rows = self._rows(f"SELECT * FROM {self.set_table} WHERE organization_id={self._p} AND project_id={self._p} AND idempotency_key={self._p}",
                          (*self.scope, key))
        return self._public_set(rows[0]) if rows else None

    def set_row(self, set_id: str) -> dict[str, Any] | None:
        rows = self._rows(f"SELECT * FROM {self.set_table} WHERE organization_id={self._p} AND project_id={self._p} AND set_id={self._p}",
                          (*self.scope, set_id))
        return self._public_set(rows[0]) if rows else None

    def sets(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._rows(f"SELECT * FROM {self.set_table} WHERE organization_id={self._p} AND project_id={self._p} ORDER BY created_at DESC, set_id DESC LIMIT {self._p}",
                          (*self.scope, limit))
        return [self._public_set(row) for row in rows]

    def insert_set(self, row: dict[str, Any]) -> None:
        columns = ("set_id", "organization_id", "project_id", "brief_id", "input_hash", "status", "phase",
                   "attempt_count", self._json_column("config"), self._json_column("context"), "error_code",
                   "error_message", "idempotency_key", "actor_id", "created_at", "updated_at")
        values = (row["set_id"], *self.scope, row["brief_id"], row["input_hash"], row["status"], row["phase"],
                  row["attempt_count"], _json(row["config"]), _json(row["context"]), row["error_code"],
                  row["error_message"], row["idempotency_key"], row["actor_id"],
                  self._time(row["created_at"]), self._time(row["updated_at"]))
        json_names = {"config", "context", "config_json", "context_json"}
        time_names = {"created_at", "updated_at"}
        placeholders = ",".join(self._json_p if name in json_names else self._time_p if name in time_names else self._p for name in columns)
        self.db.execute(f"INSERT INTO {self.set_table} ({','.join(columns)}) VALUES ({placeholders})", values)

    def update_set(self, set_id: str, *, status: str, phase: str, updated_at: str,
                   error_code: str | None = None, error_message: str | None = None) -> None:
        self.db.execute(
            f"UPDATE {self.set_table} SET status={self._p},phase={self._p},updated_at={self._time_p},"
            f"error_code={self._p},error_message={self._p} "
            f"WHERE organization_id={self._p} AND project_id={self._p} AND set_id={self._p}",
            (status, phase, self._time(updated_at), error_code, error_message, *self.scope, set_id),
        )

    def start_set(self, set_id: str, attempt: int, now: str) -> None:
        self.db.execute(
            f"UPDATE {self.set_table} SET status='running',phase='strategy',attempt_count={self._p},"
            f"error_code=NULL,error_message=NULL,updated_at={self._time_p} "
            f"WHERE organization_id={self._p} AND project_id={self._p} AND set_id={self._p} AND status='queued'",
            (attempt, self._time(now), *self.scope, set_id),
        )

    def recover_running(self, now: str, active_set_ids: tuple[str, ...] = ()) -> None:
        exclusion = ""
        args: tuple[Any, ...] = ("WORKER_RESTARTED", "服务重启，候选集等待显式重试", self._time(now), *self.scope)
        if active_set_ids:
            exclusion = f" AND set_id NOT IN ({','.join(self._p for _ in active_set_ids)})"
            args += active_set_ids
        self.db.execute(
            f"UPDATE {self.set_table} SET status='failed',phase='failed',error_code={self._p},error_message={self._p},"
            f"updated_at={self._time_p} WHERE organization_id={self._p} AND project_id={self._p} AND status='running'{exclusion}",
            args,
        )

    def latest_revision(self, option_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.revision_table} WHERE organization_id={self._p} AND project_id={self._p} AND option_id={self._p} ORDER BY revision_no DESC LIMIT 1",
            (*self.scope, option_id),
        )
        return self._public_revision(rows[0]) if rows else None

    def revision(self, option_revision_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.revision_table} WHERE organization_id={self._p} AND project_id={self._p} AND option_revision_id={self._p}",
            (*self.scope, option_revision_id),
        )
        return self._public_revision(rows[0]) if rows else None

    def revisions_for_set(self, set_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.revision_table} WHERE organization_id={self._p} AND project_id={self._p} AND set_id={self._p} ORDER BY created_at DESC, option_id, revision_no DESC",
            (*self.scope, set_id),
        )
        return [self._public_revision(row) for row in rows]

    def revisions_for_option(self, option_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.revision_table} WHERE organization_id={self._p} AND project_id={self._p} AND option_id={self._p} ORDER BY revision_no",
            (*self.scope, option_id),
        )
        return [self._public_revision(row) for row in rows]

    def insert_revision(self, row: dict[str, Any]) -> None:
        json_fields = ("strategy", "model", "validation", "materials", "cost", "feedback", "diff",
                       "conflicts", "structure_signature")
        columns = ("option_revision_id", "set_id", "option_id", "organization_id", "project_id", "revision_no",
                   "parent_revision_id", "strategy_id", *(self._json_column(name) for name in json_fields),
                   "lifecycle_status", "source_kind", "change_reason", "actor_id", "created_at")
        values = (row["option_revision_id"], row["set_id"], row["option_id"], *self.scope, row["revision_no"],
                  row["parent_revision_id"], row["strategy_id"], *(_json(row[name]) for name in json_fields),
                  row["lifecycle_status"], row["source_kind"], row["change_reason"], row["actor_id"],
                  self._time(row["created_at"]))
        json_names = set(json_fields) | {f"{name}_json" for name in json_fields}
        placeholders = ",".join(self._json_p if name in json_names else self._time_p if name == "created_at" else self._p for name in columns)
        self.db.execute(f"INSERT INTO {self.revision_table} ({','.join(columns)}) VALUES ({placeholders})", values)

    def artifact(self, artifact_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.artifact_table} WHERE organization_id={self._p} AND project_id={self._p} AND artifact_id={self._p}",
            (*self.scope, artifact_id),
        )
        return self._public_artifact(rows[0]) if rows else None

    def artifacts(self, option_revision_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.artifact_table} WHERE organization_id={self._p} AND project_id={self._p} AND option_revision_id={self._p} ORDER BY artifact_kind",
            (*self.scope, option_revision_id),
        )
        return [self._public_artifact(row) for row in rows]

    def insert_artifact(self, row: dict[str, Any]) -> None:
        columns = ("artifact_id", "option_revision_id", "organization_id", "project_id", "artifact_kind",
                   "filename", "content_type", "relative_path", "sha256", "size_bytes", "created_at")
        values = (row["artifact_id"], row["option_revision_id"], *self.scope, row["artifact_kind"],
                  row["filename"], row["content_type"], row["relative_path"], row["sha256"],
                  row["size_bytes"], self._time(row["created_at"]))
        placeholders = ",".join(self._time_p if name == "created_at" else self._p for name in columns)
        self.db.execute(f"INSERT INTO {self.artifact_table} ({','.join(columns)}) VALUES ({placeholders})", values)

    def adoption(self) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.adoption_table} WHERE organization_id={self._p} AND project_id={self._p}",
            self.scope,
        )
        if not rows:
            return None
        data = dict(rows[0])
        for key in ("created_at", "updated_at"):
            data[key] = _iso(data[key])
        return data

    def upsert_adoption(self, row: dict[str, Any]) -> None:
        columns = ("organization_id", "project_id", "option_revision_id", "set_id", "option_id", "revision_no",
                   "expected_revision", "status", "production_task_status", "actor_id", "created_at", "updated_at")
        values = (*self.scope, row["option_revision_id"], row["set_id"], row["option_id"], row["revision_no"],
                  row["expected_revision"], row["status"], row["production_task_status"], row["actor_id"],
                  self._time(row["created_at"]), self._time(row["updated_at"]))
        placeholders = ",".join(self._time_p if name in {"created_at", "updated_at"} else self._p for name in columns)
        updates = ",".join(f"{name}=EXCLUDED.{name}" for name in columns if name not in {"organization_id", "project_id", "created_at"})
        self.db.execute(
            f"INSERT INTO {self.adoption_table} ({','.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT (organization_id, project_id) DO UPDATE SET {updates}",
            values,
        )


class SQLiteAIDesignOptionRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def transaction(self, organization_id: str, project_id: str, *, write: bool = False) -> Iterator[_OptionTransaction]:
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield _OptionTransaction(connection, organization_id, project_id, postgres=False)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


class PostgresAIDesignOptionRepository:
    def __init__(self, store: Any) -> None:
        self.store = store

    @contextmanager
    def transaction(self, organization_id: str, project_id: str, *, write: bool = False) -> Iterator[_OptionTransaction]:
        context = TenantContext(organization_id, project_id, "ai-design-option-worker")
        with self.store.tenant_transaction(context) as connection:
            yield _OptionTransaction(connection, organization_id, project_id, postgres=True)
