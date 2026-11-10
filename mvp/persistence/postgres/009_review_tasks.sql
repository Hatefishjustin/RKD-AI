CREATE TABLE rkd.review_task (
 organization_id text NOT NULL, project_id text NOT NULL, task_id text PRIMARY KEY,
 position_key text NOT NULL, evidence_sha256 text NOT NULL, production_revision_id text NOT NULL,
 payload_json text NOT NULL, creator_id text NOT NULL, created_at timestamptz NOT NULL,
 status text NOT NULL CHECK(status IN ('pending','reviewed','changes_requested')),
 version integer NOT NULL, reviewer_id text, note text, updated_at timestamptz,
 UNIQUE(organization_id,project_id,position_key,evidence_sha256),
 FOREIGN KEY(organization_id,project_id) REFERENCES rkd.project(organization_id,project_id)
);
ALTER TABLE rkd.review_task ENABLE ROW LEVEL SECURITY;
CREATE POLICY review_task_scope ON rkd.review_task
 USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
 WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());
