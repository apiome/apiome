-- Keep-in-sync: a finished migration copied again on a schedule until it is switched off — PFX-8.17 (#7314).
--
-- Pipelines move from the old broker to Apiome one at a time, so pacts published to the old broker
-- after the copy would be lost. The wizard's **Switch over** step can keep copying: every
-- `interval_seconds` the migration run is set running again, and — because it skips the source keys
-- it already imported (pact_migration_run_done, V458) — brings over only what is new.
--
--   pact_migration_sync — one row per migration run that has been kept in sync: whether it still
--     is, how often, the source's sealed credentials while it is, when it last ran and succeeded,
--     since when the source could not be reached, and why it stopped.
--
-- Rules kept by the database:
--
--   1. **Credentials only while it is on.** A scheduled copy has no one to ask for the token, so it is
--      kept — sealed by the envelope cipher (AES-256-GCM, a per-secret data key wrapped by a versioned
--      master key), never in clear — exactly while keep-in-sync is on. Switching it off, or the sync
--      stopping itself, clears it (`enabled = (credential_ciphertext IS NOT NULL)`).
--   2. **One kept-in-sync migration per workspace**, like one running migration: a partial unique
--      index allows a single enabled row per tenant.
--   3. **Nothing crosses a tenant.** A sync carries its tenant and goes with its run.
--
-- Online: one new table and its indexes; nothing existing is touched.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.pact_migration_sync;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS pact_migration_sync (
    run_id UUID PRIMARY KEY REFERENCES pact_migration_run(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    interval_seconds INTEGER NOT NULL DEFAULT 900,

    credential_ciphertext BYTEA,
    key_version INTEGER,

    next_run_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_pass_at TIMESTAMP WITH TIME ZONE,
    last_success_at TIMESTAMP WITH TIME ZONE,
    unreachable_since TIMESTAMP WITH TIME ZONE,
    passes INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    stopped_reason TEXT,

    enabled_by UUID REFERENCES users(id) ON DELETE SET NULL,
    enabled_by_label TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pact_migration_sync_interval_check CHECK (interval_seconds BETWEEN 300 AND 86400),
    CONSTRAINT pact_migration_sync_credentials_check CHECK (enabled = (credential_ciphertext IS NOT NULL)),
    CONSTRAINT pact_migration_sync_key_version_check CHECK ((credential_ciphertext IS NULL) = (key_version IS NULL)),
    CONSTRAINT pact_migration_sync_passes_check CHECK (passes >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pact_migration_sync_one_enabled
    ON pact_migration_sync (tenant_id) WHERE enabled;

CREATE INDEX IF NOT EXISTS idx_pact_migration_sync_tenant
    ON pact_migration_sync (tenant_id);

CREATE INDEX IF NOT EXISTS idx_pact_migration_sync_due
    ON pact_migration_sync (next_run_at) WHERE enabled;

CREATE INDEX IF NOT EXISTS idx_pact_migration_sync_enabled_by
    ON pact_migration_sync (enabled_by) WHERE enabled_by IS NOT NULL;

COMMENT ON TABLE pact_migration_sync IS
    'A migration run copied again on a schedule until switched off: keep-in-sync (PFX-8.17, #7314)';
COMMENT ON COLUMN pact_migration_sync.enabled IS 'Whether the run is still copied on a schedule';
COMMENT ON COLUMN pact_migration_sync.interval_seconds IS 'How often it is copied again (5 minutes to a day)';
COMMENT ON COLUMN pact_migration_sync.credential_ciphertext IS
    'The source''s token or username and password, sealed (envelope cipher OPMS); held exactly while enabled';
COMMENT ON COLUMN pact_migration_sync.key_version IS 'The master key version that sealed the credentials';
COMMENT ON COLUMN pact_migration_sync.next_run_at IS 'When the next pass is due';
COMMENT ON COLUMN pact_migration_sync.unreachable_since IS
    'Since when the source could not be read; after 24 hours the sync stops itself and says so';
COMMENT ON COLUMN pact_migration_sync.stopped_reason IS 'Why the sync stopped itself, for the Switch over step';
