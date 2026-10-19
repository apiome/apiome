-- Gateway configs as entities — CDG-5.3 (#5981).
--
-- A gateway's environments deploy the APIs Apiome catalogs, but until now they were only a column
-- on `catalog_connector_items`. This migration makes each (connector, environment) a catalog
-- entity — a **gateway config** — that every connector sync refreshes:
--
--   catalog_gateway_configs — one live row per (connector, environment): how many APIs it serves,
--                             its auth and rate-limit posture (read from the served APIs' imported
--                             gateway configuration), and its declared losses ("gateway configs
--                             carry no request/response schemas").
--
-- The CDG-3.1 `deployed_on` edges now run from a Project or catalog item to the gateway config of
-- the (connector, environment) that serves it, instead of to the connector, so `gateway_config`
-- joins the graph's node kinds. A gateway config can have an owner team (CDG-2.2).
--
-- Rules kept by the database:
--
--   1. **One live row per (connector, environment).** An item with no environment belongs to the
--      environment `''`. When a sync no longer sees an environment its row is soft-deleted, so an
--      edge or an audit entry that names it still resolves.
--   2. **Slugs are handles**, unique among a tenant's live gateway configs.
--   3. **Deleting a connector deletes its gateway configs** (ON DELETE CASCADE).
--
-- Rollback notes (reverse carefully in shared environments):
--   DELETE FROM apiome.catalog_edges WHERE from_kind = 'gateway_config' OR to_kind = 'gateway_config';
--   DELETE FROM apiome.entity_owners WHERE entity_kind = 'gateway_config';
--   DELETE FROM apiome.unowned_findings WHERE entity_kind = 'gateway_config';
--   -- re-add catalog_edges_node_kinds_check with the V288 kinds and both owner kind checks with
--   -- the V297 kinds;
--   DROP TABLE IF EXISTS apiome.catalog_gateway_configs;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- catalog_gateway_configs — one per (connector, environment).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_gateway_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    connector_id UUID NOT NULL REFERENCES catalog_connectors(id) ON DELETE CASCADE,
    -- The environment the connector reported ('' when it reports none): a Kong control plane, an
    -- AWS stage, an Azure APIM instance, an Apigee environment.
    environment TEXT NOT NULL DEFAULT '',
    slug VARCHAR(128) NOT NULL
        CONSTRAINT catalog_gateway_configs_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    -- "<connector name> · <environment>".
    name VARCHAR(400) NOT NULL
        CONSTRAINT catalog_gateway_configs_name_not_blank_check CHECK (btrim(name) <> ''),
    -- The connector kind the configuration comes from (kong-konnect, aws-apigateway, …).
    flavor VARCHAR(32) NOT NULL,
    api_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT catalog_gateway_configs_api_count_check CHECK (api_count >= 0),
    -- {auth: [...], rate_limits: [...], policies: [...], credential_redactions: n} — names and
    -- schemes only; credentials are redacted when the configuration is parsed.
    posture JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT catalog_gateway_configs_posture_object_check CHECK (jsonb_typeof(posture) = 'object'),
    -- [{construct, reason}] — what a gateway configuration cannot carry.
    declared_losses JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT catalog_gateway_configs_losses_array_check CHECK (jsonb_typeof(declared_losses) = 'array'),
    last_synced_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_gateway_configs_connector_env
    ON catalog_gateway_configs (tenant_id, connector_id, environment)
    WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_gateway_configs_tenant_slug
    ON catalog_gateway_configs (tenant_id, slug)
    WHERE deleted_at IS NULL;

COMMENT ON TABLE catalog_gateway_configs IS
    'One gateway configuration per (connector, environment): APIs served, auth and rate-limit posture, declared losses (CDG-5.3, #5981)';

-- ---------------------------------------------------------------------------------------------------
-- Widened checks.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE catalog_edges DROP CONSTRAINT IF EXISTS catalog_edges_node_kinds_check;
ALTER TABLE catalog_edges
    ADD CONSTRAINT catalog_edges_node_kinds_check CHECK (
        from_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector',
                      'repository', 'mcp_source', 'identity_group', 'gateway_config')
        AND to_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector',
                        'repository', 'mcp_source', 'identity_group', 'gateway_config')
    );

ALTER TABLE entity_owners DROP CONSTRAINT IF EXISTS entity_owners_kind_check;
ALTER TABLE entity_owners
    ADD CONSTRAINT entity_owners_kind_check
        CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector', 'agent', 'model',
                               'gateway_config'));

ALTER TABLE unowned_findings DROP CONSTRAINT IF EXISTS unowned_findings_kind_check;
ALTER TABLE unowned_findings
    ADD CONSTRAINT unowned_findings_kind_check
        CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector', 'agent', 'model',
                               'gateway_config'));
