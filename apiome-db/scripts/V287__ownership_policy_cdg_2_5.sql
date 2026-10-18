-- Unowned-entity policy — CDG-2.5 (#5964).
--
-- Two tenant settings close the gaps CDG-2.3 left open:
--
--   unowned_findings_team_id — the **catch-all team**. A finding on an entity with no confirmed
--       owner (CDG-2.3 records it in `unowned_findings`) is also routed to this team, so it reaches a
--       person and not only a report. NULL means no catch-all: the report alone, as before.
--       ON DELETE SET NULL: hard-deleting the team turns the catch-all off rather than failing; a
--       soft-deleted team is ignored by routing (and reported as drift).
--
--   require_owner_to_publish — the **owner gate**. When on, publishing a version of a project
--       with no confirmed owner is refused with reason `no-owner` (after the COL-2.3 approval
--       gate). Off by default, and the publish dialog says so either way.
--
-- Rollback notes:
--   ALTER TABLE apiome.tenants DROP COLUMN IF EXISTS require_owner_to_publish,
--                              DROP COLUMN IF EXISTS unowned_findings_team_id;

SET search_path TO apiome, public;

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS unowned_findings_team_id UUID REFERENCES teams(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS require_owner_to_publish BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN tenants.unowned_findings_team_id IS
    'Catch-all team that receives findings on entities with no confirmed owner (CDG-2.5); NULL = report only';
COMMENT ON COLUMN tenants.require_owner_to_publish IS
    'When true, publishing a version of a project with no confirmed owner is refused (reason no-owner, CDG-2.5)';
