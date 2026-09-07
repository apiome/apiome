"""HTTP contract tests for the consumer contract registry — CTG-4.1 (#4479).

``/v1/tenants/{tenant_slug}/projects/{project_ref}/consumers`` and its two siblings. The store
is faked (its own resolution logic is covered by ``test_consumer_surface`` and
``test_pact_contract_import``); what is asserted here is the endpoint's own contract:

* every route is gated on the ``consumer_contracts`` RBAC resource, with *deleting* separated
  from declaring, and a denial is a 403 rather than a silent no-op;
* a refusal from the registry becomes the HTTP status that matches its *kind* (404 unknown,
  409 handle taken, 413 oversized, 400 bad definition) and always carries the stable code;
* the response shapes a client parses — including that an unresolved interaction reaches the
  caller on the import response, not only in the stored row;
* the two ingestion paths both write a revision and neither overwrites one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.consumer_contract import (
    CODE_CONSUMER_NOT_FOUND,
    CODE_PACT_TOO_LARGE,
    CODE_PROJECT_NOT_FOUND,
    CODE_SLUG_TAKEN,
    CODE_VERSION_NOT_FOUND,
    ConsumerContractField,
    ConsumerContractOperation,
    ConsumerContractRecord,
    ConsumerContractSurface,
    ConsumerRecord,
    ConsumerSummary,
    ConsumerValidationError,
    UnresolvedInteraction,
)
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}
_CONSUMER_ID = "33333333-3333-4333-8333-333333333333"
_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
_VERSION_ID = "22222222-2222-4222-8222-222222222222"
_BASE = "/v1/tenants/acme/projects/pets"


def _project() -> Dict[str, Any]:
    """A resolved project row."""
    return {"id": _PROJECT_ID, "slug": "pets", "name": "Pets"}


def _version() -> Dict[str, Any]:
    """A resolved versions row."""
    return {"id": _VERSION_ID, "version_id": "1.0.0", "project_id": _PROJECT_ID}


def _consumer(**overrides: Any) -> ConsumerRecord:
    """A stored consumer as the store returns one."""
    payload: Dict[str, Any] = {
        "id": _CONSUMER_ID,
        "tenant_id": "test-tenant-id",
        "project_id": _PROJECT_ID,
        "slug": "billing-service",
        "name": "Billing Service",
        "owner": "Payments squad",
        "metadata": {},
        "created_at": datetime(2026, 9, 7, tzinfo=timezone.utc).isoformat(),
    }
    payload.update(overrides)
    return ConsumerRecord(**payload)


def _surface() -> ConsumerContractSurface:
    """A one-operation, one-field surface."""
    return ConsumerContractSurface(
        operations=[
            ConsumerContractOperation(
                method="get",
                path="/pets",
                pointer="/paths/~1pets/get",
                operation_id="listPets",
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


def _contract(**overrides: Any) -> ConsumerContractRecord:
    """A stored contract revision as the store returns one."""
    payload: Dict[str, Any] = {
        "id": "44444444-4444-4444-8444-444444444444",
        "consumer_id": _CONSUMER_ID,
        "revision": 2,
        "is_current": True,
        "source": "manual",
        "version_id": _VERSION_ID,
        "version_label": "1.0.0",
        "surface": _surface(),
        "operation_count": 1,
        "field_count": 1,
        "unresolved": [],
        "unresolved_count": 0,
    }
    payload.update(overrides)
    return ConsumerContractRecord(**payload)


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request, grant every permission, and resolve project and version."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    with patch(
        "app.consumer_contract_routes.enforce_permission", return_value="test-user-id"
    ), patch(
        "app.consumer_contract_routes.resolve_project", return_value=_project()
    ), patch(
        "app.consumer_contract_routes.resolve_version", return_value=_version()
    ):
        yield
    app.dependency_overrides.clear()


@pytest.fixture
def _spec_document():
    """Serve a small OpenAPI document to whatever resolves a stored revision."""
    document = {
        "openapi": "3.0.3",
        "info": {"title": "Pets", "version": "1.0.0"},
        "paths": {
            "/pets": {
                "get": {
                    "operationId": "listPets",
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"total": {"type": "integer"}},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    with patch(
        "app.consumer_contract_routes.openapi_for_revision", return_value=document
    ) as rendered:
        yield rendered


# ===========================================================================
# List and read
# ===========================================================================


def test_listing_returns_each_consumer_with_its_current_contract() -> None:
    summaries: List[ConsumerSummary] = [
        ConsumerSummary(consumer=_consumer(), contract=_contract())
    ]
    with patch(
        "app.consumer_contract_routes.list_consumer_summaries", return_value=summaries
    ):
        response = client.get(f"{_BASE}/consumers")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["consumers"][0]["consumer"]["slug"] == "billing-service"
    assert body["consumers"][0]["contract"]["revision"] == 2
    assert body["consumers"][0]["contract"]["operation_count"] == 1


def test_a_consumer_that_has_declared_nothing_is_still_listed() -> None:
    with patch(
        "app.consumer_contract_routes.list_consumer_summaries",
        return_value=[ConsumerSummary(consumer=_consumer(), contract=None)],
    ):
        body = client.get(f"{_BASE}/consumers").json()
    assert body["consumers"][0]["contract"] is None


def test_an_empty_registry_is_an_empty_list_not_an_error() -> None:
    with patch("app.consumer_contract_routes.list_consumer_summaries", return_value=[]):
        response = client.get(f"{_BASE}/consumers")
    assert response.status_code == 200
    assert response.json() == {"consumers": [], "count": 0}


def test_an_unknown_project_is_a_404_with_its_stable_code() -> None:
    with patch(
        "app.consumer_contract_routes.resolve_project",
        side_effect=ConsumerValidationError(CODE_PROJECT_NOT_FOUND, "no project 'ghost'"),
    ):
        response = client.get("/v1/tenants/acme/projects/ghost/consumers")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_PROJECT_NOT_FOUND


def test_reading_one_consumer_returns_it_with_its_contract() -> None:
    with patch(
        "app.consumer_contract_routes.get_consumer", return_value=_consumer()
    ), patch("app.consumer_contract_routes.current_contract", return_value=_contract()):
        response = client.get(f"{_BASE}/consumers/billing-service")
    assert response.status_code == 200
    body = response.json()
    assert body["consumer"]["slug"] == "billing-service"
    assert body["contract"]["surface"]["operations"][0]["pointer"] == "/paths/~1pets/get"


def test_a_consumer_without_a_contract_reads_back_with_a_null_contract() -> None:
    with patch(
        "app.consumer_contract_routes.get_consumer", return_value=_consumer()
    ), patch(
        "app.consumer_contract_routes.current_contract",
        side_effect=ConsumerValidationError("consumer-contract-not-found", "none yet"),
    ):
        response = client.get(f"{_BASE}/consumers/billing-service")
    assert response.status_code == 200
    assert response.json()["contract"] is None


def test_an_unknown_consumer_is_a_404() -> None:
    with patch(
        "app.consumer_contract_routes.get_consumer",
        side_effect=ConsumerValidationError(CODE_CONSUMER_NOT_FOUND, "no consumer 'ghost'"),
    ):
        response = client.get(f"{_BASE}/consumers/ghost")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_CONSUMER_NOT_FOUND


# ===========================================================================
# Register, update, retire
# ===========================================================================


def test_registering_a_consumer_returns_201_and_the_stored_record() -> None:
    with patch(
        "app.consumer_contract_routes.create_consumer", return_value=_consumer()
    ) as create:
        response = client.post(
            f"{_BASE}/consumers",
            json={"name": "Billing Service", "owner": "Payments squad"},
        )
    assert response.status_code == 201
    assert response.json()["slug"] == "billing-service"
    assert create.call_args.args[0] == "test-tenant-id"
    assert create.call_args.args[1] == _PROJECT_ID


def test_a_taken_handle_is_a_409() -> None:
    with patch(
        "app.consumer_contract_routes.create_consumer",
        side_effect=ConsumerValidationError(CODE_SLUG_TAKEN, "already exists"),
    ):
        response = client.post(f"{_BASE}/consumers", json={"name": "Billing Service"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == CODE_SLUG_TAKEN


def test_a_malformed_handle_is_a_400_with_its_code() -> None:
    with patch(
        "app.consumer_contract_routes.create_consumer",
        side_effect=ConsumerValidationError("consumer-invalid-slug", "bad handle"),
    ):
        response = client.post(
            f"{_BASE}/consumers", json={"name": "Billing", "slug": "Not A Slug"}
        )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "consumer-invalid-slug"


def test_the_handle_is_not_patchable() -> None:
    """``slug`` is the name CI and Pact files use; the patch model forbids it outright."""
    response = client.patch(f"{_BASE}/consumers/billing-service", json={"slug": "renamed"})
    assert response.status_code == 422


def test_patching_a_consumer_returns_the_updated_record() -> None:
    with patch(
        "app.consumer_contract_routes.update_consumer",
        return_value=_consumer(owner="Platform squad"),
    ):
        response = client.patch(
            f"{_BASE}/consumers/billing-service", json={"owner": "Platform squad"}
        )
    assert response.status_code == 200
    assert response.json()["owner"] == "Platform squad"


def test_retiring_a_consumer_is_a_204() -> None:
    with patch("app.consumer_contract_routes.retire_consumer") as retire:
        response = client.delete(f"{_BASE}/consumers/billing-service")
    assert response.status_code == 204
    assert response.content == b""
    assert retire.called


def test_retiring_needs_the_delete_action_not_merely_edit() -> None:
    """Removing a consumer removes a signal that guards other people's changes."""
    with patch(
        "app.consumer_contract_routes.enforce_permission", return_value="test-user-id"
    ) as guard, patch("app.consumer_contract_routes.retire_consumer"):
        client.delete(f"{_BASE}/consumers/billing-service")
    assert guard.call_args.args[2] == "consumer_contracts"
    assert guard.call_args.args[3] == "delete"


