-- Branch push policy: require merge path (no direct push to tip) — #2583 / P2-01
SET search_path TO apiome, public;

ALTER TABLE version_branches
  ADD COLUMN IF NOT EXISTS require_merge_path BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN version_branches.require_merge_path IS
  'When true, non-admin pushes may not advance this branch tip; use merge apply (#2583)';
