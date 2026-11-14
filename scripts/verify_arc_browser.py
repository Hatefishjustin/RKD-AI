"""Real-browser acceptance for the ARC first batch, with isolated services.

Starts:
  * isolated main workbench (fresh SQLite + seeded Ningbo + a second project)
  * isolated Studio service (RKD_STUDIO_DB -> scratch db, NEVER the daily DB)
  * local model stub ONLY (no key, no external call, no cost)

Then drives a real Chromium/Edge browser through:
  1. valid-candidate grouping / history separation
  2. boss message -> versioned effective requirement
  3. run a loop -> new revision bound to the original baseline + object diff
  4. switching to another project does NOT show Ningbo results
  5. gate decision scope + replay cannot overwrite the decided record
  6. reload (restart persistence) keeps feedback / decisions / artifacts
"""
from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

EVIDENCE = ROOT / "var" / "evidence" / "architecture-handoff" / "first-batch" / "after" / "browser"
EVIDENCE.mkdir(parents=True, exist_ok=True)
RUNTIME = EVIDENCE / "runtime"
RUNTIME.mkdir(exist_ok=True)
STUDIO_DB = RUNTIME / "studio.db"
MAIN_DB = RUNTIME / "app.sqlite3"

# isolation must be set BEFORE studio modules are imported
os.environ["RKD_STUDIO_DB"] = str(STUDIO_DB)
# clear sandbox proxy for loopback browser work (no external calls involved)
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

from rkd_mvp.api_server import create_server  # noqa: E402
from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.identity import LocalIdentityProvider  # noqa: E402
from rkd_mvp.requirement_service import RequirementService  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402
from rkd_mvp.studio import llm as studio_llm  # noqa: E402
from rkd_mvp.studio import orchestrator, server as studio_server, vision  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402
import verify_studio_loop as vsl  # noqa: E402

SECOND_PROJECT_ID = "arc-other-project"
FAKE_JPEG = vsl.FAKE_JPEG


