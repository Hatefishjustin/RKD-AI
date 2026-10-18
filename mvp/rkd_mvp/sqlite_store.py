from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import AuditEvent, EventEnvelope, ExecutorResult, TenantContext
from .store import InMemoryStore


class SQLiteStore(InMemoryStore):
    """Durable local store used before a PostgreSQL deployment is available."""

    def __init__(self, db_path: str | Path) -> None:
        super().__init__()
        self.db_path = str(db_path)
        self._connection_local = threading.local()
        self._connection_lock = threading.RLock()
        self._transaction_local = threading.local()
        self._migrate()
        self._load()

    def _connection(self) -> sqlite3.Connection:
        """Open one SQLite connection per worker thread.

        The old reference store shared a connection created by the server thread,
        which fails as soon as ThreadingHTTPServer handles a request. Keeping the
        connection thread-local preserves SQLite's safety check and lets each
        request use a short transaction.
        """
        connection = getattr(self._connection_local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=True)
            connection.execute("PRAGMA foreign_keys = ON")
            self._connection_local.connection = connection
        return connection

    def _migrate(self) -> None:
        connection = self._connection()
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        migration_root = Path(__file__).resolve().parents[1] / "persistence" / "sqlite"
        migrations = sorted(migration_root.glob("*.sql"))
        for migration in migrations:
            version = int(migration.stem.split("_", 1)[0])
            already_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
            ).fetchone()
            if already_applied:
                continue
            try:
                connection.executescript("BEGIN IMMEDIATE;\n" + migration.read_text(encoding="utf-8"))
                if version == 2:
                    state = connection.execute("SELECT payload FROM mvp_state WHERE state_id = 1").fetchone()
                    if state:
                        for project in json.loads(state[0]).get("projects", {}).values():
                            connection.execute(
                                "INSERT INTO projects(organization_id, project_id, name, status, version) "
                                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(organization_id, project_id) "
                                "DO UPDATE SET name=excluded.name, status=excluded.status, version=excluded.version",
                                (project["organization_id"], project["project_id"], project.get("name", ""),
                                 project.get("status", "active"), int(project.get("version", 0))),
                            )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
                    (version,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _context(data: dict[str, Any]) -> TenantContext:
        return TenantContext(**data)

    @classmethod
    def _event(cls, data: dict[str, Any]) -> EventEnvelope:
        data = dict(data)
        data["context"] = cls._context(data["context"])
        return EventEnvelope(**data)

    @classmethod
    def _audit(cls, data: dict[str, Any]) -> AuditEvent:
        data = dict(data)
        data["context"] = cls._context(data["context"])
        return AuditEvent(**data)

    @staticmethod
    def _key(key: tuple[str, ...]) -> str:
        return "\u001f".join(key)

    @staticmethod
    def _unkey(key: str) -> tuple[str, ...]:
        return tuple(key.split("\u001f"))

    def _serialise(self) -> dict[str, Any]:
        return {
            "projects": {self._key(k): v for k, v in self.projects.items()},
            "files": self.files,
            "uploads": self.uploads,
            "aggregates": {self._key(k): v for k, v in self.aggregates.items()},
            "commands": {self._key(k): v for k, v in self.commands.items()},
            "events": [asdict(item) for item in self.events],
            "audit": [asdict(item) for item in self.audit],
            "outbox": [asdict(item) for item in self.outbox],
            "outbox_status": self.outbox_status,
            "dead_letters": self.dead_letters,
            "inbox": [list(item) for item in self.inbox],
            "inbox_status": {self._key(k): v for k, v in self.inbox_status.items()},
            "artifacts": self.artifacts,
            "jobs": {
                key: {**value, "result": asdict(value["result"])}
                for key, value in self.jobs.items()
            },
            "batches": self.batches,
            "external_actions": self.external_actions,
            "workflow_runs": self.workflow_runs,
        }

    def _flush(self) -> None:
        transaction_depth = getattr(self._transaction_local, "depth", 0)
        if transaction_depth:
            self._transaction_local.dirty = True
            return
        with self._connection_lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        connection = self._connection()
        payload = json.dumps(self._serialise(), ensure_ascii=True, sort_keys=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO mvp_state(state_id, payload) VALUES (1, ?) "
                "ON CONFLICT(state_id) DO UPDATE SET payload=excluded.payload",
                (payload,),
            )
            connection.executemany(
                "INSERT INTO projects(organization_id, project_id, name, status, version) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(organization_id, project_id) DO UPDATE SET "
                "name=excluded.name, status=excluded.status, version=excluded.version",
                [
                    (project["organization_id"], project["project_id"], project.get("name", ""),
                     project.get("status", "active"), int(project.get("version", 0)))
                    for project in self.projects.values()
                ],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _load(self) -> None:
        row = self._connection().execute("SELECT payload FROM mvp_state WHERE state_id = 1").fetchone()
        if not row:
            return
        data = json.loads(row[0])
        self.projects = {
            (organization_id, project_id): {
                "organization_id": organization_id,
                "project_id": project_id,
                "name": name,
                "status": status,
                "version": version,
            }
            for organization_id, project_id, name, status, version in self._connection().execute(
                "SELECT organization_id, project_id, name, status, version FROM projects"
            )
        }
        self.files = data.get("files", {})
        self.uploads = data.get("uploads", {})
        self.aggregates = {self._unkey(k): v for k, v in data.get("aggregates", {}).items()}
        self.commands = {self._unkey(k): v for k, v in data.get("commands", {}).items()}
        self.events = [self._event(item) for item in data.get("events", [])]
        self.audit = [self._audit(item) for item in data.get("audit", [])]
        self.outbox = [self._event(item) for item in data.get("outbox", [])]
        self.outbox_status = data.get("outbox_status", {})
        self.dead_letters = data.get("dead_letters", [])
        self.inbox = {tuple(item) for item in data.get("inbox", [])}
        self.inbox_status = {self._unkey(k): v for k, v in data.get("inbox_status", {}).items()}
        self.artifacts = data.get("artifacts", {})
        self.jobs = {}
        for key, value in data.get("jobs", {}).items():
            value = dict(value)
            value["result"] = ExecutorResult(**value["result"])
            self.jobs[key] = value
        self.batches = data.get("batches", {})
        self.external_actions = data.get("external_actions", {})
        self.workflow_runs = data.get("workflow_runs", {})

    def bootstrap_project(self, context: TenantContext, name: str) -> None:
        super().bootstrap_project(context, name)
        self._flush()

    def add_scanned_file(self, context: TenantContext, name: str, content: bytes) -> str:
        file_id = super().add_scanned_file(context, name, content)
        self._flush()
        return file_id

    def put_aggregate(self, context: TenantContext, aggregate_id: str, value: dict[str, Any]) -> None:
        super().put_aggregate(context, aggregate_id, value)
        self._flush()

    def append_event(self, context: TenantContext, event_type: str, aggregate_id: str,
                     payload: dict[str, Any], command) -> EventEnvelope:
        event = super().append_event(context, event_type, aggregate_id, payload, command)
        self._flush()
        return event

    def append_audit(self, context: TenantContext, event_type: str, target_type: str,
                     target_id: str, outcome: str, detail: dict[str, Any]) -> AuditEvent:
        audit = super().append_audit(context, event_type, target_type, target_id, outcome, detail)
        self._flush()
        return audit

    def record_command(self, command, result: dict[str, Any]) -> None:
        super().record_command(command, result)
        self._flush()

    def close(self) -> None:
        connection = getattr(self._connection_local, "connection", None)
        if connection is not None:
            connection.close()
            self._connection_local.connection = None

    def close_thread_connection(self) -> None:
        """Close only the connection owned by the current request thread."""
        self.close()

    def persist(self) -> None:
        self._flush()

    @contextmanager
    def transaction(self):
        """Group state, command, event and audit writes into one durable commit."""
        with self._connection_lock:
            depth = getattr(self._transaction_local, "depth", 0)
            if depth:
                self._transaction_local.depth = depth + 1
                try:
                    yield self
                finally:
                    self._transaction_local.depth = depth
                return

            before = deepcopy(self._serialise())
            self._transaction_local.depth = 1
            self._transaction_local.dirty = False
            try:
                yield self
                if getattr(self._transaction_local, "dirty", False):
                    self._flush_locked()
            except Exception:
                self._restore(before)
                raise
            finally:
                self._transaction_local.depth = 0
                self._transaction_local.dirty = False

    def _restore(self, data: dict[str, Any]) -> None:
        self.projects = {self._unkey(k): v for k, v in data.get("projects", {}).items()}
        self.files = data.get("files", {})
        self.uploads = data.get("uploads", {})
        self.aggregates = {self._unkey(k): v for k, v in data.get("aggregates", {}).items()}
        self.commands = {self._unkey(k): v for k, v in data.get("commands", {}).items()}
        self.events = [self._event(item) for item in data.get("events", [])]
        self.audit = [self._audit(item) for item in data.get("audit", [])]
        self.outbox = [self._event(item) for item in data.get("outbox", [])]
        self.outbox_status = data.get("outbox_status", {})
        self.dead_letters = data.get("dead_letters", [])
        self.inbox = {tuple(item) for item in data.get("inbox", [])}
        self.inbox_status = {self._unkey(k): v for k, v in data.get("inbox_status", {}).items()}
        self.artifacts = data.get("artifacts", {})
        self.jobs = {}
        for key, value in data.get("jobs", {}).items():
            value = dict(value)
            value["result"] = ExecutorResult(**value["result"])
            self.jobs[key] = value
        self.batches = data.get("batches", {})
        self.external_actions = data.get("external_actions", {})
        self.workflow_runs = data.get("workflow_runs", {})
