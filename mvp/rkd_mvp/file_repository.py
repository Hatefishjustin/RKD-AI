"""Explicit storage adapters for one shared file-byte workflow.

No SQL rewriting or fallback: each adapter names its own tables, placeholders,
JSON representation and locking. Disk validation stays in FileService.
"""
from contextlib import contextmanager
import json

from .models import TenantContext


def mapping(cursor):
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


class SQLiteFileRepository:
    def __init__(self, connection_context):
        self.connection_context = connection_context

    @contextmanager
    def transaction(self, organization_id, project_id, *, write=False):
        with self.connection_context() as db:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield SQLiteFileTransaction(db, organization_id, project_id)


class SQLiteFileTransaction:
    def __init__(self, db, organization_id, project_id):
        self.db, self.scope = db, (organization_id, project_id)

    def upload(self, upload_id):
        row = self.db.execute("SELECT * FROM file_uploads WHERE organization_id=? AND project_id=? AND upload_id=?",
                              (*self.scope, upload_id)).fetchone()
        return dict(row) if row else None

    def insert_upload(self, row):
        self.db.execute("INSERT INTO file_uploads(upload_id,organization_id,project_id,filename,declared_size,"
                        "declared_sha256,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                        tuple(row[k] for k in ("upload_id", "organization_id", "project_id", "filename", "declared_size",
                                               "declared_sha256", "status", "created_at")))

    def stage(self, upload_id, digest):
        self.db.execute("UPDATE file_uploads SET status='staged',received_sha256=? "
                        "WHERE organization_id=? AND project_id=? AND upload_id=?", (digest, *self.scope, upload_id))

    def next_revision(self, filename):
        return self.db.execute("SELECT COALESCE(MAX(revision),0)+1 FROM file_assets "
                               "WHERE organization_id=? AND project_id=? AND filename=?", (*self.scope, filename)).fetchone()[0]

    def insert_file(self, row, upload_id):
        keys = ("file_id", "organization_id", "project_id", "filename", "kind", "content_type", "size_bytes", "sha256",
                "storage_key", "source_kind", "source_ref", "format_status", "created_at", "revision")
        self.db.execute("INSERT INTO file_assets(" + ",".join(keys) + ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        tuple(row[k] for k in keys))
        self.db.execute("UPDATE file_uploads SET status='completed' WHERE organization_id=? AND project_id=? AND upload_id=?",
                        (*self.scope, upload_id))

    def files(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM file_assets WHERE organization_id=? AND project_id=? "
                                                   "ORDER BY created_at,file_id", self.scope).fetchall()]

    def file(self, file_id):
        row = self.db.execute("SELECT * FROM file_assets WHERE organization_id=? AND project_id=? AND file_id=?",
                              (*self.scope, file_id)).fetchone()
        return dict(row) if row else None

    def decisions(self):
        rows = self.db.execute("SELECT * FROM project_decisions WHERE organization_id=? AND project_id=? "
                               "ORDER BY decision_key", self.scope).fetchall()
        return [{"key": r["decision_key"], "value": json.loads(r["value_json"]), "source": r["source"],
                 "status": r["status"], "source_conflict": r["source_conflict"]} for r in rows]


class PostgresFileRepository:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def transaction(self, organization_id, project_id, *, write=False):
        with self.store.tenant_transaction(TenantContext(organization_id, project_id, "local-user")) as db:
            yield PostgresFileTransaction(db, organization_id, project_id, write)


class PostgresFileTransaction:
    def __init__(self, db, organization_id, project_id, write):
        self.db, self.scope, self.write = db, (organization_id, project_id), write

    def upload(self, upload_id):
        query = "SELECT * FROM rkd.file_upload WHERE organization_id=%s AND project_id=%s AND upload_id=%s"
        rows = mapping(self.db.execute(query + (" FOR UPDATE" if self.write else ""), (*self.scope, upload_id)))
        return rows[0] if rows else None

    def insert_upload(self, row):
        self.db.execute("INSERT INTO rkd.file_upload(upload_id,organization_id,project_id,filename,declared_size,"
                        "declared_sha256,status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        tuple(row[k] for k in ("upload_id", "organization_id", "project_id", "filename", "declared_size",
                                               "declared_sha256", "status", "created_at")))

    def stage(self, upload_id, digest):
        self.db.execute("UPDATE rkd.file_upload SET status='staged',received_sha256=%s "
                        "WHERE organization_id=%s AND project_id=%s AND upload_id=%s", (digest, *self.scope, upload_id))

    def next_revision(self, filename):
        # Different upload rows for the same filename must serialize revisions.
        self.db.execute("SELECT project_id FROM rkd.project WHERE organization_id=%s AND project_id=%s FOR UPDATE", self.scope)
        return self.db.execute("SELECT COALESCE(MAX(revision),0)+1 FROM rkd.file_asset "
                               "WHERE organization_id=%s AND project_id=%s AND filename=%s", (*self.scope, filename)).fetchone()[0]

    def insert_file(self, row, upload_id):
        keys = ("file_id", "organization_id", "project_id", "filename", "kind", "content_type", "size_bytes", "sha256",
                "storage_key", "source_kind", "source_ref", "format_status", "created_at", "revision")
        self.db.execute("INSERT INTO rkd.file_asset(file_id,organization_id,project_id,filename,kind,content_type,size_bytes,"
                        "sha256,storage_key,source_kind,source_ref,format_status,created_at,revision) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", tuple(row[k] for k in keys))
        self.db.execute("UPDATE rkd.file_upload SET status='completed' WHERE organization_id=%s AND project_id=%s AND upload_id=%s",
                        (*self.scope, upload_id))

    def files(self):
        return mapping(self.db.execute("SELECT * FROM rkd.file_asset WHERE organization_id=%s AND project_id=%s "
                                       "ORDER BY created_at,file_id", self.scope))

    def file(self, file_id):
        rows = mapping(self.db.execute("SELECT * FROM rkd.file_asset WHERE organization_id=%s AND project_id=%s AND file_id=%s",
                                       (*self.scope, file_id)))
        return rows[0] if rows else None

    def decisions(self):
        rows = mapping(self.db.execute("SELECT decision_key,value,source,status,source_conflict FROM rkd.project_decision "
                                       "WHERE organization_id=%s AND project_id=%s ORDER BY decision_key", self.scope))
        return [{"key": r["decision_key"], **{k: r[k] for k in ("value", "source", "status", "source_conflict")}} for r in rows]
