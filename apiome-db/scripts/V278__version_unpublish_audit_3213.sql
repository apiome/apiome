-- Unpublish audit on schema revisions (#3213, CLI 4.6 `apiome versions unpublish`).
--
-- Unpublishing returns a published revision to draft (POST /v1/versions/{t}/{p}/{id}/unpublish).
-- Until now nothing recorded why, or by whom. A retraction — a bad release, a publish to the wrong
-- tenant, a security regression — needs that trail, and `versions get` shows it.
--
--   versions.unpublish_reason   the reason given for the most recent unpublish (free text).
--   versions.unpublished_at     when the revision was most recently unpublished.
--   versions.unpublished_by     who unpublished it (users.id; NULL once that user is deleted).
--
-- The columns describe the *last* unpublish and are kept when the revision is published again,
-- so a re-published revision still shows that it was once retracted. NULL for every revision that
-- has never been unpublished.

SET search_path TO apiome, public;

ALTER TABLE apiome.versions
  ADD COLUMN IF NOT EXISTS unpublish_reason TEXT,
  ADD COLUMN IF NOT EXISTS unpublished_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS unpublished_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL;

COMMENT ON COLUMN apiome.versions.unpublish_reason IS
  'Reason recorded with the most recent unpublish of this revision (#3213). NULL = never unpublished, or unpublished without a reason.';
COMMENT ON COLUMN apiome.versions.unpublished_at IS
  'When this revision was most recently unpublished (#3213). Kept when the revision is published again.';
COMMENT ON COLUMN apiome.versions.unpublished_by IS
  'User who most recently unpublished this revision (#3213); NULL once that user is deleted.';

DO $$
BEGIN
    RAISE NOTICE 'apiome.versions unpublish_reason / unpublished_at / unpublished_by added (#3213, CLI 4.6).';
END $$;
