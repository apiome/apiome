"""Guardrails for the gateway configs migration — CDG-5.3 (#5981).

The REST code relies on these names: the table and its per-(connector, environment) uniqueness, the
empty-string environment, and `gateway_config` as a graph node kind and an owner kind.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V298__gateway_configs_cdg_5_3.sql"

_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS catalog_gateway_configs (",
    "connector_id UUID NOT NULL REFERENCES catalog_connectors(id) ON DELETE CASCADE",
    "environment TEXT NOT NULL DEFAULT ''",
    "ON catalog_gateway_configs (tenant_id, connector_id, environment)\n    WHERE deleted_at IS NULL",
    "posture JSONB NOT NULL DEFAULT '{}'::jsonb",
    "declared_losses JSONB NOT NULL DEFAULT '[]'::jsonb",
    "'repository', 'mcp_source', 'identity_group', 'gateway_config')",
    "'agent', 'model',\n                               'gateway_config'));",
)


def test_migration_declares_the_gateway_config_rules(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [fragment for fragment in _FRAGMENTS if fragment not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
