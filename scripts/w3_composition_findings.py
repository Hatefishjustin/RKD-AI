"""Reproduce the R1 composition-root gap against a given code root.

Same harness on the frozen baseline (446a6f6) and the fixed tree.  It drives
ONLY the real application API (``ApiService`` public methods) against an
isolated SQLite store and a local protocol stub opener injected at the
composition root seam.  No private helper is called in place of the product
entry point, no paid model call, no real key.

    python scripts/w3_composition_findings.py --code-root <dir> \
        --label before|after --out <dir> [--expect vulnerable|fixed]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASEMAP = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"
FIXTURE = ROOT / "fixtures/ningbo-xiecheng/2026-09"
ORG = "org-local"
PROJECT = "project_ningbo_xiecheng_2026"


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class FailingRenderer:
    def __call__(self, *args, **kwargs):
        raise RuntimeError("stub render failure")


class BlockingRenderer:
    def __init__(self) -> None:
        self.release = threading.Event()

    def __call__(self, *args, **kwargs):
        self.release.wait(timeout=15)
        return {"engine": "blocking-stub"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-root", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect", choices=("vulnerable", "fixed"), default=None)
    args = ap.parse_args()
    code_root = Path(args.code_root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for p in (code_root / "mvp", code_root, ROOT / "scripts"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))

    from rkd_mvp.sqlite_store import SQLiteStore
    from rkd_mvp.file_service import FileService
    from rkd_mvp.requirement_service import RequirementService
    from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository
    from rkd_mvp.ai_requirement_service import AIRequirementService
    from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider
    from rkd_mvp.api_service import ApiService, ApiError
    from rkd_mvp.engine import MVPApp
    from rkd_mvp.ai_design_option_provider import DesignOptionConfig
    from w3_trust_findings import CapturingOpener, candidate

    # Does the target composition root support the seams needed to wire a real
    # provider without an external call?  Baseline 446a6f6 does NOT.
    import inspect
    api_params = inspect.signature(ApiService.__init__).parameters
    seam_supported = ("design_transport_opener" in api_params and
                      "design_option_config" in api_params)
    results: dict[str, dict] = {}

    cfg = DesignOptionConfig(
        kind="openai_compatible", name="stub", adapter_version="stub", prompt_version="pv",
        schema_version="rkd-ai-design-option.v1", max_candidates=2, real_model=True,
        configuration_errors=[], base_url="http://127.0.0.1:9/stub", model_id="stub-model",
        api_key_present=True, max_attempts=2, timeout_seconds=5, external_context_allowed=False)

    directory = Path(tempfile.mkdtemp())
    db = directory / "app.sqlite3"
    store = SQLiteStore(db)
    files = FileService(db, directory)
    reqs = RequirementService(db)
    req_cfg = AIProviderConfig(
        kind="synthetic", name="s", model_id=None, base_url=None, api_key_present=False,
        adapter_version="v1", prompt_version="pv", schema_version="rkd-ai-design-brief.v1",
        max_input_chars=8000, max_output_tokens=2000, timeout_seconds=20,
        external_context_allowed=False, real_model=False, configuration_errors=[])
    req_ai = AIRequirementService(SQLiteAIRequirementRepository(db), reqs, config=req_cfg,
                                  provider_factory=lambda c: build_provider(c))
    opener = CapturingOpener({"branch": candidate("branch", 10.3),
                              "loop": candidate("loop", 10.3)})

    def renderer(scene_path, out_png, width, height, samples):
        out_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 300)
        return {"engine": "stub-renderer", "width": width, "height": height, "samples": samples}

    kwargs: dict = {}
    if seam_supported:
        kwargs = {"design_option_config": cfg, "design_transport_opener": opener,
                  "spatial_renderer": renderer}
    service = ApiService(
        MVPApp(store), files, requirement_service=reqs, ai_requirement_service=req_ai,
        runtime_root=directory, **kwargs)
    files.seed_ningbo(service, FIXTURE)
    results["runtime_injected"] = {
        "ok": getattr(service, "controlled_design_runtime", None) is not None,
        "detail": {"seam_supported": seam_supported,
                   "runtime": getattr(service, "controlled_design_runtime", None) is not None}}

    brief_item = service.submit_ai_requirement(
        ORG, PROJECT, "tester", {"natural_language": "开放交流，入口在左侧"}, "brief-000001")["item"]
    req_ai.wait_for_job(ORG, PROJECT, brief_item["job_id"])

    # C1: submit -> succeeded -> adopt through public API
    chain = {"succeeded": False, "adopted": False, "schema": None, "origin": None,
             "runs_all_simulated": False}
    try:
        item = service.submit_ai_design_options(ORG, PROJECT, "tester", {}, "options-000001")["item"]
        if hasattr(service.ai_design_option_service, "wait_for_set"):
            service.ai_design_option_service.wait_for_set(ORG, PROJECT, item["set_id"])
        state = service.get_ai_design_options(ORG, PROJECT)
        set_row = next((s for s in state["sets"] if s["set_id"] == item["set_id"]), None)
        chain["succeeded"] = bool(set_row and set_row["status"] == "succeeded")
        chain["set_status"] = (set_row or {}).get("status")
        chain["set_error_code"] = (set_row or {}).get("error_code")
        if chain["succeeded"] and state.get("item"):
            option = state["item"]["options"][0]
            chain["schema"] = option["model"]["schema_version"]
            chain["origin"] = (option["model"].get("spatial", {}).get("source", {})
                               .get("design_origin", {}).get("kind"))
            runtime = getattr(service, "controlled_design_runtime", None)
            runs = runtime.run_service.export_public() if runtime is not None else []
            chain["runs_all_simulated"] = bool(runs) and all(
                r.get("simulated") is True for r in runs)
            result = service.adopt_ai_design_option(ORG, PROJECT, "tester", {
                "option_id": option["option_id"], "expected_revision": 1, "expected_version": 0})
            chain["adopted"] = result["item"]["status"] == "adopted_draft"
    except Exception as error:  # noqa: BLE001
        chain["error"] = f"{type(error).__name__}: {getattr(error, 'code', '')}"
    results["chain"] = {"ok": chain["succeeded"] and chain["adopted"], "detail": chain}

    # C2: real config without runtime must fail clearly, not fall back.
    missing = {"failed_clearly": False}
    if hasattr(service.ai_design_option_service, "controlled_runtime"):
        saved = service.ai_design_option_service.controlled_runtime
        service.ai_design_option_service.controlled_runtime = None
        try:
            service.submit_ai_design_options(ORG, PROJECT, "tester", {}, "options-000002")
        except ApiError as error:
            missing["failed_clearly"] = error.code == "CONTROLLED_RUNTIME_REQUIRED"
            missing["code"] = error.code
        service.ai_design_option_service.controlled_runtime = saved
    results["missing_runtime"] = {"ok": missing["failed_clearly"], "detail": missing}

    # C3: feedback rejection preserves original revision.
    feedback = {"rejected": False, "original_preserved": False}
    if results["chain"]["ok"]:
        option = service.get_ai_design_options(ORG, PROJECT)["item"]["options"][0]
        before = option["option_revision_id"]
        try:
            service.revise_ai_design_option(ORG, PROJECT, "tester", {
                "option_id": option["option_id"], "expected_revision": 1,
                "feedback": "改成右侧中岛", "locks": []})
        except ApiError as error:
            feedback["rejected"] = error.code in {
                "CONTROLLED_FEEDBACK_PATH_UNSUPPORTED", "INVALID_FEEDBACK_BASELINE"}
        after = service.get_ai_design_options(ORG, PROJECT)["item"]["options"][0]
        feedback["original_preserved"] = after["option_revision_id"] == before and after["revision_no"] == 1
    results["feedback"] = {"ok": feedback["rejected"] and feedback["original_preserved"],
                           "detail": feedback}

    # C4: output four states driven by public API (only when chain succeeded).
    outputs = {"complete": False, "preview": False, "failed": False, "cancelled": False}
    output_evidence: dict = {}
    if results["chain"]["ok"] and "spatial_renderer" in api_params:
        option = service.get_ai_design_options(ORG, PROJECT)["item"]["options"][0]

        def wait(svc, job_id, timeout=10.0):
            deadline = time.monotonic() + timeout
            row = None
            while time.monotonic() < deadline:
                row = svc.get_ai_spatial_outputs(ORG, PROJECT, job_id=job_id)["job"]
                if row and row["status"] in {"succeeded", "failed", "cancelled"}:
                    return row
                time.sleep(0.02)
            return row

        req = {"option_revision_id": option["option_revision_id"],
               "expected_version": 1, "settings": {"render": True}}
        job = wait(service, service.submit_ai_spatial_outputs(
            ORG, PROJECT, "tester", req, "out-ok-00001")["item"]["job_id"])
        if job["status"] == "succeeded":
            rev = service.get_ai_spatial_outputs(ORG, PROJECT, job_id=job["job_id"])["revision"]["production_revision_id"]
            meta, data = service.get_ai_spatial_output_file(ORG, PROJECT, rev, "package.zip")
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                byte_ok = all(hashlib.sha256(zf.read(e["filename"])).hexdigest() == e["sha256"]
                              for e in manifest["files"])
            outputs["complete"] = bool(meta.get("complete") and byte_ok
                                       and meta.get("delivery_status") == "complete")
            output_evidence["complete"] = {
                "job": job["status"], "delivery_status": meta.get("delivery_status"),
                "manifest_entries": len(manifest["files"]), "zip_bytes": len(data),
                "zip_sha256": hashlib.sha256(data).hexdigest(),
                "every_entry_sha_matches": byte_ok,
                "render_listed": any(e["filename"].endswith(".png") for e in manifest["files"])}

        req2 = {**req, "settings": {"render": False}}
        job2 = wait(service, service.submit_ai_spatial_outputs(
            ORG, PROJECT, "tester", req2, "out-no-00002")["item"]["job_id"])
        if job2["status"] == "succeeded":
            rev2 = service.get_ai_spatial_outputs(ORG, PROJECT, job_id=job2["job_id"])["revision"]["production_revision_id"]
            meta2, data2 = service.get_ai_spatial_output_file(ORG, PROJECT, rev2, "package.zip")
            with zipfile.ZipFile(io.BytesIO(data2)) as zf:
                manifest2 = json.loads(zf.read("manifest.json").decode("utf-8"))
            outputs["preview"] = (not meta2.get("complete")
                                  and meta2.get("delivery_status") == "preview_incomplete"
                                  and manifest2["package_completeness"]["status"] == "incomplete")
            output_evidence["preview"] = {
                "job": job2["status"], "delivery_status": meta2.get("delivery_status"),
                "complete": meta2.get("complete"),
                "manifest_completeness": manifest2["package_completeness"],
                "zip_sha256": hashlib.sha256(data2).hexdigest()}

        # render failure: same store, fresh public composition root, failing renderer
        fail_service = ApiService(
            MVPApp(store), files, requirement_service=reqs, ai_requirement_service=req_ai,
            runtime_root=directory, design_option_config=cfg,
            design_transport_opener=opener, spatial_renderer=FailingRenderer())
        pending = fail_service.submit_ai_spatial_outputs(
            ORG, PROJECT, "tester", req, "out-failed-00003")["item"]
        failed = wait(fail_service, pending["job_id"])
        outputs["failed"] = bool(failed["status"] == "failed"
                                 and failed.get("error_code") in {"RENDER_FAILED", "SPATIAL_OUTPUT_FAILED"}
                                 and fail_service.get_ai_spatial_outputs(
                                     ORG, PROJECT, job_id=pending["job_id"])["revision"] is None)
        output_evidence["failed"] = {"job": failed["status"],
                                     "error_code": failed.get("error_code"),
                                     "revision_registered": False}

        # cancel while rendering
        blocking = BlockingRenderer()
        cancel_service = ApiService(
            MVPApp(store), files, requirement_service=reqs, ai_requirement_service=req_ai,
            runtime_root=directory, design_option_config=cfg,
            design_transport_opener=opener, spatial_renderer=blocking)
        pending_c = cancel_service.submit_ai_spatial_outputs(
            ORG, PROJECT, "tester", req, "out-cancel-00004")["item"]
        cancelled = cancel_service.cancel_ai_spatial_output(ORG, PROJECT, pending_c["job_id"])["item"]
        blocking.release.set()
        cancel_service.ai_spatial_output_service.wait_for_idle()
        outputs["cancelled"] = bool(cancelled["status"] == "cancelled"
                                    and cancel_service.get_ai_spatial_outputs(
                                        ORG, PROJECT, job_id=pending_c["job_id"])["revision"] is None)
        output_evidence["cancelled"] = {"job": cancelled["status"],
                                        "revision_registered": False}
    results["outputs"] = {"ok": all(outputs.values()),
                          "detail": {**outputs, "evidence": output_evidence}}

    summary = {name: ("fixed" if value["ok"] else "vulnerable")
               for name, value in results.items()}
    audit = {"schema_version": "rkd-w3-composition-findings.v1",
             "baseline": "446a6f6", "code_root": str(code_root), "label": args.label,
             "results": results, "summary": summary,
             "external_calls": 0, "cost_cny": 0, "keys_used": False}
    (out / "findings.json").write_bytes(canon(audit))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if args.expect == "vulnerable":
        return 0 if all(v == "vulnerable" for v in summary.values()) else 2
    if args.expect == "fixed":
        return 0 if all(v == "fixed" for v in summary.values()) else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
