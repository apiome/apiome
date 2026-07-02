-- Issue #149: Record last application login time on user accounts
SET search_path TO apiome, public;

ALTER TABLE apiome.users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN apiome.users.last_login_at IS 'Timestamp of the last successful login to the application';
