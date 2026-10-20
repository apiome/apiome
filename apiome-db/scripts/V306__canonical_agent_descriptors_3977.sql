-- Agent-descriptor paradigm persistence (#3977, MFI-18.4): agents and their skills as first-class
-- canonical entities.
--
-- MFI-2.2 (V135) gave the canonical model (`apiome-rest/src/app/canonical_model.py`) its relational
-- home: api_artifacts → services/operations/messages, channels, types/fields. Agents describe
-- themselves with skills, capabilities and auth rather than operations and types, so MFI-18.4 adds
-- `CanonicalApi.agents` — one `AgentDescriptor` per agent (an A2A Agent Card, or each agent of an ACP
-- `GET /agents` listing), each with `AgentSkill` entries. This migration stores them:
--   api_artifacts
--     └─ api_agent_descriptors          -- AgentDescriptor: identity, provider, version, capability
--          │                               flags, security schemes and requirements
--          └─ api_agent_skills          -- AgentSkill: id, name, tags, examples, input/output modes
--
-- Design notes (the V135 conventions):
-- * **Tenant scoping on every table.** `tenant_id` and `version_id` are denormalized onto both
--   tables for tenant-scoped queries without joins; the structural parent FK (`artifact_id`,
--   `agent_id`) defines the tree and cascades deletes.
-- * **Stable keys.** `key` is the canonical key the normalizer assigns (`<agent>` for a descriptor,
--   `<agent>.<skill id>` for a skill), unique within its parent among live rows, so a skill-level
--   diff between two versions lines up by the id the agent author chose. `skill_id` keeps that id
--   as written; `ordinal` keeps source order.
-- * **JSONB for the irregular bits.** Provider, capability flags, mode lists, security schemes
--   and requirements are JSONB mirroring the Pydantic shape, and each row keeps its `extras` bag,
--   so persistence is lossless against `CanonicalApi` equality.
-- * **Additive.** The same agents are still projected onto api_services / api_operations, which
--   is what lint, emitters and browse read; `service_ref` / `operation_ref` point at those rows'
--   keys. A model with no agents writes no rows here.
-- * **Search.** Expression GIN tsvector indexes over the human-facing text, as V135 does.
--
-- * **The `agent` paradigm.** V135's `api_artifacts_paradigm_check` predates the agent paradigm
--   (MCP, LLM tools, A2A, ACP, site manifests), so no agent model could be persisted at all. The
--   check is widened here to every `ApiParadigm` value; `apiome-rest/tests/
--   test_agent_descriptor_paradigm.py` pins it to the enum so the next paradigm cannot drift.
--
-- Rollback notes: additive apart from the widened check. To roll back, restore V135's check and
-- `DROP TABLE IF EXISTS apiome.api_agent_skills, apiome.api_agent_descriptors CASCADE;`.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- api_artifacts — allow the agent paradigm.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE api_artifacts DROP CONSTRAINT IF EXISTS api_artifacts_paradigm_check;
ALTER TABLE api_artifacts ADD CONSTRAINT api_artifacts_paradigm_check
    CHECK (paradigm IN ('rest', 'rpc', 'event', 'graph', 'data_schema', 'agent'));
COMMENT ON COLUMN api_artifacts.paradigm IS 'Canonical ApiParadigm: rest, rpc, event, graph, data_schema, or agent';

-- ---------------------------------------------------------------------------------------------------
-- api_agent_descriptors — one agent's self-description (AgentDescriptor).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_agent_descriptors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL REFERENCES api_artifacts(id) ON DELETE CASCADE,

    key VARCHAR(512) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    agent_version VARCHAR(255),
    url TEXT,
    protocol VARCHAR(32) NOT NULL,
    protocol_version VARCHAR(64),
    provider JSONB,
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
    default_input_modes JSONB NOT NULL DEFAULT '[]'::jsonb,
    default_output_modes JSONB NOT NULL DEFAULT '[]'::jsonb,
    security_schemes JSONB NOT NULL DEFAULT '[]'::jsonb,
    security JSONB NOT NULL DEFAULT '[]'::jsonb,
    service_ref VARCHAR(512),

    ordinal INTEGER NOT NULL DEFAULT 0,
    extras JSONB NOT NULL DEFAULT '{}'::jsonb,

    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT api_agent_descriptors_ordinal_check CHECK (ordinal >= 0),
    CONSTRAINT api_agent_descriptors_protocol_check CHECK (protocol IN ('a2a', 'acp'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_api_agent_descriptors_artifact_key
    ON api_agent_descriptors(artifact_id, key) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_agent_descriptors_version_id
    ON api_agent_descriptors(version_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_agent_descriptors_tenant_id
    ON api_agent_descriptors(tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_agent_descriptors_search
    ON api_agent_descriptors USING GIN (
        to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, ''))
    ) WHERE deleted_at IS NULL;

COMMENT ON TABLE api_agent_descriptors IS 'Agent descriptors of a persisted canonical artifact (AgentDescriptor) (#3977, MFI-18.4)';
COMMENT ON COLUMN api_agent_descriptors.id IS 'Unique identifier for the agent descriptor';
COMMENT ON COLUMN api_agent_descriptors.tenant_id IS 'Owning tenant (denormalized for tenant-scoped queries); cascade-deleted with the tenant';
COMMENT ON COLUMN api_agent_descriptors.version_id IS 'Owning schema revision (versions.id), denormalized from the artifact';
COMMENT ON COLUMN api_agent_descriptors.artifact_id IS 'Parent artifact; cascade-deleted with it';
COMMENT ON COLUMN api_agent_descriptors.key IS 'Stable canonical key of the agent; unique within the artifact';
COMMENT ON COLUMN api_agent_descriptors.name IS 'The agent name';
COMMENT ON COLUMN api_agent_descriptors.description IS 'Optional free-text description of the agent';
COMMENT ON COLUMN api_agent_descriptors.agent_version IS 'The agent''s own version string (not the protocol''s)';
COMMENT ON COLUMN api_agent_descriptors.url IS 'The agent''s primary endpoint, when declared';
COMMENT ON COLUMN api_agent_descriptors.protocol IS 'Agent protocol: a2a or acp';
COMMENT ON COLUMN api_agent_descriptors.protocol_version IS 'Protocol version the descriptor declares (A2A protocolVersion)';
COMMENT ON COLUMN api_agent_descriptors.provider IS 'Operating organization {organization, url}';
COMMENT ON COLUMN api_agent_descriptors.capabilities IS 'Capability flags verbatim (streaming, pushNotifications, ...)';
COMMENT ON COLUMN api_agent_descriptors.default_input_modes IS 'Media types every skill accepts unless it says otherwise';
COMMENT ON COLUMN api_agent_descriptors.default_output_modes IS 'Media types every skill produces unless it says otherwise';
COMMENT ON COLUMN api_agent_descriptors.security_schemes IS 'Typed security schemes [{name, type, scheme, location, ...}]';
COMMENT ON COLUMN api_agent_descriptors.security IS 'Agent-level security requirements [{scheme: [scopes]}]';
COMMENT ON COLUMN api_agent_descriptors.service_ref IS 'Key of the api_services row this agent is projected onto';
COMMENT ON COLUMN api_agent_descriptors.ordinal IS 'Zero-based source declaration order';
COMMENT ON COLUMN api_agent_descriptors.extras IS 'Format-specific attributes the canonical fields do not model';
COMMENT ON COLUMN api_agent_descriptors.deleted_at IS 'Soft delete timestamp; null means the descriptor is live';
COMMENT ON COLUMN api_agent_descriptors.created_at IS 'Timestamp when the descriptor row was created';
COMMENT ON COLUMN api_agent_descriptors.updated_at IS 'Timestamp when the descriptor row was last updated';

-- ---------------------------------------------------------------------------------------------------
-- api_agent_skills — one thing an agent can do (AgentSkill).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_agent_skills (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL REFERENCES api_artifacts(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES api_agent_descriptors(id) ON DELETE CASCADE,

    key VARCHAR(1024) NOT NULL,
    skill_id VARCHAR(512) NOT NULL,
    name VARCHAR(512) NOT NULL,
    description TEXT,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    examples JSONB NOT NULL DEFAULT '[]'::jsonb,
    input_modes JSONB NOT NULL DEFAULT '[]'::jsonb,
    output_modes JSONB NOT NULL DEFAULT '[]'::jsonb,
    security JSONB,
    operation_ref VARCHAR(1024),

    ordinal INTEGER NOT NULL DEFAULT 0,
    extras JSONB NOT NULL DEFAULT '{}'::jsonb,

    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT api_agent_skills_ordinal_check CHECK (ordinal >= 0)
);

-- A skill key is unique within its agent (live rows only) so skill-level diffs line up by id.
CREATE UNIQUE INDEX IF NOT EXISTS uq_api_agent_skills_agent_key
    ON api_agent_skills(agent_id, key) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_agent_skills_artifact_id
    ON api_agent_skills(artifact_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_agent_skills_version_id
    ON api_agent_skills(version_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_agent_skills_tenant_id
    ON api_agent_skills(tenant_id) WHERE deleted_at IS NULL;
-- Find every version whose agents offer a skill tag (browse facet).
CREATE INDEX IF NOT EXISTS idx_api_agent_skills_tags
    ON api_agent_skills USING GIN (tags) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_agent_skills_search
    ON api_agent_skills USING GIN (
        to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, ''))
    ) WHERE deleted_at IS NULL;

COMMENT ON TABLE api_agent_skills IS 'Skills of a persisted agent descriptor (AgentSkill) (#3977, MFI-18.4)';
COMMENT ON COLUMN api_agent_skills.id IS 'Unique identifier for the skill row';
COMMENT ON COLUMN api_agent_skills.tenant_id IS 'Owning tenant (denormalized for tenant-scoped queries); cascade-deleted with the tenant';
COMMENT ON COLUMN api_agent_skills.version_id IS 'Owning schema revision (versions.id), denormalized from the artifact';
COMMENT ON COLUMN api_agent_skills.artifact_id IS 'Owning artifact (denormalized); cascade-deleted with it';
COMMENT ON COLUMN api_agent_skills.agent_id IS 'Parent agent descriptor; cascade-deleted with it';
COMMENT ON COLUMN api_agent_skills.key IS 'Stable canonical key <agent>.<skill id>; unique within the agent';
COMMENT ON COLUMN api_agent_skills.skill_id IS 'The skill id as the agent declares it (A2A id, ACP capability name)';
COMMENT ON COLUMN api_agent_skills.name IS 'Human-readable skill name';
COMMENT ON COLUMN api_agent_skills.description IS 'Optional free-text description of the skill';
COMMENT ON COLUMN api_agent_skills.tags IS 'Discovery tags';
COMMENT ON COLUMN api_agent_skills.examples IS 'Example prompts the skill handles';
COMMENT ON COLUMN api_agent_skills.input_modes IS 'Declared input media types; empty inherits the agent defaults';
COMMENT ON COLUMN api_agent_skills.output_modes IS 'Declared output media types; empty inherits the agent defaults';
COMMENT ON COLUMN api_agent_skills.security IS 'The skill''s own security requirements; null inherits the agent''s';
COMMENT ON COLUMN api_agent_skills.operation_ref IS 'Key of the api_operations row this skill is projected onto';
COMMENT ON COLUMN api_agent_skills.ordinal IS 'Zero-based source declaration order';
COMMENT ON COLUMN api_agent_skills.extras IS 'Format-specific attributes the canonical fields do not model';
COMMENT ON COLUMN api_agent_skills.deleted_at IS 'Soft delete timestamp; null means the skill is live';
COMMENT ON COLUMN api_agent_skills.created_at IS 'Timestamp when the skill row was created';
COMMENT ON COLUMN api_agent_skills.updated_at IS 'Timestamp when the skill row was last updated';
