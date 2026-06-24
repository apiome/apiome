"""Guardrails for the repository_import_spec table migration (RAR-1.1, #3512)."""

from pathlib import Path

_MIGRATION = "objectified-db/scripts/V105__persisted_import_specification_per_impor.sql"

# Fragments the migration must contain so the table, keys, and indexes survive
# accidental edits. Acceptance criteria for #3512:
#   - table + migration with UNIQUE (repository_id, branch, path)
#   - index on (tenant_id, repository_id) for refresh-sweep joins
#   - options_json JSONB column carrying the full SpecImportOptions payload
_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS odb.repository_import_spec",
    "tenant_id UUID NOT NULL REFERENCES odb.tenants(id) ON DELETE CASCADE",
    "repository_id UUID NOT NULL REFERENCES odb.tenant_repositories(id) ON DELETE CASCADE",
    "project_id UUID NOT NULL REFERENCES odb.projects(id) ON DELETE CASCADE",
    "created_by UUID REFERENCES odb.users(id) ON DELETE SET NULL",
    "options_json JSONB NOT NULL",
    "spec_schema_version SMALLINT NOT NULL DEFAULT 1",
    "UNIQUE (repository_id, branch, path)",
    "idx_repository_import_spec_tenant_repo",
    "ON odb.repository_import_spec (tenant_id, repository_id)",
)


def test_migration_creates_repository_import_spec_table(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_unique_constraint_is_named(repo_root: Path) -> None:
    """DAO upserts target the constraint by name, so it must stay named."""
    text = (repo_root / _MIGRATION).read_text()
    assert "uq_repository_import_spec_repo_branch_path" in text
