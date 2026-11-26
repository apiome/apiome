-- Pact tenant isolation — PFX-6.1 (#6953).
--
-- Every Pact Broker table either carries tenant_id itself or reaches its tenant through a
-- composite foreign key, so a row of one tenant can never point at a row of another (V251's rule,
-- applied to the PFX tables V432–V446). Three references were single-column:
--
--   1. push_webhook_delivery_events.pact_webhook_id → pact_webhook (id). The delivery carries its
--      own tenant_id, so a delivery of tenant A could name a webhook of tenant B.
--   2. pact_triggered_webhook.delivery_event_id → push_webhook_delivery_events (id). Both rows
--      carry tenant_id, so a firing of tenant A could name a delivery of tenant B.
--   3. pact_commit_status.repository_id → tenant_repositories (id) (V443). Both rows carry
--      tenant_id, so a commit status of tenant A could name a repository of tenant B.
--
-- Each becomes a composite (…, tenant_id) reference with the same ON DELETE behaviour (CASCADE for
-- 1 and 2; SET NULL (repository_id) for 3, so removing a repository keeps the status). The app
-- already writes all three from one tenant, so existing rows validate; a row that does not fails
-- the migration loudly rather than staying crossed.
--
-- push_webhook_delivery_events and tenant_repositories gain UNIQUE (id, tenant_id) so the
-- references can name them; each new reference gets an index led by its columns (the #7195
-- coverage gate), replacing the single-column ones it supersedes.
--
-- The one PFX reference left single-column is provider_contract_publication.source_version_id →
-- versions (id): versions carries no tenant_id (its tenant is its project's), and the row's
-- source_project_id is already a composite (…, tenant_id) reference.
--
-- Rollback notes:
--   ALTER TABLE apiome.pact_triggered_webhook
--       DROP CONSTRAINT IF EXISTS pact_triggered_webhook_delivery_fk,
--       ADD CONSTRAINT pact_triggered_webhook_delivery_event_id_fkey
--           FOREIGN KEY (delivery_event_id) REFERENCES apiome.push_webhook_delivery_events (id) ON DELETE CASCADE;
--   DROP INDEX IF EXISTS apiome.idx_pact_triggered_webhook_delivery;
--   ALTER TABLE apiome.push_webhook_delivery_events
--       DROP CONSTRAINT IF EXISTS push_webhook_delivery_events_pact_webhook_fk,
--       DROP CONSTRAINT IF EXISTS push_webhook_delivery_events_id_tenant_key,
--       ADD CONSTRAINT push_webhook_delivery_events_pact_webhook_id_fkey
--           FOREIGN KEY (pact_webhook_id) REFERENCES apiome.pact_webhook (id) ON DELETE CASCADE;
--   CREATE INDEX IF NOT EXISTS idx_push_webhook_delivery_events_pact_webhook
--       ON apiome.push_webhook_delivery_events (pact_webhook_id) WHERE pact_webhook_id IS NOT NULL;
--   DROP INDEX IF EXISTS apiome.idx_push_webhook_delivery_events_pact_webhook_tenant;
--   ALTER TABLE apiome.pact_commit_status
--       DROP CONSTRAINT IF EXISTS pact_commit_status_repository_fk,
--       ADD CONSTRAINT pact_commit_status_repository_id_fkey
--           FOREIGN KEY (repository_id) REFERENCES apiome.tenant_repositories (id) ON DELETE SET NULL;
--   ALTER TABLE apiome.tenant_repositories DROP CONSTRAINT IF EXISTS tenant_repositories_id_tenant_key;
--   CREATE INDEX IF NOT EXISTS idx_pact_commit_status_repository
--       ON apiome.pact_commit_status (repository_id) WHERE repository_id IS NOT NULL;
--   DROP INDEX IF EXISTS apiome.idx_pact_commit_status_repository_tenant;

SET search_path TO apiome, public;

-- The keys the composite references need, and the indexes that serve their referential checks.
CREATE INDEX IF NOT EXISTS idx_push_webhook_delivery_events_pact_webhook_tenant
    ON push_webhook_delivery_events (pact_webhook_id, tenant_id) WHERE pact_webhook_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pact_triggered_webhook_delivery
    ON pact_triggered_webhook (delivery_event_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_pact_commit_status_repository_tenant
    ON pact_commit_status (repository_id, tenant_id) WHERE repository_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'push_webhook_delivery_events_id_tenant_key'
          AND conrelid = 'apiome.push_webhook_delivery_events'::regclass
    ) THEN
        ALTER TABLE apiome.push_webhook_delivery_events
            ADD CONSTRAINT push_webhook_delivery_events_id_tenant_key UNIQUE (id, tenant_id);
    END IF;

    -- Rule 1: a delivery fires a webhook of its own tenant.
    ALTER TABLE apiome.push_webhook_delivery_events
        DROP CONSTRAINT IF EXISTS push_webhook_delivery_events_pact_webhook_id_fkey;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'push_webhook_delivery_events_pact_webhook_fk'
          AND conrelid = 'apiome.push_webhook_delivery_events'::regclass
    ) THEN
        ALTER TABLE apiome.push_webhook_delivery_events
            ADD CONSTRAINT push_webhook_delivery_events_pact_webhook_fk
                FOREIGN KEY (pact_webhook_id, tenant_id)
                REFERENCES apiome.pact_webhook (id, tenant_id) ON DELETE CASCADE;
    END IF;

    -- Rule 2: a firing names a delivery of its own tenant.
    ALTER TABLE apiome.pact_triggered_webhook
        DROP CONSTRAINT IF EXISTS pact_triggered_webhook_delivery_event_id_fkey;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pact_triggered_webhook_delivery_fk'
          AND conrelid = 'apiome.pact_triggered_webhook'::regclass
    ) THEN
        ALTER TABLE apiome.pact_triggered_webhook
            ADD CONSTRAINT pact_triggered_webhook_delivery_fk
                FOREIGN KEY (delivery_event_id, tenant_id)
                REFERENCES apiome.push_webhook_delivery_events (id, tenant_id) ON DELETE CASCADE;
    END IF;

    -- Rule 3: a commit status names a repository of its own tenant.
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'tenant_repositories_id_tenant_key'
          AND conrelid = 'apiome.tenant_repositories'::regclass
    ) THEN
        ALTER TABLE apiome.tenant_repositories
            ADD CONSTRAINT tenant_repositories_id_tenant_key UNIQUE (id, tenant_id);
    END IF;
    ALTER TABLE apiome.pact_commit_status
        DROP CONSTRAINT IF EXISTS pact_commit_status_repository_id_fkey;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pact_commit_status_repository_fk'
          AND conrelid = 'apiome.pact_commit_status'::regclass
    ) THEN
        ALTER TABLE apiome.pact_commit_status
            ADD CONSTRAINT pact_commit_status_repository_fk
                FOREIGN KEY (repository_id, tenant_id)
                REFERENCES apiome.tenant_repositories (id, tenant_id) ON DELETE SET NULL (repository_id);
    END IF;
END;
$$;

-- The composite indexes above serve every lookup the single-column ones did.
DROP INDEX IF EXISTS idx_push_webhook_delivery_events_pact_webhook;
DROP INDEX IF EXISTS idx_pact_commit_status_repository;

COMMENT ON INDEX idx_push_webhook_delivery_events_pact_webhook_tenant IS
    'A contract webhook''s deliveries, and the tenant-scoped webhook reference''s check (PFX-6.1, #6953)';
COMMENT ON INDEX idx_pact_triggered_webhook_delivery IS
    'The tenant-scoped delivery reference''s check (PFX-6.1, #6953)';
COMMENT ON INDEX idx_pact_commit_status_repository_tenant IS
    'The tenant-scoped repository reference''s check (PFX-6.1, #6953)';
