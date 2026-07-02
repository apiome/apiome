"""Guardrails for MCP access audit table migration (#3013)."""

from pathlib import Path

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS mcp_access_audit",
    "key_id",
    "tool",
    "spec_id",
    "success",
    "error",
    "idx_mcp_access_audit_key_at",
    "idx_mcp_access_audit_spec_at",
    "REFERENCES apiome.mcp_api_keys(id)",
    "REFERENCES apiome.versions(id)",
)


def test_migration_creates_mcp_access_audit_table(repo_root: Path) -> None:
    migration = repo_root / "apiome-db" / "scripts" / "V096__mcp_private_access_audit_trail_3013.sql"
    text = migration.read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
