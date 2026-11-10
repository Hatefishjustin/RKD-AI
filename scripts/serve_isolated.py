"""Small real HTTP harness limited to var/evidence; never opens the daily DB."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database", required=True)
parser.add_argument("--application", default=str(ROOT))
args = parser.parse_args()
database, application = Path(args.database).resolve(), Path(args.application).resolve()
if not database.is_relative_to((ROOT / "var/evidence").resolve()) or not database.is_file():
    raise SystemExit("isolated existing database under var/evidence required")
sys.path.insert(0, str(application / "mvp"))
from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.file_service import FileService
from rkd_mvp.identity import LocalIdentityProvider
from rkd_mvp.sqlite_store import SQLiteStore

store = SQLiteStore(database)
service = ApiService(MVPApp(store), file_service=FileService(database, database.parent))
accounts = AccountIdentityProvider(database)
provider = accounts if accounts.has_users() else LocalIdentityProvider()
server = create_server(service, provider, port=0, static_dir=application / "web/dist")
print(json.dumps({"port": server.server_address[1], "pid": os.getpid(), "identity": getattr(provider, "mode", "local")}), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    store.close()
