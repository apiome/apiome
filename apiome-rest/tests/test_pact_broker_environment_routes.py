"""HTTP contract tests for environments and deployments — PFX-1.5 (#6918).

The routes of :mod:`app.pact_broker_environment_routes`, with the store faked
(``test_pact_environment_db`` runs them against the real schema):

* every route is gated on ``pacts`` (view / create / edit / delete) before the store is touched;
* environments, deployments and releases render in the Pact Broker's shape, with the links the
  ``pact-broker`` CLI follows (``pb:environments`` named per environment,
  ``pb:currently-deployed-deployed-versions``, ``self`` on every deployment);
* recording answers ``201`` with ``Location``, or ``200`` when nothing new was recorded;
* the ``applicationInstance`` query distinguishes "no filter" from "the unnamed instance";
* refusals map to their status (404, 409, 422 with a pointer);
* the index links ``pb:environments`` and ``pb:environment``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_environment import (
    CODE_DEPLOYED_VERSION_NOT_FOUND,
    CODE_ENVIRONMENT_INVALID,
    CODE_ENVIRONMENT_NAME_TAKEN,
    CODE_ENVIRONMENT_NOT_FOUND,
    DeployedVersionRecord,
    EnvironmentRecord,
    ReleasedVersionRecord,
)
from app.pact_environment_store import UNSPECIFIED
from app.pact_publication import PactPublicationError
from app.pacticipant import CODE_VERSION_NOT_FOUND, PacticipantValidationError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "api_key"}
_ROOT = "http://testserver/v1/tenants/acme/pact-broker"
_BASE = "/v1/tenants/acme/pact-broker"
_ROUTES = "app.pact_broker_environment_routes"
_ENV = "44444444-4444-4444-8444-444444444444"
_DEPLOYED = "55555555-5555-4555-8555-555555555555"
_RELEASED = "66666666-6666-4666-8666-666666666666"
_VERSION = f"{_BASE}/pacticipants/ledger-api/versions/4f1e2d0"

_PRODUCTION = EnvironmentRecord(
    id=_ENV,
    name="production",
    display_name="Production",
    production=True,
    contract_required=True,
    contacts=[{"name": "Team Ledger"}],
    created_at="2026-11-24T10:00:00+00:00",
    updated_at="2026-11-24T10:00:00+00:00",
)


def _deployed(**overrides: Any) -> DeployedVersionRecord:
    payload: Dict[str, Any] = {
        "id": _DEPLOYED,
        "pacticipant_slug": "ledger-api",
        "pacticipant_name": "Ledger API",
        "version_number": "4f1e2d0",
        "environment": _PRODUCTION,
        "application_instance": "eu-1",
        "currently_deployed": True,
        "created_at": "2026-11-24T11:00:00+00:00",
    }
    payload.update(overrides)
    return DeployedVersionRecord(**payload)


def _released(**overrides: Any) -> ReleasedVersionRecord:
    payload: Dict[str, Any] = {
        "id": _RELEASED,
        "pacticipant_slug": "ledger-api",
        "pacticipant_name": "Ledger API",
        "version_number": "4f1e2d0",
        "environment": _PRODUCTION,
        "created_at": "2026-11-24T11:00:00+00:00",
        "updated_at": "2026-11-24T11:00:00+00:00",
    }
    payload.update(overrides)
    return ReleasedVersionRecord(**payload)


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    """Every permission granted, in both broker route modules."""
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce,
        patch("app.pact_broker_routes.enforce_permission", return_value="test-user-id"),
    ):
        yield enforce


# --- RBAC --------------------------------------------------------------------------------------

_STORE = [
    "list_environments",
    "create_environment",
    "get_environment",
    "replace_environment",
    "delete_environment",
    "list_currently_deployed",
    "list_currently_supported",
    "record_deployment",
    "list_deployments_of_version",
    "record_release",
    "list_releases_of_version",
    "get_deployed_version",
    "record_undeployment",
    "get_released_version",
    "record_support_ended",
]


@pytest.mark.parametrize(
    ("method", "path", "action"),
    [
        ("get", f"{_BASE}/environments", "view"),
        ("post", f"{_BASE}/environments", "create"),
        ("get", f"{_BASE}/environments/{_ENV}", "view"),
        ("put", f"{_BASE}/environments/{_ENV}", "edit"),
        ("delete", f"{_BASE}/environments/{_ENV}", "delete"),
        ("get", f"{_BASE}/environments/{_ENV}/deployed-versions/currently-deployed", "view"),
        ("get", f"{_BASE}/environments/{_ENV}/released-versions/currently-supported", "view"),
        ("post", f"{_VERSION}/deployed-versions/environment/{_ENV}", "create"),
        ("get", f"{_VERSION}/deployed-versions/environment/{_ENV}", "view"),
        ("post", f"{_VERSION}/released-versions/environment/{_ENV}", "create"),
        ("get", f"{_VERSION}/released-versions/environment/{_ENV}", "view"),
        ("get", f"{_BASE}/deployed-versions/{_DEPLOYED}", "view"),
        ("patch", f"{_BASE}/deployed-versions/{_DEPLOYED}", "edit"),
        ("get", f"{_BASE}/released-versions/{_RELEASED}", "view"),
        ("patch", f"{_BASE}/released-versions/{_RELEASED}", "edit"),
    ],
)
def test_every_route_is_gated_on_pacts(method: str, path: str, action: str) -> None:
    denial = HTTPException(status_code=403, detail="Permission denied")
    patches = [patch(f"{_ROUTES}.{name}") for name in _STORE]
    mocks = [p.start() for p in patches]
    try:
        with patch(f"{_ROUTES}.enforce_permission", side_effect=denial) as enforce:
            kwargs = {"json": {"name": "x"}} if method in ("post", "put", "patch") else {}
            response = client.request(method.upper(), path, **kwargs)
    finally:
        for p in patches:
            p.stop()
    assert response.status_code == 403
    assert enforce.call_args.args[2:4] == ("pacts", action)
    for mock in mocks:
        mock.assert_not_called()


# --- environments ------------------------------------------------------------------------------


def test_the_index_links_the_environments(allowed: MagicMock) -> None:
    links = client.get(_BASE).json()["_links"]
    assert links["pb:environments"] == {"href": f"{_ROOT}/environments", "title": "Environments", "templated": False}
    assert links["pb:environment"]["href"] == f"{_ROOT}/environments/{{uuid}}"
    assert links["pb:environment"]["templated"] is True


def test_environments_list_with_a_named_link_each(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_environments", return_value=[_PRODUCTION]) as listed:
        response = client.get(f"{_BASE}/environments", params={"name": "production"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/hal+json")
    assert listed.call_args.kwargs == {"name": "production"}
    body = response.json()
    assert body["_links"]["pb:environments"] == [
        {"title": "Environment", "name": "production", "href": f"{_ROOT}/environments/{_ENV}"}
    ]
    assert body["_links"]["self"]["href"] == f"{_ROOT}/environments?name=production"
    assert body["_embedded"]["environments"][0]["uuid"] == _ENV


def test_an_environment_renders_in_the_brokers_shape(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_environment", return_value=_PRODUCTION):
        body = client.get(f"{_BASE}/environments/{_ENV}").json()
    url = f"{_ROOT}/environments/{_ENV}"
    assert body == {
        "uuid": _ENV,
        "name": "production",
        "displayName": "Production",
        "production": True,
        "contractRequired": True,
        "contacts": [{"name": "Team Ledger"}],
        "createdAt": "2026-11-24T10:00:00+00:00",
        "_links": {
            "self": {"title": "Environment", "name": "production", "href": url},
            "pb:currently-deployed-deployed-versions": {
                "title": "Versions currently deployed to Production environment",
                "href": f"{url}/deployed-versions/currently-deployed",
            },
            "pb:currently-supported-released-versions": {
                "title": "Versions released and supported in Production environment",
                "href": f"{url}/released-versions/currently-supported",
            },
            "pb:environments": {"title": "Environments", "href": f"{_ROOT}/environments"},
        },
    }


def test_creating_an_environment_answers_201_with_location(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.create_environment", return_value=_PRODUCTION) as create:
        response = client.post(f"{_BASE}/environments", json={"name": "production", "production": True})
    assert response.status_code == 201
    assert response.headers["location"] == f"{_ROOT}/environments/{_ENV}"
    assert response.json()["uuid"] == _ENV
    checked = create.call_args.args[2]
    assert (checked.name, checked.production) == ("production", True)
    assert create.call_args.kwargs["actor"].user_id == "test-user-id"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PactPublicationError(CODE_ENVIRONMENT_NAME_TAKEN, "taken", pointer="/name"), 409),
        (PactPublicationError(CODE_ENVIRONMENT_NOT_FOUND, "missing"), 404),
    ],
)
def test_store_refusals_map_to_their_status(allowed: MagicMock, error: Exception, status: int) -> None:
    with patch(f"{_ROUTES}.replace_environment", side_effect=error):
        response = client.put(f"{_BASE}/environments/{_ENV}", json={"name": "production"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == error.code  # type: ignore[attr-defined]


def test_a_malformed_environment_is_a_422_with_a_pointer(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.create_environment") as create:
        response = client.post(f"{_BASE}/environments", json={"name": "pro duction"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == CODE_ENVIRONMENT_INVALID
    assert response.json()["detail"]["pointer"] == "/name"
    create.assert_not_called()


def test_deleting_an_environment_answers_204(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.delete_environment", return_value=_PRODUCTION) as delete:
        response = client.delete(f"{_BASE}/environments/{_ENV}")
    assert response.status_code == 204
    assert delete.call_args.args[1:] == (_TENANT, _ENV)


# --- what runs where ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "instance"),
    [
        ({}, UNSPECIFIED),
        ({"applicationInstance": ""}, None),
        ({"applicationInstance": "eu-1"}, "eu-1"),
        ({"target": "blue"}, "blue"),
    ],
)
def test_currently_deployed_reads_the_instance_filter(allowed: MagicMock, query: Dict[str, str], instance: Any) -> None:
    with patch(f"{_ROUTES}.list_currently_deployed", return_value=(_PRODUCTION, [_deployed()])) as listed:
        response = client.get(
            f"{_BASE}/environments/{_ENV}/deployed-versions/currently-deployed",
            params={"pacticipant": "Ledger API", **query},
        )
    assert response.status_code == 200
    assert listed.call_args.kwargs["pacticipant_ref"] == "Ledger API"
    sent = listed.call_args.kwargs["application_instance"]
    assert sent is UNSPECIFIED if instance is UNSPECIFIED else sent == instance
    body = response.json()
    assert body["_links"]["self"]["title"] == "Currently deployed versions for Production"
    assert [entry["uuid"] for entry in body["_embedded"]["deployedVersions"]] == [_DEPLOYED]


def test_a_deployment_renders_what_record_undeployment_reads(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_deployed_version", return_value=_deployed()):
        body = client.get(f"{_BASE}/deployed-versions/{_DEPLOYED}").json()
    assert body["uuid"] == _DEPLOYED
    assert (body["currentlyDeployed"], body["applicationInstance"], body["target"]) == (True, "eu-1", "eu-1")
    assert body["undeployedAt"] is None
    assert body["_links"]["self"]["href"] == f"{_ROOT}/deployed-versions/{_DEPLOYED}"
    assert body["_embedded"]["version"]["number"] == "4f1e2d0"
    assert body["_embedded"]["pacticipant"]["name"] == "Ledger API"
    assert body["_embedded"]["environment"]["name"] == "production"


def test_currently_supported_passes_its_filters(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_currently_supported", return_value=(_PRODUCTION, [_released()])) as listed:
        response = client.get(
            f"{_BASE}/environments/{_ENV}/released-versions/currently-supported",
            params={"pacticipant": "Ledger API", "version": "4f1e2d0"},
        )
    assert listed.call_args.kwargs == {"pacticipant_ref": "Ledger API", "version_number": "4f1e2d0"}
    entry = response.json()["_embedded"]["releasedVersions"][0]
    assert (entry["currentlySupported"], entry["supportEndedAt"]) == (True, None)
    assert entry["_links"]["self"]["href"] == f"{_ROOT}/released-versions/{_RELEASED}"


# --- recording ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("created", "status"), [(True, 201), (False, 200)])
def test_recording_a_deployment(allowed: MagicMock, created: bool, status: int) -> None:
    with patch(f"{_ROUTES}.record_deployment", return_value=(_deployed(), created)) as record:
        response = client.post(
            f"{_VERSION}/deployed-versions/environment/{_ENV}",
            json={"applicationInstance": "eu-1", "target": "eu-1"},
        )
    assert response.status_code == status
    assert response.headers["location"] == f"{_ROOT}/deployed-versions/{_DEPLOYED}"
    assert record.call_args.args[1:6] == (_TENANT, "ledger-api", "4f1e2d0", _ENV, "eu-1")


@pytest.mark.parametrize(("query", "overridden"), [("", False), ("?overrideCanIDeploy=true", True)])
def test_recording_over_a_no_from_can_i_deploy_is_audited(allowed: MagicMock, query: str, overridden: bool) -> None:
    """PFX-8.12 (#7309): the Environments page's *Record it anyway* tick lands in the audit row."""
    with (
        patch(f"{_ROUTES}.record_deployment", return_value=(_deployed(), True)) as record,
        patch("app.pact_audit.record_pact_write") as audit,
    ):
        response = client.post(f"{_VERSION}/deployed-versions/environment/{_ENV}{query}")
    assert response.status_code == 201
    assert record.call_count == 1
    (call,) = audit.call_args_list
    assert call.args[2] == "pacts.deployment.record"
    assert call.args[4]["params"]["override_can_i_deploy"] is overridden


def test_a_malformed_override_flag_is_a_422(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.record_deployment") as record:
        response = client.post(f"{_VERSION}/deployed-versions/environment/{_ENV}?overrideCanIDeploy=maybe")
    assert response.status_code == 422
    record.assert_not_called()


def test_recording_a_deployment_without_a_body_is_the_unnamed_instance(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.record_deployment", return_value=(_deployed(application_instance=None), True)) as record:
        response = client.post(f"{_VERSION}/deployed-versions/environment/{_ENV}")
    assert response.status_code == 201
    assert record.call_args.args[5] is None


def test_recording_for_an_unknown_version_is_a_404(allowed: MagicMock) -> None:
    missing = PacticipantValidationError(CODE_VERSION_NOT_FOUND, "no version")
    with patch(f"{_ROUTES}.record_deployment", side_effect=missing):
        response = client.post(f"{_VERSION}/deployed-versions/environment/{_ENV}", json={})
    assert (response.status_code, response.json()["detail"]["code"]) == (404, CODE_VERSION_NOT_FOUND)


@pytest.mark.parametrize(("created", "status"), [(True, 201), (False, 200)])
def test_recording_a_release(allowed: MagicMock, created: bool, status: int) -> None:
    with patch(f"{_ROUTES}.record_release", return_value=(_released(), created)):
        response = client.post(f"{_VERSION}/released-versions/environment/{_ENV}", json={})
    assert response.status_code == status
    assert response.headers["location"] == f"{_ROOT}/released-versions/{_RELEASED}"


def test_the_history_of_a_version_in_an_environment(allowed: MagicMock) -> None:
    old = _deployed(currently_deployed=False, undeployed_at="2026-11-24T12:00:00+00:00")
    with (
        patch(f"{_ROUTES}.list_deployments_of_version", return_value=[old]),
        patch(f"{_ROUTES}.list_releases_of_version", return_value=[]),
    ):
        deployed = client.get(f"{_VERSION}/deployed-versions/environment/{_ENV}").json()
        released = client.get(f"{_VERSION}/released-versions/environment/{_ENV}").json()
    assert deployed["_embedded"]["deployedVersions"][0]["undeployedAt"] == "2026-11-24T12:00:00+00:00"
    assert released["_embedded"] == {"releasedVersions": []}


# --- ending a deployment or a release ----------------------------------------------------------


def test_patching_currently_deployed_false_records_an_undeployment(allowed: MagicMock) -> None:
    ended = _deployed(currently_deployed=False, undeployed_at="2026-11-24T12:00:00+00:00")
    with patch(f"{_ROUTES}.record_undeployment", return_value=ended) as undeploy:
        response = client.patch(
            f"{_BASE}/deployed-versions/{_DEPLOYED}",
            content=b'{"currentlyDeployed": false}',
            headers={"Content-Type": "application/merge-patch+json"},
        )
    assert response.status_code == 200
    assert undeploy.call_args.args[1:] == (_TENANT, _DEPLOYED)
    assert response.json()["currentlyDeployed"] is False


def test_a_patch_without_the_flag_reads_the_deployment(allowed: MagicMock) -> None:
    with (
        patch(f"{_ROUTES}.record_undeployment") as undeploy,
        patch(f"{_ROUTES}.get_deployed_version", return_value=_deployed()),
    ):
        response = client.patch(f"{_BASE}/deployed-versions/{_DEPLOYED}", json={})
    assert response.status_code == 200
    undeploy.assert_not_called()


def test_a_deployment_cannot_be_revived(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.record_undeployment") as undeploy:
        response = client.patch(f"{_BASE}/deployed-versions/{_DEPLOYED}", json={"currentlyDeployed": True})
    assert response.status_code == 422
    assert response.json()["detail"]["pointer"] == "/currentlyDeployed"
    undeploy.assert_not_called()


def test_an_unknown_deployment_is_a_404(allowed: MagicMock) -> None:
    missing = PactPublicationError(CODE_DEPLOYED_VERSION_NOT_FOUND, "missing")
    with patch(f"{_ROUTES}.get_deployed_version", side_effect=missing):
        response = client.get(f"{_BASE}/deployed-versions/{_DEPLOYED}")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, CODE_DEPLOYED_VERSION_NOT_FOUND)


def test_patching_currently_supported_false_ends_support(allowed: MagicMock) -> None:
    ended = _released(currently_supported=False, support_ended_at="2026-11-25T10:00:00+00:00")
    with patch(f"{_ROUTES}.record_support_ended", return_value=ended) as end:
        response = client.patch(f"{_BASE}/released-versions/{_RELEASED}", json={"currentlySupported": False})
    assert response.status_code == 200
    assert end.call_args.args[1:] == (_TENANT, _RELEASED)
    assert response.json()["supportEndedAt"] == "2026-11-25T10:00:00+00:00"
