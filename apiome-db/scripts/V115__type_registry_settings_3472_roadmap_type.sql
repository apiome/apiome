-- Type-registry settings — #3472, ROADMAP_TYPE_REGISTRY_GOVERNANCE.md §7 Issue 5.7.
--
-- The Type Registry Settings UI (Governance → Primitives → Settings) configures registry-wide
-- behavior: the default JSON Schema dialect, the `$ref` resolution policy (base URL, ref style,
-- remote allowlist, max depth, circular-ref policy), import defaults, and the validation/publishing
-- governance toggles read by the validation gate (#3479). These are per-tenant preferences that do
-- not belong on any individual `apiome.primitives` row, so they get one durable home: this small
-- `apiome.type_registry_settings` table, in the SAME database / `apiome` schema (single database — §1a;
-- there is no separate registry database to configure, so there is no DB-connection setting here).
--
-- One row per tenant, keyed by `tenant_id`. A tenant with no row yet uses the column defaults below
-- (the REST layer returns those defaults for a tenant that has never saved settings), so the table
-- is created empty and populated lazily on the first save.

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.type_registry_settings (
  tenant_id UUID PRIMARY KEY REFERENCES apiome.tenants(id) ON DELETE CASCADE,

  -- JSON Schema dialect
  default_draft TEXT NOT NULL DEFAULT '2020-12',          -- '2020-12' | '2019-09' | 'draft-07'
  strict_validation BOOLEAN NOT NULL DEFAULT true,        -- reject unknown formats
  allow_annotation_keywords BOOLEAN NOT NULL DEFAULT true,-- permit title/description/examples/etc.
  coerce_imported_drafts BOOLEAN NOT NULL DEFAULT true,   -- upgrade older drafts to default on import

  -- Reference resolution
  resolution_base_url TEXT NOT NULL DEFAULT 'https://api.apiome.app/types/',
  ref_style TEXT NOT NULL DEFAULT 'relative',             -- 'relative' | 'absolute' | 'anchor'
  allow_remote_refs BOOLEAN NOT NULL DEFAULT false,       -- fetch schemas from external hosts
  remote_host_allowlist TEXT[] NOT NULL DEFAULT ARRAY['json-schema.org', 'spec.openapis.org'],
  max_resolution_depth INTEGER NOT NULL DEFAULT 12,       -- 1..64
  circular_ref_policy TEXT NOT NULL DEFAULT 'error',      -- 'error' | 'warn'

  -- Import defaults
  default_import_scope TEXT NOT NULL DEFAULT 'tenant',    -- 'tenant' | 'system'
  default_target_namespace TEXT,                          -- NULL = no preselected namespace
  rewrite_refs_on_import BOOLEAN NOT NULL DEFAULT true,   -- convert absolute $ref to base-relative
  accepted_formats TEXT[] NOT NULL
    DEFAULT ARRAY['json-schema-2020-12', 'type-def-bundle', 'openapi-3.1'],
  dedupe_identical_types BOOLEAN NOT NULL DEFAULT true,   -- reuse a byte-for-byte identical type

  -- Validation & publishing governance (read by the validation gate, #3479)
  validate_on_save BOOLEAN NOT NULL DEFAULT true,         -- run dialect & $ref checks before persist
  block_publish_on_errors BOOLEAN NOT NULL DEFAULT true,  -- block publish on unresolved $ref / errors
  core_publish_role TEXT NOT NULL DEFAULT 'platform_admin', -- 'platform_admin'|'tenant_admin'|'maintainer'

  updated_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

  -- Enum guards mirror the REST request-model validation so a bad value can never be persisted,
  -- even by a direct SQL write.
  CONSTRAINT ck_trs_default_draft CHECK (default_draft IN ('2020-12', '2019-09', 'draft-07')),
  CONSTRAINT ck_trs_ref_style CHECK (ref_style IN ('relative', 'absolute', 'anchor')),
  CONSTRAINT ck_trs_circular_policy CHECK (circular_ref_policy IN ('error', 'warn')),
  CONSTRAINT ck_trs_import_scope CHECK (default_import_scope IN ('tenant', 'system')),
  CONSTRAINT ck_trs_core_publish_role
    CHECK (core_publish_role IN ('platform_admin', 'tenant_admin', 'maintainer')),
  CONSTRAINT ck_trs_max_depth CHECK (max_resolution_depth BETWEEN 1 AND 64)
);

COMMENT ON TABLE apiome.type_registry_settings IS
  'Per-tenant type-registry behavior settings (#3472): dialect, $ref resolution policy, import defaults, validation/publishing governance. One row per tenant; absent row means defaults.';
COMMENT ON COLUMN apiome.type_registry_settings.default_draft IS 'Default JSON Schema dialect for new/imported types.';
COMMENT ON COLUMN apiome.type_registry_settings.resolution_base_url IS 'Base URL relative $ref values resolve against.';
COMMENT ON COLUMN apiome.type_registry_settings.remote_host_allowlist IS 'Hosts permitted for remote $ref fetches when allow_remote_refs is true.';
COMMENT ON COLUMN apiome.type_registry_settings.max_resolution_depth IS 'Maximum $ref resolution depth (1..64) before the resolver bails.';
COMMENT ON COLUMN apiome.type_registry_settings.validate_on_save IS 'Run dialect & $ref checks before persisting a type (validation gate #3479).';
COMMENT ON COLUMN apiome.type_registry_settings.block_publish_on_errors IS 'Block publishing a type with unresolved $ref or schema errors (#3479).';

DO $$
BEGIN
    RAISE NOTICE 'apiome.type_registry_settings created (#3472).';
END $$;
