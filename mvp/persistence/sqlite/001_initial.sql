CREATE TABLE IF NOT EXISTS mvp_state (
    state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (organization_id, project_id)
);
