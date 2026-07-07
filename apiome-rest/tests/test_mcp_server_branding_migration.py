"""Guardrails for the server branding migration (MCAT-20.2, #4656).

DB-free: asserts the migration SQL adds the one nullable ``mcp_endpoint_versions`` column the
capture layer persists to (``server_branding`` JSONB) and that it is purely additive (no
destructive statements outside the rollback comment).
"""

from pathlib import Path

import pytest

_MIGRATION = "V147__mcp_server_branding_4656.sql"

_REQUIRED_FRAGMENTS = (
    "ALTER TABLE mcp_endpoint_versions",
    # Added idempotently and nullable (no default) — absent until a snapshot advertises branding.
    "ADD COLUMN IF NOT EXISTS server_branding JSONB",
    # The column is documented.
    "COMMENT ON COLUMN mcp_endpoint_versions.server_branding IS",
)


@pytest.fixture
def migration_text(repo_root: Path) -> str:
    path = repo_root / "apiome-db" / "scripts" / _MIGRATION
    assert path.exists(), f"Migration {_MIGRATION} not found at {path}"
    return path.read_text()


def test_migration_present_and_complete(migration_text: str) -> None:
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in migration_text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_column_is_nullable_no_default(migration_text: str) -> None:
    """The column must be nullable with no default (a snapshot has no branding until discovered)."""
    executable = "\n".join(
        line for line in migration_text.splitlines() if not line.strip().startswith("--")
    ).upper()
    assert "NOT NULL" not in executable
    assert "DEFAULT" not in executable


def test_migration_is_additive_only(migration_text: str) -> None:
    """Only ADD COLUMN — no destructive statements outside the rollback note in the comment."""
    executable = "\n".join(
        line for line in migration_text.splitlines() if not line.strip().startswith("--")
    ).upper()
    assert "DROP COLUMN" not in executable  # rollback DROP lives only in the comment
    assert "DROP TABLE" not in executable
    assert "DELETE FROM" not in executable
    assert "TRUNCATE" not in executable
