from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass(frozen=True)
class TenantContext:
    organization_id: str
    project_id: str
    actor_id: str
    actor_type: str = "human"


@dataclass(frozen=True)
class CommandEnvelope:
    command_id: str
    command_name: str
    context: TenantContext
    idempotency_key: str
    aggregate_id: str
    payload: Mapping[str, Any]
    schema_version: str = "1"
    correlation_id: str = ""
    causation_id: str = ""


@dataclass
class EventEnvelope:
    event_id: str
    event_type: str
    context: TenantContext
    aggregate_id: str
    aggregate_version: int
    payload: dict[str, Any]
    correlation_id: str
    causation_id: str
    idempotency_key: str
    created_at: str = field(default_factory=now_iso)


@dataclass
class AuditEvent:
    audit_id: str
    event_type: str
    context: TenantContext
    target_type: str
    target_id: str
    outcome: str
    detail: dict[str, Any]
    previous_hash: str = ""
    event_hash: str = ""
    created_at: str = field(default_factory=now_iso)


@dataclass
class ExecutorResult:
    job_id: str
    attempt: int
    status: str
    input_spec_hash: str
    outputs: list[dict[str, Any]]
    errors: list[dict[str, Any]] = field(default_factory=list)
    callback_id: str = field(default_factory=lambda: new_id("callback"))

