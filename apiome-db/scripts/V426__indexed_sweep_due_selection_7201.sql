-- Indexed due-selection for the periodic sweeps (DBP-1.18, #7201).
--
-- Each sweep in apiome-rest used to find its work by evaluating `last_* <= now() - interval` on
-- every row of its table, sorting the survivors and returning all of them. This migration stores
-- the instant each row next falls due, keeps it current with triggers, and indexes it, so a
-- sweep's selection is a range scan that stops after one batch — also when nothing is due.
--
--   * mcp_endpoints.discovery_due_at — when an endpoint with its own discovery_cadence_seconds is
--     next due for re-discovery: last_discovered_at + cadence, pushed back to the failure backoff
--     (next_discovery_after). NULL for an endpoint that inherits the global default cadence, which
--     only the REST process knows; those rows are selected by
--     idx_mcp_endpoints_discovery_due_default on COALESCE(last_discovered_at, '-infinity').
--   * mcp_endpoints.last_health_checked_at — the newest mcp_endpoint_health_checks.checked_at,
--     written by the REST insert of a probe (Database.record_mcp_health_check) and backfilled
--     here, so the health sweep no longer runs max(checked_at) per endpoint.
--   * tenant_repositories.refresh_due_at — last_refreshed_at plus the shortest cadence of the
--     repository and its enabled branch rules ('-infinity' when never refreshed). The global floor
--     (APIOME_REFRESH_MIN_INTERVAL) stays a filter in the query; per-repository cadences are
--     validated against it on write, so the filter rarely discards a row.
--   * mcp_catalog_digest_configs.digest_due_at — last_digest_at + cadence_seconds for a tenant
--     with its own cadence; NULL otherwise, like discovery_due_at.
--   * idx_mcp_discovery_jobs_terminal_created / _terminal_endpoint — the retention prune of
--     finished discovery jobs (Database.prune_mcp_discovery_jobs) reads them oldest first in
--     bounded windows and checks each against its endpoint's newest finished jobs.
--   * idx_mcp_endpoint_versions_endpoint_moved_at — the catalog digest's window reads
--     (grade movements, catalog changes) range over one endpoint's snapshots by time.
--
-- `-infinity` (never ran) sorts before every real instant, so "never ran" and "overdue" are one
-- range: COALESCE(x, '-infinity') <= now() - cadence.
--
-- Large databases: the ALTERs add nullable columns without a rewrite; the backfill UPDATEs touch
-- every row of mcp_endpoints, tenant_repositories and mcp_catalog_digest_configs once, and the
-- health backfill reads mcp_endpoint_health_checks once. The index builds block writes to their
-- tables while they run; to avoid that, create them by hand with CONCURRENTLY (same names and
-- definitions) before upgrading — every statement below is IF NOT EXISTS.
--
-- Rollback notes:
--   DROP TRIGGER IF EXISTS trg_mcp_endpoints_discovery_due ON apiome.mcp_endpoints;
--   DROP TRIGGER IF EXISTS trg_tenant_repositories_refresh_due ON apiome.tenant_repositories;
--   DROP TRIGGER IF EXISTS trg_repository_branch_refresh_rule_due ON apiome.repository_branch_refresh_rule;
--   DROP TRIGGER IF EXISTS trg_mcp_catalog_digest_configs_due ON apiome.mcp_catalog_digest_configs;
--   DROP FUNCTION IF EXISTS apiome.mcp_endpoints_set_discovery_due();
--   DROP FUNCTION IF EXISTS apiome.tenant_repositories_set_refresh_due();
--   DROP FUNCTION IF EXISTS apiome.repository_branch_refresh_rule_touch_due();
--   DROP FUNCTION IF EXISTS apiome.mcp_catalog_digest_configs_set_due();
--   DROP FUNCTION IF EXISTS apiome.tenant_repository_refresh_due_at(uuid, timestamptz, integer);
--   DROP INDEX IF EXISTS apiome.idx_mcp_endpoints_discovery_due;
--   DROP INDEX IF EXISTS apiome.idx_mcp_endpoints_discovery_due_default;
--   DROP INDEX IF EXISTS apiome.idx_mcp_endpoints_health_due;
--   DROP INDEX IF EXISTS apiome.idx_tenant_repositories_refresh_due;
--   DROP INDEX IF EXISTS apiome.idx_mcp_catalog_digest_configs_due;
--   DROP INDEX IF EXISTS apiome.idx_mcp_catalog_digest_configs_due_default;
--   DROP INDEX IF EXISTS apiome.idx_mcp_discovery_jobs_terminal_created;
--   DROP INDEX IF EXISTS apiome.idx_mcp_discovery_jobs_terminal_endpoint;
--   DROP INDEX IF EXISTS apiome.idx_mcp_endpoint_versions_endpoint_moved_at;
--   ALTER TABLE apiome.mcp_endpoints DROP COLUMN IF EXISTS discovery_due_at,
--                                    DROP COLUMN IF EXISTS last_health_checked_at;
--   ALTER TABLE apiome.tenant_repositories DROP COLUMN IF EXISTS refresh_due_at;
--   ALTER TABLE apiome.mcp_catalog_digest_configs DROP COLUMN IF EXISTS digest_due_at;
--   (and restore the per-row interval predicates in the REST due queries).

-- ─── 1. MCP endpoint re-discovery ────────────────────────────────────────────────────────────

ALTER TABLE apiome.mcp_endpoints
    ADD COLUMN IF NOT EXISTS discovery_due_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_health_checked_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN apiome.mcp_endpoints.discovery_due_at IS
    'When an endpoint with its own discovery_cadence_seconds is next due for re-discovery: last_discovered_at + cadence, no earlier than next_discovery_after (-infinity when never discovered). NULL when the cadence is inherited from the global default. Maintained by trg_mcp_endpoints_discovery_due (DBP-1.18, #7201).';
COMMENT ON COLUMN apiome.mcp_endpoints.last_health_checked_at IS
    'The newest mcp_endpoint_health_checks.checked_at of this endpoint, written with each probe so the health sweep selects due endpoints from an index (DBP-1.18, #7201).';

CREATE OR REPLACE FUNCTION apiome.mcp_endpoints_set_discovery_due()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.discovery_cadence_seconds IS NULL THEN
        NEW.discovery_due_at := NULL;
    ELSE
        NEW.discovery_due_at := GREATEST(
            COALESCE(NEW.last_discovered_at + make_interval(secs => NEW.discovery_cadence_seconds),
                     '-infinity'::timestamptz),
            COALESCE(NEW.next_discovery_after, '-infinity'::timestamptz)
        );
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_mcp_endpoints_discovery_due ON apiome.mcp_endpoints;
CREATE TRIGGER trg_mcp_endpoints_discovery_due
    BEFORE INSERT OR UPDATE OF last_discovered_at, discovery_cadence_seconds, next_discovery_after
    ON apiome.mcp_endpoints
    FOR EACH ROW
    EXECUTE FUNCTION apiome.mcp_endpoints_set_discovery_due();

UPDATE apiome.mcp_endpoints
   SET discovery_due_at = GREATEST(
           COALESCE(last_discovered_at + make_interval(secs => discovery_cadence_seconds),
                    '-infinity'::timestamptz),
           COALESCE(next_discovery_after, '-infinity'::timestamptz))
 WHERE discovery_cadence_seconds IS NOT NULL;

-- Endpoints with their own cadence, in due order.
CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_discovery_due
    ON apiome.mcp_endpoints (discovery_due_at)
    WHERE deleted_at IS NULL AND enabled AND quarantined_at IS NULL
      AND discovery_cadence_seconds IS NOT NULL;

-- Endpoints on the global default cadence, never-discovered first.
CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_discovery_due_default
    ON apiome.mcp_endpoints ((COALESCE(last_discovered_at, '-infinity'::timestamptz)))
    WHERE deleted_at IS NULL AND enabled AND quarantined_at IS NULL
      AND discovery_cadence_seconds IS NULL;

-- ─── 2. MCP endpoint health probes ───────────────────────────────────────────────────────────

UPDATE apiome.mcp_endpoints e
   SET last_health_checked_at = h.last_checked_at
  FROM (
        SELECT endpoint_id, max(checked_at) AS last_checked_at
          FROM apiome.mcp_endpoint_health_checks
         GROUP BY endpoint_id
       ) h
 WHERE h.endpoint_id = e.id
   AND e.last_health_checked_at IS DISTINCT FROM h.last_checked_at;

CREATE INDEX IF NOT EXISTS idx_mcp_endpoints_health_due
    ON apiome.mcp_endpoints ((COALESCE(last_health_checked_at, '-infinity'::timestamptz)), created_at)
    WHERE deleted_at IS NULL AND enabled AND transport <> 'stdio';

-- ─── 3. Repository auto-refresh ──────────────────────────────────────────────────────────────

ALTER TABLE apiome.tenant_repositories
    ADD COLUMN IF NOT EXISTS refresh_due_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN apiome.tenant_repositories.refresh_due_at IS
    'When the repository is next due for an auto-refresh tick: last_refreshed_at plus the shortest cadence of the repository and its enabled branch rules (-infinity when never refreshed). The global floor is applied by the query. Maintained by trg_tenant_repositories_refresh_due and trg_repository_branch_refresh_rule_due (DBP-1.18, #7201).';

-- The due instant of one repository, from its anchor, its own cadence and its enabled branch rules.
CREATE OR REPLACE FUNCTION apiome.tenant_repository_refresh_due_at(
    p_repository_id uuid,
    p_last_refreshed_at timestamptz,
    p_interval_seconds integer
)
RETURNS timestamptz
LANGUAGE sql
STABLE
AS $$
    SELECT CASE
        WHEN p_last_refreshed_at IS NULL THEN '-infinity'::timestamptz
        ELSE p_last_refreshed_at + make_interval(secs => LEAST(
            p_interval_seconds,
            (SELECT min(r.refresh_interval_seconds)
               FROM apiome.repository_branch_refresh_rule r
              WHERE r.repository_id = p_repository_id AND r.refresh_enabled)
        ))
    END
$$;

CREATE OR REPLACE FUNCTION apiome.tenant_repositories_set_refresh_due()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.refresh_due_at := apiome.tenant_repository_refresh_due_at(
        NEW.id, NEW.last_refreshed_at, NEW.refresh_interval_seconds);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_tenant_repositories_refresh_due ON apiome.tenant_repositories;
CREATE TRIGGER trg_tenant_repositories_refresh_due
    BEFORE INSERT OR UPDATE OF last_refreshed_at, refresh_interval_seconds
    ON apiome.tenant_repositories
    FOR EACH ROW
    EXECUTE FUNCTION apiome.tenant_repositories_set_refresh_due();

-- A branch rule change moves its repository's due instant.
CREATE OR REPLACE FUNCTION apiome.repository_branch_refresh_rule_touch_due()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_repository_id uuid;
BEGIN
    FOR v_repository_id IN
        SELECT DISTINCT x FROM unnest(ARRAY[
            CASE WHEN TG_OP <> 'INSERT' THEN OLD.repository_id END,
            CASE WHEN TG_OP <> 'DELETE' THEN NEW.repository_id END
        ]) AS x WHERE x IS NOT NULL
    LOOP
        UPDATE apiome.tenant_repositories t
           SET refresh_due_at = apiome.tenant_repository_refresh_due_at(
                   t.id, t.last_refreshed_at, t.refresh_interval_seconds)
         WHERE t.id = v_repository_id;
    END LOOP;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_repository_branch_refresh_rule_due ON apiome.repository_branch_refresh_rule;
CREATE TRIGGER trg_repository_branch_refresh_rule_due
    AFTER INSERT OR DELETE OR UPDATE OF repository_id, refresh_enabled, refresh_interval_seconds
    ON apiome.repository_branch_refresh_rule
    FOR EACH ROW
    EXECUTE FUNCTION apiome.repository_branch_refresh_rule_touch_due();

UPDATE apiome.tenant_repositories t
   SET refresh_due_at = apiome.tenant_repository_refresh_due_at(
           t.id, t.last_refreshed_at, t.refresh_interval_seconds);

CREATE INDEX IF NOT EXISTS idx_tenant_repositories_refresh_due
    ON apiome.tenant_repositories (refresh_due_at, created_at)
    WHERE deleted_at IS NULL AND status IN ('ready', 'error')
      AND auto_refresh_enabled AND refresh_paused_at IS NULL;

-- ─── 4. MCP catalog digests ──────────────────────────────────────────────────────────────────

ALTER TABLE apiome.mcp_catalog_digest_configs
    ADD COLUMN IF NOT EXISTS digest_due_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN apiome.mcp_catalog_digest_configs.digest_due_at IS
    'When a tenant with its own cadence_seconds is next due for a digest: last_digest_at + cadence (-infinity when never sent). NULL when the cadence is the global default. Maintained by trg_mcp_catalog_digest_configs_due (DBP-1.18, #7201).';

CREATE OR REPLACE FUNCTION apiome.mcp_catalog_digest_configs_set_due()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.cadence_seconds IS NULL THEN
        NEW.digest_due_at := NULL;
    ELSE
        NEW.digest_due_at := COALESCE(
            NEW.last_digest_at + make_interval(secs => NEW.cadence_seconds), '-infinity'::timestamptz);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_mcp_catalog_digest_configs_due ON apiome.mcp_catalog_digest_configs;
CREATE TRIGGER trg_mcp_catalog_digest_configs_due
    BEFORE INSERT OR UPDATE OF last_digest_at, cadence_seconds
    ON apiome.mcp_catalog_digest_configs
    FOR EACH ROW
    EXECUTE FUNCTION apiome.mcp_catalog_digest_configs_set_due();

UPDATE apiome.mcp_catalog_digest_configs
   SET digest_due_at = COALESCE(last_digest_at + make_interval(secs => cadence_seconds),
                                '-infinity'::timestamptz)
 WHERE cadence_seconds IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_catalog_digest_configs_due
    ON apiome.mcp_catalog_digest_configs (digest_due_at)
    WHERE enabled AND cadence_seconds IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_mcp_catalog_digest_configs_due_default
    ON apiome.mcp_catalog_digest_configs ((COALESCE(last_digest_at, '-infinity'::timestamptz)))
    WHERE enabled AND cadence_seconds IS NULL;

-- ─── 5. Discovery job retention ──────────────────────────────────────────────────────────────

-- The prune walks finished jobs oldest first, one bounded window per batch, resuming after the last
-- (created_at, id) it saw.
CREATE INDEX IF NOT EXISTS idx_mcp_discovery_jobs_terminal_created
    ON apiome.mcp_discovery_jobs (created_at, id)
    WHERE state IN ('completed', 'failed');

-- "Is this one of its endpoint's newest finished jobs?" — an index-only probe.
CREATE INDEX IF NOT EXISTS idx_mcp_discovery_jobs_terminal_endpoint
    ON apiome.mcp_discovery_jobs (endpoint_id, created_at DESC, id DESC)
    WHERE state IN ('completed', 'failed');

-- ─── 6. Digest grade movements ───────────────────────────────────────────────────────────────

-- The digest reads an endpoint's snapshots inside a time window (COALESCE(discovered_at,
-- created_at)); this makes that a range per endpoint instead of a scan of every snapshot.
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_versions_endpoint_moved_at
    ON apiome.mcp_endpoint_versions (endpoint_id, (COALESCE(discovered_at, created_at)));
