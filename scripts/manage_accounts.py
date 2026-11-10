"""One-time trusted local administrator setup; no passwords in CLI arguments."""
from pathlib import Path
import getpass
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.api_service import ApiError
from rkd_mvp.sqlite_store import SQLiteStore


def main():
    if "--postgres" in sys.argv:
        from psycopg.conninfo import conninfo_to_dict
        from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory
        from rkd_mvp.account_repository import PostgresAccountRepository
        dsn = os.environ.get("RKD_POSTGRES_DSN", "")
        if not dsn or conninfo_to_dict(dsn).get("host") not in {"127.0.0.1", "localhost"}:
            raise SystemExit("请显式设置回环 PostgreSQL 的 RKD_POSTGRES_DSN。")
        provider = AccountIdentityProvider(None, repository=PostgresAccountRepository(PostgresStore(postgres_connection_factory(dsn))))
    else:
        path = Path(os.environ.get("RKD_MVP_DB_PATH", str(ROOT / "var" / "app.sqlite3")))
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        store = SQLiteStore(path)
        store.close()
        provider = AccountIdentityProvider(path)
    if provider.has_users():
        print("账号模式已初始化，使用现有账号登录。")
        return
    print("创建首位本地管理员。启用后，此数据库不再接受开发身份访问。")
    username = input("登录账号（字母、数字或 ._-，3–64 位）: ").strip()
    display_name = input("显示姓名: ").strip()
    password = getpass.getpass("密码（8–128 字符，可使用长句）: ")
    if password != getpass.getpass("再次输入密码: "):
        raise SystemExit("两次密码不一致，未创建账号。")
    try:
        provider.bootstrap(username, display_name, password)
    except ApiError as error:
        raise SystemExit(error.message) from None
    print("管理员已创建。登录后可在账号与成员管理中增加成员。")


if __name__ == "__main__":
    main()
