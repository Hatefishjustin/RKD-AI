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
from .change_repository import SQLiteChangeRepository
from .requirement_service import RequirementService, RequirementServiceError
from .model_repository import SQLiteModelRepository
from .production_service import ProductionService, measure_floor
from .design_service import DesignService
from .design_rules import DesignError, normalize_program, generate_model, validate_model


class ChangeServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ChangeService:
    """Versioned local change impact and acceptance facts with no external effects."""

    def __init__(self, db_path: str | Path | None, *, repository=None, runtime_root=None, model_repository=None) -> None:
        self.db_path = Path(db_path) if db_path else None
        self.repository = repository or SQLiteChangeRepository(self._db)
        self.runtime_root = Path(runtime_root or self.db_path.parent).resolve() if runtime_root or self.db_path else None
        self.model_repository = model_repository or (SQLiteModelRepository(RequirementService(self.db_path)._db) if self.db_path else None)

    def _model_transaction(self, connection):
        if self.model_repository is None:
            raise ChangeServiceError(501, "MODEL_NOT_CONFIGURED", "模型生产存储未接入")
        return self.model_repository.bind(connection.db, *connection.scope)

    def _production(self):
        return ProductionService(self.db_path, repository=self.model_repository, runtime_root=self.runtime_root)

    @staticmethod
    def _program(raw):
        try:
            return normalize_program(raw)
        except DesignError as error:
            raise ChangeServiceError(error.status, error.code, error.message) from error

    def _current_baseline(self, connection, baseline, frozen=None):
        model = self._model_transaction(connection)
        design, requirement = model.latest_design(), model.current_requirement()
        if (not design or not requirement or design["design_revision_id"] != baseline.get("design_revision_id")
                or design["input_hash"] != baseline.get("design_input_hash")
                or design["requirement_revision_no"] != requirement["current_revision_no"]):
            raise ChangeServiceError(409, "CHANGE_SOURCE_OUTDATED", "变更的设计/需求基线已变化，请基于最新设计重新分析")
        req = model.requirement_revision(requirement["requirement_id"], requirement["current_revision_no"])
        if not req or req["input_hash"] != design["requirement_hash"]:
            raise ChangeServiceError(409, "CHANGE_SOURCE_OUTDATED", "变更的需求来源哈希已变化")
        settings = self._production()._settings(model, *connection.scope)
        production = model.latest_production()
        snapshot = {"design_revision_id": design["design_revision_id"], "design_input_hash": design["input_hash"],
                    "requirement_id": requirement["requirement_id"], "requirement_revision_no": req["revision_no"],
                    "requirement_hash": req["input_hash"], "settings_version": settings["version"],
                    "production_revision_id": production["production_revision_id"] if production else None}
        if frozen is not None and snapshot != frozen:
            raise ChangeServiceError(409, "CHANGE_SOURCE_OUTDATED", "分析后的设计、需求或量价参数已变化，不能应用旧结论")
        return model, design, req, settings, snapshot

    def _preview(self, connection, baseline, program):
        model, design, req, settings, frozen = self._current_baseline(connection, baseline)
        try:
            candidate, validation = validate_model(program, generate_model(program))
            if candidate == json.loads(design["model_json"]):
                raise ChangeServiceError(400, "NO_MODEL_CHANGE", "候选分区与当前模型相同，请填写实际尺寸变化")
            before_quantities, before = measure_floor(json.loads(design["model_json"]), settings, "preview-before")
            quantities, after = measure_floor(candidate, settings, "preview-after")
        except DesignError as error:
            raise ChangeServiceError(error.status, error.code, error.message) from error
        for item in quantities:
            item["quantity_item_id"] = None
            item["source_kind"] = "calculated_from_candidate_model_not_saved"
        delta_cost = (format(Decimal(after["cost_net"]) - Decimal(before["cost_net"]), "f")
                      if before["cost_net"] is not None and after["cost_net"] is not None else None)
        return {"calculation_status": "computed_from_candidate_model", "calculation_baseline": frozen,
                "quantity_delta_m2": format(Decimal(after["quantity"]) - Decimal(before["quantity"]), "f"),
                "cost_delta_net": delta_cost, "quote_before": before, "quote_after": after,
                "preview": {"model": candidate, "validation": validation, "quantities": quantities,
                            "status": "candidate_not_saved", "generation_method": "rule_based_layout"}}

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
        change["artifacts"] = [self._public_artifact(item) for item in connection.query('artifacts', (row['change_id'],))]
        change["acceptances"] = []
        for item in connection.query('acceptances', (row['change_id'],)):
            acceptance = dict(item)
            acceptance["checklist"] = json.loads(acceptance.pop("checklist_json"))
            change["acceptances"].append(acceptance)
        return change

    def list_changes(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as connection:
            rows = connection.query('changes', ()).fetchall()
            return {"items": [self._public(connection, row) for row in rows]}

    def get_change(self, organization_id: str, project_id: str, change_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as connection:
            row = connection.query('change', (change_id,)).fetchone()
            if row is None:
                raise ChangeServiceError(404, "NOT_FOUND", "变更请求不存在")
            return self._public(connection, row)

    def _baseline(self, connection: sqlite3.Connection, organization_id: str, project_id: str, request: dict[str, Any]) -> dict[str, Any]:
        design_id = str(request.get("design_revision_id") or "").strip()
        geometry_id = str(request.get("geometry_revision_id") or "").strip()
        design = None
        geometry = None
        if design_id:
            design = connection.query('design', (design_id,)).fetchone()
            if design is None:
                raise ChangeServiceError(404, "BASELINE_NOT_FOUND", "设计基线不存在或不属于当前项目")
        else:
            design = connection.query('latest_design', ()).fetchone()
        if geometry_id:
            geometry = connection.query('geometry', (geometry_id,)).fetchone()
            if geometry is None:
                raise ChangeServiceError(404, "BASELINE_NOT_FOUND", "几何基线不存在或不属于当前项目")
        else:
            geometry = connection.query('latest_geometry', ()).fetchone()
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
        with self.repository.transaction(organization_id, project_id, write=True) as connection:
            payload = {"title": title, "reason": reason, "description": description, "issue_id": request.get("issue_id"), "design_revision_id": request.get("design_revision_id"), "geometry_revision_id": request.get("geometry_revision_id"), "quantity_delta_m2": self._decimal(request.get("quantity_delta_m2"), "工程量变化"), "cost_delta_net": self._decimal(request.get("cost_delta_net"), "未税成本变化"), "schedule_delta_days": self._decimal(request.get("schedule_delta_days"), "工期变化")}
            if request.get("design_program") is not None:
                payload["design_program"] = self._program(request["design_program"])
            request_hash = self._fingerprint(payload)
            existing = connection.query('event', (idempotency_key,)).fetchone()
            if existing:
                if json.loads(existing["payload_json"]).get("request_hash") != request_hash:
                    raise ChangeServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已经用于不同的变更请求")
                return self._public(connection, connection.query('change', (existing['change_id'],)).fetchone())
            issue_id = str(request.get("issue_id") or "").strip() or None
            if issue_id and connection.query('issue', (issue_id,)).fetchone() is None:
                raise ChangeServiceError(404, "ISSUE_NOT_FOUND", "问题不存在或不属于当前项目")
            baseline = self._baseline(connection, organization_id, project_id, request)
            if "design_program" in payload:
                self._current_baseline(connection, baseline)
            now = now_iso()
            change_id = new_id("change")
            change_no = connection.query('next_no', ()).fetchone()["next_no"]
            connection.query('insert_change', (change_id, change_no, issue_id, title, reason, description, baseline['design_revision_id'], baseline['geometry_revision_id'], self._json(baseline), self._json(payload), now, now))
            event_payload = {"request_hash": request_hash, "payload": payload}
            connection.query('write_event', (new_id('change-event'), change_id, 'change.created', idempotency_key, request_hash, self._json(event_payload), actor_id, now))
            return self._public(connection, connection.query('change', (change_id,)).fetchone())

    def analyze_change(self, organization_id: str, project_id: str, change_id: str, actor_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if len(idempotency_key) < 16:
            raise ChangeServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键至少需要 16 个字符")
        with self.repository.transaction(organization_id, project_id, write=True) as connection:
            row = connection.query('change', (change_id,)).fetchone()
            if row is None:
                raise ChangeServiceError(404, "NOT_FOUND", "变更请求不存在")
            payload = {"expected_version": request.get("expected_version"), "notes": str(request.get("notes") or "")}
            request_hash = self._fingerprint(payload)
            existing = connection.query('event', (idempotency_key,)).fetchone()
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
                affected.extend({"artifact_id": item["artifact_id"], "artifact_kind": item["artifact_kind"], "status": "superseded_by_change"} for item in connection.query('design_artifacts', (row['design_revision_id'],)))
            if row["geometry_revision_id"]:
                affected.extend({"artifact_id": item["artifact_id"], "artifact_kind": item["artifact_kind"], "status": "superseded_by_change"} for item in connection.query('geometry_artifacts', (row['geometry_revision_id'],)))
            impact = {"calculation_status": "deterministic_snapshot", "approval_status": "not_approved", "affected_artifacts": affected, "affected_artifact_count": len(affected), "quantity_delta_m2": proposal.get("quantity_delta_m2"), "cost_delta_net": proposal.get("cost_delta_net"), "schedule_delta_days": proposal.get("schedule_delta_days"), "notes": payload["notes"], "new_outputs_required": True}
            if proposal.get("design_program"):
                impact.update(self._preview(connection, json.loads(row["baseline_json"]), proposal["design_program"]))
                current = self._model_transaction(connection).latest_production()
                if current:
                    affected.extend({"artifact_id": a["artifact_id"], "artifact_kind": a["artifact_kind"], "status": "affected_if_applied"}
                                    for a in self._model_transaction(connection).production_artifacts(current["production_revision_id"]))
                    impact["affected_artifact_count"] = len(affected)
            else:
                impact["quantity_cost_source"] = "manual_input_unverified"
            now = now_iso()
            connection.query('analyze', (self._json(impact), now, change_id))
            event_payload = {"request_hash": request_hash, "payload": payload}
            connection.query('write_event', (new_id('change-event'), change_id, 'change.analyzed', idempotency_key, request_hash, self._json(event_payload), actor_id, now))
            baseline = json.loads(row["baseline_json"])
            root = self.runtime_root / "projects" / "change-exports" / change_id
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
                    connection.query('insert_artifact', (new_id('change-artifact'), change_id, kind, filename, content_type, str(path.relative_to(self.runtime_root)), hashlib.sha256(data).hexdigest(), len(data), now))
                return self._public(connection, connection.query('change', (change_id,)).fetchone())
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
        with self.repository.transaction(organization_id, project_id, write=True) as connection:
            row = connection.query('change', (change_id,)).fetchone()
            if row is None:
                raise ChangeServiceError(404, "NOT_FOUND", "变更请求不存在")
            payload = {"conclusion": conclusion, "checklist": request.get("checklist") if isinstance(request.get("checklist"), list) else [], "evidence_ref": evidence_ref, "note": str(request.get("note") or "")}
            if json.loads(row["proposal_json"]).get("design_program"):
                payload["expected_version"] = request.get("expected_version")
            request_hash = self._fingerprint(payload)
            existing = connection.query('event', (idempotency_key,)).fetchone()
            if existing:
                if existing["change_id"] != change_id or existing["event_type"] != "change.accepted" or json.loads(existing["payload_json"]).get("request_hash") != request_hash:
                    raise ChangeServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已经用于不同的验收")
                return self._public(connection, row)
            if row["status"] != "analyzed":
                raise ChangeServiceError(409, "CHANGE_NOT_READY", "变更必须先完成影响分析")
            proposal, impact = json.loads(row["proposal_json"]), json.loads(row["impact_json"])
            if proposal.get("design_program"):
                if request.get("expected_version") != row["version"]:
                    raise ChangeServiceError(409, "STALE_CHANGE_VERSION", "请重新读取当前分析版本后记录结论")
                self._current_baseline(connection, json.loads(row["baseline_json"]), impact.get("calculation_baseline"))
            if not payload["checklist"] or any(not isinstance(item, str) or not item.strip() for item in payload["checklist"]):
                raise ChangeServiceError(400, "INVALID_ACCEPTANCE", "至少需要一条非空验收检查项")
            now = now_iso()
            status = "accepted" if conclusion == "accepted" else "rework" if conclusion == "rework" else "rejected" if conclusion == "rejected" else "analyzed"
            connection.query('insert_acceptance', (new_id('acceptance'), change_id, conclusion, self._json(payload['checklist']), evidence_ref, payload['note'], actor_id, now))
            connection.query('status', (status, now, change_id))
            connection.query('write_event', (new_id('change-event'), change_id, 'change.accepted', idempotency_key, request_hash, self._json({'request_hash': request_hash, 'payload': payload}), actor_id, now))
            return self._public(connection, connection.query('change', (change_id,)).fetchone())

    def reproduce(self, organization_id, project_id, change_id, actor_id, request, idempotency_key):
        if len(idempotency_key) < 16:
            raise ChangeServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键至少需要 16 个字符")
        request_hash = self._fingerprint({"expected_version": request.get("expected_version")})
        with self.repository.transaction(organization_id, project_id, write=True) as connection:
            row = connection.query("change", (change_id,)).fetchone()
            if not row:
                raise ChangeServiceError(404, "NOT_FOUND", "变更请求不存在")
            event = connection.query("event", (idempotency_key,)).fetchone()
            if event:
                if (event["change_id"] != change_id or event["event_type"] != "change.reproduced"
                        or json.loads(event["payload_json"]).get("request_hash") != request_hash):
                    raise ChangeServiceError(409, "IDEMPOTENCY_CONFLICT", "幂等键已用于其他再生产请求")
                return self._public(connection, row)
            proposal, impact = json.loads(row["proposal_json"]), json.loads(row["impact_json"])
            if row["status"] != "accepted" or not proposal.get("design_program"):
                raise ChangeServiceError(409, "REPRODUCTION_NOT_READY", "需要结构化尺寸变更及责任人的通过结论")
            if impact.get("reproduction"):
                raise ChangeServiceError(409, "CHANGE_ALREADY_REPRODUCED", "本次变更已生成新草稿")
            if request.get("expected_version") != row["version"]:
                raise ChangeServiceError(409, "STALE_CHANGE_VERSION", "变更版本已变化，请重新读取")
            model, design, req, settings, frozen = self._current_baseline(connection, json.loads(row["baseline_json"]), impact.get("calculation_baseline"))
            now = now_iso()
            reason = f"变更 {row['change_no']} 再生产：{row['title']}"[:500]
            requirement_service = RequirementService(self.db_path, repository=self.model_repository.requirements)
            try:
                revised = requirement_service.update_draft(organization_id, project_id, actor_id,
                    {"expected_revision": req["revision_no"], "design_program": proposal["design_program"],
                     "design_notes": json.loads(req["content_json"]).get("design_notes", ""), "change_reason": reason}, connection=connection.db)
                saved = DesignService(self.db_path, repository=self.model_repository, runtime_root=self.runtime_root).create_design(
                    organization_id, project_id, actor_id, {"expected_revision": design["revision_no"],
                    "requirement_revision_no": revised["revision_no"], "change_reason": reason}, connection=connection.db)
            except (DesignError, RequirementServiceError) as error:
                raise ChangeServiceError(error.status, error.code, error.message) from error
            production = model.latest_production()
            computed = json.loads(production["quote_json"])
            if computed != impact["quote_after"]:
                raise ChangeServiceError(409, "REPRODUCTION_MISMATCH", "新成果与已复核的量价预览不一致，整笔保存已取消")
            acceptances = connection.query("acceptances", (change_id,)).fetchall()
            accepted = next(a for a in reversed(acceptances) if a["conclusion"] == "accepted")
            result = {"requirement_id": revised["requirement_id"], "requirement_revision_no": revised["revision_no"],
                      "design_revision_id": saved["design_revision_id"], "design_revision_no": saved["revision_no"],
                      "production_revision_id": production["production_revision_id"], "production_revision_no": production["revision_no"],
                      "acceptance_id": accepted["acceptance_id"], "accepted_by": accepted["actor_id"], "applied_by": actor_id,
                      "created_at": now, "status": "draft_not_published", "external_effects_enabled": False}
            impact["reproduction"] = result
            connection.query("reproduction", (self._json(impact), now, change_id))
            connection.query("write_event", (new_id("change-event"), change_id, "change.reproduced", idempotency_key,
                                            request_hash, self._json({"request_hash": request_hash, "result": result}), actor_id, now))
            return self._public(connection, connection.query("change", (change_id,)).fetchone())

    def get_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict[str, Any], Path]:
        with self.repository.transaction(organization_id, project_id) as connection:
            row = connection.query('artifact', (artifact_id,)).fetchone()
        if row is None:
            raise ChangeServiceError(404, "NOT_FOUND", "变更成果不存在")
        path = (self.runtime_root / row["relative_path"]).resolve()
        if not path.is_relative_to(self.runtime_root.resolve()) or not path.is_file() or path.stat().st_size != row["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ChangeServiceError(500, "ARTIFACT_INTEGRITY", "变更成果文件缺失或发生变化")
        return dict(row), path
