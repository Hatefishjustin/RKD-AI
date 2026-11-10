CREATE TABLE ai_source_extractions (
    extraction_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    extractor_kind TEXT NOT NULL CHECK(extractor_kind IN ('plain_text', 'pdf_text_layer', 'unsupported')),
    extractor_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('extracted', 'no_extractable_text_layer', 'unsupported_format')),
    status_reason TEXT,
    segment_count INTEGER NOT NULL,
    text_sha256 TEXT,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, file_id, file_sha256, extractor_version),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE INDEX ai_source_extractions_project_created
ON ai_source_extractions(organization_id, project_id, created_at DESC);

CREATE TABLE ai_technical_deliveries (
    delivery_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    production_revision_id TEXT NOT NULL,
    option_revision_id TEXT NOT NULL,
    adoption_version INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft')),
    handover_json TEXT NOT NULL,
    source_extraction_ids_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
CREATE INDEX ai_technical_deliveries_project_created
ON ai_technical_deliveries(organization_id, project_id, created_at DESC);

CREATE TABLE ai_technical_artifacts (
    artifact_id TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL REFERENCES ai_technical_deliveries(delivery_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL CHECK(artifact_kind IN ('technical_plan_svg', 'detail_node_svg', 'material_schedule_csv', 'technical_handover_html', 'handover_json', 'delivery_manifest_json', 'delivery_zip')),
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (delivery_id, artifact_kind),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id)
);
