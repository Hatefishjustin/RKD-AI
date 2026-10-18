from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import new_id, now_iso


class TaskServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


ALLOWED_DISPOSITIONS = {"open", "in_review", "resolved", "deferred", "unknown"}
ACTIVE_JOB_STATES = {"queued", "retryable"}


class TaskService:
    """Persistent local jobs and source-linked issue records for the M1 workbench."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
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

    def recover_running_jobs(self) -> None:
        """A process restart cannot leave a job claiming to be running."""
        with self._db() as connection:
            now = now_iso()
            connection.execute(
                "UPDATE jobs SET status = 'retryable', error_code = 'WORKER_RESTARTED', "
                "error_message = '本地服务重启，任务等待再次执行', lease_until = NULL, updated_at = ? "
                "WHERE status = 'running'",
                (now,),
            )
            connection.execute(
                "UPDATE job_attempts SET status = 'retryable', finished_at = ?, error_code = 'WORKER_RESTARTED', "
                "error_message = '本地服务重启' WHERE status = 'running' AND finished_at IS NULL",
                (now,),
            )

    def _report_hash(self, fixture_root: Path) -> str:
        digest = hashlib.sha256()
        for name in (
            "cad-source-inspection.json",
            "cad-secondary-validation.json",
            "cad-cross-engine-review.json",
            "cad-topology-review.json",
        ):
            path = fixture_root / "derived" / name
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def ensure_ningbo_seed(self, organization_id: str, project_id: str, fixture_root: Path) -> dict[str, Any]:
        self.fixture_root = fixture_root.resolve()
        input_hash = self._report_hash(fixture_root)
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE organization_id = ? AND project_id = ? "
                "AND job_type = 'cad_report_import' AND input_hash = ?",
                (organization_id, project_id, input_hash),
            ).fetchone()
            if row is None:
                now = now_iso()
                job_id = new_id("job")
                connection.execute(
                    "INSERT INTO jobs(job_id, organization_id, project_id, job_type, status, attempt_count, "
                    "input_hash, input_ref, created_at, updated_at) VALUES (?, ?, ?, 'cad_report_import', 'queued', 0, ?, ?, ?, ?)",
                    (job_id, organization_id, project_id, input_hash, "derived/cad-source-inspection.json", now, now),
                )
                row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row["status"] in ACTIVE_JOB_STATES:
            return self._run_seed_job(row["job_id"], fixture_root)
        return self._job(row["job_id"])

    def _job(self, job_id: str) -> dict[str, Any]:
        with self._db() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise TaskServiceError(404, "NOT_FOUND", "job not found")
        return self._public_job(row)

    def _run_seed_job(self, job_id: str, fixture_root: Path) -> dict[str, Any]:
        now = now_iso()
        with self._db() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise TaskServiceError(404, "NOT_FOUND", "job not found")
            if row["status"] not in ACTIVE_JOB_STATES:
                return self._public_job(row)
            attempt = int(row["attempt_count"]) + 1
            connection.execute(
                "UPDATE jobs SET status = 'running', attempt_count = ?, error_code = NULL, error_message = NULL, "
                "lease_until = NULL, updated_at = ? WHERE job_id = ?",
                (attempt, now, job_id),
            )
            connection.execute(
                "INSERT INTO job_attempts(job_id, attempt_no, status, started_at) VALUES (?, ?, 'running', ?)",
                (job_id, attempt, now),
            )
            try:
                reports = {
                    name: json.loads((fixture_root / "derived" / name).read_text(encoding="utf-8"))
                    for name in (
                        "cad-source-inspection.json",
                        "cad-secondary-validation.json",
                        "cad-cross-engine-review.json",
                        "cad-topology-review.json",
                    )
                }
                source_files = {
                    source_ref: file_id
                    for file_id, source_ref in connection.execute(
                        "SELECT file_id, source_ref FROM file_assets WHERE organization_id = ? AND project_id = ?",
                        (row["organization_id"], row["project_id"]),
                    )
                }
                issue_specs = self._issue_specs(reports, source_files)
                issue_ids: list[str] = []
                for spec in issue_specs:
                    issue_id = new_id("issue")
                    existing = connection.execute(
                        "SELECT issue_id FROM issues WHERE organization_id = ? AND project_id = ? "
                        "AND issue_type = ? AND source_ref = ?",
                        (row["organization_id"], row["project_id"], spec["issue_type"], spec["source_ref"]),
                    ).fetchone()
                    if existing:
                        issue_ids.append(existing[0])
                        continue
                    connection.execute(
                        "INSERT INTO issues(issue_id, organization_id, project_id, source_file_id, source_ref, "
                        "source_locator, issue_type, severity, title, detail_json, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (issue_id, row["organization_id"], row["project_id"], spec["source_file_id"],
                         spec["source_ref"], spec["source_locator"], spec["issue_type"], spec["severity"],
                         spec["title"], self._json(spec["detail"]), now, now),
                    )
                    issue_ids.append(issue_id)
                output = {"issue_ids": issue_ids, "issue_count": len(issue_ids), "promotion_status": "not-approved"}
                finished = now_iso()
                connection.execute(
                    "UPDATE job_attempts SET status = 'succeeded', finished_at = ? WHERE job_id = ? AND attempt_no = ?",
                    (finished, job_id, attempt),
                )
                connection.execute(
                    "UPDATE jobs SET status = 'succeeded', output_json = ?, updated_at = ? WHERE job_id = ?",
                    (self._json(output), finished, job_id),
                )
            except Exception as error:
                finished = now_iso()
                connection.execute(
                    "UPDATE job_attempts SET status = 'retryable', finished_at = ?, error_code = 'IMPORT_FAILED', error_message = ? "
                    "WHERE job_id = ? AND attempt_no = ?",
                    (finished, str(error), job_id, attempt),
                )
                connection.execute(
                    "UPDATE jobs SET status = 'retryable', error_code = 'IMPORT_FAILED', error_message = ?, updated_at = ? WHERE job_id = ?",
                    (str(error), finished, job_id),
                )
            result = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
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
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE organization_id = ? AND project_id = ? ORDER BY updated_at DESC, job_id DESC",
                (organization_id, project_id),
            ).fetchall()
        return {"items": [self._public_job(row) for row in rows]}

    def retry_job(self, organization_id: str, project_id: str, job_id: str, fixture_root: Path) -> dict[str, Any]:
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ? AND organization_id = ? AND project_id = ?",
                (job_id, organization_id, project_id),
            ).fetchone()
            if row is None:
                raise TaskServiceError(404, "NOT_FOUND", "job not found")
            if row["status"] not in {"retryable", "failed"}:
                raise TaskServiceError(409, "JOB_STATE", "only failed or retryable jobs can be retried")
            connection.execute("UPDATE jobs SET status = 'queued', updated_at = ? WHERE job_id = ?", (now_iso(), job_id))
        return self._run_seed_job(job_id, fixture_root)

    def cancel_job(self, organization_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ? AND organization_id = ? AND project_id = ?",
                (job_id, organization_id, project_id),
            ).fetchone()
            if row is None:
                raise TaskServiceError(404, "NOT_FOUND", "job not found")
            if row["status"] not in {"queued", "running", "retryable"}:
                raise TaskServiceError(409, "JOB_STATE", "job can no longer be cancelled")
            connection.execute(
                "UPDATE jobs SET status = 'cancelled', error_code = 'CANCELLED_BY_USER', error_message = '用户取消任务', updated_at = ? WHERE job_id = ?",
                (now_iso(), job_id),
            )
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._public_job(row)

    def list_issues(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self._db() as connection:
            rows = connection.execute(
                "SELECT * FROM issues WHERE organization_id = ? AND project_id = ? ORDER BY "
                "CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, updated_at DESC",
                (organization_id, project_id),
            ).fetchall()
        return {"items": [self._public_issue(row) for row in rows]}

    def get_issue(self, organization_id: str, project_id: str, issue_id: str) -> dict[str, Any]:
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM issues WHERE issue_id = ? AND organization_id = ? AND project_id = ?",
                (issue_id, organization_id, project_id),
            ).fetchone()
            if row is None:
                raise TaskServiceError(404, "NOT_FOUND", "issue not found")
            issue = self._public_issue(row)
            actions = connection.execute(
                "SELECT action, reason, actor_id, created_at FROM issue_actions WHERE issue_id = ? ORDER BY created_at",
                (issue_id,),
            ).fetchall()
        issue["actions"] = [dict(action) for action in actions]
        return issue

    def record_disposition(self, organization_id: str, project_id: str, issue_id: str,
                           request: dict[str, Any], actor_id: str) -> dict[str, Any]:
        status = str(request.get("status", "")).strip()
        reason = str(request.get("reason", "")).strip()
        if status not in ALLOWED_DISPOSITIONS:
            raise TaskServiceError(400, "INVALID_DISPOSITION", "处置状态不支持；不能在此处批准专业对象")
        if not reason:
            raise TaskServiceError(400, "INVALID_DISPOSITION", "处置理由不能为空")
        expected_version = int(request.get("expected_version", -1))
        with self._db() as connection:
            row = connection.execute(
                "SELECT * FROM issues WHERE issue_id = ? AND organization_id = ? AND project_id = ?",
                (issue_id, organization_id, project_id),
            ).fetchone()
            if row is None:
                raise TaskServiceError(404, "NOT_FOUND", "issue not found")
            if int(row["version"]) != expected_version:
                raise TaskServiceError(409, "STALE_ISSUE_VERSION", "问题版本已变化，请重新读取")
            now = now_iso()
            connection.execute(
                "UPDATE issues SET disposition_status = ?, disposition_reason = ?, disposition_actor_id = ?, version = version + 1, updated_at = ? WHERE issue_id = ?",
                (status, reason, actor_id, now, issue_id),
            )
            connection.execute(
                "INSERT INTO issue_actions(action_id, issue_id, organization_id, project_id, action, reason, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id("issue_action"), issue_id, organization_id, project_id, status, reason, actor_id, now),
            )
            result = connection.execute("SELECT * FROM issues WHERE issue_id = ?", (issue_id,)).fetchone()
        return self._public_issue(result)
