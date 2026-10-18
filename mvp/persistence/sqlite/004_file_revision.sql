ALTER TABLE file_assets ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;

WITH ordered AS (
    SELECT file_id,
           ROW_NUMBER() OVER (
               PARTITION BY organization_id, project_id, filename
               ORDER BY created_at, file_id
           ) AS next_revision
    FROM file_assets
)
UPDATE file_assets
SET revision = (SELECT next_revision FROM ordered WHERE ordered.file_id = file_assets.file_id);

CREATE UNIQUE INDEX IF NOT EXISTS file_assets_name_revision
ON file_assets(organization_id, project_id, filename, revision);
