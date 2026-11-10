CREATE TABLE rkd.ai_requirement_job (
    job_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    job_type text NOT NULL CHECK(job_type = 'requirement_understanding'),
    status text NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    phase text NOT NULL CHECK(phase IN ('queued', 'understanding', 'validating', 'persisting', 'completed', 'configuration_failed', 'failed')),
    attempt_count integer NOT NULL DEFAULT 0,
    input_hash text NOT NULL,
    context_manifest jsonb NOT NULL,
    request jsonb NOT NULL,
    config jsonb NOT NULL,
    output_brief_id text,
    error_code text,
    error_message text,
    idempotency_key text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX ai_requirement_job_project_created
ON rkd.ai_requirement_job(organization_id, project_id, created_at DESC);
ALTER TABLE rkd.ai_requirement_job ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_requirement_job_scope ON rkd.ai_requirement_job
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());

CREATE TABLE rkd.ai_requirement_run (
    run_id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES rkd.ai_requirement_job(job_id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    attempt_no integer NOT NULL,
    provider_kind text NOT NULL,
    provider_name text NOT NULL,
    model_id text,
    adapter_version text NOT NULL,
    prompt_version text NOT NULL,
    config_hash text NOT NULL,
    real_model boolean NOT NULL,
    status text NOT NULL CHECK(status IN ('running', 'succeeded', 'failed', 'late_result_discarded')),
    provider_request_id text,
    usage jsonb NOT NULL,
    cost jsonb NOT NULL,
    error jsonb,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    UNIQUE (job_id, attempt_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX ai_requirement_run_project_started
ON rkd.ai_requirement_run(organization_id, project_id, started_at DESC);
ALTER TABLE rkd.ai_requirement_run ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_requirement_run_scope ON rkd.ai_requirement_run
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());

CREATE TABLE rkd.ai_requirement_brief (
    brief_id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES rkd.ai_requirement_job(job_id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    revision_no integer NOT NULL,
    schema_version text NOT NULL,
    brief jsonb NOT NULL,
    input_hash text NOT NULL,
    source_kind text NOT NULL CHECK(source_kind IN ('model_output', 'human_edit')),
    change_reason text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (job_id, revision_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX ai_requirement_brief_project_created
ON rkd.ai_requirement_brief(organization_id, project_id, created_at DESC);
ALTER TABLE rkd.ai_requirement_brief ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_requirement_brief_scope ON rkd.ai_requirement_brief
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());
