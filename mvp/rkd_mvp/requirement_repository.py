"""Explicit requirement persistence; shared draft rules live in the service."""
from contextlib import contextmanager
import json

from .file_repository import mapping
from .models import TenantContext


class SQLiteRequirementRepository:
    def __init__(self, connection_context):
        self.connection_context = connection_context

    def bind(self, db, org, project):
        return SQLiteRequirementTransaction(db, org, project)

    @contextmanager
    def transaction(self, organization_id, project_id, *, write=False):
        with self.connection_context() as db:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield SQLiteRequirementTransaction(db, organization_id, project_id)


class SQLiteRequirementTransaction:
    def __init__(self, db, organization_id, project_id):
        self.db, self.scope = db, (organization_id, project_id)

    def evidence(self):
        project = self.db.execute("SELECT name FROM projects WHERE organization_id=? AND project_id=?", self.scope).fetchone()
        decisions = self.db.execute("SELECT * FROM project_decisions WHERE organization_id=? AND project_id=? ORDER BY decision_key", self.scope).fetchall()
        files = self.db.execute("SELECT * FROM file_assets WHERE organization_id=? AND project_id=? ORDER BY filename,revision", self.scope).fetchall()
        return project, decisions, files

    def requirement(self):
        row = self.db.execute("SELECT * FROM requirements WHERE organization_id=? AND project_id=?", self.scope).fetchone()
        return dict(row) if row else None

    def revision(self, requirement_id, revision_no):
        row = self.db.execute("SELECT * FROM requirement_revisions WHERE organization_id=? AND project_id=? "
                              "AND requirement_id=? AND revision_no=?", (*self.scope, requirement_id, revision_no)).fetchone()
        return dict(row) if row else None

    def insert_requirement(self, requirement_id, now):
        self.db.execute("INSERT INTO requirements(requirement_id,organization_id,project_id,current_revision_no,status,created_at,updated_at) "
                        "VALUES (?,?,?,1,'draft_unconfirmed',?,?)", (requirement_id, *self.scope, now, now))

    def insert_revision(self, row):
        keys = ("requirement_id", "revision_no", "source_kind", "change_reason", "actor_id", "content_json", "source_refs_json", "input_hash", "created_at")
        self.db.execute("INSERT INTO requirement_revisions(organization_id,project_id,requirement_id,revision_no,source_kind,"
                        "change_reason,actor_id,content_json,source_refs_json,input_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (*self.scope, *(row[k] for k in keys)))

    def advance(self, requirement_id, revision_no, now):
        self.db.execute("UPDATE requirements SET current_revision_no=?,updated_at=? WHERE organization_id=? AND project_id=? AND requirement_id=?",
                        (revision_no, now, *self.scope, requirement_id))


class PostgresRequirementRepository:
    def __init__(self, store):
        self.store = store

    def bind(self, db, org, project):
        return PostgresRequirementTransaction(db, org, project)

    @contextmanager
    def transaction(self, organization_id, project_id, *, write=False):
        with self.store.tenant_transaction(TenantContext(organization_id, project_id, "local-user")) as db:
            if write:
                # Serializes first creation as well as later revision edits.
                db.execute("SELECT project_id FROM rkd.project WHERE organization_id=%s AND project_id=%s FOR UPDATE",
                           (organization_id, project_id))
            yield PostgresRequirementTransaction(db, organization_id, project_id)


class PostgresRequirementTransaction:
    def __init__(self, db, organization_id, project_id):
        self.db, self.scope = db, (organization_id, project_id)

    def evidence(self):
        projects = mapping(self.db.execute("SELECT name FROM rkd.project WHERE organization_id=%s AND project_id=%s", self.scope))
        decisions = mapping(self.db.execute("SELECT decision_key,value,source,status,source_conflict FROM rkd.project_decision "
                                           "WHERE organization_id=%s AND project_id=%s ORDER BY decision_key", self.scope))
        for row in decisions:
            row["value_json"] = json.dumps(row.pop("value"), ensure_ascii=False)
        files = mapping(self.db.execute("SELECT file_id,filename,kind,source_kind,source_ref,sha256,format_status "
                                       "FROM rkd.file_asset WHERE organization_id=%s AND project_id=%s ORDER BY filename,revision", self.scope))
        return projects[0] if projects else None, decisions, files

    def requirement(self):
        rows = mapping(self.db.execute("SELECT * FROM rkd.requirement WHERE organization_id=%s AND project_id=%s", self.scope))
        return rows[0] if rows else None

    def revision(self, requirement_id, revision_no):
        rows = mapping(self.db.execute("SELECT * FROM rkd.requirement_revision WHERE organization_id=%s AND project_id=%s "
                                       "AND requirement_id=%s AND revision_no=%s", (*self.scope, requirement_id, revision_no)))
        if not rows:
            return None
        row = rows[0]
        row["content_json"] = json.dumps(row.pop("content"), ensure_ascii=False)
        row["source_refs_json"] = json.dumps(row.pop("source_refs"), ensure_ascii=False)
        row["created_at"] = row["created_at"].isoformat()
        return row

    def insert_requirement(self, requirement_id, now):
        self.db.execute("INSERT INTO rkd.requirement(requirement_id,organization_id,project_id,current_revision_no,status,created_at,updated_at) "
                        "VALUES (%s,%s,%s,1,'draft_unconfirmed',%s,%s)", (requirement_id, *self.scope, now, now))

    def insert_revision(self, row):
        keys = ("requirement_id", "revision_no", "source_kind", "change_reason", "actor_id", "content_json", "source_refs_json", "input_hash", "created_at")
        self.db.execute("INSERT INTO rkd.requirement_revision(organization_id,project_id,requirement_id,revision_no,source_kind,"
                        "change_reason,actor_id,content,source_refs,input_hash,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)",
                        (*self.scope, *(row[k] for k in keys)))

    def advance(self, requirement_id, revision_no, now):
        self.db.execute("UPDATE rkd.requirement SET current_revision_no=%s,updated_at=%s "
                        "WHERE organization_id=%s AND project_id=%s AND requirement_id=%s", (revision_no, now, *self.scope, requirement_id))
