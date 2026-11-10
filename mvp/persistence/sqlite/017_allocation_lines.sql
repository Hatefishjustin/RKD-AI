-- One dispatch command may allocate multiple distinct order lines.
CREATE TABLE material_allocations_v2 (
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
    UNIQUE (organization_id, project_id, idempotency_key, line_id)
);
INSERT INTO material_allocations_v2 SELECT * FROM material_allocations;
DROP TABLE material_allocations;
ALTER TABLE material_allocations_v2 RENAME TO material_allocations;
CREATE INDEX procurement_allocation_order_idx ON material_allocations (order_id, created_at);
