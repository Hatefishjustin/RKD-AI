from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Iterator

from .models import new_id, now_iso
from .design_rules import DesignError, normalize_program
from .requirement_repository import SQLiteRequirementRepository


class RequirementServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class RequirementService:
    """Rule-based requirement draft assembled from persisted project evidence."""

    def __init__(self, db_path: str | Path | None, *, repository=None) -> None:
        self.db_path = Path(db_path) if db_path is not None else None
        if self.db_path is None and repository is None:
            raise ValueError("an explicit requirement repository is required")
        self.repository = repository or SQLiteRequirementRepository(self._db)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        if self.db_path is None:
            raise RuntimeError("SQLite connection is unavailable in PostgreSQL mode")
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _build_content(self, connection: sqlite3.Connection, organization_id: str, project_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        project, decisions, files = connection.evidence()
        if project is None:
            raise RequirementServiceError(404, "NOT_FOUND", "项目不存在")
        decision_map = {row["decision_key"]: json.loads(row["value_json"]) for row in decisions}
        exclusions = decision_map.get("excluded_scopes")
        if exclusions is None:
            exclusions = "unknown"
        content = {
            "title": f"{project['name']}需求草稿",
            "project_name": project["name"],
            "project_type": "企业空间/展厅（规则推断，待确认）" if "展厅" in project["name"] else "unknown",
            "status": "draft_unconfirmed",
            "generation_method": "rule_based_from_project_decisions_and_source_files",
            "budget": {
                "contract_target_gross_cny": decision_map.get("contract_target_gross_cny", "unknown"),
                "tax_rate": decision_map.get("trial_tax_rate", "unknown"),
                "tax_basis": "local_trial_only",
            },
            "scope": {
                "excluded_scopes": exclusions,
                "construction_cost_markup": decision_map.get("construction_cost_markup", "unknown"),
                "design_cost_markup": decision_map.get("design_cost_markup", "unknown"),
            },
            "evidence_policy": {
                "primary_drawing": "construction_drawing_dwg",
                "secondary_drawing": "floor_plan_pdf",
                "site_evidence": "site_photos",
                "human_confirmation_required": True,
            },
            "open_questions": [
                "客户功能分区、容量和动线需求待确认",
                "材料样板、品牌和风格偏好待确认",
                "正式税务核验、合同文本和责任人待专业复核（本地试用参数已记录）",
            ],
        }
        source_refs = [
            {"type": "project_decision", "key": row["decision_key"], "source": row["source"], "status": row["status"], "source_conflict": row["source_conflict"]}
            for row in decisions
        ] + [
            {"type": "file_asset", "file_id": row["file_id"], "filename": row["filename"], "kind": row["kind"], "source_kind": row["source_kind"], "source_ref": row["source_ref"], "sha256": row["sha256"], "format_status": row["format_status"]}
            for row in files
        ]
        return content, source_refs

    @staticmethod
    def _public(connection: sqlite3.Connection, requirement: sqlite3.Row, revision: sqlite3.Row) -> dict[str, Any]:
        return {
            "requirement_id": requirement["requirement_id"], "organization_id": requirement["organization_id"],
            "project_id": requirement["project_id"], "revision_no": revision["revision_no"],
            "status": requirement["status"], "source_kind": revision["source_kind"],
            "change_reason": revision["change_reason"], "actor_id": revision["actor_id"],
            "content": json.loads(revision["content_json"]), "source_refs": json.loads(revision["source_refs_json"]),
            "input_hash": revision["input_hash"], "created_at": revision["created_at"],
        }

    def get_current(self, organization_id: str, project_id: str) -> dict[str, Any] | None:
        with self.repository.transaction(organization_id, project_id) as transaction:
            requirement = transaction.requirement()
            if requirement is None:
                return None
            revision = transaction.revision(requirement["requirement_id"], requirement["current_revision_no"])
            if revision is None:
                raise RequirementServiceError(500, "REQUIREMENT_INTEGRITY", "需求当前修订缺失")
            return self._public(transaction, requirement, revision)

    def create_draft(self, organization_id: str, project_id: str, actor_id: str, change_reason: str = "从项目证据生成需求草稿") -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id, write=True) as transaction:
            content, source_refs = self._build_content(transaction, organization_id, project_id)
            input_hash = hashlib.sha256(self._json({"content": content, "source_refs": source_refs}).encode("utf-8")).hexdigest()
            requirement = transaction.requirement()
            if requirement is None:
                requirement_id, revision_no, now = new_id("requirement"), 1, now_iso()
                transaction.insert_requirement(requirement_id, now)
            else:
                requirement_id = requirement["requirement_id"]
                current = transaction.revision(requirement_id, requirement["current_revision_no"])
                if current:
                    return self._public(transaction, requirement, current)
                raise RequirementServiceError(500, "REQUIREMENT_INTEGRITY", "需求当前修订缺失")
            transaction.insert_revision({"requirement_id": requirement_id, "revision_no": revision_no,
                                         "source_kind": "rule_based_draft", "change_reason": change_reason,
                                         "actor_id": actor_id, "content_json": self._json(content),
                                         "source_refs_json": self._json(source_refs), "input_hash": input_hash, "created_at": now})
            requirement = transaction.requirement()
            revision = transaction.revision(requirement_id, revision_no)
            return self._public(transaction, requirement, revision)

    def update_draft(self, organization_id: str, project_id: str, actor_id: str, request: dict, *, connection=None) -> dict:
        reason = str(request.get("change_reason", "")).strip()
        if not reason or len(reason) > 500:
            raise RequirementServiceError(400, "INVALID_REQUIREMENT_CHANGE", "请填写修改理由（最多 500 字）")
        try:
            program = normalize_program(request.get("design_program"))
        except DesignError as error:
            raise RequirementServiceError(error.status, error.code, error.message) from error
        notes = str(request.get("design_notes", "")).strip()
        if len(notes) > 4000:
            raise RequirementServiceError(400, "INVALID_REQUIREMENT_CHANGE", "设计备注最多 4000 字")
        with (nullcontext(self.repository.bind(connection, organization_id, project_id)) if connection is not None
              else self.repository.transaction(organization_id, project_id, write=True)) as transaction:
            requirement = transaction.requirement()
            if not requirement:
                raise RequirementServiceError(404, "NOT_FOUND", "请先生成需求草稿")
            current_no = requirement["current_revision_no"]
            if request.get("expected_revision") != current_no:
                raise RequirementServiceError(409, "STALE_REQUIREMENT_REVISION", "需求已变化，请重新读取")
            current = transaction.revision(requirement["requirement_id"], current_no)
            if current is None:
                raise RequirementServiceError(500, "REQUIREMENT_INTEGRITY", "需求当前修订缺失")
            content = json.loads(current["content_json"])
            content.update({"design_program": program, "design_notes": notes})
            source_refs = json.loads(current["source_refs_json"])
            digest = hashlib.sha256(self._json({"content": content, "source_refs": source_refs}).encode("utf-8")).hexdigest()
            if digest == current["input_hash"]:
                return self._public(transaction, requirement, current)
            revision_no, now = current_no + 1, now_iso()
            transaction.insert_revision({"requirement_id": requirement["requirement_id"], "revision_no": revision_no,
                                         "source_kind": "manual_draft", "change_reason": reason, "actor_id": actor_id,
                                         "content_json": self._json(content), "source_refs_json": current["source_refs_json"],
                                         "input_hash": digest, "created_at": now})
            transaction.advance(requirement["requirement_id"], revision_no, now)
            revision = transaction.revision(requirement["requirement_id"], revision_no)
            return self._public(transaction, requirement, revision)
