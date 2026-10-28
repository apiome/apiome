"""Guardrails for the export_field_identities table migration (MFX-12.2, #3880)."""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V141__export_field_identities_3880.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS apiome.export_field_identities",
    "REFERENCES apiome.tenants(id) ON DELETE CASCADE",
    "REFERENCES apiome.projects(id) ON DELETE CASCADE",
    "target        VARCHAR(64)",
    "field_key     VARCHAR(512)",
    "field_number  INTEGER",
    "uq_export_field_identities_scope",
    "UNIQUE (tenant_id, project_id, target, field_key)",
    "idx_export_field_identities_project_target",
)


def test_migration_creates_export_field_identities_table(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


_CAPNP_MIGRATION = "apiome-db/scripts/V337__export_field_identities_capnp_4179.sql"

_CAPNP_FRAGMENTS = (
    "ALTER COLUMN field_number TYPE BIGINT",
    "DROP CONSTRAINT IF EXISTS export_field_identities_number_check",
    "(target = 'capnproto' AND field_number >= 0)",
    "OR (field_number >= 1 AND field_number <= 536870911)",
)


def test_capnp_migration_widens_the_number_for_capnproto_only(repo_root: Path) -> None:
    """V337 (MFX-30.2, #4179): Cap'n Proto ordinals start at 0 and its file id needs 63 bits."""
    text = (repo_root / _CAPNP_MIGRATION).read_text()
    missing = [frag for frag in _CAPNP_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
