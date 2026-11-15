-- Comment thread origin — COL-4.4 (#4528).
--
-- COL-1.1 (V259) threads are internal design discussion between workspace members. COL-4.4 lets a
-- **Browse reader** (PCX-1.1, V378) — an API consumer who is not a workspace member — open a feedback
-- thread on a published version or one of its operations. Those threads live in the same table, so
-- the owning team sees, replies to, and resolves them in the Discussion panel with the tools it
-- already has; what they need is a tag that says where they came from:
--
--   origin = 'internal' — opened by a workspace member (every thread before this migration).
--   origin = 'consumer' — opened by a Browse reader as feedback on a published spec.
--
-- The vocabulary is a CHECK, not an ENUM, matching the rest of the schema. Existing rows take the
-- default. ``created_by`` of a consumer thread is the reader's ``users`` row, so the existing
-- ``ON DELETE SET NULL`` keeps the feedback when that account is deleted.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP INDEX IF EXISTS apiome.idx_comment_threads_consumer_version_creator;
--   DROP INDEX IF EXISTS apiome.idx_comment_threads_project_origin;
--   ALTER TABLE apiome.comment_threads DROP CONSTRAINT IF EXISTS comment_threads_origin_check;
--   ALTER TABLE apiome.comment_threads DROP COLUMN IF EXISTS origin;

SET search_path TO apiome, public;

ALTER TABLE comment_threads ADD COLUMN IF NOT EXISTS origin VARCHAR(16) NOT NULL DEFAULT 'internal';

ALTER TABLE comment_threads DROP CONSTRAINT IF EXISTS comment_threads_origin_check;
ALTER TABLE comment_threads ADD CONSTRAINT comment_threads_origin_check
    CHECK (origin IN ('internal', 'consumer'));

-- The Discussion panel's Origin filter over a project.
CREATE INDEX IF NOT EXISTS idx_comment_threads_project_origin
    ON comment_threads (project_id, origin);

-- A reader's own feedback threads on a version (the Browse Feedback tab's read).
CREATE INDEX IF NOT EXISTS idx_comment_threads_consumer_version_creator
    ON comment_threads (version_id, created_by)
    WHERE origin = 'consumer';

COMMENT ON COLUMN comment_threads.origin IS
    'internal (opened by a workspace member) | consumer (feedback opened by a Browse reader, COL-4.4 #4528)';
