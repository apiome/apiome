"""The Pact Broker for the MCP tools — PFX-4.5 (#6942).

``POST /v1/internal/mcp/pacts/{list,matrix,can-i-deploy,record-deployment}`` without a database:

* every route is fail-closed behind ``X-Internal-Service-Token`` and refuses unknown body fields;
* the key is re-read and acts as its owner: an unknown, revoked or ownerless key is refused with its code,
  and the owner's ``pacts:view`` (reads) or ``pacts:create`` (record a deployment) is enforced;
* structured selectors become exactly the query string the broker parses, so its validation applies;
* the answer is bounded — ``maxRows`` rows and :data:`MAX_NOTICES` notices, with what was left out counted —
  while the verdict is reached from every row;
* ``record-deployment`` resolves the environment by name and refuses an unknown one;
* the list cursor round-trips and a forged one is refused.

``test_mcp_pact_db`` runs the list SQL, the key lookup and the matrix against a live database.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import mcp_pact_routes as routes
from app.config import settings
from app.main import app
from app.pact_environment import DeployedVersionRecord, EnvironmentRecord
from app.pact_matrix import MatrixResult, MatrixRow, parse_can_i_deploy_query, parse_matrix_query
from app.pact_publication import PactPublicationError
from app.permissions import Action, Resource

client = TestClient(app)

TENANT = "11111111-1111-4111-8111-111111111111"
KEY = "22222222-2222-4222-8222-222222222222"
OWNER = "33333333-3333-4333-8333-333333333333"
TOKEN = "internal-token-0123456789"
HEADERS = {"X-Internal-Service-Token": TOKEN}
BASE = "/v1/internal/mcp/pacts"
_AUTH = {"tenant_id": TENANT, "user_id": OWNER, "auth_method": "api_key", "user_name": "MCP key agent"}


def _row(index: int = 0, success: Any = True) -> MatrixRow:
    return MatrixRow(
        consumer_id="c-id",
        consumer_slug="billing-service",
        consumer_name="Billing Service",
        consumer_version_id=f"cv-{index}",
        consumer_version_number=f"1.{index}.0",
        consumer_version_seq=index,
        provider_id="p-id",
        provider_slug="ledger-api",
        provider_name="Ledger API",
        pact_sha="a" * 64,
        pact_created_at="2026-11-24T10:00:00+00:00",
        provider_version_id="pv-id",
        provider_version_number="5.1.0",
        verification_number=3,
        success=success,
        verified_at="2026-11-24T10:05:00+00:00",
        pact_pending=True,
        wip=True,
    )


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "internal_service_token", TOKEN)


@pytest.fixture
def mocks() -> Iterator[Dict[str, MagicMock]]:
    """The key lookup, permission check and matrix store stood in."""
    with (
        patch.object(routes, "key_auth_data", return_value=dict(_AUTH)) as key,
        patch.object(routes, "enforce_permission", return_value=OWNER) as permission,
        patch.object(routes, "query_matrix", return_value=MatrixResult(considered_rows=[_row()])) as query,
    ):
        yield {"key": key, "permission": permission, "query": query}


# ---------------------------------------------------------------------------------------------
# Internal-only
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/list", "/matrix", "/can-i-deploy", "/record-deployment"])
def test_every_route_needs_the_internal_token(path: str) -> None:
    body = {"tenantId": TENANT, "keyId": KEY}
    assert client.post(BASE + path, json=body).status_code == 401
    assert client.post(BASE + path, json=body, headers={"X-Internal-Service-Token": "wrong"}).status_code == 403


def test_without_a_configured_token_the_routes_are_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "internal_service_token", "")
    assert client.post(BASE + "/list", json={"tenantId": TENANT, "keyId": KEY}, headers=HEADERS).status_code == 503


def test_unknown_body_fields_are_refused_not_ignored(mocks: Dict[str, MagicMock]) -> None:
    body = {"tenantId": TENANT, "keyId": KEY, "selectors": [{"pacticipant": "B", "versoin": "1"}]}
    response = client.post(BASE + "/matrix", json=body, headers=HEADERS)
    assert response.status_code == 422
    assert "versoin" in response.text


# ---------------------------------------------------------------------------------------------
# The key and its owner
# ---------------------------------------------------------------------------------------------


def test_the_key_acts_as_its_owner() -> None:
    with patch.object(routes.db, "execute_query", return_value=[{"created_by": OWNER, "label": "agent"}]) as query:
        auth = routes.key_auth_data(TENANT, KEY)
    assert auth == {"tenant_id": TENANT, "user_id": OWNER, "auth_method": "api_key", "user_name": "MCP key agent"}
    sql, params = query.call_args.args
    assert "revoked_at IS NULL" in sql and "expires_at" in sql and "tenant_id = %s::uuid" in sql
    assert params == (KEY, TENANT)


def test_an_unknown_or_revoked_key_is_refused() -> None:
    with patch.object(routes.db, "execute_query", return_value=[]):
        with pytest.raises(HTTPException) as caught:
            routes.key_auth_data(TENANT, KEY)
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "mcp-pact-key-unknown"


def test_a_malformed_key_id_is_refused_without_a_query() -> None:
    with patch.object(routes.db, "execute_query") as query:
        with pytest.raises(HTTPException) as caught:
            routes.key_auth_data(TENANT, "not-a-uuid")
    assert caught.value.detail["code"] == "mcp-pact-key-unknown"
    query.assert_not_called()


def test_a_key_without_an_owner_is_refused() -> None:
    with patch.object(routes.db, "execute_query", return_value=[{"created_by": None, "label": "agent"}]):
        with pytest.raises(HTTPException) as caught:
            routes.key_auth_data(TENANT, KEY)
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "mcp-pact-key-has-no-owner"


def test_reads_need_pacts_view(mocks: Dict[str, MagicMock]) -> None:
    body = {"tenantId": TENANT, "keyId": KEY, "selectors": [{"pacticipant": "Billing Service"}]}
    assert client.post(BASE + "/matrix", json=body, headers=HEADERS).status_code == 200
    mocks["key"].assert_called_once_with(TENANT, KEY)
    args = mocks["permission"].call_args.args
    assert args[1] == _AUTH and args[2:] == (Resource.PACTS, Action.VIEW)


def test_a_permission_refusal_reaches_the_caller(mocks: Dict[str, MagicMock]) -> None:
    mocks["permission"].side_effect = HTTPException(status_code=403, detail="Permission denied: pacts:view is required")
    body = {"tenantId": TENANT, "keyId": KEY, "pacticipant": "Billing", "version": "1", "toEnvironment": "prod"}
    response = client.post(BASE + "/can-i-deploy", json=body, headers=HEADERS)
    assert response.status_code == 403
    assert "pacts:view" in response.text
    mocks["query"].assert_not_called()


# ---------------------------------------------------------------------------------------------
# Matrix and can-i-deploy
# ---------------------------------------------------------------------------------------------


def test_structured_selectors_become_the_broker_query() -> None:
    body = routes.McpPactMatrixRequest.model_validate(
        {
            "tenantId": TENANT,
            "keyId": KEY,
            "selectors": [
                {"pacticipant": "Billing Service", "version": "2.0.0"},
                {"pacticipant": "Ledger API", "latest": True, "mainBranch": True},
            ],
            "latestby": "cvpv",
            "toEnvironment": "production",
            "ignore": [{"pacticipant": "Search", "version": "9"}],
            "limit": 200,
        }
    )
    selectors, options = parse_matrix_query(routes.matrix_query_string(body))
    assert [(s.pacticipant_name, s.version_number, s.latest, s.main_branch) for s in selectors] == [
        ("Billing Service", "2.0.0", False, False),
        ("Ledger API", None, True, True),
    ]
    assert options.latestby == "cvpv" and options.environment_name == "production" and options.limit == 200
    assert [(s.pacticipant_name, s.version_number) for s in options.ignore_selectors] == [("Search", "9")]


def test_can_i_deploy_becomes_the_broker_query() -> None:
    body = routes.McpPactCanIDeployRequest.model_validate(
        {
            "tenantId": TENANT,
            "keyId": KEY,
            "pacticipant": "Billing",
            "version": "2.0.0",
            "toTag": "prod",
            "ignore": [{"pacticipant": "Search"}],
        }
    )
    selectors, options = parse_can_i_deploy_query(routes.can_i_deploy_query_string(body))
    assert selectors[0].pacticipant_name == "Billing" and selectors[0].version_number == "2.0.0"
    assert options.tag == "prod" and options.latest is True
    assert [s.pacticipant_name for s in options.ignore_selectors] == ["Search"]


def test_the_matrix_answer_is_compact(mocks: Dict[str, MagicMock]) -> None:
    body = {"tenantId": TENANT, "keyId": KEY, "selectors": [{"pacticipant": "Billing Service"}]}
    answer = client.post(BASE + "/matrix", json=body, headers=HEADERS).json()
    assert answer["summary"]["deployable"] is True
    assert answer["rowsTotal"] == 1 and answer["rowsTruncated"] is False and answer["retryAfterSeconds"] is None
    assert answer["rows"] == [
        {
            "consumer": {"name": "Billing Service", "slug": "billing-service", "version": "1.0.0"},
            "provider": {"name": "Ledger API", "slug": "ledger-api", "version": "5.1.0"},
            "pact": {"sha": "a" * 64, "createdAt": "2026-11-24T10:00:00+00:00"},
            "verification": {
                "success": True,
                "verifiedAt": "2026-11-24T10:05:00+00:00",
                "number": 3,
                "kind": "native",
                "pending": True,
                "wip": True,
            },
            "reason": answer["rows"][0]["reason"],
            "ignored": False,
        }
    ]
    assert answer["rows"][0]["reason"]["code"] == "verified"


def test_rows_past_max_rows_are_counted_and_the_verdict_reads_them_all(mocks: Dict[str, MagicMock]) -> None:
    rows = [_row(index) for index in range(7)] + [_row(7, success=False)]
    mocks["query"].return_value = MatrixResult(considered_rows=rows, ignored_rows=[_row(8)])
    body = {"tenantId": TENANT, "keyId": KEY, "selectors": [{"pacticipant": "Billing Service"}], "maxRows": 3}
    answer = client.post(BASE + "/matrix", json=body, headers=HEADERS).json()
    assert len(answer["rows"]) == 3
    assert answer["rowsTotal"] == 9 and answer["rowsTruncated"] is True
    # The failed eighth row is not returned, but the verdict still says no.
    assert answer["summary"]["deployable"] is False and answer["summary"]["failed"] == 1


def test_notices_are_bounded() -> None:
    reasons = tuple(routes.deployment_verdict(MatrixResult()).reasons) * (routes.MAX_NOTICES + 5)
    verdict = MagicMock(deployable=None, reasons=reasons, counts={"success": 0}, reason="r", unknown=True)
    with (
        patch.object(routes, "enforce_permission"),
        patch.object(routes, "query_matrix", return_value=MatrixResult()),
        patch.object(routes, "deployment_verdict", return_value=verdict),
    ):
        answer = routes.answer_matrix(TENANT, _AUTH, "q[][pacticipant]=B", parse_matrix_query, 10)
    assert len(answer.notices) == routes.MAX_NOTICES and answer.notices_truncated is True
    assert answer.retry_after_seconds == routes.RETRY_AFTER_SECONDS


def test_max_rows_is_capped() -> None:
    body = {"tenantId": TENANT, "keyId": KEY, "selectors": [{"pacticipant": "B"}], "maxRows": routes.MAX_ROWS + 1}
    assert client.post(BASE + "/matrix", json=body, headers=HEADERS).status_code == 422


def test_a_query_the_broker_refuses_is_a_400_with_its_pointer(mocks: Dict[str, MagicMock]) -> None:
    body = {"tenantId": TENANT, "keyId": KEY, "selectors": [{"pacticipant": "B", "version": "1", "latest": True}]}
    response = client.post(BASE + "/matrix", json=body, headers=HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "pact-matrix-invalid"
    assert response.json()["detail"]["pointer"] == "/q/0"


def test_can_i_deploy_without_a_destination_is_refused(mocks: Dict[str, MagicMock]) -> None:
    body = {"tenantId": TENANT, "keyId": KEY, "pacticipant": "Billing", "version": "1"}
    response = client.post(BASE + "/can-i-deploy", json=body, headers=HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "pact-matrix-invalid"


def test_an_unknown_pacticipant_is_reported(mocks: Dict[str, MagicMock]) -> None:
    mocks["query"].side_effect = PactPublicationError(
        "pact-matrix-invalid", "Pacticipant Nope not found", pointer="/q/0/pacticipant"
    )
    body = {"tenantId": TENANT, "keyId": KEY, "pacticipant": "Nope", "version": "1", "toEnvironment": "prod"}
    response = client.post(BASE + "/can-i-deploy", json=body, headers=HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"]["message"] == "Pacticipant Nope not found"


# ---------------------------------------------------------------------------------------------
# Record a deployment
# ---------------------------------------------------------------------------------------------

_PRODUCTION = EnvironmentRecord(id="e-id", name="production", display_name="Production", production=True)


def test_record_deployment_resolves_the_environment_by_name_and_needs_pacts_create(
    mocks: Dict[str, MagicMock],
) -> None:
    deployed = DeployedVersionRecord(
        id="d-id",
        pacticipant_slug="billing-service",
        pacticipant_name="Billing Service",
        version_number="2.0.0",
        environment=_PRODUCTION,
        application_instance="eu-1",
        created_at="2026-11-25T10:00:00+00:00",
    )
    with (
        patch.object(routes, "list_environments", return_value=[_PRODUCTION]) as environments,
        patch.object(routes, "record_deployment", return_value=(deployed, True)) as record,
    ):
        body = {
            "tenantId": TENANT,
            "keyId": KEY,
            "pacticipant": "Billing Service",
            "version": "2.0.0",
            "environment": "production",
            "applicationInstance": " eu-1 ",
        }
        response = client.post(BASE + "/record-deployment", json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "created": True,
        "deployment": {
            "uuid": "d-id",
            "pacticipant": {"name": "Billing Service", "slug": "billing-service"},
            "version": "2.0.0",
            "environment": {"uuid": "e-id", "name": "production", "displayName": "Production", "production": True},
            "applicationInstance": "eu-1",
            "currentlyDeployed": True,
            "createdAt": "2026-11-25T10:00:00+00:00",
        },
    }
    assert mocks["permission"].call_args.args[2:] == (Resource.PACTS, Action.CREATE)
    assert environments.call_args.kwargs == {"name": "production"}
    args, kwargs = record.call_args
    assert args[1:] == (TENANT, "Billing Service", "2.0.0", "e-id", "eu-1")
    assert kwargs["actor"].user_id == OWNER and kwargs["actor"].label == "MCP key agent"


def test_record_deployment_to_an_unknown_environment_is_a_404(mocks: Dict[str, MagicMock]) -> None:
    with (
        patch.object(routes, "list_environments", return_value=[]),
        patch.object(routes, "record_deployment") as record,
    ):
        body = {"tenantId": TENANT, "keyId": KEY, "pacticipant": "B", "version": "1", "environment": "nowhere"}
        response = client.post(BASE + "/record-deployment", json=body, headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "pact-environment-not-found"
    record.assert_not_called()


def test_record_deployment_with_a_malformed_instance_is_refused(mocks: Dict[str, MagicMock]) -> None:
    with (
        patch.object(routes, "list_environments", return_value=[_PRODUCTION]),
        patch.object(routes, "record_deployment") as record,
    ):
        body = {
            "tenantId": TENANT,
            "keyId": KEY,
            "pacticipant": "B",
            "version": "1",
            "environment": "production",
            "applicationInstance": "eu\n1",
        }
        response = client.post(BASE + "/record-deployment", json=body, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "pact-deployment-invalid"
    record.assert_not_called()


def test_record_deployment_refused_without_pacts_create(mocks: Dict[str, MagicMock]) -> None:
    mocks["permission"].side_effect = HTTPException(
        status_code=403, detail="Permission denied: pacts:create is required"
    )
    with patch.object(routes, "record_deployment") as record:
        body = {"tenantId": TENANT, "keyId": KEY, "pacticipant": "B", "version": "1", "environment": "production"}
        response = client.post(BASE + "/record-deployment", json=body, headers=HEADERS)
    assert response.status_code == 403
    record.assert_not_called()


# ---------------------------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------------------------


def _list_row(provider: str, consumer: str) -> Dict[str, Any]:
    return {
        "consumer_slug": consumer,
        "consumer_name": consumer.title(),
        "provider_slug": provider,
        "provider_name": provider.title(),
        "consumer_version": "1.0.0",
        "sha": "b" * 64,
        "specification_version": "3.0.0",
        "interaction_count": 2,
        "revision": 1,
        "created_at": "2026-11-24T10:00:00+00:00",
        "updated_at": None,
        "verification_success": None,
        "verified_at": None,
        "verification_kind": None,
        "verified_provider_version": None,
    }


def test_list_pages_with_a_cursor(mocks: Dict[str, MagicMock]) -> None:
    rows = [_list_row("ledger", "billing"), _list_row("ledger", "search"), _list_row("mail", "billing")]
    with patch.object(routes.db, "execute_query", return_value=rows) as query:
        answer = client.post(
            BASE + "/list", json={"tenantId": TENANT, "keyId": KEY, "limit": 2}, headers=HEADERS
        ).json()
    assert [item["consumer"]["slug"] for item in answer["items"]] == ["billing", "search"]
    assert answer["hasMore"] is True and answer["items"][0]["latestVerification"] is None
    params = query.call_args.args[1]
    assert params["limit"] == 3 and params["tenant"] == TENANT and params["after_provider"] is None
    assert routes.decode_list_cursor(answer["nextCursor"]) == ("ledger", "search")
    assert mocks["permission"].call_args.args[2:] == (Resource.PACTS, Action.VIEW)


def test_the_last_list_page_has_no_cursor(mocks: Dict[str, MagicMock]) -> None:
    with patch.object(routes.db, "execute_query", return_value=[_list_row("ledger", "billing")]) as query:
        cursor = routes.encode_list_cursor("aaa", "bbb")
        answer = client.post(
            BASE + "/list", json={"tenantId": TENANT, "keyId": KEY, "cursor": cursor}, headers=HEADERS
        ).json()
    assert answer["hasMore"] is False and answer["nextCursor"] is None
    params = query.call_args.args[1]
    assert (params["after_provider"], params["after_consumer"]) == ("aaa", "bbb")


def test_a_forged_cursor_is_refused(mocks: Dict[str, MagicMock]) -> None:
    response = client.post(BASE + "/list", json={"tenantId": TENANT, "keyId": KEY, "cursor": "!!nope"}, headers=HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "mcp-pact-invalid"


def test_list_filters_resolve_pacticipants_in_the_tenant(mocks: Dict[str, MagicMock]) -> None:
    provider = MagicMock(id="p-id")
    with (
        patch.object(routes, "get_pacticipant", return_value=provider) as lookup,
        patch.object(routes.db, "execute_query", return_value=[]) as query,
    ):
        body = {"tenantId": TENANT, "keyId": KEY, "provider": "Ledger API"}
        assert client.post(BASE + "/list", json=body, headers=HEADERS).status_code == 200
    assert lookup.call_args.args[1:] == (TENANT, "Ledger API")
    assert query.call_args.args[1]["provider"] == "p-id" and query.call_args.args[1]["consumer"] is None


def test_an_unknown_list_filter_is_a_404(mocks: Dict[str, MagicMock]) -> None:
    from app.pacticipant import PacticipantValidationError

    with patch.object(
        routes,
        "get_pacticipant",
        side_effect=PacticipantValidationError("pacticipant-not-found", "no pacticipant 'nope'"),
    ):
        body = {"tenantId": TENANT, "keyId": KEY, "consumer": "nope"}
        response = client.post(BASE + "/list", json=body, headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "pacticipant-not-found"


def test_the_routes_are_in_the_openapi_document() -> None:
    paths = app.openapi()["paths"]
    for path in ("/list", "/matrix", "/can-i-deploy", "/record-deployment"):
        assert BASE + path in paths
