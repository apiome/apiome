"""Guardrails for the saved catalog searches migration (MCAT-21.3, #4662).

DB-free: asserts the migration SQL creates the per-user ``mcp_saved_searches`` table with the
expected columns, uniqueness constraint, and indexes.
"""

from pathlib import Path

import pytest

_MIGRATION = "V150__mcp_saved_searches_4662.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS apiome.mcp_saved_searches",
    "tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE",
    "user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE",
    "name TEXT NOT NULL",
    "filters JSONB NOT NULL DEFAULT '{}'::jsonb",
    "query TEXT NOT NULL DEFAULT ''",
    "sort TEXT NOT NULL DEFAULT 'grade'",
    "is_pinned BOOLEAN NOT NULL DEFAULT false",
    "CONSTRAINT mcp_saved_searches_name_unique UNIQUE (tenant_id, user_id, name)",
    "CONSTRAINT mcp_saved_searches_name_nonempty CHECK (char_length(trim(name)) > 0)",
    "CREATE INDEX IF NOT EXISTS idx_mcp_saved_searches_tenant_user",
    "CREATE INDEX IF NOT EXISTS idx_mcp_saved_searches_pinned",
    "WHERE is_pinned = true",
)


@pytest.fixture
def migration_text(repo_root: Path) -> str:
    path = repo_root / "apiome-db" / "scripts" / _MIGRATION
    assert path.exists(), f"Migration {_MIGRATION} not found at {path}"
    return path.read_text()


def test_migration_present_and_complete(migration_text: str) -> None:
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in migration_text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_is_additive_only(migration_text: str) -> None:
    statements = "\n".join(
        line for line in migration_text.splitlines() if not line.strip().startswith("--")
    ).upper()
    assert "DELETE FROM" not in statements
    assert "TRUNCATE" not in statements
    assert "DROP TABLE" not in statements
