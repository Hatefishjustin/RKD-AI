"""W2 same-source output service: one frozen model revision -> visible package.

Reuses the existing AI-DEVELOPMENT job/revision/artifact tables (no migration,
no second authoritative model). The generated package is a DRAFT: no formal
quote, no purchase, no publish.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from .ai_spatial_outputs import (
    COST_VERSION, GENERATOR_VERSION, MANIFEST_VERSION, QUANTITY_VERSION,
    add_rendered, build_package, finalize_files, sha256_bytes,
)
from .models import new_id, now_iso

ROOT = Path(__file__).resolve().parents[2]
BLENDER = ROOT / "tools" / "blender" / "blender-4.2.9-windows-x64" / "blender.exe"
RENDER_SCRIPT = ROOT / "scripts" / "render_spatial_scene.py"


class AISpatialOutputError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


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
    return {"width": width, "height": height, "samples": samples, "render": render}


def run_blender(scene_path: Path, out_png: Path, width: int, height: int,
                samples: int) -> dict:
    if not BLENDER.exists():
        raise AISpatialOutputError(503, "RENDERER_UNAVAILABLE",
                                   "本机没有可用的 Blender 执行器")
    cmd = [str(BLENDER), "-b", "--factory-startup", "-noaudio",
           "--python", str(RENDER_SCRIPT), "--",
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
                 renderer: Callable[[Path, Path, int, int, int], dict] | None = None) -> None:
        self.repository = repository
        self.option_service = option_service
        self.runtime_root = Path(runtime_root).resolve()
        self.start_workers = start_workers
        self.renderer = renderer or run_blender
        self._lock = threading.Lock()
        self._active: set[str] = set()

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
        if (revision.get("validation") or {}).get("status") != "passed":
            raise AISpatialOutputError(422, "MODEL_NOT_VALIDATED", "模型修订未通过硬检查")
        if settings["render"] and not BLENDER.exists():
            raise AISpatialOutputError(503, "RENDERER_UNAVAILABLE", "本机没有可用的 Blender 执行器")
        adoption = self.option_service.status(organization_id, project_id).get("adoption") or {}
        adopted = adoption.get("option_revision_id") == option_revision_id
        input_hash = _digest({"model": revision["model_hash"] if "model_hash" in revision else None,
                              "option_revision_id": option_revision_id,
                              "settings": settings, "generator": GENERATOR_VERSION})
        config = {"kind": "spatial_outputs", "generator_version": GENERATOR_VERSION,
                  "plan_version": "rkd-spatial-plan.v2", "scene_version": "rkd-spatial-scene.v1",
                  "quantity_version": QUANTITY_VERSION, "cost_version": COST_VERSION,
                  "renderer": "blender-4.2.9/CYCLES-CPU",
                  "baseline_status": ("adopted_draft" if adopted
                                      else "candidate_preview_not_adopted")}
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
                "adoption_version": int(adoption.get("expected_revision") or 0),
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

    def _launch(self, organization_id: str, project_id: str, job_id: str) -> None:
        with self._lock:
            self._active.add(job_id)
        threading.Thread(target=self._run, args=(organization_id, project_id, job_id),
                         name=f"rkd-spatial-{job_id}", daemon=True).start()

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
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                tx.update_job(job_id, status="running", phase="geometry", updated_at=now_iso())
            package = build_package(model, project_id=project_id,
                                    option_revision_id=revision_id, settings=settings)
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                tx.update_job(job_id, status="running", phase="measurement", updated_at=now_iso())
            # render outside any DB transaction
            revision_dir = (self.runtime_root / "projects" / "ai-spatial-outputs"
                            / job_id)
            revision_dir.mkdir(parents=True, exist_ok=True)
            scene_path = revision_dir / "scene.json"
            scene_path.write_bytes(_json(package["scene"]))
            render_meta = None
            png = b""
            if settings["render"]:
                png_path = revision_dir / "render.png"
                render_meta = self.renderer(scene_path, png_path, settings["width"],
                                            settings["height"], settings["samples"])
                png = png_path.read_bytes()
                add_rendered(package["manifest"], filename="render.png", png=png,
                             render_meta={**render_meta,
                                          "assumption": "机位/材质/家具高度为渲染假设，非实测"})
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                tx.update_job(job_id, status="running", phase="pricing", updated_at=now_iso())
            files = finalize_files(package["files"], package["manifest"])
            # write every file, then register in ONE transaction
            written: list[tuple[str, str, str, bytes, str]] = []
            seen_kinds: set[str] = set()
            for name, (kind, ctype, data) in files.items():
                path = revision_dir / name
                path.write_bytes(data)
                # one artifact row per (revision, kind); the rest stay in the
                # manifest + package.zip with their own sha256
                if kind in seen_kinds:
                    continue
                seen_kinds.add(kind)
                written.append((name, kind, ctype, data,
                                path.relative_to(self.runtime_root).as_posix()))
            if png:
                (revision_dir / "render.png").write_bytes(png)
            production_revision_id = new_id("ai-production-revision")
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                job_now = tx.job(job_id)
                if not job_now or job_now["status"] != "running":
                    return
                tx.insert_revision({
                    "production_revision_id": production_revision_id,
                    "job_id": job_id, "option_revision_id": revision_id,
                    "set_id": revision["set_id"], "option_id": revision["option_id"],
                    "adoption_version": job["adoption_version"],
                    "input_hash": job["input_hash"],
                    "baseline": package["frozen"],
                    "package": {"schema_version": MANIFEST_VERSION,
                                "render": package["manifest"].get("render"),
                                "missing": package["manifest"]["missing"]},
                    "quantities": package["quantities"], "cost": package["cost"],
                    "objects": {"zones": model["spatial"]["zones"],
                                "furniture": model["spatial"]["furniture"],
                                "platforms": model["spatial"].get("platforms") or []},
                    "materials": {"main": model["materials"],
                                  "spatial": model["spatial"]["materials"]},
                    "unknowns": package["cost"]["unknown_items"],
                    "view_mapping": {"camera": package["camera"],
                                     "plan_version": "rkd-spatial-plan.v2"},
                    "formula_version": QUANTITY_VERSION,
                    "measurement_version": GENERATOR_VERSION,
                    "output_version": MANIFEST_VERSION,
                    "actor_id": job["actor_id"], "created_at": now_iso(),
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
                tx.update_job(job_id, status="succeeded", phase="completed",
                              updated_at=now_iso())
            with self.repository.transaction(organization_id, project_id, write=True) as tx:
                job2 = tx.job(job_id)
                if job2 and job2["status"] == "running":
                    tx.update_job(job_id, status="succeeded", phase="completed",
                                  updated_at=now_iso())
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

    def _fail(self, organization_id: str, project_id: str, job_id: str,
              code: str, message: str) -> None:
        with self.repository.transaction(organization_id, project_id, write=True) as tx:
            job = tx.job(job_id)
            if not job or job["status"] in {"succeeded", "cancelled"}:
                return
            tx.update_job(job_id, status="failed", phase="failed", updated_at=now_iso(),
                          error_code=code, error_message=message)

    # -------------------------------------------------------------------- read
    def status(self, organization_id: str, project_id: str) -> dict[str, Any]:
        with self.repository.transaction(organization_id, project_id) as tx:
            jobs = [j for j in tx.jobs(limit=50)
                    if (j.get("config") or {}).get("kind") == "spatial_outputs"]
            job = jobs[0] if jobs else None
            revision = None
            artifacts = []
            if job and job["status"] == "succeeded":
                revision = tx.latest_succeeded_revision()
                if revision and revision["job_id"] != job["job_id"]:
                    revision = None
                if revision:
                    artifacts = tx.artifacts(revision["production_revision_id"])
            return {"job": job, "jobs": jobs[:5], "revision": revision,
                    "artifacts": artifacts,
                    "boundary": {"formal_quote": False, "purchase": False,
                                 "publish": False, "renderer": "blender/CYCLES-CPU"}}

    def file(self, organization_id: str, project_id: str,
             production_revision_id: str, filename: str) -> tuple[dict, bytes]:
        with self.repository.transaction(organization_id, project_id) as tx:
            revision = tx.revision(production_revision_id)
            if not revision:
                raise AISpatialOutputError(404, "OUTPUT_NOT_FOUND", "找不到该成果修订")
            artifacts = tx.artifacts(production_revision_id)
        for a in artifacts:
            if a["filename"] == filename:
                path = self.runtime_root / a["relative_path"]
                if not path.exists():
                    raise AISpatialOutputError(500, "FILE_MISSING", "登记的文件不存在")
                data = path.read_bytes()
                if sha256_bytes(data) != a["sha256"]:
                    raise AISpatialOutputError(500, "FILE_HASH_MISMATCH",
                                               "文件字节与登记哈希不一致")
                return a, data
        # render.png / scene.json are listed in manifest.json, not separate rows
        manifest_file = next((a for a in artifacts if a["filename"] == "manifest.json"), None)
        if manifest_file:
            manifest = json.loads((self.runtime_root / manifest_file["relative_path"])
                                  .read_text(encoding="utf-8"))
            for entry in manifest.get("files", []):
                if entry["filename"] == filename:
                    path = (self.runtime_root / manifest_file["relative_path"]).parent / filename
                    if not path.exists():
                        raise AISpatialOutputError(500, "FILE_MISSING", "登记的文件不存在")
                    data = path.read_bytes()
                    if sha256_bytes(data) != entry["sha256"]:
                        raise AISpatialOutputError(500, "FILE_HASH_MISMATCH",
                                                   "文件字节与清单哈希不一致")
                    return {"filename": filename, "content_type": entry["content_type"],
                            "sha256": entry["sha256"], "size_bytes": entry["size_bytes"]}, data
        raise AISpatialOutputError(404, "FILE_NOT_REGISTERED", "该文件未在成果清单中登记")
