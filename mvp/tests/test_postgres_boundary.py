from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.models import TenantContext
from rkd_mvp.postgres_store import PostgresStore
from rkd_mvp.postgres_repository import PostgresRepository
from rkd_mvp.models import CommandEnvelope


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return {"rows": []}

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class PostgresBoundaryTests(unittest.TestCase):
    def test_transaction_sets_both_rls_context_values_and_commits(self):
        connection = FakeConnection()
        store = PostgresStore(lambda: connection)
        context = TenantContext("org-1", "project-1", "user-1")
        result = store.run_in_transaction(context, lambda db: "ok")
        self.assertEqual(result, "ok")
        self.assertTrue(connection.committed)
        self.assertTrue(connection.closed)
        sql = " ".join(call[0] for call in connection.calls)
        self.assertIn("rkd.organization_id", sql)
        self.assertIn("rkd.project_id", sql)

    def test_transaction_rolls_back_on_error(self):
        connection = FakeConnection()
        store = PostgresStore(lambda: connection)
        with self.assertRaises(RuntimeError):
            store.run_in_transaction(TenantContext("org-1", "project-1", "user-1"), lambda db: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)

    def test_outbox_claim_uses_skip_locked_and_lease(self):
        connection = FakeConnection()
        store = PostgresStore(lambda: connection)
        store.claim_outbox(TenantContext("org-1", "project-1", "worker"), "worker-1")
        sql = connection.calls[-1][0]
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertIn("lease_until", sql)
        self.assertIn("project_id = %s", sql)


class RepositoryConnection(FakeConnection):
    class Cursor:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    def __init__(self, command_row=None, aggregate_row=None):
        super().__init__()
        self.command_row = command_row
        self.aggregate_row = aggregate_row

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "FROM rkd.command_record" in sql:
            return self.Cursor(self.command_row)
        if "FROM rkd.aggregate_state" in sql:
            return self.Cursor(self.aggregate_row)
        if "RETURNING organization_id, project_id, name, status" in sql:
            return self.Cursor((params[0], params[1], params[2], "active"))
        return self.Cursor()


class PostgresRepositoryTests(unittest.TestCase):
    def test_project_write_uses_rkd_transaction(self):
        connection = RepositoryConnection()
        repository = PostgresRepository(PostgresStore(lambda: connection))
        context = TenantContext("org-1", "project-1", "user-1")
        project = repository.ensure_project(context, "Demo")
        self.assertEqual(project["project_id"], "project-1")
        self.assertTrue(connection.committed)
        self.assertTrue(connection.closed)
        sql = " ".join(call[0] for call in connection.calls)
        self.assertIn("INSERT INTO rkd.organization", sql)
        self.assertIn("INSERT INTO rkd.project", sql)

    def test_append_event_is_one_atomic_kernel_write(self):
        connection = RepositoryConnection()
        repository = PostgresRepository(PostgresStore(lambda: connection))
        context = TenantContext("org-1", "project-1", "user-1")
        command = CommandEnvelope(
            command_id="cmd-1", command_name="estimate", context=context,
            idempotency_key="idem-1", aggregate_id="estimate-1", payload={"x": 1},
        )
        result = repository.append_command_event(command, "estimate.created", {"x": 1})
        self.assertEqual(result["aggregate_version"], 1)
        self.assertTrue(connection.committed)
        sql = " ".join(call[0] for call in connection.calls)
        for fragment in ("command_record", "aggregate_state", "domain_event", "outbox_message"):
            self.assertIn(fragment, sql)

    def test_existing_idempotency_result_is_returned_without_new_event(self):
        connection = RepositoryConnection(command_row=({"status": "accepted"},))
        repository = PostgresRepository(PostgresStore(lambda: connection))
        context = TenantContext("org-1", "project-1", "user-1")
        command = CommandEnvelope(
            command_id="cmd-1", command_name="estimate", context=context,
            idempotency_key="idem-1", aggregate_id="estimate-1", payload={},
        )
        result = repository.append_command_event(command, "estimate.created", {})
        self.assertEqual(result, {"status": "accepted"})
        self.assertNotIn("INSERT INTO rkd.domain_event", " ".join(call[0] for call in connection.calls))


if __name__ == "__main__":
    unittest.main()
