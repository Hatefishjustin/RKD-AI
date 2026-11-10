"""Named, explicit SQL for change operations. Callers never supply SQL text.

Both dictionaries are reviewed statements, not translations. Every operation
prepends the transaction's trusted organization/project scope. PostgreSQL
JSON projections preserve the existing service contract without SQLite.
"""
from contextlib import contextmanager

from .file_repository import mapping
from .models import TenantContext
from .procurement_repository import canonical


SQLITE_QUERIES = {
    "changes": "SELECT * FROM change_requests WHERE organization_id=? AND project_id=? ORDER BY change_no DESC",
    "change": "SELECT * FROM change_requests WHERE organization_id=? AND project_id=? AND change_id=?",
    "event": "SELECT change_id,event_type,payload_json FROM change_events WHERE organization_id=? AND project_id=? AND idempotency_key=?",
    "issue": "SELECT 1 FROM issues WHERE organization_id=? AND project_id=? AND issue_id=?",
    "design": "SELECT * FROM design_revisions WHERE organization_id=? AND project_id=? AND design_revision_id=?",
    "latest_design": "SELECT * FROM design_revisions WHERE organization_id=? AND project_id=? ORDER BY revision_no DESC LIMIT 1",
    "geometry": "SELECT * FROM geometry_revisions WHERE organization_id=? AND project_id=? AND geometry_revision_id=?",
    "latest_geometry": "SELECT * FROM geometry_revisions WHERE organization_id=? AND project_id=? ORDER BY revision_no DESC LIMIT 1",
    "artifacts": "SELECT a.artifact_id,a.artifact_kind,a.filename,a.content_type,a.sha256,a.size_bytes,a.created_at FROM change_artifacts a JOIN change_requests c ON c.change_id=a.change_id WHERE c.organization_id=? AND c.project_id=? AND c.change_id=? ORDER BY artifact_kind",
    "acceptances": "SELECT acceptance_id,conclusion,checklist_json,evidence_ref,note,actor_id,created_at FROM change_acceptances WHERE organization_id=? AND project_id=? AND change_id=? ORDER BY created_at,acceptance_id",
    "design_artifacts": "SELECT a.artifact_id,a.artifact_kind FROM design_artifacts a JOIN design_revisions d ON d.design_revision_id=a.design_revision_id WHERE d.organization_id=? AND d.project_id=? AND d.design_revision_id=?",
    "geometry_artifacts": "SELECT artifact_id,artifact_kind FROM spatial_artifacts WHERE organization_id=? AND project_id=? AND geometry_revision_id=?",
    "next_no": "SELECT COALESCE(MAX(change_no),0)+1 AS next_no FROM change_requests WHERE organization_id=? AND project_id=?",
    "insert_change": "INSERT INTO change_requests(organization_id,project_id,change_id,change_no,issue_id,title,reason,description,status,design_revision_id,geometry_revision_id,baseline_json,proposal_json,impact_json,version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,'draft',?,?,?,?,'{}',1,?,?)",
    "write_event": "INSERT INTO change_events(organization_id,project_id,event_id,change_id,event_type,idempotency_key,request_hash,payload_json,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
    "analyze": "UPDATE change_requests SET status='analyzed',impact_json=?,version=version+1,updated_at=? WHERE organization_id=? AND project_id=? AND change_id=?",
    "insert_artifact": "INSERT INTO change_artifacts(artifact_id,change_id,artifact_kind,filename,content_type,relative_path,sha256,size_bytes,created_at) SELECT ?,?,?,?,?,?,?,?,? WHERE EXISTS(SELECT 1 FROM change_requests WHERE organization_id=? AND project_id=? AND change_id=?)",
    "insert_acceptance": "INSERT INTO change_acceptances(organization_id,project_id,acceptance_id,change_id,conclusion,checklist_json,evidence_ref,note,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
    "status": "UPDATE change_requests SET status=?,version=version+1,updated_at=? WHERE organization_id=? AND project_id=? AND change_id=?",
    "reproduction": "UPDATE change_requests SET impact_json=?,version=version+1,updated_at=? WHERE organization_id=? AND project_id=? AND change_id=?",
    "artifact": "SELECT a.* FROM change_artifacts a JOIN change_requests c ON c.change_id=a.change_id WHERE c.organization_id=? AND c.project_id=? AND a.artifact_id=?",
}

