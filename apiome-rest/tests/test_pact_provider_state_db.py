"""The provider-state registry against a live Postgres — PFX-3.3 (#6933).

What only the real schema proves (apiome-db V441):

* a state and its overrides are written and read back together, by name;
* a name is unique per provider (a 409 ``provider-state-name-taken``), not per workspace;
* replacing a state replaces its overrides; deleting a provider removes its states;
* **nothing crosses a tenant**: another workspace's provider, state or verification target is never
  reached — the store filters on the tenant, and the composite references refuse an override that
  names another tenant's target;
* setup kinds are a closed list.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of
``test_pact_publication_db``). Skipped when no database is reachable or V441 is not applied.
"""

from __future__ import annotations

from typing import Any, Dict

import psycopg2
import pytest

from app.consumer_contract_store import ConsumerActor
from app.pact_provider_state import (
    CODE_STATE_NAME_TAKEN,
    CODE_STATE_NOT_FOUND,
    ProviderStateInput,
    StateSetup,
    validate_state,
)
from app.pact_provider_state_store import (
    ResolvedOverride,
    create_state,
    delete_state,
    get_state,
    list_states,
    replace_state,
)
from app.pact_publication import PactPublicationError
from app.pacticipant_store import get_pacticipant
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

ACTOR = ConsumerActor(user_id=None, label="ci@example.com", kind="api_key")


@pytest.fixture
def registry(stack: Dict[str, Any]) -> Dict[str, Any]:
    """A published pact (so both pacticipants exist) and a verification target per tenant."""
    stack["cursor"].execute("SELECT to_regclass('apiome.pact_provider_state') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V441 not applied")
    answer = stack["client"].put(f"{publication_db.PAIR}/version/1.0.0", json=publication_db._pact())
    assert answer.status_code in (200, 201), answer.text
    tenant = stack["seed"]["tenant"]
    stack["provider"] = get_pacticipant(stack["db"], tenant, "ledger-api")
    stack["target"] = _target(stack, tenant, "staging")
    stack["other_target"] = _target(stack, stack["other"]["tenant"], "staging")
    return stack


def _target(stack: Dict[str, Any], tenant: str, slug: str) -> str:
    stack["cursor"].execute(
        """
        INSERT INTO apiome.verification_target (tenant_id, slug, name, environment, base_url)
        VALUES (%s::uuid, %s, %s, 'staging', 'https://ledger.example.test') RETURNING id::text AS id
        """,
        (tenant, slug, slug),
    )
    return stack["cursor"].fetchone()["id"]


def _state(name: str = "invoice 1042 exists", **fields: Any) -> ProviderStateInput:
    body = {
        "name": name,
        "parameters": [{"name": "id", "required": True}],
        "setup": {"kind": "state_change", "url": "/_pact/states"},
        **fields,
    }
    return validate_state(ProviderStateInput.model_validate(body))


def _override(target_id: str) -> ResolvedOverride:
    return ResolvedOverride(target_id=target_id, target_slug="staging", setup=StateSetup(kind="fixture"))


def test_a_state_and_its_overrides_read_back_together(registry: Dict[str, Any]) -> None:
    db, tenant, provider = registry["db"], registry["seed"]["tenant"], registry["provider"]
    stored = create_state(db, tenant, provider, _state(), [_override(registry["target"])], actor=ACTOR)

    assert stored.name == "invoice 1042 exists" and stored.provider == "ledger-api"
    assert [p.name for p in stored.parameters] == ["id"]
    assert stored.setup.url == "/_pact/states"
    assert [(o.target_id, o.target_slug, o.setup.kind) for o in stored.overrides] == [
        (registry["target"], "staging", "fixture")
    ]
    assert [s.id for s in list_states(db, tenant, provider)] == [stored.id]
    assert get_state(db, tenant, provider, stored.id) == stored


def test_a_name_is_unique_per_provider(registry: Dict[str, Any]) -> None:
    db, tenant, provider = registry["db"], registry["seed"]["tenant"], registry["provider"]
    create_state(db, tenant, provider, _state(), [], actor=ACTOR)
    # Another pacticipant may register the same name for itself.
    consumer = get_pacticipant(db, tenant, "billing-service")
    assert create_state(db, tenant, consumer, _state(), [], actor=ACTOR).provider == "billing-service"
    # (Last: the refused insert aborts the test's one transaction.)
    with pytest.raises(PactPublicationError) as refused:
        create_state(db, tenant, provider, _state(), [], actor=ACTOR)
    assert (refused.value.code, refused.value.pointer) == (CODE_STATE_NAME_TAKEN, "/name")


def test_replacing_replaces_the_overrides_and_renaming_into_a_taken_name_is_refused(registry: Dict[str, Any]) -> None:
    db, tenant, provider = registry["db"], registry["seed"]["tenant"], registry["provider"]
    first = create_state(db, tenant, provider, _state(), [_override(registry["target"])], actor=ACTOR)
    create_state(db, tenant, provider, _state("the ledger has entries"), [], actor=ACTOR)

    replaced = replace_state(
        db, tenant, provider, first.id, _state(setup={"kind": "fixture"}, parameters=[]), [], actor=ACTOR
    )
    assert (replaced.setup.kind, replaced.parameters, replaced.overrides) == ("fixture", [], [])
    assert replaced.updated_at >= first.updated_at

    with pytest.raises(PactPublicationError) as refused:
        replace_state(db, tenant, provider, first.id, _state("the ledger has entries"), [], actor=ACTOR)
    assert refused.value.code == CODE_STATE_NAME_TAKEN


def test_delete_removes_the_state_and_its_overrides(registry: Dict[str, Any]) -> None:
    db, tenant, provider, cursor = registry["db"], registry["seed"]["tenant"], registry["provider"], registry["cursor"]
    stored = create_state(db, tenant, provider, _state(), [_override(registry["target"])], actor=ACTOR)
    delete_state(db, tenant, provider, stored.id)
    assert list_states(db, tenant, provider) == []
    cursor.execute(
        "SELECT count(*) AS n FROM apiome.pact_provider_state_override WHERE state_id = %s::uuid", (stored.id,)
    )
    assert cursor.fetchone()["n"] == 0
    with pytest.raises(PactPublicationError) as refused:
        delete_state(db, tenant, provider, stored.id)
    assert refused.value.code == CODE_STATE_NOT_FOUND


def test_nothing_crosses_a_tenant(registry: Dict[str, Any]) -> None:
    db, tenant, provider = registry["db"], registry["seed"]["tenant"], registry["provider"]
    other = registry["other"]["tenant"]
    stored = create_state(db, tenant, provider, _state(), [], actor=ACTOR)

    # Another workspace reading with this provider record still sees nothing.
    assert list_states(db, other, provider) == []
    with pytest.raises(PactPublicationError):
        get_state(db, other, provider, stored.id)
    with pytest.raises(PactPublicationError):
        delete_state(db, other, provider, stored.id)

    # An override naming another tenant's target is refused by the database.
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        create_state(db, tenant, provider, _state("other"), [_override(registry["other_target"])], actor=ACTOR)


def test_setup_kinds_are_a_closed_list(registry: Dict[str, Any]) -> None:
    cursor, tenant, provider = registry["cursor"], registry["seed"]["tenant"], registry["provider"]
    cursor.execute("SAVEPOINT kinds")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            """
            INSERT INTO apiome.pact_provider_state (tenant_id, provider_id, name, setup)
            VALUES (%s::uuid, %s::uuid, 'x', '{"kind": "script"}'::jsonb)
            """,
            (tenant, provider.id),
        )
    cursor.execute("ROLLBACK TO SAVEPOINT kinds")
