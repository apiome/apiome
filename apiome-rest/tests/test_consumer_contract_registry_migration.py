"""Guardrails for the consumer contract registry migration — CTG-4.1 (#4479).

V251 is where four of the ticket's rules stop being habits and become things the database keeps.
Each fragment below pins one of them, so a later edit that relaxes one fails here rather than in
production six months later:

* contracts are **versioned**, and exactly one revision per consumer is current;
* a contract cannot be attached to a consumer of a different project;
* the CTG-4.2 intersection reads an **indexed pointer array**, not a JSON walk;
* retiring a consumer or deleting a version does not delete a declared surface.

The RBAC half is checked the same way the previous four resource additions were: the new
resource must be in ``all_resources``, in the Editor grid, and every existing tenant must be
reseeded — the three places a partial addition looks green and silently diverges.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V251__consumer_contract_registry_4479.sql"

# The schema rules.
_REQUIRED_FRAGMENTS = (
    # Two tables, tenant- and project-scoped.
    "CREATE TABLE IF NOT EXISTS consumer (",
    "CREATE TABLE IF NOT EXISTS consumer_contract (",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    # A handle is shaped, and unique among a project's live consumers.
    "consumer_slug_shape_check",
    "idx_consumer_project_slug",
    # Contracts are versioned; exactly one revision is current.
    "consumer_contract_revision_check",
    "CONSTRAINT consumer_contract_revision_key UNIQUE (consumer_id, revision)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_consumer_contract_current",
    "WHERE is_current",
    # A contract belongs to a consumer of the same project.
    "CONSTRAINT consumer_contract_consumer_fk",
    "REFERENCES consumer (id, project_id) ON DELETE CASCADE",
    # The CTG-4.2 intersection column and its index.
    "surface_pointers TEXT[] NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_consumer_contract_pointers",
    "USING GIN (surface_pointers)",
    # Unresolved interactions are stored, with a count beside them.
    "unresolved JSONB NOT NULL",
    "unresolved_count INTEGER NOT NULL",
    # A deleted version leaves the contract stale, not deleted.
    "version_id UUID REFERENCES versions(id) ON DELETE SET NULL",
    # Retirement is a stamp, not a delete.
    "deleted_at TIMESTAMP WITH TIME ZONE",
)

# The RBAC rules — the four sync points a partial resource addition silently misses.
_RBAC_FRAGMENTS = (
    "CREATE OR REPLACE FUNCTION apiome.seed_builtin_roles(p_tenant UUID)",
    "'verification_evidence','consumer_contracts']",
    "SELECT v_editor, 'consumer_contracts', a FROM unnest(ARRAY['view','create','edit']) AS a",
    "FOR t IN SELECT id FROM apiome.tenants LOOP",
    "PERFORM apiome.seed_builtin_roles(t.id)",
)


def test_migration_declares_the_registry_rules(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_adds_the_rbac_resource_and_reseeds_every_tenant(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [fragment for fragment in _RBAC_FRAGMENTS if fragment not in text]
    assert not missing, f"Migration missing expected RBAC fragments: {missing}"


def test_editor_cannot_delete_a_consumer(repo_root: Path) -> None:
    """Removing a consumer removes a signal that guards other people's changes, so the Editor
    grid gets view/create/edit and nothing more."""
    text = (repo_root / _MIGRATION).read_text()
    assert (
        "SELECT v_editor, 'consumer_contracts', a FROM unnest(ARRAY['view','create','edit']) AS a"
        in text
    )
    assert "v_editor, 'consumer_contracts', a FROM unnest(ARRAY['view','create','edit','delete']" \
        not in text


def test_migration_keeps_the_previous_resources(repo_root: Path) -> None:
    """The seed function is replaced wholesale, so every earlier resource has to be carried
    forward — dropping one would silently revoke it from every built-in role."""
    text = (repo_root / _MIGRATION).read_text()
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
    ):
        assert f"'{resource}'" in text, f"seed_builtin_roles dropped resource {resource}"


def test_the_rest_guard_and_the_migration_agree_on_the_vocabulary() -> None:
    """The frozenset validates custom-role grids; forgetting it makes the resource ungrantable
    to a custom role while the built-ins work."""
    from app.permissions import RESOURCES, Resource

    assert Resource.CONSUMER_CONTRACTS == "consumer_contracts"
    assert Resource.CONSUMER_CONTRACTS in RESOURCES
