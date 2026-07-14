"""Guardrails for MCP capability denials migration (#4773, MTG-2.4)."""

from pathlib import Path

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS mcp_capability_denials",
    "key_id",
    "tenant_id",
    "tool_id",
    "transport",
    "reason",
    "idx_mcp_capability_denials_tenant_at",
    "idx_mcp_capability_denials_key_at",
    "idx_mcp_capability_denials_tool_at",
    "REFERENCES apiome.mcp_api_keys(id)",
    "REFERENCES apiome.tenants(id)",
    "90 days",
    "Never store tool arguments",
)


def test_migration_creates_mcp_capability_denials_table(repo_root: Path) -> None:
    migration = (
        repo_root / "apiome-db" / "scripts" / "V164__mcp_capability_denials_4773.sql"
    )
    text = migration.read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
    assert "ALTER TABLE" not in text.upper() or "mcp_access_audit" not in text.lower()
