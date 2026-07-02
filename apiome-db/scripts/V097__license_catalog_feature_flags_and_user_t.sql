-- License catalog, feature flags, and user/tenant license assignments (#license-management)
SET search_path TO apiome, public;

-- ─── License catalog ───────────────────────────────────────────────────────────
-- seats JSONB holds all capacity limits so new limits can be added without
-- schema changes.  Canonical keys: max_tenants, max_users_per_tenant.

CREATE TABLE IF NOT EXISTS licenses (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name         VARCHAR(255) NOT NULL,
    description  TEXT,
    license_type VARCHAR(16)  NOT NULL DEFAULT 'free'
                 CHECK (license_type IN ('free', 'paid', 'sponsor')),
    seats        JSONB        NOT NULL DEFAULT '{"max_tenants":1,"max_users_per_tenant":5}',
    enabled      BOOLEAN      NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_licenses_license_type ON apiome.licenses (license_type);
CREATE INDEX IF NOT EXISTS idx_licenses_enabled      ON apiome.licenses (enabled);
CREATE INDEX IF NOT EXISTS idx_licenses_seats        ON apiome.licenses USING GIN (seats);

COMMENT ON TABLE  apiome.licenses              IS 'Catalog of license plans that can be assigned to users';
COMMENT ON COLUMN apiome.licenses.license_type IS 'Billing classification: free, paid, or sponsor';
COMMENT ON COLUMN apiome.licenses.seats        IS
  'Capacity limits JSON. Known keys: max_tenants (int), max_users_per_tenant (int).';

-- ─── Feature flags ─────────────────────────────────────────────────────────────
-- Each row is one toggleable feature.  url_patterns is a JSON array of URL
-- prefixes/globs that the middleware should guard with this flag.

CREATE TABLE IF NOT EXISTS feature_flags (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name         VARCHAR(64) NOT NULL UNIQUE,   -- machine slug, e.g. "ai_assistant"
    label        VARCHAR(255) NOT NULL,          -- human label, e.g. "AI Assistant"
    description  TEXT,
    url_patterns JSONB       NOT NULL DEFAULT '[]',
    is_preview   BOOLEAN     NOT NULL DEFAULT false,
    enabled      BOOLEAN     NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feature_flags_name       ON apiome.feature_flags (name);
CREATE INDEX IF NOT EXISTS idx_feature_flags_enabled    ON apiome.feature_flags (enabled);
CREATE INDEX IF NOT EXISTS idx_feature_flags_is_preview ON apiome.feature_flags (is_preview);
CREATE INDEX IF NOT EXISTS idx_feature_flags_url_patterns
    ON apiome.feature_flags USING GIN (url_patterns);

COMMENT ON TABLE  apiome.feature_flags              IS 'Registry of feature flags that gate UI routes and API endpoints';
COMMENT ON COLUMN apiome.feature_flags.name         IS 'Unique machine-readable slug used in code checks';
COMMENT ON COLUMN apiome.feature_flags.url_patterns IS
  'JSON array of URL prefixes/globs (e.g. ["/ade/studio","/api/ollama"]) guarded by this flag';
COMMENT ON COLUMN apiome.feature_flags.is_preview   IS 'Show a "Preview" badge in the UI when true';

-- ─── License ↔ Feature flag ─────────────────────────────────────────────────
-- Which feature flags are included by default in a license plan.

CREATE TABLE IF NOT EXISTS license_feature_flags (
    license_id      UUID NOT NULL REFERENCES apiome.licenses(id)       ON DELETE CASCADE,
    feature_flag_id UUID NOT NULL REFERENCES apiome.feature_flags(id)  ON DELETE CASCADE,
    PRIMARY KEY (license_id, feature_flag_id)
);

CREATE INDEX IF NOT EXISTS idx_lff_license_id      ON apiome.license_feature_flags (license_id);
CREATE INDEX IF NOT EXISTS idx_lff_feature_flag_id ON apiome.license_feature_flags (feature_flag_id);

COMMENT ON TABLE apiome.license_feature_flags IS
  'Junction: feature flags bundled into a license plan';

-- ─── Per-user feature flag overrides ────────────────────────────────────────
-- Admins can grant or revoke individual flags for a user regardless of plan.

CREATE TABLE IF NOT EXISTS user_feature_flags (
    user_id         UUID    NOT NULL REFERENCES apiome.users(id)        ON DELETE CASCADE,
    feature_flag_id UUID    NOT NULL REFERENCES apiome.feature_flags(id) ON DELETE CASCADE,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    granted_by      UUID    REFERENCES apiome.users(id)                  ON DELETE SET NULL,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, feature_flag_id)
);

CREATE INDEX IF NOT EXISTS idx_uff_user_id         ON apiome.user_feature_flags (user_id);
CREATE INDEX IF NOT EXISTS idx_uff_feature_flag_id ON apiome.user_feature_flags (feature_flag_id);

COMMENT ON TABLE  apiome.user_feature_flags          IS 'Per-user feature flag overrides; take precedence over license defaults';
COMMENT ON COLUMN apiome.user_feature_flags.enabled  IS 'true = granted, false = explicitly revoked even if in license';
COMMENT ON COLUMN apiome.user_feature_flags.granted_by IS 'Admin user who made the last change';

-- ─── Per-tenant feature flag overrides ──────────────────────────────────────
-- All members of a tenant inherit tenant-level grants unless overridden at user level.

CREATE TABLE IF NOT EXISTS tenant_feature_flags (
    tenant_id       UUID    NOT NULL REFERENCES apiome.tenants(id)      ON DELETE CASCADE,
    feature_flag_id UUID    NOT NULL REFERENCES apiome.feature_flags(id) ON DELETE CASCADE,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    granted_by      UUID    REFERENCES apiome.users(id)                  ON DELETE SET NULL,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, feature_flag_id)
);

CREATE INDEX IF NOT EXISTS idx_tff_tenant_id       ON apiome.tenant_feature_flags (tenant_id);
CREATE INDEX IF NOT EXISTS idx_tff_feature_flag_id ON apiome.tenant_feature_flags (feature_flag_id);

COMMENT ON TABLE  apiome.tenant_feature_flags         IS 'Per-tenant feature flag overrides; all tenant members inherit these';
COMMENT ON COLUMN apiome.tenant_feature_flags.enabled IS 'true = granted to tenant, false = explicitly revoked';

-- ─── Wire license_id into user_entitlements ──────────────────────────────────

ALTER TABLE apiome.user_entitlements
    ADD COLUMN IF NOT EXISTS license_id UUID REFERENCES apiome.licenses(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_user_entitlements_license_id
    ON apiome.user_entitlements (license_id);

COMMENT ON COLUMN apiome.user_entitlements.license_id IS
    'Assigned license plan; NULL means legacy/unenforced account using raw limit columns';

-- ─── Seed: feature flags ─────────────────────────────────────────────────────

INSERT INTO apiome.feature_flags (name, label, description, url_patterns, is_preview, enabled)
VALUES
    ('designer',
     'Schema Designer',
     'Visual schema designer and class editor.',
     '["/ade/dashboard", "/api/classes", "/api/properties", "/api/primitives"]',
     false, true),

    ('paths',
     'API Paths',
     'OpenAPI path editor and path management tools.',
     '["/ade/database", "/api/paths", "/api/versions"]',
     false, true),

    ('ai_assistant',
     'AI Assistant',
     'Ollama-powered chatbot and schema generation assistant.',
     '["/ade/studio", "/api/ollama"]',
     true, true),

    ('repositories',
     'Repositories',
     'Git-backed schema repository browser and diff viewer.',
     '["/ade/migration", "/api/repositories"]',
     true, true)
ON CONFLICT (name) DO NOTHING;

-- ─── Seed: license tiers ─────────────────────────────────────────────────────

INSERT INTO apiome.licenses (name, description, license_type, seats)
VALUES
    ('Free',
     'Default free-tier plan with basic schema designer access.',
     'free',
     '{"max_tenants":1,"max_users_per_tenant":5}'),

    ('Paid',
     'Standard paid plan — Designer, Paths, AI Assistant and Repositories included.',
     'paid',
     '{"max_tenants":5,"max_users_per_tenant":25}'),

    ('Sponsor',
     'Sponsor plan — all features, elevated tenant and user limits.',
     'sponsor',
     '{"max_tenants":20,"max_users_per_tenant":100}')
ON CONFLICT DO NOTHING;

-- ─── Seed: license ↔ feature flag associations ───────────────────────────────

INSERT INTO apiome.license_feature_flags (license_id, feature_flag_id)
SELECT l.id, ff.id
FROM   apiome.licenses l
CROSS  JOIN apiome.feature_flags ff
WHERE  l.name = 'Free'
  AND  ff.name IN ('designer')
ON CONFLICT DO NOTHING;

INSERT INTO apiome.license_feature_flags (license_id, feature_flag_id)
SELECT l.id, ff.id
FROM   apiome.licenses l
CROSS  JOIN apiome.feature_flags ff
WHERE  l.name = 'Paid'
  AND  ff.name IN ('designer', 'paths', 'ai_assistant', 'repositories')
ON CONFLICT DO NOTHING;

INSERT INTO apiome.license_feature_flags (license_id, feature_flag_id)
SELECT l.id, ff.id
FROM   apiome.licenses l
CROSS  JOIN apiome.feature_flags ff
WHERE  l.name = 'Sponsor'
  AND  ff.name IN ('designer', 'paths', 'ai_assistant', 'repositories')
ON CONFLICT DO NOTHING;

-- ─── Back-fill existing free-plan entitlements ───────────────────────────────

UPDATE apiome.user_entitlements ue
SET    license_id = l.id
FROM   apiome.licenses l
WHERE  l.name      = 'Free'
  AND  ue.plan_code = 'free'
  AND  ue.license_id IS NULL;
