-- Organization overview exposes project summaries only. Project tables and
-- all child data retain their strict project RLS policies. The application
-- role must be explicitly granted EXECUTE by the trusted provisioner.
CREATE FUNCTION rkd.list_project_summaries()
RETURNS TABLE (organization_id text, project_id text, name text, status text,
               version bigint, created_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog
AS $$
    SELECT p.organization_id, p.project_id, p.name, p.status, p.version, p.created_at
    FROM rkd.project p
    WHERE p.organization_id = rkd.current_organization()
    ORDER BY p.name, p.project_id
$$;
REVOKE ALL ON FUNCTION rkd.list_project_summaries() FROM PUBLIC;
