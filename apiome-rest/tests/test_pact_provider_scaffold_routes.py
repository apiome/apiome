"""Provider test scaffolding, the service and the route — PFX-8.19 (#7316).

* ``pacts:view`` is checked before anything is read; every read uses the credential's tenant;
* the recommended selectors (pending on) choose the pacts; each state's parameters and an example
  come from every interaction naming it; registered states are marked, the rest flagged;
* an unknown provider is 404, an unknown language 422 before any read, too many pacts 422;
* the caller's token never reaches the file.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Iterator, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_provider_scaffold import CODE_LANGUAGE_UNSUPPORTED, NOTICE_NO_PACTS, NOTICE_STATE_UNREGISTERED
from app.pact_provider_scaffold_service import scaffold_for_provider
from app.pact_verifier import MAX_PACTS_PER_RUN
from app.pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_TOKEN = "s3cr3t-api-key-value"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "u-1", "auth_method": "api_key", "api_key": _TOKEN}
_PATH = "/v1/tenants/acme/pact-provider-tests/billing-service"
_SERVICE = "app.pact_provider_scaffold_service"
_ROUTES = "app.pact_provider_scaffold_routes"


def _case(description: str, *states: Dict[str, Any]) -> SimpleNamespace:
    """One compiled interaction naming provider states."""
    return SimpleNamespace(
        pact=SimpleNamespace(
            description=description,
            provider_states=[SimpleNamespace(name=s["name"], params=s.get("params", {})) for s in states],
        )
    )


def _chosen(consumer: str) -> SimpleNamespace:
    return SimpleNamespace(candidate=SimpleNamespace(consumer_slug=consumer, sha=consumer * 4))


_PROVIDER = SimpleNamespace(id="p-1", slug="billing-service", name="Billing Service")

#: Two consumers' pacts: "an invoice exists" twice with different parameters, one other state.
_CASES = {
    "orders-ui": [_case("get invoice", {"name": "an invoice exists", "params": {"id": 1042}})],
    "admin": [
        _case(
            "list invoices",
            {"name": "an invoice exists", "params": {"currency": "EUR"}},
            {"name": "a customer 7 exists"},
        ),
        SimpleNamespace(pact=None),
    ],
}


def _registered(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        parameters=[SimpleNamespace(name="id", default=None), SimpleNamespace(name="draft", default=False)],
        setup=SimpleNamespace(kind="state_change"),
    )


@pytest.fixture
def store() -> Iterator[Dict[str, MagicMock]]:
    with (
        patch(
            f"{_SERVICE}.select_provider_pacts", return_value=(_PROVIDER, [_chosen("orders-ui"), _chosen("admin")])
        ) as select,
        patch(f"{_SERVICE}.get_pact_by_sha", side_effect=lambda db, t, p, consumer, sha: consumer) as read,
        patch(f"{_SERVICE}.compile_stored_pact", side_effect=lambda consumer: SimpleNamespace(cases=_CASES[consumer])),
        patch(f"{_SERVICE}.list_states", return_value=[_registered("an invoice exists")]) as states,
    ):
        yield {"select": select, "read": read, "states": states}


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


# --- the service ------------------------------------------------------------------------------


def test_the_recommended_selectors_choose_the_pacts_in_the_callers_tenant(store: Dict[str, MagicMock]) -> None:
    scaffold_for_provider(MagicMock(), _TENANT, "billing-service", "typescript")
    _db, tenant, provider, query = store["select"].call_args.args
    assert (tenant, provider) == (_TENANT, "billing-service")
    assert query.include_pending_status is True
    # deployedOrReleased reads as one deployed and one released selector.
    assert [(s.main_branch, s.deployed, s.released) for s in query.selectors] == [
        (True, False, False),
        (False, True, False),
        (False, False, True),
    ]
    assert all(call.args[1] == _TENANT for call in store["read"].call_args_list)
    assert store["states"].call_args.args[1] == _TENANT


def test_each_state_carries_every_parameter_and_whether_it_is_registered(store: Dict[str, MagicMock]) -> None:
    body = scaffold_for_provider(MagicMock(), _TENANT, "billing-service", "java").as_json()
    states = {state["name"]: state for state in body["states"]}
    invoice = states["an invoice exists"]
    assert invoice["params"] == ["currency", "draft", "id"]
    assert invoice["example"] == {"currency": "EUR", "draft": False, "id": 1042}
    assert (invoice["registered"], invoice["setup_kind"], invoice["interactions"]) == (True, "state_change", 2)
    assert invoice["consumers"] == ["orders-ui", "admin"]
    assert states["a customer 7 exists"]["registered"] is False
    assert body["unregistered"] == 1
    assert [n["code"] for n in body["notices"]] == [NOTICE_STATE_UNREGISTERED]
    assert body["pacts"] == 2 and body["pending"] is True
    assert body["selectors"] == [{"mainBranch": True}, {"deployedOrReleased": True}]
    assert body["file_name"] == "BillingServicePactTest.java"


def test_no_pacts_still_writes_the_file(store: Dict[str, MagicMock]) -> None:
    store["select"].return_value = (_PROVIDER, [])
    body = scaffold_for_provider(MagicMock(), _TENANT, "billing-service", "go").as_json()
    assert body["states"] == [] and body["pacts"] == 0
    assert [n["code"] for n in body["notices"]] == [NOTICE_NO_PACTS]


# --- the route --------------------------------------------------------------------------------


def test_it_needs_pacts_view_before_reading_anything(store: Dict[str, MagicMock]) -> None:
    denial = HTTPException(status_code=403, detail="Permission denied")
    with patch(f"{_ROUTES}.enforce_permission", side_effect=denial) as enforce:
        response = client.get(_PATH, params={"language": "typescript"})
    assert response.status_code == 403
    assert enforce.call_args.args[2:4] == (Resource.PACTS, Action.VIEW)
    store["select"].assert_not_called()


def test_it_answers_the_file_and_never_writes_the_callers_token(store: Dict[str, MagicMock]) -> None:
    with patch(f"{_ROUTES}.enforce_permission", return_value="u-1"):
        response = client.get(_PATH, params={"language": "python"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file_name"] == "test_billing_service_pact.py"
    assert _TOKEN not in body["content"]
    assert 'os.environ.get("PACT_BROKER_TOKEN")' in body["content"]
    compile(body["content"], body["file_name"], "exec")


def test_an_unknown_language_is_422_before_any_read(store: Dict[str, MagicMock]) -> None:
    with patch(f"{_ROUTES}.enforce_permission", return_value="u-1"):
        response = client.get(_PATH, params={"language": "cobol"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == CODE_LANGUAGE_UNSUPPORTED
    store["select"].assert_not_called()


def test_a_missing_language_is_refused() -> None:
    with patch(f"{_ROUTES}.enforce_permission", return_value="u-1"):
        assert client.get(_PATH).status_code == 422


def test_an_unknown_provider_or_another_tenants_is_404(store: Dict[str, MagicMock]) -> None:
    store["select"].side_effect = PacticipantValidationError(CODE_NOT_FOUND, "no pacticipant 'billing-service'")
    with patch(f"{_ROUTES}.enforce_permission", return_value="u-1"):
        response = client.get(_PATH, params={"language": "go"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_NOT_FOUND


def test_too_many_pacts_is_422(store: Dict[str, MagicMock]) -> None:
    many: List[SimpleNamespace] = [_chosen("orders-ui")] * (MAX_PACTS_PER_RUN + 1)
    store["select"].return_value = (_PROVIDER, many)
    with patch(f"{_ROUTES}.enforce_permission", return_value="u-1"):
        response = client.get(_PATH, params={"language": "go"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "pact-verify-too-many-pacts"
    store["read"].assert_not_called()


def test_a_credential_without_a_tenant_is_403() -> None:
    app.dependency_overrides[validate_broker_authentication] = lambda: {"user_id": "u-1"}
    with patch(f"{_ROUTES}.enforce_permission", return_value="u-1"):
        assert client.get(_PATH, params={"language": "go"}).status_code == 403
