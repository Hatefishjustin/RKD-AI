CREATE TABLE rkd.ai_development_job (
    job_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    option_revision_id text NOT NULL,
    adoption_version integer NOT NULL,
    input_hash text NOT NULL,
    status text NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    phase text NOT NULL CHECK(phase IN ('queued', 'geometry', 'measurement', 'pricing', 'outputs', 'completed', 'failed')),
    attempt_count integer NOT NULL DEFAULT 0,
    settings jsonb NOT NULL,
    config jsonb NOT NULL,
    error_code text,
    error_message text,
    idempotency_key text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX ai_development_job_project_created
ON rkd.ai_development_job(organization_id, project_id, created_at DESC);
ALTER TABLE rkd.ai_development_job ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_development_job_scope ON rkd.ai_development_job
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());

CREATE TABLE rkd.ai_development_revision (
    production_revision_id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES rkd.ai_development_job(job_id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    option_revision_id text NOT NULL,
    set_id text NOT NULL,
    option_id text NOT NULL,
    adoption_version integer NOT NULL,
    input_hash text NOT NULL,
    baseline jsonb NOT NULL,
    package jsonb NOT NULL,
    quantities jsonb NOT NULL,
    cost jsonb NOT NULL,
    objects jsonb NOT NULL,
    materials jsonb NOT NULL,
    unknowns jsonb NOT NULL,
    view_mapping jsonb NOT NULL,
    formula_version text NOT NULL,
    measurement_version text NOT NULL,
    output_version text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (job_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX ai_development_revision_project_created
ON rkd.ai_development_revision(organization_id, project_id, created_at DESC);
ALTER TABLE rkd.ai_development_revision ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_development_revision_scope ON rkd.ai_development_revision
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());

CREATE TABLE rkd.ai_development_artifact (
    artifact_id text PRIMARY KEY,
    production_revision_id text NOT NULL REFERENCES rkd.ai_development_revision(production_revision_id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    artifact_kind text NOT NULL CHECK(artifact_kind IN ('plan_svg', 'isometric_svg', 'model_gltf', 'development_json', 'quantity_csv', 'cost_html', 'manifest_json', 'package_zip')),
    filename text NOT NULL,
    content_type text NOT NULL,
    relative_path text NOT NULL,
    sha256 text NOT NULL,
    size_bytes integer NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (production_revision_id, artifact_kind),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
ALTER TABLE rkd.ai_development_artifact ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_development_artifact_scope ON rkd.ai_development_artifact
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());
