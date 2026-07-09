"""Guardrails for the mock usage migration (#4420, SIM-1.5)."""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V154__mock_usage_rate_limits_4420.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS mock_usage",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "usage_date DATE NOT NULL",
    "request_count BIGINT NOT NULL DEFAULT 0",
    "idx_mock_usage_tenant_date",
    "mock_rps",
    "mock_requests_per_month",
    "CREATE OR REPLACE FUNCTION apiome.record_mock_usage",
)


def test_migration_creates_mock_usage_table(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_sets_odb_search_path(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    assert "SET search_path TO apiome, public;" in text
