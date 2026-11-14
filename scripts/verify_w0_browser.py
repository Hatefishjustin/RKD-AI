"""W0 real-browser acceptance: pick an OLD plan in the page, give feedback,
run a loop, and verify the new revision's parent points at that old version.

Isolated main workbench + isolated Studio DB + explicitly-labelled local model
stub. 0 external calls, 0 keys, 0 cost. Daily var/studio/studio.db untouched.
"""
from __future__ import annotations

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
EVIDENCE = ROOT / "var" / "evidence" / "roadmap" / "W0-收口" / "after" / "browser"
EVIDENCE.mkdir(parents=True, exist_ok=True)
RUNTIME = EVIDENCE / "runtime"
RUNTIME.mkdir(exist_ok=True)
STUDIO_DB = RUNTIME / "studio.db"
MAIN_DB = RUNTIME / "app.sqlite3"

os.environ["RKD_STUDIO_DB"] = str(STUDIO_DB)
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

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


class StubConfig:
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


def main() -> int:
    # clean isolation: never accumulate runs from a previous failed attempt
    for f in (STUDIO_DB, MAIN_DB):
        if f.exists():
            f.unlink()
    started = time.monotonic()
    studio_llm.Config = StubConfig
    studio_server.Config = StubConfig
    orchestrator.Client = vsl.FakeClient
    vision.svg_to_jpeg = lambda svg, limit=720: vsl.FAKE_JPEG
    vision.reference_jpeg = lambda limit=720: vsl.FAKE_JPEG

    # One GENERATE loop to produce real valid A/B candidates. No feedback yet:
    # the browser will select an old baseline itself.
    st = Store(STUDIO_DB)
    orchestrator.Studio(st).seed_from_fixtures()
    orchestrator.Studio(st).run_a1("ningbo-xiecheng", background=False)
    before = st.project_state("ningbo-xiecheng")
    a1 = next(a for a in before["artifacts"]
              if a["kind"] == "spatial-plan" and a["option_id"] == "A"
              and a["revision"] == 1 and a["contract_status"] == "valid_candidate")

    store = SQLiteStore(MAIN_DB)
    files = FileService(MAIN_DB, RUNTIME)
    requirements = RequirementService(MAIN_DB)
    service = ApiService(MVPApp(store), files, requirement_service=requirements,
                         runtime_root=RUNTIME)
    files.seed_ningbo(service, ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09")
    main_port = _free_port()
    main_server = create_server(service, LocalIdentityProvider(), port=main_port,
                                static_dir=ROOT / "web" / "dist")
    main_thread = threading.Thread(target=main_server.serve_forever, name="w0-main",
                                   daemon=True)
    main_thread.start()

    studio_port = 8099
    studio_server.ALLOWED_ORIGINS = set(studio_server.ALLOWED_ORIGINS) | {
        f"http://127.0.0.1:{main_port}", f"http://localhost:{main_port}"}
    from http.server import ThreadingHTTPServer
    st_httpd = ThreadingHTTPServer(("127.0.0.1", studio_port), studio_server.Handler)
    st_thread = threading.Thread(target=st_httpd.serve_forever, name="w0-studio",
                                 daemon=True)
    st_thread.start()

    env = {k: v for k, v in os.environ.items()
           if k not in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                        "ALL_PROXY", "all_proxy")}
    env.update({
        "RKD_QA_URL": f"http://127.0.0.1:{main_port}",
        "RKD_QA_STUDIO_URL": f"http://127.0.0.1:{studio_port}",
        "RKD_QA_EVIDENCE_DIR": str(EVIDENCE),
        "RKD_QA_PROJECT_ID": NINGBO_PROJECT_ID,
        "RKD_QA_BASELINE_ID": a1["id"],
        "RKD_QA_BASELINE_UID": a1["revision_uid"],
    })
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node not found")
    try:
        proc = subprocess.run([node, str(ROOT / "scripts" / "verify_w0_browser.cjs")],
                              cwd=str(ROOT), env=env, capture_output=True, text=True,
                              errors="replace", timeout=300)
        (EVIDENCE / "browser-stdout.log").write_text(proc.stdout or "", encoding="utf-8")
        (EVIDENCE / "browser-stderr.log").write_text(proc.stderr or "", encoding="utf-8")
        passed = proc.returncode == 0
        obs_path = EVIDENCE / "browser-observations.json"
        obs = json.loads(obs_path.read_text(encoding="utf-8")) if obs_path.exists() else {}

        # restart persistence: a NEW Store on the same db sees the revision chain
        st2 = Store(STUDIO_DB)
        state2 = st2.project_state("ningbo-xiecheng")
        plans2 = [a for a in state2["artifacts"] if a["kind"] == "spatial-plan"]
        revised = [a for a in plans2 if a["revision"] >= 2]
        restart = {
            "feedback_revision": state2["feedback_revision"],
            "feedback_baseline": [f.get("baseline_artifact_id") for f in state2["feedback"]],
            "runs": [{"status": r["status"], "task_kind": r.get("task_kind")}
                     for r in state2["runs"]],
            "revisions": [{"revision": a["revision"],
                           "parent_revision_uid": a["parent_revision_uid"]}
                          for a in revised],
            "old_baseline_bytes_preserved": any(
                a["id"] == a1["id"] and a["sha256"] == a1["sha256"]
                for a in state2["artifacts"]),
            "gates": len(state2["gates"]),
        }
        result = {
            "schema_version": "rkd-w0-browser-verification.v1",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "passed": bool(passed and
                           any(a["parent_revision_uid"] == a1["revision_uid"]
                               for a in revised)),
            "node_returncode": proc.returncode,
            "duration_seconds": round(time.monotonic() - started, 2),
            "selected_baseline": {"artifact_id": a1["id"],
                                  "revision_uid": a1["revision_uid"]},
            "browser_observations": obs,
            "restart_persistence": restart,
            "external_calls": 0, "keys_used": False,
            "model_channel": "local-model-stub (explicitly labelled)",
            "boundaries": [
                "isolated main workbench SQLite + isolated Studio DB; daily studio.db untouched",
                "no external model/image calls; no key; cost 0",
                "browser proves engineering control, NOT design or professional sign-off",
                "AD01—AD08 unchanged; user design-stage confirmation has NOT happened",
            ],
        }
        (EVIDENCE / "verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": result["passed"],
                          "node_returncode": proc.returncode,
                          "restart": restart}, ensure_ascii=False, indent=2), flush=True)
        if not result["passed"]:
            print((proc.stderr or proc.stdout or "")[-3000:], flush=True)
        return 0 if result["passed"] else 1
    finally:
        main_server.shutdown(); main_server.server_close()
        st_httpd.shutdown(); st_httpd.server_close()
        main_thread.join(5); st_thread.join(5)
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
