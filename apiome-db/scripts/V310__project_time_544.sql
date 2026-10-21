-- Time spent per project — per-user active time, by day (#544).
--
-- Problem: Home cannot say where a member's time goes. Nothing records how long anyone spends on
-- a project.
--
-- Solution: a ``project_time`` table holding one row per (user, project, UTC day) with the active
-- seconds credited that day. While a project's page is open, visible and in use, the UI sends a
-- heartbeat about once a minute; each accepted heartbeat credits 60 seconds. ``last_beat_at``
-- rate-limits the credit, so two tabs on the same project cannot double-count, and a day can
-- never exceed 24 hours. Time is personal: Home and REST only ever show a member their own.
-- Rows cascade with their tenant, owner and project.
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.project_time;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.project_time (
    -- Owner — cascade when the user is removed; time is personal, not shared.
    user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE,

    -- The project the time was spent on — cascade when it is hard-deleted.
    project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,

    -- Tenant scope, denormalised from the project so the breakdown is one range scan.
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,

    -- The UTC calendar day the time was spent on.
    day DATE NOT NULL,

    -- Active seconds credited that day.
    active_seconds INTEGER NOT NULL DEFAULT 0,

    -- The last accepted heartbeat; a heartbeat sooner than ~a minute after it credits nothing.
    last_beat_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT project_time_pkey PRIMARY KEY (user_id, project_id, day),
    CONSTRAINT project_time_seconds_range CHECK (active_seconds BETWEEN 0 AND 86400)
);

-- A member's breakdown over a window of days in one tenant.
CREATE INDEX IF NOT EXISTS idx_project_time_tenant_user_day
    ON apiome.project_time (tenant_id, user_id, day DESC);

-- Cascade path for project deletes.
CREATE INDEX IF NOT EXISTS idx_project_time_project
    ON apiome.project_time (project_id);

COMMENT ON TABLE apiome.project_time IS
    'Per-user active time on each project, by UTC day (#544). Credited 60 s per accepted '
    'heartbeat from a visible, in-use project page; shown only to the member themselves.';
COMMENT ON COLUMN apiome.project_time.active_seconds IS
    'Active seconds credited on this day (0-86400)';
COMMENT ON COLUMN apiome.project_time.last_beat_at IS
    'Last accepted heartbeat; rate-limits crediting so parallel tabs cannot double-count';
