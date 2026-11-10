from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import new_id, now_iso
from .task_repository import SQLiteTaskRepository


class TaskServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


ALLOWED_DISPOSITIONS = {"open", "in_review", "resolved", "deferred", "unknown"}
ACTIVE_JOB_STATES = {"queued", "retryable"}
REPORT_NAMES = ("cad-source-inspection.json", "cad-secondary-validation.json", "cad-cross-engine-review.json", "cad-topology-review.json")


class TaskService:
    """Persistent local jobs and source-linked issue records for the M1 workbench."""

    def __init__(self, db_path: str | Path | None, *, repository=None) -> None:
        self.db_path = Path(db_path) if db_path is not None else None
        self.repository = repository or SQLiteTaskRepository(self._db)
        self.fixture_root: Path | None = None
        self.recover_running_jobs()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
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
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _public_job(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "organization_id": row["organization_id"],
            "project_id": row["project_id"],
            "job_type": row["job_type"],
            "status": row["status"],
            "attempt_count": row["attempt_count"],
            "input_hash": row["input_hash"],
            "input_ref": row["input_ref"],
            "output": json.loads(row["output_json"] or "{}"),
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _public_issue(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "issue_id": row["issue_id"],
            "organization_id": row["organization_id"],
            "project_id": row["project_id"],
            "source_file_id": row["source_file_id"],
            "source_ref": row["source_ref"],
            "source_locator": row["source_locator"],
            "issue_type": row["issue_type"],
            "severity": row["severity"],
            "title": row["title"],
            "detail": json.loads(row["detail_json"] or "{}"),
            "disposition_status": row["disposition_status"],
            "disposition_reason": row["disposition_reason"],
            "disposition_actor_id": row["disposition_actor_id"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def recover_running_jobs(self, organization_id=None, project_id=None) -> None:
        self.repository.recover(now_iso(), organization_id, project_id)

    def _report_hash(self, fixture_root: Path, report_data=None) -> str:
        digest = hashlib.sha256()
        for name in REPORT_NAMES:
            digest.update(name.encode("utf-8"))
            digest.update(report_data[name] if report_data is not None else (fixture_root / "derived" / name).read_bytes())
        return digest.hexdigest()

    def ensure_ningbo_seed(self, organization_id: str, project_id: str, fixture_root: Path) -> dict[str, Any]:
        self.fixture_root = fixture_root.resolve()
        input_hash = self._report_hash(fixture_root)
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            row = tx.seed_job(input_hash)
            if row is None:
                job_id = new_id("job")
                tx.insert_job(job_id, input_hash, now_iso())
                row = tx.job(job_id)
        if row["status"] in ACTIVE_JOB_STATES:
            return self._run_seed_job(organization_id, project_id, row["job_id"], fixture_root)
        return self._public_job(row)

    def _run_seed_job(self, organization_id, project_id, job_id: str, fixture_root: Path) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            row = tx.job(job_id)
            if row is None:
                raise TaskServiceError(404, "NOT_FOUND", "job not found")
            if row["status"] not in ACTIVE_JOB_STATES:
                return self._public_job(row)
            attempt = int(row["attempt_count"]) + 1
            tx.start(job_id, attempt, now_iso())
            try:
                # Roll back every issue in a failed attempt, then persist the
                # failure record outside the savepoint in the same transaction.
                with tx.work():
                    report_data = {name: (fixture_root / "derived" / name).read_bytes() for name in REPORT_NAMES}
                    if self._report_hash(fixture_root, report_data) != row["input_hash"]:
                        raise TaskServiceError(409, "TASK_SOURCE_CHANGED", "任务源报告已变化，请重新导入新版本，不能沿用旧输入哈希")
                    reports = {name: json.loads(data.decode("utf-8")) for name, data in report_data.items()}
                    issue_specs = self._issue_specs(reports, tx.source_files())
                    issue_ids = []
                    for spec in issue_specs:
                        existing = tx.existing_issue(spec["issue_type"], spec["source_ref"])
                        if existing:
                            issue_ids.append(existing["issue_id"])
                            continue
                        issue_id = new_id("issue")
                        tx.insert_issue(issue_id, spec, self._json(spec["detail"]), now_iso())
                        issue_ids.append(issue_id)
                    output = {"issue_ids": issue_ids, "issue_count": len(issue_ids), "promotion_status": "not-approved"}
                    tx.finish(job_id, attempt, now_iso(), output=self._json(output))
            except Exception as error:
                tx.finish(job_id, attempt, now_iso(), error=str(error), code=getattr(error, "code", "IMPORT_FAILED"))
            result = tx.job(job_id)
        return self._public_job(result)

    @staticmethod
    def _issue_specs(reports: dict[str, dict[str, Any]], source_files: dict[str, str]) -> list[dict[str, Any]]:
        inspection = reports["cad-source-inspection.json"]
        secondary = reports["cad-secondary-validation.json"]
        cross_engine = reports["cad-cross-engine-review.json"]
        topology = reports["cad-topology-review.json"]
        return [
            {
                "source_file_id": source_files.get(inspection.get("source_asset_id")),
                "source_ref": inspection.get("source_asset_id", "drawing-cad-01"),
                "source_locator": "derived/cad-source-inspection.json#warnings",
                "issue_type": "cad.geometry_compatibility",
                "severity": "high",
                "title": "DWG 几何解析需要二次校验",
                "detail": {"status": inspection.get("geometry_status"), "warnings": inspection.get("warnings", []), "parser": inspection.get("parser")},
            },
            {
                "source_file_id": source_files.get(secondary.get("source_asset_id")),
                "source_ref": secondary.get("source_asset_id", "drawing-cad-01-dxf-2013"),
                "source_locator": "derived/cad-secondary-validation.json#comparison",
                "issue_type": "cad.secondary_difference",
                "severity": "medium",
                "title": "DXF 对照结果存在差异，不能替换 DWG 原件",
                "detail": {"status": secondary.get("status"), "comparison": secondary.get("comparison"), "warnings": secondary.get("warnings", [])},
            },
            {
                "source_file_id": source_files.get(cross_engine.get("dwg_source_asset_id")),
                "source_ref": "cad-cross-engine-review",
                "source_locator": "derived/cad-cross-engine-review.json#summary",
                "issue_type": "cad.candidate_approval",
                "severity": "medium",
                "title": "共同图元仍是候选证据，尚未批准为专业对象",
                "detail": {"summary": cross_engine.get("summary"), "warnings": cross_engine.get("warnings", []), "promotion_status": "not-approved"},
            },
            {
                "source_file_id": source_files.get(topology.get("source_asset_id")),
                "source_ref": "cad-topology-review",
                "source_locator": "derived/cad-topology-review.json#summary",
                "issue_type": "cad.topology_review",
                "severity": "medium",
                "title": "拓扑复核队列待专业处置",
                "detail": {"summary": topology.get("summary"), "warnings": topology.get("warnings", []), "review_item_count": len(topology.get("items", []))},
            },
            {
                "source_file_id": source_files.get("budget-01"),
                "source_ref": "budget-source-conflict",
                "source_locator": "project_decisions.contract_target_gross_cny",
                "issue_type": "budget.source_conflict",
                "severity": "medium",
                "title": "合同含税目标与源预算税口径冲突",
                "detail": {"contract_target_gross_cny": "600000.00", "source_label": "discounted_price_before_tax", "status": "user_confirmed_trial"},
            },
        ]

    def list_jobs(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self.recover_running_jobs(organization_id, project_id)
        with self.repository.transaction(organization_id, project_id) as tx:
            rows = tx.jobs()
        return {"items": [self._public_job(row) for row in rows]}

    def retry_job(self, organization_id: str, project_id: str, job_id: str, fixture_root: Path) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            row = tx.job(job_id)
            if row is None:
                raise TaskServiceError(404, "NOT_FOUND", "job not found")
            if row["status"] not in {"retryable", "failed"}:
                raise TaskServiceError(409, "JOB_STATE", "only failed or retryable jobs can be retried")
            tx.queue(job_id, now_iso())
        return self._run_seed_job(organization_id, project_id, job_id, fixture_root)

    def cancel_job(self, organization_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            row = tx.job(job_id)
            if row is None:
                raise TaskServiceError(404, "NOT_FOUND", "job not found")
            if row["status"] not in {"queued", "running", "retryable"}:
                raise TaskServiceError(409, "JOB_STATE", "job can no longer be cancelled")
            tx.cancel(job_id, now_iso())
            row = tx.job(job_id)
        return self._public_job(row)

    def list_issues(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as tx:
            rows = tx.issues()
        return {"items": [self._public_issue(row) for row in rows]}

    def get_issue(self, organization_id: str, project_id: str, issue_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as tx:
            row = tx.issue(issue_id)
            if row is None:
                raise TaskServiceError(404, "NOT_FOUND", "issue not found")
            issue = self._public_issue(row)
            issue["actions"] = [dict(action) for action in tx.actions(issue_id)]
        return issue

    def record_disposition(self, organization_id: str, project_id: str, issue_id: str,
                           request: dict[str, Any], actor_id: str) -> dict[str, Any]:
        status = str(request.get("status", "")).strip()
        reason = str(request.get("reason", "")).strip()
        if status not in ALLOWED_DISPOSITIONS:
            raise TaskServiceError(400, "INVALID_DISPOSITION", "处置状态不支持；不能在此处批准专业对象")
        if not reason:
            raise TaskServiceError(400, "INVALID_DISPOSITION", "处置理由不能为空")
        version = request.get("expected_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise TaskServiceError(400, "INVALID_DISPOSITION", "需要当前问题的正整数版本")
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            row = tx.issue(issue_id)
            if row is None:
                raise TaskServiceError(404, "NOT_FOUND", "issue not found")
            if row["version"] != version:
                raise TaskServiceError(409, "STALE_ISSUE_VERSION", "问题版本已变化，请重新读取")
            tx.disposition(issue_id, status, reason, actor_id, now_iso(), new_id("issue_action"))
            result = tx.issue(issue_id)
        return self._public_issue(result)
