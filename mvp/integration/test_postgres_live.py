"""Real PostgreSQL checks, invoked explicitly by scripts/verify_postgres.py.

These are not optional/skipped cases in the SQLite suite: the runner must
actually provision PostgreSQL before loading this suite.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import unittest
from uuid import uuid4

import psycopg

from rkd_mvp.models import CommandEnvelope, TenantContext
from rkd_mvp.postgres_migrations import MigrationError, PostgresMigrationRunner
from rkd_mvp.postgres_repository import PostgresRepository
from rkd_mvp.postgres_store import PostgresStore, postgres_connection_factory
from rkd_mvp.store import ConflictError


OWNER_FACTORY = None
APP_FACTORY = None
OWNER_DSN = None
MIGRATIONS = Path(__file__).parents[1] / "persistence" / "postgres"


class PostgresLiveTests(unittest.TestCase):
    def setUp(self):
        self.context = TenantContext("org-" + uuid4().hex, "project-" + uuid4().hex, "test-actor")
        self.store = PostgresStore(APP_FACTORY)
        self.repository = PostgresRepository(self.store)
        self.repository.ensure_project(self.context, "M5 PostgreSQL verification")

    def command(self, **changes):
        return replace(CommandEnvelope("cmd-" + uuid4().hex, "test.create", self.context,
                                       "key-" + uuid4().hex, "aggregate-" + uuid4().hex, {"quantity": "46.00"}), **changes)

    def owner(self, sql, params=()):
        with OWNER_FACTORY() as db:
            cursor = db.execute(sql, params)
            return cursor.fetchall() if cursor.description else []

    def counts(self):
        return self.store.run_in_transaction(self.context, lambda db: tuple(
            db.execute(f"SELECT count(*) FROM rkd.{table}").fetchone()[0]
            for table in ("command_record", "aggregate_state", "domain_event", "outbox_message", "audit_event")))

    def test_01_real_migration_repeat_checksum_and_downgrade(self):
        self.assertEqual(PostgresMigrationRunner(OWNER_FACTORY).apply(), tuple(range(1, 15)))
        with tempfile.TemporaryDirectory() as folder:
            for file in MIGRATIONS.glob("*.sql"):
                shutil.copyfile(file, Path(folder) / file.name)
            first = Path(folder) / "001_vertical_mvp.sql"
            first.write_text(first.read_text() + "\n-- checksum change\n")
            with self.assertRaises(MigrationError):
                PostgresMigrationRunner(OWNER_FACTORY, folder).apply()
        with tempfile.TemporaryDirectory() as folder:
            shutil.copyfile(MIGRATIONS / "001_vertical_mvp.sql", Path(folder) / "001_vertical_mvp.sql")
            with self.assertRaises(MigrationError):
                PostgresMigrationRunner(OWNER_FACTORY, folder).apply()

    def test_02_real_migration_failure_rolls_back_ddl_and_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            for file in MIGRATIONS.glob("*.sql"):
                shutil.copyfile(file, Path(folder) / file.name)
            # Use the next free version, not an existing one; a duplicate
            # version would fail discovery instead of exercising DDL rollback.
            (Path(folder) / "015_failure.sql").write_text(
                "CREATE TABLE rkd.must_rollback(id integer); DO $$ BEGIN RAISE EXCEPTION 'injected'; END $$;"
            )
            with self.assertRaises(psycopg.Error):
                PostgresMigrationRunner(OWNER_FACTORY, folder).apply()
        self.assertIsNone(self.owner("SELECT to_regclass('rkd.must_rollback')")[0][0])
        self.assertEqual(self.owner("SELECT max(version) FROM rkd.schema_migration")[0][0], 14)

    def test_03_non_owner_role_and_no_context_default_deny(self):
        with self.assertRaises(PermissionError):
            postgres_connection_factory(OWNER_DSN)()
        with APP_FACTORY() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.project").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.job_attempt").fetchone()[0], 0)
            with self.assertRaises(psycopg.Error):
                db.execute("TRUNCATE rkd.project CASCADE")

    def test_04_same_organization_other_project_and_other_org_hidden(self):
        other = replace(self.context, project_id="other-" + uuid4().hex)
        foreign = replace(other, organization_id="foreign-" + uuid4().hex)
        self.repository.ensure_project(other, "Other")
        self.repository.ensure_project(foreign, "Foreign")
        for context in (self.context, other, foreign):
            rows = self.store.run_in_transaction(context, lambda db: db.execute("SELECT organization_id,project_id FROM rkd.project").fetchall())
            self.assertEqual(rows, [(context.organization_id, context.project_id)])
        self.assertEqual(self.repository.ensure_project(self.context, "must not rename")["name"], "M5 PostgreSQL verification")

    def test_05_children_are_protected_and_cross_project_parent_is_rejected(self):
        job = "job-" + uuid4().hex
        with self.store.tenant_transaction(self.context) as db:
            db.execute("INSERT INTO rkd.job(job_id,organization_id,project_id,job_type,status,input_hash,input_ref) VALUES (%s,%s,%s,'test','queued',%s,'test')",
                       (job, self.context.organization_id, self.context.project_id, job))
            db.execute("INSERT INTO rkd.job_attempt(job_id,attempt_no,organization_id,project_id,status,started_at) VALUES (%s,1,%s,%s,'running',now())",
                       (job, self.context.organization_id, self.context.project_id))
        other = replace(self.context, project_id="other-" + uuid4().hex)
        self.repository.ensure_project(other, "Other")
        self.assertEqual(self.store.run_in_transaction(other, lambda db: db.execute("SELECT count(*) FROM rkd.job_attempt").fetchone()[0]), 0)
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.store.tenant_transaction(other) as db:
                db.execute("INSERT INTO rkd.job_attempt(job_id,attempt_no,organization_id,project_id,status,started_at) VALUES (%s,2,%s,%s,'running',now())",
                           (job, other.organization_id, other.project_id))

    def test_06_command_fingerprint_and_expected_version(self):
        command = self.command()
        first = self.repository.append_command_event(command, "test.created", {"area": "46.00"}, expected_version=0)
        self.assertEqual(first, self.repository.append_command_event(command, "test.created", {"area": "46.00"}, expected_version=0))
        with self.assertRaises(ConflictError):
            self.repository.append_command_event(command, "test.created", {"area": "56.00"}, expected_version=0)
        with self.assertRaises(ConflictError):
            self.repository.append_command_event(replace(command, command_id="new-" + uuid4().hex, idempotency_key="new-key"), "test.created", {}, expected_version=0)
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))

    def test_07_concurrent_first_insert_replays_one_event(self):
        command = self.command()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.repository.append_command_event(command, "test.created", {}, expected_version=0), range(8)))
        self.assertEqual(len({row["event_id"] for row in results}), 1)
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))

    def test_08_concurrent_versions_accept_only_one(self):
        first = self.command()
        second = replace(first, command_id="cmd-" + uuid4().hex, idempotency_key="other-key")
        def write(command):
            try:
                return self.repository.append_command_event(command, "test.created", {}, expected_version=0)["status"]
            except ConflictError:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(write, (first, second))), ["accepted", "conflict"])
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))

    def test_09_outbox_failure_rolls_back_all_kernel_rows(self):
        command = self.command(aggregate_id="injected-failure")
        self.owner("""CREATE OR REPLACE FUNCTION rkd.inject_failure() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.aggregate_id='injected-failure' THEN RAISE EXCEPTION 'injected outbox failure'; END IF; RETURN NEW; END $$;
            CREATE TRIGGER test_fail_outbox BEFORE INSERT ON rkd.outbox_message FOR EACH ROW EXECUTE FUNCTION rkd.inject_failure();""")
        try:
            with self.assertRaises(psycopg.Error):
                self.repository.append_command_event(command, "test.created", {}, expected_version=0)
            self.assertEqual(self.counts(), (0, 0, 0, 0, 0))
        finally:
            self.owner("DROP TRIGGER test_fail_outbox ON rkd.outbox_message; DROP FUNCTION rkd.inject_failure();")

    def test_10_outbox_leases_materialized_and_expiry_fenced(self):
        command = self.command()
        result = self.repository.append_command_event(command, "test.created", {})
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda i: self.store.claim_outbox(self.context, "worker-" + str(i)), range(4)))
        self.assertEqual(sum(map(len, rows)), 1)
        self.assertIsNone(self.store.acknowledge_outbox(self.context, result["event_id"], "wrong-worker"))
        self.owner("UPDATE rkd.outbox_message SET lease_until=now()-interval '1 second' WHERE message_id=%s", (result["event_id"],))
        winner = next(i for i, claimed in enumerate(rows) if claimed)
        self.assertIsNone(self.store.acknowledge_outbox(self.context, result["event_id"], "worker-" + str(winner)))
        self.assertEqual(len(self.store.claim_outbox(self.context, "replacement")), 1)
        self.assertIsNotNone(self.store.acknowledge_outbox(self.context, result["event_id"], "replacement"))

    def test_11_audit_append_only_and_atomic_chain(self):
        self.repository.append_command_event(self.command(), "test.created", {})
        self.repository.append_command_event(self.command(), "test.created", {})
        rows = self.store.run_in_transaction(self.context, lambda db: db.execute(
            "SELECT previous_hash,event_hash FROM rkd.audit_event ORDER BY created_at,audit_id").fetchall())
        self.assertEqual(rows[0][0], "")
        self.assertEqual(rows[1][0], rows[0][1])
        with self.assertRaises(psycopg.Error):
            self.store.run_in_transaction(self.context, lambda db: db.execute("UPDATE rkd.audit_event SET outcome='forged'"))

    def test_12_all_runtime_tables_have_rls(self):
        rows = self.owner("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rkd' AND c.relkind='r' AND NOT c.relrowsecurity AND c.relname<>'schema_migration'")
        self.assertEqual(rows, [])

    def test_13_local_context_clears_after_commit_and_rollback(self):
        for rollback in (False, True):
            with APP_FACTORY() as db:
                db.execute("BEGIN")
                db.execute("SELECT set_config('rkd.organization_id',%s,true),set_config('rkd.project_id',%s,true)",
                           (self.context.organization_id, self.context.project_id))
                self.assertEqual(db.execute("SELECT count(*) FROM rkd.project").fetchone()[0], 1)
                db.rollback() if rollback else db.commit()
                self.assertEqual(db.execute("SELECT count(*) FROM rkd.project").fetchone()[0], 0)

    def test_14_inbox_deduplicates_on_live_database(self):
        self.assertIsNotNone(self.store.record_inbox_once(self.context, "message-1", "consumer", {"ok": True}))
        self.assertIsNone(self.store.record_inbox_once(self.context, "message-1", "consumer", {"ok": True}))

    def test_15_forged_scope_write_is_rejected_by_rls(self):
        other = replace(self.context, project_id="other-" + uuid4().hex)
        self.repository.ensure_project(other, "Other")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.store.tenant_transaction(self.context) as db:
                db.execute("INSERT INTO rkd.job(job_id,organization_id,project_id,job_type,status,input_hash,input_ref) VALUES (%s,%s,%s,'test','queued',%s,'test')",
                           (uuid4().hex, other.organization_id, other.project_id, uuid4().hex))

    def test_16_parallel_migration_startups_are_serialized(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            versions = list(pool.map(lambda _: PostgresMigrationRunner(OWNER_FACTORY).apply(), range(3)))
        self.assertEqual(versions, [tuple(range(1, 15))] * 3)
