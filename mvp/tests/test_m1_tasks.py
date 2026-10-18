from pathlib import Path
import tempfile
import unittest

from rkd_mvp.api_service import ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID
from rkd_mvp.sqlite_store import SQLiteStore
from rkd_mvp.task_service import TaskService, TaskServiceError


FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "ningbo-xiecheng" / "2026-09"


class M1TaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = SQLiteStore(root / "app.sqlite3")
        self.files = FileService(root / "app.sqlite3", root)
        self.tasks = TaskService(root / "app.sqlite3")
        self.service = ApiService(MVPApp(self.store), self.files, self.tasks)
        self.files.seed_ningbo(self.service, FIXTURE_ROOT)
        self.tasks.ensure_ningbo_seed("org-local", NINGBO_PROJECT_ID, FIXTURE_ROOT)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_seed_import_is_persistent_and_source_linked(self):
        jobs = self.tasks.list_jobs("org-local", NINGBO_PROJECT_ID)["items"]
        issues = self.tasks.list_issues("org-local", NINGBO_PROJECT_ID)["items"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "succeeded")
        self.assertEqual(jobs[0]["attempt_count"], 1)
        self.assertEqual(jobs[0]["output"]["issue_count"], 5)
        self.assertTrue(all(item["source_locator"] for item in issues))
        self.assertTrue(any(item["detail"].get("promotion_status") == "not-approved" for item in issues))

        restored_store = SQLiteStore(self.store.db_path)
        restored_tasks = TaskService(self.store.db_path)
        self.assertEqual(len(restored_tasks.list_issues("org-local", NINGBO_PROJECT_ID)["items"]), 5)
        restored_store.close()

    def test_disposition_is_versioned_and_approval_is_not_an_option(self):
        issue = self.tasks.list_issues("org-local", NINGBO_PROJECT_ID)["items"][0]
        updated = self.tasks.record_disposition(
            "org-local", NINGBO_PROJECT_ID, issue["issue_id"],
            {"status": "in_review", "reason": "已定位来源，等待专业责任人复核", "expected_version": issue["version"]},
            "local-user",
        )
        self.assertEqual(updated["disposition_status"], "in_review")
        with self.assertRaises(TaskServiceError) as error:
            self.tasks.record_disposition(
                "org-local", NINGBO_PROJECT_ID, issue["issue_id"],
                {"status": "approved", "reason": "no", "expected_version": updated["version"]},
                "local-user",
            )
        self.assertEqual(error.exception.code, "INVALID_DISPOSITION")

    def test_retry_does_not_duplicate_issues_and_restart_recovers_running(self):
        job = self.tasks.list_jobs("org-local", NINGBO_PROJECT_ID)["items"][0]
        with self.tasks._db() as connection:
            connection.execute("UPDATE jobs SET status = 'retryable' WHERE job_id = ?", (job["job_id"],))
        retried = self.tasks.retry_job("org-local", NINGBO_PROJECT_ID, job["job_id"], FIXTURE_ROOT)
        self.assertEqual(retried["status"], "succeeded")
        self.assertEqual(retried["attempt_count"], 2)
        self.assertEqual(len(self.tasks.list_issues("org-local", NINGBO_PROJECT_ID)["items"]), 5)
        with self.tasks._db() as connection:
            connection.execute("UPDATE jobs SET status = 'running' WHERE job_id = ?", (job["job_id"],))
        recovered = TaskService(self.store.db_path)
        self.assertEqual(recovered.list_jobs("org-local", NINGBO_PROJECT_ID)["items"][0]["status"], "retryable")

    def test_cancel_is_persistent_and_completed_job_cannot_be_cancelled(self):
        job = self.tasks.list_jobs("org-local", NINGBO_PROJECT_ID)["items"][0]
        with self.tasks._db() as connection:
            connection.execute("UPDATE jobs SET status = 'retryable' WHERE job_id = ?", (job["job_id"],))
        cancelled = self.tasks.cancel_job("org-local", NINGBO_PROJECT_ID, job["job_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["error_code"], "CANCELLED_BY_USER")
        with self.assertRaises(TaskServiceError) as error:
            self.tasks.cancel_job("org-local", NINGBO_PROJECT_ID, job["job_id"])
        self.assertEqual(error.exception.code, "JOB_STATE")


if __name__ == "__main__":
    unittest.main()
