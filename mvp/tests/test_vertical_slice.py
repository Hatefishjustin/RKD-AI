import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp import MVPApp
from rkd_mvp.models import TenantContext
from rkd_mvp.store import AccessDenied, ConflictError


class VerticalSliceTests(unittest.TestCase):
    def setUp(self):
        self.app = MVPApp()
        self.context = self.app.context()
        self.app.bootstrap(self.context)

    def test_happy_path_produces_two_branches_and_audit(self):
        result = self.app.run_happy_path(self.context)
        self.assertEqual(result["drawing"], "succeeded")
        self.assertEqual(result["boq"], "succeeded")
        self.assertEqual(result["validation"], "succeeded")
        self.assertEqual(result["publish"], "confirmed")
        self.assertEqual(result["workflow_state"], "completed")
        self.assertGreater(result["outbox_published"], 0)
        self.assertGreaterEqual(len(result["artifact_ids"]), 3)
        self.assertGreater(len(self.app.store.outbox), 0)
        self.assertTrue(all(item.event_hash for item in self.app.store.audit))

    def test_command_is_idempotent(self):
        first = self.app.command(self.context, "CreateRequirementDraft", "requirement_demo",
                                 {"goal": "same"}, "same-key")
        second = self.app.command(self.context, "CreateRequirementDraft", "requirement_demo",
                                  {"goal": "different"}, "same-key")
        self.assertEqual(first, second)
        self.assertEqual(len([e for e in self.app.store.events if e.event_type == "requirement.draft-created"]), 1)

    def test_executor_callback_is_deduplicated(self):
        payload = {"batch": "batch_demo"}
        first = self.app.run_executor(self.context, "drawing", payload, "duplicate-job")
        second = self.app.run_executor(self.context, "drawing", payload, "duplicate-job")
        self.assertEqual(first.job_id, second.job_id)
        self.assertEqual(len(self.app.store.artifacts), 1)

    def test_cross_tenant_access_is_rejected(self):
        other = TenantContext("other-org", self.context.project_id, "other-user")
        with self.assertRaises(AccessDenied):
            self.app.run_happy_path(other)

    def test_same_project_id_in_different_organizations_is_isolated(self):
        other = TenantContext("other-org", self.context.project_id, "other-user")
        self.app.bootstrap(other)
        self.assertEqual(len(self.app.store.projects), 2)
        first = self.app.run_executor(self.context, "drawing", {"batch": "one"}, "same-job-key")
        second = self.app.run_executor(other, "drawing", {"batch": "two"}, "same-job-key")
        self.assertNotEqual(first.job_id, second.job_id)
        self.assertEqual(len(self.app.store.jobs), 2)

    def test_agent_cannot_approve_g2(self):
        agent = self.app.context(actor_type="agent", actor_id="agent-1")
        with self.assertRaises(AccessDenied):
            self.app.command(agent, "ApproveDesignIntent", "intent_demo", {}, "agent-g2")

    def test_external_unknown_is_not_retried(self):
        result = self.app.run_executor(self.context, "drawing", {"batch": "batch_demo"}, "publish-fixture")
        artifact_id = result.outputs[0]["artifact_id"]
        self.app.publisher.mode = "unknown"
        first = self.app.publish(self.context, [artifact_id], "unknown-action")
        second = self.app.publish(self.context, [artifact_id], "unknown-action")
        self.assertEqual(first["status"], "unknown")
        self.assertEqual(first, second)

    def test_quality_failure_does_not_create_artifact(self):
        self.app.executors["drawing"].failure_mode = "quality-failed"
        result = self.app.run_executor(self.context, "drawing", {"batch": "batch_demo"}, "quality-fixture")
        self.assertEqual(result.status, "quality-failed")
        self.assertEqual(result.outputs, [])
        self.assertEqual(self.app.store.artifacts, {})

    def test_failed_branch_marks_workflow_failed(self):
        self.app.executors["drawing"].failure_mode = "quality-failed"
        with self.assertRaises(ConflictError):
            self.app.run_happy_path(self.context)
        self.assertEqual(len(self.app.store.workflow_runs), 1)
        run = next(iter(self.app.store.workflow_runs.values()))
        self.assertEqual(run["current_state"], "failed")

    def test_outbox_retry_dead_letter_and_inbox_deduplication(self):
        self.app.command(self.context, "CreateRequirementDraft", "requirement_queue",
                         {"goal": "queue"}, "queue-key")
        received = []
        first = self.app.queue.drain_outbox(self.context, lambda event: received.append(event.event_id))
        second = self.app.queue.drain_outbox(self.context, lambda event: received.append(event.event_id))
        self.assertGreater(first["published"], 0)
        self.assertEqual(second["published"], 0)
        self.assertEqual(len(received), first["published"])

        self.app.command(self.context, "CreateRequirementDraft", "requirement_dead",
                         {"goal": "dead-letter"}, "dead-letter-key")
        retry = self.app.queue.drain_outbox(self.context, lambda event: (_ for _ in ()).throw(RuntimeError("downstream unavailable")), max_attempts=2)
        dead = self.app.queue.drain_outbox(self.context, lambda event: (_ for _ in ()).throw(RuntimeError("downstream unavailable")), max_attempts=2)
        self.assertEqual(retry["retryable"], 1)
        self.assertEqual(dead["dead_letter"], 1)

        event = self.app.store.events[0]
        handled = []
        self.assertEqual(self.app.queue.consume_inbox(self.context, event, "search-index", lambda item: handled.append(item.event_id)), "processed")
        self.assertEqual(self.app.queue.consume_inbox(self.context, event, "search-index", lambda item: handled.append(item.event_id)), "duplicate")
        self.assertEqual(len(handled), 1)

    def test_inbox_failure_is_retryable(self):
        self.app.command(self.context, "CreateRequirementDraft", "requirement-inbox-failure",
                         {"goal": "retry"}, "inbox-failure-key")
        event = self.app.store.events[-1]
        with self.assertRaises(RuntimeError):
            self.app.queue.consume_inbox(self.context, event, "failing-consumer", lambda item: (_ for _ in ()).throw(RuntimeError("consumer down")))
        handled = []
        self.assertEqual(self.app.queue.consume_inbox(self.context, event, "failing-consumer", lambda item: handled.append(item.event_id)), "processed")
        self.assertEqual(len(handled), 1)


if __name__ == "__main__":
    unittest.main()
