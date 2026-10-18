from __future__ import annotations

import hashlib
from typing import Any

from .adapters import SimulatedExecutor, SimulatedPublishAdapter
from .gateway import CommandGateway
from .models import CommandEnvelope, ExecutorResult, TenantContext, new_id
from .store import AccessDenied, ConflictError, InMemoryStore
from .workflow import DurableWorkflowRuntime
from .queue import QueueWorker


class MVPApp:
    def __init__(self, store: InMemoryStore | None = None) -> None:
        self.store = store or InMemoryStore()
        self.gateway = CommandGateway(self.store)
        self.executors = {
            "drawing": SimulatedExecutor("drawing-set"),
            "boq": SimulatedExecutor("boq"),
            "bim": SimulatedExecutor("bim-model"),
            "validation": SimulatedExecutor("validation-report"),
        }
        self.publisher = SimulatedPublishAdapter()
        self.workflow = DurableWorkflowRuntime(self.store)
        self.queue = QueueWorker(self.store)
        self._register_handlers()

    def _register_handlers(self) -> None:
        for name in (
            "CreateRequirementDraft", "CreateDesignBriefDraft", "SubmitBriefForReview",
            "ComposeDesignIntent", "SelectConceptOption", "ApproveDesignIntent",
            "CreateSpatialProgramDraft", "SelectOption", "CreateProductionBatch",
            "MarkDrawingReleaseCandidate", "CreateQuoteDraft", "QueueBIMBuildJob",
            "QueueDrawingJob", "QueueQuantityTakeoff", "QueueValidationJob",
        ):
            self.gateway.register(name, self._generic_handler)

    def context(self, actor_type: str = "human", organization_id: str = "org_demo",
                project_id: str = "project_demo", actor_id: str = "user_demo") -> TenantContext:
        return TenantContext(organization_id, project_id, actor_id, actor_type)

    def bootstrap(self, context: TenantContext) -> dict[str, str]:
        self.store.bootstrap_project(context, "Vertical MVP Demo")
        file_id = self.store.add_scanned_file(context, "site-plan.txt", b"synthetic-site-plan-v1")
        self.store.add_scanned_file(context, "material-list.csv", b"item,qty\nlight,4\n")
        return {"project_id": context.project_id, "source_file_id": file_id}

    def _generic_handler(self, command: CommandEnvelope) -> dict[str, Any]:
        event_type = {
            "CreateRequirementDraft": "requirement.draft-created",
            "CreateDesignBriefDraft": "brief.generated",
            "SubmitBriefForReview": "brief.review-requested",
            "ComposeDesignIntent": "design-intent.composed",
            "SelectConceptOption": "concept-option.selected",
            "ApproveDesignIntent": "design-intent.approved",
            "CreateSpatialProgramDraft": "spatial-program.started",
            "SelectOption": "spatial-option.selected",
            "CreateProductionBatch": "production-batch.created",
            "MarkDrawingReleaseCandidate": "drawing-set.release-candidate-created",
            "CreateQuoteDraft": "quote.draft-created",
            "QueueBIMBuildJob": "bim.generation-started",
            "QueueDrawingJob": "drawing-set.generated",
            "QueueQuantityTakeoff": "boq.quantity-takeoff-queued",
            "QueueValidationJob": "validation.queued",
        }[command.command_name]
        event = self.store.append_event(
            command.context, event_type, command.aggregate_id, dict(command.payload), command
        )
        return {"command_id": command.command_id, "event_id": event.event_id, "status": "accepted"}

    def command(self, context: TenantContext, name: str, aggregate_id: str,
                payload: dict[str, Any], key: str) -> dict[str, Any]:
        return self.gateway.submit(CommandEnvelope(
            command_id=new_id("cmd"), command_name=name, context=context,
            idempotency_key=key, aggregate_id=aggregate_id, payload=payload,
            correlation_id=f"corr_{context.project_id}",
        ))

    def run_executor(self, context: TenantContext, kind: str, payload: dict[str, Any], key: str) -> ExecutorResult:
        self.store.require_project(context)
        job_id = f"job_{context.organization_id}_{context.project_id}_{key}"
        input_spec_hash = hashlib.sha256(repr(sorted(payload.items())).encode()).hexdigest()
        inbox_key = (context.organization_id, context.project_id, job_id)
        if inbox_key in self.store.inbox:
            return self.store.jobs[job_id]["result"]
        self.store.inbox.add(inbox_key)
        result = self.executors[kind].run(job_id, input_spec_hash, payload)
        self.store.jobs[job_id] = {
            "job_id": job_id, "organization_id": context.organization_id,
            "project_id": context.project_id, "kind": kind, "result": result,
        }
        if result.status == "succeeded":
            for artifact in result.outputs:
                self.store.artifacts[artifact["artifact_id"]] = {
                    **artifact, "organization_id": context.organization_id,
                    "project_id": context.project_id,
                }
        self.store.append_audit(context, "executor.callback", "ExecutorJob", job_id, result.status,
                                {"kind": kind, "attempt": result.attempt})
        return result

    def publish(self, context: TenantContext, artifact_ids: list[str], action_key: str) -> dict[str, Any]:
        self.store.require_project(context)
        for artifact_id in artifact_ids:
            artifact = self.store.artifacts.get(artifact_id)
            if not artifact or (artifact["organization_id"], artifact["project_id"]) != (
                context.organization_id, context.project_id
            ):
                raise AccessDenied("resource not found")
        action_id = f"action_{action_key}"
        if action_id in self.store.external_actions:
            return self.store.external_actions[action_id]
        result = self.publisher.dispatch(action_id, artifact_ids)
        self.store.external_actions[action_id] = result
        self.store.append_audit(context, "external.publish", "ExternalAction", action_id,
                                result["status"], {"artifact_ids": artifact_ids})
        return result

    def run_happy_path(self, context: TenantContext) -> dict[str, Any]:
        self.store.require_project(context)
        workflow_id = self.workflow.start(context, "vertical-mvp", "baseline-synthetic-v1")

        def advance(state: str, reason: str = "") -> None:
            self.workflow.transition(context, workflow_id, state, reason)

        try:
            advance("intake", "project and source scope accepted")
            advance("scanning", "synthetic source files are already scanned")
            self.command(context, "CreateRequirementDraft", "requirement_demo",
                          {"source": "synthetic-fixture", "goal": "quiet collaborative studio"}, "req-1")
            self.command(context, "CreateDesignBriefDraft", "brief_demo",
                          {"requirement_id": "requirement_demo"}, "brief-1")
            self.command(context, "SubmitBriefForReview", "brief_demo", {}, "brief-review-1")
            advance("requirements", "brief review request accepted")
            self.command(context, "SelectConceptOption", "concept_demo", {"option": "A"}, "concept-1")
            self.command(context, "ComposeDesignIntent", "intent_demo", {"concept_option_id": "concept_demo"}, "intent-1")
            advance("design-intent-review", "DesignIntent composed")
            advance("pending-g2", "awaiting human G2 approval")
            self.command(context, "ApproveDesignIntent", "intent_demo", {"approval": "G2"}, "g2-1")
            advance("g2-approved", "human G2 approval recorded")
            self.command(context, "CreateSpatialProgramDraft", "spatial_program_demo", {"area_m2": 42}, "spatial-1")
            self.command(context, "SelectOption", "spatial_option_demo", {"option": "deterministic-seed-1"}, "spatial-select-1")
            advance("spatial-plan", "spatial option selected")
            self.command(context, "QueueBIMBuildJob", "bim_job_demo",
                         {"intent": "intent_demo", "spatial": "spatial_option_demo"}, "bim-queue-1")
            bim = self.run_executor(context, "bim", {"intent": "intent_demo", "spatial": "spatial_option_demo"}, "bim-1")
            if bim.status != "succeeded":
                raise ConflictError(f"BIM branch failed: {bim.status}")
            self.command(context, "CreateProductionBatch", "batch_demo", {"bim_job": bim.job_id}, "batch-1")
            advance("production-batch", "BIM manifest accepted")
            advance("branch-processing", "drawing and BOQ branches queued")
            self.command(context, "QueueDrawingJob", "drawing_job_demo",
                         {"batch": "batch_demo", "bim_job": bim.job_id}, "drawing-queue-1")
            self.command(context, "QueueQuantityTakeoff", "boq_job_demo",
                         {"batch": "batch_demo", "bim_job": bim.job_id}, "boq-queue-1")
            drawing = self.run_executor(context, "drawing", {"batch": "batch_demo", "bim_job": bim.job_id}, "drawing-1")
            boq = self.run_executor(context, "boq", {"batch": "batch_demo", "bim_job": bim.job_id}, "boq-1")
            self.command(context, "QueueValidationJob", "validation_job_demo",
                         {"batch": "batch_demo", "drawing": drawing.status, "boq": boq.status}, "validation-queue-1")
            validation = self.run_executor(context, "validation", {
                "batch": "batch_demo", "drawing": drawing.status, "boq": boq.status,
            }, "validation-1")
            if any(result.status != "succeeded" for result in (drawing, boq, validation)):
                raise ConflictError("one or more production branches failed quality gates")
            advance("cross-check", "EX-14 validation branch succeeded")
            artifact_ids = [a["artifact_id"] for r in (drawing, boq, validation) for a in r.outputs]
            self.command(context, "MarkDrawingReleaseCandidate", "drawing_demo", {"artifact_ids": artifact_ids}, "drawing-release-1")
            self.command(context, "CreateQuoteDraft", "quote_demo", {"boq_job": boq.job_id}, "quote-1")
            advance("ready-for-review", "drawing and quote drafts are ready")
            publish = self.publish(context, artifact_ids, "publish-1")
            if publish["status"] == "confirmed":
                advance("completed", "simulated publish confirmed")
            else:
                advance("blocked", f"simulated publish status: {publish['status']}")
            queue_result = self.queue.drain_outbox(context, lambda event: None)
            workflow_status = self.workflow.get(context, workflow_id)
            return {"drawing": drawing.status, "boq": boq.status, "validation": validation.status,
                    "artifact_ids": artifact_ids, "publish": publish["status"],
                    "workflow_run_id": workflow_id, "workflow_state": workflow_status["current_state"],
                    "outbox_published": queue_result["published"]}
        except Exception as error:
            current = self.workflow.get(context, workflow_id)["current_state"]
            if current not in {"completed", "failed", "superseded"}:
                self.workflow.transition(context, workflow_id, "failed", str(error))
            raise
