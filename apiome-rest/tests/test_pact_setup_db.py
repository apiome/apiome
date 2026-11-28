"""The Contracts guided set-up against a live Postgres — PFX-8.20 (#7317).

What only the real schema (apiome-db V460) and the real SQL prove:

* an empty workspace reads its projects as proposed providers and starts at the first section;
* what exists finishes its section: pacticipants, environments, a published pact, a spec-as-contract
  source; a project's repository and owner team come with its candidate, and a candidate names the
  pacticipant that already exists for it;
* a workspace with a completed broker migration arrives with the first two sections done;
* progress saves per workspace and merges; a recorded CI key reads back only while it is live;
* what a GitHub action did is kept per repository;
* the database itself refuses an unknown section and half a key;
* nothing crosses a tenant.

Runs inside one always-rolled-back transaction. Skipped when no database is reachable or V460 is
not applied.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator

import psycopg2
import pytest

from app.consumer_contract_store import ConsumerActor
from app.pact_setup import PactSetupCiKey, PactSetupSave
from app.pact_setup_store import (
    NO_GITHUB_REPOSITORY,
    NO_LINKED_ACCOUNT,
    get_repository,
    read_state,
    record_github,
    save_progress,
)
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

ACTOR = ConsumerActor(user_id=None, label="ada@example.com")


@pytest.fixture
def setup(stack: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    stack["cursor"].execute("SELECT to_regclass('apiome.pact_setup_progress') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V460 not applied")
    yield stack


def _state(env: Dict[str, Any], which: str = "seed"):
    return read_state(env["db"].execute_query, env[which]["tenant"], can_edit=True)


def _states(env: Dict[str, Any], which: str = "seed") -> Dict[str, str]:
    return {section.id: section.state for section in _state(env, which).sections}


def _pacticipant(
    env: Dict[str, Any], name: str, slug: str, *, which: str = "seed", project: bool = False, url: str | None = None
) -> str:
    env["cursor"].execute(
        """INSERT INTO apiome.pacticipant (tenant_id, slug, name, project_id, repository_url)
           VALUES (%s::uuid, %s, %s, %s::uuid, %s) RETURNING id::text AS id""",
        (env[which]["tenant"], slug, name, env[which]["project"] if project else None, url),
    )
    return env["cursor"].fetchone()["id"]


def _repository(env: Dict[str, Any], full_name: str, *, which: str = "seed") -> str:
    env["cursor"].execute(
        """INSERT INTO apiome.tenant_repositories
             (tenant_id, source, provider, clone_url, clone_url_normalized, repository_full_name, default_branch)
           VALUES (%s::uuid, 'public_url', 'github', %s, %s, %s, 'trunk') RETURNING id::text AS id""",
        (
            env[which]["tenant"],
            f"https://github.com/{full_name}.git",
            f"https://github.com/{full_name.lower()}.git",
            full_name,
        ),
    )
    return env["cursor"].fetchone()["id"]


def test_an_empty_workspace_proposes_its_projects_and_starts_at_the_top(setup: Dict[str, Any]) -> None:
    state = _state(setup)
    assert [section.state for section in state.sections] == ["next", "todo", "todo", "todo", "todo", "todo"]
    assert state.done == 0 and state.total == 6 and not state.complete
    assert [(item.name, item.role, item.pacticipant) for item in state.candidates] == [("Pets", "provider", None)]
    assert state.github.linked is False and state.github.reason == NO_GITHUB_REPOSITORY
    assert state.saved.marked == [] and state.updated_at is None


def test_what_exists_finishes_its_section(setup: Dict[str, Any]) -> None:
    cursor, tenant, project = setup["cursor"], setup["seed"]["tenant"], setup["seed"]["project"]
    # The project is read from a repository and owned by a team.
    bound = _repository(setup, "acme/pets-service")
    loose = _repository(setup, "acme/orders-ui")
    cursor.execute(
        """INSERT INTO apiome.project_repository_sources
               (tenant_id, project_id, repository_id, branch, path, precedence)
           VALUES (%s::uuid, %s::uuid, %s::uuid, 'release', 'openapi.yaml', 1)""",
        (tenant, project, bound),
    )
    cursor.execute(
        "INSERT INTO apiome.teams (tenant_id, slug, name) VALUES (%s::uuid, 'payments', 'Payments team') "
        "RETURNING id::text AS id",
        (tenant,),
    )
    cursor.execute(
        """INSERT INTO apiome.entity_owners (tenant_id, entity_kind, entity_id, team_id, status, source, confirmed_at)
           VALUES (%s::uuid, 'project', %s::uuid, %s::uuid, 'confirmed', 'manual', now())""",
        (tenant, project, cursor.fetchone()["id"]),
    )
    provider = _pacticipant(setup, "Pets Service", "pets-service", project=True)
    _pacticipant(setup, "Orders", "orders", url="https://github.com/Acme/Orders-UI")
    cursor.execute(
        "INSERT INTO apiome.pact_environment (tenant_id, name, display_name, production) "
        "VALUES (%s::uuid, 'production', 'Production', true), (%s::uuid, 'staging', 'Staging', false)",
        (tenant, tenant),
    )
    cursor.execute(
        "INSERT INTO apiome.provider_contract_source (pacticipant_id, tenant_id, on_project_publish) "
        "VALUES (%s::uuid, %s::uuid, true)",
        (provider, tenant),
    )

    state = _state(setup)
    assert {section.id: section.state for section in state.sections} == {
        "pacticipants": "done",
        "environments": "done",
        "pipelines": "next",
        "first-pact": "todo",
        "provider": "done",
        "gates": "todo",
    }
    assert state.facts.environments == ["production", "staging"] and state.facts.production_environment
    pets, orders = state.candidates
    assert (pets.name, pets.owner, pets.main_branch, pets.repository_id) == ("Pets", "Payments team", "release", bound)
    assert pets.repository_url == "https://github.com/acme/pets-service" and pets.pacticipant == "pets-service"
    assert pets.pacticipant_name == "Pets Service" and pets.contract_source is True and not orders.contract_source
    assert (orders.name, orders.role, orders.main_branch, orders.pacticipant) == (
        "orders-ui",
        "consumer",
        "trunk",
        "orders",
    )
    # Registered from a public URL: listed, but nothing can be written with it.
    assert state.github.linked is False and state.github.reason == NO_LINKED_ACCOUNT
    assert {item.full_name: (item.linked, item.pacticipant_name) for item in state.github.repositories} == {
        "acme/orders-ui": (False, "Orders"),
        "acme/pets-service": (False, None),
    }
    assert get_repository(setup["db"].execute_query, tenant, loose)["repository_full_name"] == "acme/orders-ui"
    # The other workspace sees none of it.
    assert _states(setup, "other")["pacticipants"] == "next"
    assert get_repository(setup["db"].execute_query, setup["other"]["tenant"], loose) is None


def test_a_published_pact_finishes_the_first_pact_section(setup: Dict[str, Any]) -> None:
    response = setup["client"].put(
        f"{publication_db.BASE}/pacts/provider/Ledger%20API/consumer/Billing%20Service/version/1.0.0",
        json=publication_db._pact(),
    )
    assert response.status_code in (200, 201), response.text
    states = _states(setup)
    assert states["pacticipants"] == "done" and states["first-pact"] == "done"
    assert _state(setup).facts.pacts == 1


def test_a_migrated_workspace_arrives_with_the_first_two_sections_done(setup: Dict[str, Any]) -> None:
    setup["cursor"].execute(
        """INSERT INTO apiome.pact_migration_run (tenant_id, source, auth_kind, mode, status, finished_at)
           VALUES (%s::uuid, 'https://broker.example.com', 'token', 'copy', 'completed', now())""",
        (setup["seed"]["tenant"],),
    )
    state = _state(setup)
    assert state.facts.migrated is True
    assert [section.state for section in state.sections][:3] == ["done", "done", "next"]
    assert _state(setup, "other").facts.migrated is False


def test_progress_saves_per_workspace_and_merges(setup: Dict[str, Any]) -> None:
    database, tenant = setup["db"], setup["seed"]["tenant"]
    save_progress(
        database, tenant, PactSetupSave(mark={"pipelines": True, "gates": True}, first_pact_path="spec"), actor=ACTOR
    )
    save_progress(database, tenant, PactSetupSave(mark={"gates": False, "provider": True}), actor=ACTOR)
    state = _state(setup)
    assert state.saved.marked == ["pipelines", "provider"] and state.saved.first_pact_path == "spec"
    assert state.updated_by == "ada@example.com" and state.updated_at
    assert _states(setup)["pipelines"] == "done" and _states(setup)["gates"] == "todo"
    assert _state(setup, "other").saved.marked == []
    setup["cursor"].execute(
        "SELECT count(*) AS n FROM apiome.access_audit WHERE tenant_id = %s::uuid AND action = 'pacts.setup.update'",
        (tenant,),
    )
    assert setup["cursor"].fetchone()["n"] == 2


def test_a_recorded_key_reads_back_only_while_it_is_live(setup: Dict[str, Any]) -> None:
    database, cursor, tenant = setup["db"], setup["cursor"], setup["seed"]["tenant"]
    cursor.execute(
        """INSERT INTO apiome.api_keys (tenant_id, name, key_hash, key_prefix)
           VALUES (%s::uuid, %s, %s, 'apk_9f2c...') RETURNING id::text AS id""",
        (tenant, f"ci-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex),
    )
    key = cursor.fetchone()["id"]
    save_progress(database, tenant, PactSetupSave(ci_key=PactSetupCiKey(id=key, prefix="apk_9f2c...")), actor=ACTOR)
    assert _state(setup).saved.ci_key == PactSetupCiKey(id=key, prefix="apk_9f2c...")
    assert _states(setup)["pipelines"] == "done"
    cursor.execute("UPDATE apiome.api_keys SET enabled = false WHERE id = %s::uuid", (key,))
    assert _state(setup).saved.ci_key is None and _states(setup)["pipelines"] != "done"
    cursor.execute("UPDATE apiome.api_keys SET enabled = true WHERE id = %s::uuid", (key,))
    save_progress(database, tenant, PactSetupSave(forget_ci_key=True), actor=ACTOR)
    assert _state(setup).saved.ci_key is None


def test_what_a_github_action_did_is_kept_per_repository(setup: Dict[str, Any]) -> None:
    database, tenant = setup["db"], setup["seed"]["tenant"]
    repository = _repository(setup, "acme/orders-ui")
    record_github(
        database,
        tenant,
        actor=ACTOR,
        action="pacts.setup.github.secrets",
        updates={repository: {"secrets_at": "2026-11-30T10:00:00+00:00"}},
        detail={"repositories": [repository]},
    )
    record_github(
        database,
        tenant,
        actor=ACTOR,
        action="pacts.setup.github.pull_requests",
        updates={
            repository: {"pull_request_url": "https://github.com/acme/orders-ui/pull/7", "pull_request_number": 7}
        },
        detail={},
    )
    (listed,) = _state(setup).github.repositories
    assert listed.secrets_written_at == "2026-11-30T10:00:00+00:00"
    assert listed.pull_request_url == "https://github.com/acme/orders-ui/pull/7"
    # A later save keeps it.
    save_progress(database, tenant, PactSetupSave(mark={"gates": True}), actor=ACTOR)
    assert _state(setup).github.repositories[0].pull_request_url is not None


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO apiome.pact_setup_progress (tenant_id, marked) VALUES (%s::uuid, ARRAY['billing'])",
        "INSERT INTO apiome.pact_setup_progress (tenant_id, first_pact_path) VALUES (%s::uuid, 'mock')",
        "INSERT INTO apiome.pact_setup_progress (tenant_id, ci_key_prefix) VALUES (%s::uuid, 'apk_')",
        "INSERT INTO apiome.pact_setup_progress (tenant_id, github) VALUES (%s::uuid, '[]'::jsonb)",
    ],
)
def test_the_database_refuses_what_the_page_cannot_mean(setup: Dict[str, Any], statement: str) -> None:
    cursor = setup["cursor"]
    cursor.execute("SAVEPOINT refused")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(statement, (setup["seed"]["tenant"],))
    cursor.execute("ROLLBACK TO SAVEPOINT refused")