POSTGRES_QUERIES = {
    "changes": "SELECT c.*,baseline::text AS baseline_json,proposal::text AS proposal_json,impact::text AS impact_json FROM rkd.change_request c WHERE organization_id=%s AND project_id=%s ORDER BY change_no DESC",
    "change": "SELECT c.*,baseline::text AS baseline_json,proposal::text AS proposal_json,impact::text AS impact_json FROM rkd.change_request c WHERE organization_id=%s AND project_id=%s AND change_id=%s",
    "event": "SELECT change_id,event_type,payload::text AS payload_json FROM rkd.change_event WHERE organization_id=%s AND project_id=%s AND idempotency_key=%s",
    "issue": "SELECT 1 FROM rkd.issue WHERE organization_id=%s AND project_id=%s AND issue_id=%s",
    "design": "SELECT d.*,model::text AS model_json,validation::text AS validation_json FROM rkd.design_revision d WHERE organization_id=%s AND project_id=%s AND design_revision_id=%s",
    "latest_design": "SELECT d.*,model::text AS model_json,validation::text AS validation_json FROM rkd.design_revision d WHERE organization_id=%s AND project_id=%s ORDER BY revision_no DESC LIMIT 1",
    "geometry": "SELECT * FROM rkd.geometry_revision WHERE organization_id=%s AND project_id=%s AND geometry_revision_id=%s",
    "latest_geometry": "SELECT * FROM rkd.geometry_revision WHERE organization_id=%s AND project_id=%s ORDER BY revision_no DESC LIMIT 1",
    "artifacts": "SELECT artifact_id,artifact_kind,filename,content_type,sha256,size_bytes,created_at FROM rkd.change_artifact WHERE organization_id=%s AND project_id=%s AND change_id=%s ORDER BY artifact_kind",
    "acceptances": "SELECT acceptance_id,conclusion,checklist::text AS checklist_json,evidence_ref,note,actor_id,created_at FROM rkd.change_acceptance WHERE organization_id=%s AND project_id=%s AND change_id=%s ORDER BY created_at,acceptance_id",
    "design_artifacts": "SELECT artifact_id,artifact_kind FROM rkd.design_artifact WHERE organization_id=%s AND project_id=%s AND design_revision_id=%s",
    "geometry_artifacts": "SELECT artifact_id,artifact_kind FROM rkd.spatial_artifact WHERE organization_id=%s AND project_id=%s AND geometry_revision_id=%s",
    "next_no": "SELECT COALESCE(MAX(change_no),0)+1 AS next_no FROM rkd.change_request WHERE organization_id=%s AND project_id=%s",
    "insert_change": "INSERT INTO rkd.change_request(organization_id,project_id,change_id,change_no,issue_id,title,reason,description,status,design_revision_id,geometry_revision_id,baseline,proposal,impact,version,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s,%s::jsonb,%s::jsonb,'{}',1,%s,%s)",
    "write_event": "INSERT INTO rkd.change_event(organization_id,project_id,event_id,change_id,event_type,idempotency_key,request_hash,payload,actor_id,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)",
    "analyze": "UPDATE rkd.change_request SET status='analyzed',impact=%s::jsonb,version=version+1,updated_at=%s WHERE organization_id=%s AND project_id=%s AND change_id=%s",
    "insert_artifact": "INSERT INTO rkd.change_artifact(artifact_id,change_id,artifact_kind,filename,content_type,relative_path,sha256,size_bytes,created_at,organization_id,project_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    "insert_acceptance": "INSERT INTO rkd.change_acceptance(organization_id,project_id,acceptance_id,change_id,conclusion,checklist,evidence_ref,note,actor_id,created_at) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)",
    "status": "UPDATE rkd.change_request SET status=%s,version=version+1,updated_at=%s WHERE organization_id=%s AND project_id=%s AND change_id=%s",
    "reproduction": "UPDATE rkd.change_request SET impact=%s::jsonb,version=version+1,updated_at=%s WHERE organization_id=%s AND project_id=%s AND change_id=%s",
    "artifact": "SELECT artifact_id,change_id,artifact_kind,filename,content_type,relative_path,sha256,size_bytes,created_at FROM rkd.change_artifact WHERE organization_id=%s AND project_id=%s AND artifact_id=%s",
}


class Rows:
    def __init__(self, cursor):
        self.items = canonical(mapping(cursor)) if cursor.description else []
        # Native PG JSON columns are projected to their explicit service
        # fields above. Avoid returning both representations in API responses.
        for row in self.items:
            for field in ("baseline", "proposal", "impact", "model", "validation"):
                if field + "_json" in row:
                    row.pop(field, None)

    def fetchone(self):
        return self.items[0] if self.items else None

    def fetchall(self):
        return self.items

    def __iter__(self):
        return iter(self.items)


class ChangeTransaction:
    def __init__(self, db, org, project, statements):
        self.db, self.scope, self.statements = db, (org, project), statements

    def query(self, operation, params=()):
        # Update and artifact operations have explicitly different parameter
        # ordering. No SQL text is accepted, modified or inferred.
        if operation in {"analyze", "status", "reproduction"}:
            args = (*params[:2], *self.scope, params[2])
        elif operation == "insert_artifact":
            args = (*params, *self.scope)
            if self.statements is SQLITE_QUERIES:
                args += (params[1],)
        else:
            args = (*self.scope, *params)
        return Rows(self.db.execute(self.statements[operation], args))


class SQLiteChangeRepository:
    def __init__(self, connection_context):
        self.connection_context = connection_context

    def bind(self, db, org, project):
        return ChangeTransaction(db, org, project, SQLITE_QUERIES)

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.connection_context(write=write) as db:
            yield self.bind(db, org, project)


class PostgresChangeRepository:
    def __init__(self, store):
        self.store = store

    def bind(self, db, org, project):
        return ChangeTransaction(db, org, project, POSTGRES_QUERIES)

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.store.tenant_transaction(TenantContext(org, project, "local-user")) as db:
            if write:
                db.execute("SELECT project_id FROM rkd.project WHERE organization_id=%s AND project_id=%s FOR UPDATE", (org, project))
            yield self.bind(db, org, project)
