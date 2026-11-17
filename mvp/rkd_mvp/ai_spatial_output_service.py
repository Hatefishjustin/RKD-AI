"""W2 same-source output service: one frozen model revision -> visible package.

Reuses the existing AI-DEVELOPMENT job/revision/artifact tables (no migration,
no second authoritative model). The generated package is a DRAFT: no formal
quote, no purchase, no publish.

W2-R1: every byte that is registered is also inside ``package.zip``; the file
set, the manifest and the archive come from one dict and the archive is
re-opened and checked before the single registration transaction.
W2-R2: the job is bound to the model revision *and* to the adoption version at
submit time; cancellation is a monotone terminal state; retry is explicit and
linked to the original job; queries are per job/revision, never "latest wins".
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from .ai_spatial_outputs import (
    COST_VERSION, GENERATOR_VERSION, MANIFEST_VERSION, PLAN_VERSION, QUANTITY_VERSION,
    SCENE_VERSION, assert_complete_package, build_package, completeness_for_render,
    finalize_package, model_hash, normalize_finish_scope, sha256_bytes,
)
from .models import new_id, now_iso

ROOT = Path(__file__).resolve().parents[2]
BLENDER = ROOT / "tools" / "blender" / "blender-4.2.9-windows-x64" / "blender.exe"
RENDER_SCRIPT = ROOT / "scripts" / "render_spatial_scene.py"
RENDER_SCRIPT_R4 = ROOT / "scripts" / "render_spatial_scene_r4.py"

JOB_KIND = "spatial_outputs"
MEASUREMENT_PREFIX = "rkd-spatial-outputs"
TERMINAL = {"succeeded", "failed", "cancelled"}
# ai_development_artifacts.artifact_kind has a CHECK list fixed by migration 023.
# A render PNG therefore has no own artifact row; it is registered in manifest.json
# (whose own SHA is anchored by the manifest_json artifact row) and shipped inside
# package.zip. Everything registered here must be inside the archive as well.
ARTIFACT_KINDS = {"plan_svg", "development_json", "quantity_csv", "cost_html",
                  "manifest_json", "package_zip"}
HISTORY_LIMIT = 50


def new_instance_id() -> str:
    """Identity of one worker process instance.

    Recovery must distinguish "left behind by a previous process" from "created a
    microsecond ago by this process and not yet registered in the in-memory set".
    Only a persisted instance stamp can do that.
    """
    return f"spatial-worker-{os.getpid()}-{uuid.uuid4().hex[:12]}"


class AISpatialOutputError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def registration_ok(package: dict) -> bool:
    """True only when the stored package passed the completeness registration
    boundary.  Legacy revisions without a registration block stay conservative."""
    registration = package.get("registration") or {}
    return bool(registration.get("ok")) and "package_completeness" in package


def _settings(request: dict) -> dict:
    raw = request.get("settings") if isinstance(request.get("settings"), dict) else {}
    width = raw.get("width", 1280)
    height = raw.get("height", 800)
    samples = raw.get("samples", 40)
    render = raw.get("render", True)
    if not isinstance(width, int) or not 320 <= width <= 1920:
        raise AISpatialOutputError(400, "INVALID_RENDER_SETTINGS", "宽度需为 320—1920 的整数")
    if not isinstance(height, int) or not 240 <= height <= 1200:
        raise AISpatialOutputError(400, "INVALID_RENDER_SETTINGS", "高度需为 240—1200 的整数")
    if not isinstance(samples, int) or not 8 <= samples <= 128:
        raise AISpatialOutputError(400, "INVALID_RENDER_SETTINGS", "采样数需为 8—128 的整数")
    if not isinstance(render, bool):
        raise AISpatialOutputError(400, "INVALID_BOOLEAN", "render 必须是布尔值")
    price = raw.get("floor_unit_price_cny")
    if price is not None and (not isinstance(price, (int, float)) or isinstance(price, bool)
                              or price <= 0):
        raise AISpatialOutputError(400, "INVALID_UNIT_PRICE",
                                   "假设单价必须是大于 0 的数值（不是报价）")
    prices = raw.get("material_unit_prices") or {}
    if not isinstance(prices, dict) or len(prices) > 50:
        raise AISpatialOutputError(400, "INVALID_UNIT_PRICE",
                                   "材料假设单价必须是材料编号到数值的对象")
    for key, value in prices.items():
        if not isinstance(key, str) or not key:
            raise AISpatialOutputError(400, "INVALID_UNIT_PRICE", "材料编号必须是非空字符串")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise AISpatialOutputError(400, "INVALID_UNIT_PRICE",
                                       f"材料 {key} 的假设单价必须是大于 0 的数值")
    scope = raw.get("finish_scope")
    try:
        scope = normalize_finish_scope(scope)
    except ValueError as error:
        raise AISpatialOutputError(400, "INVALID_FINISH_SCOPE", str(error)) from error
    presentation = raw.get("presentation")
    if presentation is not None:
        from .spatial_presentation import PresentationError, normalize_presentation
        try:
            presentation = normalize_presentation(presentation)
        except PresentationError as error:
            raise AISpatialOutputError(400, "INVALID_PRESENTATION", str(error)) from error
    return {"width": width, "height": height, "samples": samples, "render": render,
            "floor_unit_price_cny": price,
            "material_unit_prices": {str(k): float(v) for k, v in prices.items()},
            "finish_scope": scope, "presentation": presentation}


def run_blender(scene_path: Path, out_png: Path, width: int, height: int,
                samples: int, *, script: Path | None = None) -> dict:
    if not BLENDER.exists():
        raise AISpatialOutputError(503, "RENDERER_UNAVAILABLE",
                                   "本机没有可用的 Blender 执行器")
    cmd = [str(BLENDER), "-b", "--factory-startup", "-noaudio",
           "--python", str(script or RENDER_SCRIPT), "--",
           "--scene", str(scene_path), "--out", str(out_png),
           "--width", str(width), "--height", str(height),
           "--samples", str(samples)]
    env = {k: v for k, v in os.environ.items()
           if k not in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                        "ALL_PROXY", "all_proxy")}
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                          timeout=1200, env=env, cwd=str(out_png.parent))
    if proc.returncode != 0 or not out_png.exists():
        raise AISpatialOutputError(500, "RENDER_FAILED",
                                   f"Blender 渲染失败：{(proc.stderr or proc.stdout)[-400:]}")
    meta_path = Path(str(out_png) + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta.update({"engine": "CYCLES-CPU", "width": width, "height": height,
                 "samples": samples})
    return meta


class AISpatialOutputService:
    def __init__(self, repository: Any, option_service: Any, runtime_root: str | Path,
                 *, start_workers: bool = True,
                 renderer: Callable[[Path, Path, int, int, int], dict] | None = None,
                 instance_id: str | None = None) -> None:
        self.repository = repository
        self.option_service = option_service
        self.runtime_root = Path(runtime_root).resolve()
        self.start_workers = start_workers
        self.renderer = renderer or run_blender
        self.instance_id = instance_id or new_instance_id()
        self._lock = threading.Lock()
        self._active: set[str] = set()

    # ------------------------------------------------------------------ helpers
    def _adoption(self, organization_id: str, project_id: str) -> dict:
        return self.option_service.status(organization_id, project_id).get("adoption") or {}

    def _binding_facts(self, organization_id: str, project_id: str,
                       option_revision_id: str) -> dict:
        """Which version this output is bound to, at the time of the call."""
        adoption = self._adoption(organization_id, project_id)
        adopted = adoption.get("option_revision_id")
        status = ("current_adopted" if adopted == option_revision_id
                  else "historical_preview" if adopted else "candidate_preview")
        return {
            "adopted_option_revision_id": adopted,
            "adoption_version": int(adoption.get("expected_revision") or 0),
            "adopted_at_submit": adopted == option_revision_id,
            "status_at_generation": status,
            "note": "候选预览与当前采用版本成果分开；换版后旧成果只作历史预览",
        }

    @staticmethod
    def _is_spatial_job(job: dict | None) -> bool:
        return bool(job) and (job.get("config") or {}).get("kind") == JOB_KIND

    # ------------------------------------------------------------------ submit
    def submit(self, organization_id: str, project_id: str, actor_id: str,
               request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 255:
            raise AISpatialOutputError(400, "INVALID_IDEMPOTENCY_KEY", "幂等键需为 8—255 字符")
        option_revision_id = request.get("option_revision_id")
        if not isinstance(option_revision_id, str) or not option_revision_id:
            raise AISpatialOutputError(400, "INVALID_REQUEST", "请显式选择要生成成果的模型修订")
        settings = _settings(request)
        revision = self.option_service.revision_by_id(organization_id, project_id,
                                                      option_revision_id)
        if not revision:
            raise AISpatialOutputError(404, "MODEL_REVISION_NOT_FOUND", "找不到该模型修订")
        spatial = (revision.get("model") or {}).get("spatial")
        if not spatial:
            raise AISpatialOutputError(
                422, "SPATIAL_PAYLOAD_REQUIRED",
                "该修订没有精确 spatial 载荷；旧矩形候选不能进入 W2 成果链")
        if settings["presentation"]:
            from .spatial_presentation import PresentationError, normalize_presentation
            boundary_mm = (spatial.get("origin") or {}).get("boundary_mm")
            try:
                settings["presentation"] = normalize_presentation(
                    settings["presentation"], boundary_mm=boundary_mm)
            except PresentationError as error:
                raise AISpatialOutputError(400, "INVALID_PRESENTATION", str(error)) from error
        if (revision.get("validation") or {}).get("status") != "passed":
            raise AISpatialOutputError(422, "MODEL_NOT_VALIDATED", "模型修订未通过硬检查")
        if settings["render"] and self.renderer is run_blender and not BLENDER.exists():
            raise AISpatialOutputError(503, "RENDERER_UNAVAILABLE", "本机没有可用的 Blender 执行器")
        return self._create_job(organization_id, project_id, actor_id, option_revision_id,
                                revision, settings, idempotency_key, retry_of=None)

    def _create_job(self, organization_id: str, project_id: str, actor_id: str,
                    option_revision_id: str, revision: dict, settings: dict,
                    idempotency_key: str, *, retry_of: str | None) -> dict[str, Any]:
        binding = self._binding_facts(organization_id, project_id, option_revision_id)
        input_hash = _digest({"model_hash": model_hash(revision["model"]),
                              "option_revision_id": option_revision_id,
                              "settings": settings, "generator": GENERATOR_VERSION,
                              "retry_of": retry_of})
        config = {"kind": JOB_KIND, "generator_version": GENERATOR_VERSION,
                  "plan_version": PLAN_VERSION, "scene_version": SCENE_VERSION,
                  "quantity_version": QUANTITY_VERSION, "cost_version": COST_VERSION,
                  "presentation_version": (settings.get("presentation") or {}).get("schema_version"),
                  "presentation_assumption": bool(settings.get("presentation")),
                  "renderer": ("blender-4.2.9/CYCLES-CPU" if self.renderer is run_blender
                               else "injected_renderer"),
                  "binding_at_submit": binding,
                  "finish_scope_declared_by": (settings.get("finish_scope") or {}).get(
                      "declared_by"),
                  "run_instance": self.instance_id,
                  "retry_of": retry_of}
        now = now_iso()
        job_id = new_id("ai-spatial-job")
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            existing = tx.job_by_key(idempotency_key)
            if existing:
                if existing["input_hash"] != input_hash:
                    raise AISpatialOutputError(409, "IDEMPOTENCY_CONFLICT",
                                               "同一幂等键对应了不同输入")
                return {"item": existing, "reused": True}
            tx.insert_job({
                "job_id": job_id, "option_revision_id": option_revision_id,
                "adoption_version": int(binding["adoption_version"] or 0),
                "input_hash": input_hash, "status": "queued", "phase": "queued",
                "attempt_count": 0, "settings": settings, "config": config,
                "error_code": None, "error_message": None,
                "idempotency_key": idempotency_key, "actor_id": actor_id,
                "created_at": now, "updated_at": now,
            })
            item = tx.job(job_id)
        if not self.start_workers:
            self._run(organization_id, project_id, job_id)
            with self.repository.transaction(organization_id, project_id) as tx:
                return {"item": tx.job(job_id), "reused": False}
        self._launch(organization_id, project_id, job_id)
        return {"item": item, "reused": False}

    def retry(self, organization_id: str, project_id: str, actor_id: str,
              job_id: str, request: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        """Explicit retry of a failed/cancelled job; linked via config.retry_of."""
        with self.repository.transaction(organization_id, project_id) as tx:
            original = tx.job(job_id)
        if not original or not self._is_spatial_job(original):
            raise AISpatialOutputError(404, "JOB_NOT_FOUND", "找不到该同源成果任务")
        if original["status"] == "succeeded":
            raise AISpatialOutputError(409, "RETRY_NOT_ALLOWED",
                                       "该任务已完成；要出新成果请提交新任务，不要重试覆盖")
        if original["status"] in {"queued", "running"}:
            raise AISpatialOutputError(409, "JOB_STILL_ACTIVE", "任务仍在进行，先把取消做完")
        settings = _settings({"settings": {**(original.get("settings") or {}),
                                           **((request or {}).get("settings") or {})}})
        if settings["render"] and self.renderer is run_blender and not BLENDER.exists():
            raise AISpatialOutputError(503, "RENDERER_UNAVAILABLE", "本机没有可用的 Blender 执行器")
        revision = self.option_service.revision_by_id(
            organization_id, project_id, original["option_revision_id"])
        if not revision:
            raise AISpatialOutputError(404, "MODEL_REVISION_NOT_FOUND", "原任务的模型修订已不存在")
        return self._create_job(organization_id, project_id, actor_id,
                                original["option_revision_id"], revision, settings,
                                idempotency_key, retry_of=job_id)

    def cancel(self, organization_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        """Cancellation is monotone: nothing may move a cancelled job forward."""
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            job = tx.job(job_id)
            if not job or not self._is_spatial_job(job):
                raise AISpatialOutputError(404, "JOB_NOT_FOUND", "找不到该同源成果任务")
            if job["status"] == "cancelled":
                return {"item": job, "already_cancelled": True}
            if job["status"] in {"succeeded", "failed"}:
                raise AISpatialOutputError(
                    409, "CANNOT_CANCEL", f"任务已{job['status']}；已完成的历史字节保留，不能撤回")
            tx.close_job(job_id, "cancelled", job["phase"], now_iso(),
                         error_code="CANCELLED_BY_USER",
                         error_message="用户取消；晚到的渲染结果会被丢弃，不登记成果")
            return {"item": tx.job(job_id), "already_cancelled": False}

    def _launch(self, organization_id: str, project_id: str, job_id: str) -> None:
        with self._lock:
            self._active.add(job_id)
        threading.Thread(target=self._run, args=(organization_id, project_id, job_id),
                         name=f"rkd-spatial-{job_id}", daemon=True).start()

    def _touch(self, organization_id: str, project_id: str, job_id: str, phase: str) -> bool:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            return tx.touch_job(job_id, phase, now_iso(), only_status="running")

    def _run(self, organization_id: str, project_id: str, job_id: str) -> None:
        try:
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                job = tx.job(job_id)
                if not job or job["status"] != "queued":
                    return
                tx.start_job(job_id, int(job["attempt_count"]) + 1, now_iso())
                settings = job["settings"]
                revision_id = job["option_revision_id"]
            revision = self.option_service.revision_by_id(organization_id, project_id,
                                                          revision_id)
            if not revision or not (revision.get("model") or {}).get("spatial"):
                raise AISpatialOutputError(422, "SPATIAL_PAYLOAD_REQUIRED", "模型缺少 spatial")
            model = revision["model"]
            self._touch(organization_id, project_id, job_id, "geometry")
            binding = self._binding_facts(organization_id, project_id, revision_id)
            package = build_package(model, project_id=project_id,
                                    option_revision_id=revision_id, settings=settings,
                                    binding=binding)
            self._touch(organization_id, project_id, job_id, "measurement")
            revision_dir = self.runtime_root / "projects" / "ai-spatial-outputs" / job_id
            revision_dir.mkdir(parents=True, exist_ok=True)
            scene_path = revision_dir / "scene.json"
            scene_path.write_bytes(_json(package["scene"]))
            files = dict(package["files"])
            render_meta = None
            render_status = "not_run"
            if settings["render"]:
                png_path = revision_dir / "render.png"
                renderer = self.renderer
                if settings.get("presentation") and renderer is run_blender:
                    # Scene v2 carries the presentation fixture; the real-asset
                    # renderer is chosen by the SAME settings, not by a hidden flag.
                    from functools import partial
                    renderer = partial(run_blender, script=RENDER_SCRIPT_R4)
                render_meta = renderer(scene_path, png_path, settings["width"],
                                       settings["height"], settings["samples"])
                png = png_path.read_bytes()
                files["render.png"] = ("render_png", "image/png", png)
                render_status = "rendered"
                package["manifest"]["render"] = {
                    **render_meta,
                    "assumption": ("表达层为人工测试假设，非现场事实、非 AI 设计；"
                                   "详见 manifest.presentation 与 scene.json/assumptions"
                                   if settings.get("presentation") else
                                   "机位/材质/家具高度为渲染假设，非实测")}
            # cancellation may have arrived while rendering: discard, never register
            with self.repository.transaction(organization_id, project_id) as tx:
                state = tx.job(job_id)
            if not state or state["status"] != "running":
                self._discard(revision_dir)
                return
            self._touch(organization_id, project_id, job_id, "pricing")
            # R5: completeness is decided BEFORE packing and written into the
            # manifest inside the archive.  A no-render job is still a legal
            # preview but is explicitly incomplete and can never be registered
            # or downloaded as a complete deliverable.
            completeness = completeness_for_render(
                render_status, render_present="render.png" in files)
            built = finalize_package(files, package["manifest"], completeness=completeness)
            manifest_bytes = built["files"]["manifest.json"][2]
            zip_bytes = built["files"]["package.zip"][2]
            registration = assert_complete_package(zip_bytes, manifest_bytes)
            if not registration["ok"] and registration["check"]["ok"]:
                # Byte-consistent but incomplete: legal PREVIEW only.
                package["manifest"]["delivery_status"] = "preview_incomplete"
            if not registration["check"]["ok"]:
                raise AISpatialOutputError(
                    500, "PACKAGE_INTEGRITY_FAILED",
                    "交付包清单与 ZIP 字节不一致，未登记：" + "；".join(registration["check"]["problems"][:3]))
            for name, (_kind, _ctype, data) in built["files"].items():
                (revision_dir / name).write_bytes(data)
            production_revision_id = new_id("ai-production-revision")
            written: list[tuple[str, str, str, bytes, str]] = []
            seen_kinds: set[str] = set()
            manifest_only: list[str] = []
            for name, (kind, ctype, data) in built["files"].items():
                if kind not in ARTIFACT_KINDS:
                    manifest_only.append(name)
                    continue
                if kind in seen_kinds:
                    continue
                seen_kinds.add(kind)
                written.append((name, kind, ctype, data,
                                (revision_dir / name).relative_to(self.runtime_root).as_posix()))
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                job_now = tx.job(job_id)
                if not job_now or job_now["status"] != "running":
                    return
                tx.insert_revision({
                    "production_revision_id": production_revision_id,
                    "job_id": job_id, "option_revision_id": revision_id,
                    "set_id": revision["set_id"], "option_id": revision["option_id"],
                    "adoption_version": job_now["adoption_version"],
                    "input_hash": job_now["input_hash"],
                    "baseline": package["frozen"],
                    "package": {"schema_version": MANIFEST_VERSION,
                                "render": package["manifest"].get("render"),
                                "missing": package["manifest"]["missing"],
                                "binding": binding,
                                "package_check": built["check"],
                                "package_completeness": completeness,
                                "registration": {k: v for k, v in registration.items() if k != "check"},
                                "delivery_status": ("complete" if registration["ok"]
                                                    else "preview_incomplete"),
                                "manifest_only_files": sorted(manifest_only)},
                    "quantities": package["quantities"], "cost": package["cost"],
                    "objects": {"zones": model["spatial"]["zones"],
                                "furniture": model["spatial"]["furniture"],
                                "platforms": model["spatial"].get("platforms") or [],
                                "presentation_enclosure": (package["scene"].get("enclosure")
                                                           if package.get("presentation") else None),
                                "presentation_furniture": (
                                    package["scene"].get("presentation_furniture")
                                    if package.get("presentation") else None)},
                    "materials": {"main": model["materials"],
                                  "spatial": model["spatial"]["materials"],
                                  "finish_scope": package["finish_scope"],
                                  "presentation": (package["manifest"].get("presentation")
                                                   if package.get("presentation") else None)},
                    "unknowns": package["cost"]["unknown_items"],
                    "view_mapping": {"camera": package["camera"],
                                     "plan_version": PLAN_VERSION},
                    "formula_version": QUANTITY_VERSION,
                    "measurement_version": GENERATOR_VERSION,
                    "output_version": MANIFEST_VERSION,
                    "actor_id": job_now["actor_id"], "created_at": now_iso(),
                })
                for name, kind, ctype, data, relative in written:
                    tx.insert_artifact({
                        "artifact_id": new_id("ai-production-artifact"),
                        "production_revision_id": production_revision_id,
                        "artifact_kind": kind, "filename": name,
                        "content_type": ctype, "relative_path": relative,
                        "sha256": sha256_bytes(data), "size_bytes": len(data),
                        "created_at": now_iso(),
                    })
                tx.close_job(job_id, "succeeded", "completed", now_iso(),
                             only_status=("running",))
        except AISpatialOutputError as error:
            self._fail(organization_id, project_id, job_id, error.code, error.message)
        except subprocess.TimeoutExpired:
            self._fail(organization_id, project_id, job_id, "RENDER_TIMEOUT",
                       "渲染超时，未登记本次成果")
        except Exception as error:  # noqa: BLE001
            self._fail(organization_id, project_id, job_id, "SPATIAL_OUTPUT_FAILED",
                       f"{type(error).__name__}: {error}")
        finally:
            with self._lock:
                self._active.discard(job_id)

    def _discard(self, revision_dir: Path) -> None:
        """Cancelled while rendering: the late bytes are dropped, not registered."""
        for name in ("render.png", "render.png.meta.json", "scene.json", "plan.svg",
                     "quantity.json", "quantity.csv", "cost.html", "manifest.json",
                     "package.zip"):
            path = revision_dir / name
            if path.exists():
                path.unlink()
        try:
            revision_dir.rmdir()
        except OSError:
            pass

    def _fail(self, organization_id: str, project_id: str, job_id: str,
              code: str, message: str) -> None:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            job = tx.job(job_id)
            if not job or job["status"] in TERMINAL:
                return
            tx.close_job(job_id, "failed", "failed", now_iso(),
                         error_code=code, error_message=message,
                         only_status=("queued", "running"))

    # ------------------------------------------------------------------ recovery
    def recover(self, organization_id: str, project_id: str) -> dict[str, Any]:
        """Reclaim ONLY jobs left behind by another worker instance.

        The previous version treated "queued/running but not in the in-memory
        active set" as a restart leftover. Between the submit commit and
        ``_launch`` registering the thread there is a real window, so an ordinary
        status read could kill a perfectly healthy job. Ownership is now decided
        by the persisted ``config.run_instance`` stamp: same instance means "this
        process still owns it", different/absent means "a previous process died".

        Scope stays this batch only; other job kinds are never touched. Multi
        process deployments (two live instances) are out of scope and would need
        a real lease — that is not claimed here.
        """
        with self.repository.transaction(organization_id, project_id) as tx:
            jobs = tx.jobs(limit=None, kind=JOB_KIND)
        stale = []
        for job in jobs:
            if job["status"] not in {"queued", "running"}:
                continue
            owner = (job.get("config") or {}).get("run_instance")
            if owner == self.instance_id:
                continue  # created by this process; ownership is not lost
            stale.append(job["job_id"])
        recovered = []
        for job_id in stale:
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                if tx.close_job(job_id, "failed", "failed", now_iso(),
                                error_code="WORKER_RESTARTED",
                                error_message="服务重启，本任务中断；请显式重试",
                                only_status=("queued", "running")):
                    recovered.append(job_id)
        return {"recovered": recovered, "checked": len(jobs),
                "instance_id": self.instance_id}

    # -------------------------------------------------------------------- read
    @staticmethod
    def _is_spatial_revision(revision: dict | None) -> bool:
        return bool(revision) and str(revision.get("measurement_version") or "").startswith(
            MEASUREMENT_PREFIX)

    def _label_binding(self, revisions: list[dict], adopted: str | None) -> None:
        for item in revisions:
            bound = (item.get("package") or {}).get("binding") or {}
            if adopted and adopted == item["option_revision_id"]:
                item["binding_status"] = "current_adopted"
            elif adopted:
                item["binding_status"] = "historical_preview"
            else:
                item["binding_status"] = "candidate_preview"
            item["bound_option_revision_id"] = bound.get("adopted_option_revision_id")
            item["is_current"] = item["binding_status"] == "current_adopted"

    def status(self, organization_id: str, project_id: str, *,
               job_id: str | None = None,
               production_revision_id: str | None = None,
               history_limit: int = HISTORY_LIMIT) -> dict[str, Any]:
        """Read one job's own outputs, or an explicitly labelled overview.

        An explicit ``job_id`` / ``production_revision_id`` never falls back to
        another job's revision or artifacts, and is looked up directly by id — not
        by scanning a truncated "latest 50" window. Without parameters the page
        keeps showing the last successful output, but says so
        (``revision_source='last_successful'``).
        """
        if job_id and production_revision_id:
            raise AISpatialOutputError(
                400, "AMBIGUOUS_QUERY",
                "job_id 与 production_revision_id 不能同时指定；请只查一个对象")
        self.recover(organization_id, project_id)
        adoption = self._adoption(organization_id, project_id)
        adopted = adoption.get("option_revision_id")
        explicit = bool(job_id or production_revision_id)
        with self.repository.transaction(organization_id, project_id) as tx:
            if job_id:
                job = tx.job(job_id)
                if not job or not self._is_spatial_job(job):
                    raise AISpatialOutputError(404, "JOB_NOT_FOUND", "找不到该同源成果任务")
                revisions = [r for r in tx.revisions_by_job(job_id)
                             if self._is_spatial_revision(r)]
                jobs = [job]
                revision = revisions[0] if revisions else None
                revision_source = "requested_job" if revision else "none"
            elif production_revision_id:
                revision = tx.revision(production_revision_id)
                if not self._is_spatial_revision(revision):
                    raise AISpatialOutputError(404, "OUTPUT_NOT_FOUND", "找不到该成果修订")
                job = tx.job(revision["job_id"])
                if not job or not self._is_spatial_job(job):
                    raise AISpatialOutputError(
                        404, "JOB_NOT_FOUND", "该成果修订对应的任务不存在或不属于同源成果")
                revisions = [r for r in tx.revisions_by_job(job["job_id"])
                             if self._is_spatial_revision(r)]
                jobs = [job]
                revision_source = "requested_revision"
            else:
                jobs = tx.jobs(limit=10, kind=JOB_KIND)
                revisions = tx.revisions(limit=history_limit,
                                         measurement_prefix=MEASUREMENT_PREFIX)
                job = jobs[0] if jobs else None
                revision = None
                revision_source = "none"
                if job and job["status"] == "succeeded":
                    revision = next((r for r in revisions if r["job_id"] == job["job_id"]), None)
                    if revision:
                        revision_source = "job"
            self._label_binding(revisions, adopted)
            last_successful = next((r for r in revisions if r.get("is_current")), None) \
                or (revisions[0] if revisions else None)
            if revision is None and not explicit and last_successful is not None:
                revision = last_successful
                revision_source = "last_successful"
            artifacts = tx.artifacts(revision["production_revision_id"]) if revision else []
        return {"job": job, "jobs": jobs[:10], "revision": revision,
                "revisions": revisions, "last_successful": last_successful,
                "revision_source": revision_source,
                "query": {"job_id": job_id, "production_revision_id": production_revision_id,
                          "explicit": explicit},
                "artifacts": artifacts, "adoption": adoption,
                "boundary": {"formal_quote": False, "purchase": False,
                             "publish": False,
                             "renderer": "blender/CYCLES-CPU"
                             if self.renderer is run_blender else "injected_renderer",
                             "one_instance": True,
                             "instance_id": self.instance_id}}

    def package_status(self, organization_id: str, project_id: str,
                       production_revision_id: str) -> dict:
        """R5: registration/download boundary exposes an explicit completeness
        state; an incomplete package is always a preview, never a deliverable."""
        with self.repository.transaction(organization_id, project_id) as tx:
            revision = tx.revision(production_revision_id)
        if not revision:
            raise AISpatialOutputError(404, "OUTPUT_NOT_FOUND", "找不到该成果修订")
        package = revision.get("package") or {}
        completeness = package.get("package_completeness") or {}
        return {"status": package.get("delivery_status")
                or ("complete" if completeness.get("status") == "complete" else "preview_incomplete"),
                "complete": bool(registration_ok(package) and completeness.get("status") == "complete"),
                "package_completeness": completeness,
                "registration": package.get("registration") or {}}

    def file(self, organization_id: str, project_id: str,
             production_revision_id: str, filename: str) -> tuple[dict, bytes]:
        with self.repository.transaction(organization_id, project_id) as tx:
            revision = tx.revision(production_revision_id)
            if not revision:
                raise AISpatialOutputError(404, "OUTPUT_NOT_FOUND", "找不到该成果修订")
            artifacts = tx.artifacts(production_revision_id)
        status = self.package_status(organization_id, project_id, production_revision_id)
        for a in artifacts:
            if a["filename"] == filename:
                path = self.runtime_root / a["relative_path"]
                if not path.exists():
                    raise AISpatialOutputError(500, "FILE_MISSING", "登记的文件不存在")
                data = path.read_bytes()
                if sha256_bytes(data) != a["sha256"]:
                    raise AISpatialOutputError(500, "FILE_HASH_MISMATCH",
                                               "文件字节与登记哈希不一致")
                if a["filename"] == "package.zip":
                    # Re-open the exact download bytes against the registered
                    # manifest; a ZIP that fails its own check is never served.
                    from .ai_spatial_outputs import check_zip_against_manifest
                    manifest_artifact = next((m for m in artifacts
                                              if m["filename"] == "manifest.json"), None)
                    if not manifest_artifact:
                        raise AISpatialOutputError(500, "MANIFEST_MISSING", "成果清单登记缺失")
                    mpath = self.runtime_root / manifest_artifact["relative_path"]
                    if not mpath.exists():
                        raise AISpatialOutputError(500, "MANIFEST_MISSING", "成果清单文件缺失")
                    zcheck = check_zip_against_manifest(data, mpath.read_bytes())
                    if not zcheck["ok"]:
                        raise AISpatialOutputError(
                            500, "PACKAGE_INTEGRITY_FAILED",
                            "下载 ZIP 与登记清单不一致：" + "；".join(zcheck["problems"][:3]))
                meta = dict(a)
                meta["delivery_status"] = status["status"]
                meta["complete"] = status["complete"]
                return meta, data
        # render.png / scene.json are listed in manifest.json, not separate rows.
        # The manifest itself must match its registered SHA before it is trusted.
        manifest_file = next((a for a in artifacts if a["filename"] == "manifest.json"), None)
        if manifest_file:
            manifest_path = self.runtime_root / manifest_file["relative_path"]
            if not manifest_path.exists():
                raise AISpatialOutputError(500, "FILE_MISSING", "成果清单缺失")
            manifest_bytes = manifest_path.read_bytes()
            if sha256_bytes(manifest_bytes) != manifest_file["sha256"]:
                raise AISpatialOutputError(500, "MANIFEST_HASH_MISMATCH",
                                           "成果清单字节与登记哈希不一致，拒绝据其校验文件")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            for entry in manifest.get("files", []):
                if entry["filename"] == filename:
                    path = manifest_path.parent / filename
                    if not path.exists():
                        raise AISpatialOutputError(500, "FILE_MISSING", "登记的文件不存在")
                    data = path.read_bytes()
                    if sha256_bytes(data) != entry["sha256"]:
                        raise AISpatialOutputError(500, "FILE_HASH_MISMATCH",
                                                   "文件字节与清单哈希不一致")
                    return {"filename": filename, "content_type": entry["content_type"],
                            "sha256": entry["sha256"], "size_bytes": entry["size_bytes"],
                            "delivery_status": status["status"], "complete": status["complete"]}, data
        raise AISpatialOutputError(404, "FILE_NOT_REGISTERED", "该文件未在成果清单中登记")
