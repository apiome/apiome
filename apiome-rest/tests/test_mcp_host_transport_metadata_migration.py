"""Guardrails for the host & transport metadata migration (MCAT-20.1, #4655).

DB-free: asserts the migration SQL adds the two nullable ``mcp_endpoints`` columns the capture
layer persists to (``transport_metadata`` JSONB + ``transport_metadata_at``) and that it is
purely additive (no destructive statements outside the rollback comment).
"""

from pathlib import Path

import pytest

_MIGRATION = "V146__mcp_host_transport_metadata_4655.sql"

_REQUIRED_FRAGMENTS = (
    "ALTER TABLE mcp_endpoints",
    # Both columns are added idempotently and are nullable (no default) — absent until first discovery.
    "ADD COLUMN IF NOT EXISTS transport_metadata JSONB",
    "ADD COLUMN IF NOT EXISTS transport_metadata_at TIMESTAMP WITH TIME ZONE",
    # Both columns documented.
    "COMMENT ON COLUMN mcp_endpoints.transport_metadata IS",
    "COMMENT ON COLUMN mcp_endpoints.transport_metadata_at IS",
)


@pytest.fixture
def migration_text(repo_root: Path) -> str:
    path = repo_root / "apiome-db" / "scripts" / _MIGRATION
    assert path.exists(), f"Migration {_MIGRATION} not found at {path}"
    return path.read_text()


def test_migration_present_and_complete(migration_text: str) -> None:
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in migration_text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_columns_are_nullable_no_default(migration_text: str) -> None:
    """The columns must be nullable with no default (an endpoint has no facts until discovery)."""
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
