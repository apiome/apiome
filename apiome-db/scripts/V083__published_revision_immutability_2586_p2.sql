-- Published revision immutability (#2586 / P2-04): flag + server-side enforcement
SET search_path TO apiome, public;

ALTER TABLE versions
  ADD COLUMN IF NOT EXISTS published_immutable BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN versions.published_immutable IS
  'When published: if true, reject git-like writes (push/merge/rollback) unless tenant admin override with audit (#2586).';

UPDATE versions SET published_immutable = true WHERE published = true;
