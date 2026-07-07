"""Guardrails for the scheduled catalog digest config migration (MCAT-19.5, #4654).

DB-free: asserts the migration SQL creates the per-tenant ``mcp_catalog_digest_configs`` table with
the opt-in default, cadence CHECK, tenant FK cascade and the due-selection index the sweep depends on.
"""

from pathlib import Path

import pytest

_MIGRATION = "V145__mcp_catalog_digest_configs_4654.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS apiome.mcp_catalog_digest_configs",
    # One row per tenant, cascade with the tenant.
    "tenant_id        UUID PRIMARY KEY REFERENCES apiome.tenants(id) ON DELETE CASCADE",
    # Opt-in: disabled by default (an acceptance criterion).
    "enabled          BOOLEAN NOT NULL DEFAULT false",
    # NULL cadence = global default; positive-only when set.
    "cadence_seconds  INTEGER",
    "CHECK (cadence_seconds IS NULL OR cadence_seconds > 0)",
    # Empty-window policy defaults to silent.
    "send_empty       BOOLEAN NOT NULL DEFAULT false",
    "last_digest_at   TIMESTAMP WITH TIME ZONE",
    # Partial index over enabled rows backs the sweep's due-selection scan.
    "CREATE INDEX IF NOT EXISTS idx_mcp_catalog_digest_due",
    "WHERE enabled = true",
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
    """The migration only adds a table/index — no destructive data statements."""
    # Consider only executable statements, not the rollback note in the leading comment block.
    statements = "\n".join(
        line for line in migration_text.splitlines() if not line.strip().startswith("--")
    ).upper()
    assert "DELETE FROM" not in statements
    assert "TRUNCATE" not in statements
    assert "DROP TABLE" not in statements  # rollback DROP lives only in the comment
