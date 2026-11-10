"""Account-only production transport, bound to loopback behind TLS or SSH."""
import os
from pathlib import Path

from rkd_mvp.account_identity import AccountIdentityProvider
from rkd_mvp.account_repository import PostgresAccountRepository
from rkd_mvp.asgi_app import create_app
from rkd_mvp.postgres_api_service import PostgresApiService
from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory


def application():
    dsn = os.environ["RKD_POSTGRES_DSN"]
    runtime = Path(os.environ["RKD_POSTGRES_RUNTIME"]).resolve()
    from psycopg.conninfo import conninfo_to_dict
    if conninfo_to_dict(dsn).get("host") not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("team database must use the isolated loopback listener")
    root = Path(__file__).resolve().parents[1]
    store = PostgresStore(postgres_connection_factory(dsn))
    accounts = AccountIdentityProvider(None, repository=PostgresAccountRepository(store))
    service = PostgresApiService(store, runtime)
    service.task_service.fixture_root = root / "fixtures/ningbo-xiecheng/2026-09"
    service.health()
    # Empty accounts expose only login/config/health/static; creating the first
    # administrator is exclusively a trusted interactive terminal operation.
    return create_app(service, accounts, root / "web/dist", os.environ["RKD_PUBLIC_ORIGIN"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(application(), host="127.0.0.1", port=int(os.environ.get("RKD_TEAM_PORT", "18080")),
                proxy_headers=False, server_header=False, access_log=False,
                limit_concurrency=32, timeout_keep_alive=5, timeout_graceful_shutdown=30)
