CREATE TABLE IF NOT EXISTS requirements (
    requirement_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    current_revision_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS requirement_revisions (
    requirement_id TEXT NOT NULL REFERENCES requirements(requirement_id) ON DELETE CASCADE,
    revision_no INTEGER NOT NULL,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    content_json TEXT NOT NULL,
    source_refs_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (requirement_id, revision_no)
);

CREATE INDEX IF NOT EXISTS requirement_revisions_project_created
ON requirement_revisions(organization_id, project_id, created_at DESC);
