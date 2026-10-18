from __future__ import annotations

import hashlib
import html
import json
import shutil
import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

from .models import new_id, now_iso


class ChangeServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ChangeService:
    """Versioned local change impact and acceptance facts with no external effects."""

    def __init__(self, db_path: str | Path | None) -> None:
        self.db_path = Path(db_path) if db_path else None

    @contextmanager
    def _db(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if self.db_path is None:
            raise ChangeServiceError(501, "CHANGES_NOT_CONFIGURED", "local change storage is not configured")
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _fingerprint(cls, value: Any) -> str:
        return hashlib.sha256(cls._json(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _decimal(value: Any, label: str, allow_unknown: bool = True) -> str | None:
        if value is None or value == "":
            if allow_unknown:
                return None
            raise ChangeServiceError(400, "INVALID_CHANGE_VALUE", f"{label} 不能为空")
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as error:
            raise ChangeServiceError(400, "INVALID_CHANGE_VALUE", f"{label} 必须是数字或 unknown") from error
        if not amount.is_finite():
            raise ChangeServiceError(400, "INVALID_CHANGE_VALUE", f"{label} 必须是有限数字")
        return format(amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize(), "f")

    @staticmethod
    def _public_artifact(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def _public(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        change = dict(row)
        change["baseline"] = json.loads(change.pop("baseline_json"))
        change["proposal"] = json.loads(change.pop("proposal_json"))
        change["impact"] = json.loads(change.pop("impact_json") or "{}")
        change["artifacts"] = [self._public_artifact(item) for item in connection.execute("SELECT artifact_id, artifact_kind, filename, content_type, sha256, size_bytes, created_at FROM change_artifacts WHERE change_id = ? ORDER BY artifact_kind", (row["change_id"],))]
        change["acceptances"] = []
        for item in connection.execute("SELECT acceptance_id, conclusion, checklist_json, evidence_ref, note, actor_id, created_at FROM change_acceptances WHERE change_id = ? ORDER BY created_at", (row["change_id"],)):
            acceptance = dict(item)
            acceptance["checklist"] = json.loads(acceptance.pop("checklist_json"))
            change["acceptances"].append(acceptance)
        return change

    def list_changes(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self._db() as connection:
            rows = connection.execute("SELECT * FROM change_requests WHERE organization_id = ? AND project_id = ? ORDER BY change_no DESC", (organization_id, project_id)).fetchall()
            return {"items": [self._public(connection, row) for row in rows]}

    def get_change(self, organization_id: str, project_id: str, change_id: str) -> dict[str, Any]:
        with self._db() as connection:
            row = connection.execute("SELECT * FROM change_requests WHERE change_id = ? AND organization_id = ? AND project_id = ?", (change_id, organization_id, project_id)).fetchone()
            if row is None:
                raise ChangeServiceError(404, "NOT_FOUND", "变更请求不存在")
            return self._public(connection, row)

    def _baseline(self, connection: sqlite3.Connection, organization_id: str, project_id: str, request: dict[str, Any]) -> dict[str, Any]:
        design_id = str(request.get("design_revision_id") or "").strip()
        geometry_id = str(request.get("geometry_revision_id") or "").strip()
        design = None
        geometry = None
        if design_id:
            design = connection.execute("SELECT design_revision_id, revision_no, input_hash FROM design_revisions WHERE design_revision_id = ? AND organization_id = ? AND project_id = ?", (design_id, organization_id, project_id)).fetchone()
            if design is None:
                raise ChangeServiceError(404, "BASELINE_NOT_FOUND", "设计基线不存在或不属于当前项目")
        else:
            design = connection.execute("SELECT design_revision_id, revision_no, input_hash FROM design_revisions WHERE organization_id = ? AND project_id = ? ORDER BY revision_no DESC LIMIT 1", (organization_id, project_id)).fetchone()
        if geometry_id:
            geometry = connection.execute("SELECT geometry_revision_id, revision_no, input_hash, area_m2_text FROM geometry_revisions WHERE geometry_revision_id = ? AND organization_id = ? AND project_id = ?", (geometry_id, organization_id, project_id)).fetchone()
            if geometry is None:
                raise ChangeServiceError(404, "BASELINE_NOT_FOUND", "几何基线不存在或不属于当前项目")
        else:
            geometry = connection.execute("SELECT geometry_revision_id, revision_no, input_hash, area_m2_text FROM geometry_revisions WHERE organization_id = ? AND project_id = ? ORDER BY revision_no DESC LIMIT 1", (organization_id, project_id)).fetchone()
        return {
            "design_revision_id": design["design_revision_id"] if design else None,
            "design_revision_no": design["revision_no"] if design else None,
            "design_input_hash": design["input_hash"] if design else None,
            "geometry_revision_id": geometry["geometry_revision_id"] if geometry else None,
            "geometry_revision_no": geometry["revision_no"] if geometry else None,
            "geometry_input_hash": geometry["input_hash"] if geometry else None,
            "geometry_area_m2": geometry["area_m2_text"] if geometry else None,
        }

    def create_change(self, organization_id: str, project_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if len(idempotency_key) < 16:
            raise ChangeServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键至少需要 16 个字符")
        title, reason, description = (str(request.get(key) or "").strip() for key in ("title", "reason", "description"))
        if not title or not reason or not description:
            raise ChangeServiceError(400, "INVALID_CHANGE", "标题、原因和变更说明不能为空")
        with self._db(write=True) as connection:
            payload = {"title": title, "reason": reason, "description": description, "issue_id": request.get("issue_id"), "design_revision_id": request.get("design_revision_id"), "geometry_revision_id": request.get("geometry_revision_id"), "quantity_delta_m2": self._decimal(request.get("quantity_delta_m2"), "工程量变化"), "cost_delta_net": self._decimal(request.get("cost_delta_net"), "未税成本变化"), "schedule_delta_days": self._decimal(request.get("schedule_delta_days"), "工期变化")}
            request_hash = self._fingerprint(payload)
            existing = connection.execute("SELECT change_id, payload_json FROM change_events WHERE organization_id = ? AND project_id = ? AND idempotency_key = ?", (organization_id, project_id, idempotency_key)).fetchone()
            if existing:
                if json.loads(existing["payload_json"]).get("request_hash") != request_hash:
                    raise ChangeServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已经用于不同的变更请求")
                return self._public(connection, connection.execute("SELECT * FROM change_requests WHERE change_id = ?", (existing["change_id"],)).fetchone())
            issue_id = str(request.get("issue_id") or "").strip() or None
            if issue_id and connection.execute("SELECT 1 FROM issues WHERE issue_id = ? AND organization_id = ? AND project_id = ?", (issue_id, organization_id, project_id)).fetchone() is None:
                raise ChangeServiceError(404, "ISSUE_NOT_FOUND", "问题不存在或不属于当前项目")
            baseline = self._baseline(connection, organization_id, project_id, request)
            now = now_iso()
            change_id = new_id("change")
            change_no = connection.execute("SELECT COALESCE(MAX(change_no), 0) + 1 AS next_no FROM change_requests WHERE organization_id = ? AND project_id = ?", (organization_id, project_id)).fetchone()["next_no"]
            connection.execute("INSERT INTO change_requests(change_id, organization_id, project_id, change_no, issue_id, title, reason, description, status, design_revision_id, geometry_revision_id, baseline_json, proposal_json, impact_json, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, '{}', 1, ?, ?)", (change_id, organization_id, project_id, change_no, issue_id, title, reason, description, baseline["design_revision_id"], baseline["geometry_revision_id"], self._json(baseline), self._json(payload), now, now))
            event_payload = {"request_hash": request_hash, "payload": payload}
            connection.execute("INSERT INTO change_events(event_id, organization_id, project_id, change_id, event_type, idempotency_key, request_hash, payload_json, actor_id, created_at) VALUES (?, ?, ?, ?, 'change.created', ?, ?, ?, ?, ?)", (new_id("change-event"), organization_id, project_id, change_id, idempotency_key, request_hash, self._json(event_payload), actor_id, now))
            return self._public(connection, connection.execute("SELECT * FROM change_requests WHERE change_id = ?", (change_id,)).fetchone())

    def analyze_change(self, organization_id: str, project_id: str, change_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if len(idempotency_key) < 16:
            raise ChangeServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键至少需要 16 个字符")
        with self._db(write=True) as connection:
            row = connection.execute("SELECT * FROM change_requests WHERE change_id = ? AND organization_id = ? AND project_id = ?", (change_id, organization_id, project_id)).fetchone()
            if row is None:
                raise ChangeServiceError(404, "NOT_FOUND", "变更请求不存在")
            payload = {"expected_version": request.get("expected_version"), "notes": str(request.get("notes") or "")}
            request_hash = self._fingerprint(payload)
            existing = connection.execute("SELECT change_id, event_type, payload_json FROM change_events WHERE organization_id = ? AND project_id = ? AND idempotency_key = ?", (organization_id, project_id, idempotency_key)).fetchone()
            if existing:
                if existing["change_id"] != change_id or existing["event_type"] != "change.analyzed" or json.loads(existing["payload_json"]).get("request_hash") != request_hash:
                    raise ChangeServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已经用于不同的影响分析")
                return self._public(connection, row)
            if row["status"] != "draft":
                raise ChangeServiceError(409, "CHANGE_STATE", "只有草稿变更可以进行影响分析")
            if request.get("expected_version") is not None and int(request["expected_version"]) != int(row["version"]):
                raise ChangeServiceError(409, "STALE_CHANGE_VERSION", "变更请求已变化，请重新读取")
            proposal = json.loads(row["proposal_json"])
            affected: list[dict[str, Any]] = []
            if row["design_revision_id"]:
                affected.extend({"artifact_id": item["artifact_id"], "artifact_kind": item["artifact_kind"], "status": "superseded_by_change"} for item in connection.execute("SELECT artifact_id, artifact_kind FROM design_artifacts WHERE design_revision_id = ?", (row["design_revision_id"],)))
            if row["geometry_revision_id"]:
                affected.extend({"artifact_id": item["artifact_id"], "artifact_kind": item["artifact_kind"], "status": "superseded_by_change"} for item in connection.execute("SELECT artifact_id, artifact_kind FROM spatial_artifacts WHERE geometry_revision_id = ?", (row["geometry_revision_id"],)))
            impact = {"calculation_status": "deterministic_snapshot", "approval_status": "not_approved", "affected_artifacts": affected, "affected_artifact_count": len(affected), "quantity_delta_m2": proposal.get("quantity_delta_m2"), "cost_delta_net": proposal.get("cost_delta_net"), "schedule_delta_days": proposal.get("schedule_delta_days"), "notes": payload["notes"], "new_outputs_required": True}
            now = now_iso()
            connection.execute("UPDATE change_requests SET status = 'analyzed', impact_json = ?, version = version + 1, updated_at = ? WHERE change_id = ?", (self._json(impact), now, change_id))
            event_payload = {"request_hash": request_hash, "payload": payload}
            connection.execute("INSERT INTO change_events(event_id, organization_id, project_id, change_id, event_type, idempotency_key, request_hash, payload_json, actor_id, created_at) VALUES (?, ?, ?, ?, 'change.analyzed', ?, ?, ?, ?, ?)", (new_id("change-event"), organization_id, project_id, change_id, idempotency_key, request_hash, self._json(event_payload), actor_id, now))
            baseline = json.loads(row["baseline_json"])
            root = self.db_path.parent / "projects" / organization_id / project_id / "exports" / "changes" / change_id
            root.mkdir(parents=True, exist_ok=False)
            try:
                result = {"change_id": change_id, "change_no": row["change_no"], "baseline": baseline, "proposal": proposal, "impact": impact, "status": "analyzed", "generated_at": now, "publication_status": "not_approved"}
                json_bytes = (self._json(result) + "\n").encode("utf-8")
                html_bytes = ("<!doctype html><meta charset='utf-8'><title>变更影响分析</title><h1>变更影响分析草稿</h1>" + f"<p>变更 {html.escape(str(row['change_no']))}：{html.escape(row['title'])}</p><p>状态：待人工确认</p><pre>{html.escape(self._json(result))}</pre>").encode("utf-8")
                manifest = {"change_id": change_id, "files": [{"filename": f"change-v{row['change_no']}.json", "sha256": hashlib.sha256(json_bytes).hexdigest()}, {"filename": f"change-impact-v{row['change_no']}.html", "sha256": hashlib.sha256(html_bytes).hexdigest()}]}
                manifest_bytes = (self._json(manifest) + "\n").encode("utf-8")
                for kind, filename, content_type, data in (("change_json", f"change-v{row['change_no']}.json", "application/json", json_bytes), ("impact_html", f"change-impact-v{row['change_no']}.html", "text/html; charset=utf-8", html_bytes), ("manifest_json", f"change-manifest-v{row['change_no']}.json", "application/json", manifest_bytes)):
                    path = root / filename
                    path.write_bytes(data)
                    connection.execute("INSERT INTO change_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id("change-artifact"), change_id, kind, filename, content_type, str(path.relative_to(self.db_path.parent)), hashlib.sha256(data).hexdigest(), len(data), now))
                return self._public(connection, connection.execute("SELECT * FROM change_requests WHERE change_id = ?", (change_id,)).fetchone())
            except Exception:
                shutil.rmtree(root, ignore_errors=True)
                raise

    def accept_change(self, organization_id: str, project_id: str, change_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if len(idempotency_key) < 16:
            raise ChangeServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键至少需要 16 个字符")
        conclusion = str(request.get("conclusion") or "").strip()
        if conclusion not in {"accepted", "rework", "rejected", "unknown"}:
            raise ChangeServiceError(400, "INVALID_ACCEPTANCE", "验收结论不支持")
        evidence_ref = str(request.get("evidence_ref") or "").strip()
        if not evidence_ref:
            raise ChangeServiceError(400, "INVALID_ACCEPTANCE", "验收证据引用不能为空")
        with self._db(write=True) as connection:
            row = connection.execute("SELECT * FROM change_requests WHERE change_id = ? AND organization_id = ? AND project_id = ?", (change_id, organization_id, project_id)).fetchone()
            if row is None:
                raise ChangeServiceError(404, "NOT_FOUND", "变更请求不存在")
            payload = {"conclusion": conclusion, "checklist": request.get("checklist") if isinstance(request.get("checklist"), list) else [], "evidence_ref": evidence_ref, "note": str(request.get("note") or "")}
            request_hash = self._fingerprint(payload)
            existing = connection.execute("SELECT change_id, event_type, payload_json FROM change_events WHERE organization_id = ? AND project_id = ? AND idempotency_key = ?", (organization_id, project_id, idempotency_key)).fetchone()
            if existing:
                if existing["change_id"] != change_id or existing["event_type"] != "change.accepted" or json.loads(existing["payload_json"]).get("request_hash") != request_hash:
                    raise ChangeServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已经用于不同的验收")
                return self._public(connection, row)
            if row["status"] != "analyzed":
                raise ChangeServiceError(409, "CHANGE_NOT_READY", "变更必须先完成影响分析")
            if not payload["checklist"] or any(not isinstance(item, str) or not item.strip() for item in payload["checklist"]):
                raise ChangeServiceError(400, "INVALID_ACCEPTANCE", "至少需要一条非空验收检查项")
            now = now_iso()
            status = "accepted" if conclusion == "accepted" else "rework" if conclusion == "rework" else "rejected" if conclusion == "rejected" else "analyzed"
            connection.execute("INSERT INTO change_acceptances VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id("acceptance"), change_id, organization_id, project_id, conclusion, self._json(payload["checklist"]), evidence_ref, payload["note"], actor_id, now))
            connection.execute("UPDATE change_requests SET status = ?, version = version + 1, updated_at = ? WHERE change_id = ?", (status, now, change_id))
            connection.execute("INSERT INTO change_events(event_id, organization_id, project_id, change_id, event_type, idempotency_key, request_hash, payload_json, actor_id, created_at) VALUES (?, ?, ?, ?, 'change.accepted', ?, ?, ?, ?, ?)", (new_id("change-event"), organization_id, project_id, change_id, idempotency_key, request_hash, self._json({"request_hash": request_hash, "payload": payload}), actor_id, now))
            return self._public(connection, connection.execute("SELECT * FROM change_requests WHERE change_id = ?", (change_id,)).fetchone())

    def get_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict[str, Any], Path]:
        with self._db() as connection:
            row = connection.execute("SELECT a.* FROM change_artifacts a JOIN change_requests c ON c.change_id = a.change_id WHERE a.artifact_id = ? AND c.organization_id = ? AND c.project_id = ?", (artifact_id, organization_id, project_id)).fetchone()
        if row is None:
            raise ChangeServiceError(404, "NOT_FOUND", "变更成果不存在")
        path = (self.db_path.parent / row["relative_path"]).resolve()
        if not path.is_relative_to(self.db_path.parent.resolve()) or not path.is_file() or path.stat().st_size != row["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ChangeServiceError(500, "ARTIFACT_INTEGRITY", "变更成果文件缺失或发生变化")
        return dict(row), path
