-- Consolidate the type registry into objectified-db; extend odb.primitives.
-- (#3446 reversal + #3447 redesign — ROADMAP_TYPE_REGISTRY_GOVERNANCE.md §6 Issues 1.1 & 1.2.)
--
-- DESIGN CHANGE: an earlier iteration created a SEPARATE registry database
-- (objectified-types-db) with its own `otr` schema and type_namespace / type_definition /
-- type_ref tables. That is the wrong design and is reversed here. Primitives are
-- tenant-scoped (tenant_id) AND system-wide (is_system / is_public), so the type registry
-- lives in the existing `odb` schema by EXTENDING the odb.primitives table in place — one
-- database, ordinary same-database foreign keys.
--
-- This migration (1.1) drops the obsolete `otr` schema if a prior migration created it, and
-- (1.2) adds the JSON Schema 2020-12 registry columns to odb.primitives. No new tables.

SET search_path TO odb, public;

-- 1.1 — Remove the obsolete separate-registry schema (and its type_* tables) if present.
-- Safe on databases that never created it; cleans up databases that applied the now-removed
-- 20260622-200000.sql / 20260622-210000.sql migrations.
DROP SCHEMA IF EXISTS otr CASCADE;

-- 1.2 — Extend odb.primitives with namespace / $id / base-uri / draft / source / $ref columns.
ALTER TABLE primitives
    ADD COLUMN IF NOT EXISTS namespace TEXT,
    ADD COLUMN IF NOT EXISTS base_uri  TEXT,
    ADD COLUMN IF NOT EXISTS schema_id TEXT,
    ADD COLUMN IF NOT EXISTS draft     TEXT  NOT NULL DEFAULT '2020-12',
    ADD COLUMN IF NOT EXISTS source    TEXT  NOT NULL DEFAULT 'human',
    ADD COLUMN IF NOT EXISTS refs      JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Constrain `source` to the supported provenance values.
ALTER TABLE primitives
    ADD CONSTRAINT primitives_source_ck CHECK (source IN ('human', 'imported'));

-- Column documentation.
COMMENT ON COLUMN primitives.namespace IS
    'Registry namespace path, e.g. std/v0/types (system-wide) or tenant/<slug>/types (tenant-owned).';
COMMENT ON COLUMN primitives.base_uri IS
    'Import-source base URL the primitive''s relative $ref values resolve against (Epic 3).';
COMMENT ON COLUMN primitives.schema_id IS 'The JSON Schema $id (namespace base_uri + name).';
COMMENT ON COLUMN primitives.draft IS 'JSON Schema dialect/draft for this primitive, default 2020-12.';
COMMENT ON COLUMN primitives.source IS 'Provenance: human (authored in-app) or imported (from a JSON Schema / bundle).';
COMMENT ON COLUMN primitives.refs IS
    'Array of relative $ref edges: [{"relative_ref": "../primitives/string", "resolved_target": "...", "status": "resolved|unresolved|circular"}].';

-- Indices for the new registry columns (GIN on refs for $ref containment lookups).
CREATE INDEX IF NOT EXISTS idx_primitives_namespace ON primitives (namespace);
CREATE INDEX IF NOT EXISTS idx_primitives_schema_id ON primitives (schema_id);
CREATE INDEX IF NOT EXISTS idx_primitives_source ON primitives (source);
CREATE INDEX IF NOT EXISTS idx_primitives_refs ON primitives USING GIN (refs);
