CREATE TABLE rkd.ai_design_option_set (
    set_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    brief_id text NOT NULL,
    input_hash text NOT NULL,
    status text NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    phase text NOT NULL CHECK(phase IN ('queued', 'strategy', 'geometry', 'validation', 'outputs', 'completed', 'configuration_failed', 'failed')),
    attempt_count integer NOT NULL DEFAULT 0,
    config jsonb NOT NULL,
    context jsonb NOT NULL,
    error_code text,
    error_message text,
    idempotency_key text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX ai_design_option_set_project_created
ON rkd.ai_design_option_set(organization_id, project_id, created_at DESC);
ALTER TABLE rkd.ai_design_option_set ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_design_option_set_scope ON rkd.ai_design_option_set
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());

CREATE TABLE rkd.ai_design_option_revision (
    option_revision_id text PRIMARY KEY,
    set_id text NOT NULL REFERENCES rkd.ai_design_option_set(set_id) ON DELETE CASCADE,
    option_id text NOT NULL,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    revision_no integer NOT NULL,
    parent_revision_id text,
    strategy_id text NOT NULL,
    strategy jsonb NOT NULL,
    model jsonb NOT NULL,
    validation jsonb NOT NULL,
    materials jsonb NOT NULL,
    cost jsonb NOT NULL,
    feedback jsonb NOT NULL,
    diff jsonb NOT NULL,
    conflicts jsonb NOT NULL,
    structure_signature jsonb NOT NULL,
    lifecycle_status text NOT NULL CHECK(lifecycle_status IN ('candidate', 'adopted_draft', 'superseded', 'rejected')),
    source_kind text NOT NULL CHECK(source_kind IN ('synthetic_design_adapter', 'real_model', 'human_feedback', 'human_edit')),
    change_reason text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (option_id, revision_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX ai_design_option_revision_set_created
ON rkd.ai_design_option_revision(set_id, created_at DESC);
ALTER TABLE rkd.ai_design_option_revision ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_design_option_revision_scope ON rkd.ai_design_option_revision
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());

CREATE TABLE rkd.ai_design_option_adoption (
    organization_id text NOT NULL,
    project_id text NOT NULL,
    option_revision_id text NOT NULL REFERENCES rkd.ai_design_option_revision(option_revision_id),
    set_id text NOT NULL,
    option_id text NOT NULL,
    revision_no integer NOT NULL,
    expected_revision integer NOT NULL,
    status text NOT NULL CHECK(status IN ('adopted_draft', 'superseded')),
    production_task_status text NOT NULL CHECK(production_task_status IN ('not_started', 'queued', 'succeeded', 'failed')),
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (organization_id, project_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
ALTER TABLE rkd.ai_design_option_adoption ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_design_option_adoption_scope ON rkd.ai_design_option_adoption
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());

CREATE TABLE rkd.ai_design_option_artifact (
    artifact_id text PRIMARY KEY,
    option_revision_id text NOT NULL REFERENCES rkd.ai_design_option_revision(option_revision_id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    artifact_kind text NOT NULL CHECK(artifact_kind = 'layout_svg'),
    filename text NOT NULL,
    content_type text NOT NULL,
    relative_path text NOT NULL,
    sha256 text NOT NULL,
    size_bytes integer NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (option_revision_id, artifact_kind),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
ALTER TABLE rkd.ai_design_option_artifact ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_design_option_artifact_scope ON rkd.ai_design_option_artifact
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());
