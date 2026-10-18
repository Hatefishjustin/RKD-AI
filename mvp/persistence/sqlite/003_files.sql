CREATE TABLE IF NOT EXISTS file_uploads (
    upload_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    declared_size INTEGER NOT NULL CHECK (declared_size > 0),
    declared_sha256 TEXT,
    received_sha256 TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS file_assets (
    file_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    kind TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    sha256 TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    format_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS file_assets_seed_source
ON file_assets(organization_id, project_id, source_ref) WHERE source_kind = 'seed_fixture';

CREATE TABLE IF NOT EXISTS project_decisions (
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    decision_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    source_conflict TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, project_id, decision_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
