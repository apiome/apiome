-- Pinned projects — per-user favorites shown on Home (#513).
--
-- Problem: a member who works on the same few projects every day has to find them on the
-- Projects list, or hope they surface in "Pick up where you left off" or "Recently viewed".
-- There is no way to keep a chosen project one click away.
--
-- Solution: a ``project_pins`` table holding one row per (user, project) the member pinned, with
-- when they pinned it. Home lists a member's pins in the current workspace, newest first. Pins are
-- personal: nobody else sees them. The per-member limit (8 per workspace) is enforced by the
-- writers, not by a constraint, so it can change without a migration. Rows cascade with their
-- tenant, owner and project; a soft-deleted project's pin stays but is not listed.
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.project_pins;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.project_pins (
    -- Owner — cascade when the user is removed; pins are personal, not shared.
    user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE,

    -- The pinned project — cascade when it is hard-deleted.
    project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,

    -- Tenant scope, denormalised from the project so listing and the limit check are one range scan.
    tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,

    -- When the member pinned the project — the list's sort key.
    pinned_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT project_pins_pkey PRIMARY KEY (user_id, project_id)
);

-- List (and count) a member's pins in a tenant, newest first.
CREATE INDEX IF NOT EXISTS idx_project_pins_tenant_user_recent
    ON apiome.project_pins (tenant_id, user_id, pinned_at DESC);

-- Cascade path for project deletes.
CREATE INDEX IF NOT EXISTS idx_project_pins_project
    ON apiome.project_pins (project_id);

COMMENT ON TABLE apiome.project_pins IS
    'Per-user pinned projects shown on Home (#513). One row per (user, project); '
    'at most 8 per user per tenant, enforced by the writers.';
COMMENT ON COLUMN apiome.project_pins.pinned_at IS
    'When the member pinned the project; pinned lists sort by it, newest first';
