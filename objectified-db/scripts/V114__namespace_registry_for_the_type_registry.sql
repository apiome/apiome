-- Namespace registry for the type registry — #3451, ROADMAP_TYPE_REGISTRY_GOVERNANCE.md §7 Issue 2.2.
--
-- The Namespace CRUD API (GET/POST/PUT /v1/types/{tenant_slug}/namespaces) manages namespaces
-- (scope, base URI, version root, visibility, default) over the existing `objectified-db`
-- connection. The acceptance criteria require *creating* a namespace (which may carry no types
-- yet) and *persisting* its default + visibility flags — neither of which can live on the
-- per-type `odb.primitives` rows (there is no row for an empty namespace, and no column for a
-- per-scope "default"). So namespaces get one durable home: this small `odb.type_namespaces`
-- table, in the SAME database / `odb` schema (no separate database — see §1a).
--
-- The table's `namespace` / `base_uri` columns mirror the same-named columns on `odb.primitives`
-- (#3447). `namespace` is the join key: a namespace's type count is COUNT(odb.primitives) sharing
-- its `namespace` string, so the API still operates over the extended primitives columns.
--
-- Scope:
--   system-core  — is_system = true, tenant_id IS NULL, visible to every tenant (is_public = true);
--                  curated by platform governance and read-only to tenant admins.
--   tenant-owned — is_system = false, tenant_id = <tenant>, private to that tenant.

SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS odb.type_namespaces (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID REFERENCES odb.tenants(id) ON DELETE CASCADE,  -- NULL for system-core namespaces
  namespace TEXT NOT NULL,            -- registry path, e.g. std/v0/types or tenant/acme/v1/types
  base_uri TEXT NOT NULL,             -- base URL relative $ref values resolve against (trailing slash)
  version_root TEXT,                  -- version segment, e.g. v0 / v1 / v2
  description TEXT,
  is_system BOOLEAN NOT NULL DEFAULT false,  -- platform-curated system-core namespace (std/*)
  is_public BOOLEAN NOT NULL DEFAULT false,  -- visible to all tenants (true for system-core)
  is_default BOOLEAN NOT NULL DEFAULT false, -- default namespace for new types in its scope
  created_by UUID REFERENCES odb.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE odb.type_namespaces IS
  'Type-registry namespaces (#3451): scope (system/tenant), base URI, version root, visibility, default. namespace mirrors odb.primitives.namespace (the type-count join key).';
COMMENT ON COLUMN odb.type_namespaces.tenant_id IS 'Owning tenant; NULL for system-core (std/*) namespaces.';
COMMENT ON COLUMN odb.type_namespaces.namespace IS 'Registry path, e.g. std/v0/types or tenant/<slug>/v1/types. Immutable once created (it links odb.primitives rows).';
COMMENT ON COLUMN odb.type_namespaces.base_uri IS 'Base URL the namespace''s relative $ref values resolve against (trailing slash).';
COMMENT ON COLUMN odb.type_namespaces.is_system IS 'Platform-curated system-core namespace; read-only to tenant admins.';
COMMENT ON COLUMN odb.type_namespaces.is_public IS 'Visible to all tenants (always true for system-core; false for tenant-private).';
COMMENT ON COLUMN odb.type_namespaces.is_default IS 'Default namespace for new types in its scope (at most one per scope/tenant).';

-- Uniqueness: a system-core path is globally unique; a tenant path is unique within its tenant.
CREATE UNIQUE INDEX IF NOT EXISTS uq_type_namespaces_system_path
  ON odb.type_namespaces (namespace) WHERE is_system;
CREATE UNIQUE INDEX IF NOT EXISTS uq_type_namespaces_tenant_path
  ON odb.type_namespaces (tenant_id, namespace) WHERE NOT is_system;

-- List filter: "system-core ∪ this tenant".
CREATE INDEX IF NOT EXISTS idx_type_namespaces_tenant ON odb.type_namespaces (tenant_id);

-- Seed the std/v0 system-core namespaces already materialized as primitives by 20260622-240000.sql,
-- so the registry table is the single source of truth for them too. Idempotent: re-running — or
-- applying to a database that already has these rows — is a no-op.
INSERT INTO odb.type_namespaces (
    namespace, base_uri, version_root, description, is_system, is_public, is_default
)
VALUES
    ('std/v0/primitives', 'https://api.objectified.dev/types/std/v0/primitives/', 'v0',
     'JSON Schema base types (string, number, integer, boolean, null, array, object).',
     true, true, false),
    ('std/v0/types', 'https://api.objectified.dev/types/std/v0/types/', 'v0',
     'Derived & composite std types (date, date-time, uuid, email, decimal, currency-code, money, ...).',
     true, true, true)
ON CONFLICT DO NOTHING;

DO $$
BEGIN
    RAISE NOTICE 'odb.type_namespaces created and seeded with std/v0 system-core namespaces (#3451).';
END $$;
