from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.postgres_migrations import (
    MigrationError,
    PostgresMigrationRunner,
    _without_outer_transaction,
    discover_migrations,
)


POSTGRES_ROOT = Path(__file__).parents[1] / "persistence" / "postgres"


class Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchall(self):
        return self._rows


class FakeMigrationConnection:
    def __init__(self, applied=()):
        self.applied = set(applied)
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if sql.startswith("SELECT version FROM rkd.schema_migration"):
            return Result((version,) for version in sorted(self.applied))
        if sql.startswith("INSERT INTO rkd.schema_migration"):
            self.applied.add(int(params[0]))
        return Result()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class FailingMigrationConnection(FakeMigrationConnection):
    def execute(self, sql, params=()):
        if "CREATE TABLE IF NOT EXISTS rkd.file_asset" in sql:
            raise RuntimeError("migration failed")
        return super().execute(sql, params)


class PostgresMigrationTests(unittest.TestCase):
    def test_migrations_are_contiguous_and_include_runtime_domains(self):
        migrations = discover_migrations(POSTGRES_ROOT)
        self.assertEqual([migration.version for migration in migrations], [1, 2])
        self.assertEqual(migrations[1].name, "runtime_domains")

    def test_legacy_outer_transaction_is_removed_for_runner(self):
        source = (POSTGRES_ROOT / "001_vertical_mvp.sql").read_text(encoding="utf-8")
        normalized = _without_outer_transaction(source)
        self.assertFalse(normalized.upper().startswith("BEGIN;"))
        self.assertFalse(normalized.upper().endswith("COMMIT;"))

    def test_runner_records_each_version_and_closes_connection(self):
        connection = FakeMigrationConnection()
        applied = PostgresMigrationRunner(lambda: connection, POSTGRES_ROOT).apply()
        self.assertEqual(applied, (1, 2))
        self.assertEqual(connection.applied, {1, 2})
        self.assertGreaterEqual(connection.commits, 3)  # schema table + one commit per migration
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.closed)
        self.assertIn("CREATE SCHEMA IF NOT EXISTS rkd", connection.calls[0][0])
        self.assertIn("CREATE TABLE IF NOT EXISTS rkd.file_asset", connection.calls[-2][0])

    def test_runtime_schema_covers_all_local_domains_and_rls(self):
        sql = (POSTGRES_ROOT / "002_runtime_domains.sql").read_text(encoding="utf-8")
        for table in (
            "file_upload", "file_asset", "job", "estimate", "estimate_line",
            "spatial_unit", "geometry_revision", "requirement", "design_revision",
            "procurement_order", "material_receipt", "material_allocation",
            "change_request", "change_acceptance", "auth_user", "auth_membership",
            "auth_session", "auth_audit",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS rkd.{table}", sql)
        self.assertIn("ALTER TABLE rkd.auth_login_limit ENABLE ROW LEVEL SECURITY", sql)
        self.assertIn("CREATE POLICY auth_session_tenant_isolation", sql)
        self.assertIn("auth_audit is append-only", sql)
        self.assertIn("external_effects_enabled boolean NOT NULL DEFAULT false", sql)

    def test_failed_migration_rolls_back_and_closes_connection(self):
        connection = FailingMigrationConnection()
        with self.assertRaises(RuntimeError):
            PostgresMigrationRunner(lambda: connection, POSTGRES_ROOT).apply()
        self.assertGreaterEqual(connection.rollbacks, 1)
        self.assertTrue(connection.closed)

    def test_invalid_migration_gap_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
            (root / "003_gap.sql").write_text("SELECT 1;", encoding="utf-8")
            with self.assertRaises(MigrationError):
                discover_migrations(root)


if __name__ == "__main__":
    unittest.main()