def test_listing_needs_only_the_view_action() -> None:
    with patch(
        "app.consumer_contract_routes.enforce_permission", return_value="test-user-id"
    ) as guard, patch(
        "app.consumer_contract_routes.list_consumer_summaries", return_value=[]
    ):
        client.get(f"{_BASE}/consumers")
    assert guard.call_args.args[2] == "consumer_contracts"
    assert guard.call_args.args[3] == "view"


def test_a_denied_caller_gets_a_403_and_the_store_is_never_touched() -> None:
    from fastapi import HTTPException

    with patch(
        "app.consumer_contract_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="denied"),
    ), patch("app.consumer_contract_routes.list_consumer_summaries") as store:
        response = client.get(f"{_BASE}/consumers")
    assert response.status_code == 403
    assert not store.called


# ===========================================================================
# The picker's catalogue
# ===========================================================================


def test_the_catalogue_lists_operations_and_their_fields(_spec_document) -> None:
    response = client.get(f"{_BASE}/consumer-surface")
    assert response.status_code == 200
    body = response.json()
    assert body["version_record_id"] == _VERSION_ID
    assert body["version_label"] == "1.0.0"
    assert body["count"] == 1
    operation = body["operations"][0]
    assert operation["pointer"] == "/paths/~1pets/get"
    assert {field["path"] for field in operation["fields"]} == {"limit", "total"}


