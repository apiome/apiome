-- Per-user JSON preferences (Developer Mode toggle, future settings) (#3343).
SET search_path TO odb, public;

ALTER TABLE odb.users
  ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN odb.users.preferences IS
  'User-level preferences merged by the API (e.g. developerModeEnabled for code-first Developer Mode).';
