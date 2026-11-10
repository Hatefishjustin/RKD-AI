"""Explicit parameter-geometry persistence; no SQL translation or fallback."""
from contextlib import contextmanager
import sqlite3
from .models import TenantContext
from .file_repository import mapping
from .model_repository import canonical

class SpatialUnitConflict(Exception):
    pass

SQLITE_QUERIES = {
    'insert_artifact': "INSERT INTO spatial_artifacts(artifact_id, geometry_revision_id, organization_id, project_id, artifact_kind, filename, content_type, relative_path, sha256, size_bytes, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)",
    'supersede': "UPDATE spatial_artifacts SET status = 'superseded' WHERE organization_id = ? AND project_id = ? AND geometry_revision_id IN (SELECT geometry_revision_id FROM geometry_revisions WHERE spatial_unit_id = ?)",
    'insert_revision': "INSERT INTO geometry_revisions(geometry_revision_id, spatial_unit_id, organization_id, project_id, revision_no, width_text, length_text, deductions_json, area_m2_text, input_hash, source_kind, change_reason, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'parameter_input', ?, ?, ?)",
    'insert_quantity': "INSERT INTO quantity_items(quantity_item_id, geometry_revision_id, organization_id, project_id, item_kind, description, quantity_text, unit, formula, source_status) VALUES (?, ?, ?, ?, 'floor_area', '参数地坪净面积', ?, 'm²', '外框宽度 × 外框长度 − 扣除区面积', 'verified_by_deterministic_calculation')",
    'insert_quote': 'INSERT INTO spatial_quotes(geometry_revision_id, quote_revision_id, pricing_json, result_json, formula_version, created_at) VALUES (?, ?, ?, ?, ?, ?)',
    'unit': 'SELECT * FROM spatial_units WHERE spatial_unit_id = ? AND organization_id = ? AND project_id = ?',
    'quantity': 'SELECT * FROM quantity_items WHERE geometry_revision_id = ?',
    'quote': 'SELECT * FROM spatial_quotes WHERE geometry_revision_id = ?',
    'insert_unit': "INSERT INTO spatial_units(spatial_unit_id, organization_id, project_id, name, unit_kind, created_at) VALUES (?, ?, ?, ?, 'floor_area', ?)",
    'quantity_id': 'SELECT quantity_item_id FROM quantity_items WHERE geometry_revision_id = ?',
    'first_unit': 'SELECT * FROM spatial_units WHERE organization_id = ? AND project_id = ? ORDER BY created_at LIMIT 1',
    'latest_revision': 'SELECT * FROM geometry_revisions WHERE spatial_unit_id = ? ORDER BY revision_no DESC LIMIT 1',
    'artifacts': 'SELECT artifact_id, geometry_revision_id, artifact_kind, filename, content_type, sha256, size_bytes, status, created_at FROM spatial_artifacts WHERE organization_id = ? AND project_id = ? ORDER BY created_at DESC, artifact_kind',
    'artifact': 'SELECT * FROM spatial_artifacts WHERE artifact_id = ? AND organization_id = ? AND project_id = ?',
    'revision': 'SELECT * FROM geometry_revisions WHERE geometry_revision_id = ?',
    'quantities': 'SELECT * FROM quantity_items WHERE geometry_revision_id = ? ORDER BY quantity_item_id',
    'revision_artifacts': 'SELECT artifact_id, artifact_kind, filename, content_type, sha256, size_bytes, status, created_at FROM spatial_artifacts WHERE geometry_revision_id = ? ORDER BY artifact_kind',
    'revisions': 'SELECT geometry_revision_id, revision_no, width_text, length_text, area_m2_text, source_kind, change_reason, actor_id, created_at FROM geometry_revisions WHERE spatial_unit_id = ? ORDER BY revision_no',
    'unit_by_id': 'SELECT * FROM spatial_units WHERE spatial_unit_id = ?',
    'pricing': 'SELECT pricing_json, formula_version FROM spatial_quotes WHERE geometry_revision_id = ?',
}

