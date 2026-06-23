-- Issue #149: Record last application login time on user accounts
SET search_path TO odb, public;

ALTER TABLE odb.users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN odb.users.last_login_at IS 'Timestamp of the last successful login to the application';
