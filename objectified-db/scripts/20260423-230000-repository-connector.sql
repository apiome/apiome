-- REPO-1.1 / #2753: Repository data model tables for repository connector MVP.
SET search_path TO odb, public;

DO $$
BEGIN
  CREATE TYPE odb.repository_provider AS ENUM ('github');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
  CREATE TYPE odb.repository_visibility AS ENUM ('public', 'private', 'internal');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
  CREATE TYPE odb.repository_status AS ENUM ('active', 'paused', 'archived', 'error');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

CREATE TABLE IF NOT EXISTS odb.repository (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL REFERENCES odb.tenants(id) ON DELETE CASCADE,
  project_id UUID REFERENCES odb.projects(id) ON DELETE SET NULL,
  provider odb.repository_provider NOT NULL DEFAULT 'github',
  provider_repo_id VARCHAR(255) NOT NULL,
  owner VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  default_branch VARCHAR(255) NOT NULL,
  visibility odb.repository_visibility NOT NULL DEFAULT 'private',
  html_url TEXT,
  clone_url TEXT,
  description TEXT,
  status odb.repository_status NOT NULL DEFAULT 'active',
  last_scan_id UUID,
  last_scan_at TIMESTAMPTZ,
  created_by UUID REFERENCES odb.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  archived_at TIMESTAMPTZ,
  CONSTRAINT uq_repository_tenant_provider_repo UNIQUE (tenant_id, provider, provider_repo_id)
);

CREATE INDEX IF NOT EXISTS idx_repository_tenant_id
  ON odb.repository (tenant_id);

CREATE INDEX IF NOT EXISTS idx_repository_project_id
  ON odb.repository (project_id);

CREATE INDEX IF NOT EXISTS idx_repository_status
  ON odb.repository (status);

CREATE INDEX IF NOT EXISTS idx_repository_provider_owner_name
  ON odb.repository (provider, owner, name);

COMMENT ON TABLE odb.repository IS
  'Registered upstream repositories for import and scan workflows (#2753).';

COMMENT ON COLUMN odb.repository.last_scan_id IS
  'Nullable repository_scan id; FK added when repository_scan table is available.';

DO $$
BEGIN
  IF to_regclass('odb.repository_scan') IS NOT NULL
     AND NOT EXISTS (
       SELECT 1
       FROM pg_constraint
       WHERE conname = 'fk_repository_last_scan_id'
     )
  THEN
    ALTER TABLE odb.repository
      ADD CONSTRAINT fk_repository_last_scan_id
      FOREIGN KEY (last_scan_id) REFERENCES odb.repository_scan(id) ON DELETE SET NULL;
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS odb.repository_branch (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  repository_id UUID NOT NULL REFERENCES odb.repository(id) ON DELETE CASCADE,
  branch VARCHAR(255) NOT NULL,
  subpath_glob TEXT NOT NULL DEFAULT '**/*',
  is_tracked BOOLEAN NOT NULL DEFAULT TRUE,
  last_known_sha VARCHAR(64),
  last_polled_at TIMESTAMPTZ,
  poll_interval_sec INTEGER NOT NULL DEFAULT 86400 CHECK (poll_interval_sec > 0),
  next_poll_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_repository_branch_repository_branch UNIQUE (repository_id, branch)
);

CREATE INDEX IF NOT EXISTS idx_repository_branch_repository_id
  ON odb.repository_branch (repository_id);

CREATE INDEX IF NOT EXISTS idx_repository_branch_next_poll_at
  ON odb.repository_branch (next_poll_at)
  WHERE is_tracked = TRUE;

COMMENT ON TABLE odb.repository_branch IS
  'Tracked branch configuration for registered repositories (#2753).';

CREATE TABLE IF NOT EXISTS odb.repository_credential_ref (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  repository_id UUID NOT NULL REFERENCES odb.repository(id) ON DELETE CASCADE,
  linked_account_id UUID NOT NULL REFERENCES odb.external_auth_providers(id) ON DELETE CASCADE,
  scopes TEXT[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_repository_credential_ref_repo_account UNIQUE (repository_id, linked_account_id)
);

CREATE INDEX IF NOT EXISTS idx_repository_credential_ref_repository_id
  ON odb.repository_credential_ref (repository_id);

CREATE INDEX IF NOT EXISTS idx_repository_credential_ref_linked_account_id
  ON odb.repository_credential_ref (linked_account_id);

COMMENT ON TABLE odb.repository_credential_ref IS
  'References OAuth-linked accounts for repository access; never stores token copies (#2753).';
