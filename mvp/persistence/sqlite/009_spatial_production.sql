CREATE TABLE spatial_quotes (
    geometry_revision_id TEXT PRIMARY KEY REFERENCES geometry_revisions(geometry_revision_id),
    quote_revision_id TEXT NOT NULL UNIQUE,
    pricing_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE spatial_audit (
    audit_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    geometry_revision_id TEXT NOT NULL REFERENCES geometry_revisions(geometry_revision_id),
    actor_id TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
