-- Type-registry core schema (#3447, ROADMAP_TYPE_REGISTRY_GOVERNANCE.md §6 Issue 1.2).
--
-- Creates the registry's three core entity tables inside the `otr` schema of the
-- separate type-registry database (objectified-types-db): namespaces, type
-- definitions, and the relative `$ref` edges between them. The `otr` schema is
-- provisioned by the baseline migration (20260622-200000.sql, #3446).
--
-- No cross-database foreign keys: the core ADE schema (`odb`) lives in a different
-- database and is never referenced here. The existing /v1/primitives surface
-- (odb.primitives) is untouched and continues to serve legacy rows unchanged.

-- The registry reuses the same UUIDv4 generator convention as the core schema.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

SET search_path TO otr, public;

-- ---------------------------------------------------------------------------
-- type_namespace: an addressable collection of types. A namespace is either
-- system-scoped (core `std/*` types visible to all tenants, tenant_id NULL) or
-- tenant-scoped (private `tenant/<slug>/*` types, tenant_id set). `base_uri` is
-- the import-source base URL against which a type's relative `$ref` resolves
-- (Epic 3); `version_root` records the version segment (e.g. `v0`).
-- ---------------------------------------------------------------------------
CREATE TABLE type_namespace (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('system', 'tenant')),
    base_uri TEXT,
    version_root TEXT,
    visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('public', 'private')),
    tenant_id UUID,
    is_default BOOLEAN NOT NULL DEFAULT false,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    -- System namespaces carry no tenant; tenant namespaces must name their tenant.
    CONSTRAINT type_namespace_scope_tenant_ck CHECK (
        (scope = 'system' AND tenant_id IS NULL)
        OR (scope = 'tenant' AND tenant_id IS NOT NULL)
    )
);

COMMENT ON TABLE type_namespace IS
    'Objectified Type Registry namespace: a scoped, addressable collection of type definitions.';
COMMENT ON COLUMN type_namespace.path IS 'Namespace path, e.g. std/v0/types or tenant/acme/v0/types.';
COMMENT ON COLUMN type_namespace.scope IS 'system (core, all tenants) or tenant (private to tenant_id).';
COMMENT ON COLUMN type_namespace.base_uri IS 'Import-source base URL for relative $ref resolution (Epic 3).';
COMMENT ON COLUMN type_namespace.version_root IS 'Version segment of the namespace, e.g. v0.';
COMMENT ON COLUMN type_namespace.tenant_id IS 'Owning tenant id (objectified-db tenants.id) for tenant scope; NULL for system. No cross-database FK.';
COMMENT ON COLUMN type_namespace.is_default IS 'Marks the default namespace for new types in its scope.';

-- A namespace path is unique within its scope: globally for system namespaces,
-- per-tenant for tenant namespaces. Partial (deleted_at IS NULL) so a soft-deleted
-- path can be recreated.
CREATE UNIQUE INDEX uq_type_namespace_system_path
    ON type_namespace (path)
    WHERE scope = 'system' AND deleted_at IS NULL;
CREATE UNIQUE INDEX uq_type_namespace_tenant_path
    ON type_namespace (tenant_id, path)
    WHERE scope = 'tenant' AND deleted_at IS NULL;