POSTGRES_QUERIES = {
    'insert_artifact': "INSERT INTO rkd.spatial_artifact(artifact_id, geometry_revision_id, organization_id, project_id, artifact_kind, filename, content_type, relative_path, sha256, size_bytes, status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s)",
    'supersede': "UPDATE rkd.spatial_artifact SET status = 'superseded' WHERE organization_id = %s AND project_id = %s AND geometry_revision_id IN (SELECT geometry_revision_id FROM rkd.geometry_revision WHERE spatial_unit_id = %s)",
    'insert_revision': "INSERT INTO rkd.geometry_revision(geometry_revision_id, spatial_unit_id, organization_id, project_id, revision_no, width_text, length_text, deductions, area_m2_text, input_hash, source_kind, change_reason, actor_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, 'parameter_input', %s, %s, %s)",
    'insert_quantity': "INSERT INTO rkd.quantity_item(quantity_item_id, geometry_revision_id, organization_id, project_id, item_kind, description, quantity_text, unit, formula, source_status) VALUES (%s, %s, %s, %s, 'floor_area', '参数地坪净面积', %s, 'm²', '外框宽度 × 外框长度 − 扣除区面积', 'verified_by_deterministic_calculation')",
    'insert_quote': 'INSERT INTO rkd.spatial_quote(organization_id,project_id,geometry_revision_id, quote_revision_id, pricing, result, formula_version, created_at) VALUES (%s,%s,%s, %s, %s::jsonb, %s::jsonb, %s, %s)',
    'unit': 'SELECT * FROM rkd.spatial_unit WHERE spatial_unit_id = %s AND organization_id = %s AND project_id = %s',
    'quantity': 'SELECT * FROM rkd.quantity_item WHERE geometry_revision_id = %s',
    'quote': 'SELECT *,pricing::text AS pricing_json,result::text AS result_json FROM rkd.spatial_quote WHERE geometry_revision_id = %s',
    'insert_unit': "INSERT INTO rkd.spatial_unit(spatial_unit_id, organization_id, project_id, name, unit_kind, created_at) VALUES (%s, %s, %s, %s, 'floor_area', %s)",
    'quantity_id': 'SELECT quantity_item_id FROM rkd.quantity_item WHERE geometry_revision_id = %s',
    'first_unit': 'SELECT * FROM rkd.spatial_unit WHERE organization_id = %s AND project_id = %s ORDER BY created_at LIMIT 1',
    'latest_revision': 'SELECT *,deductions::text AS deductions_json FROM rkd.geometry_revision WHERE spatial_unit_id = %s ORDER BY revision_no DESC LIMIT 1',
    'artifacts': 'SELECT artifact_id, geometry_revision_id, artifact_kind, filename, content_type, sha256, size_bytes, status, created_at FROM rkd.spatial_artifact WHERE organization_id = %s AND project_id = %s ORDER BY created_at DESC, artifact_kind',
    'artifact': 'SELECT * FROM rkd.spatial_artifact WHERE artifact_id = %s AND organization_id = %s AND project_id = %s',
    'revision': 'SELECT *,deductions::text AS deductions_json FROM rkd.geometry_revision WHERE geometry_revision_id = %s',
    'quantities': 'SELECT * FROM rkd.quantity_item WHERE geometry_revision_id = %s ORDER BY quantity_item_id',
    'revision_artifacts': 'SELECT artifact_id, artifact_kind, filename, content_type, sha256, size_bytes, status, created_at FROM rkd.spatial_artifact WHERE geometry_revision_id = %s ORDER BY artifact_kind',
    'revisions': 'SELECT geometry_revision_id, revision_no, width_text, length_text, area_m2_text, source_kind, change_reason, actor_id, created_at FROM rkd.geometry_revision WHERE spatial_unit_id = %s ORDER BY revision_no',
    'unit_by_id': 'SELECT * FROM rkd.spatial_unit WHERE spatial_unit_id = %s',
    'pricing': 'SELECT pricing::text AS pricing_json, formula_version FROM rkd.spatial_quote WHERE geometry_revision_id = %s',
}


class SpatialRows:
    def __init__(self, cursor):
        self.items = canonical(mapping(cursor)) if cursor.description else []

    def fetchone(self):
        return self.items[0] if self.items else None

    def fetchall(self):
        return self.items


class SQLiteSpatialTransaction:
    def __init__(self, db, org, project):
        self.db, self.scope = db, (org, project)

    def query(self, operation, params=()):
        try:
            return self.db.execute(SQLITE_QUERIES[operation], params)
        except sqlite3.IntegrityError as error:
            if operation == "insert_unit" and error.sqlite_errorcode in {sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY, sqlite3.SQLITE_CONSTRAINT_UNIQUE}:
                raise SpatialUnitConflict("space identifier unavailable") from error
            raise


class SQLiteSpatialRepository:
    def __init__(self, context):
        self.context = context

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.context() as db:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield SQLiteSpatialTransaction(db, org, project)


class PostgresSpatialTransaction:
    def __init__(self, db, org, project):
        self.db, self.scope = db, (org, project)

    def query(self, operation, params=()):
        from psycopg.errors import UniqueViolation
        if operation == "insert_quote":
            params = (*self.scope, *params)
        try:
            return SpatialRows(self.db.execute(POSTGRES_QUERIES[operation], params))
        except UniqueViolation as error:
            if operation == "insert_unit":
                raise SpatialUnitConflict("space identifier unavailable") from error
            raise


class PostgresSpatialRepository:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.store.tenant_transaction(TenantContext(org, project, "local-user")) as db:
            if write:
                db.execute("SELECT project_id FROM rkd.project WHERE organization_id=%s AND project_id=%s FOR UPDATE", (org, project))
            yield PostgresSpatialTransaction(db, org, project)
