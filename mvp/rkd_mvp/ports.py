from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .models import CommandEnvelope, ExecutorResult, TenantContext


class CommandStore(Protocol):
    def command_result(self, command: CommandEnvelope) -> dict[str, Any] | None: ...

    def record_command(self, command: CommandEnvelope, result: dict[str, Any]) -> None: ...


class WorkflowRuntime(Protocol):
    def start(self, context: TenantContext, workflow_type: str, input_revision: str) -> str: ...

    def signal(self, context: TenantContext, workflow_run_id: str, signal: str, payload: dict[str, Any]) -> None: ...

    def recover(self, context: TenantContext, workflow_run_id: str) -> None: ...


class ExecutorDispatcher(Protocol):
    def enqueue(self, context: TenantContext, kind: str, payload: dict[str, Any], idempotency_key: str) -> str: ...

    def accept_callback(self, context: TenantContext, result: ExecutorResult) -> bool: ...


@dataclass(frozen=True)
class ExternalActionPort:
    """Adapter boundary; unknown outcomes must be reconciled, never blindly retried."""

    action_kind: str

    def dispatch(self, context: TenantContext, action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def reconcile(self, context: TenantContext, action_id: str) -> dict[str, Any]:
        raise NotImplementedError

