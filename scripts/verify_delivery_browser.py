"""Drive a real browser acceptance run against an isolated local workbench."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))

from rkd_mvp.ai_design_option_provider import DesignOptionConfig, build_design_option_provider  # noqa: E402
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository  # noqa: E402
from rkd_mvp.ai_design_option_service import AIDesignOptionService  # noqa: E402
from rkd_mvp.ai_development_repository import SQLiteAIDevelopmentRepository  # noqa: E402
from rkd_mvp.ai_development_service import AIDevelopmentService  # noqa: E402
from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider  # noqa: E402
from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository  # noqa: E402
from rkd_mvp.ai_requirement_service import AIRequirementService  # noqa: E402
from rkd_mvp.api_server import create_server  # noqa: E402
from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.identity import LocalIdentityProvider  # noqa: E402
from rkd_mvp.professional_delivery import (AISourceExtractionService, AITechnicalDeliveryService,  # noqa: E402
                                           SQLiteAIProfessionalDeliveryRepository)
from rkd_mvp.requirement_service import RequirementService  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402

ORG = "org-local"
FIXTURE_ROOT = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
STAMP = "2026-11-09"
NOTE_NAME = "浏览器验收说明.txt"
NOTE_TEXT = "入口在左侧，暖木色材料意向。\n洽谈区需要相对独立。\n".encode("utf-8")


def requirement_config() -> AIProviderConfig:
    return AIProviderConfig(kind="synthetic", name="本地合成测试通道（非真实 AI）", model_id=None,
                            base_url=None, api_key_present=False, adapter_version="rkd-model-provider.v1",
                            prompt_version="requirement-understanding.zh-CN.v1",
                            schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
                            max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
                            real_model=False, configuration_errors=[])


def option_config() -> DesignOptionConfig:
    return DesignOptionConfig(kind="synthetic", name="本地合成设计通道（非真实 AI）",
                              adapter_version="rkd-design-option-provider.v1",
                              prompt_version="design-option-strategy.zh-CN.v1",
                              schema_version="rkd-ai-design-option.v1", max_candidates=2,
                              real_model=False, configuration_errors=[])


def build(runtime: Path):
    db = runtime / "app.sqlite3"
    store = SQLiteStore(db)
    files = FileService(db, runtime)
    requirements = RequirementService(db)
    repository = SQLiteAIProfessionalDeliveryRepository(db)
    extraction = AISourceExtractionService(repository, files)
    brief_service = AIRequirementService(
        SQLiteAIRequirementRepository(db), requirements, config=requirement_config(),
        provider_factory=lambda config: build_provider(config), extraction_service=extraction)
    options = AIDesignOptionService(
        SQLiteAIDesignOptionRepository(db),
        lambda org, project: brief_service.status(org, project)["item"],
        lambda org, project: {"width": "12", "length": "8",
                              "boundary_source": "test_parameters_not_site_verified", "obstacles": []},
        runtime, config=option_config(), provider=build_design_option_provider(option_config()))
    development = AIDevelopmentService(SQLiteAIDevelopmentRepository(db), options, runtime)
    technical = AITechnicalDeliveryService(repository, development, extraction, runtime)
    service = ApiService(MVPApp(store), files, requirement_service=requirements,
                         ai_requirement_service=brief_service, ai_design_option_service=options,
                         ai_development_service=development,
                         ai_source_extraction_service=extraction,
                         ai_technical_delivery_service=technical, runtime_root=runtime)
    files.seed_ningbo(service, FIXTURE_ROOT)
    initiated = files.initiate(ORG, NINGBO_PROJECT_ID,
                               {"filename": NOTE_NAME, "size_bytes": len(NOTE_TEXT),
                                "sha256": hashlib.sha256(NOTE_TEXT).hexdigest()})
    files.receive(ORG, NINGBO_PROJECT_ID, initiated["upload_id"], io.BytesIO(NOTE_TEXT), len(NOTE_TEXT))
    files.complete(ORG, NINGBO_PROJECT_ID, initiated["upload_id"], "")

    brief_job = service.submit_ai_requirement(ORG, NINGBO_PROJECT_ID, "browser-qa",
                                              {"natural_language": "开放交流，入口在左侧，暖木色，保留独立洽谈"},
                                              "browser-brief-0001")["item"]
    brief_service.wait_for_job(ORG, NINGBO_PROJECT_ID, brief_job["job_id"])
    option_set = service.submit_ai_design_options(ORG, NINGBO_PROJECT_ID, "browser-qa", {},
                                                  "browser-options-0001")["item"]
    options.wait_for_set(ORG, NINGBO_PROJECT_ID, option_set["set_id"])
    state = service.get_ai_design_options(ORG, NINGBO_PROJECT_ID)
    chosen = next(item for item in state["item"]["options"] if item["strategy_id"] == "open-loop")
    service.adopt_ai_design_option(ORG, NINGBO_PROJECT_ID, "browser-qa",
                                   {"option_id": chosen["option_id"], "expected_revision": 1,
                                    "expected_version": 0})
    job = service.submit_ai_development(ORG, NINGBO_PROJECT_ID, "browser-qa",
                                        {"expected_version": 1, "settings": {}},
                                        "browser-development-0001")["item"]
    development.wait_for_job(ORG, NINGBO_PROJECT_ID, job["job_id"])
    return service, store, (brief_service, options, development), technical


def main() -> int:
    started = time.monotonic()
    evidence = ROOT / "var" / "evidence" / "delivery-browser" / STAMP / (
        "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3))
    evidence.mkdir(parents=True)
    runtime = evidence / "runtime"
    runtime.mkdir()
    service, store, workers, technical = build(runtime)
    server = create_server(service, LocalIdentityProvider(), port=0, static_dir=ROOT / "web" / "dist")
    thread = threading.Thread(target=server.serve_forever, name="rkd-delivery-browser", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    env = {key: value for key, value in os.environ.items()
           if key not in {"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"}}
    env.update({"RKD_QA_URL": url, "RKD_QA_EVIDENCE_DIR": str(evidence),
                "RKD_QA_PROJECT_ID": NINGBO_PROJECT_ID})
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node executable not found")
    try:
        process = subprocess.run([node, str(ROOT / "scripts" / "verify_delivery_browser.cjs")],
                                 cwd=ROOT, env=env, capture_output=True, text=True,
                                 errors="replace", timeout=360)
        (evidence / "browser-stdout.log").write_text(process.stdout or "", encoding="utf-8")
        (evidence / "browser-stderr.log").write_text(process.stderr or "", encoding="utf-8")
        passed = process.returncode == 0
        result = {
            "schema_version": "rkd-delivery-browser-verification.v1",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "url": url, "project_id": NINGBO_PROJECT_ID,
            "passed": passed, "node_returncode": process.returncode,
            "duration_seconds": round(time.monotonic() - started, 2),
            "evidence_files": sorted(path.name for path in evidence.iterdir() if path.is_file()),
            "technical_delivery_status": technical.status(ORG, NINGBO_PROJECT_ID)["item"]["status"],
            "boundaries": ["isolated local SQLite workbench; daily database and NAS untouched",
                           "synthetic adapter only; AD01—AD08 remain 0/8",
                           "browser evidence supports engineering acceptance, not design/professional sign-off"],
        }
        (evidence / "verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        if not passed:
            print((process.stderr or process.stdout or "")[-2500:], flush=True)
        return 0 if passed else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        for worker in workers:
            worker.wait_for_idle()
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
