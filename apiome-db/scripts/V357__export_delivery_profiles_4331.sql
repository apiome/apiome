-- Export delivery profiles + audit — MFX-38.4 (#4331).
--
-- Git (MFX-38.1), webhook (MFX-38.2) and object-storage (MFX-38.3) delivery each take their
-- destination in the request. A delivery profile makes that destination reusable, auditable
-- configuration: a named, tenant-scoped channel + destination + credential reference that a person,
-- a pipeline or a scheduled export (MFX-39.4) selects by id. Two changes:
--
--   1. `export_delivery_profiles` — one row per profile. `destination` holds the channel's
--      non-secret request fields, exactly as the channel's own delivery endpoint takes them
--      (git: repositoryId / targetPath / baseBranch / mode; webhook: url / artifact; object storage:
--      credentialId / bucket / prefix / partitioning). The credential is a *reference*: the git
--      repository's linked account, or a storage credential in the vault (V356). A webhook's signing
--      secret has nowhere else to live, so it is sealed here (`app.mcp_credential_crypto`,
--      AES-256-GCM) — ciphertext only, never read back by a route.
--
--   2. `delivery_profile_id` on the three run tables — every delivery made from a profile names it,
--      so a job's deliveries and a profile's deliveries can both be listed.
--
-- Four rules shape them:
--
--   * **Tenant-scoped.** A profile belongs to one tenant and is named uniquely within it.
--   * **History outlives configuration.** Runs name their profile `ON DELETE SET NULL`; deleting a
--     profile never deletes a delivery record.
--   * **References, not copies.** A profile does not copy a repository or a storage credential; a
--     reference that no longer resolves is a failed run with the channel's own error code.
--   * **Secrets never leave the vault.** `sealed_secret` is the only secret column, set only for
--     the webhook channel.
--
-- **No new RBAC resource.** Managing a profile is `projects:edit` (listing: `projects:view`), as a
-- storage credential is; delivering with one is `versions:publish`, as every delivery is.
--
-- Rollback notes (reverse carefully in shared environments):
--   ALTER TABLE apiome.export_git_delivery_runs DROP COLUMN IF EXISTS delivery_profile_id;
--   ALTER TABLE apiome.export_webhook_delivery_runs DROP COLUMN IF EXISTS delivery_profile_id;
--   ALTER TABLE apiome.export_object_storage_delivery_runs DROP COLUMN IF EXISTS delivery_profile_id;
--   DROP TABLE IF EXISTS apiome.export_delivery_profiles;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS export_delivery_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    name VARCHAR(120) NOT NULL,
    description TEXT,

    channel VARCHAR(16) NOT NULL
        CONSTRAINT export_delivery_profiles_channel_check
            CHECK (channel IN ('git', 'webhook', 'object_storage')),

    -- The channel's non-secret request fields (camelCase, as its delivery endpoint takes them).
    destination JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT export_delivery_profiles_destination_object_check CHECK (jsonb_typeof(destination) = 'object'),

    -- The webhook channel's sealed signing secret; NULL for the other channels. Never plaintext.
    sealed_secret BYTEA,
    secret_key_version INTEGER,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT export_delivery_profiles_name_unique UNIQUE (tenant_id, name),
    CONSTRAINT export_delivery_profiles_secret_check
        CHECK ((channel = 'webhook') = (sealed_secret IS NOT NULL)
               AND (sealed_secret IS NULL) = (secret_key_version IS NULL))
);

COMMENT ON TABLE export_delivery_profiles IS
    'MFX-38.4 (#4331): a tenant''s reusable export delivery destinations — channel, non-secret destination '
    'and a credential reference. Only a webhook profile holds a secret, sealed (app.mcp_credential_crypto) '
    'in sealed_secret; write-only — no route reads it back.';

ALTER TABLE export_git_delivery_runs
    ADD COLUMN IF NOT EXISTS delivery_profile_id UUID REFERENCES export_delivery_profiles(id) ON DELETE SET NULL;
ALTER TABLE export_webhook_delivery_runs
    ADD COLUMN IF NOT EXISTS delivery_profile_id UUID REFERENCES export_delivery_profiles(id) ON DELETE SET NULL;
ALTER TABLE export_object_storage_delivery_runs
    ADD COLUMN IF NOT EXISTS delivery_profile_id UUID REFERENCES export_delivery_profiles(id) ON DELETE SET NULL;

-- A profile's deliveries, newest first.
CREATE INDEX IF NOT EXISTS idx_export_git_delivery_runs_profile
    ON export_git_delivery_runs (tenant_id, delivery_profile_id, started_at DESC)
    WHERE delivery_profile_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_export_webhook_delivery_runs_profile
    ON export_webhook_delivery_runs (tenant_id, delivery_profile_id, started_at DESC)
    WHERE delivery_profile_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_export_object_storage_delivery_runs_profile
    ON export_object_storage_delivery_runs (tenant_id, delivery_profile_id, started_at DESC)
    WHERE delivery_profile_id IS NOT NULL;

COMMENT ON COLUMN export_git_delivery_runs.delivery_profile_id IS
    'MFX-38.4 (#4331): the delivery profile this run was made from; NULL for a direct delivery or a deleted profile.';
COMMENT ON COLUMN export_webhook_delivery_runs.delivery_profile_id IS
    'MFX-38.4 (#4331): the delivery profile this run was made from; NULL for a direct delivery or a deleted profile.';
COMMENT ON COLUMN export_object_storage_delivery_runs.delivery_profile_id IS
    'MFX-38.4 (#4331): the delivery profile this run was made from; NULL for a direct delivery or a deleted profile.';
