-- Failed login reservations are scoped to the trusted deployment organization.
-- The legacy unscoped auth_login_limit stays service-only and is not widened.
CREATE TABLE rkd.auth_login_throttle (
    organization_id text NOT NULL REFERENCES rkd.organization(organization_id),
    bucket text NOT NULL,
    failures integer NOT NULL CHECK (failures >= 0),
    window_started_at timestamptz NOT NULL,
    PRIMARY KEY (organization_id, bucket)
);
ALTER TABLE rkd.auth_login_throttle ENABLE ROW LEVEL SECURITY;
CREATE POLICY auth_login_throttle_scope ON rkd.auth_login_throttle
    USING (organization_id = rkd.current_organization())
    WITH CHECK (organization_id = rkd.current_organization());

-- Project rows and memberships keep strict project RLS. This narrow catalogue
-- returns only role labels for an active account inside the current organization.
CREATE FUNCTION rkd.list_account_project_roles(account_id text)
RETURNS TABLE (project_id text, role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog
AS $$
    SELECT m.project_id, m.role
    FROM rkd.auth_membership m
    JOIN rkd.auth_user u ON u.organization_id=m.organization_id AND u.user_id=m.user_id
    WHERE m.organization_id = rkd.current_organization()
      AND m.user_id = account_id AND u.active
    ORDER BY m.project_id
$$;
REVOKE ALL ON FUNCTION rkd.list_account_project_roles(text) FROM PUBLIC;
