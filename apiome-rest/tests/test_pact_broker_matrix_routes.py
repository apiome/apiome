"""``GET …/pact-broker/matrix`` and ``…/can-i-deploy`` — PFX-1.6 (#6919).

The routes without a database: what they pass to the store, how a result is rendered in the Pact
Broker's shape, ``Retry-After`` while the verdict is unknown, refusals, permissions, the index
links and the OpenAPI document. ``test_pact_matrix`` covers the verdict; ``test_pact_matrix_db``
the SQL.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_matrix import (
    IGNORED,
    INFERRED,
    SPECIFIED,
    Integration,
    MatrixOptions,
    MatrixResult,
    MatrixRow,
    UnresolvedSelector,
    resolve_selector,
)
from app.pact_publication import PactPublicationError
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "api_key"}
_ROOT = "http://testserver/v1/tenants/acme/pact-broker"
_BASE = "/v1/tenants/acme/pact-broker"
_ROUTES = "app.pact_broker_matrix_routes"
_SHA = "a" * 64
_CLI_QUERY = "q[][pacticipant]=Billing%20Service&q[][version]=2.0.0&latestby=cvpv&environment=production"

_BILLING = {"id": "c-id", "slug": "billing-service", "name": "Billing Service", "main_branch": "main"}
_LEDGER = {"id": "p-id", "slug": "ledger-api", "name": "Ledger API", "main_branch": "main"}
_OPTIONS = MatrixOptions(latestby="cvpv", environment_name="production")


def _row(success: Any = True, provider_version: Any = "5.1.0") -> MatrixRow:
    verified = provider_version is not None
    return MatrixRow(
        consumer_id="c-id",
        consumer_slug="billing-service",
        consumer_name="Billing Service",
        consumer_version_id="cv-id",
        consumer_version_number="2.0.0",
        consumer_version_seq=2,
        provider_id="p-id",
        provider_slug="ledger-api",
        provider_name="Ledger API",
        pact_sha=_SHA,
        pact_created_at="2026-11-24T10:00:00+00:00",
        provider_version_id="pv-id" if verified else None,
        provider_version_number=provider_version,
        provider_version_seq=7 if verified else None,
        verification_number=3 if verified else None,
        verification_seq=9 if verified else None,
        success=success if verified else None,
        verified_at="2026-11-24T10:05:00+00:00" if verified else None,
    )


def _result(*rows: MatrixRow, ignored: Any = (), ignore_selectors: Any = ()) -> MatrixResult:
    billing = resolve_selector(
        UnresolvedSelector(pacticipant_name="Billing Service", version_number="2.0.0"),
        SPECIFIED,
        _BILLING,
        [{"id": "cv-id", "number": "2.0.0"}],
    )
    ledger = resolve_selector(
        UnresolvedSelector(pacticipant_name="Ledger API", environment_name="production"),
        INFERRED,
        _LEDGER,
        [{"id": "pv-id", "number": "5.1.0"}],
    )
    return MatrixResult(
        considered_rows=list(rows),
        ignored_rows=list(ignored),
        selectors=billing + ledger,
        ignore_selectors=list(ignore_selectors),
        integrations=[Integration("c-id", "Billing Service", "p-id", "Ledger API", required=True)],
        options=_OPTIONS,
    )


_DETAILS = {
    "cv-id": {
        "branches": [{"name": "feat/x", "latest": False}, {"name": "main", "latest": True}],
        "tags": [{"name": "dev build", "latest": True}],
        "environments": [],
    },
    "pv-id": {
        "branches": [],
        "tags": [],
        "environments": [{"uuid": "e-id", "name": "production", "displayName": "Production", "production": True}],
    },
}


@pytest.fixture
def store() -> Iterator[Dict[str, MagicMock]]:
    """The routes with the store, the permission check and authentication stood in."""
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    with (
        patch(f"{_ROUTES}.query_matrix") as query,
        patch(f"{_ROUTES}.read_version_details", return_value=_DETAILS) as details,
        patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as permission,
    ):
        query.return_value = _result(_row())
        yield {"query": query, "details": details, "permission": permission}
    app.dependency_overrides.clear()


def test_the_matrix_is_rendered_in_the_brokers_shape(store: Dict[str, MagicMock]) -> None:
    response = client.get(f"{_BASE}/matrix?{_CLI_QUERY}")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/hal+json")
    assert "retry-after" not in response.headers
    body = response.json()
    assert body["summary"] == {
        "deployable": True,
        "reason": "All required verification results are published and successful",
        "success": 1,
        "failed": 0,
        "unknown": 0,
    }
    assert body["notices"] == [
        {
            "type": "success",
            "code": "verified",
            "text": "All required verification results are published and successful",
        }
    ]
    (row,) = body["matrix"]
    pair = f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service"
    consumer = f"{_ROOT}/pacticipants/billing-service"
    assert row["consumer"] == {
        "name": "Billing Service",
        "version": {
            "number": "2.0.0",
            "branch": "main",
            "branches": row["consumer"]["version"]["branchVersions"],
            "branchVersions": [
                {
                    "name": "feat/x",
                    "latest": False,
                    "_links": {
                        "self": {
                            "title": "Version",
                            "name": "2.0.0",
                            "href": f"{consumer}/branches/feat%2Fx/versions/2.0.0",
                        }
                    },
                },
                {
                    "name": "main",
                    "latest": True,
                    "_links": {
                        "self": {
                            "title": "Version",
                            "name": "2.0.0",
                            "href": f"{consumer}/branches/main/versions/2.0.0",
                        }
                    },
                },
            ],
            "environments": [],
            "_links": {"self": {"href": f"{consumer}/versions/2.0.0"}},
            "tags": [
                {
                    "name": "dev build",
                    "latest": True,
                    "_links": {"self": {"href": f"{consumer}/versions/2.0.0/tags/dev%20build"}},
                }
            ],
        },
        "_links": {"self": {"href": consumer}},
    }
    assert row["provider"]["name"] == "Ledger API"
    assert row["provider"]["version"]["number"] == "5.1.0"
    assert row["provider"]["version"]["branch"] is None
    assert row["provider"]["version"]["environments"] == [
        {
            "uuid": "e-id",
            "name": "production",
            "displayName": "Production",
            "production": True,
            "_links": {"self": {"href": f"{_ROOT}/environments/e-id"}},
        }
    ]
    assert row["pact"] == {
        "createdAt": "2026-11-24T10:00:00+00:00",
        "_links": {"self": {"href": f"{pair}/version/2.0.0"}},
    }
    assert row["verificationResult"] == {
        "success": True,
        "verifiedAt": "2026-11-24T10:05:00+00:00",
        "_links": {"self": {"href": f"{pair}/pact-version/{_SHA}/verification-results/3"}},
    }
    assert row["reason"] == {"code": "verified", "text": "verified"}
    assert "ignored" not in row

    # What reached the store: the caller's tenant, the parsed selector and options.
    (_, tenant, selectors, options), _ = store["query"].call_args
    assert tenant == _TENANT
    assert selectors == [UnresolvedSelector(pacticipant_name="Billing Service", version_number="2.0.0")]
    assert options == _OPTIONS
    assert sorted(store["details"].call_args[0][1]) == ["cv-id", "pv-id"]
    store["permission"].assert_called_once()
    assert store["permission"].call_args[0][2:] == (Resource.PACTS, Action.VIEW)


def test_an_unknown_verdict_says_when_to_ask_again(store: Dict[str, MagicMock]) -> None:
    store["query"].return_value = _result(_row(provider_version=None))
    response = client.get(f"{_BASE}/matrix?{_CLI_QUERY}")
    assert response.status_code == 200
    assert response.headers["retry-after"] == "10"
    body = response.json()
    assert body["summary"]["deployable"] is None
    assert body["summary"]["unknown"] == 1
    assert body["notices"][0]["code"] == "no-verification-result"
    (row,) = body["matrix"]
    assert row["provider"]["version"] is None
    assert row["verificationResult"] is None
    assert row["reason"] == {"code": "no-verification-result", "text": "no verification result"}


def test_a_failed_verdict_and_ignored_rows(store: Dict[str, MagicMock]) -> None:
    store["query"].return_value = _result(_row(False))
    failed = client.get(f"{_BASE}/matrix?{_CLI_QUERY}")
    assert failed.status_code == 200
    assert "retry-after" not in failed.headers
    assert failed.json()["summary"]["deployable"] is False
    assert failed.json()["summary"]["reason"] == (
        "The verification for the pact between version 2.0.0 of Billing Service and "
        "the version of Ledger API currently in production (5.1.0) failed"
    )

    ignore = resolve_selector(UnresolvedSelector(pacticipant_name="Ledger API"), IGNORED, _LEDGER, None)
    store["query"].return_value = _result(ignored=[_row(False)], ignore_selectors=ignore)
    ignored = client.get(f"{_BASE}/matrix?{_CLI_QUERY}&ignore[][pacticipant]=Ledger%20API").json()
    assert ignored["summary"]["deployable"] is True
    assert ignored["summary"]["ignored"] == 1
    assert [row["ignored"] for row in ignored["matrix"]] == [True]
    assert store["query"].call_args[0][3].ignore_selectors == (UnresolvedSelector(pacticipant_name="Ledger API"),)


def test_can_i_deploy_asks_the_same_question(store: Dict[str, MagicMock]) -> None:
    response = client.get(
        f"{_BASE}/can-i-deploy",
        params={"pacticipant": "Billing Service", "version": "2.0.0", "toEnvironment": "production"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["deployable"] is True
    (_, tenant, selectors, options), _ = store["query"].call_args
    assert tenant == _TENANT
    assert selectors == [UnresolvedSelector(pacticipant_name="Billing Service", version_number="2.0.0")]
    assert options == _OPTIONS

    tagged = client.get(
        f"{_BASE}/can-i-deploy", params={"pacticipant": "Billing Service", "version": "2.0.0", "to": "prod"}
    )
    assert tagged.status_code == 200
    options = store["query"].call_args[0][3]
    assert (options.tag, options.latest, options.latestby) == ("prod", True, "cvp")


@pytest.mark.parametrize(
    "path, pointer",
    [
        ("matrix", "/q"),
        ("matrix?q[][pacticipant]=Foo&limit=0", "/limit"),
        ("can-i-deploy?pacticipant=Foo", "/version"),
        ("can-i-deploy?pacticipant=Foo&version=1", "/toEnvironment"),
    ],
)
def test_a_malformed_query_is_a_400_and_reads_nothing(store: Dict[str, MagicMock], path: str, pointer: str) -> None:
    response = client.get(f"{_BASE}/{path}")
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert (detail["code"], detail["pointer"]) == ("pact-matrix-invalid", pointer)
    store["query"].assert_not_called()


def test_a_store_refusal_is_a_400(store: Dict[str, MagicMock]) -> None:
    store["query"].side_effect = PactPublicationError(
        "pact-matrix-invalid", "Pacticipant Nope not found", pointer="/q/0/pacticipant"
    )
    response = client.get(f"{_BASE}/matrix?q[][pacticipant]=Nope")
    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "pact-matrix-invalid",
        "message": "Pacticipant Nope not found",
        "pointer": "/q/0/pacticipant",
    }


@pytest.mark.parametrize("path", [f"matrix?{_CLI_QUERY}", "can-i-deploy?pacticipant=Foo&version=1&to=prod"])
def test_reading_needs_pacts_view(store: Dict[str, MagicMock], path: str) -> None:
    store["permission"].side_effect = HTTPException(status_code=403, detail="Forbidden")
    assert client.get(f"{_BASE}/{path}").status_code == 403
    store["query"].assert_not_called()


def test_without_a_credential_nothing_is_answered() -> None:
    assert client.get(f"{_BASE}/matrix?{_CLI_QUERY}").status_code in (401, 403)
    assert client.get(f"{_BASE}/can-i-deploy?pacticipant=Foo&version=1&to=prod").status_code in (401, 403)


def test_the_index_links_can_i_deploy() -> None:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    try:
        with patch("app.pact_broker_routes.enforce_permission", return_value="test-user-id"):
            links = client.get(_BASE).json()["_links"]
    finally:
        app.dependency_overrides.clear()
    assert links["pb:can-i-deploy-pacticipant-version-to-environment"] == {
        "href": f"{_ROOT}/can-i-deploy?pacticipant={{pacticipant}}&version={{version}}&environment={{environment}}",
        "title": "Determine if an application version can be safely deployed to an environment",
        "templated": True,
    }
    assert links["pb:can-i-deploy-pacticipant-version-to-tag"]["href"] == (
        f"{_ROOT}/can-i-deploy?pacticipant={{pacticipant}}&version={{version}}&to={{tag}}"
    )


def test_both_operations_are_documented() -> None:
    paths = app.openapi()["paths"]
    matrix = paths["/v1/tenants/{tenant_slug}/pact-broker/matrix"]["get"]
    names = [parameter["name"] for parameter in matrix["parameters"]]
    for expected in ("q[][pacticipant]", "q[][version]", "latestby", "environment", "ignore[][pacticipant]", "limit"):
        assert expected in names
    assert "Retry-After" in matrix["responses"]["200"]["headers"]
    assert "400" in matrix["responses"]
    can_i_deploy = paths["/v1/tenants/{tenant_slug}/pact-broker/can-i-deploy"]["get"]
    required = {parameter["name"] for parameter in can_i_deploy["parameters"] if parameter.get("required")}
    assert {"pacticipant", "version"} <= required
    assert {"toEnvironment", "to", "ignore"} <= {parameter["name"] for parameter in can_i_deploy["parameters"]}
