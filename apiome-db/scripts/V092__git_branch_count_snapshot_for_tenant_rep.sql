-- Git branch count snapshot for tenant repositories (GitHub at registration for now).
SET search_path TO apiome, public;

ALTER TABLE apiome.tenant_repositories
  ADD COLUMN IF NOT EXISTS branch_count INTEGER;

COMMENT ON COLUMN apiome.tenant_repositories.branch_count IS
  'Branch count from the provider API (GitHub list-branches); populated at registration when available.';
