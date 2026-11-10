"""AI-DESIGN-02/03 candidate, feedback and adoption service.

The service stores candidate options separately from the current design,
quantity, quote, purchase, approval, and release facts. A local synthetic
design adapter is clearly marked as non-AI; it is an engineering bridge until a
real design provider is configured and verified.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .ai_design_geometry import (
    GeometryError, candidates_are_structurally_different, render_svg,
    structure_signature, validate_model,
)
from .ai_design_option_provider import (
    DesignOptionConfig, DesignOptionProviderFailure, build_design_option_provider,
    load_design_option_config,
)
from .models import new_id, now_iso

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "v1" / "ai-design-option.schema.json"


class AIDesignOptionServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class AIDesignOptionService:
    def __init__(self, repository: Any, brief_provider: Callable[[str, str], dict[str, Any] | None],
                 context_provider: Callable[[str, str], dict[str, Any]], runtime_root: str | Path,
                 *, config: DesignOptionConfig | None = None, provider: Any | None = None,
                 start_workers: bool = True) -> None:
        self.repository = repository
        self.brief_provider = brief_provider
        self.context_provider = context_provider
        self.runtime_root = Path(runtime_root).resolve()
        self.config = config or load_design_option_config()
        self.provider = provider or build_design_option_provider(self.config)
        self.start_workers = start_workers
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)
        self._lock = threading.Lock()
        self._active_sets: set[str] = set()

    def _config_record(self) -> dict[str, Any]:
        record = self.config.public()
        record["config_hash"] = self.config.fingerprint()
        return record

    def _active(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._active_sets)

    def _recover(self, organization_id: str, project_id: str) -> None:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            tx.recover_running(now_iso(), self._active())

    def _context(self, organization_id: str, project_id: str, request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
        source = self.brief_provider(organization_id, project_id)
        if not source or not source.get("brief"):
            raise AIDesignOptionServiceError(409, "BRIEF_REQUIRED", "请先生成并保存结构化任务书")
        brief_record = source["brief"]
        brief = brief_record["brief"] if isinstance(brief_record, dict) and "brief" in brief_record else brief_record
        site = dict(self.context_provider(organization_id, project_id) or {})
        site.setdefault("width", "12")
        site.setdefault("length", "8")
        site.setdefault("boundary_source", "test_parameters_not_site_verified")
        obstacles = request.get("obstacles")
        if obstacles is not None:
            if not isinstance(obstacles, list) or len(obstacles) > 12:
                raise AIDesignOptionServiceError(400, "INVALID_OBSTACLES", "障碍集合格式无效")
            site["obstacles"] = obstacles
        site.setdefault("obstacles", [])
        return brief, site, str(source.get("job", {}).get("job_id") or brief_record.get("job_id") or brief_record.get("brief_id") or "")

    def _allowed_source_ids(self, brief: dict[str, Any]) -> set[str]:
        ids = {str(item.get("source_id")) for item in brief.get("source_refs", []) if item.get("source_id")}
        ids.add("synthetic-input")
        return ids

    def _validate_candidate(self, model: Any, *, brief: dict[str, Any], config: DesignOptionConfig,
                            input_hash: str) -> dict[str, Any]:
        errors = sorted(self.validator.iter_errors(model), key=lambda error: list(error.path))
        if errors:
            raise DesignOptionProviderFailure(category="validation", code="SCHEMA_INVALID",
                                              message="候选模型不符合版本化契约")
        try:
            checked, validation = validate_model(model)
        except GeometryError as error:
            raise DesignOptionProviderFailure(category="validation", code=error.code, message=error.message) from error
        allowed = self._allowed_source_ids(brief)

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                refs = node.get("source_refs")
                if isinstance(refs, list) and all(isinstance(item, str) for item in refs):
                    unknown = set(refs) - allowed
                    if unknown:
                        raise DesignOptionProviderFailure(category="validation", code="UNKNOWN_SOURCE_ID",
                                                          message="候选引用了未授权的来源 ID")
                if node.get("known_status") == "unknown" and node.get("value") not in {None}:
                    raise DesignOptionProviderFailure(category="validation", code="UNKNOWN_VALUE_FILLED",
                                                      message="未知值不得填写数字或文本")
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(checked)
        generation = checked["generation"]
        if (generation["real_model"] != config.real_model or generation["provider_kind"] != config.kind
                or generation["config_hash"] != config.fingerprint() or generation["input_hash"] != input_hash):
            raise DesignOptionProviderFailure(category="validation", code="RUN_METADATA_MISMATCH",
                                              message="候选模型运行记录与作业快照不一致")
        if checked["cost"]["total_project_estimate"]["known_status"] != "unknown" or checked["cost"]["total_project_estimate"]["value"] is not None:
            raise DesignOptionProviderFailure(category="validation", code="UNSUPPORTED_TOTAL_ESTIMATE",
                                              message="候选阶段不允许生成完整项目估价")
        checked["validation"] = validation
        checked["structure_signature"] = structure_signature(checked)
        return checked

    def submit(self, organization_id: str, project_id: str, actor_id: str,
               request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 255:
            raise AIDesignOptionServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键需为 8—255 字符")
        self._recover(organization_id, project_id)
        brief, site, brief_id = self._context(organization_id, project_id, request)
        config_record = self._config_record()
        context = {"schema_version": "rkd-ai-design-context.v1", "brief": brief, "site": site,
                   "config": config_record, "brief_id": brief_id}
        input_hash = _digest(context)
        now = now_iso()
        set_id = new_id("ai-option-set")
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            existing = tx.set_by_key(idempotency_key)
            if existing:
                if existing["input_hash"] != input_hash:
                    raise AIDesignOptionServiceError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键对应了不同输入")
                return {"item": existing}
            tx.insert_set({
                "set_id": set_id, "brief_id": brief_id, "input_hash": input_hash, "status": "queued",
                "phase": "queued", "attempt_count": 0, "config": config_record, "context": context,
                "error_code": None, "error_message": None, "idempotency_key": idempotency_key,
                "actor_id": actor_id, "created_at": now, "updated_at": now,
            })
            item = tx.set_row(set_id)
        if (self.config.kind not in {"synthetic", "openai_compatible"}
                or self.config.configuration_errors or self.provider is None):
            self._configuration_failure(organization_id, project_id, set_id)
            with self.repository.transaction(organization_id, project_id) as tx:
                item = tx.set_row(set_id)
        else:
            self._launch(organization_id, project_id, set_id)
        return {"item": item}

    def _configuration_failure(self, organization_id: str, project_id: str, set_id: str) -> None:
        message = "设计候选通道未配置；未生成候选。"
        if self.config.configuration_errors:
            message = "设计候选配置不完整：" + "；".join(self.config.configuration_errors)
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            item = tx.set_row(set_id)
            if item and item["status"] == "queued":
                tx.update_set(set_id, status="failed", phase="configuration_failed", updated_at=now_iso(),
                              error_code="DESIGN_PROVIDER_NOT_CONFIGURED", error_message=message)

    def _launch(self, organization_id: str, project_id: str, set_id: str) -> None:
        if not self.start_workers:
            return
        with self._lock:
            self._active_sets.add(set_id)
        threading.Thread(target=self._run_set, args=(organization_id, project_id, set_id),
                         name=f"rkd-ai-option-{set_id}", daemon=True).start()

    def _run_set(self, organization_id: str, project_id: str, set_id: str) -> None:
        attempt_dir: Path | None = None
        try:
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                item = tx.set_row(set_id)
                if not item or item["status"] != "queued":
                    return
                attempt = int(item["attempt_count"]) + 1
                tx.start_set(set_id, attempt, now_iso())
                context = item["context"]
                config = DesignOptionConfig.from_public(item["config"])
            provider = build_design_option_provider(config) if self.provider is None else self.provider
            if provider is None:
                raise DesignOptionProviderFailure(category="configuration", code="DESIGN_PROVIDER_NOT_CONFIGURED",
                                                  message="设计候选通道未配置")
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                tx.update_set(set_id, status="running", phase="geometry", updated_at=now_iso())
            try:
                models = provider.generate(set_id=set_id, brief=context["brief"], site=context["site"],
                                           input_hash=item["input_hash"], generated_at=now_iso())
            except DesignOptionProviderFailure:
                raise
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                tx.update_set(set_id, status="running", phase="validation", updated_at=now_iso())
            checked = [self._validate_candidate(model, brief=context["brief"], config=config,
                                                input_hash=item["input_hash"]) for model in models]
            if len(checked) < 2 or not all(candidates_are_structurally_different(checked[0], other) for other in checked[1:]):
                raise DesignOptionProviderFailure(category="validation", code="HOMOGENEOUS_CANDIDATES",
                                                  message="候选空间组织实质相同，不能作为多方案通过")
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                tx.update_set(set_id, status="running", phase="outputs", updated_at=now_iso())
            attempt_dir = self.runtime_root / "projects" / "ai-design-options" / set_id / f"attempt-{attempt}"
            attempt_dir.mkdir(parents=True, exist_ok=False)
            prepared = []
            for model in checked:
                option_revision_id = new_id("ai-option-revision")
                model["option_id"] = f"{set_id}:{model['strategy']['strategy_id']}"
                model["set_id"] = set_id
                model["revision_no"] = 1
                data = render_svg(model)
                relative = (attempt_dir / f"layout-{option_revision_id}.svg").relative_to(self.runtime_root).as_posix()
                (self.runtime_root / relative).write_bytes(data)
                prepared.append((option_revision_id, model, relative, data))
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                current = tx.set_row(set_id)
                if not current or current["status"] != "running" or int(current["attempt_count"]) != attempt:
                    raise DesignOptionProviderFailure(category="conflict", code="LATE_RESULT_DISCARDED",
                                                      message="候选集状态已变化，迟到结果未写入")
                for option_revision_id, model, relative, data in prepared:
                    row = {
                        "option_revision_id": option_revision_id, "set_id": set_id,
                        "option_id": model["option_id"], "revision_no": 1, "parent_revision_id": None,
                        "strategy_id": model["strategy"]["strategy_id"], "strategy": model["strategy"],
                        "model": model, "validation": model["validation"], "materials": model["materials"],
                        "cost": model["cost"], "feedback": model["feedback"], "diff": model["diff"],
                        "conflicts": model["conflicts"], "structure_signature": model["structure_signature"],
                        "lifecycle_status": "candidate", "source_kind": model["source_kind"],
                        "change_reason": model["change_reason"], "actor_id": item["actor_id"], "created_at": now_iso(),
                    }
                    tx.insert_revision(row)
                    tx.insert_artifact({
                        "artifact_id": new_id("ai-option-artifact"), "option_revision_id": option_revision_id,
                        "artifact_kind": "layout_svg", "filename": f"layout-{option_revision_id}.svg",
                        "content_type": "image/svg+xml", "relative_path": relative,
                        "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "created_at": now_iso(),
                    })
                tx.update_set(set_id, status="succeeded", phase="completed", updated_at=now_iso())
            attempt_dir = None
        except DesignOptionProviderFailure as failure:
            self._finish_failure(organization_id, project_id, set_id, failure)
        except Exception:
            self._finish_failure(organization_id, project_id, set_id,
                                 DesignOptionProviderFailure(category="execution", code="UNEXPECTED_DESIGN_ERROR",
                                                             message="候选生成出现未分类错误，未写入当前生产"))
        finally:
            if attempt_dir is not None and attempt_dir.is_dir():
                shutil.rmtree(attempt_dir, ignore_errors=True)
            with self._lock:
                self._active_sets.discard(set_id)

    def _finish_failure(self, organization_id: str, project_id: str, set_id: str,
                        failure: DesignOptionProviderFailure) -> None:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            item = tx.set_row(set_id)
            if not item or item["status"] in {"succeeded", "cancelled"}:
                return
            tx.update_set(set_id, status="failed", phase="failed", updated_at=now_iso(),
                          error_code=failure.code, error_message=failure.message)

    def status(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._recover(organization_id, project_id)
        with self.repository.transaction(organization_id, project_id) as tx:
            sets = tx.sets()
            latest = next((item for item in sets if item["status"] == "succeeded"), None)
            current = None
            if latest:
                revisions = tx.revisions_for_set(latest["set_id"])
                by_option: dict[str, dict[str, Any]] = {}
                for revision in revisions:
                    if revision["option_id"] not in by_option:
                        by_option[revision["option_id"]] = revision
                options = []
                for revision in by_option.values():
                    options.append({**revision, "artifacts": tx.artifacts(revision["option_revision_id"])})
                current = {"set": latest, "options": options, "revisions": revisions}
            adoption = tx.adoption()
            return {"provider": self.config.public(),
                    "configured": self.config.kind in {"synthetic", "openai_compatible"}
                                  and not self.config.configuration_errors,
                    "item": current, "sets": sets, "adoption": adoption}

    def revision_by_id(self, organization_id: str, project_id: str,
                       option_revision_id: str) -> dict[str, Any] | None:
        with self.repository.transaction(organization_id, project_id) as tx:
            revision = tx.revision(option_revision_id)
            if revision:
                revision["artifacts"] = tx.artifacts(option_revision_id)
            return revision

    def mark_production_status(self, organization_id: str, project_id: str,
                               expected_version: int, status: str) -> bool:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            adoption = tx.adoption()
            if not adoption or int(adoption["expected_revision"]) != expected_version:
                return False
            if adoption["status"] != "adopted_draft" and status in {"queued", "succeeded"}:
                return False
            tx.upsert_adoption({**adoption, "production_task_status": status,
                                "updated_at": now_iso()})
            return True

    def _provider(self, config: DesignOptionConfig | None = None) -> Any:
        if self.provider is not None:
            return self.provider
        return build_design_option_provider(config or self.config)

    def revise(self, organization_id: str, project_id: str, actor_id: str, request: dict[str, Any]) -> dict[str, Any]:
        option_id = request.get("option_id")
        expected = request.get("expected_revision")
        feedback = request.get("feedback")
        locks = request.get("locks", [])
        if not isinstance(option_id, str) or not isinstance(expected, int) or not isinstance(feedback, str) \
                or not isinstance(locks, list) or not all(isinstance(item, str) for item in locks):
            raise AIDesignOptionServiceError(400, "INVALID_FEEDBACK", "请提供候选、预期版本、反馈文字和锁定范围")
        now = now_iso()
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            current = tx.latest_revision(option_id)
            if not current or current["revision_no"] != expected:
                raise AIDesignOptionServiceError(409, "STALE_OPTION_REVISION", "候选版本已变化，请重新读取")
            set_row = tx.set_row(current["set_id"])
            if not set_row or set_row["status"] != "succeeded":
                raise AIDesignOptionServiceError(409, "OPTION_SET_UNAVAILABLE", "候选集不可修订")
            config = DesignOptionConfig.from_public(set_row["config"])
            brief = set_row["context"]["brief"]
            provider = self._provider(config)
            if provider is None:
                raise AIDesignOptionServiceError(503, "DESIGN_PROVIDER_NOT_CONFIGURED", "设计候选通道未配置")
            input_hash = _digest({"parent": current["option_revision_id"], "feedback": feedback, "locks": locks})
            try:
                revised = provider.revise(current=current["model"], feedback=feedback, locks=locks,
                                          revision_no=expected + 1, parent_revision_id=current["option_revision_id"],
                                          input_hash=input_hash, generated_at=now, actor_id=actor_id)
                revised = self._validate_candidate(revised, brief=brief, config=config, input_hash=input_hash)
            except DesignOptionProviderFailure as failure:
                status = 409 if failure.category == "conflict" else 422
                raise AIDesignOptionServiceError(status, failure.code, failure.message) from failure
            option_revision_id = new_id("ai-option-revision")
            attempt_dir = self.runtime_root / "projects" / "ai-design-options" / current["set_id"] / f"revision-{option_revision_id}"
            attempt_dir.mkdir(parents=True, exist_ok=False)
            data = render_svg(revised)
            relative = (attempt_dir / f"layout-{option_revision_id}.svg").relative_to(self.runtime_root).as_posix()
            (self.runtime_root / relative).write_bytes(data)
            try:
                tx.insert_revision({
                    "option_revision_id": option_revision_id, "set_id": current["set_id"], "option_id": option_id,
                    "revision_no": expected + 1, "parent_revision_id": current["option_revision_id"],
                    "strategy_id": revised["strategy"]["strategy_id"], "strategy": revised["strategy"],
                    "model": revised, "validation": revised["validation"], "materials": revised["materials"],
                    "cost": revised["cost"], "feedback": revised["feedback"], "diff": revised["diff"],
                    "conflicts": revised["conflicts"], "structure_signature": revised["structure_signature"],
                    "lifecycle_status": "candidate", "source_kind": revised["source_kind"],
                    "change_reason": revised["change_reason"], "actor_id": actor_id, "created_at": now,
                })
                tx.insert_artifact({
                    "artifact_id": new_id("ai-option-artifact"), "option_revision_id": option_revision_id,
                    "artifact_kind": "layout_svg", "filename": f"layout-{option_revision_id}.svg",
                    "content_type": "image/svg+xml", "relative_path": relative,
                    "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "created_at": now,
                })
                adoption = tx.adoption()
                if adoption and adoption["option_id"] == option_id:
                    tx.upsert_adoption({**adoption, "status": "superseded", "updated_at": now})
            except Exception:
                shutil.rmtree(attempt_dir, ignore_errors=True)
                raise
            return {"item": tx.revision(option_revision_id), "diff": revised["diff"], "conflicts": revised["conflicts"]}

    def adopt(self, organization_id: str, project_id: str, actor_id: str, request: dict[str, Any]) -> dict[str, Any]:
        option_id = request.get("option_id")
        expected_revision = request.get("expected_revision")
        expected_version = request.get("expected_version", 0)
        if not isinstance(option_id, str) or not isinstance(expected_revision, int) or not isinstance(expected_version, int):
            raise AIDesignOptionServiceError(400, "INVALID_ADOPTION", "请提供候选、候选修订和预期采用版本")
        now = now_iso()
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            revision = tx.latest_revision(option_id)
            if not revision or revision["revision_no"] != expected_revision:
                raise AIDesignOptionServiceError(409, "STALE_OPTION_REVISION", "候选版本已变化，请重新读取")
            if revision["validation"]["status"] != "passed":
                raise AIDesignOptionServiceError(422, "INVALID_CANDIDATE", "未通过硬检查的候选不能采用")
            adoption = tx.adoption()
            current_version = int(adoption["expected_revision"]) if adoption else 0
            if current_version != expected_version:
                raise AIDesignOptionServiceError(409, "STALE_ADOPTION_VERSION", "采用基线已变化，请重新读取")
            tx.upsert_adoption({
                "option_revision_id": revision["option_revision_id"], "set_id": revision["set_id"],
                "option_id": option_id, "revision_no": revision["revision_no"],
                "expected_revision": current_version + 1, "status": "adopted_draft",
                "production_task_status": "not_started", "actor_id": actor_id,
                "created_at": adoption["created_at"] if adoption else now, "updated_at": now,
            })
            return {"item": tx.adoption(), "formal_approval": False, "production_sync": False}

    def cancel(self, organization_id: str, project_id: str, set_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            item = tx.set_row(set_id)
            if not item:
                raise AIDesignOptionServiceError(404, "NOT_FOUND", "候选集不存在")
            if item["status"] not in {"queued", "running"}:
                raise AIDesignOptionServiceError(409, "SET_STATE", "候选集已结束，不能取消")
            tx.update_set(set_id, status="cancelled", phase="failed", updated_at=now_iso(),
                          error_code="CANCELLED_BY_USER", error_message="用户取消候选集")
            return {"item": tx.set_row(set_id)}

    def get_artifact(self, organization_id: str, project_id: str, artifact_id: str) -> tuple[dict[str, Any], Path]:
        with self.repository.transaction(organization_id, project_id) as tx:
            artifact = tx.artifact(artifact_id)
        if not artifact:
            raise AIDesignOptionServiceError(404, "NOT_FOUND", "候选图面不存在")
        path = (self.runtime_root / artifact["relative_path"]).resolve()
        if not path.is_relative_to(self.runtime_root) or not path.is_file():
            raise AIDesignOptionServiceError(500, "ARTIFACT_MISSING", "候选图面文件缺失")
        data = path.read_bytes()
        if len(data) != artifact["size_bytes"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise AIDesignOptionServiceError(500, "ARTIFACT_INTEGRITY", "候选图面字节发生变化")
        return artifact, path

    def wait_for_set(self, organization_id: str, project_id: str, set_id: str,
                     timeout_seconds: float = 5.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with self.repository.transaction(organization_id, project_id) as tx:
                item = tx.set_row(set_id)
            if item and item["status"] in {"succeeded", "failed", "cancelled"}:
                return item
            time.sleep(0.02)
        raise AIDesignOptionServiceError(504, "SET_TIMEOUT", "等待候选集超时")

    def wait_for_idle(self, timeout_seconds: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and self._active():
            time.sleep(0.02)
