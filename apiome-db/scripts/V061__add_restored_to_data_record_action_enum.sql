-- Add 'restored' to data_record_action enum (for undelete).
-- Run this on databases that were migrated with 20260227-120000 before 'restored' was added.

SET search_path TO apiome, public;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON e.enumtypid = t.oid
        WHERE t.typname = 'data_record_action' AND e.enumlabel = 'restored'
    ) THEN
        ALTER TYPE data_record_action ADD VALUE 'restored';
    END IF;
END $$;

COMMENT ON COLUMN data_record.action IS 'created, updated, deleted, or restored (undeleted)';
