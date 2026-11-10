-- Preserve order-level idempotency in procurement_event while permitting
-- several line facts in one allocation command.
DO $$
DECLARE old_constraint text;
BEGIN
    SELECT c.conname INTO old_constraint
    FROM pg_constraint c
    WHERE c.conrelid='rkd.material_allocation'::regclass AND c.contype='u'
      AND ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(attnum,ord)
                JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum ORDER BY k.ord)
          = ARRAY['organization_id','project_id','idempotency_key'];
    IF old_constraint IS NULL THEN
        RAISE EXCEPTION 'Expected allocation command key constraint is missing';
    END IF;
    EXECUTE format('ALTER TABLE rkd.material_allocation DROP CONSTRAINT %I', old_constraint);
END $$;
ALTER TABLE rkd.material_allocation ADD CONSTRAINT allocation_command_line
    UNIQUE (organization_id, project_id, idempotency_key, line_id);
