"""Scoped procurement operations with explicit SQLite and PostgreSQL SQL."""
from contextlib import contextmanager
import json

from .file_repository import mapping
from .models import TenantContext


def canonical(rows):
    return [{k: value.isoformat() if hasattr(value, "isoformat") else value for k, value in row.items()} for row in rows]


class SQLiteProcurementRepository:
    def __init__(self, connection_context):
        self.connection_context = connection_context

    def bind(self, db, org, project):
        return SQLiteProcurementTransaction(db, org, project)

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.connection_context(write=write) as db:
            yield self.bind(db, org, project)


class SQLiteProcurementTransaction:
    def __init__(self, db, org, project):
        self.db, self.scope = db, (org, project)

    def event(self, key):
        row = self.db.execute("SELECT aggregate_id,payload_json FROM procurement_events WHERE organization_id=? AND project_id=? AND idempotency_key=?",
                              (*self.scope, key)).fetchone()
        return dict(row) if row else None

    def write_event(self, row):
        keys = ("event_id", "event_type", "aggregate_id", "idempotency_key", "payload_json", "actor_id", "created_at")
        self.db.execute("INSERT INTO procurement_events(organization_id,project_id,event_id,event_type,aggregate_id,idempotency_key,payload_json,actor_id,created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (*self.scope, *(row[k] for k in keys)))

    def orders(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM procurement_orders WHERE organization_id=? AND project_id=? ORDER BY revision_no DESC", self.scope)]

    def order(self, order_id):
        row = self.db.execute("SELECT * FROM procurement_orders WHERE organization_id=? AND project_id=? AND order_id=?", (*self.scope, order_id)).fetchone()
        return dict(row) if row else None

    def lines(self, order_id):
        return [dict(r) for r in self.db.execute("SELECT l.* FROM procurement_order_lines l JOIN procurement_orders o ON o.order_id=l.order_id "
                                               "WHERE o.organization_id=? AND o.project_id=? AND o.order_id=? ORDER BY l.rowid", (*self.scope, order_id))]

    def line(self, order_id, line_id):
        return next((row for row in self.lines(order_id) if row["line_id"] == line_id), None)

    def receipts(self, order_id):
        return [dict(r) for r in self.db.execute("SELECT * FROM material_receipts WHERE organization_id=? AND project_id=? AND order_id=? ORDER BY created_at,receipt_id",
                                               (*self.scope, order_id))]

    def receipt_lines(self, receipt_id):
        return [dict(r) for r in self.db.execute("SELECT l.receipt_line_id,l.line_id,l.quantity_text,l.unit FROM material_receipt_lines l "
                                               "JOIN material_receipts r ON r.receipt_id=l.receipt_id WHERE r.organization_id=? AND r.project_id=? AND r.receipt_id=?",
                                               (*self.scope, receipt_id))]

    def allocations(self, order_id):
        return [dict(r) for r in self.db.execute("SELECT * FROM material_allocations WHERE organization_id=? AND project_id=? AND order_id=? ORDER BY created_at,allocation_id",
                                               (*self.scope, order_id))]

    def next_revision(self):
        return self.db.execute("SELECT COALESCE(MAX(revision_no),0)+1 FROM procurement_orders WHERE organization_id=? AND project_id=?", self.scope).fetchone()[0]

    def insert_order(self, row):
        self.db.execute("INSERT INTO procurement_orders VALUES (?,?,?,?,'draft',?,?,?,?,0,1,?,?)",
                        (row["order_id"], *self.scope, row["revision_no"], row["supplier_name"], row["delivery_location"], row["source_kind"], row["source_ref"], row["now"], row["now"]))

    def insert_line(self, row):
        self.db.execute("INSERT INTO procurement_order_lines VALUES (?,?,?,?,?,?,?,'0','0',?)", tuple(row[k] for k in
                        ("line_id", "order_id", "item_code", "item_name", "specification", "quantity", "unit", "now")))

    def insert_receipt(self, row):
        self.db.execute("INSERT INTO material_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?)", (row["receipt_id"], *self.scope, *(row[k] for k in
                        ("order_id", "receipt_no", "received_at", "receiver", "evidence_ref", "note", "idempotency_key", "now"))))

    def insert_receipt_line(self, row):
        self.db.execute("INSERT INTO material_receipt_lines VALUES (?,?,?,?,?)", tuple(row[k] for k in
                        ("receipt_line_id", "receipt_id", "line_id", "quantity", "unit")))

    def insert_allocation(self, row):
        self.db.execute("INSERT INTO material_allocations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (row["allocation_id"], *self.scope, *(row[k] for k in
                        ("order_id", "line_id", "quantity", "target_area", "recipient", "evidence_ref", "note", "idempotency_key", "now"))))

    def update_line(self, order_id, line_id, field, value):
        if self.order(order_id) is None:
            raise ValueError("order scope missing")
        sql = {"received": "UPDATE procurement_order_lines SET received_quantity_text=? WHERE order_id=? AND line_id=?",
               "allocated": "UPDATE procurement_order_lines SET allocated_quantity_text=? WHERE order_id=? AND line_id=?"}[field]
        self.db.execute(sql, (value, order_id, line_id))

    def update_order(self, order_id, status, now):
        self.db.execute("UPDATE procurement_orders SET status=?,version=version+1,updated_at=? WHERE organization_id=? AND project_id=? AND order_id=?",
                        (status, now, *self.scope, order_id))

    def source_current(self, source_ref):
        current = self.db.execute("SELECT p.production_revision_id,p.design_revision_id,d.requirement_revision_no,r.current_revision_no FROM production_revisions p "
                                  "JOIN design_revisions d ON d.design_revision_id=p.design_revision_id JOIN requirements r ON r.requirement_id=d.requirement_id "
                                  "WHERE p.organization_id=? AND p.project_id=? ORDER BY p.revision_no DESC LIMIT 1", self.scope).fetchone()
        latest = self.db.execute("SELECT design_revision_id FROM design_revisions WHERE organization_id=? AND project_id=? ORDER BY revision_no DESC LIMIT 1", self.scope).fetchone()
        return bool(current and latest and current["production_revision_id"] == source_ref and current["design_revision_id"] == latest[0]
                    and current["requirement_revision_no"] == current["current_revision_no"])


