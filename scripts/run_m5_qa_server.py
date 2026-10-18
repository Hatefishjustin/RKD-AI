"""Isolated test server for the M5 entry audit. Never opens the user's database."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.file_service import FileService
from rkd_mvp.identity import LocalIdentityProvider
from rkd_mvp.sqlite_store import SQLiteStore

parser = argparse.ArgumentParser()
parser.add_argument("--runtime", required=True)
parser.add_argument("--mode", choices=["local", "accounts"], required=True)
parser.add_argument("--port", type=int, default=0)
args = parser.parse_args()
runtime = Path(args.runtime).resolve()
if not runtime.is_relative_to((ROOT / "var" / "evidence" / "m5-entry").resolve()):
    raise SystemExit("QA runtime must remain under var/evidence/m5-entry")
runtime.mkdir(parents=True, exist_ok=True)
db_path = runtime / "app.sqlite3"
store = SQLiteStore(db_path)
files = FileService(db_path, runtime)
service = ApiService(MVPApp(store), file_service=files)
fixture = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
files.seed_ningbo(service, fixture)
service.task_service.ensure_ningbo_seed("org-local", "project_ningbo_xiecheng_2026", fixture)
service.estimate_service.seed_ningbo("org-local", "project_ningbo_xiecheng_2026", fixture)
if ("org-local", "audit-floor") not in store.projects:
    service.create_project("org-local", "M5 入口复核测试地坪", "audit-floor")
    service.create_spatial_revision("org-local", "audit-floor", {"width": "10", "length": "5", "deductions": [{"deduction_id": "void", "x": "0", "y": "0", "width": "2", "length": "2"}], "pricing": {"unit_cost_net": "100", "cost_markup": "0.20", "trial_tax_rate": "0.05"}}, "qa-test")
    # Real stored issue, explicitly a test observation, for issue→change linkage.
    from rkd_mvp.models import now_iso
    with store._connection() as db:
        db.execute("INSERT INTO issues VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 'open', NULL, NULL, 1, ?, ?)",
                   ("audit-material-issue", "org-local", "audit-floor", "qa://material-observation", "test-case-MC", "test_material_unavailable", "medium", "测试：材料不可供", json.dumps({"source_kind": "test_observation"}), now_iso(), now_iso()))
if args.mode == "accounts":
    provider = AccountIdentityProvider(db_path)
    if not provider.has_users():
        provider.bootstrap("qa-admin", "M5 测试管理员", os.environ["RKD_QA_PASSWORD"])
else:
    provider = LocalIdentityProvider()
server = create_server(service, provider, port=args.port, static_dir=ROOT / "web" / "dist")
print(json.dumps({"url": f"http://127.0.0.1:{server.server_address[1]}", "pid": os.getpid(), "mode": args.mode}), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    store.close()
