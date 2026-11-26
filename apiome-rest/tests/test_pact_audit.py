"""The audit trail of Pact writes — PFX-6.1 (#6953).

:func:`app.pact_audit.audited_write` and :func:`app.pact_audit.record_pact_write`, without a database:

* a successful call appends one row: action, tenant, actor, source, target and a body-free detail;
* a call that raises, or answers 4xx / 5xx, changed nothing and writes no row;
* a failed audit insert never fails the change (it is logged);
* a call with no tenant, an unknown action, or an endpoint without ``auth_data`` is refused loudly;
* the wrapped endpoint keeps its signature, so FastAPI still reads its body as the body;
* real routes — registering a pacticipant, creating an environment, recording a deployment over
  MCP — write their row, and a refused one does not.

``tests/test_pacts_permission_matrix.py`` proves every write route is wrapped (or audits in its
own transaction).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.responses import JSONResponse

from app import pact_audit
from app.pact_audit import AUDIT_ACTIONS, AUDITED_ENDPOINTS, audited_write, record_pact_write

USER = "33333333-3333-4333-8333-333333333333"
TENANT = "11111111-1111-4111-8111-111111111111"
AUTH = {"tenant_id": TENANT, "user_id": USER, "auth_method": "jwt", "user_email": "dev@example.com"}

#: The database the toy endpoints below resolve (``audited_write`` reads the endpoint module's ``db``).
db = MagicMock()


@pytest.fixture(autouse=True)
def _fresh_db() -> Iterator[MagicMock]:
    db.reset_mock(side_effect=True)
    db.write_access_audit.side_effect = None
    yield db


def _rows() -> List[Dict[str, Any]]:
    return [call.kwargs for call in db.write_access_audit.call_args_list]


# ---------------------------------------------------------------------------------------------
# record_pact_write
# ---------------------------------------------------------------------------------------------


def test_a_row_names_the_action_actor_source_and_target() -> None:
    assert record_pact_write(db, AUTH, "pacts.environment.create", "pact-environments", {"status": 201})
    assert _rows() == [
        {
            "tenant_id": TENANT,
            "action": "pacts.environment.create",
            "actor_id": USER,
            "actor_label": "dev@example.com",
            "target": "pact-environments",
            "source": "web",
            "detail": {"status": 201},
        }
    ]


def test_a_ci_key_is_recorded_as_an_api_key_and_an_unstorable_user_id_is_dropped() -> None:
    auth = {"tenant_id": TENANT, "user_id": "not-a-uuid", "auth_method": "api_key", "user_name": "ci"}
    record_pact_write(db, auth, "pacts.version.record", "pacticipant/billing/version/1.0.0")
    (row,) = _rows()
    assert row["source"] == "api_key" and row["actor_id"] is None and row["actor_label"] == "ci"
    assert row["detail"] == {}


def test_a_failed_insert_is_logged_and_reported_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    db.write_access_audit.side_effect = RuntimeError("audit table locked")
    with caplog.at_level(logging.WARNING, logger="app.pact_audit"):
        assert record_pact_write(db, AUTH, "pacts.webhook.delete", "pact-webhook/x") is False
    assert "Failed to audit pacts.webhook.delete" in caplog.text


def test_a_call_without_a_tenant_writes_nothing_and_says_so(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.pact_audit"):
        assert record_pact_write(db, {"user_id": USER}, "pacts.tag.add", "t") is False
    assert db.write_access_audit.call_count == 0 and "no tenant" in caplog.text


def test_an_unknown_action_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="unknown pact audit action"):
        record_pact_write(db, AUTH, "pacts.typo", "t")
    with pytest.raises(ValueError, match="unknown pact audit action"):
        audited_write("pacts.typo", "t")


def test_every_action_is_namespaced_and_unique() -> None:
    assert len(AUDIT_ACTIONS) == len(set(AUDIT_ACTIONS))
    assert all(action.startswith("pacts.") for action in AUDIT_ACTIONS)
    assert not set(AUDIT_ACTIONS) & set(pact_audit.TRANSACTIONAL_AUDIT_ACTIONS)


# ---------------------------------------------------------------------------------------------
# audited_write, on a toy app
# ---------------------------------------------------------------------------------------------


def _auth() -> Dict[str, Any]:
    return dict(AUTH)


class Thing(BaseModel):
    """A request body (proves the wrapped endpoint still reads its body)."""

    name: str


toy = FastAPI()


@toy.post("/things/{slug}", status_code=201)
@audited_write("pacts.pacticipant.create", "thing/{slug}")
def create_thing(slug: str, body: Thing, auth_data: Dict[str, Any] = Depends(_auth)) -> Dict[str, Any]:
    if body.name == "boom":
        raise HTTPException(status_code=409, detail="taken")
    return {"id": "thing-1", "slug": slug, "name": body.name}


@toy.put("/async/{slug}")
@audited_write("pacts.pacticipant.update", "thing/{slug}")
async def update_thing(slug: str, auth_data: Dict[str, Any] = Depends(_auth)) -> JSONResponse:
    status = 404 if slug == "missing" else 200
    return JSONResponse({"slug": slug}, status_code=status)


toy_client = TestClient(toy, raise_server_exceptions=False)


def test_a_successful_sync_write_appends_one_row_without_the_body() -> None:
    response = toy_client.post("/things/billing", json={"name": "Secret Name"})
    assert response.status_code == 201 and response.json()["name"] == "Secret Name"
    (row,) = _rows()
    assert row["action"] == "pacts.pacticipant.create" and row["target"] == "thing/billing"
    assert row["detail"] == {
        "route": "create_thing",
        "params": {"slug": "billing"},
        "id": "thing-1",
    }
    assert "Secret Name" not in str(row)


def test_a_refused_write_appends_nothing() -> None:
    assert toy_client.post("/things/billing", json={"name": "boom"}).status_code == 409
    assert toy_client.post("/things/billing", json={}).status_code == 422
    assert _rows() == []


def test_an_async_write_is_audited_and_an_error_response_is_not() -> None:
    assert toy_client.put("/async/billing").status_code == 200
    assert toy_client.put("/async/missing").status_code == 404
    (row,) = _rows()
    assert row["action"] == "pacts.pacticipant.update" and row["detail"]["status"] == 200
    assert "id" not in row["detail"]


def test_a_failing_audit_never_fails_the_write() -> None:
    db.write_access_audit.side_effect = RuntimeError("down")
    assert toy_client.post("/things/billing", json={"name": "Billing"}).status_code == 201


def test_the_wrapped_endpoint_is_registered_with_its_action() -> None:
    assert AUDITED_ENDPOINTS[f"{__name__}.create_thing"] == "pacts.pacticipant.create"
    assert AUDITED_ENDPOINTS[f"{__name__}.update_thing"] == "pacts.pacticipant.update"


def test_an_endpoint_without_auth_data_cannot_be_wrapped() -> None:
    def anonymous(slug: str) -> None:
        return None

    with pytest.raises(TypeError, match="no auth_data"):
        audited_write("pacts.tag.add", "x")(anonymous)


def test_a_target_with_a_missing_placeholder_falls_back_to_the_template() -> None:
    assert pact_audit._target("thing/{nope}", {"slug": "a"}) == "thing/{nope}"


# ---------------------------------------------------------------------------------------------
# Real routes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def app_client() -> Iterator[TestClient]:
    from app.auth import validate_authentication
    from app.main import app
    from app.pact_broker_auth import validate_broker_authentication

    app.dependency_overrides[validate_authentication] = _auth
    app.dependency_overrides[validate_broker_authentication] = _auth
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(validate_authentication, None)
    app.dependency_overrides.pop(validate_broker_authentication, None)


def test_registering_a_pacticipant_writes_its_row(app_client: TestClient) -> None:
    from tests.test_pacticipant_routes import _pacticipant

    audit = MagicMock()
    with (
        patch("app.pacticipant_routes.enforce_permission", return_value=USER),
        patch("app.pacticipant_routes.create_pacticipant", return_value=_pacticipant()),
        patch("app.pacticipant_routes.db.write_access_audit", audit),
    ):
        response = app_client.post("/v1/tenants/acme/pacticipants", json={"name": "Billing Service"})
    assert response.status_code == 201, response.text
    (call,) = audit.call_args_list
    assert call.kwargs["action"] == "pacts.pacticipant.create" and call.kwargs["tenant_id"] == TENANT
    assert call.kwargs["detail"]["id"] == _pacticipant().id and call.kwargs["actor_id"] == USER


def test_a_refused_registration_writes_no_row(app_client: TestClient) -> None:
    from app.pacticipant import PacticipantValidationError

    audit = MagicMock()
    with (
        patch("app.pacticipant_routes.enforce_permission", return_value=USER),
        patch(
            "app.pacticipant_routes.create_pacticipant",
            side_effect=PacticipantValidationError("pacticipant-slug-taken", "taken"),
        ),
        patch("app.pacticipant_routes.db.write_access_audit", audit),
    ):
        response = app_client.post("/v1/tenants/acme/pacticipants", json={"name": "Billing Service"})
    assert response.status_code == 409
    assert audit.call_count == 0


def test_a_permission_refusal_writes_only_the_denial(app_client: TestClient) -> None:
    from app.database import db as app_db

    rows: List[Dict[str, Any]] = []
    with (
        patch.object(app_db, "user_has_permission", return_value=False),
        patch.object(app_db, "is_user_tenant_admin", return_value=False),
        patch.object(app_db, "write_access_audit", side_effect=lambda **kw: rows.append(kw)),
    ):
        response = app_client.post("/v1/tenants/acme/pact-broker/environments", content=b"{}")
    assert response.status_code == 403
    assert [row["action"] for row in rows] == ["permission.denied"]


def test_recording_a_deployment_over_mcp_writes_its_row(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests import test_mcp_pact_routes as mcp

    monkeypatch.setattr(mcp.settings, "internal_service_token", mcp.TOKEN)
    deployed = MagicMock()
    audit = MagicMock()
    with (
        patch.object(mcp.routes, "key_auth_data", return_value=dict(mcp._AUTH)),
        patch.object(mcp.routes, "enforce_permission", return_value=mcp.OWNER),
        patch.object(mcp.routes, "list_environments", return_value=[mcp._PRODUCTION]),
        patch.object(mcp.routes, "record_deployment", return_value=(deployed, True)),
        patch.object(mcp.routes, "deployment_document", return_value={}),
        patch.object(mcp.routes.db, "write_access_audit", audit),
    ):
        body = {
            "tenantId": mcp.TENANT,
            "keyId": mcp.KEY,
            "pacticipant": "billing-service",
            "version": "2.0.0",
            "environment": "production",
        }
        response = mcp.client.post(mcp.BASE + "/record-deployment", json=body, headers=mcp.HEADERS)
    assert response.status_code == 200, response.text
    (call,) = audit.call_args_list
    assert call.kwargs["action"] == "pacts.deployment.record" and call.kwargs["source"] == "api_key"
    assert call.kwargs["target"] == "pacticipant/billing-service/version/2.0.0/environment/e-id"
    assert call.kwargs["detail"] == {"route": "record_mcp_deployment", "via": "mcp", "created": True}