class PostgresProcurementRepository:
    def __init__(self, store):
        self.store = store

    def bind(self, db, org, project):
        return PostgresProcurementTransaction(db, org, project)

    @contextmanager
    def transaction(self, org, project, *, write=False):
        with self.store.tenant_transaction(TenantContext(org, project, "local-user")) as db:
            if write:
                db.execute("SELECT project_id FROM rkd.project WHERE organization_id=%s AND project_id=%s FOR UPDATE", (org, project))
            yield self.bind(db, org, project)


class PostgresProcurementTransaction:
    def __init__(self, db, org, project):
        self.db, self.scope = db, (org, project)

    def event(self, key):
        rows = mapping(self.db.execute("SELECT aggregate_id,payload FROM rkd.procurement_event WHERE organization_id=%s AND project_id=%s AND idempotency_key=%s",
                                       (*self.scope, key)))
        return {"aggregate_id": rows[0]["aggregate_id"], "payload_json": json.dumps(rows[0]["payload"])} if rows else None

    def write_event(self, row):
        keys = ("event_id", "event_type", "aggregate_id", "idempotency_key", "payload_json", "actor_id", "created_at")
        self.db.execute("INSERT INTO rkd.procurement_event(organization_id,project_id,event_id,event_type,aggregate_id,idempotency_key,payload,actor_id,created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)", (*self.scope, *(row[k] for k in keys)))

    def orders(self):
        return canonical(mapping(self.db.execute("SELECT * FROM rkd.procurement_order WHERE organization_id=%s AND project_id=%s ORDER BY revision_no DESC", self.scope)))

    def order(self, order_id):
        rows = canonical(mapping(self.db.execute("SELECT * FROM rkd.procurement_order WHERE organization_id=%s AND project_id=%s AND order_id=%s", (*self.scope, order_id))))
        return rows[0] if rows else None

    def lines(self, order_id):
        rows = canonical(mapping(self.db.execute("SELECT * FROM rkd.procurement_order_line WHERE organization_id=%s AND project_id=%s AND order_id=%s ORDER BY created_at,line_id",
                                                (*self.scope, order_id))))
        return [{k: v for k, v in row.items() if k not in {"organization_id", "project_id"}} for row in rows]

    def line(self, order_id, line_id):
        return next((row for row in self.lines(order_id) if row["line_id"] == line_id), None)

    def receipts(self, order_id):
        return canonical(mapping(self.db.execute("SELECT * FROM rkd.material_receipt WHERE organization_id=%s AND project_id=%s AND order_id=%s ORDER BY created_at,receipt_id",
                                                (*self.scope, order_id))))

    def receipt_lines(self, receipt_id):
        return mapping(self.db.execute("SELECT receipt_line_id,line_id,quantity_text,unit FROM rkd.material_receipt_line "
                                       "WHERE organization_id=%s AND project_id=%s AND receipt_id=%s", (*self.scope, receipt_id)))

    def allocations(self, order_id):
        return canonical(mapping(self.db.execute("SELECT * FROM rkd.material_allocation WHERE organization_id=%s AND project_id=%s AND order_id=%s ORDER BY created_at,allocation_id",
                                                (*self.scope, order_id))))

    def next_revision(self):
        return self.db.execute("SELECT COALESCE(MAX(revision_no),0)+1 FROM rkd.procurement_order WHERE organization_id=%s AND project_id=%s", self.scope).fetchone()[0]

    def insert_order(self, row):
        self.db.execute("INSERT INTO rkd.procurement_order(order_id,organization_id,project_id,revision_no,status,supplier_name,delivery_location,source_kind,source_ref,created_at,updated_at) "
                        "VALUES (%s,%s,%s,%s,'draft',%s,%s,%s,%s,%s,%s)",
                        (row["order_id"], *self.scope, row["revision_no"], row["supplier_name"], row["delivery_location"], row["source_kind"], row["source_ref"], row["now"], row["now"]))

    def insert_line(self, row):
        self.db.execute("INSERT INTO rkd.procurement_order_line(organization_id,project_id,line_id,order_id,item_code,item_name,specification,ordered_quantity_text,unit,created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (*self.scope, *(row[k] for k in
                        ("line_id", "order_id", "item_code", "item_name", "specification", "quantity", "unit", "now"))))

    def insert_receipt(self, row):
        self.db.execute("INSERT INTO rkd.material_receipt(organization_id,project_id,receipt_id,order_id,receipt_no,received_at,receiver,evidence_ref,note,idempotency_key,created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (*self.scope, *(row[k] for k in
                        ("receipt_id", "order_id", "receipt_no", "received_at", "receiver", "evidence_ref", "note", "idempotency_key", "now"))))

    def insert_receipt_line(self, row):
        self.db.execute("INSERT INTO rkd.material_receipt_line(organization_id,project_id,receipt_line_id,receipt_id,order_id,line_id,quantity_text,unit) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (*self.scope, *(row[k] for k in
                        ("receipt_line_id", "receipt_id", "order_id", "line_id", "quantity", "unit"))))

    def insert_allocation(self, row):
        self.db.execute("INSERT INTO rkd.material_allocation(organization_id,project_id,allocation_id,order_id,line_id,quantity_text,target_area,recipient,evidence_ref,note,idempotency_key,created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (*self.scope, *(row[k] for k in
                        ("allocation_id", "order_id", "line_id", "quantity", "target_area", "recipient", "evidence_ref", "note", "idempotency_key", "now"))))

    def update_line(self, order_id, line_id, field, value):
        sql = {"received": "UPDATE rkd.procurement_order_line SET received_quantity_text=%s WHERE organization_id=%s AND project_id=%s AND order_id=%s AND line_id=%s",
               "allocated": "UPDATE rkd.procurement_order_line SET allocated_quantity_text=%s WHERE organization_id=%s AND project_id=%s AND order_id=%s AND line_id=%s"}[field]
        self.db.execute(sql, (value, *self.scope, order_id, line_id))

    def update_order(self, order_id, status, now):
        self.db.execute("UPDATE rkd.procurement_order SET status=%s,version=version+1,updated_at=%s WHERE organization_id=%s AND project_id=%s AND order_id=%s",
                        (status, now, *self.scope, order_id))

    def source_current(self, source_ref):
        rows = mapping(self.db.execute("SELECT p.production_revision_id,p.design_revision_id,d.requirement_revision_no,r.current_revision_no FROM rkd.production_revision p "
                                       "JOIN rkd.design_revision d ON d.design_revision_id=p.design_revision_id JOIN rkd.requirement r ON r.requirement_id=d.requirement_id "
                                       "WHERE p.organization_id=%s AND p.project_id=%s ORDER BY p.revision_no DESC LIMIT 1", self.scope))
        latest = self.db.execute("SELECT design_revision_id FROM rkd.design_revision WHERE organization_id=%s AND project_id=%s ORDER BY revision_no DESC LIMIT 1", self.scope).fetchone()
        current = rows[0] if rows else None
        return bool(current and latest and current["production_revision_id"] == source_ref and current["design_revision_id"] == latest[0]
                    and current["requirement_revision_no"] == current["current_revision_no"])
