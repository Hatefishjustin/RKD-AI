CREATE TABLE production_settings (
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    settings_json TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, project_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE TABLE production_revisions (
    production_revision_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    design_revision_id TEXT NOT NULL REFERENCES design_revisions(design_revision_id),
    settings_version INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    baseline_json TEXT NOT NULL,
    quantities_json TEXT NOT NULL,
    quote_json TEXT NOT NULL,
    procurement_json TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, revision_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE TABLE production_artifacts (
    artifact_id TEXT PRIMARY KEY,
    production_revision_id TEXT NOT NULL REFERENCES production_revisions(production_revision_id),
    artifact_kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    UNIQUE (production_revision_id, artifact_kind)
);
