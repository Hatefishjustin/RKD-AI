from pathlib import Path
import tempfile
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp import MVPApp
from rkd_mvp.sqlite_store import SQLiteStore
from rkd_mvp.workflow import DurableWorkflowRuntime
from rkd_mvp.store import AccessDenied, ConflictError
from rkd_mvp.models import TenantContext


SQL_PATH = Path(__file__).parents[1] / "persistence" / "postgres" / "001_vertical_mvp.sql"


class PersistenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = SQL_PATH.read_text(encoding="utf-8")

    def test_core_tables_and_deduplication_constraints_exist(self):
        for table in (
            "command_record", "aggregate_state", "domain_event", "outbox_message",
            "inbox_message", "audit_event", "workflow_run", "workflow_activity",
            "dead_letter", "executor_job", "executor_result", "artifact", "external_action",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS rkd.{table}", self.sql)
        self.assertIn("UNIQUE (organization_id, project_id, idempotency_key)", self.sql)
        self.assertIn("PRIMARY KEY (organization_id, project_id, message_id, consumer_name)", self.sql)

    def test_all_project_scoped_tables_enable_rls(self):
        expected = (
            "organization", "project", "project_member", "command_record", "aggregate_state", "domain_event",
            "outbox_message", "inbox_message", "audit_event", "workflow_run", "workflow_activity",
            "dead_letter", "executor_job", "executor_result", "artifact", "external_action",
        )
        for table in expected:
            self.assertIn(f"ALTER TABLE rkd.{table} ENABLE ROW LEVEL SECURITY", self.sql)
            self.assertIn(f"ON rkd.{table}", self.sql)
        self.assertIn("rkd.current_organization()", self.sql)
        self.assertIn("rkd.current_project()", self.sql)

    def test_external_unknown_and_audit_append_only_are_explicit(self):
        self.assertIn("'unknown'", self.sql)
        self.assertIn("'manual-resolution'", self.sql)
        self.assertIn("audit_event is append-only", self.sql)

    def test_sqlite_store_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "vertical-mvp.sqlite3"
            first = MVPApp(SQLiteStore(db_path))
            context = first.context()
            first.bootstrap(context)
            result = first.run_happy_path(context)
            event_count = len(first.store.events)
            first.store.close()

            second_store = SQLiteStore(db_path)
            second = MVPApp(second_store)
            self.assertEqual(len(second.store.events), event_count)
            self.assertGreater(len(second.store.commands), 0)
            self.assertGreater(len(second.store.jobs), 0)
            self.assertGreater(len(second.store.artifacts), 0)
            self.assertIn("action_publish-1", second.store.external_actions)
            self.assertIn(result["publish"], {"confirmed", "unknown"})
            self.assertEqual(second.store.projects[(context.organization_id, context.project_id)]["name"], "Vertical MVP Demo")
            second.store.close()

    def test_workflow_state_survives_restart_and_rejects_invalid_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "workflow.sqlite3"
            context = MVPApp().context()
            first_store = SQLiteStore(db_path)
            first = MVPApp(first_store)
            first.bootstrap(context)
            runtime = DurableWorkflowRuntime(first_store)
            run_id = runtime.start(context, "vertical-mvp", "baseline-1")
            runtime.transition(context, run_id, "intake")
            with self.assertRaises(ConflictError):
                runtime.transition(context, run_id, "completed")
            first_store.close()

            second_store = SQLiteStore(db_path)
            recovered = DurableWorkflowRuntime(second_store)
            self.assertEqual(recovered.get(context, run_id)["current_state"], "intake")
            recovered.recover(context, run_id)
            self.assertEqual(recovered.get(context, run_id)["recovery_count"], 1)
            other = TenantContext("other-org", context.project_id, "other-user")
            with self.assertRaises(AccessDenied):
                recovered.get(other, run_id)
            second_store.close()


if __name__ == "__main__":
    unittest.main()
