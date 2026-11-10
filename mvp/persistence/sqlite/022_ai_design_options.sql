CREATE TABLE ai_design_option_sets (
    set_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    brief_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    phase TEXT NOT NULL CHECK(phase IN ('queued', 'strategy', 'geometry', 'validation', 'outputs', 'completed', 'configuration_failed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,
    context_json TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    idempotency_key TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE INDEX ai_design_option_sets_project_created
ON ai_design_option_sets(organization_id, project_id, created_at DESC);

CREATE TABLE ai_design_option_revisions (
    option_revision_id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL REFERENCES ai_design_option_sets(set_id) ON DELETE CASCADE,
    option_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    parent_revision_id TEXT,
    strategy_id TEXT NOT NULL,
    strategy_json TEXT NOT NULL,
    model_json TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    materials_json TEXT NOT NULL,
    cost_json TEXT NOT NULL,
    feedback_json TEXT NOT NULL,
    diff_json TEXT NOT NULL,
    conflicts_json TEXT NOT NULL,
    structure_signature_json TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('candidate', 'adopted_draft', 'superseded', 'rejected')),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('synthetic_design_adapter', 'real_model', 'human_feedback', 'human_edit')),
    change_reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (option_id, revision_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE INDEX ai_design_option_revisions_set_created
ON ai_design_option_revisions(set_id, created_at DESC);

CREATE TABLE ai_design_option_adoptions (
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    option_revision_id TEXT NOT NULL REFERENCES ai_design_option_revisions(option_revision_id),
    set_id TEXT NOT NULL,
    option_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    expected_revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('adopted_draft', 'superseded')),
    production_task_status TEXT NOT NULL CHECK(production_task_status IN ('not_started', 'queued', 'succeeded', 'failed')),
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, project_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);

CREATE TABLE ai_design_option_artifacts (
    artifact_id TEXT PRIMARY KEY,
    option_revision_id TEXT NOT NULL REFERENCES ai_design_option_revisions(option_revision_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL CHECK(artifact_kind = 'layout_svg'),
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (option_revision_id, artifact_kind),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
