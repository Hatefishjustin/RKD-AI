CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    input_hash TEXT NOT NULL,
    input_ref TEXT NOT NULL,
    output_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    error_message TEXT,
    lease_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, job_type, input_hash)
);

CREATE INDEX IF NOT EXISTS jobs_project_updated
ON jobs(organization_id, project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS job_attempts (
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_code TEXT,
    error_message TEXT,
    PRIMARY KEY (job_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS issues (
    issue_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    source_file_id TEXT,
    source_ref TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    disposition_status TEXT NOT NULL DEFAULT 'open',
    disposition_reason TEXT,
    disposition_actor_id TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, issue_type, source_ref)
);

CREATE INDEX IF NOT EXISTS issues_project_updated
ON issues(organization_id, project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS issue_actions (
    action_id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL REFERENCES issues(issue_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
