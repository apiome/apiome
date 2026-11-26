"""HTTP contract tests for the Postman export of a pact — PFX-4.7 (#6944).

``POST /v1/tenants/{t}/pact-postman-collections`` with the store faked:

* it needs ``pacts:view``; a denial is a 403 before anything is read;
* a stored pact is read in the caller's tenant (from the credential, never the URL) by version,
  SHA, tag, branch or latest;
* an inline pact is checked (shape, size) and named from its own document;
* every bad request is a 4xx with a code and reason: nothing named, two selections, an inline pact
  with a selection, a bad base URL, an unknown pact or pacticipant, a pact with no HTTP interaction.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.pact_postman_routes import CODE_EXPORT_INVALID, CODE_NO_HTTP_INTERACTIONS
from app.pact_publication import CODE_PACT_NOT_FOUND, PactPublicationError, PactRecord
from app.pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "session"}
_PATH = "/v1/tenants/acme/pact-postman-collections"
_ROUTES = "app.pact_postman_routes"


def _pact() -> Dict[str, Any]:
    return {
        "consumer": {"name": "Web App"},
        "provider": {"name": "Orders API"},
        "interactions": [
            {
                "description": "get order 42",
                "providerState": "order 42 exists",
                "request": {"method": "GET", "path": "/orders/42"},
                "response": {"status": 200, "headers": {"Content-Type": "application/json"}, "body": {"id": 42}},
            },
        ],
        "messages": [{"description": "order shipped", "contents": {"id": 42}}],
        "metadata": {"pactSpecification": {"version": "3.0.0"}},
    }


def _record(**overrides: Any) -> PactRecord:
    payload: Dict[str, Any] = {
        "consumer_slug": "web-app",
        "consumer_name": "Web App",
        "provider_slug": "orders-api",
        "provider_name": "Orders API",
        "consumer_version": "abc123",
        "sha": "ab" * 32,
        "content": _pact(),
        "specification_version": "3.0.0",
        "interaction_count": 2,
    }
    payload.update(overrides)
    return PactRecord(**payload)


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


# --- RBAC -------------------------------------------------------------------------------------


def test_it_needs_pacts_view_before_reading_anything() -> None:
    denial = HTTPException(status_code=403, detail="Permission denied")
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=denial) as enforce,
        patch(f"{_ROUTES}.get_latest_pact") as latest,
    ):
        response = client.post(_PATH, json={"provider": "orders-api", "consumer": "web-app"})
    assert response.status_code == 403
    resource, action = enforce.call_args.args[2:4]
    assert (resource, action) == (Resource.PACTS, Action.VIEW)
    latest.assert_not_called()


# --- stored pacts -----------------------------------------------------------------------------


def test_the_latest_stored_pact_is_read_in_the_callers_tenant(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_latest_pact", return_value=_record()) as latest:
        response = client.post(_PATH, json={"provider": "orders-api", "consumer": "web-app", "baseUrl": "http://x:8080"})
    assert response.status_code == 200, response.text
    args, kwargs = latest.call_args
    assert args[1:] == (_TENANT, "orders-api", "web-app")
    assert kwargs == {"tag": None, "branch": None}
    body = response.json()
    assert body["pact"] == {
        "consumer": "Web App",
        "provider": "Orders API",
        "consumerVersion": "abc123",
        "pactVersionSha": "ab" * 32,
        "specificationVersion": "3.0.0",
    }
    assert body["counts"] == {"interactions": 2, "exported": 1, "leftOut": 1}
    assert body["collection"]["info"]["name"] == "Pact: Web App → Orders API"
    assert "version abc123" in body["collection"]["info"]["description"]
    assert body["collection"]["variable"] == [{"key": "baseUrl", "value": "http://x:8080"}]
    assert [notice["code"] for notice in body["notices"]] == [
        "pact-postman-message-left-out",
        "pact-postman-provider-states",
    ]


@pytest.mark.parametrize(
    "selection, reader, expected_args, expected_kwargs",
    [
        ({"consumerVersion": "1.2.3"}, "get_pact", ("orders-api", "web-app", "1.2.3"), {}),
        ({"pactVersionSha": "cd" * 32}, "get_pact_by_sha", ("orders-api", "web-app", "cd" * 32), {}),
        ({"tag": "prod"}, "get_latest_pact", ("orders-api", "web-app"), {"tag": "prod", "branch": None}),
        ({"branch": "main"}, "get_latest_pact", ("orders-api", "web-app"), {"tag": None, "branch": "main"}),
    ],
)
def test_each_selection_reads_its_pact(
    allowed: MagicMock, selection: Dict[str, str], reader: str, expected_args: tuple, expected_kwargs: dict
) -> None:
    with patch(f"{_ROUTES}.{reader}", return_value=_record()) as read:
        response = client.post(_PATH, json={"provider": "orders-api", "consumer": "web-app", **selection})
    assert response.status_code == 200, response.text
    assert read.call_args.args[1] == _TENANT
    assert read.call_args.args[2:] == expected_args
    assert read.call_args.kwargs == expected_kwargs


@pytest.mark.parametrize(
    "error, status, code",
    [
        (PactPublicationError(CODE_PACT_NOT_FOUND, "no pact between …"), 404, CODE_PACT_NOT_FOUND),
        (PacticipantValidationError(CODE_NOT_FOUND, "no pacticipant 'nope'"), 404, CODE_NOT_FOUND),
    ],
)
def test_an_unknown_pact_or_pacticipant_is_a_404(allowed: MagicMock, error: Exception, status: int, code: str) -> None:
    with patch(f"{_ROUTES}.get_latest_pact", side_effect=error):
        response = client.post(_PATH, json={"provider": "orders-api", "consumer": "nope"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


# --- inline pacts -----------------------------------------------------------------------------


def test_an_inline_pact_is_exported_without_reading_the_store(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_latest_pact") as latest:
        response = client.post(_PATH, json={"pact": _pact(), "tests": False})
    assert response.status_code == 200, response.text
    latest.assert_not_called()
    body = response.json()
    assert body["pact"]["consumer"] == "Web App"
    assert body["pact"]["provider"] == "Orders API"
    assert len(body["pact"]["pactVersionSha"]) == 64
    assert "consumerVersion" not in body["pact"]
    assert "event" not in body["collection"]["item"][0]
    assert body["collection"]["variable"][0]["value"] == ""


def test_an_inline_pact_can_be_renamed(allowed: MagicMock) -> None:
    response = client.post(_PATH, json={"pact": _pact(), "consumer": "web", "provider": "orders"})
    assert response.json()["collection"]["info"]["name"] == "Pact: web → orders"


def test_an_inline_document_that_is_not_a_pact_is_refused(allowed: MagicMock) -> None:
    response = client.post(_PATH, json={"pact": {"openapi": "3.1.0"}})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "pact-invalid"


def test_an_inline_pact_over_the_size_limit_is_refused(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.settings") as settings:
        settings.pact_max_bytes = 10
        response = client.post(_PATH, json={"pact": _pact()})
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "pact-too-large"


# --- refusals ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body, reason",
    [
        ({}, "name the stored pact"),
        ({"provider": "orders-api"}, "name the stored pact"),
        ({"provider": "orders-api", "consumer": "web-app", "tag": "a", "branch": "b"}, "choose one of tag, branch"),
        ({"pact": _pact(), "consumerVersion": "1"}, "cannot be combined with consumerVersion"),
        ({"provider": "p", "consumer": "c", "baseUrl": "ftp://x"}, "absolute http or https URL"),
        ({"provider": "p", "consumer": "c", "baseUrl": "localhost:8080"}, "absolute http or https URL"),
    ],
)
def test_bad_requests_are_refused_with_the_reason(allowed: MagicMock, body: Dict[str, Any], reason: str) -> None:
    with patch(f"{_ROUTES}.get_latest_pact") as latest:
        response = client.post(_PATH, json=body)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == CODE_EXPORT_INVALID
    assert reason in detail["message"]
    latest.assert_not_called()


def test_an_unknown_field_is_refused(allowed: MagicMock) -> None:
    response = client.post(_PATH, json={"provider": "p", "consumer": "c", "format": "v2.0"})
    assert response.status_code == 422


def test_a_pact_with_no_http_interaction_is_refused_with_its_notices(allowed: MagicMock) -> None:
    pact = {"consumer": {"name": "W"}, "provider": {"name": "O"}, "messages": [{"description": "evt", "contents": {}}]}
    response = client.post(_PATH, json={"pact": pact})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == CODE_NO_HTTP_INTERACTIONS
    assert [notice["code"] for notice in detail["notices"]] == ["pact-postman-message-left-out"]
