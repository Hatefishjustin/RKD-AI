CREATE TABLE change_requests (
    change_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    change_no INTEGER NOT NULL,
    issue_id TEXT,
    title TEXT NOT NULL,
    reason TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'analyzed', 'accepted', 'rework', 'rejected')),
    design_revision_id TEXT,
    geometry_revision_id TEXT,
    baseline_json TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    impact_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, change_no)
);

CREATE TABLE change_artifacts (
    artifact_id TEXT PRIMARY KEY,
    change_id TEXT NOT NULL REFERENCES change_requests(change_id),
    artifact_kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (change_id, artifact_kind)
);

CREATE TABLE change_acceptances (
    acceptance_id TEXT PRIMARY KEY,
    change_id TEXT NOT NULL REFERENCES change_requests(change_id),
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    conclusion TEXT NOT NULL CHECK (conclusion IN ('accepted', 'rework', 'rejected', 'unknown')),
    checklist_json TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    note TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE change_events (
    event_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    change_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key)
);

CREATE INDEX change_project_idx ON change_requests (organization_id, project_id, change_no);
CREATE INDEX change_artifact_idx ON change_artifacts (change_id, artifact_kind);
CREATE INDEX change_acceptance_idx ON change_acceptances (change_id, created_at);
