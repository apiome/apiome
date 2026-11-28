"""HTTP tests for the declared-surface Pact export — PFX-2.6 (#6930).

``GET …/consumers/{c}/pact`` and ``POST …/consumers/{c}/pact/publish``. The registry, the
broker store and the specification renderer are faked; the generator itself is covered by
``test_consumer_pact_export``. What is asserted is the endpoints' own contract:

* RBAC: export needs ``consumer_contracts:view`` **and** ``pacts:view``; publish needs
  ``consumer_contracts:view`` **and** ``pacts:create``; a denial is a 403 and nothing is stored;
* tenant isolation: every lookup is made with the credential's tenant, never the URL's, and a
  consumer another tenant owns is a 404;
* every refusal has its status and stable code: non-picker revision, no specification version,
  no interaction (with findings), ambiguous provider, unrenderable specification, publish
  conflict, malformed version;
* publish hands the generated pact to the broker store with the version, branch and tags.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.consumer_contract import (
    CODE_CONSUMER_NOT_FOUND,
    CODE_CONTRACT_NOT_FOUND,
    ConsumerContractOperation,
    ConsumerContractRecord,
    ConsumerContractSurface,
    ConsumerRecord,
    ConsumerValidationError,
)
from app.consumer_pact_export_store import CODE_PROVIDER_AMBIGUOUS, PactNames
from app.main import app
from app.pact_publication import CODE_PACT_CONFLICT, PactPublicationError
from app.pacticipant import PacticipantValidationError
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "test-tenant-id"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "jwt"}
_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
_VERSION_ID = "22222222-2222-4222-8222-222222222222"
_CONSUMER_ID = "33333333-3333-4333-8333-333333333333"
_BASE = "/v1/tenants/acme/projects/pets/consumers/web-app"
_MODULE = "app.consumer_pact_export_routes"

_DOCUMENT: Dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"total": {"type": "integer", "example": 3}},
                                }
                            }
                        },
                    }
                },
            }
        }
    },
}


def _consumer() -> ConsumerRecord:
    """The stored consumer."""
    return ConsumerRecord(id=_CONSUMER_ID, tenant_id=_TENANT, project_id=_PROJECT_ID, slug="web-app", name="Web App")


def _contract(**overrides: Any) -> ConsumerContractRecord:
    """A picker revision declaring ``GET /pets`` → ``total``."""
    from app.consumer_contract import ConsumerContractField

    payload: Dict[str, Any] = {
        "id": "44444444-4444-4444-8444-444444444444",
        "consumer_id": _CONSUMER_ID,
        "revision": 2,
        "source": "manual",
        "version_id": _VERSION_ID,
        "version_label": "1.0.0",
        "surface": ConsumerContractSurface(
            operations=[
                ConsumerContractOperation(
                    method="get",
                    path="/pets",
                    pointer="/paths/~1pets/get",
                    operation_id="listPets",
                    fields=[
                        ConsumerContractField(
                            pointer="/paths/~1pets/get/responses/200/content/application~1json/schema/properties/total",
                            schema_pointer="/paths/~1pets/get/responses/200/content/application~1json/schema/properties/total",
                            location="response",
                            status="200",
                            media_type="application/json",
                            path="total",
                        )
                    ],
                )
            ]
        ),
    }
    payload.update(overrides)
    return ConsumerContractRecord(**payload)


class _Registry:
    """The faked registry and broker, recording what each was asked."""

    def __init__(self) -> None:
        self.permission = MagicMock(return_value="test-user-id")
        self.project = MagicMock(return_value={"id": _PROJECT_ID, "slug": "pets", "name": "Pets"})
        self.consumer = MagicMock(return_value=_consumer())
        self.current = MagicMock(return_value=_contract())
        self.revision = MagicMock(return_value=_contract(revision=1))
        self.version = MagicMock(return_value={"id": _VERSION_ID, "version_id": "1.0.0", "project_id": _PROJECT_ID})
        self.names = MagicMock(return_value=PactNames("web-app", "pets-api", False, True))
        self.render = MagicMock(return_value=_DOCUMENT)
        self.publish = MagicMock(return_value=MagicMock(name="outcome"))
        self.events = MagicMock(return_value=[])
        self.compare = MagicMock(return_value=None)
        self.result = MagicMock(return_value={"notices": [{"type": "success", "text": "published"}]})


@pytest.fixture
def registry():
    """Authenticate, and fake every collaborator of the two routes."""
    fake = _Registry()
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    with (
        patch(f"{_MODULE}.enforce_permission", fake.permission),
        patch(f"{_MODULE}.resolve_project", fake.project),
        patch(f"{_MODULE}.get_consumer", fake.consumer),
        patch(f"{_MODULE}.current_contract", fake.current),
        patch(f"{_MODULE}.contract_revision", fake.revision),
        patch(f"{_MODULE}.resolve_version", fake.version),
        patch(f"{_MODULE}.resolve_pact_names", fake.names),
        patch("app.consumer_contract_routes.openapi_for_revision", fake.render),
        patch(f"{_MODULE}.publish_pacts", fake.publish),
        patch(f"{_MODULE}.fire_publish_events", fake.events),
        patch(f"{_MODULE}.compare_published_pacts", fake.compare),
        patch(f"{_MODULE}._publish_result", fake.result),
        patch(f"{_MODULE}._enforce_publish_budget"),
    ):
        yield fake
    app.dependency_overrides.clear()


def _deny(resource: Resource, action: Action):
    """An ``enforce_permission`` that refuses one grant."""

    def check(_db: Any, _auth: Any, wanted_resource: Resource, wanted_action: Action, **_kw: Any) -> str:
        if (wanted_resource, wanted_action) == (resource, action):
            raise HTTPException(status_code=403, detail="forbidden")
        return "test-user-id"

    return check


def _grants(fake: _Registry) -> List[tuple]:
    """The (resource, action) pairs a request checked."""
    return [(c.args[2], c.args[3]) for c in fake.permission.call_args_list]


# ===========================================================================
# Export
# ===========================================================================


def test_export_returns_the_pact_and_its_report(registry: _Registry) -> None:
    response = client.get(f"{_BASE}/pact")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["consumer_name"] == "web-app"
    assert body["provider_name"] == "pets-api"
    assert body["provider_pacticipant_bound"] is True
    assert body["revision"] == 2
    assert body["version_record_id"] == _VERSION_ID
    assert body["interaction_count"] == 1
    assert (body["placeholder_count"], body["omitted_count"], body["findings"]) == (0, 0, [])
    interaction = body["pact"]["interactions"][0]
    assert interaction["response"]["body"]["content"] == {"total": 3}
    assert body["pact"]["metadata"]["pactSpecification"]["version"] == "4.0"
    (operation,) = body["operations"]
    assert operation["interactions"] == [0]
    assert (operation["placeholder_count"], operation["omitted_count"]) == (0, 0)
    assert operation["method"] == interaction["request"]["method"]


def test_export_needs_consumer_contracts_view_and_pacts_view(registry: _Registry) -> None:
    client.get(f"{_BASE}/pact")
    assert _grants(registry) == [
        (Resource.CONSUMER_CONTRACTS, Action.VIEW),
        (Resource.PACTS, Action.VIEW),
    ]


@pytest.mark.parametrize("denied", [(Resource.PACTS, Action.VIEW), (Resource.CONSUMER_CONTRACTS, Action.VIEW)])
def test_export_is_403_without_either_grant(registry: _Registry, denied: tuple) -> None:
    registry.permission.side_effect = _deny(*denied)
    response = client.get(f"{_BASE}/pact")
    assert response.status_code == 403
    registry.consumer.assert_not_called()


def test_every_lookup_uses_the_credentials_tenant(registry: _Registry) -> None:
    client.get(f"{_BASE}/pact")
    registry.project.assert_called_once_with(_TENANT, "pets")
    registry.consumer.assert_called_once_with(_TENANT, _PROJECT_ID, "web-app")
    registry.current.assert_called_once_with(_TENANT, _CONSUMER_ID)
    registry.version.assert_called_once_with(_TENANT, _PROJECT_ID, _VERSION_ID)
    assert registry.names.call_args.args[1] == _TENANT


def test_a_consumer_of_another_tenant_is_404(registry: _Registry) -> None:
    registry.consumer.side_effect = ConsumerValidationError(CODE_CONSUMER_NOT_FOUND, "no consumer 'web-app'")
    response = client.get(f"{_BASE}/pact")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_CONSUMER_NOT_FOUND


def test_a_credential_without_a_tenant_is_403(registry: _Registry) -> None:
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": "u"}
    assert client.get(f"{_BASE}/pact").status_code == 403


def test_a_consumer_without_a_contract_is_404(registry: _Registry) -> None:
    registry.current.side_effect = ConsumerValidationError(CODE_CONTRACT_NOT_FOUND, "no contract")
    response = client.get(f"{_BASE}/pact")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_CONTRACT_NOT_FOUND


def test_a_specific_revision_is_read_when_asked(registry: _Registry) -> None:
    response = client.get(f"{_BASE}/pact", params={"revision": 1})
    assert response.json()["revision"] == 1
    registry.revision.assert_called_once_with(_TENANT, _CONSUMER_ID, 1)
    registry.current.assert_not_called()


def test_the_provider_name_is_passed_through(registry: _Registry) -> None:
    client.get(f"{_BASE}/pact", params={"provider": "pets-v2"})
    assert registry.names.call_args.args[4] == "pets-v2"


@pytest.mark.parametrize("source", ["pact", "agent"])
def test_a_revision_not_from_the_picker_is_422(registry: _Registry, source: str) -> None:
    registry.current.return_value = _contract(source=source)
    response = client.get(f"{_BASE}/pact")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "consumer-pact-export-unsupported-source"


def test_a_revision_without_a_specification_version_is_422(registry: _Registry) -> None:
    registry.current.return_value = _contract(version_id=None)
    response = client.get(f"{_BASE}/pact")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "consumer-pact-export-no-version"


def test_a_revision_that_yields_no_interaction_is_422_with_its_findings(registry: _Registry) -> None:
    registry.current.return_value = _contract(
        surface=ConsumerContractSurface(
            operations=[ConsumerContractOperation(method="delete", path="/pets", pointer="/paths/~1pets/delete")]
        )
    )
    response = client.get(f"{_BASE}/pact")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "consumer-pact-export-empty"
    assert [f["reason"] for f in detail["findings"]] == ["operation-not-found"]


def test_an_ambiguous_provider_is_409(registry: _Registry) -> None:
    registry.names.side_effect = ConsumerValidationError(CODE_PROVIDER_AMBIGUOUS, "several")
    response = client.get(f"{_BASE}/pact")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == CODE_PROVIDER_AMBIGUOUS


def test_an_unrenderable_specification_is_422(registry: _Registry) -> None:
    registry.render.side_effect = RuntimeError("boom")
    response = client.get(f"{_BASE}/pact")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "consumer-specification-unavailable"


# ===========================================================================
# Publish
# ===========================================================================


def _publish(body: Optional[Dict[str, Any]] = None) -> Any:
    """POST the publish route."""
    return client.post(f"{_BASE}/pact/publish", json=body or {"consumer_version": "abc123"})


def test_publish_stores_the_generated_pact_for_the_version(registry: _Registry) -> None:
    response = _publish({"consumer_version": "abc123", "branch": "main", "tags": ["prod"], "build_url": "https://ci/1"})
    assert response.status_code == 200, response.text
    kwargs = registry.publish.call_args.kwargs
    assert registry.publish.call_args.args[1] == _TENANT
    assert kwargs["consumer_name"] == "web-app"
    assert kwargs["version_number"] == "abc123"
    assert (kwargs["branch"], kwargs["tags"], kwargs["build_url"]) == ("main", ["prod"], "https://ci/1")
    (pact,) = kwargs["pacts"]
    assert (pact.consumer_name, pact.provider_name, pact.interaction_count) == ("web-app", "pets-api", 1)
    body = response.json()
    assert body["publish"] == {"notices": [{"type": "success", "text": "published"}]}
    assert body["interaction_count"] == 1
    registry.events.assert_called_once()
    registry.compare.assert_called_once()


def test_publish_needs_pacts_create(registry: _Registry) -> None:
    _publish()
    assert _grants(registry) == [
        (Resource.CONSUMER_CONTRACTS, Action.VIEW),
        (Resource.PACTS, Action.CREATE),
    ]
    registry.permission.side_effect = _deny(Resource.PACTS, Action.CREATE)
    registry.publish.reset_mock()
    assert _publish().status_code == 403
    registry.publish.assert_not_called()


def test_publish_requires_a_consumer_version(registry: _Registry) -> None:
    assert client.post(f"{_BASE}/pact/publish", json={}).status_code == 422
    registry.publish.assert_not_called()


def test_a_changed_pact_for_a_published_version_is_409(registry: _Registry) -> None:
    registry.publish.side_effect = PactPublicationError(CODE_PACT_CONFLICT, "fixed once published")
    response = _publish()
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == CODE_PACT_CONFLICT
    registry.events.assert_not_called()


def test_a_malformed_version_is_400(registry: _Registry) -> None:
    registry.publish.side_effect = PacticipantValidationError("pacticipant-invalid-version", "bad version")
    response = _publish({"consumer_version": "bad version"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "pacticipant-invalid-version"


def test_publish_refuses_a_non_picker_revision_before_storing(registry: _Registry) -> None:
    registry.current.return_value = _contract(source="pact")
    assert _publish().status_code == 422
    registry.publish.assert_not_called()
