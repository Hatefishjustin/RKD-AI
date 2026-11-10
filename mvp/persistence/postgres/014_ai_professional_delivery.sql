CREATE TABLE rkd.ai_source_extraction (
    extraction_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    file_id text NOT NULL,
    file_sha256 text NOT NULL,
    filename text NOT NULL,
    size_bytes integer NOT NULL,
    extractor_kind text NOT NULL CHECK(extractor_kind IN ('plain_text', 'pdf_text_layer', 'unsupported')),
    extractor_version text NOT NULL,
    status text NOT NULL CHECK(status IN ('extracted', 'no_extractable_text_layer', 'unsupported_format')),
    status_reason text,
    segment_count integer NOT NULL,
    text_sha256 text,
    record jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (organization_id, project_id, file_id, file_sha256, extractor_version),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX ai_source_extraction_project_created
ON rkd.ai_source_extraction(organization_id, project_id, created_at DESC);
ALTER TABLE rkd.ai_source_extraction ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_source_extraction_scope ON rkd.ai_source_extraction
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());

CREATE TABLE rkd.ai_technical_delivery (
    delivery_id text PRIMARY KEY,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    production_revision_id text NOT NULL,
    option_revision_id text NOT NULL,
    adoption_version integer NOT NULL,
    input_hash text NOT NULL,
    status text NOT NULL CHECK(status IN ('draft')),
    handover jsonb NOT NULL,
    source_extraction_ids jsonb NOT NULL,
    idempotency_key text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (organization_id, project_id, idempotency_key),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
CREATE INDEX ai_technical_delivery_project_created
ON rkd.ai_technical_delivery(organization_id, project_id, created_at DESC);
ALTER TABLE rkd.ai_technical_delivery ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_technical_delivery_scope ON rkd.ai_technical_delivery
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());

CREATE TABLE rkd.ai_technical_artifact (
    artifact_id text PRIMARY KEY,
    delivery_id text NOT NULL REFERENCES rkd.ai_technical_delivery(delivery_id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    project_id text NOT NULL,
    artifact_kind text NOT NULL CHECK(artifact_kind IN ('technical_plan_svg', 'detail_node_svg', 'material_schedule_csv', 'technical_handover_html', 'handover_json', 'delivery_manifest_json', 'delivery_zip')),
    filename text NOT NULL,
    content_type text NOT NULL,
    relative_path text NOT NULL,
    sha256 text NOT NULL,
    size_bytes integer NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (delivery_id, artifact_kind),
    FOREIGN KEY (organization_id, project_id) REFERENCES rkd.project(organization_id, project_id)
);
ALTER TABLE rkd.ai_technical_artifact ENABLE ROW LEVEL SECURITY;
CREATE POLICY ai_technical_artifact_scope ON rkd.ai_technical_artifact
USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());
