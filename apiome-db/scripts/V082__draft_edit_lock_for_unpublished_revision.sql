-- Draft edit lock for unpublished revisions (#2584 / P2-02)
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS version_draft_lock (
  version_id UUID NOT NULL PRIMARY KEY REFERENCES apiome.versions(id) ON DELETE CASCADE,
  owner_user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_version_draft_lock_expires_at
  ON apiome.version_draft_lock(expires_at);

COMMENT ON TABLE apiome.version_draft_lock IS
  'Exclusive edit lease for an unpublished (draft) revision; #2584';

COMMENT ON COLUMN apiome.version_draft_lock.expires_at IS
  'When the lock must be renewed or it becomes available to other editors';
