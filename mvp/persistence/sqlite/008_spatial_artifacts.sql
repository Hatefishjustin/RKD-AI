CREATE TABLE IF NOT EXISTS spatial_artifacts (
    artifact_id TEXT PRIMARY KEY,
    geometry_revision_id TEXT NOT NULL REFERENCES geometry_revisions(geometry_revision_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (geometry_revision_id, artifact_kind)
);

CREATE INDEX IF NOT EXISTS spatial_artifacts_project_created
ON spatial_artifacts(organization_id, project_id, created_at DESC);
