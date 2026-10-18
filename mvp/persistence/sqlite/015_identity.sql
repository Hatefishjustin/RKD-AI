CREATE TABLE auth_users (
    user_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, user_id)
);
CREATE TABLE auth_memberships (
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('manager', 'editor', 'viewer')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, project_id, user_id),
    FOREIGN KEY (organization_id, project_id) REFERENCES projects(organization_id, project_id),
    FOREIGN KEY (organization_id, user_id) REFERENCES auth_users(organization_id, user_id)
);
CREATE TABLE auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES auth_users(user_id),
    csrf_token TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    last_seen_at REAL NOT NULL
);
CREATE TABLE auth_login_limits (
    bucket TEXT PRIMARY KEY,
    failures INTEGER NOT NULL,
    window_started_at REAL NOT NULL
);
CREATE TABLE auth_audit (
    audit_id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    project_id TEXT,
    action TEXT NOT NULL,
    target_id TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX auth_sessions_user ON auth_sessions(user_id);
