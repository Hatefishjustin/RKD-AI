"""Explicit task/issue persistence adapters; no SQL rewriting or fallback."""
from contextlib import contextmanager
from .models import TenantContext
from .file_repository import mapping
from .model_repository import canonical


class SQLiteTaskTransaction:
    def __init__(self, db, org=None, project=None):
        self.db, self.scope = db, (org, project)

    def job(self, job_id):
        return self.db.execute("SELECT * FROM jobs WHERE organization_id=? AND project_id=? AND job_id=?", (*self.scope, job_id)).fetchone()

    def seed_job(self, input_hash):
        return self.db.execute("SELECT * FROM jobs WHERE organization_id=? AND project_id=? AND job_type='cad_report_import' AND input_hash=?", (*self.scope, input_hash)).fetchone()

    def insert_job(self, job_id, input_hash, now):
        self.db.execute("INSERT INTO jobs(organization_id,project_id,job_id,job_type,status,attempt_count,input_hash,input_ref,created_at,updated_at) VALUES (?,?,?,'cad_report_import','queued',0,?,'derived/cad-source-inspection.json',?,?)", (*self.scope, job_id, input_hash, now, now))

    def start(self, job_id, attempt, now):
        self.db.execute("UPDATE jobs SET status='running',attempt_count=?,error_code=NULL,error_message=NULL,lease_until=NULL,updated_at=? WHERE organization_id=? AND project_id=? AND job_id=?", (attempt, now, *self.scope, job_id))
        self.db.execute("INSERT INTO job_attempts(job_id,attempt_no,status,started_at) VALUES (?,?,'running',?)", (job_id, attempt, now))

    @contextmanager
    def work(self):
        self.db.execute("SAVEPOINT import_work")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK TO SAVEPOINT import_work")
            raise
        finally:
            self.db.execute("RELEASE SAVEPOINT import_work")

    def source_files(self):
        return {r["source_ref"]: r["file_id"] for r in self.db.execute("SELECT file_id,source_ref FROM file_assets WHERE organization_id=? AND project_id=?", self.scope)}

    def existing_issue(self, issue_type, source_ref):
        return self.db.execute("SELECT issue_id FROM issues WHERE organization_id=? AND project_id=? AND issue_type=? AND source_ref=?", (*self.scope, issue_type, source_ref)).fetchone()

    def insert_issue(self, issue_id, spec, detail, now):
        self.db.execute("INSERT INTO issues(organization_id,project_id,issue_id,source_file_id,source_ref,source_locator,issue_type,severity,title,detail_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (*self.scope, issue_id, spec['source_file_id'], spec['source_ref'], spec['source_locator'], spec['issue_type'], spec['severity'], spec['title'], detail, now, now))

    def finish(self, job_id, attempt, now, output=None, error=None, code=None):
        if error is None:
            self.db.execute("UPDATE job_attempts SET status='succeeded',finished_at=? WHERE job_id=? AND attempt_no=?", (now, job_id, attempt))
            self.db.execute("UPDATE jobs SET status='succeeded',output_json=?,updated_at=? WHERE organization_id=? AND project_id=? AND job_id=?", (output, now, *self.scope, job_id))
        else:
            self.db.execute("UPDATE job_attempts SET status='retryable',finished_at=?,error_code=?,error_message=? WHERE job_id=? AND attempt_no=?", (now, code, error, job_id, attempt))
            self.db.execute("UPDATE jobs SET status='retryable',error_code=?,error_message=?,updated_at=? WHERE organization_id=? AND project_id=? AND job_id=?", (code, error, now, *self.scope, job_id))

    def jobs(self):
        return self.db.execute("SELECT * FROM jobs WHERE organization_id=? AND project_id=? ORDER BY updated_at DESC,job_id DESC", self.scope).fetchall()

    def queue(self, job_id, now):
        self.db.execute("UPDATE jobs SET status='queued',updated_at=? WHERE organization_id=? AND project_id=? AND job_id=?", (now, *self.scope, job_id))

    def cancel(self, job_id, now):
        self.db.execute("UPDATE jobs SET status='cancelled',error_code='CANCELLED_BY_USER',error_message='用户取消任务',updated_at=? WHERE organization_id=? AND project_id=? AND job_id=?", (now, *self.scope, job_id))

    def issues(self):
        return self.db.execute("SELECT * FROM issues WHERE organization_id=? AND project_id=? ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,updated_at DESC,issue_id", self.scope).fetchall()

    def issue(self, issue_id):
        return self.db.execute("SELECT * FROM issues WHERE organization_id=? AND project_id=? AND issue_id=?", (*self.scope, issue_id)).fetchone()

    def actions(self, issue_id):
        return self.db.execute("SELECT action,reason,actor_id,created_at FROM issue_actions WHERE organization_id=? AND project_id=? AND issue_id=? ORDER BY created_at,action_id", (*self.scope, issue_id)).fetchall()

    def disposition(self, issue_id, status, reason, actor, now, action_id):
        self.db.execute("UPDATE issues SET disposition_status=?,disposition_reason=?,disposition_actor_id=?,version=version+1,updated_at=? WHERE organization_id=? AND project_id=? AND issue_id=?", (status, reason, actor, now, *self.scope, issue_id))
        self.db.execute("INSERT INTO issue_actions(action_id,issue_id,organization_id,project_id,action,reason,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?)", (action_id, issue_id, *self.scope, status, reason, actor, now))


class SQLiteTaskRepository:
    def __init__(self, context):
        self.context = context

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.context() as db:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield SQLiteTaskTransaction(db, org, project)

    def recover(self, now, org=None, project=None):
        if org is not None:
            return
        with self.context() as db:
            db.execute("BEGIN IMMEDIATE")
            if org is None:
                db.execute("UPDATE jobs SET status='retryable',error_code='WORKER_RESTARTED',error_message='本地服务重启，任务等待再次执行',lease_until=NULL,updated_at=? WHERE status='running'", (now,))
                db.execute("UPDATE job_attempts SET status='retryable',finished_at=?,error_code='WORKER_RESTARTED',error_message='本地服务重启' WHERE status='running' AND finished_at IS NULL", (now,))


class PostgresTaskTransaction:
    def __init__(self, db, org, project):
        self.db, self.scope = db, (org, project)

    def rows(self, query, params):
        return canonical(mapping(self.db.execute(query, params)))

    def one(self, query, params):
        rows = self.rows(query, params)
        return rows[0] if rows else None

    def job(self, job_id):
        return self.one("SELECT job_id,organization_id,project_id,job_type,status,attempt_count,input_hash,input_ref,output::text AS output_json,error_code,error_message,created_at,updated_at FROM rkd.job WHERE organization_id=%s AND project_id=%s AND job_id=%s", (*self.scope, job_id))

    def seed_job(self, input_hash):
        row = self.one("SELECT job_id FROM rkd.job WHERE organization_id=%s AND project_id=%s AND job_type='cad_report_import' AND input_hash=%s", (*self.scope, input_hash))
        return self.job(row['job_id']) if row else None

    def insert_job(self, job_id, input_hash, now):
        self.db.execute("INSERT INTO rkd.job(organization_id,project_id,job_id,job_type,status,attempt_count,input_hash,input_ref,created_at,updated_at) VALUES (%s,%s,%s,'cad_report_import','queued',0,%s,'derived/cad-source-inspection.json',%s,%s)", (*self.scope, job_id, input_hash, now, now))

    def start(self, job_id, attempt, now):
        self.db.execute("UPDATE rkd.job SET status='running',attempt_count=%s,error_code=NULL,error_message=NULL,lease_until=NULL,updated_at=%s WHERE organization_id=%s AND project_id=%s AND job_id=%s", (attempt, now, *self.scope, job_id))
        self.db.execute("INSERT INTO rkd.job_attempt(organization_id,project_id,job_id,attempt_no,status,started_at) VALUES (%s,%s,%s,%s,'running',%s)", (*self.scope, job_id, attempt, now))

    work = SQLiteTaskTransaction.work

    def source_files(self):
        return {r['source_ref']: r['file_id'] for r in self.rows("SELECT file_id,source_ref FROM rkd.file_asset WHERE organization_id=%s AND project_id=%s", self.scope)}

    def existing_issue(self, issue_type, source_ref):
        return self.one("SELECT issue_id FROM rkd.issue WHERE organization_id=%s AND project_id=%s AND issue_type=%s AND source_ref=%s", (*self.scope, issue_type, source_ref))

    def insert_issue(self, issue_id, spec, detail, now):
        self.db.execute("INSERT INTO rkd.issue(organization_id,project_id,issue_id,source_file_id,source_ref,source_locator,issue_type,severity,title,detail,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)", (*self.scope, issue_id, spec['source_file_id'], spec['source_ref'], spec['source_locator'], spec['issue_type'], spec['severity'], spec['title'], detail, now, now))

    def finish(self, job_id, attempt, now, output=None, error=None, code=None):
        if error is None:
            self.db.execute("UPDATE rkd.job_attempt SET status='succeeded',finished_at=%s WHERE organization_id=%s AND project_id=%s AND job_id=%s AND attempt_no=%s", (now, *self.scope, job_id, attempt))
            self.db.execute("UPDATE rkd.job SET status='succeeded',output=%s::jsonb,updated_at=%s WHERE organization_id=%s AND project_id=%s AND job_id=%s", (output, now, *self.scope, job_id))
        else:
            self.db.execute("UPDATE rkd.job_attempt SET status='retryable',finished_at=%s,error_code=%s,error_message=%s WHERE organization_id=%s AND project_id=%s AND job_id=%s AND attempt_no=%s", (now, code, error, *self.scope, job_id, attempt))
            self.db.execute("UPDATE rkd.job SET status='retryable',error_code=%s,error_message=%s,updated_at=%s WHERE organization_id=%s AND project_id=%s AND job_id=%s", (code, error, now, *self.scope, job_id))

    def jobs(self):
        return self.rows("SELECT job_id,organization_id,project_id,job_type,status,attempt_count,input_hash,input_ref,output::text AS output_json,error_code,error_message,created_at,updated_at FROM rkd.job WHERE organization_id=%s AND project_id=%s ORDER BY updated_at DESC,job_id DESC", self.scope)

    def queue(self, job_id, now):
        self.db.execute("UPDATE rkd.job SET status='queued',updated_at=%s WHERE organization_id=%s AND project_id=%s AND job_id=%s", (now, *self.scope, job_id))

    def cancel(self, job_id, now):
        self.db.execute("UPDATE rkd.job SET status='cancelled',error_code='CANCELLED_BY_USER',error_message='用户取消任务',updated_at=%s WHERE organization_id=%s AND project_id=%s AND job_id=%s", (now, *self.scope, job_id))

    def issues(self):
        return self.rows("SELECT issue_id,organization_id,project_id,source_file_id,source_ref,source_locator,issue_type,severity,title,detail::text AS detail_json,disposition_status,disposition_reason,disposition_actor_id,version,created_at,updated_at FROM rkd.issue WHERE organization_id=%s AND project_id=%s ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,updated_at DESC,issue_id", self.scope)

    def issue(self, issue_id):
        return self.one("SELECT issue_id,organization_id,project_id,source_file_id,source_ref,source_locator,issue_type,severity,title,detail::text AS detail_json,disposition_status,disposition_reason,disposition_actor_id,version,created_at,updated_at FROM rkd.issue WHERE organization_id=%s AND project_id=%s AND issue_id=%s", (*self.scope, issue_id))

    def actions(self, issue_id):
        return self.rows("SELECT action,reason,actor_id,created_at FROM rkd.issue_action WHERE organization_id=%s AND project_id=%s AND issue_id=%s ORDER BY created_at,action_id", (*self.scope, issue_id))

    def disposition(self, issue_id, status, reason, actor, now, action_id):
        self.db.execute("UPDATE rkd.issue SET disposition_status=%s,disposition_reason=%s,disposition_actor_id=%s,version=version+1,updated_at=%s WHERE organization_id=%s AND project_id=%s AND issue_id=%s", (status, reason, actor, now, *self.scope, issue_id))
        self.db.execute("INSERT INTO rkd.issue_action(action_id,issue_id,organization_id,project_id,action,reason,actor_id,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (action_id, issue_id, *self.scope, status, reason, actor, now))


class PostgresTaskRepository:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.store.tenant_transaction(TenantContext(org, project, 'local-user')) as db:
            if write:
                db.execute("SELECT project_id FROM rkd.project WHERE organization_id=%s AND project_id=%s FOR UPDATE", (org, project))
            yield PostgresTaskTransaction(db, org, project)

    def recover(self, now, org=None, project=None):
        # No unscoped RLS bypass. A visible running import after acquiring the
        # project lock is orphaned: our worker holds that lock until completion.
        if org is None:
            return
        with self.transaction(org, project, write=True) as tx:
            tx.db.execute("UPDATE rkd.job SET status='retryable',error_code='WORKER_RESTARTED',error_message='任务等待再次执行',lease_until=NULL,updated_at=%s WHERE organization_id=%s AND project_id=%s AND status='running'", (now, org, project))
            tx.db.execute("UPDATE rkd.job_attempt SET status='retryable',finished_at=%s,error_code='WORKER_RESTARTED',error_message='任务等待再次执行' WHERE organization_id=%s AND project_id=%s AND status='running' AND finished_at IS NULL", (now, org, project))
