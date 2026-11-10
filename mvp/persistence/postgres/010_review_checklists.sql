CREATE TABLE rkd.review_checklist (
 task_id text PRIMARY KEY REFERENCES rkd.review_task(task_id),
 organization_id text NOT NULL, project_id text NOT NULL,
 checklist_json text NOT NULL,
 FOREIGN KEY(organization_id,project_id) REFERENCES rkd.project(organization_id,project_id)
);
ALTER TABLE rkd.review_checklist ENABLE ROW LEVEL SECURITY;
CREATE POLICY review_checklist_scope ON rkd.review_checklist
 USING (organization_id=rkd.current_organization() AND project_id=rkd.current_project())
 WITH CHECK (organization_id=rkd.current_organization() AND project_id=rkd.current_project());
