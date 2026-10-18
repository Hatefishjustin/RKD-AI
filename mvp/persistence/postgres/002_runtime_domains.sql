-- M5-02 runtime schema.  The first migration contains the durable kernel;
-- this migration mirrors the M1-M5 local runtime domains in PostgreSQL.

CREATE TABLE IF NOT EXISTS rkd.file_upload (
    upload_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    filename text NOT NULL,
    declared_size bigint NOT NULL CHECK (declared_size > 0),
    declared_sha256 text,
    received_sha256 text,
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.file_asset (
    file_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    filename text NOT NULL,
    kind text NOT NULL,
    content_type text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    sha256 text NOT NULL,
    storage_key text NOT NULL UNIQUE,
    source_kind text NOT NULL,
    source_ref text NOT NULL,
    format_status text NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id),
    UNIQUE (organization_id, project_id, filename, revision)
);
CREATE UNIQUE INDEX IF NOT EXISTS file_asset_seed_source
    ON rkd.file_asset (organization_id, project_id, source_ref)
    WHERE source_kind = 'seed_fixture';

CREATE TABLE IF NOT EXISTS rkd.project_decision (
    organization_id text NOT NULL,
    project_id text NOT NULL,
    decision_key text NOT NULL,
    value jsonb NOT NULL,
    source text NOT NULL,
    status text NOT NULL,
    source_conflict text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, decision_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.job (
    job_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    job_type text NOT NULL,
    status text NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    input_hash text NOT NULL,
    input_ref text NOT NULL,
    output jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code text,
    error_message text,
    lease_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, job_type, input_hash),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX IF NOT EXISTS job_project_updated ON rkd.job (organization_id, project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS rkd.job_attempt (
    job_id text NOT NULL REFERENCES rkd.job(job_id) ON DELETE CASCADE,
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    error_code text,
    error_message text,
    PRIMARY KEY (job_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS rkd.issue (
    issue_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    source_file_id text,
    source_ref text NOT NULL,
    source_locator text NOT NULL,
    issue_type text NOT NULL,
    severity text NOT NULL,
    title text NOT NULL,
    detail jsonb NOT NULL,
    disposition_status text NOT NULL DEFAULT 'open',
    disposition_reason text,
    disposition_actor_id text,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, issue_type, source_ref),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX IF NOT EXISTS issue_project_updated ON rkd.issue (organization_id, project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS rkd.issue_action (
    action_id text PRIMARY KEY,
    issue_id text NOT NULL REFERENCES rkd.issue(issue_id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    action text NOT NULL,
    reason text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.estimate (
    estimate_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    name text NOT NULL,
    currency text NOT NULL,
    status text NOT NULL,
    source_file_id text,
    source_hash text NOT NULL,
    source_summary jsonb NOT NULL,
    source_notes jsonb NOT NULL,
    current_revision_no integer NOT NULL CHECK (current_revision_no > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, source_hash),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX IF NOT EXISTS estimate_project_updated ON rkd.estimate (organization_id, project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS rkd.estimate_revision (
    estimate_id text NOT NULL REFERENCES rkd.estimate(estimate_id) ON DELETE CASCADE,
    revision_no integer NOT NULL CHECK (revision_no > 0),
    organization_id text NOT NULL,
    project_id text NOT NULL,
    source_kind text NOT NULL,
    change_reason text NOT NULL,
    actor_id text NOT NULL,
    assumptions jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (estimate_id, revision_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.estimate_line (
    estimate_id text NOT NULL,
    revision_no integer NOT NULL,
    line_id text NOT NULL,
    order_index integer NOT NULL,
    category text NOT NULL,
    section_name text NOT NULL,
    sequence_label text NOT NULL,
    item_name text NOT NULL,
    unit text NOT NULL,
    quantity_text text,
    main_material_unit_cost_text text,
    auxiliary_unit_cost_text text,
    labor_unit_cost_text text,
    source_quantity_text text,
    source_main_material_unit_cost_text text,
    source_auxiliary_unit_cost_text text,
    source_labor_unit_cost_text text,
    source_amount_text text,
    material_name text NOT NULL,
    auxiliary_description text NOT NULL,
    inclusion_status text NOT NULL,
    exclusion_reason text,
    source_scope_conflict boolean NOT NULL DEFAULT false,
    source_sheet text NOT NULL,
    source_row integer NOT NULL,
    source_locator text NOT NULL,
    PRIMARY KEY (estimate_id, revision_no, line_id),
    FOREIGN KEY (estimate_id, revision_no) REFERENCES rkd.estimate_revision(estimate_id, revision_no) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS estimate_line_revision_order ON rkd.estimate_line (estimate_id, revision_no, order_index);

CREATE TABLE IF NOT EXISTS rkd.calculation_run (
    calculation_run_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    estimate_id text NOT NULL,
    revision_no integer NOT NULL,
    formula_version text NOT NULL,
    input_hash text NOT NULL,
    result jsonb NOT NULL,
    warnings jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (estimate_id, revision_no, input_hash),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id),
    FOREIGN KEY (estimate_id, revision_no) REFERENCES rkd.estimate_revision(estimate_id, revision_no) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rkd.spatial_unit (
    spatial_unit_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    name text NOT NULL,
    unit_kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, spatial_unit_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.geometry_revision (
    geometry_revision_id text PRIMARY KEY,
    spatial_unit_id text NOT NULL REFERENCES rkd.spatial_unit(spatial_unit_id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    revision_no integer NOT NULL CHECK (revision_no > 0),
    width_text text NOT NULL,
    length_text text NOT NULL,
    deductions jsonb NOT NULL,
    area_m2_text text NOT NULL,
    input_hash text NOT NULL,
    source_kind text NOT NULL,
    change_reason text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (spatial_unit_id, revision_no),
    UNIQUE (spatial_unit_id, input_hash),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.quantity_item (
    quantity_item_id text PRIMARY KEY,
    geometry_revision_id text NOT NULL REFERENCES rkd.geometry_revision(geometry_revision_id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    item_kind text NOT NULL,
    description text NOT NULL,
    quantity_text text NOT NULL,
    unit text NOT NULL,
    formula text NOT NULL,
    source_status text NOT NULL,
    UNIQUE (geometry_revision_id, quantity_item_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.spatial_artifact (
    artifact_id text PRIMARY KEY,
    geometry_revision_id text NOT NULL REFERENCES rkd.geometry_revision(geometry_revision_id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    artifact_kind text NOT NULL,
    filename text NOT NULL,
    content_type text NOT NULL,
    relative_path text NOT NULL,
    sha256 text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (geometry_revision_id, artifact_kind),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.spatial_quote (
    geometry_revision_id text PRIMARY KEY REFERENCES rkd.geometry_revision(geometry_revision_id),
    quote_revision_id text NOT NULL UNIQUE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    pricing jsonb NOT NULL,
    result jsonb NOT NULL,
    formula_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.spatial_audit (
    audit_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    geometry_revision_id text NOT NULL REFERENCES rkd.geometry_revision(geometry_revision_id),
    actor_id text NOT NULL,
    change_reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.estimate_artifact (
    artifact_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    estimate_id text NOT NULL REFERENCES rkd.estimate(estimate_id),
    revision_no integer NOT NULL,
    artifact_kind text NOT NULL,
    filename text NOT NULL,
    content_type text NOT NULL,
    relative_path text NOT NULL,
    sha256 text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (estimate_id, revision_no, artifact_kind),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.requirement (
    requirement_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    current_revision_no integer NOT NULL CHECK (current_revision_no > 0),
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.requirement_revision (
    requirement_id text NOT NULL REFERENCES rkd.requirement(requirement_id) ON DELETE CASCADE,
    revision_no integer NOT NULL CHECK (revision_no > 0),
    organization_id text NOT NULL,
    project_id text NOT NULL,
    source_kind text NOT NULL,
    change_reason text NOT NULL,
    actor_id text NOT NULL,
    content jsonb NOT NULL,
    source_refs jsonb NOT NULL,
    input_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (requirement_id, revision_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.design_revision (
    design_revision_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    revision_no integer NOT NULL CHECK (revision_no > 0),
    requirement_id text NOT NULL,
    requirement_revision_no integer NOT NULL,
    requirement_hash text NOT NULL,
    input_hash text NOT NULL,
    model jsonb NOT NULL,
    validation jsonb NOT NULL,
    source_kind text NOT NULL,
    change_reason text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, revision_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id),
    FOREIGN KEY (requirement_id, requirement_revision_no) REFERENCES rkd.requirement_revision(requirement_id, revision_no)
);

CREATE TABLE IF NOT EXISTS rkd.design_artifact (
    artifact_id text PRIMARY KEY,
    design_revision_id text NOT NULL REFERENCES rkd.design_revision(design_revision_id),
    organization_id text NOT NULL,
    project_id text NOT NULL,
    artifact_kind text NOT NULL,
    filename text NOT NULL,
    content_type text NOT NULL,
    relative_path text NOT NULL,
    sha256 text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    UNIQUE (design_revision_id, artifact_kind),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.procurement_order (
    order_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    revision_no integer NOT NULL CHECK (revision_no > 0),
    status text NOT NULL CHECK (status IN ('draft', 'partially_received', 'received', 'partially_allocated', 'allocated', 'cancelled')),
    supplier_name text NOT NULL,
    delivery_location text NOT NULL,
    source_kind text NOT NULL,
    source_ref text NOT NULL,
    external_effects_enabled boolean NOT NULL DEFAULT false CHECK (external_effects_enabled = false),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, revision_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.procurement_order_line (
    line_id text PRIMARY KEY,
    order_id text NOT NULL REFERENCES rkd.procurement_order(order_id),
    item_code text NOT NULL,
    item_name text NOT NULL,
    specification text NOT NULL,
    ordered_quantity_text text NOT NULL,
    unit text NOT NULL,
    received_quantity_text text NOT NULL DEFAULT '0',
    allocated_quantity_text text NOT NULL DEFAULT '0',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rkd.material_receipt (
    receipt_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    order_id text NOT NULL REFERENCES rkd.procurement_order(order_id),
    receipt_no text NOT NULL,
    received_at timestamptz NOT NULL,
    receiver text NOT NULL,
    evidence_ref text NOT NULL,
    note text NOT NULL,
    idempotency_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.material_receipt_line (
    receipt_line_id text PRIMARY KEY,
    receipt_id text NOT NULL REFERENCES rkd.material_receipt(receipt_id),
    line_id text NOT NULL REFERENCES rkd.procurement_order_line(line_id),
    quantity_text text NOT NULL,
    unit text NOT NULL
);

CREATE TABLE IF NOT EXISTS rkd.material_allocation (
    allocation_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    order_id text NOT NULL REFERENCES rkd.procurement_order(order_id),
    line_id text NOT NULL REFERENCES rkd.procurement_order_line(line_id),
    quantity_text text NOT NULL,
    target_area text NOT NULL,
    recipient text NOT NULL,
    evidence_ref text NOT NULL,
    note text NOT NULL,
    idempotency_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.procurement_event (
    event_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    event_type text NOT NULL,
    aggregate_id text NOT NULL,
    idempotency_key text,
    payload jsonb NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.change_request (
    change_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    change_no integer NOT NULL CHECK (change_no > 0),
    issue_id text,
    title text NOT NULL,
    reason text NOT NULL,
    description text NOT NULL,
    status text NOT NULL CHECK (status IN ('draft', 'analyzed', 'accepted', 'rework', 'rejected')),
    design_revision_id text,
    geometry_revision_id text,
    baseline jsonb NOT NULL,
    proposal jsonb NOT NULL,
    impact jsonb NOT NULL DEFAULT '{}'::jsonb,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, change_no),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.change_artifact (
    artifact_id text PRIMARY KEY,
    change_id text NOT NULL REFERENCES rkd.change_request(change_id),
    organization_id text NOT NULL,
    project_id text NOT NULL,
    artifact_kind text NOT NULL,
    filename text NOT NULL,
    content_type text NOT NULL,
    relative_path text NOT NULL,
    sha256 text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (change_id, artifact_kind),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.change_acceptance (
    acceptance_id text PRIMARY KEY,
    change_id text NOT NULL REFERENCES rkd.change_request(change_id),
    organization_id text NOT NULL,
    project_id text NOT NULL,
    conclusion text NOT NULL CHECK (conclusion IN ('accepted', 'rework', 'rejected', 'unknown')),
    checklist jsonb NOT NULL,
    evidence_ref text NOT NULL,
    note text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.change_event (
    event_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    change_id text NOT NULL REFERENCES rkd.change_request(change_id),
    event_type text NOT NULL,
    idempotency_key text NOT NULL,
    request_hash text NOT NULL,
    payload jsonb NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE TABLE IF NOT EXISTS rkd.auth_user (
    user_id text PRIMARY KEY,
    organization_id text NOT NULL,
    username text NOT NULL UNIQUE,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    is_admin boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, user_id),
    FOREIGN KEY (organization_id) REFERENCES rkd.organization(organization_id)
);

CREATE TABLE IF NOT EXISTS rkd.auth_membership (
    organization_id text NOT NULL,
    project_id text NOT NULL,
    user_id text NOT NULL,
    role text NOT NULL CHECK (role IN ('manager', 'editor', 'viewer')),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, project_id, user_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id),
    FOREIGN KEY (organization_id, user_id) REFERENCES rkd.auth_user(organization_id, user_id)
);

CREATE TABLE IF NOT EXISTS rkd.auth_session (
    token_hash text PRIMARY KEY,
    user_id text NOT NULL REFERENCES rkd.auth_user(user_id),
    csrf_token text NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_session_user ON rkd.auth_session(user_id);

CREATE TABLE IF NOT EXISTS rkd.auth_login_limit (
    bucket text PRIMARY KEY,
    failures integer NOT NULL CHECK (failures >= 0),
    window_started_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS rkd.auth_audit (
    audit_id text PRIMARY KEY,
    actor_id text NOT NULL,
    organization_id text NOT NULL,
    project_id text,
    action text NOT NULL,
    target_id text NOT NULL,
    details jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (organization_id) REFERENCES rkd.organization(organization_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);

CREATE INDEX IF NOT EXISTS procurement_order_project_idx ON rkd.procurement_order (organization_id, project_id, revision_no);
CREATE INDEX IF NOT EXISTS material_receipt_order_idx ON rkd.material_receipt (order_id, created_at);
CREATE INDEX IF NOT EXISTS material_allocation_order_idx ON rkd.material_allocation (order_id, created_at);
CREATE INDEX IF NOT EXISTS change_project_idx ON rkd.change_request (organization_id, project_id, change_no);
CREATE INDEX IF NOT EXISTS change_acceptance_idx ON rkd.change_acceptance (change_id, created_at);

-- Every project-scoped runtime table is protected by the same request context.
DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'file_upload', 'file_asset', 'project_decision', 'job', 'issue', 'issue_action',
        'estimate', 'estimate_revision', 'calculation_run', 'spatial_unit', 'geometry_revision',
        'quantity_item', 'spatial_artifact', 'spatial_quote', 'spatial_audit', 'estimate_artifact',
        'requirement', 'requirement_revision', 'design_revision', 'design_artifact',
        'procurement_order', 'material_receipt', 'material_allocation', 'procurement_event',
        'change_request', 'change_artifact', 'change_acceptance', 'change_event', 'auth_membership',
        'auth_audit'
    ] LOOP
        EXECUTE format('ALTER TABLE rkd.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY %I ON rkd.%I USING (organization_id = rkd.current_organization() AND (project_id IS NULL OR project_id = rkd.current_project())) WITH CHECK (organization_id = rkd.current_organization() AND (project_id IS NULL OR project_id = rkd.current_project()))',
            table_name || '_tenant_isolation', table_name
        );
    END LOOP;
END $$;

ALTER TABLE rkd.auth_user ENABLE ROW LEVEL SECURITY;
CREATE POLICY auth_user_tenant_isolation ON rkd.auth_user
    USING (organization_id = rkd.current_organization())
    WITH CHECK (organization_id = rkd.current_organization());

ALTER TABLE rkd.auth_session ENABLE ROW LEVEL SECURITY;
CREATE POLICY auth_session_tenant_isolation ON rkd.auth_session
    USING (EXISTS (SELECT 1 FROM rkd.auth_user u WHERE u.user_id = auth_session.user_id AND u.organization_id = rkd.current_organization()))
    WITH CHECK (EXISTS (SELECT 1 FROM rkd.auth_user u WHERE u.user_id = auth_session.user_id AND u.organization_id = rkd.current_organization()));

ALTER TABLE rkd.auth_login_limit ENABLE ROW LEVEL SECURITY;
CREATE POLICY auth_login_limit_service_only ON rkd.auth_login_limit
    USING (false) WITH CHECK (false);

CREATE OR REPLACE FUNCTION rkd.prevent_auth_audit_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'auth_audit is append-only';
END;
$$;
DROP TRIGGER IF EXISTS auth_audit_append_only ON rkd.auth_audit;
CREATE TRIGGER auth_audit_append_only
    BEFORE UPDATE OR DELETE ON rkd.auth_audit
    FOR EACH ROW EXECUTE FUNCTION rkd.prevent_auth_audit_mutation();
