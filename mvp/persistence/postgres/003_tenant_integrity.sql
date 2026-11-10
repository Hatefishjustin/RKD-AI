-- Complete the tenant boundary before any runtime data is imported.
ALTER TABLE rkd.project ADD COLUMN version bigint NOT NULL DEFAULT 0 CHECK (version >= 0);
DROP POLICY project_tenant_isolation ON rkd.project;
CREATE POLICY project_tenant_isolation ON rkd.project
    USING (organization_id = rkd.current_organization() AND project_id = rkd.current_project())
    WITH CHECK (organization_id = rkd.current_organization() AND project_id = rkd.current_project());

ALTER TABLE rkd.command_record ADD COLUMN request_hash text NOT NULL DEFAULT '';
ALTER TABLE rkd.command_record DROP CONSTRAINT command_record_organization_id_project_id_idempotency_key_key;
ALTER TABLE rkd.command_record ADD CONSTRAINT command_scope_key
    UNIQUE (organization_id, project_id, command_name, idempotency_key);

-- Local child tables used globally unique IDs.  PostgreSQL children must also
-- carry scope, so a guessed parent ID can never attach another tenant's data.
DO $$
DECLARE
    item record;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('job_attempt', 'job', 'job_id'),
        ('estimate_line', 'estimate_revision', 'estimate_id'),
        ('procurement_order_line', 'procurement_order', 'order_id'),
        ('material_receipt_line', 'material_receipt', 'receipt_id')
    ) AS links(child_table, parent_table, parent_id)
    LOOP
        EXECUTE format('ALTER TABLE rkd.%I ADD COLUMN organization_id text, ADD COLUMN project_id text', item.child_table);
        EXECUTE format('UPDATE rkd.%I c SET organization_id=p.organization_id, project_id=p.project_id FROM rkd.%I p WHERE c.%I=p.%I', item.child_table, item.parent_table, item.parent_id, item.parent_id);
        EXECUTE format('ALTER TABLE rkd.%I ALTER COLUMN organization_id SET NOT NULL, ALTER COLUMN project_id SET NOT NULL', item.child_table);
        EXECUTE format('ALTER TABLE rkd.%I ENABLE ROW LEVEL SECURITY', item.child_table);
        EXECUTE format('CREATE POLICY tenant_isolation ON rkd.%I USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project()) WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project())', item.child_table);
    END LOOP;
END $$;

DO $$
DECLARE
    item record;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('job_attempt', 'job', 'job_id'),
        ('issue_action', 'issue', 'issue_id'),
        ('estimate_revision', 'estimate', 'estimate_id'),
        ('geometry_revision', 'spatial_unit', 'spatial_unit_id'),
        ('quantity_item', 'geometry_revision', 'geometry_revision_id'),
        ('spatial_artifact', 'geometry_revision', 'geometry_revision_id'),
        ('spatial_quote', 'geometry_revision', 'geometry_revision_id'),
        ('spatial_audit', 'geometry_revision', 'geometry_revision_id'),
        ('requirement_revision', 'requirement', 'requirement_id'),
        ('design_artifact', 'design_revision', 'design_revision_id'),
        ('procurement_order_line', 'procurement_order', 'order_id'),
        ('material_receipt', 'procurement_order', 'order_id'),
        ('material_receipt_line', 'material_receipt', 'receipt_id'),
        ('material_receipt_line', 'procurement_order_line', 'line_id'),
        ('material_allocation', 'procurement_order', 'order_id'),
        ('material_allocation', 'procurement_order_line', 'line_id'),
        ('change_artifact', 'change_request', 'change_id'),
        ('change_acceptance', 'change_request', 'change_id'),
        ('change_event', 'change_request', 'change_id'),
        ('workflow_activity', 'workflow_run', 'workflow_run_id'),
        ('executor_result', 'executor_job', 'job_id')
    ) AS links(child_table, parent_table, parent_id)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname=item.parent_table || '_scope_identity' AND conrelid=('rkd.' || item.parent_table)::regclass) THEN
            EXECUTE format('ALTER TABLE rkd.%I ADD CONSTRAINT %I UNIQUE (organization_id, project_id, %I)', item.parent_table, item.parent_table || '_scope_identity', item.parent_id);
        END IF;
        EXECUTE format('ALTER TABLE rkd.%I ADD CONSTRAINT %I FOREIGN KEY (organization_id, project_id, %I) REFERENCES rkd.%I (organization_id, project_id, %I)', item.child_table, item.child_table || '_' || item.parent_id || '_scope_fk', item.parent_id, item.parent_table, item.parent_id);
    END LOOP;
