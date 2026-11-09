-- MCP catalog categorization model & manual tags (#3693, V2-MCP-23.3 / MCAT-9.3).
--
-- Catalogers need to sort MCP servers into a shared vocabulary of categories and label them with
-- free-form tags, and browse/search need both as facets. Two tables:
--
--   * mcp_categories     — the category lookup. Rows with a NULL tenant_id are the built-in
--                          vocabulary every tenant sees (seeded below, read-only through the API);
--                          rows with a tenant_id are categories that tenant added. A category is
--                          addressed by its `slug`, which is what `mcp_endpoints.category` stores
--                          once a write matches the lookup.
--   * mcp_endpoint_tags  — zero or more free tags per endpoint, stored already normalized
--                          (lowercase, no spaces) so equality is a plain btree match.
--
-- `mcp_endpoints.category` stays a free-form VARCHAR (V126): the lookup is lenient. The API
-- canonicalizes a value that matches a category's slug or label to that slug, and still accepts a
-- value that matches nothing, so existing endpoints and clients keep working. No FK is added.
--
-- Rollback notes: purely additive. To roll back,
-- `DROP TABLE IF EXISTS apiome.mcp_endpoint_tags; DROP TABLE IF EXISTS apiome.mcp_categories;`.
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mcp_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- NULL for a built-in category; the owning tenant for a tenant-defined one.
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,

    -- Stable identifier stored on mcp_endpoints.category: lowercase letters, digits and hyphens.
    slug VARCHAR(64) NOT NULL,

    -- Display name shown in facets and pickers.
    label VARCHAR(128) NOT NULL,

    description TEXT,

    -- Ascending display order; ties break on label.
    sort_order INTEGER NOT NULL DEFAULT 0,

    -- Who added a tenant-defined category; NULL for built-ins or after the user is removed.
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT mcp_categories_slug_check
        CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
    CONSTRAINT mcp_categories_label_check
        CHECK (length(btrim(label)) > 0)
);

-- A built-in slug is unique on its own; a tenant slug is unique within the tenant. The API also
-- refuses a tenant slug that shadows a built-in one.
CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_categories_builtin_slug
    ON mcp_categories(slug) WHERE tenant_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_categories_tenant_slug
    ON mcp_categories(tenant_id, slug) WHERE tenant_id IS NOT NULL;

-- The built-in vocabulary (mirrored by app.mcp_categorization.BUILTIN_CATEGORIES).
INSERT INTO mcp_categories (tenant_id, slug, label, description, sort_order) VALUES
    (NULL, 'developer-tools', 'Developer tools', 'Source control, CI/CD, issue trackers, code analysis and build tooling.', 10),
    (NULL, 'data-analytics', 'Data & analytics', 'Querying, reporting, BI and data pipelines.', 20),
    (NULL, 'databases', 'Databases', 'Direct access to SQL, NoSQL and vector stores.', 30),
    (NULL, 'files-storage', 'Files & storage', 'File systems, object storage and document stores.', 40),
    (NULL, 'search-web', 'Search & web', 'Web search, browsing, scraping and fetch.', 50),
    (NULL, 'productivity', 'Productivity', 'Calendars, notes, docs, tasks and project management.', 60),
    (NULL, 'communication', 'Communication', 'Chat, email, messaging and notifications.', 70),
    (NULL, 'cloud-infrastructure', 'Cloud & infrastructure', 'Cloud providers, containers, monitoring and operations.', 80),
    (NULL, 'finance-commerce', 'Finance & commerce', 'Payments, accounting, billing and e-commerce.', 90),
    (NULL, 'ai-ml', 'AI & machine learning', 'Model hosting, inference, embeddings and agent tooling.', 100),
    (NULL, 'security', 'Security', 'Identity, secrets, scanning and compliance.', 110),
    (NULL, 'other', 'Other', 'Anything that fits no other category.', 1000)
ON CONFLICT (slug) WHERE tenant_id IS NULL DO NOTHING;

CREATE TABLE IF NOT EXISTS mcp_endpoint_tags (
    -- The tagged endpoint; its tags go with it when the endpoint row is removed.
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints(id) ON DELETE CASCADE,

    -- Denormalized from the endpoint so the tenant's tag vocabulary is one indexed read.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- The normalized tag: lowercase letters, digits and . _ : - (no spaces).
    tag VARCHAR(64) NOT NULL,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (endpoint_id, tag),

    CONSTRAINT mcp_endpoint_tags_tag_check
        CHECK (tag ~ '^[a-z0-9][a-z0-9._:-]{0,63}$')
);

-- Tag facet filters and the per-tenant tag vocabulary look tags up by value within a tenant.
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_tags_tenant_tag
    ON mcp_endpoint_tags(tenant_id, tag);

COMMENT ON TABLE mcp_categories IS
    'MCP catalog category lookup (#3693): built-in rows (tenant_id NULL) plus tenant-defined rows. mcp_endpoints.category stores the slug when a write matches.';
COMMENT ON COLUMN mcp_categories.tenant_id IS
    'NULL for a built-in category; the owning tenant for a tenant-defined category.';
COMMENT ON COLUMN mcp_categories.slug IS
    'Stable identifier stored on mcp_endpoints.category (lowercase letters, digits, hyphens).';
COMMENT ON TABLE mcp_endpoint_tags IS
    'Free-form, normalized manual tags on catalog endpoints (#3693), surfaced as a browse/search facet.';
COMMENT ON COLUMN mcp_endpoint_tags.tag IS
    'Normalized tag: lowercase letters, digits and . _ : - (no spaces), at most 64 characters.';
