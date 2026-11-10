CREATE TABLE review_checklists (
 task_id TEXT PRIMARY KEY REFERENCES review_tasks(task_id),
 organization_id TEXT NOT NULL, project_id TEXT NOT NULL,
 checklist_json TEXT NOT NULL,
 FOREIGN KEY(organization_id,project_id) REFERENCES projects(organization_id,project_id)
);
