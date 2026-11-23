-- Document store maintenance indexes (DBP-1.11, #7194).
--
-- The integrity, purge, store-move and stale-render jobs each walked document_objects or
-- version_documents in an order no index had. Measured on the scale database with 600k
-- document_objects and 600k version_documents rows:
--
--   * idx_document_objects_verify_order — Database.list_document_objects_for_integrity's sample
--     (ORDER BY verified_at NULLS FIRST, created_at, id LIMIT n): 20.5 ms / 19,156 buffers (full
--     scan and top-n sort) -> 0.44 ms / 2,007.
--   * idx_document_objects_unreferenced_since — Database.list_unreferenced_document_objects
--     (WHERE ref_count = 0 AND COALESCE(unreferenced_at, created_at) <= $1 ORDER BY that
--     expression, id). The old partial index was on unreferenced_at alone, which the COALESCE
--     cannot use: 29.0 ms / 17,146 buffers -> 0.09 ms / 282. It replaces
--     idx_document_objects_unreferenced, which nothing else reads.
--   * idx_document_objects_tenant_id_text — the tenant store move (document_store_move
--     _candidates), which pages a tenant's objects by id::text COLLATE "C". A plain
--     (tenant_id, id) index cannot serve that comparison (the plan check showed it unused), so the
--     index is on the expression the query compares: 11.9 ms -> 1.1 ms a page, and each page reads
--     only its own rows instead of sorting the tenant. It replaces idx_document_objects_tenant
--     (tenant_id), which the unique (tenant_id, sha256) key already covers.
--   * idx_version_documents_rendered_created — Database.delete_stale_rendered_documents (rendered
--     roles written at or before a cutoff, oldest first): 11.6 ms / 12,008 buffers -> 0.42 ms /
--     2,442. Partial on the three rendered roles.
--
-- Large databases: a migration runs in one transaction, so these are plain CREATE INDEX
-- statements and each blocks writes to its table while it builds. To avoid that, build the
-- CREATE INDEX statements first by hand with CREATE INDEX CONCURRENTLY (same names and
-- definitions); every statement is IF [NOT] EXISTS, so the migration then only drops the replaced
-- indexes.
--
-- Rollback notes:
--   CREATE INDEX idx_document_objects_unreferenced ON apiome.document_objects (unreferenced_at) WHERE ref_count = 0;
--   CREATE INDEX idx_document_objects_tenant ON apiome.document_objects (tenant_id);
--   DROP INDEX IF EXISTS apiome.idx_document_objects_verify_order;
--   DROP INDEX IF EXISTS apiome.idx_document_objects_unreferenced_since;
--   DROP INDEX IF EXISTS apiome.idx_document_objects_tenant_id_text;
--   DROP INDEX IF EXISTS apiome.idx_version_documents_rendered_created;

CREATE INDEX IF NOT EXISTS idx_document_objects_verify_order
    ON apiome.document_objects (verified_at NULLS FIRST, created_at, id);

CREATE INDEX IF NOT EXISTS idx_document_objects_unreferenced_since
    ON apiome.document_objects ((COALESCE(unreferenced_at, created_at)), id)
    WHERE ref_count = 0;
DROP INDEX IF EXISTS apiome.idx_document_objects_unreferenced;  -- replaced by idx_document_objects_unreferenced_since

CREATE INDEX IF NOT EXISTS idx_document_objects_tenant_id_text
    ON apiome.document_objects (tenant_id, (id::text) COLLATE "C");
DROP INDEX IF EXISTS apiome.idx_document_objects_tenant;  -- leading prefix of document_objects_tenant_sha256_key

CREATE INDEX IF NOT EXISTS idx_version_documents_rendered_created
    ON apiome.version_documents (created_at)
    WHERE role IN ('rendered_openapi', 'rendered_openapi_members', 'rendered_canonical');
