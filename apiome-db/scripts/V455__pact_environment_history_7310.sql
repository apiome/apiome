-- What-is-where board and history — PFX-8.13 (#7310).
--
-- The Environments page gains a **History** view: who deployed, released, undeployed or ended
-- support for what, and whether can-i-deploy said yes when it was recorded. V435 kept who *recorded*
-- each deployment and release, but not who ended it, why a deployment ended, which deployment a new
-- one replaced, or the verdict at the time. This adds them:
--
--   * `recorded_verdict` (both tables) — can-i-deploy's answer for the version and environment when
--     apiome-rest recorded it: `deployable`, `not-deployable` or `unknown` (a verification is still
--     missing). NULL is "not known": recorded before this migration, or imported from another broker.
--     A deployment's verdict never changes; recording a release again stores the new answer.
--   * `ended_actor_label` (both tables) — who ended the deployment (an undeployment, or the
--     deployment that replaced it) or the support. Set only when it ends.
--   * `deployed_version.ended_reason` — `replaced` (a newer version was deployed to the same
--     instance) or `undeployed` (`record-undeployment`). NULL while deployed, and for a deployment
--     that ended before this migration and could not be matched to the one that replaced it.
--   * `deployed_version.replaced_id` — the deployment this one replaced, so the history can say
--     "Replaced 2.6.1". Set NULL if that row is ever removed with its version.
--
-- The history guards of V435 are widened only as far as these columns need: a deployment's
-- `ended_actor_label` / `ended_reason` are written once, when it ends; `replaced_id` may only be
-- cleared (the foreign key's ON DELETE SET NULL); a release's verdict and label move with its support.
--
-- Backfill: a deployment ended before this migration is marked `replaced` (and the replacing row's
-- `replaced_id` set) when the next deployment of the same pacticipant to the same environment and
-- instance was recorded at the instant it ended — the same transaction, as apiome-rest records a
-- replacement. The guard trigger is disabled for those two statements only.
--
-- The tenant-wide history reads each event kind newest first; the four indexes keep each page a
-- bounded index scan (apiome-db plan-check: pact.environment_history_*).
--
-- Online: nullable columns without defaults (catalog-only), an UPDATE over the ended deployments
-- (a small table: one row per recorded deployment), and five index builds.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP INDEX IF EXISTS apiome.idx_deployed_version_tenant_recorded;
--   DROP INDEX IF EXISTS apiome.idx_deployed_version_tenant_undeployed;
--   DROP INDEX IF EXISTS apiome.idx_deployed_version_replaced;
--   DROP INDEX IF EXISTS apiome.idx_released_version_tenant_recorded;
--   DROP INDEX IF EXISTS apiome.idx_released_version_tenant_support_ended;
--   ALTER TABLE apiome.deployed_version DROP COLUMN IF EXISTS recorded_verdict,
--       DROP COLUMN IF EXISTS ended_actor_label, DROP COLUMN IF EXISTS ended_reason,
--       DROP COLUMN IF EXISTS replaced_id;
--   ALTER TABLE apiome.released_version DROP COLUMN IF EXISTS recorded_verdict,
--       DROP COLUMN IF EXISTS ended_actor_label;
--   then re-run V435's two guard functions.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. Columns
-- ---------------------------------------------------------------------------------------------------

ALTER TABLE deployed_version
    ADD COLUMN IF NOT EXISTS recorded_verdict VARCHAR(16)
        CONSTRAINT deployed_version_recorded_verdict_check
            CHECK (recorded_verdict IS NULL OR recorded_verdict IN ('deployable', 'not-deployable', 'unknown')),
    ADD COLUMN IF NOT EXISTS ended_actor_label TEXT,
    ADD COLUMN IF NOT EXISTS ended_reason VARCHAR(16)
        CONSTRAINT deployed_version_ended_reason_check
            CHECK (ended_reason IS NULL OR ended_reason IN ('replaced', 'undeployed')),
    ADD COLUMN IF NOT EXISTS replaced_id UUID
        CONSTRAINT deployed_version_replaced_fk REFERENCES deployed_version (id) ON DELETE SET NULL;

ALTER TABLE released_version
    ADD COLUMN IF NOT EXISTS recorded_verdict VARCHAR(16)
        CONSTRAINT released_version_recorded_verdict_check
            CHECK (recorded_verdict IS NULL OR recorded_verdict IN ('deployable', 'not-deployable', 'unknown')),
    ADD COLUMN IF NOT EXISTS ended_actor_label TEXT;

COMMENT ON COLUMN deployed_version.recorded_verdict IS
    'can-i-deploy''s answer when it was recorded: deployable, not-deployable or unknown; NULL = not known (PFX-8.13)';
COMMENT ON COLUMN deployed_version.ended_actor_label IS
    'Who ended the deployment (undeployed it, or deployed the version that replaced it) (PFX-8.13)';
COMMENT ON COLUMN deployed_version.ended_reason IS
    'replaced or undeployed; NULL while deployed or when an older ending could not be classified (PFX-8.13)';
COMMENT ON COLUMN deployed_version.replaced_id IS 'The deployment this one replaced in the same instance (PFX-8.13)';
COMMENT ON COLUMN released_version.recorded_verdict IS
    'can-i-deploy''s answer when the release was last recorded; NULL = not known (PFX-8.13)';
COMMENT ON COLUMN released_version.ended_actor_label IS 'Who ended support for the release (PFX-8.13)';

-- ---------------------------------------------------------------------------------------------------
-- 2. Guards
-- ---------------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION apiome.deployed_version_history_guard()
RETURNS trigger AS $$
DECLARE
    ending BOOLEAN := OLD.currently_deployed AND NOT NEW.currently_deployed;
BEGIN
    IF (to_jsonb(NEW) - 'created_by' - 'currently_deployed' - 'undeployed_at' - 'ended_actor_label'
            - 'ended_reason' - 'replaced_id')
           = (to_jsonb(OLD) - 'created_by' - 'currently_deployed' - 'undeployed_at' - 'ended_actor_label'
            - 'ended_reason' - 'replaced_id')
       AND (NEW.created_by IS NULL OR NEW.created_by IS NOT DISTINCT FROM OLD.created_by)
       AND (NEW.currently_deployed = OLD.currently_deployed OR ending)
       AND (OLD.undeployed_at IS NULL OR NEW.undeployed_at IS NOT DISTINCT FROM OLD.undeployed_at)
       AND (ending OR (NEW.ended_actor_label IS NOT DISTINCT FROM OLD.ended_actor_label
                       AND NEW.ended_reason IS NOT DISTINCT FROM OLD.ended_reason))
       AND (NEW.replaced_id IS NULL OR NEW.replaced_id IS NOT DISTINCT FROM OLD.replaced_id) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'deployed_version % can only be marked undeployed, once', OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION apiome.released_version_history_guard()
RETURNS trigger AS $$
BEGIN
    IF (to_jsonb(NEW) - 'created_by' - 'currently_supported' - 'support_ended_at' - 'updated_at'
            - 'recorded_verdict' - 'ended_actor_label')
           = (to_jsonb(OLD) - 'created_by' - 'currently_supported' - 'support_ended_at' - 'updated_at'
            - 'recorded_verdict' - 'ended_actor_label')
       AND (NEW.created_by IS NULL OR NEW.created_by IS NOT DISTINCT FROM OLD.created_by) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'released_version % can only change whether it is supported', OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------------
-- 3. Backfill: which ended deployments were replaced
-- ---------------------------------------------------------------------------------------------------

ALTER TABLE deployed_version DISABLE TRIGGER trg_deployed_version_history_guard;

WITH pairs AS (
    SELECT old.id AS old_id, new.id AS new_id
    FROM deployed_version old
    JOIN LATERAL (
        SELECT n.id, n.created_at
        FROM deployed_version n
        WHERE n.environment_id = old.environment_id
          AND n.pacticipant_id = old.pacticipant_id
          AND COALESCE(n.application_instance, '') = COALESCE(old.application_instance, '')
          AND n.seq > old.seq
        ORDER BY n.seq
        LIMIT 1
    ) new ON new.created_at = old.undeployed_at
    WHERE NOT old.currently_deployed AND old.ended_reason IS NULL
)
UPDATE deployed_version d
SET ended_reason = 'replaced'
FROM pairs
WHERE d.id = pairs.old_id;

UPDATE deployed_version n
SET replaced_id = old.id
FROM deployed_version old
WHERE old.ended_reason = 'replaced'
  AND n.replaced_id IS NULL
  AND n.environment_id = old.environment_id
  AND n.pacticipant_id = old.pacticipant_id
  AND COALESCE(n.application_instance, '') = COALESCE(old.application_instance, '')
  AND n.created_at = old.undeployed_at
  AND n.seq > old.seq;

ALTER TABLE deployed_version ENABLE TRIGGER trg_deployed_version_history_guard;

-- ---------------------------------------------------------------------------------------------------
-- 4. The history's reads
-- ---------------------------------------------------------------------------------------------------

-- "Deployed" events, newest first.
CREATE INDEX IF NOT EXISTS idx_deployed_version_tenant_recorded
    ON deployed_version (tenant_id, created_at DESC, id DESC);
-- "Undeployed" events. A replacement is told on the deployment that replaced it, so replaced rows
-- (most ended rows) are left out of the index and a page never scans past them.
CREATE INDEX IF NOT EXISTS idx_deployed_version_tenant_undeployed
    ON deployed_version (tenant_id, undeployed_at DESC, id DESC)
    WHERE undeployed_at IS NOT NULL AND ended_reason IS DISTINCT FROM 'replaced';
-- The replaced_id foreign key's check, and "which deployment replaced this one".
CREATE INDEX IF NOT EXISTS idx_deployed_version_replaced
    ON deployed_version (replaced_id)
    WHERE replaced_id IS NOT NULL;
-- "Released" events.
CREATE INDEX IF NOT EXISTS idx_released_version_tenant_recorded
    ON released_version (tenant_id, created_at DESC, id DESC);
-- "Support ended" events.
CREATE INDEX IF NOT EXISTS idx_released_version_tenant_support_ended
    ON released_version (tenant_id, support_ended_at DESC, id DESC)
    WHERE support_ended_at IS NOT NULL;

COMMENT ON INDEX idx_deployed_version_tenant_recorded IS 'The environment history''s deployed events (PFX-8.13, #7310)';
COMMENT ON INDEX idx_deployed_version_tenant_undeployed IS
    'The environment history''s undeployed events (PFX-8.13, #7310)';
COMMENT ON INDEX idx_deployed_version_replaced IS 'deployed_version.replaced_id lookups and FK check (PFX-8.13, #7310)';
COMMENT ON INDEX idx_released_version_tenant_recorded IS 'The environment history''s released events (PFX-8.13, #7310)';
COMMENT ON INDEX idx_released_version_tenant_support_ended IS
    'The environment history''s support-ended events (PFX-8.13, #7310)';