CREATE INDEX idx_type_namespace_scope ON type_namespace (scope) WHERE deleted_at IS NULL;
CREATE INDEX idx_type_namespace_tenant_id ON type_namespace (tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_type_namespace_deleted_at ON type_namespace (deleted_at) WHERE deleted_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- type_definition: a single JSON Schema 2020-12 type within a namespace. The
-- `json_schema` JSONB holds the full schema document; `schema_id` mirrors its
-- `$id` (derived from the namespace base + name in Epic 2). `scope` is denormalized
-- from the owning namespace for fast scope-filtered reads (2.4).
-- ---------------------------------------------------------------------------
CREATE TABLE type_definition (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    namespace_id UUID NOT NULL REFERENCES type_namespace (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    schema_id TEXT,
    json_schema JSONB NOT NULL,
    draft TEXT NOT NULL DEFAULT '2020-12',
    scope TEXT NOT NULL CHECK (scope IN ('system', 'tenant')),
    source TEXT NOT NULL DEFAULT 'human' CHECK (source IN ('human', 'imported')),
    mutability TEXT NOT NULL DEFAULT 'mutable' CHECK (mutability IN ('mutable', 'immutable')),
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE type_definition IS
    'A JSON Schema 2020-12 type definition within a registry namespace.';
COMMENT ON COLUMN type_definition.namespace_id IS 'Owning namespace (otr.type_namespace.id).';
COMMENT ON COLUMN type_definition.name IS 'Type name, unique within its namespace, e.g. date or money.';
COMMENT ON COLUMN type_definition.schema_id IS 'The JSON Schema $id (namespace base_uri + name).';
COMMENT ON COLUMN type_definition.json_schema IS 'Full JSON Schema 2020-12 document for the type.';
COMMENT ON COLUMN type_definition.draft IS 'JSON Schema dialect/draft, default 2020-12.';
COMMENT ON COLUMN type_definition.scope IS 'system or tenant (denormalized from the owning namespace).';
COMMENT ON COLUMN type_definition.source IS 'human (authored in-app) or imported (from a JSON Schema / bundle).';
COMMENT ON COLUMN type_definition.mutability IS 'mutable or immutable (core/system types are immutable).';

-- (namespace_id, name) is unique. Partial (deleted_at IS NULL) so a soft-deleted
-- type name can be reclaimed.
CREATE UNIQUE INDEX uq_type_definition_namespace_name
    ON type_definition (namespace_id, name)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_type_definition_namespace_id ON type_definition (namespace_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_type_definition_scope ON type_definition (scope) WHERE deleted_at IS NULL;
CREATE INDEX idx_type_definition_schema_id ON type_definition (schema_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_type_definition_source ON type_definition (source) WHERE deleted_at IS NULL;
CREATE INDEX idx_type_definition_deleted_at ON type_definition (deleted_at) WHERE deleted_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- type_ref: a single relative `$ref` edge originating from a type definition.
-- `relative_ref` is the literal reference as authored (e.g. ../primitives/string);
-- `resolved_target` is the absolute/registry target once resolved (Epic 3); `status`
-- records whether resolution succeeded, is still pending a target, or is circular.
-- ---------------------------------------------------------------------------
CREATE TABLE type_ref (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type_id UUID NOT NULL REFERENCES type_definition (id) ON DELETE CASCADE,
    relative_ref TEXT NOT NULL,
    resolved_target TEXT,
    status TEXT NOT NULL DEFAULT 'unresolved' CHECK (status IN ('resolved', 'unresolved', 'circular')),
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE type_ref IS
    'A relative $ref edge from a type definition to another type, with resolution status.';
COMMENT ON COLUMN type_ref.source_type_id IS 'The referencing type definition (otr.type_definition.id).';
COMMENT ON COLUMN type_ref.relative_ref IS 'The literal relative $ref as authored, e.g. ../primitives/string.';
COMMENT ON COLUMN type_ref.resolved_target IS 'Absolute/registry target the ref resolves to (Epic 3); NULL until resolved.';
COMMENT ON COLUMN type_ref.status IS 'resolved, unresolved (target missing), or circular.';

-- A given (source, relative_ref) edge is recorded once. Partial (deleted_at IS NULL).
CREATE UNIQUE INDEX uq_type_ref_source_relative
    ON type_ref (source_type_id, relative_ref)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_type_ref_source_type_id ON type_ref (source_type_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_type_ref_status ON type_ref (status) WHERE deleted_at IS NULL;
CREATE INDEX idx_type_ref_deleted_at ON type_ref (deleted_at) WHERE deleted_at IS NOT NULL;
