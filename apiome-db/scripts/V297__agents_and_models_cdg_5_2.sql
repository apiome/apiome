-- Agent and model entities — CDG-5.2 (#5980).
--
-- Agents are the fastest-growing consumers and models are what they run on. Apiome already knows
-- its agents through agent keys (AGX-3.1, `api_keys.kind = 'agent'`) and toolsets (AGX-1.2)
-- without naming them; this migration names them as catalog entities.
--
--   catalog_models          — a model an agent runs on: provider, model name and version, where
--                             it is hosted and how it handles data; `deprecated_at` is shown on
--                             every agent that runs on it.
--   catalog_agents          — a named agent: runtime (framework or host), the model it runs on,
--                             `active` or `retired`.
--   catalog_agent_keys      — which agent keys an agent uses (an agent key belongs to at most one
--                             agent).
--   catalog_agent_consumers — the `consumer` row the agent is, per project its keys reach. An
--                             agent is a consumer, so CTG impact and the blast radius include it.
--
-- The agent's `consumes` edges are not written here: apiome-rest records a `consumer_contract`
-- (source `agent`) per project holding the operations its keys' toolsets enable, and the existing
-- CDG-3.1 `consumes` family derives the edges from it. Revoking a key records a new revision
-- without its operations, which marks those edges stale.
--
-- Rules kept by the database:
--
--   1. **Slugs are handles**, shaped like team slugs and unique among a tenant's live agents
--      (and live models), so retiring a name frees it.
--   2. **Deletes are soft** (`deleted_at`), so an audit entry or a past edge that names an agent
--      still resolves.
--   3. **An agent key belongs to one agent.** `catalog_agent_keys.api_key_id` is unique.
--   4. **One consumer per agent per project.** `catalog_agent_consumers (agent_id, project_id)`
--      is unique.
--
-- Constraint changes:
--   * `consumer_contract.source` gains `agent` (an agent's derived contract).
--   * `entity_owners.entity_kind` and `unowned_findings.entity_kind` gain `agent` and `model`, so
--     both can have an owner team (CDG-2.2) and route findings to it (CDG-2.3).
--
-- Rollback notes (reverse carefully in shared environments):
--   DELETE FROM apiome.consumer_contract WHERE source = 'agent';
--   ALTER TABLE apiome.consumer_contract DROP CONSTRAINT consumer_contract_source_check,
--     ADD CONSTRAINT consumer_contract_source_check CHECK (source IN ('pact', 'manual'));
--   DELETE FROM apiome.entity_owners WHERE entity_kind IN ('agent', 'model');
--   DELETE FROM apiome.unowned_findings WHERE entity_kind IN ('agent', 'model');
--   -- and re-add both kind checks with the five V285 kinds;
--   DROP TABLE IF EXISTS apiome.catalog_agent_consumers;
--   DROP TABLE IF EXISTS apiome.catalog_agent_keys;
--   DROP TABLE IF EXISTS apiome.catalog_agents;
--   DROP TABLE IF EXISTS apiome.catalog_models;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- catalog_models — what an agent runs on.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_models (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug VARCHAR(128) NOT NULL
        CONSTRAINT catalog_models_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    -- Display name; the API defaults it to `model_name`.
    name VARCHAR(200) NOT NULL
        CONSTRAINT catalog_models_name_not_blank_check CHECK (btrim(name) <> ''),
    provider VARCHAR(120) NOT NULL
        CONSTRAINT catalog_models_provider_not_blank_check CHECK (btrim(provider) <> ''),
    model_name VARCHAR(200) NOT NULL
        CONSTRAINT catalog_models_model_name_not_blank_check CHECK (btrim(model_name) <> ''),
    model_version VARCHAR(120),
    hosting VARCHAR(16) NOT NULL DEFAULT 'api'
        CONSTRAINT catalog_models_hosting_check CHECK (hosting IN ('api', 'self_hosted')),
    -- Free text: what the provider retains, where data is processed, training opt-outs.
    data_handling TEXT,
    deprecated_at TIMESTAMP WITH TIME ZONE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT catalog_models_tenant_id_key UNIQUE (tenant_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_models_tenant_slug
    ON catalog_models (tenant_id, slug)
    WHERE deleted_at IS NULL;

COMMENT ON TABLE catalog_models IS
    'A model agents run on: provider, version, hosting, data handling, deprecation (CDG-5.2, #5980)';

-- ---------------------------------------------------------------------------------------------------
-- catalog_agents — a named agent.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug VARCHAR(128) NOT NULL
        CONSTRAINT catalog_agents_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    name VARCHAR(200) NOT NULL
        CONSTRAINT catalog_agents_name_not_blank_check CHECK (btrim(name) <> ''),
    description TEXT,
    -- The framework or host the agent runs in (LangGraph, Claude Desktop, a Lambda, …).
    runtime VARCHAR(200),
    model_id UUID REFERENCES catalog_models(id) ON DELETE SET NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active'
        CONSTRAINT catalog_agents_status_check CHECK (status IN ('active', 'retired')),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT catalog_agents_tenant_id_key UNIQUE (tenant_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_agents_tenant_slug
    ON catalog_agents (tenant_id, slug)
    WHERE deleted_at IS NULL;

-- "Every agent that runs on this model."
CREATE INDEX IF NOT EXISTS idx_catalog_agents_model
    ON catalog_agents (model_id)
    WHERE deleted_at IS NULL AND model_id IS NOT NULL;

COMMENT ON TABLE catalog_agents IS
    'A named agent: runtime, model, status; it is a consumer of the projects its keys reach (CDG-5.2, #5980)';

-- ---------------------------------------------------------------------------------------------------
-- catalog_agent_keys — the agent keys an agent uses.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_agent_keys (
    agent_id UUID NOT NULL REFERENCES catalog_agents(id) ON DELETE CASCADE,
    -- An `api_keys` row of kind `agent` (checked by apiome-rest when linking).
    api_key_id UUID NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (agent_id, api_key_id),
    CONSTRAINT catalog_agent_keys_one_agent_per_key UNIQUE (api_key_id)
);

COMMENT ON TABLE catalog_agent_keys IS
    'Agent keys (api_keys kind agent) an agent uses; a key belongs to at most one agent (CDG-5.2, #5980)';

-- ---------------------------------------------------------------------------------------------------
-- catalog_agent_consumers — the consumer row an agent is, per project.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_agent_consumers (
    agent_id UUID NOT NULL REFERENCES catalog_agents(id) ON DELETE CASCADE,
    consumer_id UUID NOT NULL REFERENCES consumer(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (agent_id, project_id),
    CONSTRAINT catalog_agent_consumers_consumer_key UNIQUE (consumer_id)
);

COMMENT ON TABLE catalog_agent_consumers IS
    'The consumer an agent is in each project its keys reach (CDG-5.2, #5980)';

-- ---------------------------------------------------------------------------------------------------
-- Widened checks.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE consumer_contract DROP CONSTRAINT IF EXISTS consumer_contract_source_check;
ALTER TABLE consumer_contract
    ADD CONSTRAINT consumer_contract_source_check CHECK (source IN ('pact', 'manual', 'agent'));

ALTER TABLE entity_owners DROP CONSTRAINT IF EXISTS entity_owners_kind_check;
ALTER TABLE entity_owners
    ADD CONSTRAINT entity_owners_kind_check
        CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector', 'agent', 'model'));

ALTER TABLE unowned_findings DROP CONSTRAINT IF EXISTS unowned_findings_kind_check;
ALTER TABLE unowned_findings
    ADD CONSTRAINT unowned_findings_kind_check
        CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector', 'agent', 'model'));
