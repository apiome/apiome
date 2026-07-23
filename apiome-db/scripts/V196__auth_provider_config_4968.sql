-- Server-global OAuth provider configuration (#4968, OLO-8.2, Epic OLO-EPIC-8 #4966).
--
-- Sign-in provider config (client id/secret, per-provider extras) is SERVER-WIDE, not tenant-scoped:
-- a deployment signs everyone in through the same GitHub/GitLab/Entra apps. The established
-- `*_settings` pattern (e.g. type_registry_settings, V115) is per-TENANT and keyed by tenant_id, so
-- it does not fit here. This migration adds the one global home for that config:
-- `apiome.auth_provider_config`, one row per provider.
--
-- Relationship to the env config (OLO-2.3, provider-registry.ts) and env-fallback semantics (OLO-8.5):
--   Historically a provider is configured purely through env vars (GITHUB_ID/GITHUB_SECRET, …) and is
--   *enabled* when all of its required env vars are set. This table lets an operator override that
--   from the admin UI (OLO-8.4) without editing env and restarting. The store is layered OVER env,
--   field by field:
--       * ABSENT ROW for a provider        ⇒ that provider is governed entirely by env (unchanged).
--       * PRESENT ROW, but a NULL field    ⇒ fall back to env for THAT field only.
--       * PRESENT ROW, NON-NULL field      ⇒ the stored value wins over env for that field.
--   So `enabled = NULL` means "use the env-derived enablement", `client_id = NULL` means "use the env
--   client id", and so on. The table is created empty and rows are written lazily on the first save,
--   exactly like type_registry_settings — a fresh deployment therefore behaves identically to before.
--
-- Secrets: the client secret is persisted as CIPHERTEXT only, in `client_secret_encrypted` (BYTEA),
-- sealed by the application layer (envelope encryption) — the database never sees plaintext. `enc_key_id`
-- tags which key sealed it so the secret can be rotated and older rows still decrypted (OLO-8.3). The two
-- travel together (both NULL, or both set) — a stored secret always records the key that sealed it.
--
-- Nullability: every configurable field is nullable so a provider can be partially configured — e.g.
-- enable-toggled (`enabled` set, secret still from env) or given a client id ahead of its secret. Only
-- `provider_id`, `config`, and `updated_at` are NOT NULL.
--
-- Rollback notes: this migration is additive (one new table, its touch-trigger function + trigger, and
-- comments). To roll back:
--   DROP TABLE IF EXISTS apiome.auth_provider_config CASCADE;   -- also drops its trigger
--   DROP FUNCTION IF EXISTS apiome.update_auth_provider_config_updated_at();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- auth_provider_config — one row per sign-in provider, server-global. Overlays env config field-by-field.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS apiome.auth_provider_config (
  -- Provider slug, matching the PROVIDER_REGISTRY ids (provider-registry.ts, OLO-2.3) and the value
  -- stored in external_auth_providers.provider. One row per provider — the slug IS the primary key.
  provider_id TEXT PRIMARY KEY,

  -- Explicit enable toggle. NULL ⇒ fall back to the env-derived enablement (all required env vars set);
  -- TRUE/FALSE ⇒ the operator has pinned the provider on/off regardless of env.
  enabled BOOLEAN,

  -- OAuth client id (public). NULL ⇒ fall back to the env client id for this provider.
  client_id TEXT,

  -- OAuth client secret as ciphertext ONLY (app-layer envelope encryption); the DB never holds plaintext.
  -- NULL ⇒ fall back to the env secret. Nullable so a provider can be enable-toggled or partially
  -- configured without a secret yet.
  client_secret_encrypted BYTEA,

  -- Key-generation id that sealed client_secret_encrypted, enabling secret rotation (OLO-8.3).
  -- NULL exactly when there is no stored secret.
  enc_key_id TEXT,

  -- Provider-specific non-secret extras: Azure tenant/authority, GitLab/GitHub base URLs, etc. Cleartext
  -- by design (no secret material). Empty object ⇒ no overrides; each absent key falls back to env.
  config JSONB NOT NULL DEFAULT '{}'::jsonb,

  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

  -- Who last changed this row. TEXT (not a users FK) because the super-admin that manages provider
  -- config need not correspond to a tenant users row (OLO-8.1 signed super-admin session).
  updated_by TEXT,

  -- Guard the slug against typos / unknown providers — the enum-guard convention (cf. type_registry_settings,
  -- V115): a bad value can never be persisted even by a direct SQL write. Extend this list when a new
  -- provider joins PROVIDER_REGISTRY.
  CONSTRAINT auth_provider_config_provider_id_check
    CHECK (provider_id IN ('github', 'gitlab', 'azure', 'google', 'aws')),

  -- Ciphertext and its key id travel together: either both present, or both absent. A stored secret always
  -- records the key that sealed it (OLO-8.3 rotation); "no secret" means both NULL (fall back to env).
  CONSTRAINT auth_provider_config_secret_key_consistent
    CHECK (
      (client_secret_encrypted IS NULL AND enc_key_id IS NULL)
      OR (client_secret_encrypted IS NOT NULL AND enc_key_id IS NOT NULL)
    )
);

COMMENT ON TABLE apiome.auth_provider_config IS
  'Server-global OAuth provider config (#4968, OLO-8.2), one row per provider. Overlays env config field-by-field: absent row or null field ⇒ fall back to env (OLO-8.5).';
COMMENT ON COLUMN apiome.auth_provider_config.provider_id IS 'Provider slug matching PROVIDER_REGISTRY ids (github|gitlab|azure|google|aws); primary key, one row per provider.';
COMMENT ON COLUMN apiome.auth_provider_config.enabled IS 'Explicit enable toggle; NULL ⇒ fall back to env-derived enablement (all required env vars set).';
COMMENT ON COLUMN apiome.auth_provider_config.client_id IS 'OAuth client id; NULL ⇒ fall back to the env client id.';
COMMENT ON COLUMN apiome.auth_provider_config.client_secret_encrypted IS 'App-layer envelope-encrypted client secret (ciphertext only); NULL ⇒ fall back to the env secret.';
COMMENT ON COLUMN apiome.auth_provider_config.enc_key_id IS 'Key-generation id that sealed client_secret_encrypted, enabling rotation (OLO-8.3); NULL iff no stored secret.';
COMMENT ON COLUMN apiome.auth_provider_config.config IS 'Non-secret provider extras (Azure tenant/authority, GitLab/GitHub base URLs); cleartext, each absent key falls back to env.';
COMMENT ON COLUMN apiome.auth_provider_config.updated_at IS 'When the row was last changed (maintained by trigger).';
COMMENT ON COLUMN apiome.auth_provider_config.updated_by IS 'Identity of the super-admin who last changed the row; TEXT (not a users FK) as super-admin need not be a tenant user.';

-- ---------------------------------------------------------------------------------------------------
-- updated_at maintenance: provider config is mutable (edited/rotated), so a BEFORE UPDATE trigger keeps
-- updated_at current on every change — the established convention (cf. V129 mcp_endpoint_credentials).
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_auth_provider_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_auth_provider_config_updated_at ON apiome.auth_provider_config;
CREATE TRIGGER trigger_update_auth_provider_config_updated_at
    BEFORE UPDATE ON apiome.auth_provider_config
    FOR EACH ROW
    EXECUTE FUNCTION update_auth_provider_config_updated_at();

COMMENT ON FUNCTION update_auth_provider_config_updated_at() IS 'Trigger function that refreshes updated_at on any change to an auth_provider_config row (#4968).';

DO $$
BEGIN
    RAISE NOTICE 'apiome.auth_provider_config created (#4968, OLO-8.2).';
END $$;
