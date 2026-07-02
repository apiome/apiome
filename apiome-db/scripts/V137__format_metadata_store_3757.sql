-- Format-specific metadata store (#3757, MFI-7.2).
--
-- Problem: each importable format carries identity *beyond* the common canonical model — Avro
-- subject + compatibility level, gRPC package/edition, OData service root, WSDL targetNamespace,
-- schema-registry coordinates, and so on. These fields are needed by discovery, diff and lint, but
-- they differ per format. Modelling each as its own column would mean a schema migration every time a
-- new adapter wants to stash a new attribute ("schema churn per format" — explicitly disallowed by
-- the acceptance criteria).
--
-- Solution: a single open-ended JSONB `format_metadata` bag on `apiome.versions`. Each format adapter
-- writes the keys it cares about; readers (discovery/diff/lint) pull them back out. Adding a new
-- format, or new attributes to an existing one, never requires a DDL change.
--
--   format_metadata  -- JSONB map of adapter-specific attributes for this revision, e.g.
--                       Avro     {"subject": "user-value", "compatibility": "BACKWARD"}
--                       gRPC     {"package": "acme.user.v1", "edition": "2023"}
--                       OData    {"serviceRoot": "https://host/odata/"}
--                       WSDL     {"targetNamespace": "urn:acme:user"}
--                       registry {"registryUrl": "...", "schemaId": 42}
--                       Empty object when the adapter records nothing.
--
-- Why on `versions`, not `api_artifacts`: this mirrors V136 (MFI-7.1, source_format/protocol/
-- source_tool_versions) and V124 (quality score captured at import). An `api_artifacts` row only
-- exists once the full normalizer pipeline has run, whereas every import — including specs stored
-- without a persisted canonical model — always yields a `versions` row. Format metadata is captured
-- at import, so it must live on the universally-present revision entity to be available to discovery
-- and diff regardless of normalization state. (`api_artifacts.extras` is a *different* bag: the
-- format-specific attributes of the canonical model itself; this column is the import-time,
-- pre-/non-canonical metadata the catalog and adapters key off of.)
--
-- Nullability: NOT NULL DEFAULT '{}' — there is always a (possibly empty) bag, so readers never have
-- to null-check. Pre-existing and non-import revisions simply carry an empty object.
--
-- Indexing: intentionally none. Like V136's `source_tool_versions`, this is adapter provenance read
-- per-revision (you already hold the `versions` row when you want its metadata), not a cross-revision
-- facet. A JSONB GIN index here would be write-amplifying on the hot import path for no read benefit —
-- exactly the kind of unused JSONB GIN index V125 dropped to speed imports. Facet dimensions that DO
-- warrant indexing (source_format, protocol) already have their partial indexes from V136.
--
-- Rollback notes: purely additive. To roll back:
--   ALTER TABLE apiome.versions DROP COLUMN IF EXISTS format_metadata;

SET search_path TO apiome, public;

ALTER TABLE apiome.versions
  ADD COLUMN IF NOT EXISTS format_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN apiome.versions.format_metadata IS
  'JSONB bag of format-specific metadata captured at import for discovery/diff/lint (e.g. Avro subject/compatibility, gRPC package/edition, OData serviceRoot, WSDL targetNamespace, schema-registry coordinates). Adapter-defined keys — open-ended so a new format needs no schema change. Empty object when none recorded. Distinct from api_artifacts.extras, which holds canonical-model-level format attributes.';
