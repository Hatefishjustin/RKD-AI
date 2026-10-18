from __future__ import annotations

"""Small DB-API migration runner for the PostgreSQL deployment boundary.

The application deliberately does not import a PostgreSQL driver here.  The
driver is supplied by the deployment, while tests can use any DB-API-shaped
connection to verify ordering and rollback behavior.
"""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable, Iterable


ConnectionFactory = Callable[[], Any]
_MIGRATION_NAME = re.compile(r"^(?P<version>\d+)_(?P<name>[a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path


class MigrationError(RuntimeError):
    pass


def discover_migrations(directory: str | Path) -> tuple[Migration, ...]:
    root = Path(directory)
    migrations: list[Migration] = []
    for path in root.glob("*.sql"):
        match = _MIGRATION_NAME.match(path.name)
        if not match:
            raise MigrationError(f"invalid migration filename: {path.name}")
        migrations.append(Migration(int(match.group("version")), match.group("name"), path))
    migrations.sort(key=lambda item: item.version)
    versions = [item.version for item in migrations]
    if len(versions) != len(set(versions)):
        raise MigrationError("duplicate PostgreSQL migration version")
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"PostgreSQL migrations must be contiguous from 1, found {versions}")
    return tuple(migrations)


def _without_outer_transaction(sql: str) -> str:
    """Allow the legacy 001 file to be run inside the runner's transaction."""
    text = sql.strip()
    if text.upper().startswith("BEGIN;"):
        text = text[6:].lstrip()
    if text.upper().endswith("COMMIT;"):
        text = text[:-7].rstrip()
    return text


def _rows(result: Any) -> Iterable[Any]:
    if result is None:
        return ()
    fetchall = getattr(result, "fetchall", None)
    if callable(fetchall):
        return fetchall()
    if isinstance(result, (list, tuple)):
        return result
    return ()


class PostgresMigrationRunner:
    """Apply ordered migrations with one committed transaction per version."""

    def __init__(self, connection_factory: ConnectionFactory, directory: str | Path | None = None) -> None:
        self.connection_factory = connection_factory
        self.directory = Path(directory) if directory else Path(__file__).resolve().parents[1] / "persistence" / "postgres"

    def apply(self) -> tuple[int, ...]:
        migrations = discover_migrations(self.directory)
        connection = self.connection_factory()
        applied: set[int] = set()
        try:
            connection.execute("CREATE SCHEMA IF NOT EXISTS rkd")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rkd.schema_migration ("
                "version integer PRIMARY KEY, name text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            connection.commit()
            result = connection.execute("SELECT version FROM rkd.schema_migration ORDER BY version")
            applied = {int(row[0]) for row in _rows(result)}

            for migration in migrations:
                if migration.version in applied:
                    continue
                connection.execute("BEGIN")
                try:
                    connection.execute(_without_outer_transaction(migration.path.read_text(encoding="utf-8")))
                    connection.execute(
                        "INSERT INTO rkd.schema_migration(version, name) VALUES (%s, %s)",
                        (migration.version, migration.name),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                applied.add(migration.version)
            return tuple(sorted(applied))
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

