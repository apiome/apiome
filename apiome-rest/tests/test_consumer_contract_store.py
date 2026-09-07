"""The consumer contract store's own rules — CTG-4.1 (#4479).

The database is faked here: what is asserted is the store's contract with it, which is where
three of the ticket's guarantees actually live.

* **Pointers are derived, never supplied.** :func:`~app.consumer_contract_store.record_contract`
  computes ``surface_pointers`` from the surface it is handed, so a caller cannot store a
  pointer set that disagrees with the surface beside it.
* **A handle is validated and unique before a row is written**, with the same stable codes the
  API returns.
* **The CTG-4.2 intersection is a store call, not a document walk** — and the query it makes is
  scoped to one project's live consumers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from app.consumer_contract import (
    ConsumerContractField,
    ConsumerContractOperation,
    ConsumerContractSurface,
    ConsumerInput,
    ConsumerPatch,
    ConsumerRecord,
    ConsumerValidationError,
    UnresolvedInteraction,
    consumer_record_from_row,
)
from app.consumer_contract_store import (
    ConsumerActor,
    actor_from_auth,
    contracts_affected_by,
    create_consumer,
    ensure_consumer,
    list_consumer_summaries,
    record_contract,
    resolve_project,
    resolve_version,
    retire_consumer,
    update_consumer,
)

_TENANT = "test-tenant-id"
_PROJECT = "11111111-1111-4111-8111-111111111111"
_CONSUMER = "33333333-3333-4333-8333-333333333333"
_VERSION = "22222222-2222-4222-8222-222222222222"


def _consumer_row(**overrides: Any) -> Dict[str, Any]:
    """A ``consumer`` row as the driver returns one."""
    row: Dict[str, Any] = {
        "id": _CONSUMER,
        "tenant_id": _TENANT,
        "project_id": _PROJECT,
        "slug": "billing-service",
        "name": "Billing Service",
        "description": None,
        "owner": "Payments squad",
        "contact": None,
        "metadata": {},
        "created_at": datetime(2026, 9, 7, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 7, tzinfo=timezone.utc),
        "deleted_at": None,
    }
    row.update(overrides)
    return row


def _contract_row(**overrides: Any) -> Dict[str, Any]:
    """A ``consumer_contract`` row as the driver returns one."""
    row: Dict[str, Any] = {
        "id": "44444444-4444-4444-8444-444444444444",
        "tenant_id": _TENANT,
        "project_id": _PROJECT,
        "consumer_id": _CONSUMER,
        "revision": 1,
        "is_current": True,
        "source": "manual",
        "version_id": _VERSION,
        "version_label": "1.0.0",
        "surface": {"schema_version": "apiome.consumer.contract/v1", "operations": []},
        "operation_count": 0,
        "field_count": 0,
        "surface_pointers": [],
        "unresolved": [],
        "unresolved_count": 0,
        "source_metadata": {},
        "source_digest": None,
        "note": None,
        "created_by": None,
        "actor_label": None,
        "created_at": datetime(2026, 9, 7, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _surface() -> ConsumerContractSurface:
    """A surface with one operation and one ``$ref``-reached field."""
    return ConsumerContractSurface(
        operations=[
            ConsumerContractOperation(
                method="get",
                path="/pets",
                pointer="/paths/~1pets/get",
                fields=[
                    ConsumerContractField(
                        pointer=(
                            "/paths/~1pets/get/responses/200/content/"
                            "application~1json/schema/properties/total"
                        ),
                        schema_pointer="/components/schemas/PetList/properties/total",
                        location="response",
                        status="200",
                        media_type="application/json",
                        path="total",
                    )
                ],
            )
        ]
    )


@pytest.fixture
def fake_db():
    """A stand-in for the ``db`` singleton, with every accessor the store uses."""
    stub = MagicMock()
    stub.get_consumer_by_slug.return_value = None
    stub.get_consumer_by_id.return_value = None
    stub.list_consumers.return_value = []
    stub.list_current_consumer_contracts.return_value = []
    stub.insert_consumer.return_value = _consumer_row()
    stub.update_consumer.return_value = _consumer_row()
    stub.soft_delete_consumer.return_value = True
    stub.insert_consumer_contract.return_value = _contract_row()
    stub.find_consumer_contracts_by_pointers.return_value = []
    with patch("app.consumer_contract_store.db", stub):
        yield stub


# ===========================================================================
# Actor
# ===========================================================================


def test_an_api_key_caller_is_recorded_as_a_runner() -> None:
    actor = actor_from_auth(
        {"auth_method": "api_key", "user_id": "u1", "user_email": "ci@example.com"}
    )
    assert actor.kind == "api_key"
    assert actor.user_id == "u1"
    assert actor.label == "ci@example.com"


def test_an_interactive_caller_is_recorded_as_a_user() -> None:
    actor = actor_from_auth({"auth_method": "jwt", "user_name": "Ada"}, "u2")
    assert actor.kind == "user"
    assert actor.user_id == "u2"
    assert actor.label == "Ada"


# ===========================================================================
# Resolution
# ===========================================================================


def test_an_unknown_project_refuses_with_a_stable_code(fake_db) -> None:
    fake_db.get_project_by_slug.return_value = None
    with pytest.raises(ConsumerValidationError) as caught:
        resolve_project(_TENANT, "ghost")
    assert caught.value.code == "consumer-project-not-found"


def test_an_empty_project_reference_refuses(fake_db) -> None:
    with pytest.raises(ConsumerValidationError) as caught:
        resolve_project(_TENANT, "   ")
    assert caught.value.code == "consumer-project-not-found"


def test_an_omitted_version_resolves_to_the_projects_latest(fake_db) -> None:
    fake_db.get_latest_revision_id_for_project.return_value = _VERSION
    fake_db.get_version_by_id.return_value = {"id": _VERSION, "version_id": "2.0.0"}
    assert resolve_version(_TENANT, _PROJECT, None)["version_id"] == "2.0.0"


def test_a_project_with_no_versions_refuses_by_name(fake_db) -> None:
    fake_db.get_latest_revision_id_for_project.return_value = None
    with pytest.raises(ConsumerValidationError) as caught:
        resolve_version(_TENANT, _PROJECT, "latest")
    assert caught.value.code == "consumer-version-not-found"


def test_a_version_from_another_project_does_not_resolve(fake_db) -> None:
    fake_db.get_version_by_id.return_value = {"id": _VERSION, "project_id": "other"}
    with pytest.raises(ConsumerValidationError) as caught:
        resolve_version(_TENANT, _PROJECT, _VERSION)
    assert caught.value.code == "consumer-version-not-found"


# ===========================================================================
# Registering
# ===========================================================================


def test_a_handle_is_derived_from_the_name_when_omitted(fake_db) -> None:
    create_consumer(
        _TENANT, _PROJECT, ConsumerInput(name="Billing Service"), actor=ConsumerActor()
    )
    assert fake_db.insert_consumer.call_args.kwargs["slug"] == "billing-service"


def test_a_malformed_handle_never_reaches_the_database(fake_db) -> None:
    with pytest.raises(ConsumerValidationError) as caught:
        create_consumer(
            _TENANT, _PROJECT, ConsumerInput(name="x", slug="Not A Slug"), actor=ConsumerActor()
        )
    assert caught.value.code == "consumer-invalid-slug"
    assert not fake_db.insert_consumer.called


def test_a_taken_handle_refuses_before_the_insert(fake_db) -> None:
    fake_db.get_consumer_by_slug.return_value = _consumer_row()
    with pytest.raises(ConsumerValidationError) as caught:
        create_consumer(
            _TENANT, _PROJECT, ConsumerInput(name="Billing Service"), actor=ConsumerActor()
        )
    assert caught.value.code == "consumer-slug-taken"
    assert not fake_db.insert_consumer.called


def test_ensure_consumer_returns_the_existing_one_without_writing(fake_db) -> None:
    fake_db.get_consumer_by_slug.return_value = _consumer_row()
    record = ensure_consumer(
        _TENANT, _PROJECT, slug="billing-service", name="Billing", actor=ConsumerActor()
    )
    assert record.id == _CONSUMER
    assert not fake_db.insert_consumer.called


def test_ensure_consumer_registers_a_new_one_when_it_is_absent(fake_db) -> None:
    ensure_consumer(
        _TENANT, _PROJECT, slug="checkout", name="Checkout", actor=ConsumerActor()
    )
    assert fake_db.insert_consumer.call_args.kwargs["slug"] == "checkout"


# ===========================================================================
# Updating and retiring
# ===========================================================================


def test_a_patch_with_no_writable_field_does_not_touch_the_database(fake_db) -> None:
    fake_db.get_consumer_by_slug.return_value = _consumer_row()
    result = update_consumer(
        _TENANT, _PROJECT, "billing-service", ConsumerPatch(), actor=ConsumerActor()
    )
    assert isinstance(result, ConsumerRecord)
    assert not fake_db.update_consumer.called


def test_a_patch_forwards_only_the_fields_that_were_set(fake_db) -> None:
    fake_db.get_consumer_by_slug.return_value = _consumer_row()
    update_consumer(
        _TENANT,
        _PROJECT,
        "billing-service",
        ConsumerPatch(owner="Platform squad"),
        actor=ConsumerActor(),
    )
    assert fake_db.update_consumer.call_args.args[2] == {"owner": "Platform squad"}


def test_retiring_an_already_retired_consumer_refuses(fake_db) -> None:
    fake_db.get_consumer_by_slug.return_value = _consumer_row()
    fake_db.soft_delete_consumer.return_value = False
    with pytest.raises(ConsumerValidationError) as caught:
        retire_consumer(_TENANT, _PROJECT, "billing-service", actor=ConsumerActor())
    assert caught.value.code == "consumer-not-found"


# ===========================================================================
# Recording a revision
# ===========================================================================


def test_recording_derives_the_pointer_array_from_the_surface(fake_db) -> None:
    record_contract(
        _TENANT,
        _PROJECT,
        consumer_record_from_row(_consumer_row()),
        _surface(),
        actor=ConsumerActor(user_id=None, label="Ada"),
    )
    written = fake_db.insert_consumer_contract.call_args.kwargs
    assert written["surface_pointers"] == [
        "/components/schemas/PetList/properties/total",
        "/paths/~1pets/get",
        "/paths/~1pets/get/responses/200/content/application~1json/schema/properties/total",
    ]
    assert written["operation_count"] == 1
    assert written["field_count"] == 1


def test_recording_stores_unresolved_entries_rather_than_dropping_them(fake_db) -> None:
    record_contract(
        _TENANT,
        _PROJECT,
        consumer_record_from_row(_consumer_row()),
        _surface(),
        actor=ConsumerActor(),
        unresolved=[UnresolvedInteraction(reason="field-not-found", message="gone")],
    )
    written = fake_db.insert_consumer_contract.call_args.kwargs
    assert [entry["reason"] for entry in written["unresolved"]] == ["field-not-found"]


def test_recording_an_empty_surface_still_writes_a_revision(fake_db) -> None:
    """A Pact import that resolved nothing must leave a visible, empty revision — not silence."""
    record_contract(
        _TENANT,
        _PROJECT,
        consumer_record_from_row(_consumer_row()),
        ConsumerContractSurface(),
        actor=ConsumerActor(),
        source="pact",
        unresolved=[UnresolvedInteraction(reason="operation-not-found", message="gone")],
    )
    written = fake_db.insert_consumer_contract.call_args.kwargs
    assert written["operation_count"] == 0
    assert written["surface_pointers"] == []
    assert written["source"] == "pact"


def test_a_write_that_finds_no_consumer_refuses_by_name(fake_db) -> None:
    fake_db.insert_consumer_contract.return_value = None
    with pytest.raises(ConsumerValidationError) as caught:
        record_contract(
            _TENANT,
            _PROJECT,
            consumer_record_from_row(_consumer_row()),
            _surface(),
            actor=ConsumerActor(),
        )
    assert caught.value.code == "consumer-not-found"


# ===========================================================================
# Reading the project page's list
# ===========================================================================


def test_the_project_listing_joins_consumers_to_their_current_contracts(fake_db) -> None:
    fake_db.list_consumers.return_value = [
        _consumer_row(),
        _consumer_row(id="55555555-5555-4555-8555-555555555555", slug="checkout"),
    ]
    fake_db.list_current_consumer_contracts.return_value = [_contract_row()]
    summaries = list_consumer_summaries(_TENANT, _PROJECT)
    assert [summary.consumer.slug for summary in summaries] == ["billing-service", "checkout"]
    assert summaries[0].contract is not None
    assert summaries[1].contract is None


def test_the_project_listing_costs_two_reads_not_one_per_consumer(fake_db) -> None:
    fake_db.list_consumers.return_value = [_consumer_row() for _ in range(20)]
    list_consumer_summaries(_TENANT, _PROJECT)
    assert fake_db.list_consumers.call_count == 1
    assert fake_db.list_current_consumer_contracts.call_count == 1
    assert not fake_db.get_current_consumer_contract.called


# ===========================================================================
# The CTG-4.2 enabling query
# ===========================================================================


def test_the_intersection_query_is_scoped_to_the_project_and_its_pointers(fake_db) -> None:
    fake_db.find_consumer_contracts_by_pointers.return_value = [_contract_row()]
    affected = contracts_affected_by(
        _TENANT, _PROJECT, ["/components/schemas/PetList/properties/total"]
    )
    assert [record.consumer_id for record in affected] == [_CONSUMER]
    args = fake_db.find_consumer_contracts_by_pointers.call_args.args
    assert args[0] == _PROJECT
    assert args[1] == _TENANT
    assert args[2] == ["/components/schemas/PetList/properties/total"]


def test_the_intersection_query_answers_nothing_for_no_pointers(fake_db) -> None:
    assert contracts_affected_by(_TENANT, _PROJECT, []) == []
