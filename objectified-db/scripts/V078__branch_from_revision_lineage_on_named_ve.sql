-- Branch-from-revision lineage on named version branches (#2570, P0-08)
SET search_path TO odb, public;

ALTER TABLE version_branches
  ADD COLUMN IF NOT EXISTS branched_from_revision_id UUID REFERENCES versions(id) ON DELETE SET NULL;

COMMENT ON COLUMN version_branches.branched_from_revision_id IS
  'Revision (versions.id) this branch was created from; persists when tip advances via push';

CREATE INDEX IF NOT EXISTS idx_version_branches_branched_from_revision_id
  ON version_branches(branched_from_revision_id)
  WHERE branched_from_revision_id IS NOT NULL;
