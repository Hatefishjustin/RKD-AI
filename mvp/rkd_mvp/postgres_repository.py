from __future__ import annotations

"""PostgreSQL repository for the shared command/event kernel.

The domain services still use SQLite in the local release.  This adapter is
the first production repository slice: it keeps command idempotency,
optimistic aggregate versions, domain events, and Outbox writes in one RLS
scoped transaction so individual domains can be ported without inventing a
second consistency model.
"""

import hashlib
import json
from typing import Any

from .models import CommandEnvelope, TenantContext, new_id
from .postgres_store import PostgresStore


def _row_value(row: Any, key: str, index: int) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


class PostgresRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def ensure_project(self, context: TenantContext, name: str) -> dict[str, Any]:
        def write(connection: Any) -> dict[str, Any]:
            connection.execute(
                """
                INSERT INTO rkd.organization(organization_id, name)
                VALUES (%s, %s)
                ON CONFLICT (organization_id) DO NOTHING
                """,
                (context.organization_id, context.organization_id),
            )
            result = connection.execute(
                """
                INSERT INTO rkd.project(organization_id, project_id, name)
                VALUES (%s, %s, %s)
                ON CONFLICT (organization_id, project_id)
                DO UPDATE SET name = EXCLUDED.name
                RETURNING organization_id, project_id, name, status
                """,
                (context.organization_id, context.project_id, name),
            )
            row = result.fetchone()
            return {
                "organization_id": _row_value(row, "organization_id", 0),
                "project_id": _row_value(row, "project_id", 1),
                "name": _row_value(row, "name", 2),
                "status": _row_value(row, "status", 3),
            }

        return self.store.run_in_transaction(context, write)

    def get_project(self, context: TenantContext) -> dict[str, Any] | None:
        def read(connection: Any) -> dict[str, Any] | None:
            result = connection.execute(
                """
                SELECT organization_id, project_id, name, status, created_at
                FROM rkd.project
                WHERE organization_id = %s AND project_id = %s
                """,
                (context.organization_id, context.project_id),
            )
            row = result.fetchone()
            if row is None:
                return None
            return {
                "organization_id": _row_value(row, "organization_id", 0),
                "project_id": _row_value(row, "project_id", 1),
                "name": _row_value(row, "name", 2),
                "status": _row_value(row, "status", 3),
                "created_at": _row_value(row, "created_at", 4),
            }

        return self.store.run_in_transaction(context, read)

    def append_command_event(
        self,
        command: CommandEnvelope,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically record a command, aggregate state, event and Outbox row."""
        context = command.context
        payload_copy = dict(payload)
        payload_json = json.dumps(payload_copy, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

        def write(connection: Any) -> dict[str, Any]:
            existing = connection.execute(
                """
                SELECT result FROM rkd.command_record
                WHERE organization_id = %s AND project_id = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (context.organization_id, context.project_id, command.idempotency_key),
            ).fetchone()
            if existing is not None:
                result = _row_value(existing, "result", 0)
                return result if isinstance(result, dict) else json.loads(result)

            aggregate = connection.execute(
                """
                SELECT version, state FROM rkd.aggregate_state
                WHERE organization_id = %s AND project_id = %s
                  AND aggregate_type = %s AND aggregate_id = %s
                FOR UPDATE
                """,
                (context.organization_id, context.project_id, command.command_name, command.aggregate_id),
            ).fetchone()
            previous_version = int(_row_value(aggregate, "version", 0) or 0)
            version = previous_version + 1
            event_id = new_id("evt")
            command_result = {
                "event_id": event_id,
                "aggregate_id": command.aggregate_id,
                "aggregate_version": version,
                "status": "accepted",
            }
            connection.execute(
                """
                INSERT INTO rkd.command_record
                    (command_id, organization_id, project_id, command_name, aggregate_id,
                     idempotency_key, actor_id, actor_type, status, result)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'accepted', %s::jsonb)
                """,
                (
                    command.command_id, context.organization_id, context.project_id,
                    command.command_name, command.aggregate_id, command.idempotency_key,
                    context.actor_id, context.actor_type, json.dumps(command_result, ensure_ascii=True),
                ),
            )
            state = {"version": version, "last_event_id": event_id, "payload": payload_copy}
            if aggregate is None:
                connection.execute(
                    """
                    INSERT INTO rkd.aggregate_state
                        (organization_id, project_id, aggregate_type, aggregate_id, version, state)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        context.organization_id, context.project_id, command.command_name,
                        command.aggregate_id, version, json.dumps(state, ensure_ascii=True),
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE rkd.aggregate_state
                    SET version = %s, state = %s::jsonb, updated_at = now()
                    WHERE organization_id = %s AND project_id = %s
                      AND aggregate_type = %s AND aggregate_id = %s
                    """,
                    (
                        version, json.dumps(state, ensure_ascii=True), context.organization_id,
                        context.project_id, command.command_name, command.aggregate_id,
                    ),
                )
            connection.execute(
                """
                INSERT INTO rkd.domain_event
                    (event_id, organization_id, project_id, event_type, event_schema_version,
                     aggregate_type, aggregate_id, aggregate_version, correlation_id,
                     causation_id, idempotency_key, payload_hash, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    event_id, context.organization_id, context.project_id, event_type,
                    command.schema_version, command.command_name, command.aggregate_id, version,
                    command.correlation_id or command.command_id, command.causation_id or command.command_id,
                    command.idempotency_key, payload_hash, payload_json,
                ),
            )
            connection.execute(
                """
                INSERT INTO rkd.outbox_message
                    (message_id, organization_id, project_id, message_type, aggregate_id,
                     dedupe_key, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    event_id, context.organization_id, context.project_id, event_type,
                    command.aggregate_id, command.idempotency_key, payload_json,
                ),
            )
            return command_result

        return self.store.run_in_transaction(context, write)
