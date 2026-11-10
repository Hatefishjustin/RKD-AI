from __future__ import annotations

from contextlib import contextmanager
import json
from typing import Any, Callable, Iterator, Protocol

from .models import TenantContext


class DbConnection(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[], DbConnection]


def postgres_connection_factory(dsn: str, *, application_role: bool = True) -> ConnectionFactory:
    """No implicit SQLite fallback. Driver and connection errors fail explicitly."""
    import psycopg

    def connect() -> DbConnection:
        connection = psycopg.connect(dsn, autocommit=True, connect_timeout=10)
        try:
            if application_role:
                role = connection.execute(
                    "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname=current_user"
                ).fetchone()
                owned = connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='rkd' AND pg_has_role(current_user,c.relowner,'USAGE'))"
                ).fetchone()[0]
                if not role or any(role) or owned:
                    raise PermissionError("PostgreSQL application role must not own tables, bypass RLS, or administer roles/databases")
            return connection
        except BaseException:
            connection.close()
            raise

    return connect


class PostgresStore:
    """DB-API boundary for the production store; requires a PostgreSQL driver at deployment time."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self.connection_factory = connection_factory

    @contextmanager
    def tenant_transaction(self, context: TenantContext) -> Iterator[DbConnection]:
        if not all(isinstance(value, str) and value.strip() for value in (
            context.organization_id, context.project_id, context.actor_id,
        )):
            raise ValueError("organization, project and actor context are required")
        connection = self.connection_factory()
        try:
            connection.execute("BEGIN")
            connection.execute(
                "SELECT set_config('rkd.organization_id', %s, true)",
                (context.organization_id,),
            )
            connection.execute(
                "SELECT set_config('rkd.project_id', %s, true)",
                (context.project_id,),
            )
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def run_in_transaction(self, context: TenantContext,
                           operation: Callable[[DbConnection], Any]) -> Any:
        with self.tenant_transaction(context) as connection:
            return operation(connection)

    def claim_outbox(self, context: TenantContext, worker_id: str,
                     limit: int = 50, lease_seconds: int = 60) -> Any:
        def claim(connection: DbConnection) -> Any:
            return connection.execute(
                """
                WITH claimable AS (
                    SELECT message_id
                    FROM rkd.outbox_message
                    WHERE organization_id = %s
                      AND project_id = %s
                      AND published_at IS NULL
                      AND available_at <= now()
                      AND (lease_until IS NULL OR lease_until < now())
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE rkd.outbox_message AS message
                   SET lease_owner = %s,
                       lease_until = now() + (%s * interval '1 second'),
                       attempts = attempts + 1
                  FROM claimable
                 WHERE message.message_id = claimable.message_id
                RETURNING message.message_id, message.message_type, message.payload,
                          message.attempts, message.lease_until
                """,
                (context.organization_id, context.project_id, limit, worker_id, lease_seconds),
            ).fetchall()

        return self.run_in_transaction(context, claim)

    def acknowledge_outbox(self, context: TenantContext, message_id: str, worker_id: str) -> Any:
        return self.run_in_transaction(
            context,
            lambda connection: connection.execute(
                """
                UPDATE rkd.outbox_message
                   SET published_at = now(), lease_owner = NULL, lease_until = NULL
                 WHERE message_id = %s
                   AND organization_id = %s
                   AND project_id = %s
                   AND lease_owner = %s AND lease_until > now() AND published_at IS NULL
                RETURNING message_id
                """,
                (message_id, context.organization_id, context.project_id, worker_id),
            ).fetchone(),
        )

    def record_inbox_once(self, context: TenantContext, message_id: str,
                          consumer_name: str, result: dict[str, Any]) -> Any:
        return self.run_in_transaction(
            context,
            lambda connection: connection.execute(
                """
                INSERT INTO rkd.inbox_message
                    (organization_id, project_id, message_id, consumer_name, result)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (organization_id, project_id, message_id, consumer_name)
                DO NOTHING
                RETURNING message_id
                """,
                (context.organization_id, context.project_id, message_id, consumer_name, json.dumps(result, ensure_ascii=True)),
            ).fetchone(),
        )
