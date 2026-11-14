from __future__ import annotations

from pathlib import Path
from typing import Any

from .engine import MVPApp
from .ai_development_repository import SQLiteAIDevelopmentRepository
from .ai_development_service import AIDevelopmentService, AIDevelopmentServiceError
from .ai_design_option_repository import SQLiteAIDesignOptionRepository
from .ai_design_option_service import AIDesignOptionService, AIDesignOptionServiceError
from .ai_requirement_repository import SQLiteAIRequirementRepository
from .ai_requirement_service import AIRequirementService, AIRequirementServiceError
from .professional_delivery import (AIProfessionalDeliveryError, AISourceExtractionService,
                                    AITechnicalDeliveryService,
                                    SQLiteAIProfessionalDeliveryRepository)
from .estimate_service import EstimateService, EstimateServiceError
from .models import TenantContext, new_id
from .store import AccessDenied, ConflictError
from .task_service import TaskService, TaskServiceError
from .spatial_service import SpatialService, SpatialServiceError
from .requirement_service import RequirementService, RequirementServiceError
from .design_service import DesignService
from .production_service import ProductionService
from .design_rules import DesignError
from .procurement_service import ProcurementService, ProcurementServiceError
from .change_service import ChangeService, ChangeServiceError
from .project_inputs import project_name, project_version


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


