"""Consumer usage projection — DCW-0.5 (private-suite #2422).

Covers the pure projection (:func:`app.consumer_usage.project_consumer_usage`) and its route
(``GET /v1/tenants/{tenant}/projects/{project}/consumer-usage``): only contracts resolved against
the requested revision are projected, counts never depend on the reader, and consumer names are
attached only for a reader holding ``consumer_contracts:view``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.consumer_contract import (
    CODE_VERSION_NOT_FOUND,
    ConsumerContractField,
    ConsumerContractOperation,
    ConsumerContractRecord,
    ConsumerContractSurface,
    ConsumerRecord,
    ConsumerSummary,
    ConsumerValidationError,
)
from app.consumer_usage import project_consumer_usage
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}
_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
_VERSION_ID = "22222222-2222-4222-8222-222222222222"
_OTHER_VERSION_ID = "55555555-5555-4555-8555-555555555555"
_BASE = "/v1/tenants/acme/projects/pets"
_LIST = "/paths/~1pets/get"
_READ = "/paths/~1pets~1{petId}/get"
_TOTAL = f"{_LIST}/responses/200/content/application~1json/schema/properties/total"
_NAME = f"{_READ}/responses/200/content/application~1json/schema/properties/name"


def _field(pointer: str, schema_pointer: str) -> ConsumerContractField:
    """A declared response field."""
    return ConsumerContractField(
        pointer=pointer,
        schema_pointer=schema_pointer,
        location="response",
        status="200",
        media_type="application/json",
        path=pointer.rsplit("/", 1)[-1],
    )


def _operation(pointer: str, path: str, fields: List[ConsumerContractField]) -> ConsumerContractOperation:
    """A declared GET operation."""
    return ConsumerContractOperation(method="get", path=path, pointer=pointer, fields=fields)


def _summary(
    index: int,
    operations: Optional[List[ConsumerContractOperation]],
    version_id: str = _VERSION_ID,
) -> ConsumerSummary:
    """A consumer with a current contract, or with none when ``operations`` is ``None``."""
    consumer_id = f"3333333{index}-3333-4333-8333-333333333333"
    consumer = ConsumerRecord(
        id=consumer_id,
        tenant_id="test-tenant-id",
        project_id=_PROJECT_ID,
        slug=f"consumer-{index}",
        name=f"Consumer {index}",
        metadata={},
    )
    contract = None
    if operations is not None:
        contract = ConsumerContractRecord(
            id=f"4444444{index}-4444-4444-8444-444444444444",
            consumer_id=consumer_id,
            revision=1,
            is_current=True,
            source="manual",
            version_id=version_id,
            version_label="1.0.0",
            surface=ConsumerContractSurface(operations=operations),
            operation_count=len(operations),
            field_count=sum(len(op.fields) for op in operations),
            unresolved=[],
            unresolved_count=0,
        )
    return ConsumerSummary(consumer=consumer, contract=contract)


def _registry() -> List[ConsumerSummary]:
    """Two consumers on this version, one on another version, and one with no contract."""
    return [
        _summary(
            1,
            [
                _operation(_LIST, "/pets", [_field(_TOTAL, "/components/schemas/PetList/properties/total")]),
                _operation(_READ, "/pets/{petId}", [_field(_NAME, "/components/schemas/Pet/properties/name")]),
            ],
        ),
        _summary(
            2, [_operation(_LIST, "/pets", [_field(_TOTAL, "/components/schemas/PetList/properties/total")])]
        ),
        _summary(3, [_operation(_LIST, "/pets", [])], version_id=_OTHER_VERSION_ID),
        _summary(4, None),
    ]


# ===========================================================================
# Projection
# ===========================================================================


def test_only_contracts_resolved_against_the_version_are_projected() -> None:
    usage = project_consumer_usage(
        _registry(), version_record_id=_VERSION_ID, version_label="1.0.0", consumers_visible=True
    )
    assert usage.consumer_count == 2
    assert usage.other_version_consumer_count == 1
    assert usage.undeclared_consumer_count == 1
    by_pointer = {op.pointer: op for op in usage.operations}
    assert by_pointer[_LIST].consumer_count == 2
    assert by_pointer[_READ].consumer_count == 1


def test_fields_and_component_schemas_carry_their_own_counts() -> None:
    usage = project_consumer_usage(
        _registry(), version_record_id=_VERSION_ID, version_label="1.0.0", consumers_visible=True
    )
    list_op = next(op for op in usage.operations if op.pointer == _LIST)
    assert [(f.pointer, f.consumer_count) for f in list_op.fields] == [(_TOTAL, 2)]
    assert list_op.fields[0].schema_pointer == "/components/schemas/PetList/properties/total"
    assert [(s.schema_pointer, s.consumer_count) for s in usage.schemas] == [
        ("/components/schemas/Pet", 1),
        ("/components/schemas/PetList", 2),
    ]


def test_a_reader_allowed_to_see_names_gets_them_ordered_by_handle() -> None:
    usage = project_consumer_usage(
        _registry(), version_record_id=_VERSION_ID, version_label="1.0.0", consumers_visible=True
    )
    list_op = next(op for op in usage.operations if op.pointer == _LIST)
    assert usage.consumers_visible is True
    assert [ref.slug for ref in list_op.consumers or []] == ["consumer-1", "consumer-2"]


def test_a_restricted_reader_gets_the_same_counts_and_no_names() -> None:
    visible = project_consumer_usage(
        _registry(), version_record_id=_VERSION_ID, version_label="1.0.0", consumers_visible=True
    )
    hidden = project_consumer_usage(
        _registry(), version_record_id=_VERSION_ID, version_label="1.0.0", consumers_visible=False
    )
    assert hidden.consumers_visible is False
    assert hidden.consumer_count == visible.consumer_count
    assert [op.consumer_count for op in hidden.operations] == [op.consumer_count for op in visible.operations]
    assert all(op.consumers is None for op in hidden.operations)
    assert all(f.consumers is None for op in hidden.operations for f in op.fields)
    assert all(s.consumers is None for s in hidden.schemas)
    assert "consumer-1" not in hidden.model_dump_json()


def test_a_consumer_declaring_an_operation_twice_is_counted_once() -> None:
    twice = _summary(
        1,
        [
            _operation(_LIST, "/pets", [_field(_TOTAL, _TOTAL)]),
            _operation(_LIST, "/pets", [_field(_TOTAL, _TOTAL)]),
        ],
    )
    usage = project_consumer_usage(
        [twice], version_record_id=_VERSION_ID, version_label=None, consumers_visible=True
    )
    assert usage.operations[0].consumer_count == 1
    assert usage.operations[0].fields[0].consumer_count == 1


def test_an_inline_field_reaches_no_component_schema() -> None:
    inline = _summary(1, [_operation(_LIST, "/pets", [_field(_TOTAL, _TOTAL)])])
    usage = project_consumer_usage(
        [inline], version_record_id=_VERSION_ID, version_label=None, consumers_visible=True
    )
    assert usage.schemas == []


def test_an_empty_registry_projects_nothing_and_says_so() -> None:
    usage = project_consumer_usage(
        [], version_record_id=_VERSION_ID, version_label="1.0.0", consumers_visible=True
    )
    assert (usage.consumer_count, usage.operations, usage.schemas) == (0, [], [])


# ===========================================================================
# Route
# ===========================================================================


def _project() -> Dict[str, Any]:
    """A resolved project row."""
    return {"id": _PROJECT_ID, "slug": "pets", "name": "Pets"}


def _version() -> Dict[str, Any]:
    """A resolved versions row."""
    return {"id": _VERSION_ID, "version_id": "1.0.0", "project_id": _PROJECT_ID}


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request and resolve project, version and registry."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    with patch(
        "app.consumer_contract_routes.enforce_permission", return_value="test-user-id"
    ), patch(
        "app.consumer_contract_routes.resolve_project", return_value=_project()
    ), patch(
        "app.consumer_contract_routes.resolve_version", return_value=_version()
    ), patch(
        "app.consumer_contract_routes.list_consumer_summaries", return_value=_registry()
    ):
        yield
    app.dependency_overrides.clear()


def test_the_route_needs_only_projects_view() -> None:
    with patch(
        "app.consumer_contract_routes.enforce_permission", return_value="test-user-id"
    ) as guard, patch("app.consumer_contract_routes.has_permission", return_value=True):
        response = client.get(f"{_BASE}/consumer-usage?version=1.0.0")
    assert response.status_code == 200
    assert guard.call_args.args[2:] == ("projects", "view")


def test_a_reader_with_consumer_contracts_view_sees_names() -> None:
    with patch("app.consumer_contract_routes.has_permission", return_value=True):
        body = client.get(f"{_BASE}/consumer-usage").json()
    assert body["consumers_visible"] is True
    assert body["version_record_id"] == _VERSION_ID
    assert body["consumer_count"] == 2
    list_op = next(op for op in body["operations"] if op["pointer"] == _LIST)
    assert [c["slug"] for c in list_op["consumers"]] == ["consumer-1", "consumer-2"]


def test_a_reader_without_consumer_contracts_view_sees_counts_only() -> None:
    with patch("app.consumer_contract_routes.has_permission", return_value=False):
        response = client.get(f"{_BASE}/consumer-usage")
    body = response.json()
    assert response.status_code == 200
    assert body["consumers_visible"] is False
    assert body["consumer_count"] == 2
    assert all(op["consumers"] is None for op in body["operations"])
    assert "Consumer 1" not in response.text


def test_an_unreadable_grant_hides_names_rather_than_failing() -> None:
    with patch("app.consumer_contract_routes.has_permission", side_effect=RuntimeError("db down")):
        response = client.get(f"{_BASE}/consumer-usage")
    assert response.status_code == 200
    assert response.json()["consumers_visible"] is False


def test_a_caller_without_projects_view_gets_a_403_and_the_registry_is_untouched() -> None:
    with patch(
        "app.consumer_contract_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="denied"),
    ), patch("app.consumer_contract_routes.list_consumer_summaries") as store:
        response = client.get(f"{_BASE}/consumer-usage")
    assert response.status_code == 403
    assert not store.called


def test_an_unknown_version_is_a_404_with_its_stable_code() -> None:
    with patch(
        "app.consumer_contract_routes.resolve_version",
        side_effect=ConsumerValidationError(CODE_VERSION_NOT_FOUND, "no version '9.9.9'"),
    ):
        response = client.get(f"{_BASE}/consumer-usage?version=9.9.9")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_VERSION_NOT_FOUND
