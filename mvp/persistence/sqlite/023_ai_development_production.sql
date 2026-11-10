CREATE TABLE ai_development_jobs (
    job_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    option_revision_id TEXT NOT NULL,
    adoption_version INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    phase TEXT NOT NULL CHECK(phase IN ('queued', 'geometry', 'measurement', 'pricing', 'outputs', 'completed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    settings_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    idempotency_key TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE INDEX ai_development_jobs_project_created
ON ai_development_jobs(organization_id, project_id, created_at DESC);

CREATE TABLE ai_development_revisions (
    production_revision_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES ai_development_jobs(job_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    option_revision_id TEXT NOT NULL,
    set_id TEXT NOT NULL,
    option_id TEXT NOT NULL,
    adoption_version INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    baseline_json TEXT NOT NULL,
    package_json TEXT NOT NULL,
    quantities_json TEXT NOT NULL,
    cost_json TEXT NOT NULL,
    objects_json TEXT NOT NULL,
    materials_json TEXT NOT NULL,
    unknowns_json TEXT NOT NULL,
    view_mapping_json TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    measurement_version TEXT NOT NULL,
    output_version TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (job_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE INDEX ai_development_revisions_project_created
ON ai_development_revisions(organization_id, project_id, created_at DESC);

CREATE TABLE ai_development_artifacts (
    artifact_id TEXT PRIMARY KEY,
    production_revision_id TEXT NOT NULL REFERENCES ai_development_revisions(production_revision_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL CHECK(artifact_kind IN ('plan_svg', 'isometric_svg', 'model_gltf', 'development_json', 'quantity_csv', 'cost_html', 'manifest_json', 'package_zip')),
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (production_revision_id, artifact_kind),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
