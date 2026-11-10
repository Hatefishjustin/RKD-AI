"""PostgreSQL business API slices. No SQLite object or fallback exists.

Only explicitly connected business routes are exposed; other domains return 501.
The launcher supports local accounts; network team deployment is separate.
"""
import re
from types import SimpleNamespace

from .ai_development_repository import PostgresAIDevelopmentRepository
from .ai_development_service import AIDevelopmentService
from .ai_design_option_repository import PostgresAIDesignOptionRepository
from .ai_design_option_service import AIDesignOptionService
from .ai_requirement_repository import PostgresAIRequirementRepository
from .ai_requirement_service import AIRequirementService
from .api_service import ApiError, ApiService
from .professional_delivery import (AISourceExtractionService, AITechnicalDeliveryService,
                                    PostgresAIProfessionalDeliveryRepository)
from .file_repository import PostgresFileRepository, mapping
from .file_service import FileService
from .models import CommandEnvelope, new_id
from .postgres_repository import PostgresRepository
from .project_inputs import project_name, project_version
from .requirement_service import RequirementService
from .requirement_repository import PostgresRequirementRepository
from .procurement_service import ProcurementService
from .procurement_repository import PostgresProcurementRepository
from .model_repository import PostgresModelRepository
from .design_service import DesignService
from .production_service import ProductionService
from .change_service import ChangeService
from .change_repository import PostgresChangeRepository
from .task_repository import PostgresTaskRepository
from .task_service import TaskService
from .estimate_service import EstimateService
from .estimate_repository import PostgresEstimateRepository
from .spatial_service import SpatialService
from .spatial_repository import PostgresSpatialRepository


def public_project(row):
    return {key: value.isoformat() if hasattr(value, "isoformat") else value for key, value in row.items()}


