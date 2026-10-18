"""Guardrails for the teams migration — CDG-2.1 (#5960).

V284 is where the ticket's rules stop being habits and become things the database keeps. Each
fragment below pins one, so a later edit that relaxes it fails here:

* a slug is shaped and unique among a tenant's *live* teams (deletes are soft);
* a team member must be a tenant member (BEFORE trigger on ``team_members``);
* a user who leaves the tenant leaves every team in the same transaction (AFTER DELETE trigger on
  ``tenant_users``).

The RBAC half is checked the way earlier resource additions were: ``teams`` in ``all_resources``,
view-only in the Editor grid, every earlier resource carried forward, and every tenant reseeded.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V284__teams_cdg_2_1.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS teams (",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "teams_slug_shape_check",
    "contact_email VARCHAR(320)",
    "chat_url TEXT",
    "oncall_url TEXT",
    "docs_url TEXT",
    "created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "deleted_at TIMESTAMP WITH TIME ZONE",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_tenant_slug",
    "WHERE deleted_at IS NULL",
    "CREATE TABLE IF NOT EXISTS team_members (",
    "team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE",
    "CHECK (role IN ('lead', 'member'))",
    "CONSTRAINT team_members_pkey PRIMARY KEY (team_id, user_id)",
    # Members must be tenant members.
    "CREATE TRIGGER trg_team_members_require_tenant_member",
    "BEFORE INSERT OR UPDATE OF team_id, user_id ON team_members",
    "JOIN apiome.tenant_users tu ON tu.tenant_id = t.tenant_id AND tu.user_id = NEW.user_id",
    # Leaving the tenant leaves every team.
    "CREATE TRIGGER trg_tenant_users_leave_teams",
    "AFTER DELETE ON tenant_users",
    "AND t.tenant_id = OLD.tenant_id",
)

_RBAC_FRAGMENTS = (
    "CREATE OR REPLACE FUNCTION apiome.seed_builtin_roles(p_tenant UUID)",
    "'verification_evidence','consumer_contracts','teams']",
    "unnest(ARRAY['types','members','billing','verification_targets','teams']) AS res",
    "SELECT v_editor, 'consumer_contracts', a FROM unnest(ARRAY['view','create','edit']) AS a",
    "FOR t IN SELECT id FROM apiome.tenants LOOP",
    "PERFORM apiome.seed_builtin_roles(t.id)",
)


def _text(repo_root: Path) -> str:
    return (repo_root / _MIGRATION).read_text()


def test_migration_declares_the_team_rules(repo_root: Path) -> None:
    text = _text(repo_root)
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_adds_the_rbac_resource_and_reseeds_every_tenant(repo_root: Path) -> None:
    text = _text(repo_root)
    missing = [fragment for fragment in _RBAC_FRAGMENTS if fragment not in text]
    assert not missing, f"Migration missing expected RBAC fragments: {missing}"


def test_editor_cannot_change_teams(repo_root: Path) -> None:
    """Membership decides who is paged for an entity's findings, so Editor only reads teams."""
    text = _text(repo_root)
    assert "v_editor, 'teams', a" not in text


def test_migration_keeps_the_previous_resources(repo_root: Path) -> None:
    text = _text(repo_root)
    for resource in (
        "projects",
        "versions",
        "classes",
        "properties",
        "paths",
        "types",
        "imports",
        "members",
        "api_keys",
        "billing",
        "lint_findings",
        "verification_targets",
        "verification_evidence",
        "consumer_contracts",
    ):
        assert f"'{resource}'" in text, f"seed_builtin_roles dropped resource {resource}"


def test_the_rest_guard_and_the_migration_agree_on_the_vocabulary() -> None:
    from app.permissions import RESOURCES, Resource

    assert Resource.TEAMS == "teams"
    assert Resource.TEAMS in RESOURCES
