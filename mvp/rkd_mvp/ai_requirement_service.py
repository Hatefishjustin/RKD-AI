"""AI-DESIGN-01a/01b/01d: persistent requirement-understanding tasks.

This slice records a real provider configuration and call attempt, produces a
versioned candidate brief, and lets a human edit/save it. It deliberately does
not create designs, quantities, quotes, purchase orders, or releases. A local
synthetic adapter is clearly marked as non-AI; a missing real channel fails
instead of silently falling back to rules.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .ai_model_provider import (
    AIProviderConfig,
    ProviderFailure,
    SCHEMA_VERSION,
    build_provider,
    load_provider_config,
    unknown_cost,
    unknown_usage,
)
from .models import new_id, now_iso

CONTEXT_VERSION = "rkd-ai-context-manifest.v1"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "v1" / "ai-design-brief.schema.json"


class AIRequirementServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _value(value: Any, unit: str, known_status: str, source_refs: list[str],
           unknown_reason: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"value": value, "unit": unit, "known_status": known_status, "source_refs": source_refs}
    if known_status == "unknown" or value is None:
        result["unknown_reason"] = unknown_reason or "没有可核验来源"
    return result


class AIRequirementService:
    def __init__(self, repository: Any, requirement_service: Any, *, config: AIProviderConfig | None = None,
                 provider_factory: Callable[[AIProviderConfig], Any] | None = None,
                 start_workers: bool = True, extraction_service: Any | None = None) -> None:
        self.repository = repository
        self.requirements = requirement_service
        self.config = config or load_provider_config()
        self.provider_factory = provider_factory or (lambda resolved: build_provider(resolved))
        self.start_workers = start_workers
        # Optional 01c source-content reader. When absent the context manifest
        # keeps its original metadata-only semantics for old data and tests.
        self.extraction_service = extraction_service
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)
        self._lock = threading.Lock()
        self._active_jobs: set[str] = set()

    def _provider(self, config: AIProviderConfig) -> Any:
        return self.provider_factory(config)

    def _active(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._active_jobs)

    def _recover(self, organization_id: str, project_id: str) -> None:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            tx.recover_running(now_iso(), self._active())

    def _requirement(self, organization_id: str, project_id: str, actor_id: str) -> dict[str, Any]:
        if self.requirements is None:
            raise AIRequirementServiceError(501, "REQUIREMENTS_NOT_CONFIGURED", "需求存储未配置")
        current = self.requirements.get_current(organization_id, project_id)
        if current is None:
            current = self.requirements.create_draft(organization_id, project_id, actor_id, "AI 需求理解前生成来源草稿")
        return current

    def _source_catalog(self, requirement: dict[str, Any],
                        summaries: dict[str, dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
        synthetic = {"source_id": "synthetic-input", "origin_kind": "manual_input",
                     "locator": "request.natural_language", "content_status": "provided",
                     "evidence_status": "unverified"}
        catalog = [synthetic]
        conflicts: dict[str, str] = {}
        summaries = summaries or {}
        for ref in requirement.get("source_refs", []):
            file_id = None
            if ref.get("type") == "project_decision" and ref.get("key"):
                source_id = f"decision:{ref['key']}"
                origin_kind = "project_decision"
                locator = f"project_decision:{ref['key']}"
                label = str(ref.get("key"))
            elif ref.get("file_id"):
                file_id = str(ref["file_id"])
                source_id = f"file:{file_id}"
                origin_kind = "file_asset_metadata"
                locator = f"file_asset:{file_id}"
                label = str(ref.get("filename") or file_id)
            else:
                continue
            if any(item["source_id"] == source_id for item in catalog):
                continue
            entry = {"source_id": source_id, "origin_kind": origin_kind, "locator": locator,
                     "content_status": "metadata_only_not_parsed", "evidence_status": "unverified"}
            summary = summaries.get(file_id) if file_id else None
            if summary:
                entry.update({
                    "origin_kind": "file_content_extraction",
                    "content_status": "content_extracted",
                    "content_locator": summary["content_locator"],
                    "extraction_id": summary["extraction_id"],
                    "segment_count": summary["segment_count"],
                })
            catalog.append(entry)
            if ref.get("source_conflict"):
                conflicts[source_id] = f"{label} 存在来源口径冲突：{ref['source_conflict']}"
        return catalog, conflicts

    def _context_manifest(self, organization_id: str, project_id: str, actor_id: str,
                          text: str, request: dict[str, Any]) -> dict[str, Any]:
        requirement = self._requirement(organization_id, project_id, actor_id)
        summaries: dict[str, dict[str, Any]] = {}
        if self.extraction_service is not None:
            summaries = self.extraction_service.summaries(organization_id, project_id)
        catalog, conflicts = self._source_catalog(requirement, summaries)
        available = {item["source_id"] for item in catalog if item["source_id"] != "synthetic-input"}
        raw_selected = request.get("selected_source_ids")
        if raw_selected is None:
            selected = sorted(available)
        elif isinstance(raw_selected, list) and all(isinstance(item, str) for item in raw_selected):
            selected = list(dict.fromkeys(raw_selected))
        else:
            raise AIRequirementServiceError(400, "INVALID_SOURCE_SELECTION", "资料选择必须是来源 ID 字符串列表")
        unknown = [item for item in selected if item not in available]
        if unknown:
            raise AIRequirementServiceError(400, "UNKNOWN_SOURCE_ID", "选择了不属于当前项目的来源")
        source_refs = [item for item in catalog if item["source_id"] == "synthetic-input" or item["source_id"] in selected]
        content = requirement.get("content", {})
        budget_content = content.get("budget", {}) if isinstance(content.get("budget"), dict) else {}
        budget_source = "decision:contract_target_gross_cny"
        raw_budget = budget_content.get("contract_target_gross_cny", "unknown")
        if raw_budget not in {None, "", "unknown"} and budget_source in selected:
            budget = _value(str(raw_budget), "CNY", "known", [budget_source])
        else:
            budget = _value(None, "CNY", "unknown", [], "合同目标未进入本次允许上下文，或尚未确认")
        scope = content.get("scope", {}) if isinstance(content.get("scope"), dict) else {}
        excluded = scope.get("excluded_scopes", [])
        if not isinstance(excluded, list):
            excluded = [str(excluded)] if excluded not in {None, "", "unknown"} else []
        extracted_selected = [item for item in source_refs if item.get("content_status") == "content_extracted"]
        if self.extraction_service is None:
            source_status = "project_metadata_only" if selected else "synthetic_input_only"
        elif not selected:
            source_status = "synthetic_input_only"
        elif extracted_selected:
            source_status = "selected_content_extracted"
        else:
            source_status = "selected_content_not_available"
        project_context = {
            "project_type": str(content.get("project_type") or "unknown"),
            "service_scope": "内部设计草稿；正式服务范围待确认",
            "budget": budget,
            "excluded_scopes": [str(item) for item in excluded],
            "source_status": source_status,
        }
        source_conflicts = [
            {"conflict_id": f"source-conflict-{index + 1}", "statement": statement,
             "resolution": "pending", "source_refs": [source_id]}
            for index, (source_id, statement) in enumerate(sorted(conflicts.items()))
            if source_id in selected
        ]
        full = {
            "schema_version": CONTEXT_VERSION,
            "requirement_id": requirement.get("requirement_id"),
            "requirement_revision_no": requirement.get("revision_no"),
            "source_refs": source_refs,
            "project_context": project_context,
            "source_conflicts": source_conflicts,
            "content_reading": (
                "local_file_text_segments_available_external_send_not_approved"
                if extracted_selected else "original_file_contents_not_parsed_in_this_slice"
            ),
            "local_source_content": [
                {"source_id": item["source_id"], "extraction_id": item["extraction_id"],
                 "segment_count": item["segment_count"], "content_locator": item["content_locator"]}
                for item in extracted_selected
            ],
            "external_project_context_allowed": self.config.external_context_allowed,
        }
        synthetic_only_source = source_refs[0]
        if self.config.real_model and not self.config.external_context_allowed:
            provider_manifest = {
                "schema_version": CONTEXT_VERSION,
                "requirement_id": full["requirement_id"],
                "requirement_revision_no": full["requirement_revision_no"],
                "source_refs": [synthetic_only_source],
                "project_context": {
                    "project_type": "unknown",
                    "service_scope": "内部设计草稿；项目资料未获准外发",
                    "budget": _value(None, "CNY", "unknown", [], "项目资料未获准外发，不重复询问已知口径"),
                    "excluded_scopes": [],
                    "source_status": "synthetic_input_only",
                },
                "source_conflicts": [],
                "content_reading": "synthetic_input_only",
                "external_project_context_allowed": False,
            }
        else:
            # A JSON round-trip makes a deep copy and prevents a self-reference
            # when provider_manifest is nested back into the stored manifest.
            provider_manifest = json.loads(_json(full))
            # The local extraction index is an operator-facing locator list,
            # never model input; only the approved source_refs may be sent.
            provider_manifest.pop("local_source_content", None)
        full["provider_manifest"] = provider_manifest
        return full

    def _validate_brief(self, brief: Any, manifest: dict[str, Any], config: AIProviderConfig,
                        input_hash: str, *, expected_source_kind: str = "model_output",
                        expected_revision: int = 1) -> dict[str, Any]:
        errors = sorted(self.validator.iter_errors(brief), key=lambda error: list(error.path))
        if errors:
            detail = "；".join(f"{'.'.join(str(part) for part in error.path) or 'root'}: {error.message}"
                              for error in errors[:3])
            raise ProviderFailure(category="validation", code="SCHEMA_INVALID",
                                  message=f"结构化任务书不符合版本化契约：{detail}")
        provider_manifest = manifest.get("provider_manifest", manifest)
        allowed = {item["source_id"] for item in provider_manifest.get("source_refs", [])}
        used: set[str] = set()

        for source in brief["source_refs"]:
            if source["source_id"] not in allowed:
                raise ProviderFailure(category="validation", code="UNKNOWN_SOURCE_ID",
                                      message="任务书来源清单引用了未授权的来源 ID")

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                refs = node.get("source_refs")
                if isinstance(refs, list) and all(isinstance(item, str) for item in refs):
                    used.update(refs)
                if node.get("known_status") == "unknown" and node.get("value") not in {None}:
                    raise ProviderFailure(category="validation", code="UNKNOWN_VALUE_FILLED",
                                          message="未知值不得填写数字或文本")
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(brief)
        if used - allowed:
            raise ProviderFailure(category="validation", code="UNKNOWN_SOURCE_ID",
                                  message="任务书引用了未授权的来源 ID")
        generation = brief["generation"]
        if (generation["real_model"] != config.real_model
                or generation["provider_kind"] != config.kind
                or generation["model_id"] != config.model_id
                or generation["config_hash"] != config.fingerprint()
                or generation["input_hash"] != input_hash):
            raise ProviderFailure(category="validation", code="RUN_METADATA_MISMATCH",
                                  message="任务书的模型运行记录与作业快照不一致")
        if brief["source_kind"] != expected_source_kind or brief["revision_no"] != expected_revision:
            raise ProviderFailure(category="validation", code="REVISION_METADATA_MISMATCH",
                                  message="任务书版本元数据不一致")
        if brief["cost"]["total_project_estimate"]["known_status"] != "unknown" or brief["cost"]["total_project_estimate"]["value"] is not None:
            raise ProviderFailure(category="validation", code="UNSUPPORTED_TOTAL_ESTIMATE",
                                  message="本切片不允许把候选任务书写成完整项目估价")
        checked = json.loads(_json(brief))
        checked["validation_status"] = "structural_check_passed"
        return checked

    def _config_record(self) -> dict[str, Any]:
        record = self.config.public()
        record["config_hash"] = self.config.fingerprint()
        return record

    def submit(self, organization_id: str, project_id: str, actor_id: str,
               request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        text = request.get("natural_language")
        if not isinstance(text, str) or not text.strip() or len(text) > self.config.max_input_chars:
            raise AIRequirementServiceError(400, "INVALID_NATURAL_LANGUAGE", f"需求文字需为 1—{self.config.max_input_chars} 字")
        text = text.strip()
        if not isinstance(idempotency_key, str) or len(idempotency_key) < 8 or len(idempotency_key) > 255:
            raise AIRequirementServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键需为 8—255 字符")
        self._recover(organization_id, project_id)
        manifest = self._context_manifest(organization_id, project_id, actor_id, text, request)
        config_record = self._config_record()
        input_payload = {"natural_language": text, "context_manifest": manifest, "config": config_record,
                         "schema_version": SCHEMA_VERSION}
        input_hash = _digest(input_payload)
        now = now_iso()
        job_id = new_id("ai-brief-job")
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            existing = tx.job_by_key(idempotency_key)
            if existing:
                if existing["input_hash"] != input_hash:
                    raise AIRequirementServiceError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键对应了不同输入")
                return {"item": existing, "status": existing["status"]}
            tx.insert_job({
                "job_id": job_id, "job_type": "requirement_understanding", "status": "queued", "phase": "queued",
                "attempt_count": 0, "input_hash": input_hash, "context_manifest": manifest,
                "request": {"natural_language": text, "selected_source_ids": [item["source_id"] for item in manifest["source_refs"][1:]]},
                "config": config_record, "output_brief_id": None, "error_code": None, "error_message": None,
                "idempotency_key": idempotency_key, "actor_id": actor_id, "created_at": now, "updated_at": now,
            })
            job = tx.job(job_id)
        if self.config.kind == "unconfigured" or self.config.configuration_errors:
            self._configuration_failure(organization_id, project_id, job_id, config_record)
            with self.repository.transaction(organization_id, project_id) as tx:
                job = tx.job(job_id)
        else:
            self._launch(organization_id, project_id, job_id)
        return {"item": job, "status": job["status"]}

    def _configuration_failure(self, organization_id: str, project_id: str, job_id: str,
                               config_record: dict[str, Any]) -> None:
        now = now_iso()
        message = "真实模型通道未配置；已保留失败任务，未生成规则替代结果。"
        if config_record.get("configuration_errors"):
            message = "模型配置不完整：" + "；".join(config_record["configuration_errors"])
        error = {"code": "MODEL_NOT_CONFIGURED", "category": "configuration", "message": message}
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            job = tx.job(job_id)
            if not job or job["status"] != "queued":
                return
            tx.update_job(job_id, status="failed", phase="configuration_failed", updated_at=now,
                          error_code="MODEL_NOT_CONFIGURED", error_message=message)
            tx.insert_run({
                "run_id": new_id("ai-run"), "job_id": job_id,
                "attempt_no": int(job["attempt_count"]) + 1,
                "provider_kind": "unconfigured", "provider_name": "未配置真实模型通道", "model_id": None,
                "adapter_version": self.config.adapter_version, "prompt_version": self.config.prompt_version,
                "config_hash": config_record["config_hash"], "real_model": False, "status": "failed",
                "provider_request_id": None, "usage": {**unknown_usage(), **unknown_cost()},
                "cost": unknown_cost(), "error": error, "started_at": now, "finished_at": now,
            })

    def _launch(self, organization_id: str, project_id: str, job_id: str) -> None:
        if not self.start_workers:
            return
        with self._lock:
            self._active_jobs.add(job_id)
        thread = threading.Thread(target=self._run_job, args=(organization_id, project_id, job_id),
                                  name=f"rkd-ai-brief-{job_id}", daemon=True)
        thread.start()

    def _run_job(self, organization_id: str, project_id: str, job_id: str) -> None:
        try:
            config = self.config
            now = now_iso()
            run_id = new_id("ai-run")
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                job = tx.job(job_id)
                if not job or job["status"] != "queued":
                    return
                attempt = int(job["attempt_count"]) + 1
                tx.start_job(job_id, attempt, now)
                tx.insert_run({
                    "run_id": run_id, "job_id": job_id, "attempt_no": attempt,
                    "provider_kind": config.kind, "provider_name": config.name, "model_id": config.model_id,
                    "adapter_version": config.adapter_version, "prompt_version": config.prompt_version,
                    "config_hash": config.fingerprint(), "real_model": config.real_model, "status": "running",
                    "provider_request_id": None, "usage": {**unknown_usage(), **unknown_cost()},
                    "cost": unknown_cost(), "error": None, "started_at": now, "finished_at": None,
                })
            saved_config = AIProviderConfig.from_public(job["config"])
            provider = self._provider(saved_config)
            transport_attempts = 0
            while True:
                transport_attempts += 1
                try:
                    result = provider.generate(
                        text=job["request"]["natural_language"],
                        manifest=job["context_manifest"]["provider_manifest"],
                        input_hash=job["input_hash"], config_hash=saved_config.fingerprint(), generated_at=now,
                    )
                    # A timed-out call may already have been billed. Record the
                    # transport attempt count in the run's usage, never hide it.
                    result.usage = {**result.usage, "transport_attempts": transport_attempts}
                    brief = self._validate_brief(result.brief, job["context_manifest"], saved_config, job["input_hash"])
                    break
                except ProviderFailure as failure:
                    if failure.retryable and failure.category == "network" and transport_attempts < 2:
                        continue  # exactly one bounded retry, no infinite billing loop
                    self._finish_failure(organization_id, project_id, job_id, run_id, attempt, failure)
                    return
                except Exception:
                    self._finish_failure(organization_id, project_id, job_id, run_id, attempt,
                                         ProviderFailure(category="execution", code="UNEXPECTED_PROVIDER_ERROR",
                                                         message="模型执行出现未分类错误，未生成候选结果"))
                    return
            self._finish_success(organization_id, project_id, job_id, run_id, attempt, brief, result)
        finally:
            with self._lock:
                self._active_jobs.discard(job_id)

    def _finish_failure(self, organization_id: str, project_id: str, job_id: str, run_id: str,
                        attempt: int, failure: ProviderFailure) -> None:
        now = now_iso()
        error = {"code": failure.code, "category": failure.category, "message": failure.message}
        usage = {**unknown_usage(), **unknown_cost(), **failure.usage}
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            job = tx.job(job_id)
            if not job:
                return
            if job["status"] != "running" or int(job["attempt_count"]) != attempt:
                tx.finish_run(run_id, status="late_result_discarded", finished_at=now, usage=usage,
                              cost=failure.cost, error={"code": "LATE_RESULT_DISCARDED", "category": "conflict",
                                                        "message": "作业状态已变化，迟到的模型结果未写入"},
                              provider_request_id=failure.provider_request_id)
                return
            tx.update_job(job_id, status="failed", phase="failed", updated_at=now,
                          error_code=failure.code, error_message=failure.message)
            tx.finish_run(run_id, status="failed", finished_at=now, usage=usage, cost=failure.cost,
                          error=error, provider_request_id=failure.provider_request_id)

    def _finish_success(self, organization_id: str, project_id: str, job_id: str, run_id: str,
                        attempt: int, brief: dict[str, Any], result: Any) -> None:
        now = now_iso()
        brief_id = new_id("ai-brief")
        usage = {**unknown_usage(), **unknown_cost(), **result.usage}
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            job = tx.job(job_id)
            if not job:
                return
            if job["status"] != "running" or int(job["attempt_count"]) != attempt:
                tx.finish_run(run_id, status="late_result_discarded", finished_at=now, usage=usage,
                              cost=result.cost, error={"code": "LATE_RESULT_DISCARDED", "category": "conflict",
                                                       "message": "作业状态已变化，迟到的模型结果未写入"},
                              provider_request_id=result.provider_request_id)
                return
            tx.insert_brief({
                "brief_id": brief_id, "job_id": job_id, "revision_no": 1,
                "schema_version": SCHEMA_VERSION, "brief": brief, "input_hash": job["input_hash"],
                "source_kind": "model_output", "change_reason": "模型理解生成候选任务书",
                "actor_id": job["actor_id"], "created_at": now,
            })
            tx.update_job(job_id, status="succeeded", phase="completed", updated_at=now,
                          output_brief_id=brief_id)
            tx.finish_run(run_id, status="succeeded", finished_at=now, usage=usage, cost=result.cost,
                          error=None, provider_request_id=result.provider_request_id)

    def status(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._recover(organization_id, project_id)
        with self.repository.transaction(organization_id, project_id) as tx:
            jobs = tx.jobs()
            latest_job = tx.latest_succeeded_job()
            current = None
            if latest_job:
                brief = tx.latest_brief(latest_job["job_id"])
                if brief:
                    current = {"job": latest_job, "brief": brief, "revisions": tx.briefs(latest_job["job_id"]),
                               "runs": tx.runs(latest_job["job_id"])}
            return {"provider": self.config.public(), "configured": self.config.kind != "unconfigured",
                    "item": current, "jobs": jobs}

    def get_job(self, organization_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        self._recover(organization_id, project_id)
        with self.repository.transaction(organization_id, project_id) as tx:
            job = tx.job(job_id)
            if not job:
                raise AIRequirementServiceError(404, "NOT_FOUND", "AI 需求理解任务不存在")
            return {"item": {**job, "runs": tx.runs(job_id), "briefs": tx.briefs(job_id)}}

    def retry(self, organization_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        self._recover(organization_id, project_id)
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            job = tx.job(job_id)
            if not job:
                raise AIRequirementServiceError(404, "NOT_FOUND", "AI 需求理解任务不存在")
            if job["status"] not in {"failed", "cancelled"}:
                raise AIRequirementServiceError(409, "JOB_STATE", "只有失败或取消的任务可以显式重试")
            tx.update_job(job_id, status="queued", phase="queued", updated_at=now_iso())
            job = tx.job(job_id)
        if self.config.kind == "unconfigured" or self.config.configuration_errors:
            self._configuration_failure(organization_id, project_id, job_id, self._config_record())
        else:
            self._launch(organization_id, project_id, job_id)
        return {"item": job}

    def cancel(self, organization_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            job = tx.job(job_id)
            if not job:
                raise AIRequirementServiceError(404, "NOT_FOUND", "AI 需求理解任务不存在")
            if job["status"] not in {"queued", "running"}:
                raise AIRequirementServiceError(409, "JOB_STATE", "任务已结束，不能取消")
            tx.update_job(job_id, status="cancelled", phase="failed", updated_at=now_iso(),
                          error_code="CANCELLED_BY_USER", error_message="用户取消任务")
            return {"item": tx.job(job_id)}

    def save_brief(self, organization_id: str, project_id: str, actor_id: str,
                   request: dict[str, Any]) -> dict[str, Any]:
        job_id = request.get("job_id")
        expected = request.get("expected_revision")
        brief = request.get("brief")
        reason = str(request.get("change_reason", "")).strip()
        if not isinstance(job_id, str) or not isinstance(expected, int) or not isinstance(brief, dict) or not 1 <= len(reason) <= 500:
            raise AIRequirementServiceError(400, "INVALID_BRIEF_REVISION", "请提供任务、预期版本、任务书和修改理由")
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            job = tx.job(job_id)
            if not job or job["status"] != "succeeded":
                raise AIRequirementServiceError(409, "BRIEF_SOURCE_UNAVAILABLE", "只能修订成功任务的候选任务书")
            latest_job = tx.latest_succeeded_job()
            if not latest_job or latest_job["job_id"] != job_id:
                raise AIRequirementServiceError(409, "STALE_JOB", "已出现更新的成功任务，旧任务书不能覆盖当前视图")
            current = tx.latest_brief(job_id)
            if not current or current["revision_no"] != expected:
                raise AIRequirementServiceError(409, "STALE_BRIEF_REVISION", "任务书版本已变化，请重新读取")
            config = AIProviderConfig.from_public(job["config"])
            try:
                checked = self._validate_brief(brief, job["context_manifest"], config, job["input_hash"],
                                               expected_source_kind=current["brief"]["source_kind"],
                                               expected_revision=current["revision_no"])
            except ProviderFailure as failure:
                raise AIRequirementServiceError(422, failure.code, failure.message) from failure
            original = current["brief"]
            revised = json.loads(_json(checked))
            for field in ("schema_version", "generation", "project_context", "source_refs", "lifecycle_status", "validation_status"):
                revised[field] = original[field]
            revised["source_kind"] = "human_edit"
            revised["revision_no"] = expected + 1
            brief_id = new_id("ai-brief")
            tx.insert_brief({
                "brief_id": brief_id, "job_id": job_id, "revision_no": expected + 1,
                "schema_version": SCHEMA_VERSION, "brief": revised, "input_hash": job["input_hash"],
                "source_kind": "human_edit", "change_reason": reason, "actor_id": actor_id,
                "created_at": now_iso(),
            })
            tx.update_job(job_id, status="succeeded", phase="completed", updated_at=now_iso(),
                          output_brief_id=brief_id)
            return {"item": tx.latest_brief(job_id)}

    def wait_for_job(self, organization_id: str, project_id: str, job_id: str,
                     timeout_seconds: float = 5.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            job = self.get_job(organization_id, project_id, job_id)["item"]
            if job["status"] in {"succeeded", "failed", "cancelled"}:
                return job
            time.sleep(0.02)
        raise AIRequirementServiceError(504, "JOB_TIMEOUT", "等待 AI 需求理解任务超时")

    def wait_for_idle(self, timeout_seconds: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and self._active():
            time.sleep(0.02)
