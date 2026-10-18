from __future__ import annotations

from typing import Any

from .models import TenantContext, new_id, now_iso
from .store import AccessDenied, ConflictError, InMemoryStore


class DurableWorkflowRuntime:
    """Minimal durable state machine; production will replace storage/queue, not states."""

    TRANSITIONS = {
        "created": {"intake", "blocked", "failed", "superseded"},
        "intake": {"scanning", "blocked", "failed", "superseded"},
        "scanning": {"requirements", "blocked", "failed", "superseded"},
        "requirements": {"design-intent-review", "blocked", "failed", "superseded"},
        "design-intent-review": {"pending-g2", "blocked", "failed", "superseded"},
        "pending-g2": {"g2-approved", "blocked", "failed", "superseded"},
        "g2-approved": {"spatial-plan", "blocked", "failed", "superseded"},
        "spatial-plan": {"production-batch", "blocked", "failed", "superseded"},
        "production-batch": {"branch-processing", "blocked", "failed", "superseded"},
        "branch-processing": {"cross-check", "blocked", "failed", "superseded"},
        "cross-check": {"ready-for-review", "blocked", "failed", "superseded"},
        "ready-for-review": {"completed", "blocked", "failed", "superseded"},
        "blocked": {"intake", "requirements", "design-intent-review", "spatial-plan", "branch-processing", "failed", "superseded"},
        "failed": {"intake", "requirements", "design-intent-review", "spatial-plan", "branch-processing", "superseded"},
        "completed": set(),
        "superseded": set(),
    }

    def __init__(self, store: InMemoryStore) -> None:
        self.store = store

    def start(self, context: TenantContext, workflow_type: str, input_revision: str) -> str:
        self.store.require_project(context)
        run_id = new_id("workflow")
        self.store.workflow_runs[run_id] = {
            "workflow_run_id": run_id,
            "organization_id": context.organization_id,
            "project_id": context.project_id,
            "workflow_type": workflow_type,
            "workflow_version": "1",
            "status": "running",
            "current_state": "created",
            "input_revision": input_revision,
            "correlation_id": f"corr_{run_id}",
            "recovery_count": 0,
            "updated_at": now_iso(),
        }
        self._persist()
        return run_id

    def get(self, context: TenantContext, workflow_run_id: str) -> dict[str, Any]:
        run = self.store.workflow_runs.get(workflow_run_id)
        if not run or (run["organization_id"], run["project_id"]) != (
            context.organization_id, context.project_id
        ):
            raise AccessDenied("resource not found")
        return dict(run)

    def transition(self, context: TenantContext, workflow_run_id: str, next_state: str,
                   reason: str = "") -> dict[str, Any]:
        run = self.get(context, workflow_run_id)
        current = run["current_state"]
        if next_state not in self.TRANSITIONS.get(current, set()):
            raise ConflictError(f"invalid workflow transition: {current} -> {next_state}")
        run["current_state"] = next_state
        run["status"] = "completed" if next_state == "completed" else (
            "blocked" if next_state == "blocked" else "failed" if next_state == "failed" else "superseded" if next_state == "superseded" else "running"
        )
        run["last_reason"] = reason
        run["updated_at"] = now_iso()
        self.store.workflow_runs[workflow_run_id] = run
        self.store.append_audit(context, "workflow.transition", "WorkflowRun", workflow_run_id,
                                "succeeded", {"from": current, "to": next_state, "reason": reason})
        self._persist()
        return dict(run)

    def recover(self, context: TenantContext, workflow_run_id: str) -> dict[str, Any]:
        run = self.get(context, workflow_run_id)
        if run["status"] in {"completed", "superseded"}:
            raise ConflictError("terminal workflow cannot be recovered")
        run["recovery_count"] += 1
        run["updated_at"] = now_iso()
        self.store.workflow_runs[workflow_run_id] = run
        self.store.append_audit(context, "workflow.recovered", "WorkflowRun", workflow_run_id,
                                "succeeded", {"recovery_count": run["recovery_count"]})
        self._persist()
        return dict(run)

    def _persist(self) -> None:
        persist = getattr(self.store, "persist", None)
        if persist:
            persist()

