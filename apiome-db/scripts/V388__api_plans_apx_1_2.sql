-- API plans — APX-1.2 (#6099).
--
-- A gateway holds rate limits per consumer group, but the *intent* — what the Standard tier
-- promises — lives in wikis and contracts. A **plan** is that intent, declared once on an API product
-- (APX-1.1, V387):
--
--   api_plans — one tier of one product: how a consumer authenticates (`auth_strategy` +
--               `auth_config`), the request limits it promises (`limits`, optional `concurrency`),
--               whether a subscription is approved automatically or by a person (`approval`), the
--               gateway configs it is provisioned to (`environments`), an optional maximum key age
--               (`credential_ttl_days`), its terms, pricing note and billing reference, and a
--               lifecycle state.
--
-- `limits` is a JSON array of `{window, requests}` with `window` one of second | minute | hour | day |
-- month; apiome-rest (app.api_plans) checks every count is positive and every window appears once.
--
-- `environments` holds catalog_gateway_configs ids (V298). A plan is **declared only** while it has no
-- environment, or one of its environments belongs to a connector that cannot provision (no connector
-- can until APX-4.1 gives connectors the `provision` capability): Apiome records the intent and shows
-- a notice, but changes nothing on a gateway. apiome-rest re-derives `declared_only` on every write so
-- the provisioner (APX-4.x) can select the plans it owns.
--
-- Rules kept by the database:
--
--   1. **A slug is a handle**, shaped like a product slug and unique among a product's live plans.
--      Deletes are soft, so a subscription (APX-2.2) or an audit entry still resolves.
--   2. **A plan cannot cross tenants.** It carries `tenant_id` and references its product by the
--      composite `(id, tenant_id)` key (V387 rule 3); deleting a product's row deletes its plans.
--   3. **Shapes are bounded**: `auth_config` is an object, `limits` an array, counts positive, a
--      terms URL is http(s).
--
-- No new RBAC resource: plans belong to products, which use `projects:view|edit`.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.api_plans;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS api_plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL,
    product_id UUID NOT NULL,

    -- Rule 1.
    slug VARCHAR(128) NOT NULL
        CONSTRAINT api_plans_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    name VARCHAR(200) NOT NULL
        CONSTRAINT api_plans_name_not_blank_check CHECK (btrim(name) <> ''),
    description TEXT
        CONSTRAINT api_plans_description_length_check CHECK (description IS NULL OR length(description) <= 4000),

    auth_strategy VARCHAR(32) NOT NULL DEFAULT 'key_auth'
        CONSTRAINT api_plans_auth_strategy_check
            CHECK (auth_strategy IN ('key_auth', 'oauth2_client_credentials', 'mtls', 'none')),
    -- Header name (key_auth), IdP config id and scopes (oauth2_client_credentials). Never a secret.
    auth_config JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT api_plans_auth_config_object_check CHECK (jsonb_typeof(auth_config) = 'object'),

    -- Rule 3. `[{window, requests}]`; positivity and unique windows are apiome-rest's.
    limits JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT api_plans_limits_array_check CHECK (jsonb_typeof(limits) = 'array'),
    concurrency INTEGER
        CONSTRAINT api_plans_concurrency_positive_check CHECK (concurrency IS NULL OR concurrency > 0),

    approval VARCHAR(16) NOT NULL DEFAULT 'manual'
        CONSTRAINT api_plans_approval_check CHECK (approval IN ('auto', 'manual')),

    -- catalog_gateway_configs ids; a deleted gateway config reads back as missing.
    environments UUID[] NOT NULL DEFAULT '{}',
    declared_only BOOLEAN NOT NULL DEFAULT TRUE,

    credential_ttl_days INTEGER
        CONSTRAINT api_plans_credential_ttl_check
            CHECK (credential_ttl_days IS NULL OR credential_ttl_days BETWEEN 1 AND 3650),
    terms_url TEXT
        CONSTRAINT api_plans_terms_url_check
            CHECK (terms_url IS NULL OR (length(terms_url) <= 2048 AND terms_url ~* '^https?://')),
    pricing_note TEXT
        CONSTRAINT api_plans_pricing_note_length_check CHECK (pricing_note IS NULL OR length(pricing_note) <= 1000),
    -- An external billing system's id for the plan. Internal: never shown on the portal or exported.
    billing_ref VARCHAR(200),

    state VARCHAR(16) NOT NULL DEFAULT 'draft'
        CONSTRAINT api_plans_state_check CHECK (state IN ('draft', 'published', 'deprecated', 'retired')),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,

    -- Rule 2.
    CONSTRAINT api_plans_product_fk
        FOREIGN KEY (product_id, tenant_id) REFERENCES api_products (id, tenant_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_api_plans_product_slug
    ON api_plans (product_id, slug)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_api_plans_tenant_product
    ON api_plans (tenant_id, product_id)
    WHERE deleted_at IS NULL;

COMMENT ON TABLE api_plans IS
    'API plans: tiers of an API product — auth strategy, declared limits, approval, environments, terms (APX-1.2, #6099)';
COMMENT ON COLUMN api_plans.limits IS '[{window: second|minute|hour|day|month, requests}], windows unique, counts positive';
COMMENT ON COLUMN api_plans.environments IS 'catalog_gateway_configs ids the plan is provisioned to';
COMMENT ON COLUMN api_plans.declared_only IS
    'True while no environment can be provisioned: the plan is recorded, not pushed to a gateway';
COMMENT ON COLUMN api_plans.billing_ref IS 'External billing id; internal, never exported or shown on the portal';
