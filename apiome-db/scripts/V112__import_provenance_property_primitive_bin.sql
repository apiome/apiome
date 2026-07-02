-- Import provenance + property→primitive binding (#3448, ROADMAP_TYPE_REGISTRY_GOVERNANCE.md §6 Issue 1.3).
--
-- Two durable records were missing, both in the existing apiome-db / apiome schema
-- (single database, ordinary same-database foreign keys — no cross-DB ids):
--
--   1. Primitive imports wrote rows with no audit trail. #3447 added the per-row `source`
--      column ('human' | 'imported'), but there was no record of WHEN an import ran, WHAT it
--      pulled from, or its outcome. This mirrors the catalog import-history infrastructure
--      (apiome.tenant_repository_imports, #2299/#2305): one row per import carrying its options
--      and a JSON report.
--
--   2. The Designer merged a selected primitive's JSON inline onto a property with no persisted
--      link, so a bound property could not reload its `$ref`. We extend apiome.class_properties
--      with the stored `$ref` and a real FK to the resolved apiome.primitives row.

SET search_path TO apiome, public;

-- 1.3a — Import provenance. One row per primitive import, with its options and report JSON.
CREATE TABLE IF NOT EXISTS apiome.primitive_imports (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
  source_kind TEXT NOT NULL DEFAULT 'json-schema'
      CHECK (source_kind IN ('json-schema', 'type-def-bundle', 'openapi')),
  source_label TEXT,                              -- human label / filename / URL of the source, if known
  target_namespace TEXT,                          -- registry namespace imported into (NULL for legacy flat imports)
  options JSONB NOT NULL DEFAULT '{}'::jsonb,      -- import options echoed back for reproducibility
  report  JSONB NOT NULL DEFAULT '{}'::jsonb,      -- the import report: imported / skipped / errors lists + counts
  imported_count INTEGER NOT NULL DEFAULT 0,
  skipped_count  INTEGER NOT NULL DEFAULT 0,
  error_count    INTEGER NOT NULL DEFAULT 0,
  imported_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_primitive_imports_tenant_created
  ON apiome.primitive_imports (tenant_id, created_at DESC);

COMMENT ON TABLE apiome.primitive_imports IS
  'One row per primitive import (#3448) — auditable provenance: source, options, and a JSON outcome report.';
COMMENT ON COLUMN apiome.primitive_imports.source_kind IS
  'Shape of the imported document: json-schema (default), type-def-bundle, or openapi.';
COMMENT ON COLUMN apiome.primitive_imports.options IS
  'Import options echoed at import time (import_all, selected_definitions, ...) for reproducibility.';
COMMENT ON COLUMN apiome.primitive_imports.report IS
  'Import outcome report: {"imported": [...], "skipped": [...], "errors": [...]} plus counts.';

-- 1.3b — Property→primitive binding. The stored `$ref` plus a real FK to the resolved primitive.
ALTER TABLE class_properties
  ADD COLUMN IF NOT EXISTS primitive_id  UUID REFERENCES primitives(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS primitive_ref TEXT;

COMMENT ON COLUMN class_properties.primitive_id IS
  'Resolved target: FK to the apiome.primitives row this property is bound to (#3448). NULL for inline/library-only properties.';
COMMENT ON COLUMN class_properties.primitive_ref IS
  'The registry $ref string the Designer persisted for this binding (e.g. std/v0/primitives/string); pairs with primitive_id.';

-- Reverse lookup: "which class properties bind to this primitive" (impact analysis, cascade checks).
CREATE INDEX IF NOT EXISTS idx_class_properties_primitive_id
  ON class_properties (primitive_id)
  WHERE primitive_id IS NOT NULL;
