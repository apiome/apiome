-- Enable/disable auto-refresh per repository (RAR-3.3, #3524).
--
-- The auto-refresh sweep (RAR-3.2) refreshes every scannable repository on its
-- configured cadence (RAR-3.1). Acceptance criteria for #3524 require a per-repo
-- opt-out so a repo owner can turn auto-refresh off for a single repository,
-- independent of the global `APIOME_REFRESH_ENABLED` kill switch (applied in
-- the application, not the schema).
--
--   `auto_refresh_enabled` — BOOLEAN NOT NULL DEFAULT TRUE. When FALSE the sweep's
--      due-selection (`list_due_repositories`) skips the repository, so it is never
--      auto-refreshed. Defaults to TRUE so existing repositories keep refreshing.
--      Manual "Refresh Now" (RAR-5.2) does not consult this flag.
SET search_path TO apiome, public;

ALTER TABLE apiome.tenant_repositories
  ADD COLUMN IF NOT EXISTS auto_refresh_enabled BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN apiome.tenant_repositories.auto_refresh_enabled IS
  'Per-repo auto-refresh opt-out (RAR-3.3). TRUE (default) lets the refresh sweep pick this repo on its cadence; FALSE makes list_due_repositories skip it. Independent of the global APIOME_REFRESH_ENABLED kill switch and of manual Refresh Now (RAR-5.2).';
