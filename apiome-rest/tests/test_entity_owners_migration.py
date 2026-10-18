"""Guardrails for the entity-owners migration — CDG-2.2 (#5961).

V285 keeps the ownership rules in the database: one confirmed owner per entity, suggestions unique
per (entity, team, source) with their source recorded, the five kinds and seven sources, and the
CODEOWNERS triggers that refresh suggestions when a path is linked or its owners change. CDG-2.1's
team delete reads ``team_id`` and ``status = 'confirmed'`` from this table, so those are pinned too.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V285__entity_owners_cdg_2_2.sql"

_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS entity_owners (",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector'))",
    "team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE",
    "CHECK (status IN ('confirmed', 'suggested'))",
    "CHECK (source IN ('manual', 'gateway_tag', 'codeowners', 'spec_extension',",
    "'backstage', 'compass', 'hub'))",
    "source_ref TEXT",
    "confirmed_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "confirmed_at TIMESTAMP WITH TIME ZONE",
    "CHECK ((status = 'confirmed') = (confirmed_at IS NOT NULL))",
    # One confirmed owner; suggestions unique per (entity, team, source).
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_owners_one_confirmed",
    "ON entity_owners (tenant_id, entity_kind, entity_id)\n    WHERE status = 'confirmed'",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_owners_suggestion",
    "ON entity_owners (tenant_id, entity_kind, entity_id, team_id, source)\n    WHERE status = 'suggested'",
    # CODEOWNERS.
    "ADD COLUMN IF NOT EXISTS codeowners TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]",
    "t.slug = lower(substring(ref FROM '^@[^/]+/(.+)$'))",
    "CREATE TRIGGER trg_repository_import_spec_codeowners",
    "AFTER INSERT OR UPDATE OF repository_id, branch, path, project_id ON repository_import_spec",
    "CREATE TRIGGER trg_tenant_repository_files_codeowners",
    "AFTER INSERT OR UPDATE OF codeowners ON tenant_repository_files",
)


def test_migration_declares_the_ownership_rules(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [fragment for fragment in _FRAGMENTS if fragment not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_importers_only_ever_suggest(repo_root: Path) -> None:
    """The CODEOWNERS trigger writes suggestions, never a confirmed owner."""
    text = (repo_root / _MIGRATION).read_text()
    trigger_body = text.split("CREATE OR REPLACE FUNCTION apiome.refresh_codeowner_suggestions", 1)[1]
    trigger_body = trigger_body.split("$$ LANGUAGE plpgsql;", 1)[0]
    assert "'suggested', 'codeowners'" in trigger_body
    assert "'confirmed'" not in trigger_body
