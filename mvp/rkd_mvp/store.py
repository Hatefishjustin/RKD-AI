from __future__ import annotations

import copy
import hashlib
import json
from contextlib import nullcontext
from collections import defaultdict
from typing import Any

from .models import AuditEvent, CommandEnvelope, EventEnvelope, TenantContext, new_id


class AccessDenied(Exception):
    pass


class ConflictError(Exception):
    pass


class InMemoryStore:
    """Small in-memory stand-in for the transactional database boundary."""

    def __init__(self) -> None:
        self.projects: dict[tuple[str, str], dict[str, Any]] = {}
        self.files: dict[str, dict[str, Any]] = {}
        self.uploads: dict[str, dict[str, Any]] = {}
        self.aggregates: dict[tuple[str, str], dict[str, Any]] = {}
        self.commands: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.events: list[EventEnvelope] = []
        self.audit: list[AuditEvent] = []
        self.outbox: list[EventEnvelope] = []
        self.outbox_status: dict[str, dict[str, Any]] = {}
        self.dead_letters: list[dict[str, Any]] = []
        self.inbox: set[tuple[str, ...]] = set()
        self.inbox_status: dict[tuple[str, ...], dict[str, Any]] = {}
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.batches: dict[str, dict[str, Any]] = {}
        self.external_actions: dict[str, dict[str, Any]] = {}
        self.workflow_runs: dict[str, dict[str, Any]] = {}

    def persist(self) -> None:
        """Durable stores override this; the in-memory store has nothing to flush."""
        return None

    def transaction(self):
        """Provide a common transaction boundary for gateways and durable stores."""
        return nullcontext()

    @staticmethod
    def _scope(context: TenantContext) -> tuple[str, str]:
        return context.organization_id, context.project_id

    def bootstrap_project(self, context: TenantContext, name: str) -> None:
        self.projects[self._scope(context)] = {
            "organization_id": context.organization_id,
            "project_id": context.project_id,
            "name": name,
            "status": "active",
            "version": 0,
        }

    def require_project(self, context: TenantContext) -> None:
        project = self.projects.get(self._scope(context))
        if not project or project["organization_id"] != context.organization_id:
            raise AccessDenied("resource not found")

    def add_scanned_file(self, context: TenantContext, name: str, content: bytes) -> str:
        self.require_project(context)
        file_id = new_id("file")
        self.files[file_id] = {
            "file_id": file_id,
            "organization_id": context.organization_id,
            "project_id": context.project_id,
            "name": name,
            "sha256": hashlib.sha256(content).hexdigest(),
            "status": "scanned",
        }
        return file_id

    def check_scope(self, context: TenantContext, organization_id: str, project_id: str) -> None:
        if (context.organization_id, context.project_id) != (organization_id, project_id):
            raise AccessDenied("resource not found")

    def get_aggregate(self, context: TenantContext, aggregate_id: str) -> dict[str, Any] | None:
        aggregate = self.aggregates.get(self._scope(context) + (aggregate_id,))
        return copy.deepcopy(aggregate) if aggregate else None

    def put_aggregate(self, context: TenantContext, aggregate_id: str, value: dict[str, Any]) -> None:
        value = copy.deepcopy(value)
        value["organization_id"] = context.organization_id
        value["project_id"] = context.project_id
        self.aggregates[self._scope(context) + (aggregate_id,)] = value

    def append_event(self, context: TenantContext, event_type: str, aggregate_id: str,
                     payload: dict[str, Any], command: CommandEnvelope) -> EventEnvelope:
        existing = self.get_aggregate(context, aggregate_id) or {"version": 0}
        version = int(existing.get("version", 0)) + 1
        event = EventEnvelope(
            event_id=new_id("evt"),
            event_type=event_type,
            context=context,
            aggregate_id=aggregate_id,
            aggregate_version=version,
            payload=copy.deepcopy(payload),
            correlation_id=command.correlation_id or command.command_id,
            causation_id=command.causation_id or command.command_id,
            idempotency_key=command.idempotency_key,
        )
        existing["version"] = version
        self.put_aggregate(context, aggregate_id, existing)
        self.events.append(event)
        self.outbox.append(event)
        self.outbox_status[event.event_id] = {
            "organization_id": context.organization_id,
            "project_id": context.project_id,
            "status": "pending",
            "attempts": 0,
            "last_error": "",
        }
        return event

    def append_audit(self, context: TenantContext, event_type: str, target_type: str,
                     target_id: str, outcome: str, detail: dict[str, Any]) -> AuditEvent:
        previous = self.audit[-1].event_hash if self.audit else ""
        material = json.dumps({
            "event_type": event_type,
            "target_type": target_type,
            "target_id": target_id,
            "outcome": outcome,
            "detail": detail,
            "previous_hash": previous,
        }, sort_keys=True, ensure_ascii=True)
        audit = AuditEvent(
            audit_id=new_id("audit"),
            event_type=event_type,
            context=context,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            detail=copy.deepcopy(detail),
            previous_hash=previous,
            event_hash=hashlib.sha256(material.encode()).hexdigest(),
        )
        self.audit.append(audit)
        return audit

    def record_command(self, command: CommandEnvelope, result: dict[str, Any]) -> None:
        key = (command.context.organization_id, command.context.project_id, command.idempotency_key)
        self.commands[key] = copy.deepcopy(result)

    def command_result(self, command: CommandEnvelope) -> dict[str, Any] | None:
        key = (command.context.organization_id, command.context.project_id, command.idempotency_key)
        result = self.commands.get(key)
        return copy.deepcopy(result) if result else None

    def snapshot(self) -> dict[str, Any]:
        return {
            "projects": copy.deepcopy(self.projects),
            "files": copy.deepcopy(self.files),
            "events": len(self.events),
            "audit": len(self.audit),
            "outbox": len(self.outbox),
            "outbox_status": copy.deepcopy(self.outbox_status),
            "dead_letters": copy.deepcopy(self.dead_letters),
            "jobs": copy.deepcopy(self.jobs),
            "batches": copy.deepcopy(self.batches),
        }
