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
