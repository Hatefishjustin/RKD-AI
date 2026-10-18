from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from .design_outputs import generate_design_outputs
from .design_rules import DesignError, RULE_VERSION, generate_model, normalize_program, validate_model
from .models import new_id, now_iso
from .requirement_service import RequirementService


class DesignService(RequirementService):
    """Versioned local design drafts. No professional approval or external effects."""

    def _public_design(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        latest = connection.execute("SELECT MAX(revision_no) FROM design_revisions WHERE organization_id = ? AND project_id = ?", (row["organization_id"], row["project_id"])).fetchone()[0]
        current_requirement = connection.execute("SELECT current_revision_no FROM requirements WHERE requirement_id = ?", (row["requirement_id"],)).fetchone()[0]
        status = "superseded" if row["revision_no"] < latest else "source_outdated" if current_requirement != row["requirement_revision_no"] else "draft"
        artifacts = []
        for artifact in connection.execute("SELECT artifact_id, artifact_kind, filename, content_type, sha256, size_bytes FROM design_artifacts WHERE design_revision_id = ? ORDER BY artifact_kind", (row["design_revision_id"],)):
            artifacts.append({**dict(artifact), "status": status, "download_url": f"/api/v1/projects/{row['project_id']}/design/artifacts/{artifact['artifact_id']}/content"})
        return {"design_revision_id": row["design_revision_id"], "project_id": row["project_id"], "revision_no": row["revision_no"], "requirement_id": row["requirement_id"], "requirement_revision_no": row["requirement_revision_no"], "requirement_hash": row["requirement_hash"], "input_hash": row["input_hash"], "model": json.loads(row["model_json"]), "validation": json.loads(row["validation_json"]), "source_kind": row["source_kind"], "change_reason": row["change_reason"], "actor_id": row["actor_id"], "created_at": row["created_at"], "status": status, "artifacts": artifacts}

    def get_design(self, organization_id: str, project_id: str, revision_no: int | None = None) -> dict:
        with self._db() as connection:
            args = [organization_id, project_id]
            clause = ""
            if revision_no is not None:
                clause = " AND revision_no = ?"
                args.append(revision_no)
            row = connection.execute("SELECT * FROM design_revisions WHERE organization_id = ? AND project_id = ?" + clause + " ORDER BY revision_no DESC LIMIT 1", args).fetchone()
            if row is None and revision_no is not None:
                raise DesignError(404, "NOT_FOUND", "设计修订不存在")
            revisions = [dict(r) for r in connection.execute("SELECT revision_no, requirement_revision_no, source_kind, change_reason, actor_id, created_at FROM design_revisions WHERE organization_id = ? AND project_id = ? ORDER BY revision_no DESC", (organization_id, project_id))]
            return {"item": None if row is None else self._public_design(connection, row), "revisions": revisions}

    def create_design(self, organization_id: str, project_id: str, actor_id: str, request: dict) -> dict:
        reason = str(request.get("change_reason", "")).strip()
        if not reason or len(reason) > 500:
            raise DesignError(400, "INVALID_DESIGN_CHANGE", "请填写设计修改理由（最多 500 字）")
        root = None
        try:
            with self._db() as connection:
                connection.execute("BEGIN IMMEDIATE")
                requirement = connection.execute("SELECT * FROM requirements WHERE organization_id = ? AND project_id = ?", (organization_id, project_id)).fetchone()
                if not requirement:
                    raise DesignError(409, "DESIGN_PROGRAM_REQUIRED", "请先生成并保存结构化设计需求")
                if requirement["current_revision_no"] != request.get("requirement_revision_no"):
                    raise DesignError(409, "STALE_REQUIREMENT_REVISION", "需求基线已变化，请重新读取")
                req_row = connection.execute("SELECT * FROM requirement_revisions WHERE requirement_id = ? AND revision_no = ?", (requirement["requirement_id"], requirement["current_revision_no"])).fetchone()
                content = json.loads(req_row["content_json"])
                program = normalize_program(content.get("design_program"))
                latest = connection.execute("SELECT * FROM design_revisions WHERE organization_id = ? AND project_id = ? ORDER BY revision_no DESC LIMIT 1", (organization_id, project_id)).fetchone()
                current_no = latest["revision_no"] if latest else 0
                if request.get("expected_revision") != current_no:
                    raise DesignError(409, "STALE_DESIGN_REVISION", "设计已变化，请重新读取")
                raw_model = generate_model(program) if request.get("model") is None else request["model"]
                model, validation = validate_model(program, raw_model)
                digest = hashlib.sha256(self._json({"rule_version": RULE_VERSION, "requirement_hash": req_row["input_hash"], "model": model}).encode("utf-8")).hexdigest()
                if latest and latest["input_hash"] == digest:
                    return self._public_design(connection, latest)
                revision_no, revision_id, now = current_no + 1, new_id("design"), now_iso()
                source_kind = "rule_based_layout" if request.get("model") is None else "manual_layout_edit"
                connection.execute("INSERT INTO design_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (revision_id, organization_id, project_id, revision_no, requirement["requirement_id"], req_row["revision_no"], req_row["input_hash"], digest, self._json(model), self._json(validation), source_kind, reason, actor_id, now))
                baseline = {"design_revision_id": revision_id, "revision_no": revision_no, "requirement_id": requirement["requirement_id"], "requirement_revision_no": req_row["revision_no"], "requirement_hash": req_row["input_hash"], "input_hash": digest, "source_kind": source_kind, "actor_id": actor_id, "change_reason": reason}
                snapshot = {"content": content, "source_refs": json.loads(req_row["source_refs_json"])}
                # Generated UUID path components isolate orgs/projects and avoid filename collisions.
                root = self.db_path.parent / "projects" / requirement["requirement_id"] / "exports" / revision_id
                root.mkdir(parents=True, exist_ok=False)
                for kind, (filename, mime, data) in generate_design_outputs(baseline, model, validation, snapshot).items():
                    path = root / filename
                    path.write_bytes(data)
                    connection.execute("INSERT INTO design_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (new_id("design-artifact"), revision_id, kind, filename, mime, str(path.relative_to(self.db_path.parent)), hashlib.sha256(data).hexdigest(), len(data)))
                row = connection.execute("SELECT * FROM design_revisions WHERE design_revision_id = ?", (revision_id,)).fetchone()
                return self._public_design(connection, row)
        except Exception:
            if root is not None:
                # Only this attempt's freshly generated directory is eligible for cleanup.
                shutil.rmtree(root)
            raise

    def get_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict, Path]:
        with self._db() as connection:
            artifact = connection.execute("SELECT a.* FROM design_artifacts a JOIN design_revisions d ON a.design_revision_id = d.design_revision_id WHERE a.artifact_id = ? AND d.organization_id = ? AND d.project_id = ?", (artifact_id, organization_id, project_id)).fetchone()
        if not artifact:
            raise DesignError(404, "NOT_FOUND", "设计成果不存在")
        path = (self.db_path.parent / artifact["relative_path"]).resolve()
        if not path.is_relative_to(self.db_path.parent.resolve()):
            raise DesignError(500, "INVALID_ARTIFACT_PATH", "设计成果路径无效")
        if not path.is_file() or path.stat().st_size != artifact["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
            raise DesignError(500, "ARTIFACT_INTEGRITY", "设计成果字节缺失或发生变化")
        return dict(artifact), path
