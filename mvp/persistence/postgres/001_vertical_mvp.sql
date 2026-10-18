BEGIN;

CREATE SCHEMA IF NOT EXISTS rkd;

CREATE TABLE IF NOT EXISTS rkd.organization (
    organization_id text PRIMARY KEY,
    name text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rkd.project (
    organization_id text NOT NULL REFERENCES rkd.organization(organization_id),
    project_id text NOT NULL,
    name text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.project_member (
    organization_id text NOT NULL,
    project_id text NOT NULL,
    actor_id text NOT NULL,
    role_code text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, actor_id),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.command_record (
    command_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    command_name text NOT NULL,
    aggregate_id text NOT NULL,
    idempotency_key text NOT NULL,
    actor_id text NOT NULL,
    actor_type text NOT NULL,
    status text NOT NULL CHECK (status IN ('accepted', 'rejected', 'failed')),
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.aggregate_state (
    organization_id text NOT NULL,
    project_id text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, aggregate_type, aggregate_id),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.domain_event (
    event_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    event_type text NOT NULL,
    event_schema_version text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    aggregate_version bigint NOT NULL,
    correlation_id text NOT NULL,
    causation_id text NOT NULL,
    idempotency_key text NOT NULL,
    payload_hash text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, aggregate_type, aggregate_id, aggregate_version),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.outbox_message (
    message_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    message_type text NOT NULL,
    aggregate_id text NOT NULL,
    dedupe_key text NOT NULL,
    payload jsonb NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    lease_owner text,
    lease_until timestamptz,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, dedupe_key),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.inbox_message (
    organization_id text NOT NULL,
    project_id text NOT NULL,
    message_id text NOT NULL,
    consumer_name text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (organization_id, project_id, message_id, consumer_name),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.dead_letter (
    dead_letter_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    message_id text NOT NULL,
    consumer_name text NOT NULL,
    attempts integer NOT NULL CHECK (attempts > 0),
    last_error text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, message_id, consumer_name),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.audit_event (
    audit_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    event_type text NOT NULL,
    target_type text NOT NULL,
    target_id text NOT NULL,
    actor_id text NOT NULL,
    outcome text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    previous_hash text NOT NULL DEFAULT '',
    event_hash text NOT NULL,
    checkpoint boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.workflow_run (
    workflow_run_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    workflow_type text NOT NULL,
    workflow_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('created', 'running', 'waiting', 'blocked', 'failed', 'completed', 'superseded')),
    current_state text NOT NULL,
    correlation_id text NOT NULL,
    input_revision text NOT NULL,
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.workflow_activity (
    activity_id text PRIMARY KEY,
    workflow_run_id text NOT NULL REFERENCES rkd.workflow_run(workflow_run_id),
    organization_id text NOT NULL,
    project_id text NOT NULL,
    activity_type text NOT NULL,
    activity_key text NOT NULL,
    status text NOT NULL CHECK (status IN ('scheduled', 'running', 'waiting', 'succeeded', 'retryable', 'failed', 'cancelled')),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    input_hash text NOT NULL,
    output jsonb NOT NULL DEFAULT '{}'::jsonb,
    next_attempt_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workflow_run_id, activity_key),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.executor_job (
    job_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    production_batch_id text NOT NULL,
    executor_kind text NOT NULL,
    executor_version text NOT NULL,
    input_spec_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'retryable', 'quality-failed', 'failed', 'cancelled')),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.executor_result (
    result_id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES rkd.executor_job(job_id),
    organization_id text NOT NULL,
    project_id text NOT NULL,
    callback_id text NOT NULL,
    attempt integer NOT NULL,
    input_spec_hash text NOT NULL,
    status text NOT NULL,
    outputs jsonb NOT NULL DEFAULT '[]'::jsonb,
    errors jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, job_id, callback_id),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.artifact (
    artifact_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    production_batch_id text NOT NULL,
    artifact_kind text NOT NULL,
    source_revision text NOT NULL,
    object_key text NOT NULL,
    sha256 text NOT NULL,
    status text NOT NULL CHECK (status IN ('draft', 'validated', 'release-candidate', 'published', 'superseded')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.external_action (
    action_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    action_kind text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL CHECK (status IN ('prepared', 'authorized', 'dispatched', 'confirmed', 'rejected', 'failed', 'unknown', 'reconciling', 'manual-resolution')),
    request_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    response_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_reconciled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id)
        REFERENCES rkd.project(organization_id, project_id)
);

CREATE INDEX IF NOT EXISTS idx_outbox_ready
    ON rkd.outbox_message (available_at, created_at)
    WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_workflow_project_status
    ON rkd.workflow_run (organization_id, project_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_executor_project_status
    ON rkd.executor_job (organization_id, project_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_audit_project_created
    ON rkd.audit_event (organization_id, project_id, created_at);

CREATE OR REPLACE FUNCTION rkd.current_organization() RETURNS text
LANGUAGE sql STABLE AS $$ SELECT current_setting('rkd.organization_id', true) $$;

CREATE OR REPLACE FUNCTION rkd.current_project() RETURNS text
LANGUAGE sql STABLE AS $$ SELECT current_setting('rkd.project_id', true) $$;

ALTER TABLE rkd.organization ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.project ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.project_member ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.command_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.aggregate_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.domain_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.outbox_message ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.inbox_message ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.dead_letter ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.workflow_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.workflow_activity ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.executor_job ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.executor_result ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.artifact ENABLE ROW LEVEL SECURITY;
ALTER TABLE rkd.external_action ENABLE ROW LEVEL SECURITY;

CREATE POLICY organization_tenant_isolation ON rkd.organization
    USING (organization_id = rkd.current_organization())
    WITH CHECK (organization_id = rkd.current_organization());

CREATE POLICY project_tenant_isolation ON rkd.project
    USING (organization_id = rkd.current_organization())
    WITH CHECK (organization_id = rkd.current_organization());

CREATE POLICY project_member_tenant_isolation ON rkd.project_member
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY command_tenant_isolation ON rkd.command_record
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY aggregate_tenant_isolation ON rkd.aggregate_state
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY event_tenant_isolation ON rkd.domain_event
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY outbox_tenant_isolation ON rkd.outbox_message
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY inbox_tenant_isolation ON rkd.inbox_message
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY dead_letter_tenant_isolation ON rkd.dead_letter
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY audit_tenant_isolation ON rkd.audit_event
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY workflow_tenant_isolation ON rkd.workflow_run
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY workflow_activity_tenant_isolation ON rkd.workflow_activity
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY executor_job_tenant_isolation ON rkd.executor_job
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY executor_result_tenant_isolation ON rkd.executor_result
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY artifact_tenant_isolation ON rkd.artifact
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE POLICY external_action_tenant_isolation ON rkd.external_action
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

CREATE OR REPLACE FUNCTION rkd.prevent_audit_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only';
END;
$$;

DROP TRIGGER IF EXISTS audit_event_append_only ON rkd.audit_event;
CREATE TRIGGER audit_event_append_only
    BEFORE UPDATE OR DELETE ON rkd.audit_event
    FOR EACH ROW EXECUTE FUNCTION rkd.prevent_audit_mutation();

COMMIT;
