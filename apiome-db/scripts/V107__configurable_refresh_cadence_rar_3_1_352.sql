-- Configurable refresh cadence (RAR-3.1, #3522).
--
-- The repository auto-refresh sweep was a hardcoded, global `await asyncio.sleep(5)`
-- (`apiome-rest/src/app/main.py:179`); "refresh after a few minutes" could not
-- be expressed per repository. Two columns make the cadence configurable and give
-- the sweep (RAR-3.2) a due-selection anchor:
--
--   1. `refresh_interval_seconds` — per-repo refresh cadence in seconds. Defaults to
--      300 (~5 minutes), the v1 default behaviour. A global floor
--      (`APIOME_REFRESH_MIN_INTERVAL`, default 60s) clamps sub-floor values at
--      read time in the application; the CHECK below only enforces a positive value.
--   2. `last_refreshed_at` — the timestamp of the last refresh sweep tick for this
--      repository. The sweep selects due repos via
--      `last_refreshed_at IS NULL OR now() - last_refreshed_at >= interval` and
--      advances it each tick (RAR-3.2).
SET search_path TO apiome, public;

ALTER TABLE apiome.tenant_repositories
  ADD COLUMN IF NOT EXISTS refresh_interval_seconds INTEGER NOT NULL DEFAULT 300,
  ADD COLUMN IF NOT EXISTS last_refreshed_at TIMESTAMPTZ;

-- Reject non-positive cadences outright; the configurable floor (default 60s) is
-- applied in the application so it can be tuned per environment without a migration.
ALTER TABLE apiome.tenant_repositories
  DROP CONSTRAINT IF EXISTS ck_tenant_repositories_refresh_interval_positive;
ALTER TABLE apiome.tenant_repositories
  ADD CONSTRAINT ck_tenant_repositories_refresh_interval_positive
  CHECK (refresh_interval_seconds > 0);

COMMENT ON COLUMN apiome.tenant_repositories.refresh_interval_seconds IS
  'Per-repo auto-refresh cadence in seconds (RAR-3.1). Default 300 (~5 min); the global APIOME_REFRESH_MIN_INTERVAL floor (default 60s) clamps sub-floor values at read time.';

COMMENT ON COLUMN apiome.tenant_repositories.last_refreshed_at IS
  'Timestamp of the last auto-refresh sweep tick for this repository (RAR-3.1); the sweep picks repos where now() - last_refreshed_at >= refresh_interval_seconds and advances it each tick (RAR-3.2).';
