-- Audit ledger indexes for the project timeline, refresh history and keyset search (DBP-1.11, #7194).
--
-- Measured on the scale database (700k workflow_audit rows, 200k version_protection_audit,
-- 200k registry_audit, 200k access_audit):
--
--   * idx_workflow_audit_project_created, idx_version_protection_audit_project_created —
--     apiome-rest Database.list_project_timeline, the UNION ALL of both ledgers WHERE tenant_id
--     AND project_id ORDER BY created_at DESC, id DESC LIMIT n. Neither ledger had an index that
--     starts with the project, so each branch read the whole tenant: 8.2 ms and 15,609 buffers
--     before, 0.02 ms and 41 buffers after (a merge of two ordered index scans that stops at n).
--   * idx_workflow_audit_refresh_repository — Database.search_repository_refresh_audit and
--     count_repository_refresh_audit with a repository filter (action =
--     'repository.refresh.cycle' AND detail->>'repositoryId' = $2). Partial on the refresh
--     action, keyed on the JSON key the filter compares: page 7.2 ms / 4,305 buffers -> 0.01 ms /
--     54; count 13.7 ms / 15,596 buffers -> 0.02 ms / 104.
--   * workflow_audit, registry_audit, access_audit (tenant_id, created_at DESC) become
--     (tenant_id, created_at DESC, id DESC): the keyset searches (search_workflow_audit,
--     search_registry_audit, list_access_audit and the access-audit chain head) order by
--     created_at DESC, id DESC, which the old index answered only with a sort on top. Each new
--     index replaces the old one, which is a leading prefix of it, so the write cost does not
--     change. The tenant-less access-audit chain head (WHERE tenant_id IS NULL) uses the same
--     index, so it needs no separate partial index.
--
-- Large databases: a migration runs in one transaction, so these are plain CREATE INDEX
-- statements and each blocks writes to its table while it builds. To avoid that, build the
-- CREATE INDEX statements first by hand with CREATE INDEX CONCURRENTLY (same names and
-- definitions); every statement is IF [NOT] EXISTS, so the migration then only drops the
-- replaced indexes.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_workflow_audit_project_created;
--   DROP INDEX IF EXISTS apiome.idx_version_protection_audit_project_created;
--   DROP INDEX IF EXISTS apiome.idx_workflow_audit_refresh_repository;
--   CREATE INDEX idx_workflow_audit_tenant_created_at ON apiome.workflow_audit (tenant_id, created_at DESC);
--   CREATE INDEX idx_registry_audit_tenant_created_at ON apiome.registry_audit (tenant_id, created_at DESC);
--   CREATE INDEX idx_access_audit_tenant_created_at ON apiome.access_audit (tenant_id, created_at DESC);
--   then DROP the three *_tenant_created_id indexes below.

CREATE INDEX IF NOT EXISTS idx_workflow_audit_project_created
    ON apiome.workflow_audit (tenant_id, project_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_version_protection_audit_project_created
    ON apiome.version_protection_audit (tenant_id, project_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_workflow_audit_refresh_repository
    ON apiome.workflow_audit (tenant_id, (detail ->> 'repositoryId'), created_at DESC, id DESC)
    WHERE action = 'repository.refresh.cycle';

CREATE INDEX IF NOT EXISTS idx_workflow_audit_tenant_created_id
    ON apiome.workflow_audit (tenant_id, created_at DESC, id DESC);
DROP INDEX IF EXISTS apiome.idx_workflow_audit_tenant_created_at;  -- leading prefix of idx_workflow_audit_tenant_created_id

CREATE INDEX IF NOT EXISTS idx_registry_audit_tenant_created_id
    ON apiome.registry_audit (tenant_id, created_at DESC, id DESC);
DROP INDEX IF EXISTS apiome.idx_registry_audit_tenant_created_at;  -- leading prefix of idx_registry_audit_tenant_created_id

CREATE INDEX IF NOT EXISTS idx_access_audit_tenant_created_id
    ON apiome.access_audit (tenant_id, created_at DESC, id DESC);
DROP INDEX IF EXISTS apiome.idx_access_audit_tenant_created_at;  -- leading prefix of idx_access_audit_tenant_created_id
