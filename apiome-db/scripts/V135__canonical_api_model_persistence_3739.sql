-- Normalized canonical-API-model persistence (#3739, MFI-2.2): make the canonical model queryable.
--
-- MFI-2.1 (#3738) defined the paradigm-agnostic canonical model in
-- `apiome-rest/src/app/canonical_model.py` (`CanonicalApi`): one normalized shape that every
-- importable API format (REST/OpenAPI, RPC/gRPC, event/AsyncAPI, graph/GraphQL, data-schema/Avro)
-- maps into, so versioning/diff/lint/browse are written once. That model is a Pydantic tree; this
-- migration gives it a relational home so it is *queryable* (browse/search/diff) rather than an
-- opaque JSONB blob.
--
-- The tables mirror the canonical tree exactly (see the EPIC-2 ER diagram in
-- docs/ROADMAP_MULTI_FORMAT_IMPORT.md):
--
--   api_artifacts                       -- CanonicalApi: format, protocol, identity, version, servers
--     ├─ api_services                   -- Service: named groups of operations
--     │    └─ api_operations            -- Operation: kind + streaming + verb/route / channel binding
--     │         └─ api_messages         -- Message: in/out payloads (+ headers, status, media type)
--     ├─ api_channels                   -- Channel: event addresses / bindings (event-driven)
--     └─ api_types                      -- Type: record/enum/union/scalar/alias/map
--          └─ api_fields                -- CanonicalField: typed, nullable, defaulted, constrained
--
-- Design notes:
--
-- * **One artifact per version.** Each artifact is tied to a `versions` row (reusing the existing
--   `versions`/`version_tags` machinery, per the ticket) via `version_id`. A partial unique index
--   enforces at most one *live* artifact per version; soft-deleting one lets a re-import create a
--   fresh artifact for the same version without colliding.
--
-- * **Tenant scoping on every table.** Every table carries `tenant_id` (FK `tenants`) and
--   `version_id` (FK `versions`). These are denormalized on the child tables — they are derivable by
--   walking up to the artifact and out to the version's project — but carrying them directly lets
--   tenant-scoped browse/search/diff queries filter without multi-level joins, and keeps the tables
--   RLS-ready. The structural parent FK (`artifact_id` / `service_id` / `operation_id` / `type_id`)
--   defines the tree; cascading on it deletes a subtree cleanly.
--
-- * **Stable keys.** Every entity stores the canonical `key` a normalizer assigns deterministically
--   (GraphQL Schema Coordinates, protobuf package-qualified names + field numbers, XSD QNames). Keys
--   are unique within their parent (partial unique index, live rows only) so diffs between two
--   versions line up by identity, not position. `ordinal` preserves source declaration order.
--
-- * **JSONB for the irregular bits + fidelity.** Small/variadic sub-structures that do not warrant
--   their own tables are stored as JSONB mirroring the Pydantic shape: `servers`, operation
--   `parameters`/`tags`, message `headers`/`content_types`/`payload`/`payload_schema`, channel
--   `parameters`/`bindings`, type `enum_values`/`union_members`/`aliased`/`key_type`/`value_type`,
--   field `type_ref`/`default_value`, and `constraints` everywhere. Each entity also keeps its
--   `extras` bag, and the artifact keeps `raw` (native AST), so normalization stays lossless.
--
-- * **Search.** Per the AC ("indexed for search"), the browsable tables get expression GIN tsvector
--   indexes over their human-facing text. `to_tsvector('english', …)` with a constant config is
--   IMMUTABLE, so these are index-safe without stored columns or refresh triggers (same approach as
--   V127's capability-item FTS). MFI-6.2 (#…, "search the normalized model") reuses these indexes.
--
-- * **Enum check constraints** mirror the string values of the canonical model's Python enums
--   (ApiParadigm, OperationKind, StreamingMode, MessageRole, TypeKind) so the DB rejects values the
--   model cannot produce. Parameter/field locations live inside JSONB and are validated in the app.
--
-- Rollback notes: purely additive. To roll back, drop the tables in child-to-parent order (or simply
-- `DROP TABLE IF EXISTS apiome.api_fields, apiome.api_messages, apiome.api_operations, apiome.api_channels,
-- apiome.api_types, apiome.api_services, apiome.api_artifacts CASCADE;`) — this also drops the dependent
-- indexes. No shared types/enums are introduced.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- api_artifacts — the root: one normalized API description at one version (CanonicalApi).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_artifacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    creator_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

    -- Envelope version of the canonical model shape (CANONICAL_API_SCHEMA_VERSION); lets readers
    -- migrate older JSONB rows forward when the model changes.
    schema_version INTEGER NOT NULL DEFAULT 1,

    -- High-level interaction style + concrete source format/protocol (CanonicalApi.paradigm/format).
    paradigm VARCHAR(32) NOT NULL,
    format VARCHAR(128) NOT NULL,
    protocol VARCHAR(64),

    -- Version-independent artifact identity (ApiIdentity).
    identity_name VARCHAR(255) NOT NULL,
    identity_namespace VARCHAR(255),
    identity_id TEXT,

    -- Source-declared version of the API (e.g. "1.4.0"); distinct from the owning versions row.
    source_version VARCHAR(255),
    title TEXT,
    description TEXT,

    -- Host/endpoint list (Server[]); small and variadic, stored as JSONB.
    servers JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Format-specific attributes the canonical fields do not model.
    extras JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Native AST / source document, retained for full-fidelity round-tripping and per-format lint.
    raw JSONB,

    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Paradigm must be one of the canonical ApiParadigm values.
    CONSTRAINT api_artifacts_paradigm_check
        CHECK (paradigm IN ('rest', 'rpc', 'event', 'graph', 'data_schema')),
    CONSTRAINT api_artifacts_schema_version_check
        CHECK (schema_version >= 1)
);

-- At most one live artifact per version (a re-import soft-deletes the old one first).
CREATE UNIQUE INDEX IF NOT EXISTS uq_api_artifacts_version
    ON api_artifacts(version_id) WHERE deleted_at IS NULL;
-- Scope/list every artifact a tenant owns (live rows only).
CREATE INDEX IF NOT EXISTS idx_api_artifacts_tenant_id
    ON api_artifacts(tenant_id) WHERE deleted_at IS NULL;
-- Browse facets: filter the catalog by paradigm/format.
CREATE INDEX IF NOT EXISTS idx_api_artifacts_paradigm_format
    ON api_artifacts(paradigm, format) WHERE deleted_at IS NULL;
-- Full-text search over the artifact's human-facing text (MFI-6.2 reuses this).
CREATE INDEX IF NOT EXISTS idx_api_artifacts_fts
    ON api_artifacts USING gin (to_tsvector('english',
        coalesce(title, '') || ' ' || coalesce(description, '') || ' ' ||
        coalesce(identity_name, '') || ' ' || coalesce(format, '')));

COMMENT ON TABLE api_artifacts IS 'Root of a persisted canonical API model (CanonicalApi) for one versions row; queryable for browse/search/diff (#3739, MFI-2.2)';
COMMENT ON COLUMN api_artifacts.id IS 'Unique identifier for the artifact';
COMMENT ON COLUMN api_artifacts.tenant_id IS 'Owning tenant; cascade-deleted with the tenant';
COMMENT ON COLUMN api_artifacts.version_id IS 'Owning schema revision (versions.id); at most one live artifact per version';
COMMENT ON COLUMN api_artifacts.creator_id IS 'User who produced this artifact (deletion restricted while artifacts exist)';
COMMENT ON COLUMN api_artifacts.schema_version IS 'Envelope version of the canonical model shape (CANONICAL_API_SCHEMA_VERSION)';
COMMENT ON COLUMN api_artifacts.paradigm IS 'Canonical ApiParadigm: rest, rpc, event, graph, or data_schema';
COMMENT ON COLUMN api_artifacts.format IS 'Source format key, e.g. openapi-3.1, asyncapi-3, grpc, graphql, avro';
COMMENT ON COLUMN api_artifacts.protocol IS 'Primary transport protocol (http, grpc, kafka, graphql-over-http); null when not applicable';
COMMENT ON COLUMN api_artifacts.identity_name IS 'Human/source name of the API (ApiIdentity.name)';
COMMENT ON COLUMN api_artifacts.identity_namespace IS 'Package/group/target namespace (ApiIdentity.namespace); null when none';
COMMENT ON COLUMN api_artifacts.identity_id IS 'Globally stable id when the source provides one — URN, package path, $id (ApiIdentity.id)';
COMMENT ON COLUMN api_artifacts.source_version IS 'Source-declared version of the API (e.g. 1.4.0); distinct from the owning versions row';
COMMENT ON COLUMN api_artifacts.title IS 'Optional display title of the API';
COMMENT ON COLUMN api_artifacts.description IS 'Optional free-text description of the API';
COMMENT ON COLUMN api_artifacts.servers IS 'Server[] (host/endpoint templates + variables) as JSONB mirroring the canonical shape';
COMMENT ON COLUMN api_artifacts.extras IS 'Format-specific attributes the canonical fields do not model';
COMMENT ON COLUMN api_artifacts.raw IS 'Native AST / source document, retained for lossless round-tripping and per-format lint';
COMMENT ON COLUMN api_artifacts.deleted_at IS 'Soft delete timestamp; null means the artifact is live';
COMMENT ON COLUMN api_artifacts.created_at IS 'Timestamp when the artifact was created';
COMMENT ON COLUMN api_artifacts.updated_at IS 'Timestamp when the artifact was last updated';

-- ---------------------------------------------------------------------------------------------------
-- api_services — named groups of operations (Service).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_services (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL REFERENCES api_artifacts(id) ON DELETE CASCADE,

    -- Stable coordinate the normalizer assigns (e.g. acme.PetService); unique within the artifact.
    key VARCHAR(512) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Source declaration order, preserved for stable rendering.
    ordinal INTEGER NOT NULL DEFAULT 0,
    extras JSONB NOT NULL DEFAULT '{}'::jsonb,

    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT api_services_ordinal_check CHECK (ordinal >= 0)
);

-- A service key is unique within its artifact (live rows only) so diffs line up by identity.
CREATE UNIQUE INDEX IF NOT EXISTS uq_api_services_artifact_key
    ON api_services(artifact_id, key) WHERE deleted_at IS NULL;
-- List a version's services for browse/diff.
CREATE INDEX IF NOT EXISTS idx_api_services_version_id
    ON api_services(version_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_services_tenant_id
    ON api_services(tenant_id) WHERE deleted_at IS NULL;

COMMENT ON TABLE api_services IS 'Named groups of operations within a persisted canonical artifact (Service) (#3739, MFI-2.2)';
COMMENT ON COLUMN api_services.id IS 'Unique identifier for the service';
COMMENT ON COLUMN api_services.tenant_id IS 'Owning tenant (denormalized for tenant-scoped queries); cascade-deleted with the tenant';
COMMENT ON COLUMN api_services.version_id IS 'Owning schema revision (versions.id), denormalized from the artifact';
COMMENT ON COLUMN api_services.artifact_id IS 'Parent artifact; cascade-deleted with it';
COMMENT ON COLUMN api_services.key IS 'Stable canonical coordinate (e.g. acme.PetService); unique within the artifact';
COMMENT ON COLUMN api_services.name IS 'Source service name';
COMMENT ON COLUMN api_services.description IS 'Optional free-text description of the service';
COMMENT ON COLUMN api_services.ordinal IS 'Zero-based source declaration order';
COMMENT ON COLUMN api_services.extras IS 'Format-specific attributes the canonical fields do not model';
COMMENT ON COLUMN api_services.deleted_at IS 'Soft delete timestamp; null means the service is live';
COMMENT ON COLUMN api_services.created_at IS 'Timestamp when the service row was created';
COMMENT ON COLUMN api_services.updated_at IS 'Timestamp when the service row was last updated';

-- ---------------------------------------------------------------------------------------------------
-- api_operations — a single callable/subscribable unit within a service (Operation).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_operations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    service_id UUID NOT NULL REFERENCES api_services(id) ON DELETE CASCADE,

    -- Stable coordinate (e.g. Query.user, acme.PetService.GetPet, GET /pets/{id}).
    key VARCHAR(512) NOT NULL,
    name VARCHAR(255) NOT NULL,

    -- Message-exchange semantics + streaming cardinality (OperationKind / StreamingMode).
    kind VARCHAR(32) NOT NULL,
    streaming VARCHAR(32) NOT NULL DEFAULT 'none',

    -- HTTP verb/route when the paradigm has one; channel binding for event-driven operations.
    http_method VARCHAR(16),
    http_path TEXT,
    channel_ref VARCHAR(512),

    description TEXT,
    deprecated BOOLEAN NOT NULL DEFAULT false,

    -- Non-body inputs (Parameter[]) and grouping tags (string[]) as JSONB mirroring the model.
    parameters JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,

    ordinal INTEGER NOT NULL DEFAULT 0,
    extras JSONB NOT NULL DEFAULT '{}'::jsonb,

    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- kind / streaming must be canonical OperationKind / StreamingMode values.
    CONSTRAINT api_operations_kind_check
        CHECK (kind IN ('request_response', 'one_way', 'publish', 'subscribe',
                        'query', 'mutation', 'subscription')),
    CONSTRAINT api_operations_streaming_check
        CHECK (streaming IN ('none', 'client', 'server', 'bidirectional')),
    CONSTRAINT api_operations_ordinal_check CHECK (ordinal >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_api_operations_service_key
    ON api_operations(service_id, key) WHERE deleted_at IS NULL;
-- Browse/diff all operations of a version; also backs lookups by (version_id) alone.
CREATE INDEX IF NOT EXISTS idx_api_operations_version_id
    ON api_operations(version_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_operations_tenant_id
    ON api_operations(tenant_id) WHERE deleted_at IS NULL;
-- Full-text search over operations (MFI-6.2).
CREATE INDEX IF NOT EXISTS idx_api_operations_fts
    ON api_operations USING gin (to_tsvector('english',
        coalesce(name, '') || ' ' || coalesce(description, '') || ' ' ||
        coalesce(http_path, '') || ' ' || coalesce(key, '')));

COMMENT ON TABLE api_operations IS 'Callable/subscribable operations within a persisted canonical service (Operation) (#3739, MFI-2.2)';
COMMENT ON COLUMN api_operations.id IS 'Unique identifier for the operation';
COMMENT ON COLUMN api_operations.tenant_id IS 'Owning tenant (denormalized for tenant-scoped queries); cascade-deleted with the tenant';
COMMENT ON COLUMN api_operations.version_id IS 'Owning schema revision (versions.id), denormalized from the artifact';
COMMENT ON COLUMN api_operations.service_id IS 'Parent service; cascade-deleted with it';
COMMENT ON COLUMN api_operations.key IS 'Stable canonical coordinate (e.g. Query.user, GET /pets/{id}); unique within the service';
COMMENT ON COLUMN api_operations.name IS 'Source operation name';
COMMENT ON COLUMN api_operations.kind IS 'Canonical OperationKind: request_response, one_way, publish, subscribe, query, mutation, subscription';
COMMENT ON COLUMN api_operations.streaming IS 'Canonical StreamingMode: none, client, server, or bidirectional';
COMMENT ON COLUMN api_operations.http_method IS 'HTTP verb (GET/POST/…) when the paradigm has one; null otherwise';
COMMENT ON COLUMN api_operations.http_path IS 'Route template (e.g. /pets/{id}) when the paradigm has one; null otherwise';
COMMENT ON COLUMN api_operations.channel_ref IS 'Key of the channel this operation publishes to / subscribes from (event-driven); null otherwise';
COMMENT ON COLUMN api_operations.description IS 'Optional free-text description of the operation';
COMMENT ON COLUMN api_operations.deprecated IS 'Whether the source marks this operation deprecated';
COMMENT ON COLUMN api_operations.parameters IS 'Parameter[] (path/query/header/cookie inputs) as JSONB mirroring the canonical shape';
COMMENT ON COLUMN api_operations.tags IS 'Grouping tags (string[]) as JSONB';
COMMENT ON COLUMN api_operations.ordinal IS 'Zero-based source declaration order';
COMMENT ON COLUMN api_operations.extras IS 'Format-specific attributes the canonical fields do not model';
COMMENT ON COLUMN api_operations.deleted_at IS 'Soft delete timestamp; null means the operation is live';
COMMENT ON COLUMN api_operations.created_at IS 'Timestamp when the operation row was created';
COMMENT ON COLUMN api_operations.updated_at IS 'Timestamp when the operation row was last updated';

-- ---------------------------------------------------------------------------------------------------
-- api_messages — in/out payloads of an operation (Message).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    operation_id UUID NOT NULL REFERENCES api_operations(id) ON DELETE CASCADE,

    -- Stable coordinate (e.g. GET /pets/{id}#response.200); unique within the operation.
    key VARCHAR(512) NOT NULL,
    role VARCHAR(32) NOT NULL,
    name VARCHAR(255),

    -- Payload as a named-type reference (TypeRef) and/or an inline JSON-Schema body.
    payload JSONB,
    payload_schema JSONB,

    -- Headers (CanonicalField[]) and media types (string[]) as JSONB mirroring the model.
    headers JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_types JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- REST response status (e.g. 200, 4XX, default); null for non-REST / non-response messages.
    status_code VARCHAR(16),
    description TEXT,

    ordinal INTEGER NOT NULL DEFAULT 0,
    extras JSONB NOT NULL DEFAULT '{}'::jsonb,

    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- role must be a canonical MessageRole value.
    CONSTRAINT api_messages_role_check
        CHECK (role IN ('request', 'response', 'error', 'event')),
    CONSTRAINT api_messages_ordinal_check CHECK (ordinal >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_api_messages_operation_key
    ON api_messages(operation_id, key) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_messages_version_id
    ON api_messages(version_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_messages_tenant_id
    ON api_messages(tenant_id) WHERE deleted_at IS NULL;
-- Full-text search over message text (MFI-6.2).
CREATE INDEX IF NOT EXISTS idx_api_messages_fts
    ON api_messages USING gin (to_tsvector('english',
        coalesce(name, '') || ' ' || coalesce(description, '')));

COMMENT ON TABLE api_messages IS 'In/out payloads of a persisted canonical operation (Message) (#3739, MFI-2.2)';
COMMENT ON COLUMN api_messages.id IS 'Unique identifier for the message';
COMMENT ON COLUMN api_messages.tenant_id IS 'Owning tenant (denormalized for tenant-scoped queries); cascade-deleted with the tenant';
COMMENT ON COLUMN api_messages.version_id IS 'Owning schema revision (versions.id), denormalized from the artifact';
COMMENT ON COLUMN api_messages.operation_id IS 'Parent operation; cascade-deleted with it';
COMMENT ON COLUMN api_messages.key IS 'Stable canonical coordinate (e.g. GET /pets/{id}#response.200); unique within the operation';
COMMENT ON COLUMN api_messages.role IS 'Canonical MessageRole: request, response, error, or event';
COMMENT ON COLUMN api_messages.name IS 'Optional source message name';
COMMENT ON COLUMN api_messages.payload IS 'Reference to the payload type (TypeRef) as JSONB, when it is a named type';
COMMENT ON COLUMN api_messages.payload_schema IS 'Inline payload JSON-Schema (JSONB) when the body is defined inline rather than as a named type';
COMMENT ON COLUMN api_messages.headers IS 'Message headers (CanonicalField[]) as JSONB';
COMMENT ON COLUMN api_messages.content_types IS 'Media types this message is encoded as (string[]) as JSONB';
COMMENT ON COLUMN api_messages.status_code IS 'Response status code for REST (e.g. 200, 4XX, default); null otherwise';
COMMENT ON COLUMN api_messages.description IS 'Optional free-text description of the message';
COMMENT ON COLUMN api_messages.ordinal IS 'Zero-based source declaration order';
COMMENT ON COLUMN api_messages.extras IS 'Format-specific attributes the canonical fields do not model';
COMMENT ON COLUMN api_messages.deleted_at IS 'Soft delete timestamp; null means the message is live';
COMMENT ON COLUMN api_messages.created_at IS 'Timestamp when the message row was created';
COMMENT ON COLUMN api_messages.updated_at IS 'Timestamp when the message row was last updated';

-- ---------------------------------------------------------------------------------------------------
-- api_channels — event addresses / bindings, attached to the artifact (Channel).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_channels (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL REFERENCES api_artifacts(id) ON DELETE CASCADE,

    -- Stable coordinate (e.g. user/signedup); unique within the artifact.
    key VARCHAR(512) NOT NULL,
    -- The wire address — topic, routing key, subject, or path.
    address TEXT NOT NULL,
    name VARCHAR(255),
    description TEXT,
    protocol VARCHAR(64),

    -- Address template parameters (CanonicalField[]) and protocol bindings as JSONB.
    parameters JSONB NOT NULL DEFAULT '[]'::jsonb,
    bindings JSONB NOT NULL DEFAULT '{}'::jsonb,

    ordinal INTEGER NOT NULL DEFAULT 0,
    extras JSONB NOT NULL DEFAULT '{}'::jsonb,

    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT api_channels_ordinal_check CHECK (ordinal >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_api_channels_artifact_key
    ON api_channels(artifact_id, key) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_channels_version_id
    ON api_channels(version_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_channels_tenant_id
    ON api_channels(tenant_id) WHERE deleted_at IS NULL;
-- Full-text search over channel text (MFI-6.2).
CREATE INDEX IF NOT EXISTS idx_api_channels_fts
    ON api_channels USING gin (to_tsvector('english',
        coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || coalesce(address, '')));

COMMENT ON TABLE api_channels IS 'Event addresses/bindings of a persisted canonical artifact (Channel) (#3739, MFI-2.2)';
COMMENT ON COLUMN api_channels.id IS 'Unique identifier for the channel';
COMMENT ON COLUMN api_channels.tenant_id IS 'Owning tenant (denormalized for tenant-scoped queries); cascade-deleted with the tenant';
COMMENT ON COLUMN api_channels.version_id IS 'Owning schema revision (versions.id), denormalized from the artifact';
COMMENT ON COLUMN api_channels.artifact_id IS 'Parent artifact; cascade-deleted with it';
COMMENT ON COLUMN api_channels.key IS 'Stable canonical coordinate (e.g. user/signedup); unique within the artifact';
COMMENT ON COLUMN api_channels.address IS 'The wire address — topic, routing key, subject, or path';
COMMENT ON COLUMN api_channels.name IS 'Optional source channel name';
COMMENT ON COLUMN api_channels.description IS 'Optional free-text description of the channel';
COMMENT ON COLUMN api_channels.protocol IS 'Transport protocol for this channel (kafka/amqp/mqtt/ws); null when none';
COMMENT ON COLUMN api_channels.parameters IS 'Address template parameters (CanonicalField[]) as JSONB';
COMMENT ON COLUMN api_channels.bindings IS 'Protocol-specific binding settings (partitions, qos, …) as JSONB';
COMMENT ON COLUMN api_channels.ordinal IS 'Zero-based source declaration order';
COMMENT ON COLUMN api_channels.extras IS 'Format-specific attributes the canonical fields do not model';
COMMENT ON COLUMN api_channels.deleted_at IS 'Soft delete timestamp; null means the channel is live';
COMMENT ON COLUMN api_channels.created_at IS 'Timestamp when the channel row was created';
COMMENT ON COLUMN api_channels.updated_at IS 'Timestamp when the channel row was last updated';

-- ---------------------------------------------------------------------------------------------------
-- api_types — named types defined by the artifact (Type).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL REFERENCES api_artifacts(id) ON DELETE CASCADE,

    -- Stable coordinate (e.g. User, acme.Pet, a QName); unique within the artifact.
    key VARCHAR(512) NOT NULL,
    name VARCHAR(255) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    namespace VARCHAR(255),
    description TEXT,
    deprecated BOOLEAN NOT NULL DEFAULT false,

    -- Kind-specific structure mirroring the canonical Type: enum_values (EnumValue[]),
    -- union_members (member type keys), aliased/key_type/value_type (TypeRef), constraints.
    -- RECORD members live in the api_fields child table.
    enum_values JSONB NOT NULL DEFAULT '[]'::jsonb,
    union_members JSONB NOT NULL DEFAULT '[]'::jsonb,
    aliased JSONB,
    key_type JSONB,
    value_type JSONB,
    constraints JSONB,

    ordinal INTEGER NOT NULL DEFAULT 0,
    extras JSONB NOT NULL DEFAULT '{}'::jsonb,

    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- kind must be a canonical TypeKind value.
    CONSTRAINT api_types_kind_check
        CHECK (kind IN ('record', 'enum', 'union', 'scalar', 'alias', 'map')),
    CONSTRAINT api_types_ordinal_check CHECK (ordinal >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_api_types_artifact_key
    ON api_types(artifact_id, key) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_types_version_id
    ON api_types(version_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_types_tenant_id
    ON api_types(tenant_id) WHERE deleted_at IS NULL;
-- Browse facet: filter types by kind within a version.
CREATE INDEX IF NOT EXISTS idx_api_types_version_kind
    ON api_types(version_id, kind) WHERE deleted_at IS NULL;
-- Full-text search over type text (MFI-6.2).
CREATE INDEX IF NOT EXISTS idx_api_types_fts
    ON api_types USING gin (to_tsvector('english',
        coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || coalesce(key, '')));

COMMENT ON TABLE api_types IS 'Named types defined by a persisted canonical artifact (Type) (#3739, MFI-2.2)';
COMMENT ON COLUMN api_types.id IS 'Unique identifier for the type';
COMMENT ON COLUMN api_types.tenant_id IS 'Owning tenant (denormalized for tenant-scoped queries); cascade-deleted with the tenant';
COMMENT ON COLUMN api_types.version_id IS 'Owning schema revision (versions.id), denormalized from the artifact';
COMMENT ON COLUMN api_types.artifact_id IS 'Parent artifact; cascade-deleted with it';
COMMENT ON COLUMN api_types.key IS 'Stable canonical coordinate (e.g. User, acme.Pet, a QName); unique within the artifact';
COMMENT ON COLUMN api_types.name IS 'Source type name';
COMMENT ON COLUMN api_types.kind IS 'Canonical TypeKind: record, enum, union, scalar, alias, or map';
COMMENT ON COLUMN api_types.namespace IS 'Package / namespace / XSD target namespace, when applicable; null otherwise';
COMMENT ON COLUMN api_types.description IS 'Optional free-text description of the type';
COMMENT ON COLUMN api_types.deprecated IS 'Whether the source marks this type deprecated';
COMMENT ON COLUMN api_types.enum_values IS 'ENUM members (EnumValue[]) as JSONB; empty for non-enum kinds';
COMMENT ON COLUMN api_types.union_members IS 'UNION variant type keys (string[]) in declaration order; empty for non-union kinds';
COMMENT ON COLUMN api_types.aliased IS 'ALIAS target reference (TypeRef) as JSONB; null for non-alias kinds';
COMMENT ON COLUMN api_types.key_type IS 'MAP key type (TypeRef) as JSONB; null for non-map kinds';
COMMENT ON COLUMN api_types.value_type IS 'MAP value type (TypeRef) as JSONB; null for non-map kinds';
COMMENT ON COLUMN api_types.constraints IS 'Type-level validation constraints (JSON-Schema vocabulary) as JSONB; null when none';
COMMENT ON COLUMN api_types.ordinal IS 'Zero-based source declaration order';
COMMENT ON COLUMN api_types.extras IS 'Format-specific attributes the canonical fields do not model';
COMMENT ON COLUMN api_types.deleted_at IS 'Soft delete timestamp; null means the type is live';
COMMENT ON COLUMN api_types.created_at IS 'Timestamp when the type row was created';
COMMENT ON COLUMN api_types.updated_at IS 'Timestamp when the type row was last updated';

-- ---------------------------------------------------------------------------------------------------
-- api_fields — members of a record/struct/object type (CanonicalField).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_fields (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    type_id UUID NOT NULL REFERENCES api_types(id) ON DELETE CASCADE,

    -- Stable coordinate (e.g. User.email); unique within the type.
    key VARCHAR(512) NOT NULL,
    name VARCHAR(255) NOT NULL,

    -- The field's type at this use site (TypeRef), carrying nullability and list nesting.
    type_ref JSONB NOT NULL,

    -- Positional identity for protobuf/Thrift; stable across renames so a rename is not add+remove.
    field_number INTEGER,
    -- Declared default value (any JSON scalar/structure), when the source provides one.
    default_value JSONB,
    constraints JSONB,
    description TEXT,
    deprecated BOOLEAN NOT NULL DEFAULT false,

    ordinal INTEGER NOT NULL DEFAULT 0,
    extras JSONB NOT NULL DEFAULT '{}'::jsonb,

    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT api_fields_ordinal_check CHECK (ordinal >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_api_fields_type_key
    ON api_fields(type_id, key) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_fields_version_id
    ON api_fields(version_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_fields_tenant_id
    ON api_fields(tenant_id) WHERE deleted_at IS NULL;
-- Full-text search over field text (MFI-6.2).
CREATE INDEX IF NOT EXISTS idx_api_fields_fts
    ON api_fields USING gin (to_tsvector('english',
        coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || coalesce(key, '')));

COMMENT ON TABLE api_fields IS 'Members of a persisted canonical record/struct/object type (CanonicalField) (#3739, MFI-2.2)';
COMMENT ON COLUMN api_fields.id IS 'Unique identifier for the field';
COMMENT ON COLUMN api_fields.tenant_id IS 'Owning tenant (denormalized for tenant-scoped queries); cascade-deleted with the tenant';
COMMENT ON COLUMN api_fields.version_id IS 'Owning schema revision (versions.id), denormalized from the artifact';
COMMENT ON COLUMN api_fields.type_id IS 'Parent type; cascade-deleted with it';
COMMENT ON COLUMN api_fields.key IS 'Stable canonical coordinate (e.g. User.email); unique within the type';
COMMENT ON COLUMN api_fields.name IS 'Source field name';
COMMENT ON COLUMN api_fields.type_ref IS 'The field type at this use site (TypeRef) as JSONB, carrying nullability and list nesting';
COMMENT ON COLUMN api_fields.field_number IS 'Positional identity for protobuf/Thrift; stable across renames; null when none';
COMMENT ON COLUMN api_fields.default_value IS 'Declared default value (JSONB) when the source provides one; null otherwise';
COMMENT ON COLUMN api_fields.constraints IS 'Field validation constraints (JSON-Schema vocabulary) as JSONB; null when none';
COMMENT ON COLUMN api_fields.description IS 'Optional free-text description of the field';
COMMENT ON COLUMN api_fields.deprecated IS 'Whether the source marks this field deprecated';
COMMENT ON COLUMN api_fields.ordinal IS 'Zero-based source declaration order';
COMMENT ON COLUMN api_fields.extras IS 'Format-specific attributes the canonical fields do not model';
COMMENT ON COLUMN api_fields.deleted_at IS 'Soft delete timestamp; null means the field is live';
COMMENT ON COLUMN api_fields.created_at IS 'Timestamp when the field row was created';
COMMENT ON COLUMN api_fields.updated_at IS 'Timestamp when the field row was last updated';
