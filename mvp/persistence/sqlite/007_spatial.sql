CREATE TABLE IF NOT EXISTS spatial_units (
    spatial_unit_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    unit_kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, spatial_unit_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS geometry_revisions (
    geometry_revision_id TEXT PRIMARY KEY,
    spatial_unit_id TEXT NOT NULL REFERENCES spatial_units(spatial_unit_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    width_text TEXT NOT NULL,
    length_text TEXT NOT NULL,
    deductions_json TEXT NOT NULL,
    area_m2_text TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (spatial_unit_id, revision_no),
    UNIQUE (spatial_unit_id, input_hash)
);

CREATE TABLE IF NOT EXISTS quantity_items (
    quantity_item_id TEXT PRIMARY KEY,
    geometry_revision_id TEXT NOT NULL REFERENCES geometry_revisions(geometry_revision_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity_text TEXT NOT NULL,
    unit TEXT NOT NULL,
    formula TEXT NOT NULL,
    source_status TEXT NOT NULL,
    UNIQUE (geometry_revision_id, quantity_item_id)
);

CREATE INDEX IF NOT EXISTS geometry_revisions_project_revision
ON geometry_revisions(organization_id, project_id, spatial_unit_id, revision_no DESC);
