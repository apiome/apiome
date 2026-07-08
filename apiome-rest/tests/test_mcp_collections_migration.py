"""DB-free: asserts the migration SQL creates MCP collection tables (#4667)."""

from pathlib import Path

_MIGRATION = "V152__mcp_collections_4667.sql"
_ROOT = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
_SQL = (_ROOT / _MIGRATION).read_text(encoding="utf-8")
_LOWER = _SQL.lower()


def test_migration_creates_tables():
    assert "CREATE TABLE IF NOT EXISTS mcp_collections" in _SQL
    assert "CREATE TABLE IF NOT EXISTS mcp_collection_members" in _SQL


def test_migration_scopes_to_tenant_and_publish_flag():
    assert "tenant_id uuid not null references tenants(id) on delete cascade" in _LOWER
    assert "is_published boolean not null default false" in _LOWER
    assert "primary key (collection_id, endpoint_id)" in _LOWER
