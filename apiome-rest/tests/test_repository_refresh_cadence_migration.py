"""Guardrails for the refresh cadence migration (RAR-3.1, #3522)."""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V107__configurable_refresh_cadence_rar_3_1_352.sql"

# Fragments the migration must contain so the cadence columns + constraint survive
# accidental edits. Acceptance criteria for #3522:
#   - per-repo `refresh_interval_seconds` (default 300 -> ~5-minute refresh)
#   - `last_refreshed_at` column for the sweep's due-selection anchor
#   - a positive-value CHECK (the configurable floor is applied in the app)
_REQUIRED_FRAGMENTS = (
    "ALTER TABLE apiome.tenant_repositories",
    "ADD COLUMN IF NOT EXISTS refresh_interval_seconds INTEGER NOT NULL DEFAULT 300",
    "ADD COLUMN IF NOT EXISTS last_refreshed_at TIMESTAMPTZ",
    "ck_tenant_repositories_refresh_interval_positive",
    "CHECK (refresh_interval_seconds > 0)",
)


def test_migration_adds_cadence_columns(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_default_is_five_minutes(repo_root: Path) -> None:
    """The default cadence must remain 300s so v1 behaves as a ~5-minute refresh."""
    text = (repo_root / _MIGRATION).read_text()
    assert "DEFAULT 300" in text
