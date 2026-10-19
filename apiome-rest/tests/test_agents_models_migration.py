"""Guardrails for the agent and model entities migration — CDG-5.2 (#5980).

The REST code relies on these names: the four tables, the one-agent-per-key and
one-consumer-per-agent-per-project rules, the ``agent`` contract source, and the ``agent`` /
``model`` owner kinds.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V297__agents_and_models_cdg_5_2.sql"

_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS catalog_models (",
    "CHECK (hosting IN ('api', 'self_hosted'))",
    "deprecated_at TIMESTAMP WITH TIME ZONE",
    "CREATE TABLE IF NOT EXISTS catalog_agents (",
    "model_id UUID REFERENCES catalog_models(id) ON DELETE SET NULL",
    "CHECK (status IN ('active', 'retired'))",
    "CREATE TABLE IF NOT EXISTS catalog_agent_keys (",
    "api_key_id UUID NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE",
    "CONSTRAINT catalog_agent_keys_one_agent_per_key UNIQUE (api_key_id)",
    "CREATE TABLE IF NOT EXISTS catalog_agent_consumers (",
    "PRIMARY KEY (agent_id, project_id)",
    "CHECK (source IN ('pact', 'manual', 'agent'))",
    "CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector', 'agent', 'model'))",
)


def test_migration_declares_the_agent_and_model_rules(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [fragment for fragment in _FRAGMENTS if fragment not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
