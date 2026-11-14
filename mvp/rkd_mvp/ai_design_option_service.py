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
                 start_workers: bool = True, studio_source: Any | None = None) -> None:
        self.repository = repository
        self.brief_provider = brief_provider
        self.context_provider = context_provider
        self.runtime_root = Path(runtime_root).resolve()
        self.config = config or load_design_option_config()
        self.provider = provider or build_design_option_provider(self.config)
        self.start_workers = start_workers
        # W1: explicit read boundary into Studio's own store. None -> lazy
        # default bound to RKD_STUDIO_DB at first use (never the live project DB).
        self.studio_source = studio_source
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

    # ------------------------------------------------------------ W1 Studio import
    def _studio(self) -> Any:
        if self.studio_source is None:
            from .ai_design_studio_adapter import StudioProposalSource
            self.studio_source = StudioProposalSource()
        return self.studio_source

    @staticmethod
    def _adapt_error(error: Exception) -> "AIDesignOptionServiceError":
        code = getattr(error, "code", "ADAPTATION_FAILED")
        message = getattr(error, "message", str(error))
        return AIDesignOptionServiceError(422, code, message)

    def studio_sources(self, organization_id: str, project_id: str) -> dict[str, Any]:
        """List Studio valid proposals that MAY be imported (read-only)."""
        source = self._studio()
        studio_pid = source.resolve(project_id)
        if studio_pid is None:
            return {"studio_project_id": None, "mapping": None, "items": [],
                    "note": "主系统项目没有显式 Studio 映射；不按名称推断"}
        project = source.project(studio_pid) or {}
        return {"studio_project_id": studio_pid,
                "mapping": {"source_project_id": project.get("source_project_id"),
                            "mapping_note": project.get("mapping_note")},
                "items": source.valid_proposals(studio_pid)}

    def _lineage_state(self, tx: Any, option_id: str,
                       source_parent_uid: str | None) -> dict[str, Any]:
        """Main-system state of ONE source lineage, read inside the caller txn.

        Parent comes from the SOURCE ``parent_revision_uid`` mapped through
        previously imported revisions of the same root lineage — never from
        "latest imported". Missing parents are reported, not faked.
        """
        revisions = tx.revisions_for_option(option_id)
        by_source: dict[str, dict[str, Any]] = {}
        for revision in revisions:
            spatial = (revision.get("model") or {}).get("spatial") or {}
            uid = (spatial.get("source") or {}).get("revision_uid")
            if uid:
                by_source[str(uid)] = revision
        latest = max(revisions, key=lambda r: int(r["revision_no"])) if revisions else None
        parent_revision = by_source.get(str(source_parent_uid)) if source_parent_uid else None
        return {
            "revision_count": len(revisions),
            "next_revision_no": int(latest["revision_no"]) + 1 if latest else 1,
            "by_source": by_source,
            "parent_revision": parent_revision,
            "parent_missing": bool(source_parent_uid) and parent_revision is None,
            "parent_spatial": ((parent_revision or {}).get("model") or {}).get("spatial"),
            "latest_spatial": ((latest or {}).get("model") or {}).get("spatial"),
        }

    def import_studio_proposal(self, organization_id: str, project_id: str, actor_id: str,
                               request: dict[str, Any], *,
                               on_before_commit: Any | None = None,
                               after_prepare: Any | None = None,
                               allow_orphan: bool = False) -> dict[str, Any]:
        """Adapt ONE Studio valid proposal into the main versioned candidate model.

        Identity and parent chain come from the SOURCE lineage (root revision UID
        + parent revision UID), not from letter names or import order. The write
        transaction re-checks idempotency and lineage so concurrent imports cannot
        duplicate versions or fabricate a parent.
        """
        from .ai_design_studio_adapter import (
            ADAPTER_VERSION, MAPPING_VERSION, StudioAdaptationError,
            adapt_proposal, render_spatial_svg,
        )
        from .studio.tools import CATALOG

        def fail(status: int, code: str, message: str) -> None:
            raise AIDesignOptionServiceError(status, code, message)

        if not isinstance(request, dict):
            fail(400, "INVALID_IMPORT_REQUEST", "请求体不是对象")
        studio_pid = str(request.get("studio_project_id") or "").strip()
        artifact_id = str(request.get("studio_artifact_id") or "").strip()
        if not studio_pid or not artifact_id:
            fail(400, "INVALID_IMPORT_REQUEST",
                 "必须显式给出 studio_project_id 与 studio_artifact_id")
        expected_unit = str(request.get("expected_unit") or "mm")
        if expected_unit != "mm":
            fail(422, "UNIT_MISMATCH",
                 f"调用方声明单位为 {expected_unit}；Studio 契约是 mm，适配器不猜测换算")
        declared_main = request.get("source_project_id")
        if declared_main is not None and str(declared_main) != project_id:
            fail(409, "PROJECT_MAPPING_MISMATCH", "请求里的主系统项目与 URL 项目不一致")
        raw_orphan = request.get("allow_orphan", allow_orphan)
        if not isinstance(raw_orphan, bool):
            fail(400, "INVALID_BOOLEAN",
                 "allow_orphan 必须是布尔值；字符串 false 不会被当成 true")
        allow_orphan = raw_orphan

        source = self._studio()
        project = source.project(studio_pid)
        if not project:
            fail(404, "STUDIO_PROJECT_NOT_FOUND", "Studio 项目不存在")
        if project.get("source_project_id") != project_id or source.resolve(project_id) != studio_pid:
            fail(409, "PROJECT_MAPPING_MISMATCH",
                 "Studio→主系统项目映射不是显式一致的；拒绝跨项目导入")
        artifact = source.artifact(artifact_id)
        if not artifact:
            fail(404, "STUDIO_ARTIFACT_NOT_FOUND", "找不到该 Studio 产物")
        if artifact.get("project_id") != studio_pid:
            fail(409, "CROSS_PROJECT_ARTIFACT", "产物属于另一个 Studio 项目")
        if (artifact.get("kind") != "spatial-plan"
                or artifact.get("contract_status") != "valid_candidate"
                or artifact.get("status") in ("superseded", "invalid_raw")):
            fail(422, "NOT_VALID_STUDIO_CANDIDATE",
                 "只允许导入 Studio 的有效 spatial-plan 候选，不导入原始/失效稿")
        source_sha = str(artifact.get("sha256") or "")
        expected_sha = request.get("expected_source_sha256")
        if expected_sha is not None and str(expected_sha) != source_sha:
            fail(409, "SOURCE_SHA_MISMATCH", "源产物字节已变化，请重新确认后再导入")
        plan = artifact.get("payload")
        if not isinstance(plan, dict) or not plan.get("zones"):
            fail(422, "EMPTY_STUDIO_PAYLOAD", "源产物没有可用的完整平面数据")

        lineage = source.lineage(studio_pid, artifact)
        if lineage["status"] == "source_uid_missing":
            fail(422, "SOURCE_UID_MISSING", "源产物没有 revision_uid，无法建立稳定谱系")
        if lineage["status"] == "source_parent_missing":
            fail(409, "SOURCE_PARENT_MISSING",
                 f"源产物的父版本 {lineage['missing_uid']} 不在 Studio 库中，不能猜测谱系")
        if lineage["status"] == "source_lineage_cycle":
            fail(409, "SOURCE_LINEAGE_CYCLE", "源产物的父链成环，拒绝导入")
        design_origin = source.design_origin(artifact)

        source_parent_uid = artifact.get("parent_revision_uid")
        root_uid = str(lineage["root_uid"])
        # Candidate identity = stable ROOT lineage, not the A/B letter.
        option_id = f"studio:{project_id}:{studio_pid}:root:{root_uid}"
        source_key = _digest({"studio_project_id": studio_pid, "artifact_id": artifact_id,
                              "sha256": source_sha, "adapter_version": ADAPTER_VERSION,
                              "mapping_version": MAPPING_VERSION,
                              "main_project_id": project_id,
                              "organization_id": organization_id,
                              "root_revision_uid": root_uid})
        idempotency_key = "studio-import:" + source_key
        provenance = {
            "artifact_id": artifact_id, "sha256": source_sha,
            "studio_project_id": studio_pid, "main_project_id": project_id,
            "revision_uid": artifact.get("revision_uid"),
            "parent_revision_uid": source_parent_uid,
            "candidate_group_id": artifact.get("candidate_group_id"),
            "run_id": artifact.get("run_id"),
        }
        catalog = {c["catalog_id"]: c for c in CATALOG}
        set_id = new_id("ai-option-set")
        option_revision_id = new_id("ai-option-revision")
        created_at = now_iso()
        attempt_dir = (self.runtime_root / "projects" / "ai-design-options"
                       / "studio-import" / set_id)
        svg_path = attempt_dir / f"layout-{option_revision_id}.svg"

        def prepare(revision_no: int, parent_revision_id: str | None,
                    previous_spatial: dict | None, parent_link_status: str,
                    diff_baseline: str):
            try:
                model = adapt_proposal(
                    plan, provenance=provenance, site=project["site"], catalog=catalog,
                    actor_id=actor_id, created_at=created_at, set_id=set_id,
                    option_id=option_id, revision_no=revision_no,
                    parent_revision_id=parent_revision_id,
                    previous_spatial=previous_spatial, expected_unit=expected_unit,
                    lineage=lineage, design_origin=design_origin,
                    parent_link_status=parent_link_status,
                    diff_baseline=diff_baseline)
            except StudioAdaptationError as error:
                raise self._adapt_error(error) from error
            except Exception as error:  # noqa: BLE001 - never write half an adaptation
                raise AIDesignOptionServiceError(
                    422, "ADAPTATION_FAILED",
                    f"适配失败，未写入任何候选：{type(error).__name__}: {error}") from error
            errors = sorted(self.validator.iter_errors(model), key=lambda e: list(e.path))
            if errors:
                first = errors[0]
                raise AIDesignOptionServiceError(
                    422, "ADAPTED_MODEL_INVALID",
                    "适配结果不符合主系统版本化契约："
                    + f"{list(first.path)} {first.message[:160]}")
            if (model["cost"]["total_project_estimate"]["value"] is not None
                    or model["cost"]["budget"]["value"] is not None):
                raise AIDesignOptionServiceError(422, "UNKNOWN_VALUE_FILLED",
                                                 "适配结果把 unknown 金额填成了数值")
            return model, render_spatial_svg(model)

        # Provisional read (fast); the write transaction re-checks everything.
        with self.repository.transaction(organization_id, project_id) as tx:
            existing_set = tx.set_by_key(idempotency_key)
            adoption_before = tx.adoption()
            if existing_set:
                revisions = tx.revisions_for_set(existing_set["set_id"])
                head = revisions[0] if revisions else None
                return {"reused": True, "item": head, "set": existing_set,
                        "adoption_unchanged": True, "formal_approval": False,
                        "note": "同一来源（artifact id + sha256 + 适配器版本 + 根谱系）已导入过，未重复造版本"}
            state = self._lineage_state(tx, option_id, source_parent_uid)
        if state["parent_missing"] and not allow_orphan:
            fail(409, "SOURCE_PARENT_NOT_IMPORTED",
                 f"源父修订 {source_parent_uid} 尚未导入主系统；请先导入父版本，"
                 "或显式 allow_orphan=true 并以缺父状态留痕（不伪造父关系）")
        parent_link_status = ("source_root" if not source_parent_uid
                              else "resolved" if state["parent_revision"]
                              else "source_parent_not_imported")
        diff_baseline = ("none_root" if not source_parent_uid
                         else "source_parent" if state["parent_revision"]
                         else "unknown_missing_parent")
        model, svg = prepare(state["next_revision_no"],
                             (state["parent_revision"] or {}).get("option_revision_id"),
                             state["parent_spatial"] if state["parent_revision"] else None,
                             parent_link_status, diff_baseline)

        committed = False
        reuse_result: dict[str, Any] | None = None
        try:
            attempt_dir.mkdir(parents=True, exist_ok=False)
            svg_path.write_bytes(svg)
            if after_prepare is not None:
                after_prepare()   # W1-R2 seam: a competing import may commit here
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                # (1) same-source idempotency re-check INSIDE the write txn
                existing_set = tx.set_by_key(idempotency_key)
                if existing_set:
                    revisions = tx.revisions_for_set(existing_set["set_id"])
                    reuse_result = {
                        "reused": True, "item": revisions[0] if revisions else None,
                        "set": existing_set, "adoption_unchanged": True,
                        "formal_approval": False,
                        "note": "并发导入：另一个请求已提交同一来源，本次复用其版本"}
                else:
                    # (2) lineage + expected version re-check INSIDE the write txn
                    state2 = self._lineage_state(tx, option_id, source_parent_uid)
                    if state2["parent_missing"] and not allow_orphan:
                        fail(409, "SOURCE_PARENT_NOT_IMPORTED",
                             f"源父修订 {source_parent_uid} 尚未导入主系统；不伪造父关系")
                    parent2 = (state2["parent_revision"] or {}).get("option_revision_id")
                    revision_no2 = state2["next_revision_no"]
                    if (revision_no2 != model["revision_no"]
                            or parent2 != model["parent_revision_id"]):
                        # Recompute under the write lock: never reuse a stale
                        # revision number and never chain to a wrong parent.
                        parent_link_status2 = ("source_root" if not source_parent_uid
                                               else "resolved" if state2["parent_revision"]
                                               else "source_parent_not_imported")
                        diff_baseline2 = ("none_root" if not source_parent_uid
                                          else "source_parent" if state2["parent_revision"]
                                          else "unknown_missing_parent")
                        model, svg = prepare(
                            revision_no2, parent2,
                            state2["parent_spatial"] if state2["parent_revision"] else None,
                            parent_link_status2, diff_baseline2)
                        svg_path.write_bytes(svg)
                    spatial = model["spatial"]
                    context = {
                        "schema_version": "rkd-studio-import-context.v1",
                        "adapter_version": ADAPTER_VERSION,
                        "mapping_version": MAPPING_VERSION,
                        "source": provenance, "source_unit": "mm", "target_unit": "m",
                        "unit_conversion": "mm_to_m_div_1000",
                        "option_id": option_id,
                        "root_revision_uid": spatial["source"]["root_revision_uid"],
                        "lineage_chain": spatial["source"]["lineage_chain"],
                        "parent_link_status": spatial["source"]["parent_link_status"],
                        "diff_baseline": spatial["adaptation"].get("diff_baseline"),
                        "design_origin": spatial["source"]["design_origin"],
                        "revision_no": model["revision_no"],
                        "parent_revision_id": model["parent_revision_id"],
                        "field_ledger": spatial["adaptation"]["field_ledger"],
                        "object_id_map": spatial["adaptation"]["object_id_map"],
                        "unsupported_items": spatial["unsupported_items"],
                        "losses": spatial["adaptation"]["losses"],
                        "source_sha256": source_sha,
                        "geometry_mode": spatial["adaptation"]["geometry_mode"],
                        "source_contract": "rkd-spatial-plan.v1",
                        "target_contract": "rkd-ai-design-option.v1",
                    }
                    config = {"kind": "studio_proposal_adapter", "real_model": False,
                              "configuration_errors": [],
                              "adapter_version": ADAPTER_VERSION}
                    tx.insert_set({
                        "set_id": set_id, "brief_id": artifact_id,
                        "input_hash": source_key, "status": "succeeded",
                        "phase": "completed", "attempt_count": 1,
                        "config": config, "context": context, "error_code": None,
                        "error_message": None, "idempotency_key": idempotency_key,
                        "actor_id": actor_id, "created_at": created_at,
                        "updated_at": created_at,
                    })
                    tx.insert_revision({
                        "option_revision_id": option_revision_id, "set_id": set_id,
                        "option_id": option_id, "revision_no": model["revision_no"],
                        "parent_revision_id": model["parent_revision_id"],
                        "strategy_id": model["strategy"]["strategy_id"],
                        "strategy": model["strategy"], "model": model,
                        "validation": model["validation"],
                        "materials": model["materials"], "cost": model["cost"],
                        "feedback": model["feedback"], "diff": model["diff"],
                        "conflicts": model["conflicts"],
                        "structure_signature": model["structure_signature"],
                        "lifecycle_status": "candidate",
                        "source_kind": model["source_kind"],
                        "change_reason": model["change_reason"],
                        "actor_id": actor_id, "created_at": created_at,
                    })
                    tx.insert_artifact({
                        "artifact_id": new_id("ai-option-artifact"),
                        "option_revision_id": option_revision_id,
                        "artifact_kind": "layout_svg",
                        "filename": f"layout-{option_revision_id}.svg",
                        "content_type": "image/svg+xml",
                        "relative_path": svg_path.relative_to(self.runtime_root).as_posix(),
                        "sha256": hashlib.sha256(svg).hexdigest(),
                        "size_bytes": len(svg), "created_at": created_at,
                    })
                    if on_before_commit is not None:
                        on_before_commit()   # explicit rollback seam used by tests
                    committed = True
            if reuse_result is not None:
                return reuse_result
            with self.repository.transaction(organization_id, project_id) as tx:
                result_set = tx.set_row(set_id)
                revision = tx.revision(option_revision_id)
                if revision:
                    revision["artifacts"] = tx.artifacts(option_revision_id)
                adoption_after = tx.adoption()
            spatial = model["spatial"]
            context_view = {
                "field_ledger": spatial["adaptation"]["field_ledger"],
                "object_id_map": spatial["adaptation"]["object_id_map"],
                "unsupported_items": spatial["unsupported_items"],
                "losses": spatial["adaptation"]["losses"],
            }
            return {
                "reused": False, "item": revision, "set": result_set,
                "source": provenance,
                "root_revision_uid": spatial["source"]["root_revision_uid"],
                "lineage_chain": spatial["source"]["lineage_chain"],
                "parent_link_status": spatial["source"]["parent_link_status"],
                "design_origin": spatial["source"]["design_origin"],
                "field_ledger": context_view["field_ledger"],
                "object_id_map": context_view["object_id_map"],
                "unsupported_items": context_view["unsupported_items"],
                "losses": context_view["losses"],
                "adaptation": spatial["adaptation"],
                "source_unit": "mm", "target_unit": "m",
                "adoption_unchanged": _json(adoption_before) == _json(adoption_after),
                "adoption": adoption_after,
                "formal_approval": False, "production_sync": False,
                "svg_sha256": hashlib.sha256(svg).hexdigest(),
            }
        finally:
            # only this attempt's own directory is removed on failure/duplicate
            if not committed:
                shutil.rmtree(attempt_dir, ignore_errors=True)

    def list_studio_imports(self, organization_id: str, project_id: str,
                            limit: int = 50) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as tx:
            items = []
            for s in tx.sets(limit=max(limit, 50)):
                if not str(s.get("idempotency_key") or "").startswith("studio-import:"):
                    continue
                revisions = tx.revisions_for_set(s["set_id"])
                rows = []
                for r in revisions:
                    spatial = (r.get("model") or {}).get("spatial") or {}
                    rows.append({
                        "option_revision_id": r["option_revision_id"],
                        "option_id": r["option_id"], "revision_no": r["revision_no"],
                        "parent_revision_id": r.get("parent_revision_id"),
                        "source": spatial.get("source"),
                        "unsupported_items": spatial.get("unsupported_items"),
                        "diff": r.get("diff"),
                        "artifacts": tx.artifacts(r["option_revision_id"]),
                    })
                items.append({"set": s, "context": s.get("context"), "revisions": rows})
            return {"items": items, "adoption": tx.adoption()}

    def studio_import_detail(self, organization_id: str, project_id: str,
                             option_revision_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as tx:
            revision = tx.revision(option_revision_id)
            if not revision:
                raise AIDesignOptionServiceError(404, "IMPORT_REVISION_NOT_FOUND",
                                                 "找不到该导入修订")
            spatial = (revision.get("model") or {}).get("spatial")
            if not spatial:
                raise AIDesignOptionServiceError(422, "NOT_A_STUDIO_IMPORT",
                                                 "该修订不是 Studio 导入候选")
            revision["artifacts"] = tx.artifacts(option_revision_id)
            return {"item": revision, "spatial": spatial,
                    "field_ledger": spatial["adaptation"]["field_ledger"],
                    "unsupported_items": spatial["unsupported_items"]}

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
            # W1→W2 boundary: the legacy rect feedback/patch chain cannot edit a
            # precise spatial model without silently degrading it to bboxes.
            if (current.get("model") or {}).get("spatial"):
                raise AIDesignOptionServiceError(
                    422, "SPATIAL_MODEL_REQUIRES_PRECISE_PATH",
                    "该候选来自精确 spatial 模型，旧的矩形反馈/补丁链不支持；"
                    "请在 Studio 源稿上反馈后重新导入，或走 W2 精确路径")
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
