-- Down-migration: remove the per-user preferences column added for Developer Mode (#3343).
-- Developer Mode is being withdrawn; this reverses 20260511-162000.sql so applied
-- databases converge with fresh installs (which create then drop the column).
SET search_path TO apiome, public;

ALTER TABLE apiome.users
  DROP COLUMN IF EXISTS preferences;
