CREATE TABLE IF NOT EXISTS estimate_artifacts (
    artifact_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    estimate_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    artifact_kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (estimate_id, revision_no, artifact_kind)
);
CREATE INDEX IF NOT EXISTS estimate_artifacts_project_created
ON estimate_artifacts(organization_id, project_id, created_at DESC);
