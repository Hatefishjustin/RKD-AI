CREATE TABLE ai_requirement_jobs (
    job_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    job_type TEXT NOT NULL CHECK(job_type = 'requirement_understanding'),
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    phase TEXT NOT NULL CHECK(phase IN ('queued', 'understanding', 'validating', 'persisting', 'completed', 'configuration_failed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    input_hash TEXT NOT NULL,
    context_manifest_json TEXT NOT NULL,
    request_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    output_brief_id TEXT,
    error_code TEXT,
    error_message TEXT,
    idempotency_key TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE INDEX ai_requirement_jobs_project_created
ON ai_requirement_jobs(organization_id, project_id, created_at DESC);

CREATE TABLE ai_requirement_runs (
    run_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES ai_requirement_jobs(job_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    provider_kind TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    model_id TEXT,
    adapter_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    real_model INTEGER NOT NULL CHECK(real_model IN (0, 1)),
    status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed', 'late_result_discarded')),
    provider_request_id TEXT,
    usage_json TEXT NOT NULL,
    cost_json TEXT NOT NULL,
    error_json TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (job_id, attempt_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE INDEX ai_requirement_runs_project_started
ON ai_requirement_runs(organization_id, project_id, started_at DESC);

CREATE TABLE ai_requirement_briefs (
    brief_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES ai_requirement_jobs(job_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    schema_version TEXT NOT NULL,
    brief_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('model_output', 'human_edit')),
    change_reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (job_id, revision_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE INDEX ai_requirement_briefs_project_created
ON ai_requirement_briefs(organization_id, project_id, created_at DESC);
