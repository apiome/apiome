"""Guardrails for the MCP date/time version-tag migration (V2-MCP-18.4 / MCAT-4.4, #3671).

DB-free: asserts the migration SQL adds the ``version_tag`` column, back-fills it safely around
the V128 immutability trigger, and enforces per-endpoint uniqueness — the shape MCAT-4.5's history
listings depend on.
"""

from pathlib import Path

import pytest

_MIGRATION = "V131__mcp_catalog_version_datetime_tag_3671.sql"

_REQUIRED_FRAGMENTS = (
    # Column added NULLable first so existing rows can be back-filled before NOT NULL.
    "ADD COLUMN IF NOT EXISTS version_tag TEXT",
    "ALTER COLUMN version_tag SET NOT NULL",
    # Per-endpoint uniqueness is the acceptance-criterion backstop.
    "mcp_endpoint_versions_endpoint_tag_unique UNIQUE (endpoint_id, version_tag)",
    # Backfill must use the same minute-precision UTC format the app emits.
    "'YYYY-MM-DD\"T\"HH24:MI\"Z\"'",
    "AT TIME ZONE 'UTC'",
    "COALESCE(discovered_at, created_at)",
    # Collisions within a minute get a -N suffix, mirroring the runtime disambiguation.
    "ROW_NUMBER() OVER",
    # The V128 immutability trigger must be toggled off for the one-time backfill, then restored.
    "DISABLE TRIGGER trigger_mcp_endpoint_versions_immutable",
    "ENABLE TRIGGER trigger_mcp_endpoint_versions_immutable",
    "COMMENT ON COLUMN mcp_endpoint_versions.version_tag",
)


@pytest.fixture
def migration_text(repo_root: Path) -> str:
    path = repo_root / "apiome-db" / "scripts" / _MIGRATION
    assert path.exists(), f"Migration {_MIGRATION} not found at {path}"
    return path.read_text()


def test_migration_present_and_complete(migration_text: str) -> None:
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in migration_text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_backfill_reenables_trigger_after_disable(migration_text: str) -> None:
    """The immutability trigger must be re-enabled after the backfill, never left disabled."""
    disable_at = migration_text.index("DISABLE TRIGGER trigger_mcp_endpoint_versions_immutable")
    enable_at = migration_text.index("ENABLE TRIGGER trigger_mcp_endpoint_versions_immutable")
    assert disable_at < enable_at, "ENABLE TRIGGER must follow DISABLE TRIGGER"


def test_not_null_set_after_backfill(migration_text: str) -> None:
    """NOT NULL must be enforced only after the backfill has populated existing rows."""
    backfill_at = migration_text.index("ROW_NUMBER() OVER")
    not_null_at = migration_text.index("ALTER COLUMN version_tag SET NOT NULL")
    assert backfill_at < not_null_at, "SET NOT NULL must come after the backfill UPDATE"
