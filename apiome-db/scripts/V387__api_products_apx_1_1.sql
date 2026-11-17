-- API products — APX-1.1 (#6098).
--
-- Access is granted to a thing a consumer understands ("Payments API"), which is usually several
-- projects and versions, possibly MCP servers and catalog items. This migration adds that bundle:
--
--   api_products         — a named, owned bundle with a visibility (`private` | `workspace` |
--                          `portal`) and a lifecycle state (`draft` | `published` | `deprecated` |
--                          `retired`). The issue's slot was V311; the next free one is V387.
--   api_product_members  — what a product includes, one row per member:
--                            project_version — one project at a version label or a `2.x` range
--                                              (`version_selector`)
--                            project_latest  — one project at whatever version is published last,
--                                              so the product follows new publishes
--                            mcp_server      — one MCP server (`mcp_endpoints`)
--                            catalog_item    — one catalog item (a non-publishable `projects` row)
--                          `member_ref` is the member's id; `environment` optionally narrows it
--                          (`production`, `sandbox`).
--
-- `api_product` joins the graph's node kinds and `includes` its edge kinds: app.catalog_graph
-- derives one `includes` edge per member (product → member), so the dependency graph and the blast
-- radius of a change in a member see the products that bundle it.
--
-- Rules kept by the database:
--
--   1. **A slug is a handle**, shaped like a team slug and unique among a tenant's live products.
--      Deletes are soft, so an edge or an audit entry still resolves.
--   2. **A version selector belongs to a `project_version` member, and only to one.**
--   3. **A member cannot cross tenants.** It carries `tenant_id` and references its product by the
--      composite `(id, tenant_id)` key; deleting a product's row deletes its members.
--   4. **A member is listed once** per (product, kind, ref, selector, environment).
--
-- "A `portal` product's members are all published" depends on version state that changes after the
-- write, so apiome-rest checks it (app.api_products) on every visibility or membership change.
--
-- No new RBAC resource: products bundle projects, so they use `projects:view|create|edit|delete`.
--
-- Rollback notes (reverse carefully in shared environments):
--   DELETE FROM apiome.catalog_edges WHERE from_kind = 'api_product' OR to_kind = 'api_product'
--                                       OR edge_kind = 'includes';
--   -- re-add catalog_edges_node_kinds_check with the V299 kinds and catalog_edges_kind_check with
--   -- the V288 kinds;
--   DROP TABLE IF EXISTS apiome.api_product_members;
--   DROP TABLE IF EXISTS apiome.api_products;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- api_products — one bundle.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Rule 1.
    slug VARCHAR(128) NOT NULL
        CONSTRAINT api_products_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    name VARCHAR(200) NOT NULL
        CONSTRAINT api_products_name_not_blank_check CHECK (btrim(name) <> ''),
    summary TEXT
        CONSTRAINT api_products_summary_length_check CHECK (summary IS NULL OR length(summary) <= 4000),
    -- The team accountable for the product; a deleted team leaves it unowned rather than gone.
    owner_team_id UUID REFERENCES teams(id) ON DELETE SET NULL,

    visibility VARCHAR(16) NOT NULL DEFAULT 'private'
        CONSTRAINT api_products_visibility_check CHECK (visibility IN ('private', 'workspace', 'portal')),
    state VARCHAR(16) NOT NULL DEFAULT 'draft'
        CONSTRAINT api_products_state_check CHECK (state IN ('draft', 'published', 'deprecated', 'retired')),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,

    -- Rule 3: what members reference.
    CONSTRAINT api_products_id_tenant_key UNIQUE (id, tenant_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_api_products_tenant_slug
    ON api_products (tenant_id, slug)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_api_products_owner_team
    ON api_products (owner_team_id)
    WHERE owner_team_id IS NOT NULL;

COMMENT ON TABLE api_products IS
    'API products: named bundles of projects, versions, MCP servers and catalog items (APX-1.1, #6098)';
COMMENT ON COLUMN api_products.visibility IS 'private, workspace or portal; portal needs every member published';
COMMENT ON COLUMN api_products.state IS 'draft, published, deprecated or retired';

-- ---------------------------------------------------------------------------------------------------
-- api_product_members — what a product includes.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_product_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL,
    product_id UUID NOT NULL,

    member_kind VARCHAR(32) NOT NULL
        CONSTRAINT api_product_members_kind_check
            CHECK (member_kind IN ('project_version', 'project_latest', 'mcp_server', 'catalog_item')),
    -- The member's id: a projects row, or an mcp_endpoints row for `mcp_server`.
    member_ref UUID NOT NULL,
    -- Rule 2. An exact version label (`1.4.0`) or a range (`2.x`, `2.1.x`).
    version_selector VARCHAR(100)
        CONSTRAINT api_product_members_selector_shape_check
            CHECK (version_selector IS NULL OR version_selector ~ '^[A-Za-z0-9][A-Za-z0-9._+-]{0,99}$'),
    environment VARCHAR(64)
        CONSTRAINT api_product_members_environment_shape_check
            CHECK (environment IS NULL OR environment ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT api_product_members_selector_check
        CHECK ((member_kind = 'project_version') = (version_selector IS NOT NULL)),
    -- Rule 3.
    CONSTRAINT api_product_members_product_fk
        FOREIGN KEY (product_id, tenant_id) REFERENCES api_products (id, tenant_id) ON DELETE CASCADE,
    -- Rule 4.
    CONSTRAINT api_product_members_identity_key UNIQUE NULLS NOT DISTINCT
        (product_id, member_kind, member_ref, version_selector, environment)
);

-- "Which products include this entity" (the graph materializer and the member's own page).
CREATE INDEX IF NOT EXISTS idx_api_product_members_ref
    ON api_product_members (tenant_id, member_ref);

COMMENT ON TABLE api_product_members IS
    'What an API product includes: a project at a version or at latest, an MCP server or a catalog item (APX-1.1, #6098)';
COMMENT ON COLUMN api_product_members.version_selector IS
    'project_version only: an exact version label or a 2.x / 2.1.x range';

-- ---------------------------------------------------------------------------------------------------
-- Widened graph checks: the `api_product` node and its `includes` edges.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE catalog_edges DROP CONSTRAINT IF EXISTS catalog_edges_node_kinds_check;
ALTER TABLE catalog_edges
    ADD CONSTRAINT catalog_edges_node_kinds_check CHECK (
        from_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector',
                      'repository', 'mcp_source', 'identity_group', 'gateway_config', 'component',
                      'api_product')
        AND to_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector',
                        'repository', 'mcp_source', 'identity_group', 'gateway_config', 'component',
                        'api_product')
    );

ALTER TABLE catalog_edges DROP CONSTRAINT IF EXISTS catalog_edges_kind_check;
ALTER TABLE catalog_edges
    ADD CONSTRAINT catalog_edges_kind_check
        CHECK (edge_kind IN ('depends_on', 'consumes', 'served_by', 'deployed_on', 'built_from',
                             'converted_from', 'identity_of', 'runtime_calls', 'includes'));
