"""Guardrails for MCP API keys table migration (#2997)."""

from pathlib import Path

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS mcp_api_keys",
    "key_hash",
    "prefix",
    "label",
    "tenant_id",
    "scope_json",
    "created_by",
    "created_at",
    "expires_at",
    "revoked_at",
    "last_used_at",
    "idx_mcp_api_keys_prefix",
    "REFERENCES apiome.tenants(id)",
    "chk_mcp_api_keys_expires_after_created",
    "chk_mcp_api_keys_revoked_after_created",
)


def test_migration_creates_mcp_api_keys_table(repo_root: Path) -> None:
    migration = repo_root / "apiome-db" / "scripts" / "V094__mcp_api_keys_hashed_secrets_tenant_bindi.sql"
    text = migration.read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
