-- Type-registry baseline (#3446, ROADMAP_TYPE_REGISTRY_GOVERNANCE.md §1.1).
--
-- Provisions the schema namespace for the separate registry database
-- (objectified-types-db). Registry entity tables — type_namespace,
-- type_definition, type_ref — arrive in ticket #3447 (1.2) and are created
-- inside this `otr` schema. The core ADE schema (`odb`) lives in a different
-- database and is never referenced here (no cross-database foreign keys).

CREATE SCHEMA IF NOT EXISTS otr;

COMMENT ON SCHEMA otr IS
  'Objectified Type Registry: namespaces, type definitions, and $ref edges (objectified-types-db).';
