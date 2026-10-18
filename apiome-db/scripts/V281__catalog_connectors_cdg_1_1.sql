-- Catalog connectors: the connector registry and the shared refresh-run ledger (CDG-1.1, #5952).
--
-- A connector is a second *source* for the repository auto-refresh engine, not a second
-- engine. A Git repository gives the engine branches and files; a connector gives it the
-- inventory of an API gateway, a registry or a URL. Both go through the same
-- `app.refresh_source.RefreshSource` protocol, the same tenant quota window and the same
-- run ledger, so a tenant has one cadence vocabulary, one quota and one audit trail.
--
-- The roadmap names this migration V274; V274–V280 were taken by the time it landed.
--
--   1. `catalog_connectors` — one row per registered source. `kind` is the source family;
--      only the families with a `RefreshSource` registered in apiome-rest can sync (the
--      others are CDG-1.2–1.7 and RAR-6.1). `scope` holds the kind-specific coordinates
--      (control-plane ids, region/account, resource group, org/env). The cadence is the
--      RAR-3.1 vocabulary (`refresh_interval_seconds`, floor-clamped in the app) and the
--      conflict policy reuses the RAR-4.5 values. Connectors are soft-deleted.
--   2. `catalog_connector_items` — the inventory: one row per remote API the connector has
--      ever seen. An API that disappears from the inventory is marked `missing`, never
--      deleted, and its catalog item (a `projects` row with `publishable = false`) is kept.
--   3. `catalog_connector_credentials` — one sealed credential per connector. Ciphertext
--      only, sealed by the envelope `mcp_endpoint_credentials` uses (`app.mcp_credential_crypto`).
--      A credential is replaced, never edited, and no route reads it back.
--   4. `tenant_repository_refresh_jobs` gains connector runs. A Git row stays a per-file
--      re-import job; a connector row is one sync run. `refresh_source` tells them apart
--      (the existing `source_kind` column already holds the *import* kind, so it could not be
--      reused). Every existing reader filters on `repository_id`, which is NULL on a connector
--      row, so none of them sees connector runs by accident.
--
-- Rollback:
--   DELETE FROM apiome.tenant_repository_refresh_jobs WHERE refresh_source = 'connector';
--   ALTER TABLE apiome.tenant_repository_refresh_jobs
--     DROP CONSTRAINT IF EXISTS ck_tenant_repo_refresh_jobs_source_shape,
--     DROP COLUMN IF EXISTS connector_id, DROP COLUMN IF EXISTS refresh_source,
--     DROP COLUMN IF EXISTS pull_count, DROP COLUMN IF EXISTS error_class,
--     DROP COLUMN IF EXISTS http_status, DROP COLUMN IF EXISTS run_summary,
--     ALTER COLUMN repository_id SET NOT NULL, ALTER COLUMN branch SET NOT NULL,
--     ALTER COLUMN path SET NOT NULL;
--   DROP TABLE IF EXISTS apiome.catalog_connector_credentials;
--   DROP TABLE IF EXISTS apiome.catalog_connector_items;
--   DROP TABLE IF EXISTS apiome.catalog_connectors;
SET search_path TO apiome, public;

-- ─── 1. Connectors ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.catalog_connectors (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id                UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    kind                     VARCHAR(32) NOT NULL
                             CHECK (kind IN (
                                 'kong-konnect',
                                 'kong-admin',
                                 'aws-apigateway',
                                 'azure-apim',
                                 'apigee',
                                 'url',
                                 'schema-registry',
                                 'mcp-registry'
                             )),
    name                     VARCHAR(200) NOT NULL,
    -- The control-plane / admin / registry URL. Optional because some kinds are addressed by
    -- scope alone (an AWS region and account). Every value passed the SSRF check when written.
    base_url                 TEXT,
    scope                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- RAR-3.1 cadence: NULL means the deployment default; the app clamps to the floor.
    refresh_interval_seconds INTEGER CHECK (refresh_interval_seconds IS NULL OR refresh_interval_seconds > 0),
    conflict_policy          VARCHAR(32) NOT NULL DEFAULT 'hold-for-review'
                             CHECK (conflict_policy IN ('overwrite', 'hold-for-review', 'new-branch')),
    status                   VARCHAR(16) NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active', 'paused', 'failing')),
    last_run_at              TIMESTAMPTZ,
    created_by               UUID,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at               TIMESTAMPTZ
);

-- A live connector's name is unique in its tenant; a deleted one frees its name.
CREATE UNIQUE INDEX IF NOT EXISTS uq_catalog_connectors_tenant_name_live
    ON apiome.catalog_connectors (tenant_id, lower(name))
    WHERE deleted_at IS NULL;

-- Due-selection for the scheduled sweep: live, active connectors by last run.
CREATE INDEX IF NOT EXISTS idx_catalog_connectors_due
    ON apiome.catalog_connectors (last_run_at NULLS FIRST)
    WHERE deleted_at IS NULL AND status <> 'paused';

COMMENT ON TABLE apiome.catalog_connectors IS
    'Registered catalog connectors (CDG-1.1): non-Git refresh sources (gateways, registries, URLs) synced by the repository auto-refresh engine through the RefreshSource protocol.';
COMMENT ON COLUMN apiome.catalog_connectors.status IS
    'active (synced on its cadence) | paused (skipped by the sweep; manual sync still runs) | failing (the last run failed; the sweep keeps retrying on its cadence).';

-- ─── 2. Inventory ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.catalog_connector_items (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    connector_id      UUID NOT NULL REFERENCES apiome.catalog_connectors(id) ON DELETE CASCADE,
    remote_id         TEXT NOT NULL,
    remote_name       TEXT,
    environment       TEXT,
    hosts             TEXT[] NOT NULL DEFAULT '{}',
    base_path         TEXT,
    remote_revision   TEXT,
    remote_updated_at TIMESTAMPTZ,
    -- The freshness anchor at the last import (the remote_* columns above are what the latest
    -- sync saw). The RAR-2.2 newer-than gate compares the two pairs; the content digest is the
    -- fallback for a remote that reports neither a revision nor an update time.
    imported_revision          TEXT,
    imported_remote_updated_at TIMESTAMPTZ,
    imported_sha256            VARCHAR(64),
    status            VARCHAR(16) NOT NULL DEFAULT 'discovered'
                      CHECK (status IN ('discovered', 'imported', 'ignored', 'missing')),
    -- The catalog item this remote API became. SET NULL, never CASCADE: deleting a catalog
    -- item must not erase the inventory's memory that the API exists.
    project_id        UUID REFERENCES apiome.projects(id) ON DELETE SET NULL,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_catalog_connector_items_remote UNIQUE (connector_id, remote_id)
);

CREATE INDEX IF NOT EXISTS idx_catalog_connector_items_project
    ON apiome.catalog_connector_items (project_id)
    WHERE project_id IS NOT NULL;

COMMENT ON TABLE apiome.catalog_connector_items IS
    'Inventory of the remote APIs a catalog connector has seen (CDG-1.1). Rows are never deleted by a sync: an API gone from the inventory becomes missing.';

-- ─── 3. Credentials ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.catalog_connector_credentials (
    connector_id      UUID PRIMARY KEY REFERENCES apiome.catalog_connectors(id) ON DELETE CASCADE,
    -- Sealed by app.mcp_credential_crypto (AES-256-GCM envelope). Never plaintext.
    encrypted_payload BYTEA NOT NULL,
    key_version       INTEGER NOT NULL,
    created_by        UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    replaced_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE apiome.catalog_connector_credentials IS
    'One sealed credential per catalog connector (CDG-1.1). Write-only: replaced as a whole, never read back by any route.';

-- ─── 4. Connector runs on the shared refresh ledger ──────────────────────────

ALTER TABLE apiome.tenant_repository_refresh_jobs
    ALTER COLUMN repository_id DROP NOT NULL,
    ALTER COLUMN branch DROP NOT NULL,
    ALTER COLUMN path DROP NOT NULL;

ALTER TABLE apiome.tenant_repository_refresh_jobs
    ADD COLUMN IF NOT EXISTS refresh_source VARCHAR(16) NOT NULL DEFAULT 'git',
    ADD COLUMN IF NOT EXISTS connector_id UUID REFERENCES apiome.catalog_connectors(id) ON DELETE CASCADE,
    -- Documents fetched from the remote by this run; what the tenant quota counts for it.
    ADD COLUMN IF NOT EXISTS pull_count INTEGER NOT NULL DEFAULT 0,
    -- A failed connector run names the provider's error class and HTTP status.
    ADD COLUMN IF NOT EXISTS error_class VARCHAR(64),
    ADD COLUMN IF NOT EXISTS http_status SMALLINT,
    -- Per-run counts: trigger, candidates, fetched, imported, unchanged, missing, failed.
    ADD COLUMN IF NOT EXISTS run_summary JSONB;

ALTER TABLE apiome.tenant_repository_refresh_jobs
    DROP CONSTRAINT IF EXISTS ck_tenant_repo_refresh_jobs_source_shape;

-- A Git row is a per-file job of one repository; a connector row is a run of one connector.
ALTER TABLE apiome.tenant_repository_refresh_jobs
    ADD CONSTRAINT ck_tenant_repo_refresh_jobs_source_shape
    CHECK (
        (refresh_source = 'git'
            AND repository_id IS NOT NULL AND branch IS NOT NULL AND path IS NOT NULL
            AND connector_id IS NULL)
        OR (refresh_source = 'connector'
            AND connector_id IS NOT NULL AND repository_id IS NULL)
    );

-- Connector single-flight: at most one active run per connector.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_repo_refresh_jobs_active_connector
    ON apiome.tenant_repository_refresh_jobs (connector_id)
    WHERE refresh_source = 'connector' AND status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_tenant_repo_refresh_jobs_connector
    ON apiome.tenant_repository_refresh_jobs (connector_id, created_at DESC)
    WHERE connector_id IS NOT NULL;

COMMENT ON COLUMN apiome.tenant_repository_refresh_jobs.refresh_source IS
    'git (a per-file re-import job of a tenant repository, RAR-3.2) | connector (one sync run of a catalog connector, CDG-1.1).';
COMMENT ON COLUMN apiome.tenant_repository_refresh_jobs.pull_count IS
    'Remote documents fetched by a connector run; counted against the tenant refresh quota (a Git job counts as one).';
