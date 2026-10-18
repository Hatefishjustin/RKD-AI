from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).parent))

from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.estimate_service import EstimateService
from rkd_mvp.file_service import FileService
from rkd_mvp.sqlite_store import SQLiteStore
from rkd_mvp.task_service import TaskService
from rkd_mvp.requirement_service import RequirementService
from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.identity import LocalIdentityProvider


project_root = Path(__file__).resolve().parents[1]
db_path = Path(os.environ.get("RKD_MVP_DB_PATH", str(project_root / "var" / "app.sqlite3")))
if not db_path.is_absolute():
    db_path = project_root / db_path
db_path.parent.mkdir(parents=True, exist_ok=True)
store = SQLiteStore(db_path)
file_service = FileService(db_path, db_path.parent)
task_service = TaskService(db_path)
estimate_service = EstimateService(db_path)
requirement_service = RequirementService(db_path)
service = ApiService(MVPApp(store), file_service=file_service, task_service=task_service, estimate_service=estimate_service, requirement_service=requirement_service)
fixture_root = project_root / "fixtures" / "ningbo-xiecheng" / "2026-09"
file_service.seed_ningbo(service, fixture_root)
task_service.ensure_ningbo_seed("org-local", "project_ningbo_xiecheng_2026", fixture_root)
estimate_service.seed_ningbo("org-local", "project_ningbo_xiecheng_2026", fixture_root)
static_dir = project_root / "web" / "dist"
port = int(os.environ.get("RKD_MVP_PORT", "8080"))
accounts = AccountIdentityProvider(db_path)
mode = os.environ.get("RKD_AUTH_MODE", "accounts" if accounts.has_users() else "local")
if mode not in {"local", "accounts"}:
    raise SystemExit("RKD_AUTH_MODE must be local or accounts")
if mode == "local" and accounts.has_users():
    raise SystemExit("账号已启用，拒绝退回开发身份模式。请使用 accounts 模式。")
if mode == "accounts" and not accounts.has_users():
    raise SystemExit("请先运行 scripts/rkd.ps1 start-secure 初始化管理员。")
server = create_server(service, identity_provider=accounts if mode == "accounts" else LocalIdentityProvider(), port=port, static_dir=static_dir)
print(f"RKD local API listening on http://127.0.0.1:{port}")
print(f"Identity mode: {mode}; loopback only; external publication disabled")
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
    store.close()
