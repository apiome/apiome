-- Recently viewed projects — per-user project view log (#510).
--
-- Problem: Home's "Pick up where you left off" ranks projects by when *anyone* in the workspace
-- last edited or published them. Nothing records which projects a given reader has opened, so
-- the dashboard cannot answer "what was I just looking at?".
--
-- Solution: a ``project_views`` table holding one row per (user, project): when the reader
-- first and last opened it and how many times. Opening a project upserts its row, so the table
-- grows with the projects a reader has touched, never with the number of visits. Rows cascade
-- with their tenant, owner and project; a soft-deleted project's row stays but is filtered out
-- when listed.
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.project_views;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.project_views (
    -- Owner — cascade when the user is removed; the view history is personal, not shared.
    user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE,

    -- The project that was opened — cascade when it is hard-deleted.
    project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,

    -- Tenant scope, denormalised from the project so listing is a single indexed range scan.
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,

    -- When the reader first opened the project.
    first_viewed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- When the reader most recently opened the project — the list's sort key.
    last_viewed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- How many times the reader has opened the project.
    view_count INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT project_views_pkey PRIMARY KEY (user_id, project_id),
    CONSTRAINT project_views_view_count_positive CHECK (view_count > 0)
);

-- List a user's recently viewed projects in a tenant, newest first.
CREATE INDEX IF NOT EXISTS idx_project_views_tenant_user_recent
    ON apiome.project_views (tenant_id, user_id, last_viewed_at DESC);

-- Cascade path for project deletes.
CREATE INDEX IF NOT EXISTS idx_project_views_project
    ON apiome.project_views (project_id);

COMMENT ON TABLE apiome.project_views IS
    'Per-user project view log backing "Recently viewed" on Home (#510). '
    'One row per (user, project), upserted each time the reader opens the project.';
COMMENT ON COLUMN apiome.project_views.last_viewed_at IS
    'When the reader most recently opened the project; recently viewed lists sort by it';
COMMENT ON COLUMN apiome.project_views.view_count IS
    'How many times the reader has opened the project';
