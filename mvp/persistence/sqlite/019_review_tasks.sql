CREATE TABLE review_tasks (
 organization_id TEXT NOT NULL, project_id TEXT NOT NULL, task_id TEXT PRIMARY KEY,
 position_key TEXT NOT NULL, evidence_sha256 TEXT NOT NULL, production_revision_id TEXT NOT NULL,
 payload_json TEXT NOT NULL, creator_id TEXT NOT NULL, created_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','reviewed','changes_requested')),
 version INTEGER NOT NULL, reviewer_id TEXT, note TEXT, updated_at TEXT,
 UNIQUE(organization_id,project_id,position_key,evidence_sha256),
 FOREIGN KEY(organization_id,project_id) REFERENCES projects(organization_id,project_id)
);
