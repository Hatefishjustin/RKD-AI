"""AI-DESIGN-04/05 same-source development and quantity draft.

The chain starts only from an explicitly adopted, checked design option. It
produces a separate development package, deterministic quantities, a local
cost draft and real downloadable files. It never calls the legacy design-save
production sync, creates a purchase order, or grants formal approval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import threading
import time
from typing import Any

from jsonschema import Draft202012Validator

from .ai_development_outputs import (
    FORMULA_VERSION, GENERATOR_VERSION, MEASUREMENT_VERSION, OUTPUT_VERSION,
    PACKAGE_VERSION, build_development_package, generate_development_outputs,
    normalize_settings,
)
from .models import new_id, now_iso

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "v1" / "ai-development-package.schema.json"


class AIDevelopmentServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class AIDevelopmentService:
    def __init__(self, repository: Any, option_service: Any,
                 runtime_root: str | Path, *, start_workers: bool = True) -> None:
        self.repository = repository
        self.option_service = option_service
        self.runtime_root = Path(runtime_root).resolve()
        self.start_workers = start_workers
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)
        self._lock = threading.Lock()
        self._active_jobs: set[str] = set()

    def _config(self) -> dict[str, Any]:
        return {"schema_version": PACKAGE_VERSION, "formula_version": FORMULA_VERSION,
                "measurement_version": MEASUREMENT_VERSION, "output_version": OUTPUT_VERSION,
                "generator_version": GENERATOR_VERSION, "provider_kind": "deterministic_program",
                "real_model": False, "formal_quote": False, "external_effects_enabled": False}

    def _active(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._active_jobs)

    def _recover(self, organization_id: str, project_id: str) -> None:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            tx.recover_running(now_iso(), self._active())

    def submit(self, organization_id: str, project_id: str, actor_id: str,
               request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 255:
            raise AIDevelopmentServiceError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键需为 8—255 字符")
        expected_version = request.get("expected_version")
        if not isinstance(expected_version, int):
            raise AIDevelopmentServiceError(400, "INVALID_ADOPTION_VERSION", "请提供预期采用版本")
        try:
            settings = normalize_settings(request.get("settings", {}))
        except ValueError as error:
            raise AIDevelopmentServiceError(400, "INVALID_PRODUCTION_SETTINGS", str(error)) from error
        self._recover(organization_id, project_id)
        option_state = self.option_service.status(organization_id, project_id)
        adoption = option_state.get("adoption")
        if not adoption or adoption.get("status") != "adopted_draft":
            raise AIDevelopmentServiceError(409, "ADOPTION_REQUIRED", "请先采用一个通过检查的候选")
        if int(adoption["expected_revision"]) != expected_version:
            raise AIDevelopmentServiceError(409, "STALE_ADOPTION_VERSION", "采用基线已变化，请重新读取")
        if adoption.get("production_task_status") in {"queued", "running"}:
            with self.repository.transaction(organization_id, project_id) as tx:
                active = next((job for job in tx.jobs() if job["status"] in {"queued", "running"}), None)
            if active:
                return {"item": active}
        option_revision = self.option_service.revision_by_id(organization_id, project_id,
                                                            adoption["option_revision_id"])
        if not option_revision or option_revision["validation"]["status"] != "passed":
            raise AIDevelopmentServiceError(422, "INVALID_ADOPTED_OPTION", "采用候选未通过硬检查")
        # W1→W2 boundary: this legacy generator measures rect objects. A precise
        # spatial candidate must NOT be run through it (bbox measurement would
        # look valid but be wrong); it needs the precise W2 path.
        if (option_revision.get("model") or {}).get("spatial"):
            raise AIDevelopmentServiceError(
                422, "SPATIAL_MODEL_REQUIRES_PRECISE_PATH",
                "该采用候选是精确 spatial 模型，旧矩形深化/量价链会用包围盒算量；"
                "已拒绝，需走 W2 精确同源成果路径")
        config = self._config()
        input_payload = {"option_revision_id": option_revision["option_revision_id"],
                         "model_input_hash": option_revision["model"]["generation"]["input_hash"],
                         "adoption_version": expected_version, "settings": settings, "config": config}
        input_hash = _digest(input_payload)
        now = now_iso()
        job_id = new_id("ai-development-job")
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            existing = tx.job_by_key(idempotency_key)
            if existing:
                if existing["input_hash"] != input_hash:
                    raise AIDevelopmentServiceError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键对应了不同输入")
                return {"item": existing}
            tx.insert_job({
                "job_id": job_id, "option_revision_id": option_revision["option_revision_id"],
                "adoption_version": expected_version, "input_hash": input_hash, "status": "queued",
                "phase": "queued", "attempt_count": 0, "settings": settings, "config": config,
                "error_code": None, "error_message": None, "idempotency_key": idempotency_key,
                "actor_id": actor_id, "created_at": now, "updated_at": now,
            })
            item = tx.job(job_id)
        if not self.option_service.mark_production_status(organization_id, project_id,
                                                          expected_version, "queued"):
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                tx.update_job(job_id, status="failed", phase="failed", updated_at=now_iso(),
                              error_code="STALE_ADOPTION", error_message="采用基线已变化，未生成深化量价")
                item = tx.job(job_id)
        else:
            self._launch(organization_id, project_id, job_id)
        return {"item": item}

    def _launch(self, organization_id: str, project_id: str, job_id: str) -> None:
        if not self.start_workers:
            return
        with self._lock:
            self._active_jobs.add(job_id)
        threading.Thread(target=self._run_job, args=(organization_id, project_id, job_id),
                         name=f"rkd-ai-development-{job_id}", daemon=True).start()

    def _run_job(self, organization_id: str, project_id: str, job_id: str) -> None:
        attempt_dir: Path | None = None
        try:
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                job = tx.job(job_id)
                if not job or job["status"] != "queued":
                    return
                attempt = int(job["attempt_count"]) + 1
                tx.start_job(job_id, attempt, now_iso())
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                tx.update_job(job_id, status="running", phase="measurement", updated_at=now_iso())
            adoption = self.option_service.status(organization_id, project_id).get("adoption")
            if not adoption or int(adoption["expected_revision"]) != int(job["adoption_version"]):
                raise AIDevelopmentServiceError(409, "STALE_ADOPTION", "采用基线已变化，未生成深化量价")
            option_revision = self.option_service.revision_by_id(organization_id, project_id,
                                                                job["option_revision_id"])
            if not option_revision:
                raise AIDevelopmentServiceError(404, "ADOPTED_OPTION_MISSING", "采用候选不存在")
            production_revision_id = new_id("ai-development-revision")
            try:
                package, plan_bytes, iso_bytes, gltf_bytes, node_map = build_development_package(
                    production_revision_id=production_revision_id, job_id=job_id,
                    option_revision=option_revision, adoption=adoption,
                    settings=job["settings"], input_hash=job["input_hash"], created_at=now_iso(),
                )
                errors = sorted(self.validator.iter_errors(package), key=lambda error: list(error.path))
                if errors:
                    raise AIDevelopmentServiceError(500, "PACKAGE_SCHEMA_INVALID", "深化包不符合版本化契约")
                outputs = generate_development_outputs(package, plan_bytes, iso_bytes, gltf_bytes)
            except AIDevelopmentServiceError:
                raise
            except Exception as error:
                raise AIDevelopmentServiceError(500, "OUTPUT_GENERATION_FAILED", "深化成果生成失败") from error
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                tx.update_job(job_id, status="running", phase="outputs", updated_at=now_iso())
            attempt_dir = self.runtime_root / "projects" / "ai-development" / job_id / f"attempt-{attempt}"
            attempt_dir.mkdir(parents=True, exist_ok=False)
            prepared = []
            for kind, (filename, mime, data) in outputs.items():
                path = attempt_dir / filename
                path.write_bytes(data)
                prepared.append((kind, filename, mime, path.relative_to(self.runtime_root).as_posix(), data))
            # Read the adoption pointer before opening the final write lock; a
            # cross-repository write inside this transaction would deadlock SQLite.
            current_adoption = self.option_service.status(organization_id, project_id).get("adoption")
            if not current_adoption or current_adoption.get("status") != "adopted_draft" \
                    or int(current_adoption["expected_revision"]) != int(job["adoption_version"]) \
                    or current_adoption["option_revision_id"] != job["option_revision_id"]:
                raise AIDevelopmentServiceError(409, "STALE_ADOPTION", "采用基线已变化，迟到结果未写入")
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                current = tx.job(job_id)
                if not current or current["status"] != "running" or int(current["attempt_count"]) != attempt:
                    raise AIDevelopmentServiceError(409, "LATE_RESULT_DISCARDED", "作业状态已变化，迟到结果未写入")
                tx.insert_revision({
                    "production_revision_id": production_revision_id, "job_id": job_id,
                    "option_revision_id": job["option_revision_id"], "set_id": package["set_id"],
                    "option_id": package["option_id"], "adoption_version": job["adoption_version"],
                    "input_hash": job["input_hash"], "baseline": package["baseline"],
                    "package": package, "quantities": package["quantity_items"],
                    "cost": package["cost"], "objects": package["objects"],
                    "materials": package["materials"], "unknowns": package["unknown_items"],
                    "view_mapping": {"node_object_map": node_map, "views": package["views"]},
                    "formula_version": FORMULA_VERSION, "measurement_version": MEASUREMENT_VERSION,
                    "output_version": OUTPUT_VERSION, "actor_id": job["actor_id"], "created_at": now_iso(),
                })
                for kind, filename, mime, relative, data in prepared:
                    tx.insert_artifact({
                        "artifact_id": new_id("ai-development-artifact"),
                        "production_revision_id": production_revision_id, "artifact_kind": kind,
                        "filename": filename, "content_type": mime, "relative_path": relative,
                        "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
                        "created_at": now_iso(),
                    })
                tx.update_job(job_id, status="succeeded", phase="completed", updated_at=now_iso())
            self.option_service.mark_production_status(organization_id, project_id,
                                                       int(job["adoption_version"]), "succeeded")
            attempt_dir = None
        except AIDevelopmentServiceError as error:
            self._finish_failure(organization_id, project_id, job_id, error.code, error.message)
        except Exception:
            self._finish_failure(organization_id, project_id, job_id,
                                 "UNEXPECTED_DEVELOPMENT_ERROR", "深化量价任务出现未分类错误")
        finally:
            if attempt_dir is not None and attempt_dir.is_dir():
                shutil.rmtree(attempt_dir, ignore_errors=True)
            with self._lock:
                self._active_jobs.discard(job_id)

    def _finish_failure(self, organization_id: str, project_id: str, job_id: str,
                        code: str, message: str) -> None:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            job = tx.job(job_id)
            if not job or job["status"] in {"succeeded", "cancelled"}:
                return
            tx.update_job(job_id, status="failed", phase="failed", updated_at=now_iso(),
                          error_code=code, error_message=message)
            adoption_version = int(job["adoption_version"])
        self.option_service.mark_production_status(organization_id, project_id,
                                                   adoption_version, "failed")

    def status(self, organization_id: str, project_id: str) -> dict[str, Any]:
        self._recover(organization_id, project_id)
        option_state = self.option_service.status(organization_id, project_id)
        adoption = option_state.get("adoption")
        with self.repository.transaction(organization_id, project_id) as tx:
            jobs = tx.jobs()
            revision = tx.latest_succeeded_revision()
            current = None
            if revision:
                artifacts = tx.artifacts(revision["production_revision_id"])
                outdated = not adoption or adoption.get("status") != "adopted_draft" \
                    or adoption.get("option_revision_id") != revision["option_revision_id"] \
                    or int(adoption.get("expected_revision", -1)) != int(revision["adoption_version"])
                current = {"revision": revision, "artifacts": artifacts,
                           "status": "source_outdated" if outdated else "draft"}
            return {"configured": True, "provider": self._config(), "adoption": adoption,
                    "item": current, "jobs": jobs, "formal_quote": False,
                    "legacy_production_sync": False}

    def get_artifact(self, organization_id: str, project_id: str,
                     artifact_id: str) -> tuple[dict[str, Any], Path]:
        with self.repository.transaction(organization_id, project_id) as tx:
            artifact = tx.artifact(artifact_id)
        if not artifact:
            raise AIDevelopmentServiceError(404, "NOT_FOUND", "深化成果不存在")
        path = (self.runtime_root / artifact["relative_path"]).resolve()
        if not path.is_relative_to(self.runtime_root) or not path.is_file():
            raise AIDevelopmentServiceError(500, "ARTIFACT_MISSING", "深化成果文件缺失")
        data = path.read_bytes()
        if len(data) != artifact["size_bytes"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise AIDevelopmentServiceError(500, "ARTIFACT_INTEGRITY", "深化成果字节发生变化")
        return artifact, path

    def wait_for_job(self, organization_id: str, project_id: str, job_id: str,
                     timeout_seconds: float = 5.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with self.repository.transaction(organization_id, project_id) as tx:
                item = tx.job(job_id)
            if item and item["status"] in {"succeeded", "failed", "cancelled"}:
                return item
            time.sleep(0.02)
        raise AIDevelopmentServiceError(504, "JOB_TIMEOUT", "等待深化量价任务超时")

    def wait_for_idle(self, timeout_seconds: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and self._active():
            time.sleep(0.02)
