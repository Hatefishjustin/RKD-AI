from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import nullcontext
from pathlib import Path

from .design_outputs import generate_design_outputs
from .design_rules import DesignError, RULE_VERSION, generate_model, normalize_program, validate_model
from .models import new_id, now_iso
from .requirement_service import RequirementService
from .production_service import ProductionService


class DesignService(ProductionService):
    """Versioned local design drafts. No professional approval or external effects."""

    def _public_design(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        latest = connection.latest_design()["revision_no"]
        current_requirement = connection.current_requirement()["current_revision_no"]
        status = "superseded" if row["revision_no"] < latest else "source_outdated" if current_requirement != row["requirement_revision_no"] else "draft"
        artifacts = []
        for artifact in connection.design_artifacts(row["design_revision_id"]):
            artifacts.append({**{k: artifact[k] for k in ("artifact_id", "artifact_kind", "filename", "content_type", "sha256", "size_bytes")},
                              "status": status, "download_url": f"/api/v1/projects/{row['project_id']}/design/artifacts/{artifact['artifact_id']}/content"})
        return {"design_revision_id": row["design_revision_id"], "project_id": row["project_id"], "revision_no": row["revision_no"], "requirement_id": row["requirement_id"], "requirement_revision_no": row["requirement_revision_no"], "requirement_hash": row["requirement_hash"], "input_hash": row["input_hash"], "model": json.loads(row["model_json"]), "validation": json.loads(row["validation_json"]), "source_kind": row["source_kind"], "change_reason": row["change_reason"], "actor_id": row["actor_id"], "created_at": row["created_at"], "status": status, "artifacts": artifacts}

    def get_design(self, organization_id: str, project_id: str, revision_no: int | None = None) -> dict:
        with self.model_repository.transaction(organization_id, project_id) as connection:
            row = connection.design(revision_no)
            if row is None and revision_no is not None:
                raise DesignError(404, "NOT_FOUND", "设计修订不存在")
            return {"item": None if row is None else self._public_design(connection, row), "revisions": connection.design_history()}

    def create_design(self, organization_id: str, project_id: str, actor_id: str, request: dict, *, connection=None) -> dict:
        reason = str(request.get("change_reason", "")).strip()
        if not reason or len(reason) > 500:
            raise DesignError(400, "INVALID_DESIGN_CHANGE", "请填写设计修改理由（最多 500 字）")
        root = None
        root_created = False
        try:
            with (nullcontext(self.model_repository.bind(connection, organization_id, project_id)) if connection is not None
                  else self.model_repository.transaction(organization_id, project_id, write=True)) as connection:
                requirement = connection.current_requirement()
                if not requirement:
                    raise DesignError(409, "DESIGN_PROGRAM_REQUIRED", "请先生成并保存结构化设计需求")
                if requirement["current_revision_no"] != request.get("requirement_revision_no"):
                    raise DesignError(409, "STALE_REQUIREMENT_REVISION", "需求基线已变化，请重新读取")
                req_row = connection.requirement_revision(requirement["requirement_id"], requirement["current_revision_no"])
                content = json.loads(req_row["content_json"])
                program = normalize_program(content.get("design_program"))
                latest = connection.latest_design()
                current_no = latest["revision_no"] if latest else 0
                if request.get("expected_revision") != current_no:
                    raise DesignError(409, "STALE_DESIGN_REVISION", "设计已变化，请重新读取")
                raw_model = generate_model(program) if request.get("model") is None else request["model"]
                model, validation = validate_model(program, raw_model)
                digest = hashlib.sha256(self._json({"rule_version": RULE_VERSION, "requirement_hash": req_row["input_hash"], "model": model}).encode("utf-8")).hexdigest()
                if latest and latest["input_hash"] == digest:
                    self.sync(connection, latest, actor_id)
                    return self._public_design(connection, latest)
                revision_no, revision_id, now = current_no + 1, new_id("design"), now_iso()
                source_kind = "rule_based_layout" if request.get("model") is None else "manual_layout_edit"
                connection.insert_design({"design_revision_id": revision_id, "revision_no": revision_no, "requirement_id": requirement["requirement_id"],
                                          "requirement_revision_no": req_row["revision_no"], "requirement_hash": req_row["input_hash"], "input_hash": digest,
                                          "model_json": self._json(model), "validation_json": self._json(validation), "source_kind": source_kind,
                                          "change_reason": reason, "actor_id": actor_id, "created_at": now})
                baseline = {"design_revision_id": revision_id, "revision_no": revision_no, "requirement_id": requirement["requirement_id"], "requirement_revision_no": req_row["revision_no"], "requirement_hash": req_row["input_hash"], "input_hash": digest, "source_kind": source_kind, "actor_id": actor_id, "change_reason": reason}
                snapshot = {"content": content, "source_refs": json.loads(req_row["source_refs_json"])}
                # Generated UUID path components isolate orgs/projects and avoid filename collisions.
                root = self.runtime_root / "projects" / requirement["requirement_id"] / "exports" / revision_id
                root.mkdir(parents=True, exist_ok=False)
                root_created = True
                for kind, (filename, mime, data) in generate_design_outputs(baseline, model, validation, snapshot).items():
                    path = root / filename
                    path.write_bytes(data)
                    connection.insert_design_artifact({"artifact_id": new_id("design-artifact"), "design_revision_id": revision_id,
                                                       "artifact_kind": kind, "filename": filename, "content_type": mime,
                                                       "relative_path": path.relative_to(self.runtime_root).as_posix(),
                                                       "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})
                row = connection.latest_design()
                self.sync(connection, row, actor_id)
                return self._public_design(connection, row)
        except Exception:
            if root_created:
                # Only this attempt's freshly generated directory is eligible for cleanup.
                shutil.rmtree(root)
            raise

    def get_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict, Path]:
        with self.model_repository.transaction(organization_id, project_id) as connection:
            artifact = connection.design_artifact(artifact_id)
        if not artifact:
            raise DesignError(404, "NOT_FOUND", "设计成果不存在")
        path = (self.runtime_root / artifact["relative_path"]).resolve()
        if not path.is_relative_to(self.runtime_root.resolve()):
            raise DesignError(500, "INVALID_ARTIFACT_PATH", "设计成果路径无效")
        if not path.is_file() or path.stat().st_size != artifact["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
            raise DesignError(500, "ARTIFACT_INTEGRITY", "设计成果字节缺失或发生变化")
        return dict(artifact), path
