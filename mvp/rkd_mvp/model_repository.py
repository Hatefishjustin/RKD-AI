"""Explicit repositories for a transaction spanning design and floor production."""
from contextlib import contextmanager
import json

from .file_repository import mapping
from .models import TenantContext
from .procurement_repository import SQLiteProcurementRepository, PostgresProcurementRepository, canonical
from .requirement_repository import (SQLiteRequirementRepository, SQLiteRequirementTransaction,
                                     PostgresRequirementRepository, PostgresRequirementTransaction)


def pg_records(cursor, fields=()):
    rows = canonical(mapping(cursor))
    for row in rows:
        for name in fields:
            row[name + "_json"] = json.dumps(row.pop(name), ensure_ascii=False)
    return rows


class SQLiteModelRepository:
    def __init__(self, connection_context):
        self.connection_context = connection_context
        self.requirements = SQLiteRequirementRepository(connection_context)
        # Procurement joins the same raw connection when called from sync.
        self.procurement = SQLiteProcurementRepository(None)

    def bind(self, db, org, project):
        return SQLiteModelTransaction(db, org, project)

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.connection_context() as db:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield self.bind(db, org, project)


class ModelTransaction:
    def current_requirement(self):
        return self.requirements.requirement()

    def requirement_revision(self, requirement_id, revision_no):
        return self.requirements.revision(requirement_id, revision_no)

    def latest_design(self):
        return self.design(None)

    def latest_production(self):
        return self.production(None)