def test_an_unknown_version_is_a_404_from_the_catalogue() -> None:
    with patch(
        "app.consumer_contract_routes.resolve_version",
        side_effect=ConsumerValidationError(CODE_VERSION_NOT_FOUND, "no version '9.9.9'"),
    ):
        response = client.get(f"{_BASE}/consumer-surface?version=9.9.9")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_VERSION_NOT_FOUND


def test_a_version_that_cannot_be_rendered_is_a_422_not_a_500() -> None:
    with patch(
        "app.consumer_contract_routes.openapi_for_revision",
        side_effect=RuntimeError("boom"),
    ):
        response = client.get(f"{_BASE}/consumer-surface")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "consumer-specification-unavailable"


# ===========================================================================
# Declaring a contract from a picked surface
# ===========================================================================


def test_declaring_a_picked_surface_writes_a_revision(_spec_document) -> None:
    with patch(
        "app.consumer_contract_routes.get_consumer", return_value=_consumer()
    ), patch(
        "app.consumer_contract_routes.record_contract", return_value=_contract()
    ) as record:
        response = client.put(
            f"{_BASE}/consumers/billing-service/contract",
            json={
                "operations": [
                    {
                        "method": "GET",
                        "path": "/pets",
                        "fields": [{"location": "response", "path": "total"}],
                    }
                ]
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["contract"]["revision"] == 2
    assert body["unresolved"] == []
    assert record.call_args.kwargs["source"] == "manual"
    assert record.call_args.kwargs["version_id"] == _VERSION_ID


def test_a_picked_field_that_does_not_resolve_comes_back_as_unresolved(_spec_document) -> None:
    with patch(
        "app.consumer_contract_routes.get_consumer", return_value=_consumer()
    ), patch("app.consumer_contract_routes.record_contract", return_value=_contract()):
        response = client.put(
            f"{_BASE}/consumers/billing-service/contract",
            json={
                "operations": [
                    {
                        "method": "GET",
                        "path": "/pets",
                        "fields": [{"location": "response", "path": "gone"}],
                    }
                ]
            },
        )
    assert response.status_code == 201
    assert [entry["reason"] for entry in response.json()["unresolved"]] == ["field-not-found"]


def test_an_empty_selection_is_refused_by_name() -> None:
    response = client.put(
        f"{_BASE}/consumers/billing-service/contract", json={"operations": []}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "consumer-empty-surface"


def test_a_client_cannot_supply_its_own_pointers() -> None:
    """The selection model forbids unknown keys, so a hand-written pointer never reaches the
    store — a stored surface always describes something the specification contains."""
    response = client.put(
        f"{_BASE}/consumers/billing-service/contract",
        json={
            "operations": [
                {"method": "GET", "path": "/pets", "pointer": "/paths/~1anything/get"}
            ]
        },
    )
    assert response.status_code == 422


def test_declaring_needs_the_edit_action(_spec_document) -> None:
    with patch(
        "app.consumer_contract_routes.enforce_permission", return_value="test-user-id"
    ) as guard, patch(
        "app.consumer_contract_routes.get_consumer", return_value=_consumer()
    ), patch("app.consumer_contract_routes.record_contract", return_value=_contract()):
        client.put(
            f"{_BASE}/consumers/billing-service/contract",
            json={"operations": [{"method": "GET", "path": "/pets"}]},
        )
    assert guard.call_args.args[3] == "edit"


# ===========================================================================
# Contract history
# ===========================================================================


def test_reading_the_current_contract_returns_the_stored_revision() -> None:
    with patch(
        "app.consumer_contract_routes.get_consumer", return_value=_consumer()
    ), patch("app.consumer_contract_routes.current_contract", return_value=_contract()):
        response = client.get(f"{_BASE}/consumers/billing-service/contract")
    assert response.status_code == 200
    assert response.json()["revision"] == 2


def test_reading_a_named_revision_asks_the_store_for_it() -> None:
    with patch(
        "app.consumer_contract_routes.get_consumer", return_value=_consumer()
    ), patch(
        "app.consumer_contract_routes.contract_revision",
        return_value=_contract(revision=1, is_current=False),
    ) as reader:
        response = client.get(f"{_BASE}/consumers/billing-service/contract?revision=1")
    assert response.status_code == 200
    assert response.json()["revision"] == 1
    assert reader.call_args.args[2] == 1


def test_the_revision_history_is_newest_first() -> None:
    with patch(
        "app.consumer_contract_routes.get_consumer", return_value=_consumer()
    ), patch(
        "app.consumer_contract_routes.contract_revisions",
        return_value=[_contract(revision=2), _contract(revision=1, is_current=False)],
    ):
        response = client.get(f"{_BASE}/consumers/billing-service/contract-revisions")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [entry["revision"] for entry in body["revisions"]] == [2, 1]


# ===========================================================================
# The Pact ingestion path
# ===========================================================================


def _pact_body(**overrides: Any) -> Dict[str, Any]:
    """A request body carrying a minimal pact."""
    import json

    pact = {
        "consumer": {"name": "Billing Service"},
        "provider": {"name": "Pets"},
        "interactions": [
            {
                "description": "list pets",
                "request": {"method": "GET", "path": "/pets"},
                "response": {"status": 200, "body": {"total": 3}},
            }
        ],
        "metadata": {"pactSpecification": {"version": "3.0.0"}},
    }
    body: Dict[str, Any] = {"pact": json.dumps(pact)}
    body.update(overrides)
    return body


def test_importing_a_pact_registers_the_consumer_and_writes_a_revision(
    _spec_document,
) -> None:
    with patch(
        "app.consumer_contract_routes.ensure_consumer", return_value=_consumer()
    ) as ensure, patch(
        "app.consumer_contract_routes.record_contract",
        return_value=_contract(source="pact"),
    ) as record:
        response = client.post(f"{_BASE}/consumer-pact-imports", json=_pact_body())
    assert response.status_code == 201
    body = response.json()
    assert body["consumer"]["slug"] == "billing-service"
    assert body["contract"]["source"] == "pact"
    assert ensure.call_args.kwargs["slug"] == "billing-service"
    assert record.call_args.kwargs["source"] == "pact"
    assert record.call_args.kwargs["source_digest"].startswith("sha256:")


def test_an_unresolvable_interaction_reaches_the_caller_on_the_import_response(
    _spec_document,
) -> None:
    import json

    pact = json.dumps(
        {
            "consumer": {"name": "Billing Service"},
            "interactions": [
                {
                    "description": "a retired call",
                    "request": {"method": "GET", "path": "/orders"},
                    "response": {"status": 200},
                }
            ],
        }
    )
    with patch(
        "app.consumer_contract_routes.ensure_consumer", return_value=_consumer()
    ), patch(
        "app.consumer_contract_routes.record_contract",
        return_value=_contract(
            source="pact",
            unresolved=[
                UnresolvedInteraction(reason="operation-not-found", message="gone")
            ],
            unresolved_count=1,
        ),
    ) as record:
        response = client.post(f"{_BASE}/consumer-pact-imports", json={"pact": pact})
    assert response.status_code == 201
    assert [entry["reason"] for entry in response.json()["unresolved"]] == [
        "operation-not-found"
    ]
    # And it was stored, not merely reported.
    assert [entry.reason for entry in record.call_args.kwargs["unresolved"]] == [
        "operation-not-found"
    ]


def test_a_pact_that_names_no_consumer_is_refused_unless_a_handle_is_supplied(
    _spec_document,
) -> None:
    import json

    pact = json.dumps({"interactions": []})
    response = client.post(f"{_BASE}/consumer-pact-imports", json={"pact": pact})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "consumer-invalid-slug"


def test_a_supplied_handle_overrides_the_documents_own_consumer_name(_spec_document) -> None:
    with patch(
        "app.consumer_contract_routes.ensure_consumer", return_value=_consumer()
    ) as ensure, patch(
        "app.consumer_contract_routes.record_contract", return_value=_contract(source="pact")
    ):
        client.post(
            f"{_BASE}/consumer-pact-imports", json=_pact_body(consumer_slug="checkout")
        )
    assert ensure.call_args.kwargs["slug"] == "checkout"


def test_a_malformed_pact_is_a_400_with_its_code() -> None:
    response = client.post(f"{_BASE}/consumer-pact-imports", json={"pact": "not json"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "consumer-pact-malformed"


def test_an_oversized_pact_is_a_413() -> None:
    from app.pact_contract_import import MAX_PACT_BYTES

    response = client.post(
        f"{_BASE}/consumer-pact-imports", json={"pact": "x" * (MAX_PACT_BYTES + 1)}
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == CODE_PACT_TOO_LARGE


def test_importing_needs_the_create_action(_spec_document) -> None:
    with patch(
        "app.consumer_contract_routes.enforce_permission", return_value="test-user-id"
    ) as guard, patch(
        "app.consumer_contract_routes.ensure_consumer", return_value=_consumer()
    ), patch(
        "app.consumer_contract_routes.record_contract", return_value=_contract(source="pact")
    ):
        client.post(f"{_BASE}/consumer-pact-imports", json=_pact_body())
    assert guard.call_args.args[2] == "consumer_contracts"
    assert guard.call_args.args[3] == "create"
