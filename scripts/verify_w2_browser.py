"""W2 真实浏览器验收：页面选择模型修订 → 生成同源成果 → 看平面/人眼图/净量/下载。

用法：python scripts/verify_w2_browser.py --out <dir> --runtime <dir>
0 外部模型调用；渲染本机 Blender。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _arg(flag: str, default: Path) -> Path:
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).resolve()
        if a.startswith(flag + "="):
            return Path(a.split("=", 1)[1]).resolve()
    return default


EVIDENCE = _arg("--out", ROOT / "var/evidence/roadmap/W2-同源成果切片/after/browser")
RUNTIME = _arg("--runtime", ROOT / "var/evidence/roadmap/W2-同源成果切片/browser-runtime")
EVIDENCE.mkdir(parents=True, exist_ok=True)
RUNTIME.mkdir(parents=True, exist_ok=True)
MAIN_DB = RUNTIME / "app.sqlite3"
STUDIO_DB = RUNTIME / "studio.db"
for f in (MAIN_DB, STUDIO_DB):
    if f.exists():
        f.unlink()

sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from arc_first_batch_stub import SITE, valid_proposal  # noqa: E402
from rkd_mvp.ai_design_option_provider import (  # noqa: E402
    DesignOptionConfig, build_design_option_provider)
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository  # noqa: E402
from rkd_mvp.ai_design_option_service import AIDesignOptionService  # noqa: E402
from rkd_mvp.ai_design_studio_adapter import StudioProposalSource  # noqa: E402
from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider  # noqa: E402
from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository  # noqa: E402
from rkd_mvp.ai_requirement_service import AIRequirementService  # noqa: E402
from rkd_mvp.ai_spatial_output_service import AISpatialOutputService  # noqa: E402
from rkd_mvp.api_server import create_server  # noqa: E402
from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.identity import LocalIdentityProvider  # noqa: E402
from rkd_mvp.requirement_service import RequirementService  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from rkd_mvp.studio import orchestrator, validation  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402

FIXTURE_ROOT = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def main() -> int:
    started = time.monotonic()
    studio = Store(STUDIO_DB)
    orchestrator.Studio(studio).seed_from_fixtures()
    source = StudioProposalSource(studio)
    rep = validation.validate_proposal(
        valid_proposal("A"), project={"id": "ningbo-xiecheng", "site": SITE},
        option_id="A", revision=1, parent_revision=None)
    art_id = studio.save_artifact(
        "ningbo-xiecheng", "spatial-plan", rep["plan"], "D2", option_id="A", revision=1,
        status="valid_candidate", contract_status="valid_candidate",
        revision_uid="uid-w2-browser", run_id="run-w2-browser",
        candidate_group_id="group-w2-browser",
        input_hash_value=hashlib.sha256(json.dumps(rep["plan"], sort_keys=True).encode()).hexdigest(),
        check_report_id="check-w2-browser", diagnostics={"source": "labelled_local_fixture"})

    main_store = SQLiteStore(MAIN_DB)
    files = FileService(MAIN_DB, RUNTIME)
    requirements = RequirementService(MAIN_DB)
    brief_config = AIProviderConfig(
        kind="synthetic", name="本地合成测试通道（非真实 AI）", model_id=None,
        base_url=None, api_key_present=False, adapter_version="rkd-model-provider.v1",
        prompt_version="requirement-understanding.zh-CN.v1",
        schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
        max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
        real_model=False, configuration_errors=[])
    option_config = DesignOptionConfig(
        kind="synthetic", name="本地合成设计通道（非真实 AI）",
        adapter_version="rkd-design-option-provider.v1",
        prompt_version="design-option-strategy.zh-CN.v1",
        schema_version="rkd-ai-design-option.v1", max_candidates=2,
        real_model=False, configuration_errors=[])
    requirement_ai = AIRequirementService(
        SQLiteAIRequirementRepository(MAIN_DB), requirements, config=brief_config,
        provider_factory=lambda config: build_provider(config))
    options_ai = AIDesignOptionService(
        SQLiteAIDesignOptionRepository(MAIN_DB),
        lambda org, project: requirement_ai.status(org, project)["item"],
        lambda org, project: {"width": "12", "length": "8",
                              "boundary_source": "test_parameters_not_site_verified",
                              "obstacles": []},
        RUNTIME, config=option_config,
        provider=build_design_option_provider(option_config), studio_source=source)
    spatial_ai = AISpatialOutputService(
        __import__("rkd_mvp.ai_development_repository", fromlist=["SQLiteAIDevelopmentRepository"])
        .SQLiteAIDevelopmentRepository(MAIN_DB), options_ai, RUNTIME, start_workers=True)
    service = ApiService(MVPApp(main_store), files, requirement_service=requirements,
                         ai_requirement_service=requirement_ai,
                         ai_design_option_service=options_ai,
                         ai_spatial_output_service=spatial_ai, runtime_root=RUNTIME,
                         studio_source=source)
    files.seed_ningbo(service, FIXTURE_ROOT)
    imp = service.import_ai_design_studio_proposal(
        "org-local", NINGBO_PROJECT_ID, "local-user",
        {"studio_project_id": "ningbo-xiecheng", "studio_artifact_id": art_id,
         "expected_source_sha256": art_id and studio.artifact_by_id(art_id)["sha256"],
         "expected_unit": "mm"})
    service.adopt_ai_design_option("org-local", NINGBO_PROJECT_ID, "local-user",
                                   {"option_id": imp["item"]["option_id"],
                                    "expected_revision": imp["item"]["revision_no"],
                                    "expected_version": 0})

    port = _free_port()
    server = create_server(service, LocalIdentityProvider(), port=port,
                           static_dir=ROOT / "web" / "dist")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {k: v for k, v in os.environ.items()
           if k not in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                        "ALL_PROXY", "all_proxy")}
    env.update({"RKD_QA_URL": f"http://127.0.0.1:{port}",
                "RKD_QA_EVIDENCE_DIR": str(EVIDENCE),
                "RKD_QA_PROJECT_ID": NINGBO_PROJECT_ID,
                "RKD_QA_OPTION_REVISION_ID": imp["item"]["option_revision_id"]})
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node not found")
    try:
        proc = subprocess.run([node, str(ROOT / "scripts" / "verify_w2_browser.cjs")],
                              cwd=str(ROOT), env=env, capture_output=True, text=True,
                              errors="replace", timeout=900)
        (EVIDENCE / "browser-stdout.log").write_text(proc.stdout or "", encoding="utf-8")
        (EVIDENCE / "browser-stderr.log").write_text(proc.stderr or "", encoding="utf-8")
        obs_path = EVIDENCE / "browser-observations.json"
        obs = json.loads(obs_path.read_text(encoding="utf-8")) if obs_path.exists() else {}
        result = {"schema_version": "rkd-w2-browser-verification.v1",
                  "checked_at": datetime.now(timezone.utc).isoformat(),
                  "passed": bool(proc.returncode == 0 and obs.get("passed")),
                  "node_returncode": proc.returncode,
                  "duration_seconds": round(time.monotonic() - started, 2),
                  "browser_observations": obs,
                  "external_calls": 0, "keys_used": False,
                  "boundaries": ["隔离主工作台 + 隔离 Studio；日常库未写入",
                                 "渲染为本机 Blender，不是外部图像通道",
                                 "本页成果是内部评审，不是施工图/报价/发布"]}
        (EVIDENCE / "verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": result["passed"],
                          "node_returncode": proc.returncode}, ensure_ascii=False))
        if not result["passed"]:
            print((proc.stderr or proc.stdout or "")[-3000:], flush=True)
        return 0 if result["passed"] else 1
    finally:
        server.shutdown(); server.server_close(); thread.join(3)
        main_store.close()


if __name__ == "__main__":
    raise SystemExit(main())
