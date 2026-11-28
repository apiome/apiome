-- Contracts settings: commit statuses, agents, and secrets waiting for a value — PFX-8.15 (#7312).
--
-- The Contracts **Settings** page gains its last tabs. Two need storage:
--
--   pact_contract_settings — one row per tenant:
--     * commit statuses: whether a verdict is written on the consumer's commit, on the provider's
--       commit, and whether bi-directional verdicts (verification_result.kind = 'bidirectional') set a
--       status and fire their webhooks at all;
--     * agents: what an MCP-connected agent may do with contracts — read, draft, publish, record a
--       deployment. Reading and drafting are on by default; anything that writes is the
--       workspace's to allow.
--   A workspace with no row reads the defaults below.
--
-- And `apiome pact migrate` (PFX-6.7) stops refusing a webhook whose secret the source redacted:
--
--   pact_secret.secret_ciphertext / key_version become optional, with `awaiting_value` saying a secret
--   was created without one (by a migration — `origin = 'migration'`). Resolving such a secret is
--   refused by apiome-rest; setting its value clears the flag.
--   pact_webhook.awaiting_secrets marks a webhook imported turned off because a secret it refers to
--   has no value yet; apiome-rest turns it on once none of them is waiting.
--
-- Rules kept by the database:
--
--   1. **A secret has a value unless it is waiting for one.** `awaiting_value` is true exactly when
--      there is no ciphertext, and ciphertext and key version come together.
--   2. **A webhook waiting for a secret is off.** `awaiting_secrets` implies `enabled = false`.
--   3. **Nothing crosses a tenant.** The settings row is keyed by `tenant_id` and goes with it.
--
-- Online: one new table; two NOT NULLs dropped and three columns with constant defaults added
-- (catalog-only); three CHECK constraints added NOT VALID then validated (existing rows satisfy them).
--
-- Rollback notes (only once no secret is waiting for a value):
--   DROP TABLE IF EXISTS apiome.pact_contract_settings;
--   ALTER TABLE apiome.pact_webhook DROP CONSTRAINT IF EXISTS pact_webhook_awaiting_secrets_off_check,
--       DROP COLUMN IF EXISTS awaiting_secrets;
--   ALTER TABLE apiome.pact_secret DROP CONSTRAINT IF EXISTS pact_secret_value_or_awaiting_check,
--       DROP CONSTRAINT IF EXISTS pact_secret_origin_check,
--       DROP COLUMN IF EXISTS awaiting_value, DROP COLUMN IF EXISTS origin,
--       ALTER COLUMN secret_ciphertext SET NOT NULL, ALTER COLUMN key_version SET NOT NULL;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. pact_contract_settings
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_contract_settings (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,

    status_consumer_commit BOOLEAN NOT NULL DEFAULT TRUE,
    status_provider_commit BOOLEAN NOT NULL DEFAULT TRUE,
    status_bidirectional BOOLEAN NOT NULL DEFAULT FALSE,

    agent_read BOOLEAN NOT NULL DEFAULT TRUE,
    agent_draft BOOLEAN NOT NULL DEFAULT TRUE,
    agent_publish BOOLEAN NOT NULL DEFAULT FALSE,
    agent_record BOOLEAN NOT NULL DEFAULT FALSE,

    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by_label TEXT,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pact_contract_settings_updated_by
    ON pact_contract_settings (updated_by) WHERE updated_by IS NOT NULL;

COMMENT ON TABLE pact_contract_settings IS
    'A workspace''s Contracts commit-status and agent switches (PFX-8.15, #7312); no row = the defaults';
COMMENT ON COLUMN pact_contract_settings.status_consumer_commit IS
    'Write pact verdicts (pending and verified) as statuses on the consumer''s commit';
COMMENT ON COLUMN pact_contract_settings.status_provider_commit IS
    'Write verification verdicts as statuses on the provider''s commit';
COMMENT ON COLUMN pact_contract_settings.status_bidirectional IS
    'Bi-directional verdicts set commit statuses and fire their webhooks, as a verification does';
COMMENT ON COLUMN pact_contract_settings.agent_read IS 'MCP agents may read pacts, verdicts and can-i-deploy';
COMMENT ON COLUMN pact_contract_settings.agent_draft IS 'MCP agents may draft a pact for a person to review';
COMMENT ON COLUMN pact_contract_settings.agent_publish IS
    'MCP agents may publish pacts and provider contracts (never on a main branch)';
COMMENT ON COLUMN pact_contract_settings.agent_record IS
    'MCP agents may record deployments (never to a production environment)';

-- ---------------------------------------------------------------------------------------------------
-- 2. Secrets waiting for a value
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE pact_secret
    ALTER COLUMN secret_ciphertext DROP NOT NULL,
    ALTER COLUMN key_version DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS awaiting_value BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS origin VARCHAR(16);

ALTER TABLE pact_secret DROP CONSTRAINT IF EXISTS pact_secret_value_or_awaiting_check;
ALTER TABLE pact_secret ADD CONSTRAINT pact_secret_value_or_awaiting_check
    CHECK ((awaiting_value AND secret_ciphertext IS NULL AND key_version IS NULL)
           OR (NOT awaiting_value AND secret_ciphertext IS NOT NULL AND key_version IS NOT NULL)) NOT VALID;
ALTER TABLE pact_secret VALIDATE CONSTRAINT pact_secret_value_or_awaiting_check;

ALTER TABLE pact_secret DROP CONSTRAINT IF EXISTS pact_secret_origin_check;
ALTER TABLE pact_secret ADD CONSTRAINT pact_secret_origin_check
    CHECK (origin IS NULL OR origin IN ('migration')) NOT VALID;
ALTER TABLE pact_secret VALIDATE CONSTRAINT pact_secret_origin_check;

COMMENT ON COLUMN pact_secret.awaiting_value IS
    'Created without a value (a migrated webhook''s redacted secret); resolving it is refused until set';
COMMENT ON COLUMN pact_secret.origin IS 'migration: created by apiome pact migrate; NULL: created by a person';

ALTER TABLE pact_webhook
    ADD COLUMN IF NOT EXISTS awaiting_secrets BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE pact_webhook DROP CONSTRAINT IF EXISTS pact_webhook_awaiting_secrets_off_check;
ALTER TABLE pact_webhook ADD CONSTRAINT pact_webhook_awaiting_secrets_off_check
    CHECK (NOT awaiting_secrets OR NOT enabled) NOT VALID;
ALTER TABLE pact_webhook VALIDATE CONSTRAINT pact_webhook_awaiting_secrets_off_check;

COMMENT ON COLUMN pact_webhook.awaiting_secrets IS
    'Imported turned off because a secret it refers to has no value yet; turned on when none is waiting';
