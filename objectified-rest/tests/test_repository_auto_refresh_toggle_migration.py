"""Guardrails for the auto-refresh enable/disable migration (RAR-3.3, #3524)."""

from pathlib import Path

_MIGRATION = "objectified-db/scripts/20260622-120000.sql"

# Fragments the migration must keep so the per-repo toggle survives accidental
# edits. Acceptance criteria for #3524: a per-repo `auto_refresh_enabled` flag,
# default TRUE so existing repositories keep auto-refreshing.
_REQUIRED_FRAGMENTS = (
    "ALTER TABLE odb.tenant_repositories",
    "ADD COLUMN IF NOT EXISTS auto_refresh_enabled BOOLEAN NOT NULL DEFAULT TRUE",
)


def test_migration_adds_auto_refresh_column(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_default_is_enabled(repo_root: Path) -> None:
    """The default must remain TRUE so existing repos keep auto-refreshing."""
    text = (repo_root / _MIGRATION).read_text()
    assert "DEFAULT TRUE" in text