class ApiService:
    """HTTP-independent API application service used by the local server and tests."""

    def __init__(self, app: MVPApp | None = None, file_service: Any | None = None,
                 task_service: TaskService | None = None,
                 estimate_service: EstimateService | None = None,
                 spatial_service: SpatialService | None = None,
                 requirement_service: RequirementService | None = None,
                 procurement_service: ProcurementService | None = None,
                 change_service: ChangeService | None = None,
                 ai_requirement_service: AIRequirementService | None = None,
                 ai_design_option_service: AIDesignOptionService | None = None,
                 ai_development_service: AIDevelopmentService | None = None,
                 ai_source_extraction_service: AISourceExtractionService | None = None,
                 ai_technical_delivery_service: AITechnicalDeliveryService | None = None,
                 runtime_root: str | Path | None = None,
                 studio_source: Any | None = None) -> None:
        self.app = app or MVPApp()
        self.file_service = file_service
        db_path = getattr(self.app.store, "db_path", None)
        self.task_service = task_service or (TaskService(db_path) if db_path else None)
        self.estimate_service = estimate_service or (EstimateService(db_path) if db_path else None)
        self.spatial_service = spatial_service or (SpatialService(db_path) if db_path else None)
        self.requirement_service = requirement_service or (RequirementService(db_path) if db_path else None)
        self.design_service = DesignService(db_path) if db_path else None
        self.production_service = ProductionService(db_path) if db_path else None
        self.procurement_service = procurement_service or (ProcurementService(db_path) if db_path else None)
        self.change_service = change_service or (ChangeService(db_path) if db_path else None)
        self.ai_source_extraction_service = ai_source_extraction_service or (
            AISourceExtractionService(SQLiteAIProfessionalDeliveryRepository(db_path), self.file_service)
            if db_path else None
        )
        self.ai_requirement_service = ai_requirement_service or (
            AIRequirementService(SQLiteAIRequirementRepository(db_path), self.requirement_service,
                                 extraction_service=self.ai_source_extraction_service)
            if db_path and self.requirement_service else None
        )

        def ai_brief_provider(org: str, project: str) -> dict[str, Any] | None:
            if self.ai_requirement_service is None:
                return None
            return self.ai_requirement_service.status(org, project)["item"]

        def ai_design_context_provider(org: str, project: str) -> dict[str, Any]:
            context: dict[str, Any] = {"width": "12", "length": "8",
                                       "boundary_source": "test_parameters_not_site_verified", "obstacles": []}
            if self.requirement_service is not None:
                requirement = self.requirement_service.get_current(org, project)
                program = requirement.get("content", {}).get("design_program") if requirement else None
                if isinstance(program, dict):
                    context.update({"width": program.get("width", context["width"]),
                                    "length": program.get("length", context["length"]),
                                    "boundary_source": program.get("boundary_source", context["boundary_source"])})
            return context

        root = Path(runtime_root) if runtime_root else (Path(db_path).parent if db_path else None)
        self.ai_design_option_service = ai_design_option_service or (
            AIDesignOptionService(SQLiteAIDesignOptionRepository(db_path), ai_brief_provider,
                                  ai_design_context_provider, root,
                                  studio_source=studio_source)
            if db_path and self.ai_requirement_service and root else None
        )
        self.ai_development_service = ai_development_service or (
            AIDevelopmentService(SQLiteAIDevelopmentRepository(db_path),
                                 self.ai_design_option_service, root)
            if db_path and self.ai_design_option_service and root else None
        )
        self.ai_technical_delivery_service = ai_technical_delivery_service or (
            AITechnicalDeliveryService(SQLiteAIProfessionalDeliveryRepository(db_path),
                                       self.ai_development_service,
                                       self.ai_source_extraction_service, root)
            if db_path and self.ai_development_service and root else None
        )

    def _files(self) -> Any:
        if self.file_service is None:
            raise ApiError(501, "FILES_NOT_CONFIGURED", "local file storage is not configured")
        return self.file_service

    @staticmethod
    def _context(organization_id: str, project_id: str, actor_id: str = "local-user") -> TenantContext:
        return TenantContext(organization_id, project_id, actor_id, "human")

    def _require_project(self, organization_id: str, project_id: str) -> TenantContext:
        context = self._context(organization_id, project_id)
        try:
            self.app.store.require_project(context)
        except AccessDenied as error:
            raise ApiError(404, "NOT_FOUND", "resource not found") from error
        return context

    def list_projects(self, organization_id: str) -> dict[str, Any]:
        items = [
            dict(project) for (org_id, _), project in self.app.store.projects.items()
            if org_id == organization_id
        ]
        items.sort(key=lambda project: (project.get("name", ""), project["project_id"]))
        return {"items": items, "next_cursor": None}

    def create_project(self, organization_id: str, name: str, project_id: str | None = None, *, actor_id: str = "local-user") -> dict[str, Any]:
        try:
            name = project_name(name)
        except ValueError as error:
            raise ApiError(400, "INVALID_PROJECT", str(error)) from error
        project_id = project_id or new_id("project")
        context = self._context(organization_id, project_id, actor_id)
        if (organization_id, project_id) in self.app.store.projects:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "project already exists")
        self.app.store.bootstrap_project(context, name)
        return dict(self.app.store.projects[(organization_id, project_id)])

    def get_project(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return dict(self.app.store.projects[(organization_id, project_id)])

    def update_project(self, organization_id: str, project_id: str, request: dict[str, Any], *, actor_id: str = "local-user") -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        context = self._context(organization_id, project_id, actor_id)
        try:
            name = project_name(request.get("name"))
            expected_version = project_version(request.get("expected_version"))
        except ValueError as error:
            raise ApiError(400, "INVALID_PROJECT", str(error)) from error
        project = self.app.store.projects[(organization_id, project_id)]
        current_version = int(project.get("version", 0))
        if expected_version != current_version:
            raise ApiError(409, "STALE_PROJECT_VERSION", "project version is stale")
        with self.app.store.transaction():
            project["name"] = name
            project["version"] = current_version + 1
            self.app.store.append_audit(
                context,
                "project.updated",
                "Project",
                project_id,
                "succeeded",
                {"version": project["version"]},
            )
            self.app.store.persist()
        return dict(project)

    def initiate_upload(self, organization_id: str, project_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._files().initiate(organization_id, project_id, request)

    def receive_upload(self, organization_id: str, project_id: str, upload_id: str,
                       stream: Any, content_length: int) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._files().receive(organization_id, project_id, upload_id, stream, content_length)

    def complete_upload(self, organization_id: str, project_id: str, upload_id: str,
                        completed_sha256: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._files().complete(organization_id, project_id, upload_id, completed_sha256)

    def list_files(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._files().list_files(organization_id, project_id)

    def get_file_content(self, organization_id: str, project_id: str, file_id: str) -> tuple[dict[str, Any], Any]:
        self._require_project(organization_id, project_id)
        return self._files().get_content(organization_id, project_id, file_id)

    def list_decisions(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._files().list_decisions(organization_id, project_id)

    def _tasks(self) -> TaskService:
        if self.task_service is None:
            raise ApiError(501, "TASKS_NOT_CONFIGURED", "local task storage is not configured")
        return self.task_service

    def list_issues(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._tasks().list_issues(organization_id, project_id)

    def get_issue(self, organization_id: str, project_id: str, issue_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._tasks().get_issue(organization_id, project_id, issue_id)
        except TaskServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def record_issue_disposition(self, organization_id: str, project_id: str, issue_id: str,
                                 request: dict[str, Any], actor_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._tasks().record_disposition(organization_id, project_id, issue_id, request, actor_id)
        except TaskServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def list_jobs(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._tasks().list_jobs(organization_id, project_id)

    def retry_job(self, organization_id: str, project_id: str, job_id: str, fixture_root: Any | None = None) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            root = fixture_root or self._tasks().fixture_root
            if root is None:
                raise TaskServiceError(501, "TASK_FIXTURE_NOT_CONFIGURED", "task input source is not configured")
            return self._tasks().retry_job(organization_id, project_id, job_id, root)
        except TaskServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def cancel_job(self, organization_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._tasks().cancel_job(organization_id, project_id, job_id)
        except TaskServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def _estimates(self) -> EstimateService:
        if self.estimate_service is None:
            raise ApiError(501, "ESTIMATES_NOT_CONFIGURED", "local estimate storage is not configured")
        return self.estimate_service

    def list_estimates(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._estimates().list_estimates(organization_id, project_id)

    def get_estimate(self, organization_id: str, project_id: str, estimate_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._estimates().get_estimate(organization_id, project_id, estimate_id)
        except EstimateServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def update_estimate_line(self, organization_id: str, project_id: str, estimate_id: str,
                             line_id: str, request: dict[str, Any], actor_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._estimates().update_line(
                organization_id, project_id, estimate_id, line_id, request, actor_id,
            )
        except EstimateServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def calculate_estimate(self, organization_id: str, project_id: str, estimate_id: str,
                           request: dict[str, Any], actor_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._estimates().calculate(
                organization_id, project_id, estimate_id, request, actor_id,
            )
        except EstimateServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def export_estimate(self, organization_id: str, project_id: str, estimate_id: str, actor_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._estimates().export_estimate(organization_id, project_id, estimate_id, actor_id)
        except EstimateServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_estimate_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict[str, Any], Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._estimates().get_artifact(organization_id, project_id, artifact_id)
        except EstimateServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_spatial_model(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        if self.spatial_service is None:
            raise ApiError(501, "SPATIAL_NOT_CONFIGURED", "local spatial storage is not configured")
        return self.spatial_service.get_model(organization_id, project_id)

    def get_requirement(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        if self.requirement_service is None:
            raise ApiError(501, "REQUIREMENTS_NOT_CONFIGURED", "requirement storage is not configured")
        current = self.requirement_service.get_current(organization_id, project_id)
        return {"item": current}

    def update_requirement(self, organization_id: str, project_id: str, actor_id: str, request: dict) -> dict:
        self._require_project(organization_id, project_id)
        if self.requirement_service is None:
            raise ApiError(501, "REQUIREMENTS_NOT_CONFIGURED", "requirement storage is not configured")
        try:
            return {"item": self.requirement_service.update_draft(organization_id, project_id, actor_id, request)}
        except RequirementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def _ai(self) -> AIRequirementService:
        if self.ai_requirement_service is None:
            raise ApiError(501, "AI_REQUIREMENT_NOT_CONFIGURED", "AI 需求理解服务未配置")
        return self.ai_requirement_service

    def get_ai_requirement_status(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai().status(organization_id, project_id)
        except AIRequirementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def submit_ai_requirement(self, organization_id: str, project_id: str, actor_id: str,
                              request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai().submit(organization_id, project_id, actor_id, request, idempotency_key)
        except AIRequirementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_ai_requirement_job(self, organization_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai().get_job(organization_id, project_id, job_id)
        except AIRequirementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def retry_ai_requirement_job(self, organization_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai().retry(organization_id, project_id, job_id)
        except AIRequirementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def cancel_ai_requirement_job(self, organization_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai().cancel(organization_id, project_id, job_id)
        except AIRequirementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def save_ai_requirement_brief(self, organization_id: str, project_id: str, actor_id: str,
                                  request: dict[str, Any]) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai().save_brief(organization_id, project_id, actor_id, request)
        except AIRequirementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def _ai_options(self) -> AIDesignOptionService:
        if self.ai_design_option_service is None:
            raise ApiError(501, "AI_DESIGN_OPTIONS_NOT_CONFIGURED", "AI 设计候选服务未配置")
        return self.ai_design_option_service

    def get_ai_design_options(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._ai_options().status(organization_id, project_id)

    def submit_ai_design_options(self, organization_id: str, project_id: str, actor_id: str,
                                 request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_options().submit(organization_id, project_id, actor_id, request, idempotency_key)
        except AIDesignOptionServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def revise_ai_design_option(self, organization_id: str, project_id: str, actor_id: str,
                                request: dict[str, Any]) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_options().revise(organization_id, project_id, actor_id, request)
        except AIDesignOptionServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def adopt_ai_design_option(self, organization_id: str, project_id: str, actor_id: str,
                               request: dict[str, Any]) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_options().adopt(organization_id, project_id, actor_id, request)
        except AIDesignOptionServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def cancel_ai_design_option_set(self, organization_id: str, project_id: str, set_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_options().cancel(organization_id, project_id, set_id)
        except AIDesignOptionServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_ai_design_studio_sources(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._ai_options().studio_sources(organization_id, project_id)

    def import_ai_design_studio_proposal(self, organization_id: str, project_id: str,
                                         actor_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_options().import_studio_proposal(
                organization_id, project_id, actor_id, request)
        except AIDesignOptionServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error
        except Exception as error:  # noqa: BLE001 - surface a failed import, never half a write
            raise ApiError(500, "STUDIO_IMPORT_FAILED",
                           f"导入事务失败已回滚：{type(error).__name__}: {error}") from error

    def list_ai_design_studio_imports(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._ai_options().list_studio_imports(organization_id, project_id)

    def get_ai_design_studio_import_detail(self, organization_id: str, project_id: str,
                                           option_revision_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_options().studio_import_detail(
                organization_id, project_id, option_revision_id)
        except AIDesignOptionServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_ai_design_option_artifact(self, organization_id: str, project_id: str,
                                      artifact_id: str) -> tuple[dict[str, Any], Path]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_options().get_artifact(organization_id, project_id, artifact_id)
        except AIDesignOptionServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def _ai_development(self) -> AIDevelopmentService:
        if self.ai_development_service is None:
            raise ApiError(501, "AI_DEVELOPMENT_NOT_CONFIGURED", "AI 深化量价服务未配置")
        return self.ai_development_service

    def get_ai_development(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._ai_development().status(organization_id, project_id)

    def submit_ai_development(self, organization_id: str, project_id: str, actor_id: str,
                              request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_development().submit(organization_id, project_id, actor_id,
                                                 request, idempotency_key)
        except AIDevelopmentServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_ai_development_artifact(self, organization_id: str, project_id: str,
                                    artifact_id: str) -> tuple[dict[str, Any], Path]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_development().get_artifact(organization_id, project_id, artifact_id)
        except AIDevelopmentServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def _ai_sources(self) -> AISourceExtractionService:
        if self.ai_source_extraction_service is None:
            raise ApiError(501, "SOURCE_EXTRACTION_NOT_CONFIGURED", "原件内容解析服务未配置")
        return self.ai_source_extraction_service

    def get_ai_source_extractions(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_sources().list_extractions(organization_id, project_id)
        except AIProfessionalDeliveryError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def submit_ai_source_extraction(self, organization_id: str, project_id: str,
                                    request: dict[str, Any]) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_sources().extract(organization_id, project_id, request.get("file_id"))
        except AIProfessionalDeliveryError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def _ai_technical_delivery(self) -> AITechnicalDeliveryService:
        if self.ai_technical_delivery_service is None:
            raise ApiError(501, "TECHNICAL_DELIVERY_NOT_CONFIGURED", "技术交付服务未配置")
        return self.ai_technical_delivery_service

    def get_ai_technical_delivery(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_technical_delivery().status(organization_id, project_id)
        except AIProfessionalDeliveryError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def submit_ai_technical_delivery(self, organization_id: str, project_id: str, actor_id: str,
                                     request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_technical_delivery().submit(organization_id, project_id, actor_id,
                                                        request, idempotency_key)
        except AIProfessionalDeliveryError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_ai_technical_delivery_artifact(self, organization_id: str, project_id: str,
                                           artifact_id: str) -> tuple[dict[str, Any], Path]:
        self._require_project(organization_id, project_id)
        try:
            return self._ai_technical_delivery().get_artifact(organization_id, project_id, artifact_id)
        except AIProfessionalDeliveryError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_design(self, organization_id: str, project_id: str, revision_no: int | None = None) -> dict:
        self._require_project(organization_id, project_id)
        if self.design_service is None:
            raise ApiError(501, "DESIGN_NOT_CONFIGURED", "design storage is not configured")
        try:
            return self.design_service.get_design(organization_id, project_id, revision_no)
        except DesignError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_production(self, organization_id: str, project_id: str, revision_no: int | None = None) -> dict:
        self._require_project(organization_id, project_id)
        if self.production_service is None:
            raise ApiError(501, "PRODUCTION_NOT_CONFIGURED", "production storage is not configured")
        try:
            return self.production_service.get(organization_id, project_id, revision_no)
        except DesignError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def save_production_settings(self, organization_id: str, project_id: str, actor_id: str, request: dict) -> dict:
        self._require_project(organization_id, project_id)
        if self.production_service is None:
            raise ApiError(501, "PRODUCTION_NOT_CONFIGURED", "production storage is not configured")
        try:
            return self.production_service.save_settings(organization_id, project_id, actor_id, request)
        except (DesignError, ProcurementServiceError) as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_production_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict, Any]:
        self._require_project(organization_id, project_id)
        if self.production_service is None:
            raise ApiError(501, "PRODUCTION_NOT_CONFIGURED", "production storage is not configured")
        try:
            return self.production_service.get_artifact(organization_id, project_id, artifact_id)
        except DesignError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def create_design(self, organization_id: str, project_id: str, actor_id: str, request: dict) -> dict:
        self._require_project(organization_id, project_id)
        if self.design_service is None:
            raise ApiError(501, "DESIGN_NOT_CONFIGURED", "design storage is not configured")
        try:
            return {"item": self.design_service.create_design(organization_id, project_id, actor_id, request)}
        except DesignError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_design_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict, Any]:
        self._require_project(organization_id, project_id)
        if self.design_service is None:
            raise ApiError(501, "DESIGN_NOT_CONFIGURED", "design storage is not configured")
        try:
            return self.design_service.get_artifact(organization_id, project_id, artifact_id)
        except DesignError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def _procurement(self) -> ProcurementService:
        if self.procurement_service is None:
            raise ApiError(501, "PROCUREMENT_NOT_CONFIGURED", "local procurement storage is not configured")
        return self.procurement_service

    def list_procurement_orders(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._procurement().list_orders(organization_id, project_id)

    def get_procurement_order(self, organization_id: str, project_id: str, order_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._procurement().get_order(organization_id, project_id, order_id)
        except ProcurementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def create_procurement_order(self, organization_id: str, project_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._procurement().create_order(organization_id, project_id, actor_id, request, idempotency_key)
        except ProcurementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def receive_procurement(self, organization_id: str, project_id: str, order_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._procurement().receive(organization_id, project_id, order_id, actor_id, request, idempotency_key)
        except ProcurementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def allocate_procurement(self, organization_id: str, project_id: str, order_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._procurement().allocate(organization_id, project_id, order_id, actor_id, request, idempotency_key)
        except ProcurementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def _changes(self) -> ChangeService:
        if self.change_service is None:
            raise ApiError(501, "CHANGES_NOT_CONFIGURED", "local change storage is not configured")
        return self.change_service

    def list_changes(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        return self._changes().list_changes(organization_id, project_id)

    def get_change(self, organization_id: str, project_id: str, change_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._changes().get_change(organization_id, project_id, change_id)
        except ChangeServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def create_change(self, organization_id: str, project_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._changes().create_change(organization_id, project_id, actor_id, request, idempotency_key)
        except ChangeServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def analyze_change(self, organization_id: str, project_id: str, change_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._changes().analyze_change(organization_id, project_id, change_id, actor_id, request, idempotency_key)
        except ChangeServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def accept_change(self, organization_id: str, project_id: str, change_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._changes().accept_change(organization_id, project_id, change_id, actor_id, request, idempotency_key)
        except ChangeServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def reproduce_change(self, organization_id, project_id, change_id, actor_id, request, idempotency_key):
        self._require_project(organization_id, project_id)
        try:
            return self._changes().reproduce(organization_id, project_id, change_id, actor_id, request, idempotency_key)
        except ChangeServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def get_change_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict[str, Any], Any]:
        self._require_project(organization_id, project_id)
        try:
            return self._changes().get_artifact(organization_id, project_id, artifact_id)
        except ChangeServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def create_requirement_draft(self, organization_id: str, project_id: str, actor_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        if self.requirement_service is None:
            raise ApiError(501, "REQUIREMENTS_NOT_CONFIGURED", "requirement storage is not configured")
        try:
            return {"item": self.requirement_service.create_draft(organization_id, project_id, actor_id, str(request.get("change_reason") or "从项目证据生成需求草稿"))}
        except RequirementServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def create_spatial_revision(self, organization_id: str, project_id: str,
                                request: dict[str, Any], actor_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        if self.spatial_service is None:
            raise ApiError(501, "SPATIAL_NOT_CONFIGURED", "local spatial storage is not configured")
        try:
            return self.spatial_service.create_revision(organization_id, project_id, request, actor_id)
        except SpatialServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def list_spatial_artifacts(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._require_project(organization_id, project_id)
        if self.spatial_service is None:
            raise ApiError(501, "SPATIAL_NOT_CONFIGURED", "local spatial storage is not configured")
        return self.spatial_service.list_artifacts(organization_id, project_id)

    def get_spatial_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict[str, Any], Any]:
        self._require_project(organization_id, project_id)
        if self.spatial_service is None:
            raise ApiError(501, "SPATIAL_NOT_CONFIGURED", "local spatial storage is not configured")
        try:
            return self.spatial_service.get_artifact(organization_id, project_id, artifact_id)
        except SpatialServiceError as error:
            raise ApiError(error.status, error.code, error.message) from error

    def submit_command(self, organization_id: str, project_id: str, actor_id: str,
                       request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        context = self._context(organization_id, project_id, actor_id)
        self._require_project(organization_id, project_id)
        if len(idempotency_key) < 16:
            raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must contain at least 16 characters")
        command_type = request.get("command_type")
        target_id = request.get("target_id")
        if not command_type or not target_id or not isinstance(request.get("payload", {}), dict):
            raise ApiError(400, "INVALID_COMMAND", "command_type, target_id and object payload are required")
        cached = self.app.store.commands.get((organization_id, project_id, idempotency_key))
        if cached:
            return {"command_id": cached["command_id"], "status": "duplicate", "workflow_run_id": None}
        aggregate = self.app.store.get_aggregate(context, target_id) or {"version": 0}
        expected_version = int(request.get("expected_version", 0))
        if int(aggregate.get("version", 0)) != expected_version:
            raise ApiError(409, "STALE_TARGET_VERSION", "target version is stale")
        try:
            result = self.app.command(context, command_type, target_id, request["payload"], idempotency_key)
        except AccessDenied as error:
            raise ApiError(403, "COMMAND_NOT_ALLOWED", str(error)) from error
        except ConflictError as error:
            raise ApiError(409, "COMMAND_NOT_REGISTERED", str(error)) from error
        return {"command_id": result["command_id"], "status": "accepted", "workflow_run_id": None}

    def get_command(self, organization_id: str, project_id: str, command_id: str) -> dict[str, Any]:
        for (org_id, project_key, _), result in self.app.store.commands.items():
            if (org_id, project_key) == (organization_id, project_id) and result.get("command_id") == command_id:
                return {"command_id": command_id, "command_type": result.get("command_name", "registered"), "status": result.get("status", "accepted"), "result": result}
        raise ApiError(404, "NOT_FOUND", "resource not found")

    def get_workflow(self, organization_id: str, project_id: str, workflow_run_id: str) -> dict[str, Any]:
        try:
            return self.app.workflow.get(self._context(organization_id, project_id), workflow_run_id)
        except AccessDenied as error:
            raise ApiError(404, "NOT_FOUND", str(error)) from error

    def get_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> dict[str, Any]:
        artifact = self.app.store.artifacts.get(artifact_id)
        if not artifact or (artifact["organization_id"], artifact["project_id"]) != (organization_id, project_id):
            raise ApiError(404, "NOT_FOUND", "resource not found")
        return {"artifact_id": artifact_id, "kind": artifact.get("kind", "unknown"), "status": "validated", "source_revision": artifact.get("input_spec_hash", ""), "download_url": None}
