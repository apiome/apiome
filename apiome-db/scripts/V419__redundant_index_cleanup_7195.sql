-- Redundant and unused index cleanup (DBP-1.12, #7195).
--
-- Every index costs a write on each INSERT and each non-HOT UPDATE of its table. These buy
-- nothing:
--
--   1. Five indexes that are a leading prefix of another index with the same predicate (the
--      comment names the wider one). Any query that can use the narrow one can use the wider one.
--      The six others of this kind found by the audit (idx_classes_version_id,
--      idx_api_types_version_id, idx_push_webhook_subscriptions_tenant_id,
--      idx_tenant_repositories_tenant_id, idx_version_component_pins_version and, in V415,
--      idx_document_objects_tenant) are replaced by foreign-key indexes in V418 or were already
--      dropped.
--   2. Twenty-four single-column indexes on a boolean or on deleted_at that nothing scanned. A
--      boolean such as enabled or published is true for most live rows, so the planner prefers a
--      table scan or a more selective index; the non-partial deleted_at indexes hold one entry per
--      row for a column that is filtered only as deleted_at IS NULL. Measured: after
--      pg_stat_reset() on the DBP-1.1 scale database, the plan check plus the REST database test
--      suites (1,534 tests, run against that database, so the planner saw its 1M classes, 105k
--      versions and 20k projects) made 46M index scans over 206 indexes and none on any of these. The one index of
--      this kind that was scanned, idx_tenants_deleted_at (the document-store tenant purge sweep,
--      Database.list_purgeable_tenants), stays.
--   3. idx_consumer_contract_pointers, a GIN index on consumer_contract.surface_pointers. Nothing
--      queries the column with && or @>: the blast-radius match (apiome-rest
--      app/blast_radius.py) is a JSON-pointer prefix comparison done after reading a project's
--      contracts by consumer and project, which the b-tree indexes serve. A GIN index is also the
--      most expensive kind to maintain on each insert.
--
-- Only non-unique indexes are dropped, so no constraint and no ON CONFLICT target changes. Each
-- DROP takes a brief exclusive lock on its table and does not depend on its size.
--
-- Rollback notes: recreate a dropped index from the migration named in its comment.

-- ---------------------------------------------------------------------------------------------
-- 1. Leading prefix of another index with the same predicate
-- ---------------------------------------------------------------------------------------------

DROP INDEX IF EXISTS apiome.idx_projects_tenant_id;  -- V002; prefix of idx_projects_tenant_publishable (deleted_at IS NULL)
DROP INDEX IF EXISTS apiome.idx_properties_project_id;  -- V004; prefix of idx_properties_project_enabled (deleted_at IS NULL)
DROP INDEX IF EXISTS apiome.mcp_endpoint_sources_endpoint_idx;  -- V172; prefix of mcp_endpoint_sources_live_unique (retired_at IS NULL)
DROP INDEX IF EXISTS apiome.sso_provider_domain_provider_idx;  -- V312; prefix of sso_provider_domain_provider_domain_key
DROP INDEX IF EXISTS apiome.idx_operational_components_tenant;  -- V366; prefix of uq_operational_components_live_name (deleted_at IS NULL)

-- ---------------------------------------------------------------------------------------------
-- 2. Unscanned single-column indexes on a boolean or deleted_at
-- ---------------------------------------------------------------------------------------------

DROP INDEX IF EXISTS apiome.idx_api_keys_deleted_at;
DROP INDEX IF EXISTS apiome.idx_api_keys_enabled;
DROP INDEX IF EXISTS apiome.idx_canvas_layouts_is_default;
DROP INDEX IF EXISTS apiome.idx_class_templates_is_public;
DROP INDEX IF EXISTS apiome.idx_class_templates_is_system;
DROP INDEX IF EXISTS apiome.idx_classes_deleted_at;
DROP INDEX IF EXISTS apiome.idx_classes_enabled;
DROP INDEX IF EXISTS apiome.idx_feature_flags_enabled;
DROP INDEX IF EXISTS apiome.idx_feature_flags_is_preview;
DROP INDEX IF EXISTS apiome.idx_licenses_enabled;
DROP INDEX IF EXISTS apiome.idx_projects_deleted_at;
DROP INDEX IF EXISTS apiome.idx_projects_enabled;
DROP INDEX IF EXISTS apiome.idx_properties_deleted_at;
DROP INDEX IF EXISTS apiome.idx_properties_enabled;
DROP INDEX IF EXISTS apiome.idx_property_templates_is_public;
DROP INDEX IF EXISTS apiome.idx_property_templates_is_system;
DROP INDEX IF EXISTS apiome.idx_tenants_enabled;
DROP INDEX IF EXISTS apiome.idx_users_deleted_at;
DROP INDEX IF EXISTS apiome.idx_users_enabled;
DROP INDEX IF EXISTS apiome.idx_users_verified;
DROP INDEX IF EXISTS apiome.idx_version_preservation_deleted_at;
DROP INDEX IF EXISTS apiome.idx_versions_deleted_at;
DROP INDEX IF EXISTS apiome.idx_versions_enabled;
DROP INDEX IF EXISTS apiome.idx_versions_published;

-- ---------------------------------------------------------------------------------------------
-- 3. Unused GIN index
-- ---------------------------------------------------------------------------------------------

DROP INDEX IF EXISTS apiome.idx_consumer_contract_pointers;  -- V251
