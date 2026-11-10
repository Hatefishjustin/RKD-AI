"""Explicit loopback business pilot; never changes the daily SQLite entry."""
import os
from pathlib import Path

from rkd_mvp.api_server import create_server
from rkd_mvp.account_identity import AccountIdentityProvider, AccountGuardedLocalIdentityProvider
from rkd_mvp.account_repository import PostgresAccountRepository
from rkd_mvp.postgres_api_service import PostgresApiService
from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory


def main():
    from psycopg.conninfo import conninfo_to_dict

    dsn = os.environ.get("RKD_POSTGRES_DSN")
    runtime = os.environ.get("RKD_POSTGRES_RUNTIME")
    if not dsn or not runtime:
        raise SystemExit("Set RKD_POSTGRES_DSN and RKD_POSTGRES_RUNTIME explicitly; no SQLite fallback")
    if conninfo_to_dict(dsn).get("host") not in {"127.0.0.1", "localhost"}:
        raise SystemExit("PostgreSQL pilot requires an explicit loopback database host")
    root = Path(runtime).resolve()
    daily = Path(__file__).resolve().parents[1] / "var"
    if root == daily.resolve():
        raise SystemExit("Use a separate PostgreSQL pilot runtime, not the daily SQLite runtime")
    factory = postgres_connection_factory(dsn)
    store = PostgresStore(factory)
    accounts = AccountIdentityProvider(None, repository=PostgresAccountRepository(store))
    initialized = accounts.has_users()
    mode = os.environ.get("RKD_AUTH_MODE", "accounts" if initialized else "local")
    if mode not in {"local", "accounts"}:
        raise SystemExit("RKD_AUTH_MODE must be local or accounts")
    if mode == "local" and initialized:
        raise SystemExit("Accounts enabled; refusing local identity downgrade")
    if mode == "accounts" and not initialized:
        raise SystemExit("Initialize PostgreSQL administrator using scripts/rkd.ps1 postgres-accounts")
    root.mkdir(parents=True, exist_ok=True)
    service = PostgresApiService(store, root)
    service.task_service.fixture_root = Path(__file__).resolve().parents[1] / "fixtures/ningbo-xiecheng/2026-09"
    service.health()
    server = create_server(service, accounts if mode == "accounts" else AccountGuardedLocalIdentityProvider(accounts),
                           port=int(os.environ.get("RKD_POSTGRES_PORT", "8092")),
                           static_dir=Path(__file__).resolve().parents[1] / "web/dist")
    print(f"RKD PostgreSQL business pilot http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Identity mode: {mode}; loopback only; no daily cutover or formal release", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
