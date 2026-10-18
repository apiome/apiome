"""Guardrails for the shadow-API report migration (CDG-1.6, #5957)."""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V283__shadow_api_report_cdg_1_6.sql"

_REQUIRED_FRAGMENTS = (
    "ADD COLUMN IF NOT EXISTS ignored_reason",
    "ADD COLUMN IF NOT EXISTS ignored_hosts     TEXT[]",
    "ADD COLUMN IF NOT EXISTS ignored_base_path TEXT",
    "ADD COLUMN IF NOT EXISTS linked_by         UUID",
    "CREATE TABLE IF NOT EXISTS apiome.catalog_connector_notification_throttle",
    "connector_id     UUID NOT NULL REFERENCES apiome.catalog_connectors(id) ON DELETE CASCADE",
    "CHECK (event_type IN ('catalog.connector.shadow_api_detected'))",
    "CONSTRAINT uq_catalog_connector_notification_throttle UNIQUE (connector_id, event_type)",
)


def test_migration_adds_ignore_reasons_links_and_the_throttle(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"V283 is missing: {missing}"


def test_migration_documents_a_rollback(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    assert "-- Rollback:" in text and "DROP TABLE IF EXISTS apiome.catalog_connector_notification_throttle" in text