class PostgresApiService(ApiService):
    runtime_info = {"backend": "postgresql", "scope": "business-pilot", "team_ready": False,
                    "capabilities": ["projects", "files", "decisions", "requirements", "design", "production", "procurement", "changes", "jobs", "issues", "estimates", "spatial", "ai_requirement_understanding", "ai_design_options", "ai_development_production", "ai_source_extractions", "ai_technical_delivery"]}

    def __init__(self, store, runtime_root):
        # Deliberately no MVPApp: its legacy simulated command gateway is not
        # a PostgreSQL business implementation.
        self.app = SimpleNamespace(store=store)
        self.repository = PostgresRepository(store)
        self.file_service = FileService(None, runtime_root, repository=PostgresFileRepository(store))
        self.requirement_service = RequirementService(None, repository=PostgresRequirementRepository(store))
        self.procurement_service = ProcurementService(None, repository=PostgresProcurementRepository(store))
        model_repository = PostgresModelRepository(store)
        self.design_service = DesignService(None, repository=model_repository, runtime_root=runtime_root)
        self.production_service = ProductionService(None, repository=model_repository, runtime_root=runtime_root)
        self.change_service = ChangeService(None, repository=PostgresChangeRepository(store), runtime_root=runtime_root, model_repository=model_repository)
        self.task_service = TaskService(None, repository=PostgresTaskRepository(store))
        self.estimate_service = EstimateService(None, repository=PostgresEstimateRepository(store), runtime_root=runtime_root)
        self.spatial_service = SpatialService(None, repository=PostgresSpatialRepository(store), runtime_root=runtime_root)
        self.ai_source_extraction_service = AISourceExtractionService(
            PostgresAIProfessionalDeliveryRepository(store), self.file_service)
        self.ai_requirement_service = AIRequirementService(
            PostgresAIRequirementRepository(store), self.requirement_service,
            extraction_service=self.ai_source_extraction_service,
        )

        def brief_provider(org, project):
            return self.ai_requirement_service.status(org, project)["item"]

        def context_provider(org, project):
            context = {"width": "12", "length": "8", "boundary_source": "test_parameters_not_site_verified",
                       "obstacles": []}
            requirement = self.requirement_service.get_current(org, project)
            program = requirement.get("content", {}).get("design_program") if requirement else None
            if isinstance(program, dict):
                context.update({"width": program.get("width", context["width"]),
                                "length": program.get("length", context["length"]),
                                "boundary_source": program.get("boundary_source", context["boundary_source"])})
            return context

        self.ai_design_option_service = AIDesignOptionService(
            PostgresAIDesignOptionRepository(store), brief_provider, context_provider, runtime_root,
        )
        self.ai_development_service = AIDevelopmentService(
            PostgresAIDevelopmentRepository(store), self.ai_design_option_service, runtime_root,
        )
        self.ai_technical_delivery_service = AITechnicalDeliveryService(
            PostgresAIProfessionalDeliveryRepository(store), self.ai_development_service,
            self.ai_source_extraction_service, runtime_root,
        )

    def validate_route(self, method, path):
        if not path.startswith("/api/") and method == "GET":
            return
        if ((method == "GET" and path in {"/api/v1/auth/session", "/api/v1/auth/users", "/api/v1/operations/status", "/api/v1/auth/review-positions"})
            or (method == 'PATCH' and re.fullmatch(r'/api/v1/auth/review-positions/[^/]+',path))
            or (method == "POST" and path in {"/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/users"})
            or (method == "PATCH" and re.fullmatch(r"/api/v1/auth/users/[^/]+", path))
            or (method in {"GET", "POST"} and re.fullmatch(r"/api/v1/projects/[^/]+/members", path))):
            return
        if path in {"/api/health/live", "/api/health/ready", "/api/v1/auth/config"} and method == "GET":
            return
        patterns = {
            "GET": (r"/api/v1/projects", r"/api/v1/projects/[^/]+", r"/api/v1/projects/[^/]+/review-readiness", r"/api/v1/projects/[^/]+/review-tasks", r"/api/v1/projects/[^/]+/review-tasks/[^/]+/evidence",
                    r"/api/v1/projects/[^/]+/(?:files|decisions|requirements)", r"/api/v1/projects/[^/]+/files/[^/]+/content",
                    r"/api/v1/projects/[^/]+/procurement/orders(?:/[^/]+)?",
                    r"/api/v1/projects/[^/]+/(?:design|production)(?:/revisions/\d+)?",
                    r"/api/v1/projects/[^/]+/(?:design|production|changes)/artifacts/[^/]+/content",
                    r"/api/v1/projects/[^/]+/changes(?:/[^/]+)?", r"/api/v1/projects/[^/]+/jobs", r"/api/v1/projects/[^/]+/issues(?:/[^/]+)?",
                    r"/api/v1/projects/[^/]+/estimates(?:/[^/]+)?", r"/api/v1/projects/[^/]+/estimates/artifacts/[^/]+/content",
                    r"/api/v1/projects/[^/]+/spatial(?:/artifacts)?", r"/api/v1/projects/[^/]+/spatial/artifacts/[^/]+/content",
                    r"/api/v1/projects/[^/]+/ai/requirement-understanding",
                    r"/api/v1/projects/[^/]+/ai/requirement-understanding/jobs/[^/]+",
                    r"/api/v1/projects/[^/]+/ai/design-options",
                    r"/api/v1/projects/[^/]+/ai/design-options/artifacts/[^/]+/content",
                    r"/api/v1/projects/[^/]+/ai/development-production",
                    r"/api/v1/projects/[^/]+/ai/development-production/artifacts/[^/]+/content",
                    r"/api/v1/projects/[^/]+/ai/source-extractions",
                    r"/api/v1/projects/[^/]+/ai/technical-delivery",
                    r"/api/v1/projects/[^/]+/ai/technical-delivery/artifacts/[^/]+/content"),
            "POST": (r"/api/v1/projects", r"/api/v1/projects/[^/]+/uploads", r"/api/v1/projects/[^/]+/review-tasks(?:/[^/]+)?",
                     r"/api/v1/projects/[^/]+/uploads/[^/]+/complete", r"/api/v1/projects/[^/]+/requirements/drafts",
                     r"/api/v1/projects/[^/]+/procurement/orders(?:/[^/]+/(?:receipts|allocations))?",
                     r"/api/v1/projects/[^/]+/design/revisions", r"/api/v1/projects/[^/]+/changes(?:/[^/]+/(?:analyze|acceptance|reproduce))?",
                     r"/api/v1/projects/[^/]+/jobs/[^/]+/(?:retry|cancel)", r"/api/v1/projects/[^/]+/estimates/[^/]+/(?:calculations|export)", r"/api/v1/projects/[^/]+/spatial/revisions",
                     r"/api/v1/projects/[^/]+/ai/requirement-understanding",
                     r"/api/v1/projects/[^/]+/ai/requirement-understanding/jobs/[^/]+/(?:retry|cancel)",
                     r"/api/v1/projects/[^/]+/ai/design-options",
                     r"/api/v1/projects/[^/]+/ai/design-options/[^/]+/(?:revise|adopt)",
                     r"/api/v1/projects/[^/]+/ai/design-options/sets/[^/]+/cancel",
                     r"/api/v1/projects/[^/]+/ai/development-production",
                     r"/api/v1/projects/[^/]+/ai/source-extractions",
                     r"/api/v1/projects/[^/]+/ai/technical-delivery"),
            "PATCH": (r"/api/v1/projects/[^/]+", r"/api/v1/projects/[^/]+/requirements", r"/api/v1/projects/[^/]+/production/settings", r"/api/v1/projects/[^/]+/issues/[^/]+", r"/api/v1/projects/[^/]+/estimates/[^/]+/lines/[^/]+", r"/api/v1/projects/[^/]+/ai/requirement-understanding/briefs"),
            "PUT": (r"/api/v1/projects/[^/]+/uploads/[^/]+/content",),
        }
        if not any(re.fullmatch(pattern, path) for pattern in patterns.get(method, ())):
            raise ApiError(501, "POSTGRES_DOMAIN_NOT_CONNECTED", "该业务域尚未接入 PostgreSQL 试点，请使用现有本地完整工作台")

    def health(self):
        try:
            with self.app.store.connection_factory() as db:
                db.execute("SELECT 1").fetchone()
        except Exception as error:
            raise ApiError(503, "DATABASE_UNAVAILABLE", "PostgreSQL 暂不可用", True) from error
        return {"status": "ready", **self.runtime_info}

    def _require_project(self, organization_id, project_id):
        context = self._context(organization_id, project_id)
        if self.repository.get_project(context) is None:
            raise ApiError(404, "NOT_FOUND", "resource not found")
        return context

    def list_projects(self, organization_id):
        context = self._context(organization_id, "organization-overview")
        with self.app.store.tenant_transaction(context) as db:
            rows = mapping(db.execute("SELECT * FROM rkd.list_project_summaries()"))
        return {"items": [public_project(row) for row in rows], "next_cursor": None}

    @staticmethod
    def _read_project(db, context):
        rows = mapping(db.execute("SELECT organization_id,project_id,name,status,version,created_at FROM rkd.project "
                                  "WHERE organization_id=%s AND project_id=%s", (context.organization_id, context.project_id)))
        if not rows:
            raise ApiError(404, "NOT_FOUND", "resource not found")
        return public_project(rows[0])

    def get_project(self, organization_id, project_id):
        context = self._context(organization_id, project_id)
        with self.app.store.tenant_transaction(context) as db:
            return self._read_project(db, context)

    def create_project(self, organization_id, name, project_id=None, *, actor_id="local-user"):
        try:
            name = project_name(name)
        except ValueError as error:
            raise ApiError(400, "INVALID_PROJECT", str(error)) from error
        project_id = project_id or new_id("project")
        if not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", project_id):
            raise ApiError(400, "INVALID_PROJECT", "project_id must be 1 to 160 letters, digits, underscores or hyphens")
        context = self._context(organization_id, project_id, actor_id)
        with self.app.store.tenant_transaction(context) as db:
            db.execute("INSERT INTO rkd.organization(organization_id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                       (organization_id, organization_id))
            inserted = db.execute("INSERT INTO rkd.project(organization_id,project_id,name) VALUES (%s,%s,%s) "
                                  "ON CONFLICT DO NOTHING RETURNING project_id", (organization_id, project_id, name)).fetchone()
            if not inserted:
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "project already exists")
            project = self._read_project(db, context)
            self._event(db, context, "project.created", project, "create")
            return project

    def update_project(self, organization_id, project_id, request, *, actor_id="local-user"):
        try:
            name = project_name(request.get("name"))
            expected = project_version(request.get("expected_version"))
        except ValueError as error:
            raise ApiError(400, "INVALID_PROJECT", str(error)) from error
        context = self._context(organization_id, project_id, actor_id)
        with self.app.store.tenant_transaction(context) as db:
            # Same project advisory lock as the event kernel; acquire before
            # project row updates to avoid lock-order inversion.
            import json
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (json.dumps([organization_id, project_id]),))
            self._read_project(db, context)
            changed = db.execute("UPDATE rkd.project SET name=%s,version=version+1 WHERE organization_id=%s "
                                 "AND project_id=%s AND version=%s RETURNING project_id",
                                 (name, organization_id, project_id, expected)).fetchone()
            if not changed:
                raise ApiError(409, "STALE_PROJECT_VERSION", "project version is stale")
            project = self._read_project(db, context)
            self._event(db, context, "project.updated", project, f"update-{expected}")
            return project

    def _event(self, db, context, event_type, project, key):
        command = CommandEnvelope(new_id("cmd"), event_type, context, key, context.project_id, project)
        self.repository.append_command_event(command, event_type, project, aggregate_type="Project", connection=db)
