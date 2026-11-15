-- Branch / merge-request spec workflow — COL-4.3 (#4527).
--
-- Teams draft a change on a branch, open a merge request, review it, and merge — inside Apiome,
-- without external git. The pieces already exist; this migration only ties them together:
--
--   version_branches.draft_of_branch_id — marks a **draft branch** and names the version line
--       (the branch) it was drafted off. Its tip is a revision of its own, so edits on the branch
--       never touch the line.
--   merge_requests — one proposal to merge a draft branch into a line. It *composes* a review
--       (COL-2.1 ``reviews``), a merge session (``merge_sessions``, the only merge path), and the
--       revision the merge produced; it holds no merge or review state of its own.
--
-- Rules:
--
--   1. **One open merge request per source branch** (partial unique index).
--   2. **A merge request never merges a branch into itself** (CHECK on the branch names).
--   3. **Terminal states are recorded with who and when**: ``merged`` carries ``merged_at``,
--      ``closed`` carries ``closed_at``, and an ``open`` request carries neither.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.merge_requests;
--   ALTER TABLE apiome.version_branches DROP COLUMN IF EXISTS draft_of_branch_id;

SET search_path TO apiome, public;

ALTER TABLE version_branches
    ADD COLUMN IF NOT EXISTS draft_of_branch_id UUID REFERENCES version_branches(id) ON DELETE SET NULL;

COMMENT ON COLUMN version_branches.draft_of_branch_id IS
    'Set on a draft branch: the version line (branch) it was drafted off (COL-4.3, #4527)';

CREATE INDEX IF NOT EXISTS idx_version_branches_draft_of_branch_id
    ON version_branches (draft_of_branch_id)
    WHERE draft_of_branch_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS merge_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL
        CONSTRAINT merge_requests_title_check CHECK (length(btrim(title)) >= 1),
    description TEXT
        CONSTRAINT merge_requests_description_check CHECK (description IS NULL OR length(description) <= 5000),
    source_branch_id UUID REFERENCES version_branches(id) ON DELETE SET NULL,
    source_branch_name VARCHAR(255) NOT NULL,
    target_branch_id UUID REFERENCES version_branches(id) ON DELETE SET NULL,
    target_branch_name VARCHAR(255) NOT NULL,
    review_id UUID REFERENCES reviews(id) ON DELETE SET NULL,
    merge_session_id UUID REFERENCES merge_sessions(id) ON DELETE SET NULL,
    merged_version_id UUID REFERENCES versions(id) ON DELETE SET NULL,
    state VARCHAR(16) NOT NULL DEFAULT 'open'
        CONSTRAINT merge_requests_state_check CHECK (state IN ('open', 'merged', 'closed')),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    merged_by UUID REFERENCES users(id) ON DELETE SET NULL,
    merged_at TIMESTAMP WITH TIME ZONE,
    closed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    closed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT merge_requests_distinct_branches_check CHECK (source_branch_name <> target_branch_name),
    CONSTRAINT merge_requests_merged_check CHECK ((state = 'merged') = (merged_at IS NOT NULL)),
    CONSTRAINT merge_requests_closed_check CHECK ((state = 'closed') = (closed_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_merge_requests_open_source_branch
    ON merge_requests (source_branch_id)
    WHERE state = 'open';

CREATE INDEX IF NOT EXISTS idx_merge_requests_project
    ON merge_requests (project_id, state, updated_at DESC);

COMMENT ON TABLE merge_requests IS
    'A proposal to merge a draft branch into a version line, composing a review and a merge session (COL-4.3, #4527)';