class StubConfig:
    """Explicitly-labelled local channel stub. No key, no network."""
    configured = True
    model = "local-model-stub"
    base_url = "local://stub"
    run_token_limit = 600_000
    project_token_limit = 2_000_000

    @classmethod
    def from_env(cls):
        return cls()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def build_main_service():
    store = SQLiteStore(MAIN_DB)
    files = FileService(MAIN_DB, RUNTIME)
    requirements = RequirementService(MAIN_DB)
    service = ApiService(MVPApp(store), files, requirement_service=requirements,
                         runtime_root=RUNTIME)
    files.seed_ningbo(service, ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09")
    # a second, unmapped project to prove the studio does not leak Ningbo data
    try:
        service.create_project("org-local", "另一个项目（未接入 Studio）", SECOND_PROJECT_ID)
    except Exception as exc:
        print("second project note:", type(exc).__name__, str(exc)[:120])
    return service, store


def seed_studio() -> None:
    st = Store(STUDIO_DB)
    # Use the fixture-driven seed so the explicit main-system id mapping is
    # identical to production (source_project_id = project_ningbo_xiecheng_2026).
    orchestrator.Studio(st).seed_from_fixtures()
    # One historical, unvalidated row: must be shown as history, never deleted.
    st.save_artifact("ningbo-xiecheng", "spatial-plan",
                     {"legacy": True, "note": "历史未校验产物，字节保留"}, "D2",
                     option_id="A", revision=0, status="draft")
    # Run one loop with the local stub to produce real valid candidates + gate
    orchestrator.Client = vsl.FakeClient
    vision.svg_to_jpeg = lambda svg, limit=720: FAKE_JPEG
    vision.reference_jpeg = lambda limit=720: FAKE_JPEG
    orchestrator.Studio(st).run_a1("ningbo-xiecheng", background=False)


def main() -> int:
    started = time.monotonic()
    # channel stub must be in place before the Studio HTTP service starts
    studio_llm.Config = StubConfig  # type: ignore[assignment]
    studio_server.Config = StubConfig  # type: ignore[assignment]
    seed_studio()

    service, store = build_main_service()
    main_port = _free_port()
    main_server = create_server(service, LocalIdentityProvider(), port=main_port,
                                static_dir=ROOT / "web" / "dist")
    main_thread = threading.Thread(target=main_server.serve_forever,
                                   name="arc-main", daemon=True)
    main_thread.start()

    # StudioView's API base is the local experimental service's fixed port 8099
    # (verified free). CORS in server.py is limited to a fixed origin set, so
    # add this isolated test origin only.
    studio_port = 8099
    studio_server.ALLOWED_ORIGINS = set(studio_server.ALLOWED_ORIGINS) | {
        f"http://127.0.0.1:{main_port}", f"http://localhost:{main_port}"}
    from http.server import ThreadingHTTPServer
    st_httpd = ThreadingHTTPServer(("127.0.0.1", studio_port), studio_server.Handler)
    st_thread = threading.Thread(target=st_httpd.serve_forever, name="arc-studio", daemon=True)
    st_thread.start()

    # The frontend hardcodes the studio API port; run an isolated frontend
    # instance with the studio URL replaced at serve time (no source edit).
    index = (ROOT / "web" / "dist" / "index.html").read_text(encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k not in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                        "ALL_PROXY", "all_proxy")}
    env.update({
        "RKD_QA_URL": f"http://127.0.0.1:{main_port}",
        "RKD_QA_STUDIO_URL": f"http://127.0.0.1:{studio_port}",
        "RKD_QA_STUDIO_PORT": str(studio_port),
        "RKD_QA_EVIDENCE_DIR": str(EVIDENCE),
        "RKD_QA_PROJECT_ID": NINGBO_PROJECT_ID,
        "RKD_QA_OTHER_PROJECT_ID": SECOND_PROJECT_ID,
    })
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node not found")
    try:
        proc = subprocess.run([node, str(ROOT / "scripts" / "verify_arc_browser.cjs")],
                              cwd=str(ROOT), env=env, capture_output=True, text=True,
                              errors="replace", timeout=300)
        (EVIDENCE / "browser-stdout.log").write_text(proc.stdout or "", encoding="utf-8")
        (EVIDENCE / "browser-stderr.log").write_text(proc.stderr or "", encoding="utf-8")
        passed = proc.returncode == 0
        # restart persistence check: a NEW Store on the same db sees everything
        st2 = Store(STUDIO_DB)
        state2 = st2.project_state("ningbo-xiecheng")
        restart = {
            "feedback_revision": state2["feedback_revision"],
            "artifacts": len(state2["artifacts"]),
            "gates": len(state2["gates"]),
            "decided_gates": sum(1 for g in state2["gates"] if g["status"] == "decided"),
            "check_reports": len(state2["check_reports"]),
            "valid_candidates": sum(1 for a in state2["artifacts"]
                                    if a["contract_status"] == "valid_candidate"),
            "legacy_artifact_preserved": any(
                a["payload"].get("legacy") for a in state2["artifacts"]
                if isinstance(a["payload"], dict)),
        }
        result = {
            "schema_version": "rkd-arc-browser-verification.v1",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "main_url": env["RKD_QA_URL"], "studio_url": env["RKD_QA_STUDIO_URL"],
            "passed": passed, "node_returncode": proc.returncode,
            "duration_seconds": round(time.monotonic() - started, 2),
            "restart_persistence": restart,
            "external_calls": 0, "keys_used": False,
            "model_channel": "local-model-stub (explicitly labelled)",
            "image_counts": {
                "images_sent_external": 0,
                "images_generated_local": 0,
                "stub_placeholder_images_in_loop": "A1 看图自评步骤向本地模型桩传入 3 张占位字节；未调用任何外部图像/模型通道",
                "note": "runs.images_sent 是本轮传给本地桩的占位张数，不等于外发图片数"
            },
            "boundaries": [
                "isolated SQLite main workbench + isolated Studio DB; daily studio.db untouched",
                "no external model/image calls; no key; cost 0",
                "browser evidence supports engineering control, NOT design or professional sign-off",
                "AD01—AD08 unchanged; user design-stage confirmation has NOT happened",
            ],
            "evidence_files": sorted(p.name for p in EVIDENCE.iterdir() if p.is_file()),
        }
        (EVIDENCE / "verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        if not passed:
            print((proc.stderr or proc.stdout or "")[-3500:], flush=True)
        return 0 if passed else 1
    finally:
        main_server.shutdown(); main_server.server_close()
        st_httpd.shutdown(); st_httpd.server_close()
        main_thread.join(5); st_thread.join(5)
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
