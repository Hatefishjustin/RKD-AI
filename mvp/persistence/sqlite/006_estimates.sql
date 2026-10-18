CREATE TABLE IF NOT EXISTS estimates (
    estimate_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    source_file_id TEXT,
    source_hash TEXT NOT NULL,
    source_summary_json TEXT NOT NULL,
    source_notes_json TEXT NOT NULL,
    current_revision_no INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, source_hash)
);

CREATE INDEX IF NOT EXISTS estimates_project_updated
ON estimates(organization_id, project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS estimate_revisions (
    estimate_id TEXT NOT NULL REFERENCES estimates(estimate_id) ON DELETE CASCADE,
    revision_no INTEGER NOT NULL,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (estimate_id, revision_no)
);

CREATE TABLE IF NOT EXISTS estimate_lines (
    estimate_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    line_id TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    category TEXT NOT NULL,
    section_name TEXT NOT NULL,
    sequence_label TEXT NOT NULL,
    item_name TEXT NOT NULL,
    unit TEXT NOT NULL,
    quantity_text TEXT,
    main_material_unit_cost_text TEXT,
    auxiliary_unit_cost_text TEXT,
    labor_unit_cost_text TEXT,
    source_quantity_text TEXT,
    source_main_material_unit_cost_text TEXT,
    source_auxiliary_unit_cost_text TEXT,
    source_labor_unit_cost_text TEXT,
    source_amount_text TEXT,
    material_name TEXT NOT NULL,
    auxiliary_description TEXT NOT NULL,
    inclusion_status TEXT NOT NULL,
    exclusion_reason TEXT,
    source_scope_conflict INTEGER NOT NULL DEFAULT 0,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    source_locator TEXT NOT NULL,
    PRIMARY KEY (estimate_id, revision_no, line_id),
    FOREIGN KEY (estimate_id, revision_no)
        REFERENCES estimate_revisions(estimate_id, revision_no) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS estimate_lines_revision_order
ON estimate_lines(estimate_id, revision_no, order_index);

CREATE TABLE IF NOT EXISTS calculation_runs (
    calculation_run_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    estimate_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    formula_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (estimate_id, revision_no)
        REFERENCES estimate_revisions(estimate_id, revision_no) ON DELETE CASCADE,
    UNIQUE (estimate_id, revision_no, input_hash)
);

CREATE INDEX IF NOT EXISTS calculation_runs_estimate_revision
ON calculation_runs(estimate_id, revision_no, created_at DESC);