END $$;

ALTER TABLE rkd.estimate_revision ADD CONSTRAINT estimate_revision_scope_version
    UNIQUE (organization_id, project_id, estimate_id, revision_no);
ALTER TABLE rkd.estimate_line ADD CONSTRAINT estimate_line_scope_version_fk
    FOREIGN KEY (organization_id, project_id, estimate_id, revision_no)
    REFERENCES rkd.estimate_revision(organization_id, project_id, estimate_id, revision_no);
ALTER TABLE rkd.calculation_run ADD CONSTRAINT calculation_scope_version_fk
    FOREIGN KEY (organization_id, project_id, estimate_id, revision_no)
    REFERENCES rkd.estimate_revision(organization_id, project_id, estimate_id, revision_no);
ALTER TABLE rkd.estimate_artifact ADD CONSTRAINT estimate_artifact_scope_version_fk
    FOREIGN KEY (organization_id, project_id, estimate_id, revision_no)
    REFERENCES rkd.estimate_revision(organization_id, project_id, estimate_id, revision_no);
ALTER TABLE rkd.requirement_revision ADD CONSTRAINT requirement_revision_scope_version
    UNIQUE (organization_id, project_id, requirement_id, revision_no);
ALTER TABLE rkd.design_revision ADD CONSTRAINT design_requirement_scope_version_fk
    FOREIGN KEY (organization_id, project_id, requirement_id, requirement_revision_no)
    REFERENCES rkd.requirement_revision(organization_id, project_id, requirement_id, revision_no);

-- Rows whose identity includes both an order and a line/receipt must agree on
-- the order as well as the tenant.
ALTER TABLE rkd.procurement_order_line ADD CONSTRAINT order_line_identity
    UNIQUE (organization_id, project_id, order_id, line_id);
ALTER TABLE rkd.material_allocation ADD CONSTRAINT allocation_order_line_fk
    FOREIGN KEY (organization_id, project_id, order_id, line_id)
    REFERENCES rkd.procurement_order_line(organization_id, project_id, order_id, line_id);
ALTER TABLE rkd.material_receipt ADD CONSTRAINT receipt_order_identity
    UNIQUE (organization_id, project_id, order_id, receipt_id);
ALTER TABLE rkd.material_receipt_line ADD COLUMN order_id text;
UPDATE rkd.material_receipt_line l SET order_id=r.order_id FROM rkd.material_receipt r WHERE r.receipt_id=l.receipt_id;
ALTER TABLE rkd.material_receipt_line ALTER COLUMN order_id SET NOT NULL;
ALTER TABLE rkd.material_receipt_line ADD CONSTRAINT receipt_line_order_fk
    FOREIGN KEY (organization_id, project_id, order_id, receipt_id)
    REFERENCES rkd.material_receipt(organization_id, project_id, order_id, receipt_id);
ALTER TABLE rkd.material_receipt_line ADD CONSTRAINT receipt_line_order_line_fk
    FOREIGN KEY (organization_id, project_id, order_id, line_id)
    REFERENCES rkd.procurement_order_line(organization_id, project_id, order_id, line_id);

CREATE INDEX IF NOT EXISTS calculation_revision_idx ON rkd.calculation_run(organization_id, project_id, estimate_id, revision_no, created_at DESC);
CREATE INDEX IF NOT EXISTS geometry_revision_idx ON rkd.geometry_revision(organization_id, project_id, spatial_unit_id, revision_no DESC);
