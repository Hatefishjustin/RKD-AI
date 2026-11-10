"""Explicit estimate persistence statements; callers submit named operations only."""
from contextlib import contextmanager
from .models import TenantContext
from .file_repository import mapping
from .model_repository import canonical

SQLITE_QUERIES = {
    'insert_calculation': 'INSERT OR IGNORE INTO calculation_runs(calculation_run_id, organization_id, project_id, estimate_id, revision_no, formula_version, input_hash, result_json, warnings_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    'insert_revision': 'INSERT INTO estimate_revisions(estimate_id, revision_no, organization_id, project_id, source_kind, change_reason, actor_id, assumptions_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
    'copy_lines': 'INSERT INTO estimate_lines(estimate_id, revision_no, line_id, order_index, category, section_name, sequence_label, item_name, unit, quantity_text, main_material_unit_cost_text, auxiliary_unit_cost_text, labor_unit_cost_text, source_quantity_text, source_main_material_unit_cost_text, source_auxiliary_unit_cost_text, source_labor_unit_cost_text, source_amount_text, material_name, auxiliary_description, inclusion_status, exclusion_reason, source_scope_conflict, source_sheet, source_row, source_locator) SELECT estimate_id, ?, line_id, order_index, category, section_name, sequence_label, item_name, unit, quantity_text, main_material_unit_cost_text, auxiliary_unit_cost_text, labor_unit_cost_text, source_quantity_text, source_main_material_unit_cost_text, source_auxiliary_unit_cost_text, source_labor_unit_cost_text, source_amount_text, material_name, auxiliary_description, inclusion_status, exclusion_reason, source_scope_conflict, source_sheet, source_row, source_locator FROM estimate_lines WHERE estimate_id = ? AND revision_no = ?',
    'advance': 'UPDATE estimates SET current_revision_no = ?, updated_at = ? WHERE estimate_id = ?',
    'supersede': "UPDATE estimate_artifacts SET status = 'superseded' WHERE estimate_id = ?",
    'decisions': 'SELECT decision_key, value_json FROM project_decisions WHERE organization_id = ? AND project_id = ?',
    'insert_estimate': "INSERT INTO estimates(estimate_id, organization_id, project_id, name, currency, status, source_file_id, source_hash, source_summary_json, source_notes_json, current_revision_no, created_at, updated_at) VALUES (?, ?, ?, ?, 'CNY', 'working', ?, ?, ?, ?, 1, ?, ?)",
    'insert_initial_revision': "INSERT INTO estimate_revisions(estimate_id, revision_no, organization_id, project_id, source_kind, change_reason, actor_id, assumptions_json, created_at) VALUES (?, 1, ?, ?, 'source_import', ?, 'system', ?, ?)",
    'estimate': 'SELECT * FROM estimates WHERE estimate_id = ? AND organization_id = ? AND project_id = ?',
    'revision': 'SELECT * FROM estimate_revisions WHERE estimate_id = ? AND revision_no = ?',
    'lines': 'SELECT * FROM estimate_lines WHERE estimate_id = ? AND revision_no = ? ORDER BY order_index',
    'calculation': 'SELECT * FROM calculation_runs WHERE estimate_id = ? AND revision_no = ? AND input_hash = ?',
    'insert_artifact': "INSERT INTO estimate_artifacts(artifact_id, organization_id, project_id, estimate_id, revision_no, artifact_kind, filename, content_type, relative_path, sha256, size_bytes, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)",
    'by_source': 'SELECT estimate_id FROM estimates WHERE organization_id = ? AND project_id = ? AND source_hash = ?',
    'insert_line': 'INSERT INTO estimate_lines(estimate_id, revision_no, line_id, order_index, category, section_name, sequence_label, item_name, unit, quantity_text, main_material_unit_cost_text, auxiliary_unit_cost_text, labor_unit_cost_text, source_quantity_text, source_main_material_unit_cost_text, source_auxiliary_unit_cost_text, source_labor_unit_cost_text, source_amount_text, material_name, auxiliary_description, inclusion_status, exclusion_reason, source_scope_conflict, source_sheet, source_row, source_locator) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    'estimates': 'SELECT estimate_id, name, currency, status, current_revision_no, updated_at FROM estimates WHERE organization_id = ? AND project_id = ? ORDER BY updated_at DESC',
    'latest_calculation': 'SELECT * FROM calculation_runs WHERE estimate_id = ? AND revision_no = ? ORDER BY created_at DESC LIMIT 1',
    'line_exists': 'SELECT 1 FROM estimate_lines WHERE estimate_id = ? AND revision_no = ? AND line_id = ?',
    'artifacts': 'SELECT * FROM estimate_artifacts WHERE estimate_id = ? AND revision_no = ? ORDER BY artifact_kind',
    'artifact': 'SELECT * FROM estimate_artifacts WHERE artifact_id = ? AND organization_id = ? AND project_id = ?',
    'source_file': 'SELECT file_id FROM file_assets WHERE organization_id = ? AND project_id = ? AND source_ref = ?',
}

POSTGRES_QUERIES = {
    'insert_calculation': 'INSERT INTO rkd.calculation_run(calculation_run_id, organization_id, project_id, estimate_id, revision_no, formula_version, input_hash, result, warnings, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) ON CONFLICT (estimate_id,revision_no,input_hash) DO NOTHING',
    'insert_revision': 'INSERT INTO rkd.estimate_revision(estimate_id, revision_no, organization_id, project_id, source_kind, change_reason, actor_id, assumptions, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)',
    'copy_lines': 'INSERT INTO rkd.estimate_line(organization_id,project_id,estimate_id, revision_no, line_id, order_index, category, section_name, sequence_label, item_name, unit, quantity_text, main_material_unit_cost_text, auxiliary_unit_cost_text, labor_unit_cost_text, source_quantity_text, source_main_material_unit_cost_text, source_auxiliary_unit_cost_text, source_labor_unit_cost_text, source_amount_text, material_name, auxiliary_description, inclusion_status, exclusion_reason, source_scope_conflict, source_sheet, source_row, source_locator) SELECT organization_id,project_id,estimate_id, %s, line_id, order_index, category, section_name, sequence_label, item_name, unit, quantity_text, main_material_unit_cost_text, auxiliary_unit_cost_text, labor_unit_cost_text, source_quantity_text, source_main_material_unit_cost_text, source_auxiliary_unit_cost_text, source_labor_unit_cost_text, source_amount_text, material_name, auxiliary_description, inclusion_status, exclusion_reason, source_scope_conflict, source_sheet, source_row, source_locator FROM rkd.estimate_line WHERE estimate_id = %s AND revision_no = %s',
    'advance': 'UPDATE rkd.estimate SET current_revision_no = %s, updated_at = %s WHERE estimate_id = %s',
    'supersede': "UPDATE rkd.estimate_artifact SET status = 'superseded' WHERE estimate_id = %s",
    'decisions': 'SELECT decision_key, value::text AS value_json FROM rkd.project_decision WHERE organization_id = %s AND project_id = %s',
    'insert_estimate': "INSERT INTO rkd.estimate(estimate_id, organization_id, project_id, name, currency, status, source_file_id, source_hash, source_summary, source_notes, current_revision_no, created_at, updated_at) VALUES (%s, %s, %s, %s, 'CNY', 'working', %s, %s, %s::jsonb, %s::jsonb, 1, %s, %s)",
    'insert_initial_revision': "INSERT INTO rkd.estimate_revision(estimate_id, revision_no, organization_id, project_id, source_kind, change_reason, actor_id, assumptions, created_at) VALUES (%s, 1, %s, %s, 'source_import', %s, 'system', %s::jsonb, %s)",
    'estimate': 'SELECT *,source_summary::text AS source_summary_json,source_notes::text AS source_notes_json FROM rkd.estimate WHERE estimate_id = %s AND organization_id = %s AND project_id = %s',
    'revision': 'SELECT *,assumptions::text AS assumptions_json FROM rkd.estimate_revision WHERE estimate_id = %s AND revision_no = %s',
    'lines': 'SELECT * FROM rkd.estimate_line WHERE estimate_id = %s AND revision_no = %s ORDER BY order_index',
    'calculation': 'SELECT *,result::text AS result_json,warnings::text AS warnings_json FROM rkd.calculation_run WHERE estimate_id = %s AND revision_no = %s AND input_hash = %s',
    'insert_artifact': "INSERT INTO rkd.estimate_artifact(artifact_id, organization_id, project_id, estimate_id, revision_no, artifact_kind, filename, content_type, relative_path, sha256, size_bytes, status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s)",
    'by_source': 'SELECT estimate_id FROM rkd.estimate WHERE organization_id = %s AND project_id = %s AND source_hash = %s',
    'insert_line': 'INSERT INTO rkd.estimate_line(organization_id,project_id,estimate_id, revision_no, line_id, order_index, category, section_name, sequence_label, item_name, unit, quantity_text, main_material_unit_cost_text, auxiliary_unit_cost_text, labor_unit_cost_text, source_quantity_text, source_main_material_unit_cost_text, source_auxiliary_unit_cost_text, source_labor_unit_cost_text, source_amount_text, material_name, auxiliary_description, inclusion_status, exclusion_reason, source_scope_conflict, source_sheet, source_row, source_locator) VALUES (%s,%s,%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
    'estimates': 'SELECT estimate_id, name, currency, status, current_revision_no, updated_at FROM rkd.estimate WHERE organization_id = %s AND project_id = %s ORDER BY updated_at DESC',
    'latest_calculation': 'SELECT *,result::text AS result_json,warnings::text AS warnings_json FROM rkd.calculation_run WHERE estimate_id = %s AND revision_no = %s ORDER BY created_at DESC LIMIT 1',
    'line_exists': 'SELECT 1 FROM rkd.estimate_line WHERE estimate_id = %s AND revision_no = %s AND line_id = %s',
    'artifacts': 'SELECT * FROM rkd.estimate_artifact WHERE estimate_id = %s AND revision_no = %s ORDER BY artifact_kind',
    'artifact': 'SELECT * FROM rkd.estimate_artifact WHERE artifact_id = %s AND organization_id = %s AND project_id = %s',
    'source_file': 'SELECT file_id FROM rkd.file_asset WHERE organization_id = %s AND project_id = %s AND source_ref = %s',
}

EDITABLE_COLUMNS = {"quantity_text", "main_material_unit_cost_text", "auxiliary_unit_cost_text", "labor_unit_cost_text", "inclusion_status", "exclusion_reason"}


class EstimateRows:
    def __init__(self, cursor):
        self.items = canonical(mapping(cursor)) if cursor.description else []

    def fetchone(self):
        return self.items[0] if self.items else None

    def fetchall(self):
        return self.items


class SQLiteEstimateTransaction:
    def __init__(self, db, org, project):
        self.db, self.scope = db, (org, project)

    def query(self, operation, params=()):
        return self.db.execute(SQLITE_QUERIES[operation], params)

    def update_line(self, estimate, revision, line, updates):
        if not updates or not updates.keys() <= EDITABLE_COLUMNS:
            raise ValueError("unsupported estimate columns")
        assignments = ", ".join(f"{column}=?" for column in updates)
        self.db.execute(f"UPDATE estimate_lines SET {assignments} WHERE estimate_id=? AND revision_no=? AND line_id=?", (*updates.values(), estimate, revision, line))


class SQLiteEstimateRepository:
    def __init__(self, context):
        self.context = context

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.context() as db:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield SQLiteEstimateTransaction(db, org, project)


class PostgresEstimateTransaction:
    def __init__(self, db, org, project):
        self.db, self.scope = db, (org, project)

    def query(self, operation, params=()):
        if operation == "insert_line":
            # SQLite stores a 0/1 source-conflict marker; PG stores boolean.
            params = (*self.scope, *params[:21], bool(params[21]), *params[22:])
        return EstimateRows(self.db.execute(POSTGRES_QUERIES[operation], params))

    def update_line(self, estimate, revision, line, updates):
        if not updates or not updates.keys() <= EDITABLE_COLUMNS:
            raise ValueError("unsupported estimate columns")
        assignments = ", ".join(f"{column}=%s" for column in updates)
        self.db.execute(f"UPDATE rkd.estimate_line SET {assignments} WHERE organization_id=%s AND project_id=%s AND estimate_id=%s AND revision_no=%s AND line_id=%s", (*updates.values(), *self.scope, estimate, revision, line))


class PostgresEstimateRepository:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.store.tenant_transaction(TenantContext(org, project, "local-user")) as db:
            if write:
                db.execute("SELECT project_id FROM rkd.project WHERE organization_id=%s AND project_id=%s FOR UPDATE", (org, project))
            yield PostgresEstimateTransaction(db, org, project)
