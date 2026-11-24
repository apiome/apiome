"""Guardrails for the pacticipant registry migration — PFX-1.1 (#6914).

V432 is where the ticket's rules stop being habits and become things the database keeps. Each
fragment below pins one, so a later edit that relaxes it fails here:

* names are unique per tenant;
* nothing crosses a tenant, and a branch or a tag can only name a version of its own pacticipant;
* deleting a project (hard or soft) clears the binding and keeps the pacticipant;
* versions never mutate;
* a tag and a branch membership exist once.

The RBAC half is checked the way the earlier resource additions were: the resource must be in
``all_resources``, in the Editor grid without delete, and every tenant must be reseeded.
"""

from pathlib import Path

import pytest

_MIGRATION = "apiome-db/scripts/V432__pacticipant_registry_6914.sql"

_REQUIRED_FRAGMENTS = (
    # The migrator runs every script on one connection; this one sets its own path.
    "SET search_path TO apiome, public;",
    # Five tables.
    "CREATE TABLE IF NOT EXISTS pacticipant (",
    "CREATE TABLE IF NOT EXISTS pacticipant_version (",
    "CREATE TABLE IF NOT EXISTS pacticipant_branch (",
    "CREATE TABLE IF NOT EXISTS pacticipant_branch_version (",
    "CREATE TABLE IF NOT EXISTS pacticipant_version_tag (",
    # Names are unique per tenant, and shaped.
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "pacticipant_slug_shape_check",
    "CONSTRAINT pacticipant_tenant_slug_key UNIQUE (tenant_id, slug)",
    # A binding cannot cross a tenant, and deleting its target only clears it.
    "ADD CONSTRAINT projects_id_tenant_key UNIQUE (id, tenant_id)",
    "ADD CONSTRAINT consumer_id_tenant_key UNIQUE (id, tenant_id)",
    "REFERENCES projects (id, tenant_id) ON DELETE SET NULL (project_id)",
    "REFERENCES consumer (id, tenant_id) ON DELETE SET NULL (consumer_id)",
    # The delete the app performs is a stamp; the trigger clears the binding on it.
    "AFTER UPDATE OF deleted_at ON apiome.projects",
    "WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)",
    "SET project_id = NULL, updated_at = CURRENT_TIMESTAMP",
    # Retiring a consumer is a stamp as well.
    "AFTER UPDATE OF deleted_at ON apiome.consumer",
    "SET consumer_id = NULL, updated_at = CURRENT_TIMESTAMP",
    # Versions never mutate, and order is not the timestamp.
    "CONSTRAINT pacticipant_version_number_key UNIQUE (pacticipant_id, number)",
    "seq BIGINT GENERATED ALWAYS AS IDENTITY",
    "BEFORE UPDATE ON apiome.pacticipant_version",
    "RAISE EXCEPTION 'pacticipant_version rows are immutable",
    # A branch has one head, of its own pacticipant.
    "CONSTRAINT pacticipant_branch_name_key UNIQUE (pacticipant_id, name)",
    "head_version_id UUID NOT NULL",
    "FOREIGN KEY (head_version_id, pacticipant_id)",
    # Membership and tags exist once and stay inside one pacticipant.
    "CONSTRAINT pacticipant_branch_version_pkey PRIMARY KEY (branch_id, pacticipant_id, version_id)",
    "REFERENCES pacticipant_branch (id, pacticipant_id) ON DELETE CASCADE",
    "CONSTRAINT pacticipant_version_tag_pkey PRIMARY KEY (version_id, pacticipant_id, name)",
    "REFERENCES pacticipant_version (id, pacticipant_id) ON DELETE CASCADE",
)

_RBAC_FRAGMENTS = (
    "CREATE OR REPLACE FUNCTION apiome.seed_builtin_roles(p_tenant UUID)",
    "'consumer_contracts','teams','pacts']",
    "SELECT v_editor, 'pacts', a FROM unnest(ARRAY['view','create','edit']) AS a",
    "FOR t IN SELECT id FROM apiome.tenants LOOP",
    "PERFORM apiome.seed_builtin_roles(t.id)",
)


@pytest.fixture
def migration(repo_root: Path) -> str:
    """The migration's text."""
    return (repo_root / _MIGRATION).read_text()


def test_migration_declares_the_registry_rules(migration: str) -> None:
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in migration]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_only_the_pacticipant_carries_a_tenant(migration: str) -> None:
    """A child row's tenant is its pacticipant's; a second copy could disagree with it."""
    assert migration.count("tenant_id UUID NOT NULL") == 1


def test_migration_adds_the_rbac_resource_and_reseeds_every_tenant(migration: str) -> None:
    missing = [fragment for fragment in _RBAC_FRAGMENTS if fragment not in migration]
    assert not missing, f"Migration missing expected RBAC fragments: {missing}"


def test_editor_cannot_delete_a_pacticipant(migration: str) -> None:
    """Deleting a pacticipant removes its whole version history, so the Editor grid stops at edit."""
    assert "v_editor, 'pacts', a FROM unnest(ARRAY['view','create','edit','delete']" not in migration
    assert "'pacts'" not in migration.split("content_resources TEXT[] := ARRAY[")[1].split("]")[0]


def test_migration_keeps_the_previous_resources_and_grants(migration: str) -> None:
    """The seed function is replaced wholesale, so every earlier grant has to be carried forward."""
    for resource in (
        "projects", "versions", "classes", "properties", "paths", "types", "imports", "members",
        "api_keys", "billing", "lint_findings", "verification_targets", "verification_evidence",
        "consumer_contracts", "teams",
    ):
        assert f"'{resource}'" in migration, f"seed_builtin_roles dropped resource {resource}"
    for grant in (
        "VALUES (v_owner, 'document_store', 'manage')",
        "VALUES (v_admin, 'document_store', 'manage')",
        "VALUES (v_owner, 'versions', 'publish')",
        "SELECT v_editor, 'consumer_contracts', a FROM unnest(ARRAY['view','create','edit']) AS a",
    ):
        assert grant in migration, f"seed_builtin_roles dropped: {grant}"


def test_the_rest_guard_and_the_migration_agree_on_the_vocabulary() -> None:
    """The frozenset validates custom-role grids; forgetting it makes the resource ungrantable."""
    from app.permissions import RESOURCES, Resource

    assert Resource.PACTS == "pacts"
    assert Resource.PACTS in RESOURCES


def test_the_validators_mirror_the_migration(migration: str) -> None:
    """The API's slug pattern is the database's, character for character."""
    from app.pacticipant import _SLUG_PATTERN

    assert f"CHECK (slug ~ '{_SLUG_PATTERN.pattern}')" in migration
