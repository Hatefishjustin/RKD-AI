"""Explicit SQLite/PostgreSQL repositories for AI requirement-understanding jobs.

The two dialects share one service contract. JSON and timestamps are encoded per
adapter; no SQL string translation or implicit fallback is used. Model calls are
deliberately outside these short transactions.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from .models import TenantContext


def _json(value: dict[str, Any] | list[Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


class _AITransaction:
    def __init__(self, db: Any, organization_id: str, project_id: str, *, postgres: bool) -> None:
        self.db, self.scope = db, (organization_id, project_id)
        self.postgres = postgres
        self.job_table = "rkd.ai_requirement_job" if postgres else "ai_requirement_jobs"
        self.run_table = "rkd.ai_requirement_run" if postgres else "ai_requirement_runs"
        self.brief_table = "rkd.ai_requirement_brief" if postgres else "ai_requirement_briefs"

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
        if not self.postgres or not isinstance(value, str):
            return value
        return datetime.fromisoformat(value)

    def _rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cursor = self.db.execute(sql, args)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def _json_column(self, name: str) -> str:
        return name if self.postgres else f"{name}_json"

    @staticmethod
    def _public_job(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for key in ("context_manifest", "request", "config"):
            suffix = f"{key}_json"
            data[key] = _decode(data.pop(suffix, data.pop(key, None)))
        for key in ("created_at", "updated_at"):
            data[key] = _iso(data[key])
        return data

    @staticmethod
    def _public_run(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for key in ("usage", "cost", "error"):
            suffix = f"{key}_json"
            data[key] = _decode(data.pop(suffix, data.pop(key, None)))
        data["real_model"] = bool(data["real_model"])
        for key in ("started_at", "finished_at"):
            data[key] = _iso(data[key])
        return data

    @staticmethod
    def _public_brief(row: dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        brief_key = "brief" if "brief" in data else "brief_json"
        data["brief"] = _decode(data.pop(brief_key))
        data["created_at"] = _iso(data["created_at"])
        return data

    def job_by_key(self, idempotency_key: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.job_table} WHERE organization_id={self._p} AND project_id={self._p} AND idempotency_key={self._p}",
            (*self.scope, idempotency_key),
        )
        return self._public_job(rows[0]) if rows else None

    def job(self, job_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.job_table} WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p}",
            (*self.scope, job_id),
        )
        return self._public_job(rows[0]) if rows else None

    def jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.job_table} WHERE organization_id={self._p} AND project_id={self._p} ORDER BY created_at DESC, job_id DESC LIMIT {self._p}",
            (*self.scope, limit),
        )
        return [self._public_job(row) for row in rows]

    def latest_succeeded_job(self) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.job_table} WHERE organization_id={self._p} AND project_id={self._p} AND status='succeeded' ORDER BY created_at DESC, job_id DESC LIMIT 1",
            self.scope,
        )
        return self._public_job(rows[0]) if rows else None

    def insert_job(self, row: dict[str, Any]) -> None:
        columns = (
            "job_id", "organization_id", "project_id", "job_type", "status", "phase", "attempt_count",
            "input_hash", self._json_column("context_manifest"), self._json_column("request"),
            self._json_column("config"), "output_brief_id", "error_code", "error_message",
            "idempotency_key", "actor_id", "created_at", "updated_at",
        )
        values = (
            row["job_id"], *self.scope, row["job_type"], row["status"], row["phase"], row["attempt_count"],
            row["input_hash"], _json(row["context_manifest"]), _json(row["request"]), _json(row["config"]),
            row["output_brief_id"], row["error_code"], row["error_message"], row["idempotency_key"],
            row["actor_id"], self._time(row["created_at"]), self._time(row["updated_at"]),
        )
        placeholders = ",".join(
            self._json_p if name in {"context_manifest", "request", "config", "context_manifest_json", "request_json", "config_json"}
            else self._time_p if name in {"created_at", "updated_at"}
            else self._p
            for name in columns
        )
        self.db.execute(f"INSERT INTO {self.job_table} ({','.join(columns)}) VALUES ({placeholders})", values)

    def update_job(self, job_id: str, *, status: str, phase: str, updated_at: str,
                   error_code: str | None = None, error_message: str | None = None,
                   output_brief_id: str | None = None) -> None:
        self.db.execute(
            f"UPDATE {self.job_table} SET status={self._p},phase={self._p},updated_at={self._time_p},"
            f"error_code={self._p},error_message={self._p},output_brief_id={self._p} "
            f"WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p}",
            (status, phase, self._time(updated_at), error_code, error_message, output_brief_id, *self.scope, job_id),
        )

    def start_job(self, job_id: str, attempt: int, now: str) -> None:
        self.db.execute(
            f"UPDATE {self.job_table} SET status='running',phase='understanding',attempt_count={self._p},"
            f"error_code=NULL,error_message=NULL,updated_at={self._time_p} "
            f"WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p} AND status='queued'",
            (attempt, self._time(now), *self.scope, job_id),
        )

    def recover_running(self, now: str, active_job_ids: tuple[str, ...] = ()) -> None:
        error = _json({"code": "WORKER_RESTARTED", "category": "execution", "message": "服务重启，作业等待显式重试"})
        exclusion = ""
        args: tuple[Any, ...] = ("WORKER_RESTARTED", "服务重启，作业等待显式重试", self._time(now), *self.scope)
        if active_job_ids:
            exclusion = f" AND job_id NOT IN ({','.join(self._p for _ in active_job_ids)})"
            args += active_job_ids
        self.db.execute(
            f"UPDATE {self.job_table} SET status='failed',phase='failed',error_code={self._p},error_message={self._p},"
            f"updated_at={self._time_p} WHERE organization_id={self._p} AND project_id={self._p} AND status='running'{exclusion}",
            args,
        )
        self.db.execute(
            f"UPDATE {self.run_table} SET status='failed',{self._json_column('error')}={self._json_p},finished_at={self._time_p} "
            f"WHERE organization_id={self._p} AND project_id={self._p} AND status='running'{exclusion}",
            (error, self._time(now), *self.scope, *active_job_ids),
        )

    def insert_run(self, row: dict[str, Any]) -> None:
        columns = (
            "run_id", "job_id", "organization_id", "project_id", "attempt_no", "provider_kind",
            "provider_name", "model_id", "adapter_version", "prompt_version", "config_hash",
            "real_model", "status", "provider_request_id", self._json_column("usage"),
            self._json_column("cost"), self._json_column("error"), "started_at", "finished_at",
        )
        values = (
            row["run_id"], row["job_id"], *self.scope, row["attempt_no"], row["provider_kind"],
            row["provider_name"], row["model_id"], row["adapter_version"], row["prompt_version"],
            row["config_hash"], bool(row["real_model"]) if self.postgres else int(bool(row["real_model"])),
            row["status"], row["provider_request_id"], _json(row["usage"]), _json(row["cost"]),
            _json(row["error"]), self._time(row["started_at"]),
            self._time(row["finished_at"]) if row["finished_at"] else None,
        )
        json_names = {"usage", "cost", "error", "usage_json", "cost_json", "error_json"}
        time_names = {"started_at", "finished_at"}
        placeholders = ",".join(self._json_p if name in json_names else self._time_p if name in time_names else self._p for name in columns)
        self.db.execute(f"INSERT INTO {self.run_table} ({','.join(columns)}) VALUES ({placeholders})", values)

    def finish_run(self, run_id: str, *, status: str, finished_at: str,
                   usage: dict[str, Any], cost: dict[str, Any], error: dict[str, Any] | None,
                   provider_request_id: str | None) -> None:
        self.db.execute(
            f"UPDATE {self.run_table} SET status={self._p},{self._json_column('usage')}={self._json_p},"
            f"{self._json_column('cost')}={self._json_p},{self._json_column('error')}={self._json_p},"
            f"provider_request_id={self._p},finished_at={self._time_p} "
            f"WHERE organization_id={self._p} AND project_id={self._p} AND run_id={self._p}",
            (status, _json(usage), _json(cost), _json(error), provider_request_id,
             self._time(finished_at), *self.scope, run_id),
        )

    def runs(self, job_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.run_table} WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p} ORDER BY attempt_no",
            (*self.scope, job_id),
        )
        return [self._public_run(row) for row in rows]

    def latest_brief(self, job_id: str) -> dict[str, Any] | None:
        rows = self._rows(
            f"SELECT * FROM {self.brief_table} WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p} ORDER BY revision_no DESC LIMIT 1",
            (*self.scope, job_id),
        )
        return self._public_brief(rows[0]) if rows else None

    def briefs(self, job_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            f"SELECT * FROM {self.brief_table} WHERE organization_id={self._p} AND project_id={self._p} AND job_id={self._p} ORDER BY revision_no",
            (*self.scope, job_id),
        )
        return [self._public_brief(row) for row in rows]

    def insert_brief(self, row: dict[str, Any]) -> None:
        brief_column = "brief" if self.postgres else "brief_json"
        columns = (
            "brief_id", "job_id", "organization_id", "project_id", "revision_no", "schema_version",
            brief_column, "input_hash", "source_kind", "change_reason", "actor_id", "created_at",
        )
        placeholders = ",".join(self._json_p if name == brief_column else self._time_p if name == "created_at" else self._p for name in columns)
        values = (
            row["brief_id"], row["job_id"], *self.scope, row["revision_no"], row["schema_version"],
            _json(row["brief"]), row["input_hash"], row["source_kind"], row["change_reason"],
            row["actor_id"], self._time(row["created_at"]),
        )
        self.db.execute(f"INSERT INTO {self.brief_table} ({','.join(columns)}) VALUES ({placeholders})", values)


class SQLiteAIRequirementRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def transaction(self, organization_id: str, project_id: str, *, write: bool = False) -> Iterator[_AITransaction]:
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield _AITransaction(connection, organization_id, project_id, postgres=False)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


class PostgresAIRequirementRepository:
    def __init__(self, store: Any) -> None:
        self.store = store

    @contextmanager
    def transaction(self, organization_id: str, project_id: str, *, write: bool = False) -> Iterator[_AITransaction]:
        context = TenantContext(organization_id, project_id, "ai-requirement-worker")
        with self.store.tenant_transaction(context) as connection:
            yield _AITransaction(connection, organization_id, project_id, postgres=True)
