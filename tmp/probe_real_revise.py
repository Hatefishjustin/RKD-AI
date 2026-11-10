"""Probe only the real-model feedback revision against a previous isolated run."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))

from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402

key = os.environ["RKD_TEST_KEY"]
os.environ.update({
    "RKD_AI_PROVIDER": "openai-compatible", "RKD_AI_DESIGN_PROVIDER": "openai-compatible",
    "RKD_AI_BASE_URL": "https://api.codelink.chat/v1", "RKD_AI_MODEL": "gpt-5.6-sol",
    "RKD_AI_API_KEY": key, "RKD_AI_EXTERNAL_CONTEXT": "false",
    "RKD_AI_TIMEOUT_SECONDS": "180", "RKD_AI_DESIGN_MAX_ATTEMPTS": "3",
    "RKD_AI_DESIGN_MAX_OUTPUT_TOKENS": "6000",
    "RKD_AI_RUN_LOG_DIR": str(ROOT / "var" / "ai-model-runs" / "revise-probe"),
})
run = ROOT / "var/evidence/real-design/2026-11-09/run-20261109T144154-c6b31c/runtime"
store = SQLiteStore(run / "app.sqlite3")
files = FileService(run / "app.sqlite3", run)
service = ApiService(MVPApp(store), files, runtime_root=run)
state = service.get_ai_design_options("org-local", NINGBO_PROJECT_ID)
options = state["item"]["options"]
print("options", [(item["strategy"]["strategy_id"], item["revision_no"]) for item in options])
target = options[0]
result = service.revise_ai_design_option(
    "org-local", NINGBO_PROJECT_ID, "revise-probe",
    {"option_id": target["option_id"], "expected_revision": 1,
     "feedback": "更开放一些，但保留入口和主展台", "locks": ["entrance", "display"]})
item = result["item"]
print(json.dumps({
    "revision_no": item["revision_no"], "source_kind": item["source_kind"],
    "validation": item["validation"]["status"],
    "interpretation": item["model"]["feedback"]["interpretation_method"],
    "parsed_intents": item["model"]["feedback"]["parsed_intents"],
    "diff_count": len(result["diff"]),
    "diff": result["diff"][:6],
    "conflicts": result["conflicts"],
    "real_model": item["model"]["generation"]["real_model"],
    "strategy": item["model"]["strategy"]["statement"][:220],
}, ensure_ascii=False, indent=2))
store.close()
