-- Job and run ledger indexes (DBP-1.11, #7194).
--
-- Measured on the scale database with the side tables filled (400k provider_check_runs, 400k
-- mcp_discovery_jobs, 600k tenant_repository_refresh_jobs, 300k export_run_ledger rows):
--
--   * idx_provider_check_runs_project_created — Database.list_provider_check_runs with a project
--     filter (WHERE tenant_id AND project_id ORDER BY created_at DESC, id DESC LIMIT/OFFSET). It
--     replaces idx_provider_check_runs_project_id_fk (project_id), a leading prefix of it that
--     still serves the cascade from projects, so the write cost does not change.
--   * idx_mcp_discovery_jobs_endpoint_active — Database.create_mcp_discovery_job's dedupe probe
--     (WHERE endpoint_id AND state IN ('queued','running') ORDER BY created_at LIMIT 1). The
--     existing (endpoint_id, created_at DESC) index walks the endpoint's whole job history from
--     the oldest finished job; the partial index holds only the active ones (7 -> 3 buffers with
--     100 jobs per endpoint; the gap grows with history). Only queued and running rows are in it.
--   * idx_tenant_repo_refresh_jobs_created — the repository polling quota
--     (count_repository_refresh_jobs_by_tenant: WHERE created_at >= now() - window GROUP BY
--     tenant_id). No index started with created_at, so every sweep read the whole table:
--     10.3 ms / 10,986 buffers -> 0.004 ms / 3 (index-only scan of the window).
--   * idx_tenant_repo_refresh_jobs_lineage_finished — apiome-ui repository-import-metrics' two
--     "last refresh" LATERALs per import spec (WHERE repository_id AND branch AND path AND
--     finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1). 20 specs of one repository:
--     2.2 ms / 12,120 buffers -> 0.09 ms / 161.
--   * idx_export_run_ledger_tenant_actor_finished — Database.list_export_run_actors (the Export
--     history actor filter: WHERE tenant_id AND actor_id IS NOT NULL GROUP BY actor_id,
--     actor_label ORDER BY max(finished_at)). Parallel sequential scan before (9.8 ms / 4,874
--     buffers); index-only scan after (7.2 ms / 832 buffers).
--
-- Large databases: a migration runs in one transaction, so these are plain CREATE INDEX
-- statements and each blocks writes to its table while it builds. To avoid that, build the
-- CREATE INDEX statements first by hand with CREATE INDEX CONCURRENTLY (same names and
-- definitions); every statement is IF [NOT] EXISTS, so the migration then only drops the replaced
-- index.
--
-- Rollback notes:
--   CREATE INDEX idx_provider_check_runs_project_id_fk ON apiome.provider_check_runs (project_id);
--   DROP INDEX IF EXISTS apiome.idx_provider_check_runs_project_created;
--   DROP INDEX IF EXISTS apiome.idx_mcp_discovery_jobs_endpoint_active;
--   DROP INDEX IF EXISTS apiome.idx_tenant_repo_refresh_jobs_created;
--   DROP INDEX IF EXISTS apiome.idx_tenant_repo_refresh_jobs_lineage_finished;
--   DROP INDEX IF EXISTS apiome.idx_export_run_ledger_tenant_actor_finished;

CREATE INDEX IF NOT EXISTS idx_provider_check_runs_project_created
    ON apiome.provider_check_runs (project_id, created_at DESC, id DESC);
DROP INDEX IF EXISTS apiome.idx_provider_check_runs_project_id_fk;  -- leading prefix of idx_provider_check_runs_project_created

CREATE INDEX IF NOT EXISTS idx_mcp_discovery_jobs_endpoint_active
    ON apiome.mcp_discovery_jobs (endpoint_id, created_at)
    WHERE state IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_tenant_repo_refresh_jobs_created
    ON apiome.tenant_repository_refresh_jobs (created_at)
    INCLUDE (tenant_id, refresh_source, pull_count);

CREATE INDEX IF NOT EXISTS idx_tenant_repo_refresh_jobs_lineage_finished
    ON apiome.tenant_repository_refresh_jobs (repository_id, branch, path, finished_at DESC)
    WHERE finished_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_export_run_ledger_tenant_actor_finished
    ON apiome.export_run_ledger (tenant_id, actor_id, finished_at DESC)
    INCLUDE (actor_label)
    WHERE actor_id IS NOT NULL;
