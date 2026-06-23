-- Git branch count snapshot for tenant repositories (GitHub at registration for now).
SET search_path TO odb, public;

ALTER TABLE odb.tenant_repositories
  ADD COLUMN IF NOT EXISTS branch_count INTEGER;

COMMENT ON COLUMN odb.tenant_repositories.branch_count IS
  'Branch count from the provider API (GitHub list-branches); populated at registration when available.';
