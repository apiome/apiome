-- Persisted import specification per imported repository file (RAR-1.1, #3512).
--
-- `SpecImportOptions` (naming conventions, prefix/suffix, type mappings, conflict
-- flags, project/version targeting, ...) is accepted and applied at import time but
-- never stored, so a repository auto-refresh re-imports a changed file with importer
-- DEFAULTS instead of the user's original request. This table captures the full
-- import spec plus the source descriptor, keyed to the imported-file lineage
-- (repository_id, branch, path), so the spec can be replayed faithfully.
--
-- The unique key keeps exactly one row per file lineage (the latest spec); the
-- (tenant_id, repository_id) index serves the refresh-sweep joins.
SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS apiome.repository_import_spec (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE,
  repository_id UUID NOT NULL REFERENCES apiome.tenant_repositories(id) ON DELETE CASCADE,
  branch TEXT NOT NULL,
  path TEXT NOT NULL,
  project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE,
  source_kind TEXT NOT NULL,
  format_override TEXT,
  content_type TEXT,
  options_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  spec_schema_version SMALLINT NOT NULL DEFAULT 1,
  created_by UUID REFERENCES apiome.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_repository_import_spec_repo_branch_path UNIQUE (repository_id, branch, path)
);

CREATE INDEX IF NOT EXISTS idx_repository_import_spec_tenant_repo
  ON apiome.repository_import_spec (tenant_id, repository_id);

COMMENT ON TABLE apiome.repository_import_spec IS
  'Latest persisted SpecImportOptions + source descriptor per imported repository file, keyed (repository_id, branch, path); replayed by repository auto-refresh so re-imports honor the original request instead of importer defaults (RAR-1.1).';

COMMENT ON COLUMN apiome.repository_import_spec.options_json IS
  'Full SpecImportOptions payload as submitted at import time; round-trips losslessly.';

COMMENT ON COLUMN apiome.repository_import_spec.spec_schema_version IS
  'Envelope version for the stored spec so it survives future option-shape changes (RAR-1.4).';
