-- Consumer identification for the usage index — RDG-1.8 (#5765).
--
-- "This change affects billing-service at 38%" needs traffic attributed to a consumer the CTG-4.1
-- registry (V251) already knows. Traffic carries headers, API keys, JWT claims and user agents, not
-- consumer handles. Storing those values would turn the usage index into an identity log, and not
-- binding them would make every share anonymous. This migration adds the bridge between the two.
-- (The roadmap reserved V275; that number shipped long ago, so this is V292.)
--
--   usage_consumer_binding        how a consumer is recognised in traffic: a header, an API key or
--                                 a JWT claim (stored as a keyed hash of the value, never the
--                                 value), or a user-agent glob
--   consumer.runtime_last_seen_at when traffic last attributed to the consumer
--   consumer_slug_reserved_check  the handle `anonymous` is reserved: unattributed traffic is
--                                 reported under it
--
-- Five rules shape the schema:
--
--   1. **A bound value is never stored.** For `header`, `api_key` and `jwt_claim` bindings the REST
--      API hashes the value it is given (HMAC-SHA256 under a tenant-scoped key derived from the
--      `APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS` envelope key map, see
--      `app.consumer_binding`) **before** its transaction opens, and only the hash reaches this
--      table. `value_hmac` is exactly 64 lower-case hex characters (CHECK), so a raw value cannot be
--      stored by mistake. A `user_agent` binding has no value: its `name` is the glob itself.
--
--   2. **The edge sends the same hash.** A usage event's `consumer_hint` is `{kind, hmac}` (V290's
--      event contract), so the RDG-1.2 ingest pipeline matches a hint against `(kind, value_hmac)`
--      and never needs the value either. `key_version` records which master key the hash was made
--      under, so a key rotation does not silently break existing bindings.
--
--   3. **Unique per tenant, kind, name and value** among live bindings — one value identifies one
--      consumer. `NULLS NOT DISTINCT` makes two identical user-agent globs collide too.
--
--   4. **Deleting a binding never rewrites history.** A binding is deleted by stamping `deleted_at`.
--      The row stays, so `usage_hourly` / `usage_daily` rows that already carry its id (V290's
--      `consumer_binding_id`, which has no FK on purpose) still name the consumer they were
--      attributed to. The ingest pipeline only matches live bindings, so attribution stops with
--      the next batch.
--
--   5. **Unattributed traffic is counted, never dropped.** A call no binding matches keeps
--      `consumer_binding_id = NULL`. Readers report it under the reserved consumer handle
--      `anonymous`, which the new CHECK keeps any real consumer from taking. The CHECK is added
--      `NOT VALID`, so a consumer that already holds the handle stays readable (and can still be
--      retired), but no new live row can take it.
--
-- Rollback notes:
--   ALTER TABLE apiome.consumer DROP CONSTRAINT IF EXISTS consumer_slug_reserved_check;
--   ALTER TABLE apiome.consumer DROP COLUMN IF EXISTS runtime_last_seen_at;
--   DROP TABLE IF EXISTS apiome.usage_consumer_binding;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- Bindings.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_consumer_binding (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL,
    consumer_id UUID NOT NULL,
    -- The binding belongs to the consumer, and the consumer to the project (V251's composite key).
    CONSTRAINT usage_consumer_binding_consumer_fk
        FOREIGN KEY (consumer_id, project_id) REFERENCES consumer (id, project_id) ON DELETE CASCADE,

    kind VARCHAR(16) NOT NULL
        CONSTRAINT usage_consumer_binding_kind_ck CHECK (
            kind IN ('header', 'api_key', 'jwt_claim', 'user_agent')
        ),
    -- The header name (lower case), the API-key header name, the JWT claim name, or the user-agent
    -- glob. Printable characters only, at most 256 of them.
    name VARCHAR(256) NOT NULL
        CONSTRAINT usage_consumer_binding_name_ck CHECK (name ~ '^[[:print:]]+$' AND char_length(name) <= 256),
    -- Rule 1: the keyed hash of the value, and the master key it was made under. Present for every
    -- kind except user_agent.
    value_hmac CHAR(64)
        CONSTRAINT usage_consumer_binding_value_hmac_ck CHECK (value_hmac ~ '^[0-9a-f]{64}$'),
    key_version INTEGER
        CONSTRAINT usage_consumer_binding_key_version_ck CHECK (key_version >= 1),
    CONSTRAINT usage_consumer_binding_value_shape_ck CHECK (
        (kind = 'user_agent' AND value_hmac IS NULL AND key_version IS NULL)
        OR (kind <> 'user_agent' AND value_hmac IS NOT NULL AND key_version IS NOT NULL)
    ),

    -- When traffic last matched this binding (the call's observed time).
    last_matched_at TIMESTAMPTZ,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Rule 4: a deleted binding is kept so history stays attributed.
    deleted_at TIMESTAMPTZ,
    deleted_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- Rule 3.
CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_consumer_binding_live_uq
    ON usage_consumer_binding (tenant_id, kind, name, value_hmac) NULLS NOT DISTINCT
    WHERE deleted_at IS NULL;
-- The ingest matcher: a hint looks up (kind, value_hmac) among a project's live bindings.
CREATE INDEX IF NOT EXISTS idx_usage_consumer_binding_project_live
    ON usage_consumer_binding (tenant_id, project_id, kind)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_usage_consumer_binding_consumer
    ON usage_consumer_binding (consumer_id);

COMMENT ON TABLE usage_consumer_binding IS
    'RDG-1.8 (#5765): how a consumer is recognised in usage traffic — a header, API key or JWT claim '
    'stored as an HMAC-SHA256 of the value under a tenant-scoped key (never the value), or a '
    'user-agent glob. Deleted bindings are kept (deleted_at) so attributed history stays attributed.';
COMMENT ON COLUMN usage_consumer_binding.name IS
    'The header name (lower case), the API-key header name, the JWT claim name, or the user-agent '
    'glob (* and ? wildcards).';
COMMENT ON COLUMN usage_consumer_binding.value_hmac IS
    'Lower-case hex HMAC-SHA256 of the bound value under the tenant''s derived key. NULL for a '
    'user_agent binding. The value itself is never stored.';
COMMENT ON COLUMN usage_consumer_binding.key_version IS
    'The envelope master-key version the tenant key was derived from when value_hmac was made.';
COMMENT ON COLUMN usage_consumer_binding.last_matched_at IS
    'The observed time of the newest call attributed through this binding.';

-- ---------------------------------------------------------------------------------------------------
-- The consumer side.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE consumer ADD COLUMN IF NOT EXISTS runtime_last_seen_at TIMESTAMPTZ;

COMMENT ON COLUMN consumer.runtime_last_seen_at IS
    'RDG-1.8 (#5765): the observed time of the newest call attributed to this consumer through any '
    'of its usage_consumer_binding rows.';

-- Rule 5.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'consumer_slug_reserved_check' AND conrelid = 'apiome.consumer'::regclass
    ) THEN
        ALTER TABLE consumer
            ADD CONSTRAINT consumer_slug_reserved_check CHECK (slug <> 'anonymous' OR deleted_at IS NOT NULL) NOT VALID;
    END IF;
END;
$$;
