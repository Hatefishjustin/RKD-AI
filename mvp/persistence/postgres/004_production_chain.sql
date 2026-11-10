CREATE TABLE rkd.production_settings (
    organization_id text NOT NULL,
    project_id text NOT NULL,
    version bigint NOT NULL,
    settings jsonb NOT NULL,
    actor_id text NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (organization_id, project_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE TABLE rkd.production_revision (
    production_revision_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    revision_no bigint NOT NULL,
    design_revision_id text NOT NULL,
    settings_version bigint NOT NULL,
    input_hash text NOT NULL,
    baseline jsonb NOT NULL,
    quantities jsonb NOT NULL,
    quote jsonb NOT NULL,
    procurement jsonb NOT NULL,
    settings jsonb NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (organization_id, project_id, revision_no),
    UNIQUE (organization_id, project_id, production_revision_id),
    FOREIGN KEY (organization_id, project_id, design_revision_id)
        REFERENCES rkd.design_revision(organization_id, project_id, design_revision_id)
);
CREATE TABLE rkd.production_artifact (
    artifact_id text PRIMARY KEY,
    production_revision_id text NOT NULL,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    artifact_kind text NOT NULL,
    filename text NOT NULL,
    content_type text NOT NULL,
    relative_path text NOT NULL,
    sha256 text NOT NULL,
    size_bytes bigint NOT NULL,
    UNIQUE (production_revision_id, artifact_kind),
    FOREIGN KEY (organization_id, project_id, production_revision_id)
        REFERENCES rkd.production_revision(organization_id, project_id, production_revision_id)
);
DO $$
DECLARE item text;
BEGIN
    FOREACH item IN ARRAY ARRAY['production_settings', 'production_revision', 'production_artifact'] LOOP
        EXECUTE format('ALTER TABLE rkd.%I ENABLE ROW LEVEL SECURITY', item);
        EXECUTE format('CREATE POLICY tenant_isolation ON rkd.%I USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project()) WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project())', item);
    END LOOP;
END $$;
