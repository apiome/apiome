"""Guardrails for the mock-instances migration (#3615, RC1-2.2)."""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V123__mock_server_instances_rc1_2_2_3615.sql"

# Fragments the migration must contain so the mock-instance table + its free-tier guardrails survive
# accidental edits. Acceptance criteria for #3615:
#   - a table holding the frozen spec a mock replays from;
#   - per-instance expiry + rate limit columns;
#   - tenant scoping and an expiry index for sweeps.
_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS mock_instances",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "spec JSONB NOT NULL",
    "config JSONB NOT NULL DEFAULT '{}'::jsonb",
    "rate_limit_per_minute INTEGER NOT NULL DEFAULT 60",
    "expires_at TIMESTAMP WITH TIME ZONE",
    "CHECK (status IN ('active', 'expired'))",
    "CHECK (rate_limit_per_minute > 0)",
    "idx_mock_instances_tenant_created_at",
    "idx_mock_instances_expires_at",
)


def test_migration_creates_mock_instances_table(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_sets_odb_search_path(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    assert "SET search_path TO apiome, public;" in text
