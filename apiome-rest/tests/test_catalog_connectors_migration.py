"""Guardrails for the catalog connector migration (CDG-1.1, #5952)."""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V281__catalog_connectors_cdg_1_1.sql"

_REQUIRED_FRAGMENTS = (
    # The registry, with the issue's kind / status vocabulary and the RAR-4.5 conflict policies.
    "CREATE TABLE IF NOT EXISTS apiome.catalog_connectors",
    "'kong-konnect',",
    "'mcp-registry'",
    "CHECK (status IN ('active', 'paused', 'failing'))",
    "CHECK (conflict_policy IN ('overwrite', 'hold-for-review', 'new-branch'))",
    "refresh_interval_seconds INTEGER",
    "deleted_at               TIMESTAMPTZ",
    "uq_catalog_connectors_tenant_name_live",
    # The inventory: never deleted by a sync, items keep their catalog item on SET NULL.
    "CREATE TABLE IF NOT EXISTS apiome.catalog_connector_items",
    "CHECK (status IN ('discovered', 'imported', 'ignored', 'missing'))",
    "project_id        UUID REFERENCES apiome.projects(id) ON DELETE SET NULL",
    "hosts             TEXT[] NOT NULL DEFAULT '{}'",
    "CONSTRAINT uq_catalog_connector_items_remote UNIQUE (connector_id, remote_id)",
    # Credentials: ciphertext only.
    "CREATE TABLE IF NOT EXISTS apiome.catalog_connector_credentials",
    "encrypted_payload BYTEA NOT NULL",
    # Connector runs on the shared refresh ledger.
    "ALTER COLUMN repository_id DROP NOT NULL",
    "ADD COLUMN IF NOT EXISTS refresh_source VARCHAR(16) NOT NULL DEFAULT 'git'",
    "ADD COLUMN IF NOT EXISTS connector_id UUID REFERENCES apiome.catalog_connectors(id)",
    "ADD COLUMN IF NOT EXISTS pull_count INTEGER NOT NULL DEFAULT 0",
    "ADD COLUMN IF NOT EXISTS error_class VARCHAR(64)",
    "ADD COLUMN IF NOT EXISTS http_status SMALLINT",
    "ck_tenant_repo_refresh_jobs_source_shape",
    "uq_tenant_repo_refresh_jobs_active_connector",
)


def test_migration_creates_the_connector_registry(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_connector_single_flight_is_a_partial_unique_index(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_repo_refresh_jobs_active_connector" in text
    assert "WHERE refresh_source = 'connector' AND status IN ('queued', 'running')" in text


def test_kind_check_matches_the_app_vocabulary(repo_root: Path) -> None:
    from app.catalog_connectors import KINDS

    text = (repo_root / _MIGRATION).read_text()
    for kind in KINDS:
        assert f"'{kind}'" in text
