-- REPO-10.3 / #2949: target table for tenant-level scan corpus roll-up (mirrors the
-- in-process cache in objectified-rest today; can be backfilled/REFRESHed when
-- materialized scan reports are stored in PostgreSQL end-to-end).
SET search_path TO odb, public;

CREATE TABLE IF NOT EXISTS odb.repository_corpus_stats_rollup (
  tenant_id UUID NOT NULL PRIMARY KEY REFERENCES odb.tenants(id) ON DELETE CASCADE,
  repositories_tracked INTEGER NOT NULL,
  importable_specs INTEGER NOT NULL,
  awaiting_selection_count INTEGER NOT NULL,
  parse_error_count INTEGER NOT NULL,
  manifest_error_count INTEGER NOT NULL,
  refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE odb.repository_corpus_stats_rollup IS
  'Tenant roll-up of latest per-repo scan report totals; refreshed when scan materialization completes (#2949).';
