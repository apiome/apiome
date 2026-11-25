"""HTTP contract tests for ``POST …/pact-suites/…/pact-version/{sha}`` — PFX-3.1 (#6931).

The route of :mod:`app.pact_suite_routes` with the pact store faked:

* it needs ``pacts:view``; a denial is a 403 before the store is touched;
* the pact is read for the caller's tenant (from the credential, never the URL), so a pact of
  another workspace is a 404;
* an unknown pacticipant or pact version is a 404 with its code, a malformed reference a 400, a
  malformed SHA or option a 422;
* the response carries the pair, the pact version and a manifest that is byte-identical for the
  same pact version and options, whichever consumer version published it.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.pact_publication import CODE_PACT_NOT_FOUND, PactPublicationError, PactRecord, pact_content_sha
from app.pact_suite_routes import pact_suite_reference
from app.pacticipant import CODE_INVALID_SLUG, CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "session"}
_ROUTES = "app.pact_suite_routes"

_DOCUMENT: Dict[str, Any] = {
    "consumer": {"name": "Billing Service"},
    "provider": {"name": "Ledger API"},
    "interactions": [
        {
            "description": "get invoice",
            "providerStates": [{"name": "invoice 1042 exists"}],
            "request": {"method": "GET", "path": "/invoices/1042"},
            "response": {"status": 200, "body": {"id": 1042}},
        },
        {"description": "invoice created", "type": "Asynchronous/Messages", "contents": {}},
    ],
    "metadata": {"pactSpecification": {"version": "4.0"}},
}
_SHA = pact_content_sha(_DOCUMENT)
_URL = f"/v1/tenants/acme/pact-suites/provider/ledger-api/consumer/billing-service/pact-version/{_SHA}"


def _record(consumer_version: str = "2.0.0") -> PactRecord:
    return PactRecord(
        consumer_slug="billing-service",
        consumer_name="Billing Service",
        provider_slug="ledger-api",
        provider_name="Ledger API",
        consumer_version=consumer_version,
        sha=_SHA,
        content=_DOCUMENT,
        specification_version="4.0",
        interaction_count=2,
    )


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


def test_it_compiles_the_pact_version_for_the_callers_tenant(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_pact_by_sha", return_value=_record()) as read:
        response = client.post(_URL, json={})

    assert response.status_code == 200, response.text
    assert read.call_args.args[1:] == (_TENANT, "ledger-api", "billing-service", _SHA)
    assert allowed.call_args.args[2:] == (Resource.PACTS, Action.VIEW)
    payload = response.json()
    assert (payload["consumer"], payload["provider"], payload["pact_version_sha"]) == (
        "billing-service",
        "ledger-api",
        _SHA,
    )
    manifest = payload["manifest"]
    assert manifest["digest"].startswith("sha256:")
    assert manifest["pact"]["pact_version_sha"] == _SHA
    assert manifest["pact"]["consumer"] == "Billing Service"
    assert manifest["source"]["kind"] == "pact"
    assert manifest["source"]["reference"] == pact_suite_reference("ledger-api", "billing-service", _SHA)
    assert [case["source"] for case in manifest["cases"]] == ["pact_interaction"]
    assert manifest["cases"][0]["pact"]["provider_states"] == [{"name": "invoice 1042 exists", "params": {}}]
    assert [item["operation_key"] for item in manifest["unsupported"]] == ["/interactions/1"]


def test_the_tenant_comes_from_the_credential_not_the_url(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_pact_by_sha", return_value=_record()) as read:
        client.post(_URL.replace("/acme/", "/someone-else/"), json={})
    assert read.call_args.args[1] == _TENANT


def test_every_consumer_version_sharing_the_content_gets_the_same_suite(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_pact_by_sha", return_value=_record("2.0.0")):
        first = client.post(_URL, json={"options": {"interactions": ["get invoice"]}}).json()
    with patch(f"{_ROUTES}.get_pact_by_sha", return_value=_record("2.1.0")):
        second = client.post(_URL, json={"options": {"interactions": ["get invoice"]}}).json()
    assert first["manifest"] == second["manifest"]


def test_options_change_the_digest(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_pact_by_sha", return_value=_record()):
        every = client.post(_URL, json={}).json()["manifest"]
        narrowed = client.post(_URL, json={"options": {"max_interactions": 1}}).json()["manifest"]
    assert every["digest"] != narrowed["digest"]
    assert narrowed["pact"]["options"]["max_interactions"] == 1


def test_without_pacts_view_it_is_a_403_before_any_read() -> None:
    denied = HTTPException(status_code=403, detail="Permission denied: pacts:view")
    with patch(f"{_ROUTES}.enforce_permission", side_effect=denied), patch(
        f"{_ROUTES}.get_pact_by_sha"
    ) as read:
        response = client.post(_URL, json={})
    assert response.status_code == 403
    read.assert_not_called()


def test_a_credential_without_a_tenant_is_a_403(allowed: MagicMock) -> None:
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": "u"}
    with patch(f"{_ROUTES}.get_pact_by_sha") as read:
        response = client.post(_URL, json={})
    assert response.status_code == 403
    read.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PactPublicationError(CODE_PACT_NOT_FOUND, "no pact version"), 404),
        (PacticipantValidationError(CODE_NOT_FOUND, "no such pacticipant"), 404),
        (PacticipantValidationError(CODE_INVALID_SLUG, "bad slug"), 400),
    ],
)
def test_lookup_failures_keep_their_code(allowed: MagicMock, error: Exception, status: int) -> None:
    with patch(f"{_ROUTES}.get_pact_by_sha", side_effect=error):
        response = client.post(_URL, json={})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == error.code  # type: ignore[attr-defined]


def test_a_pact_of_another_workspace_is_not_found(allowed: MagicMock) -> None:
    # The store reads by the caller's tenant: another workspace's pact simply is not there.
    missing = PactPublicationError(CODE_PACT_NOT_FOUND, "no pact version")
    with patch(f"{_ROUTES}.get_pact_by_sha", side_effect=missing) as read:
        response = client.post(_URL, json={})
    assert response.status_code == 404
    assert read.call_args.args[1] == _TENANT


@pytest.mark.parametrize(
    ("url", "body"),
    [
        (_URL.replace(_SHA, "not-a-sha"), {}),
        (_URL, {"options": {"max_interactions": 0}}),
        (_URL, {"options": {"seed": 1}}),
        (_URL, {"unknown": True}),
    ],
)
def test_malformed_input_is_a_422(allowed: MagicMock, url: str, body: Dict[str, Any]) -> None:
    with patch(f"{_ROUTES}.get_pact_by_sha") as read:
        response = client.post(url, json=body)
    assert response.status_code == 422
    read.assert_not_called()


def test_the_body_may_be_omitted(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_pact_by_sha", return_value=_record()):
        response = client.post(_URL)
    assert response.status_code == 200, response.text
