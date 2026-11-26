-- Secrets for webhooks and verification targets — PFX-6.5 (#6957).
--
-- A workspace keeps named secrets — a CI token, an API key, a signing secret — once, in the
-- credential vault, and webhooks and verification targets *refer* to them by name instead of each
-- holding its own copy. Rotating a token is then one change, and nothing outside the vault holds it.
--
--   * `pact_secret` — one named secret per row. The value is stored only as `secret_ciphertext`,
--     sealed by apiome-rest's envelope cipher with the credential vault's master keys
--     (`app.pact_secret_vault`, magic `OPSC`); there is deliberately no plaintext column. `name` is
--     what a reference uses (`${user.<name>}` in a webhook, `auth.ref` of a target), unique per
--     workspace and never changed once created.
--   * `pact_webhook.secret_refs` — the names a webhook's templates refer to (URL, headers, body,
--     credentials, signing secret), written by the store when the webhook is saved. It is how a
--     secret that is still in use is found without opening any webhook's sealed values.
--   * `verification_target.auth_kind` gains `secret`: `auth_ref` is then a secret's name in the
--     target's workspace, resolved by the runner when it starts.
--
-- Online: one new table and two indexes (empty), one column with a constant default (no rewrite),
-- and a CHECK swapped on verification_target (a short lock; every existing row satisfies it).
--
-- Rollback notes:
--   ALTER TABLE apiome.verification_target DROP CONSTRAINT IF EXISTS verification_target_auth_secret_ref_shape_check;
--   ALTER TABLE apiome.verification_target DROP CONSTRAINT IF EXISTS verification_target_auth_kind_check;
--   ALTER TABLE apiome.verification_target ADD CONSTRAINT verification_target_auth_kind_check
--       CHECK (auth_kind IN ('none', 'env', 'stored'));   -- after re-pointing any 'secret' target
--   ALTER TABLE apiome.pact_webhook DROP COLUMN IF EXISTS secret_refs;
--   DROP TABLE IF EXISTS apiome.pact_secret CASCADE;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- pact_secret — a workspace's named secrets. Ciphertext only.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pact_secret (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- What a reference uses: a letter, then letters, digits and underscores (64 at most).
    name TEXT NOT NULL
        CONSTRAINT pact_secret_name_shape_check
            CHECK (name ~ '^[A-Za-z][A-Za-z0-9_]{0,63}$'),
    description TEXT
        CONSTRAINT pact_secret_description_length_check
            CHECK (description IS NULL OR char_length(description) <= 1000),

    -- The sealed value and the master key version that sealed it. Never NULL: a secret has a value.
    secret_ciphertext BYTEA NOT NULL,
    key_version INTEGER NOT NULL,

    -- When the value was last set (created or rotated); updated_at also moves on a description edit.
    value_updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- One name per workspace; the btree also serves the by-name lookup a reference resolves with.
    CONSTRAINT uq_pact_secret_name UNIQUE (tenant_id, name),
    -- A composite reference target, as every PFX table has (V447).
    CONSTRAINT uq_pact_secret_id_tenant UNIQUE (id, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_pact_secret_created_by
    ON pact_secret (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pact_secret_updated_by
    ON pact_secret (updated_by) WHERE updated_by IS NOT NULL;

COMMENT ON TABLE pact_secret IS
    'A workspace''s named secrets for webhooks and verification targets; ciphertext only (PFX-6.5, #6957)';
COMMENT ON COLUMN pact_secret.name IS
    'What a reference uses: ${user.<name>} in a webhook, auth.ref of a target with auth_kind secret; never renamed';
COMMENT ON COLUMN pact_secret.description IS 'What the secret is for; shown in lists';
COMMENT ON COLUMN pact_secret.secret_ciphertext IS
    'The value, envelope-sealed by app.pact_secret_vault; never stored or returned in the clear';
COMMENT ON COLUMN pact_secret.key_version IS 'The master key version that sealed secret_ciphertext';
COMMENT ON COLUMN pact_secret.value_updated_at IS 'When the value was last set (created or rotated)';

-- ---------------------------------------------------------------------------------------------------
-- pact_webhook.secret_refs — the secret names a webhook refers to.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE pact_webhook
    ADD COLUMN IF NOT EXISTS secret_refs TEXT[] NOT NULL DEFAULT ARRAY[]::text[];

COMMENT ON COLUMN pact_webhook.secret_refs IS
    'Names of the workspace secrets the webhook''s templates refer to as ${user.<name>} (PFX-6.5)';

-- ---------------------------------------------------------------------------------------------------
-- verification_target — a credential reference may name a workspace secret.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE verification_target DROP CONSTRAINT IF EXISTS verification_target_auth_kind_check;
ALTER TABLE verification_target ADD CONSTRAINT verification_target_auth_kind_check
    CHECK (auth_kind IN ('none', 'env', 'stored', 'secret'));

ALTER TABLE verification_target DROP CONSTRAINT IF EXISTS verification_target_auth_secret_ref_shape_check;
ALTER TABLE verification_target ADD CONSTRAINT verification_target_auth_secret_ref_shape_check
    CHECK (auth_kind <> 'secret' OR auth_ref ~ '^[A-Za-z][A-Za-z0-9_]{0,63}$');

COMMENT ON COLUMN verification_target.auth_kind IS
    'none | env (runner-resolved environment variable) | stored (id in the encrypted credential vault) | secret (a workspace secret''s name, PFX-6.5); never a secret';