class SQLiteModelTransaction(ModelTransaction):
    def __init__(self, db, org, project):
        self.db, self.scope = db, (org, project)
        self.requirements = SQLiteRequirementTransaction(db, org, project)

    def design(self, revision_no):
        query = "SELECT * FROM design_revisions WHERE organization_id=? AND project_id=?"
        args = self.scope
        if revision_no is not None:
            query += " AND revision_no=?"
            args += (revision_no,)
        row = self.db.execute(query + " ORDER BY revision_no DESC LIMIT 1", args).fetchone()
        return dict(row) if row else None

    def design_history(self):
        return [dict(r) for r in self.db.execute("SELECT revision_no,requirement_revision_no,source_kind,change_reason,actor_id,created_at "
                                               "FROM design_revisions WHERE organization_id=? AND project_id=? ORDER BY revision_no DESC", self.scope)]

    def design_artifacts(self, design_id):
        return [dict(r) for r in self.db.execute("SELECT a.* FROM design_artifacts a JOIN design_revisions d ON d.design_revision_id=a.design_revision_id "
                                               "WHERE d.organization_id=? AND d.project_id=? AND d.design_revision_id=? ORDER BY artifact_kind", (*self.scope, design_id))]

    def design_artifact(self, artifact_id):
        row = self.db.execute("SELECT a.* FROM design_artifacts a JOIN design_revisions d ON d.design_revision_id=a.design_revision_id "
                              "WHERE d.organization_id=? AND d.project_id=? AND a.artifact_id=?", (*self.scope, artifact_id)).fetchone()
        return dict(row) if row else None

    def insert_design(self, row):
        keys = ("design_revision_id", "revision_no", "requirement_id", "requirement_revision_no", "requirement_hash", "input_hash", "model_json",
                "validation_json", "source_kind", "change_reason", "actor_id", "created_at")
        self.db.execute("INSERT INTO design_revisions(organization_id,project_id,design_revision_id,revision_no,requirement_id,requirement_revision_no,"
                        "requirement_hash,input_hash,model_json,validation_json,source_kind,change_reason,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (*self.scope, *(row[k] for k in keys)))

    def insert_design_artifact(self, row):
        self.db.execute("INSERT INTO design_artifacts VALUES (?,?,?,?,?,?,?,?)", tuple(row[k] for k in
                        ("artifact_id", "design_revision_id", "artifact_kind", "filename", "content_type", "relative_path", "sha256", "size_bytes")))

    def settings(self):
        row = self.db.execute("SELECT * FROM production_settings WHERE organization_id=? AND project_id=?", self.scope).fetchone()
        return dict(row) if row else None

    def save_settings(self, version, settings_json, actor, now):
        self.db.execute("INSERT INTO production_settings VALUES (?,?,?,?,?,?) ON CONFLICT(organization_id,project_id) DO UPDATE SET "
                        "version=excluded.version,settings_json=excluded.settings_json,actor_id=excluded.actor_id,updated_at=excluded.updated_at",
                        (*self.scope, version, settings_json, actor, now))

    def production(self, revision_no):
        query = "SELECT * FROM production_revisions WHERE organization_id=? AND project_id=?"
        args = self.scope
        if revision_no is not None:
            query += " AND revision_no=?"
            args += (revision_no,)
        row = self.db.execute(query + " ORDER BY revision_no DESC LIMIT 1", args).fetchone()
        return dict(row) if row else None

    def production_history(self):
        return [dict(r) for r in self.db.execute("SELECT revision_no,design_revision_id,settings_version,created_at FROM production_revisions "
                                               "WHERE organization_id=? AND project_id=? ORDER BY revision_no DESC", self.scope)]

    def production_has_facts(self):
        return bool(self.db.execute("SELECT 1 FROM procurement_order_lines l JOIN procurement_orders o ON o.order_id=l.order_id "
                                    "WHERE o.organization_id=? AND o.project_id=? AND o.source_kind='design_boq_draft' "
                                    "AND (CAST(l.received_quantity_text AS NUMERIC)>0 OR CAST(l.allocated_quantity_text AS NUMERIC)>0) LIMIT 1", self.scope).fetchone())

    def production_artifacts(self, production_id):
        return [dict(r) for r in self.db.execute("SELECT a.* FROM production_artifacts a JOIN production_revisions p ON p.production_revision_id=a.production_revision_id "
                                               "WHERE p.organization_id=? AND p.project_id=? AND p.production_revision_id=? ORDER BY artifact_kind", (*self.scope, production_id))]

    def production_artifact(self, artifact_id):
        row = self.db.execute("SELECT a.* FROM production_artifacts a JOIN production_revisions p ON p.production_revision_id=a.production_revision_id "
                              "WHERE p.organization_id=? AND p.project_id=? AND a.artifact_id=?", (*self.scope, artifact_id)).fetchone()
        return dict(row) if row else None

    def insert_production(self, row):
        keys = ("production_revision_id", "revision_no", "design_revision_id", "settings_version", "input_hash", "baseline_json", "quantities_json",
                "quote_json", "procurement_json", "settings_json", "actor_id", "created_at")
        self.db.execute("INSERT INTO production_revisions(organization_id,project_id,production_revision_id,revision_no,design_revision_id,settings_version,input_hash,"
                        "baseline_json,quantities_json,quote_json,procurement_json,settings_json,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (*self.scope, *(row[k] for k in keys)))

    def insert_production_artifact(self, row):
        self.db.execute("INSERT INTO production_artifacts VALUES (?,?,?,?,?,?,?,?)", tuple(row[k] for k in
                        ("artifact_id", "production_revision_id", "artifact_kind", "filename", "content_type", "relative_path", "sha256", "size_bytes")))


class PostgresModelRepository:
    def __init__(self, store):
        self.store = store
        self.requirements = PostgresRequirementRepository(store)
        self.procurement = PostgresProcurementRepository(store)

    def bind(self, db, org, project):
        return PostgresModelTransaction(db, org, project)

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.store.tenant_transaction(TenantContext(org, project, "local-user")) as db:
            if write:
                db.execute("SELECT project_id FROM rkd.project WHERE organization_id=%s AND project_id=%s FOR UPDATE", (org, project))
            yield self.bind(db, org, project)


class PostgresModelTransaction(ModelTransaction):
    def __init__(self, db, org, project):
        self.db, self.scope = db, (org, project)
        self.requirements = PostgresRequirementTransaction(db, org, project)

    def design(self, revision_no):
        query = "SELECT * FROM rkd.design_revision WHERE organization_id=%s AND project_id=%s"
        args = self.scope
        if revision_no is not None:
            query += " AND revision_no=%s"
            args += (revision_no,)
        rows = pg_records(self.db.execute(query + " ORDER BY revision_no DESC LIMIT 1", args), ("model", "validation"))
        return rows[0] if rows else None

    def design_history(self):
        return pg_records(self.db.execute("SELECT revision_no,requirement_revision_no,source_kind,change_reason,actor_id,created_at "
                                          "FROM rkd.design_revision WHERE organization_id=%s AND project_id=%s ORDER BY revision_no DESC", self.scope))

    def design_artifacts(self, design_id):
        return pg_records(self.db.execute("SELECT artifact_id,design_revision_id,artifact_kind,filename,content_type,relative_path,sha256,size_bytes "
                                          "FROM rkd.design_artifact WHERE organization_id=%s AND project_id=%s AND design_revision_id=%s ORDER BY artifact_kind", (*self.scope, design_id)))

    def design_artifact(self, artifact_id):
        rows = pg_records(self.db.execute("SELECT artifact_id,design_revision_id,artifact_kind,filename,content_type,relative_path,sha256,size_bytes "
                                          "FROM rkd.design_artifact WHERE organization_id=%s AND project_id=%s AND artifact_id=%s", (*self.scope, artifact_id)))
        return rows[0] if rows else None

    def insert_design(self, row):
        keys = ("design_revision_id", "revision_no", "requirement_id", "requirement_revision_no", "requirement_hash", "input_hash", "model_json",
                "validation_json", "source_kind", "change_reason", "actor_id", "created_at")
        self.db.execute("INSERT INTO rkd.design_revision(organization_id,project_id,design_revision_id,revision_no,requirement_id,requirement_revision_no,"
                        "requirement_hash,input_hash,model,validation,source_kind,change_reason,actor_id,created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s)", (*self.scope, *(row[k] for k in keys)))

    def insert_design_artifact(self, row):
        self.db.execute("INSERT INTO rkd.design_artifact(organization_id,project_id,artifact_id,design_revision_id,artifact_kind,filename,content_type,relative_path,sha256,size_bytes) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (*self.scope, *(row[k] for k in
                        ("artifact_id", "design_revision_id", "artifact_kind", "filename", "content_type", "relative_path", "sha256", "size_bytes"))))

    def settings(self):
        rows = pg_records(self.db.execute("SELECT * FROM rkd.production_settings WHERE organization_id=%s AND project_id=%s", self.scope), ("settings",))
        return rows[0] if rows else None

    def save_settings(self, version, settings_json, actor, now):
        self.db.execute("INSERT INTO rkd.production_settings VALUES (%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT(organization_id,project_id) DO UPDATE SET "
                        "version=excluded.version,settings=excluded.settings,actor_id=excluded.actor_id,updated_at=excluded.updated_at",
                        (*self.scope, version, settings_json, actor, now))

    def production(self, revision_no):
        query = "SELECT * FROM rkd.production_revision WHERE organization_id=%s AND project_id=%s"
        args = self.scope
        if revision_no is not None:
            query += " AND revision_no=%s"
            args += (revision_no,)
        rows = pg_records(self.db.execute(query + " ORDER BY revision_no DESC LIMIT 1", args), ("baseline", "quantities", "quote", "procurement", "settings"))
        return rows[0] if rows else None

    def production_history(self):
        return pg_records(self.db.execute("SELECT revision_no,design_revision_id,settings_version,created_at FROM rkd.production_revision "
                                          "WHERE organization_id=%s AND project_id=%s ORDER BY revision_no DESC", self.scope))

    def production_has_facts(self):
        return bool(self.db.execute("SELECT 1 FROM rkd.procurement_order_line l JOIN rkd.procurement_order o ON o.order_id=l.order_id "
                                    "WHERE o.organization_id=%s AND o.project_id=%s AND o.source_kind='design_boq_draft' "
                                    "AND (CAST(l.received_quantity_text AS NUMERIC)>0 OR CAST(l.allocated_quantity_text AS NUMERIC)>0) LIMIT 1", self.scope).fetchone())

    def production_artifacts(self, production_id):
        return pg_records(self.db.execute("SELECT artifact_id,production_revision_id,artifact_kind,filename,content_type,relative_path,sha256,size_bytes "
                                          "FROM rkd.production_artifact WHERE organization_id=%s AND project_id=%s AND production_revision_id=%s ORDER BY artifact_kind", (*self.scope, production_id)))

    def production_artifact(self, artifact_id):
        rows = pg_records(self.db.execute("SELECT artifact_id,production_revision_id,artifact_kind,filename,content_type,relative_path,sha256,size_bytes "
                                          "FROM rkd.production_artifact WHERE organization_id=%s AND project_id=%s AND artifact_id=%s", (*self.scope, artifact_id)))
        return rows[0] if rows else None

    def insert_production(self, row):
        keys = ("production_revision_id", "revision_no", "design_revision_id", "settings_version", "input_hash", "baseline_json", "quantities_json",
                "quote_json", "procurement_json", "settings_json", "actor_id", "created_at")
        self.db.execute("INSERT INTO rkd.production_revision(organization_id,project_id,production_revision_id,revision_no,design_revision_id,settings_version,input_hash,"
                        "baseline,quantities,quote,procurement,settings,actor_id,created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s)", (*self.scope, *(row[k] for k in keys)))

    def insert_production_artifact(self, row):
        self.db.execute("INSERT INTO rkd.production_artifact(organization_id,project_id,artifact_id,production_revision_id,artifact_kind,filename,content_type,relative_path,sha256,size_bytes) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (*self.scope, *(row[k] for k in
                        ("artifact_id", "production_revision_id", "artifact_kind", "filename", "content_type", "relative_path", "sha256", "size_bytes"))))
