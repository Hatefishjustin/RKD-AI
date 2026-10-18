CREATE TABLE procurement_orders (
    order_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision_no INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'partially_received', 'received', 'partially_allocated', 'allocated', 'cancelled')),
    supplier_name TEXT NOT NULL,
    delivery_location TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    external_effects_enabled INTEGER NOT NULL DEFAULT 0 CHECK (external_effects_enabled = 0),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, revision_no)
);

CREATE TABLE procurement_order_lines (
    line_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES procurement_orders(order_id),
    item_code TEXT NOT NULL,
    item_name TEXT NOT NULL,
    specification TEXT NOT NULL,
    ordered_quantity_text TEXT NOT NULL,
    unit TEXT NOT NULL,
    received_quantity_text TEXT NOT NULL DEFAULT '0',
    allocated_quantity_text TEXT NOT NULL DEFAULT '0',
    created_at TEXT NOT NULL
);

CREATE TABLE material_receipts (
    receipt_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    order_id TEXT NOT NULL REFERENCES procurement_orders(order_id),
    receipt_no TEXT NOT NULL,
    received_at TEXT NOT NULL,
    receiver TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    note TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key)
);

CREATE TABLE material_receipt_lines (
    receipt_line_id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL REFERENCES material_receipts(receipt_id),
    line_id TEXT NOT NULL REFERENCES procurement_order_lines(line_id),
    quantity_text TEXT NOT NULL,
    unit TEXT NOT NULL
);

CREATE TABLE material_allocations (
    allocation_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    order_id TEXT NOT NULL REFERENCES procurement_orders(order_id),
    line_id TEXT NOT NULL REFERENCES procurement_order_lines(line_id),
    quantity_text TEXT NOT NULL,
    target_area TEXT NOT NULL,
    recipient TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    note TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key)
);

CREATE TABLE procurement_events (
    event_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    idempotency_key TEXT,
    payload_json TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX procurement_order_project_idx ON procurement_orders (organization_id, project_id, revision_no);
CREATE INDEX procurement_receipt_order_idx ON material_receipts (order_id, created_at);
CREATE INDEX procurement_allocation_order_idx ON material_allocations (order_id, created_at);
