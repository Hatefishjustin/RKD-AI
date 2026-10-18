CREATE TABLE design_revisions (
    design_revision_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    requirement_id TEXT NOT NULL,
    requirement_revision_no INTEGER NOT NULL,
    requirement_hash TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    model_json TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, revision_no),
    FOREIGN KEY (requirement_id, requirement_revision_no)
        REFERENCES requirement_revisions(requirement_id, revision_no)
);
CREATE TABLE design_artifacts (
    artifact_id TEXT PRIMARY KEY,
    design_revision_id TEXT NOT NULL REFERENCES design_revisions(design_revision_id),
    artifact_kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    UNIQUE (design_revision_id, artifact_kind)
);
