-- Catalog item refresh: per-item live-source cadence and the tenant kill switch (MFI-31.1, #4398).
--
-- A catalog item (a `projects` row with `publishable = false`) can opt in to being re-checked
-- against the live source it describes: a GraphQL endpoint (introspection) or a gRPC server
-- (reflection). The background sweep in apiome-rest (`app.catalog_refresh_sweep`) walks the due
-- rows, runs the adapter's live discovery under a global concurrency cap and a per-host
-- politeness delay, and records the outcome here. A failed check backs off exponentially and
-- shows as `failed`; it never creates a version, so the item's history is untouched.
--
--   1. `catalog_item_refresh` — one row per item that has a live source. The cadence is
--      `off` (the default: stored but never checked), `manual` (checked only on request) or
--      `hourly` / `daily` / `weekly` (checked by the sweep). The credential is sealed by the
--      envelope `mcp_endpoint_credentials` uses (`app.mcp_credential_crypto`); no route reads it
--      back. Deleting the item deletes its row.
--   2. `tenants.catalog_refresh_enabled` — the tenant kill switch. FALSE stops the sweep for
--      every item in the tenant without touching the per-item settings.
--
-- Rollback:
--   ALTER TABLE apiome.tenants DROP COLUMN IF EXISTS catalog_refresh_enabled;
--   DROP TABLE IF EXISTS apiome.catalog_item_refresh;
SET search_path TO apiome, public;

-- ─── 1. Per-item refresh settings and status ─────────────────────────────────

CREATE TABLE IF NOT EXISTS apiome.catalog_item_refresh (
    project_id           UUID PRIMARY KEY REFERENCES apiome.projects(id) ON DELETE CASCADE,
    tenant_id            UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
    cadence              VARCHAR(16) NOT NULL DEFAULT 'off'
                         CHECK (cadence IN ('off', 'manual', 'hourly', 'daily', 'weekly')),
    -- The import adapter that discovers the source (`graphql`, `grpc`). The app accepts only
    -- adapters that declare supports_live_discovery and have a discovery runner.
    adapter_key          VARCHAR(64) NOT NULL,
    -- The live endpoint (a URL, or a host:port target for gRPC). SSRF-checked when written and
    -- again on every call.
    endpoint             TEXT NOT NULL,
    options              JSONB NOT NULL DEFAULT '{}'::jsonb,
    auth_type            VARCHAR(16) NOT NULL DEFAULT 'none'
                         CHECK (auth_type IN ('none', 'bearer', 'header', 'oauth2')),
    -- Sealed by app.mcp_credential_crypto (AES-256-GCM envelope). Never plaintext.
    encrypted_payload    BYTEA,
    key_version          INTEGER,
    status               VARCHAR(16) NOT NULL DEFAULT 'never'
                         CHECK (status IN ('never', 'unchanged', 'changed', 'failed')),
    last_checked_at      TIMESTAMPTZ,
    last_success_at      TIMESTAMPTZ,
    last_failure_at      TIMESTAMPTZ,
    last_error           TEXT,
    last_fingerprint     TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    -- Exponential backoff after a failure: the sweep skips the row until this time.
    next_check_after     TIMESTAMPTZ,
    created_by           UUID,
    updated_by           UUID,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_catalog_item_refresh_sealed_pair
        CHECK ((encrypted_payload IS NULL) = (key_version IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_catalog_item_refresh_tenant
    ON apiome.catalog_item_refresh (tenant_id);

-- Due-selection for the sweep: only scheduled cadences, oldest check first.
CREATE INDEX IF NOT EXISTS idx_catalog_item_refresh_due
    ON apiome.catalog_item_refresh (last_checked_at NULLS FIRST)
    WHERE cadence IN ('hourly', 'daily', 'weekly');

COMMENT ON TABLE apiome.catalog_item_refresh IS
    'Per-catalog-item live-source refresh (MFI-31.1): cadence, the source to re-discover, a sealed credential and the last check outcome. A failed check never creates a version.';
COMMENT ON COLUMN apiome.catalog_item_refresh.status IS
    'never (not checked yet) | unchanged (the live fingerprint matches the last one) | changed (it differs) | failed (the last check failed; see last_error and next_check_after).';

-- ─── 2. Tenant kill switch ───────────────────────────────────────────────────

ALTER TABLE apiome.tenants
    ADD COLUMN IF NOT EXISTS catalog_refresh_enabled BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN apiome.tenants.catalog_refresh_enabled IS
    'Tenant kill switch for catalog item refresh (MFI-31.1). FALSE stops the scheduled sweep and manual checks for the tenant; per-item settings are kept.';
