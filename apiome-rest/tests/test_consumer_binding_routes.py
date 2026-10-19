"""HTTP contract of the RDG-1.8 binding and runtime routes, with the stores faked (#5765).

The live behaviour is in ``test_consumer_binding_db``; this file pins what needs no database:

* each route is gated on the ``consumer_contracts`` action it documents (view, create, delete), and
  a denial never reaches the store;
* a store refusal keeps its status and code;
* the consumer list stays readable when the usage index cannot be read;
* V292's guard rails are in the migration text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.consumer_binding import CODE_BINDING_EXISTS, BindingError, BindingRecord
from app.consumer_contract import ConsumerRecord, ConsumerSummary
from app.main import app
from app.permissions import Action

client = TestClient(app)

_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}
_PROJECT = {"id": "11111111-1111-4111-8111-111111111111"}
_CONSUMER = ConsumerRecord(
    id="33333333-3333-4333-8333-333333333333",
    tenant_id="test-tenant-id",
    project_id=_PROJECT["id"],
    slug="billing-service",
    name="Billing",
)
_BASE = "/v1/tenants/acme/projects/pets/consumers"
_BINDING = BindingRecord(id="b1", consumer_id=_CONSUMER.id, kind="user_agent", name="billing/*", hashed=False)
_MIGRATION = next(
    (Path(__file__).resolve().parents[2] / "apiome-db" / "scripts").glob("V292__*.sql"), None
)


@pytest.fixture(autouse=True)
def _wired() -> Any:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    with patch("app.consumer_binding_routes.resolve_project", return_value=_PROJECT), patch(
        "app.consumer_binding_routes.get_consumer", return_value=_CONSUMER
    ):
        yield
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("method", "path", "body", "action", "store"),
    [
        ("get", "/billing-service/bindings", None, Action.VIEW, "list_bindings"),
        ("post", "/billing-service/bindings", {"kind": "user_agent", "name": "billing/*"}, Action.CREATE,
         "create_binding"),
        ("delete", "/billing-service/bindings/b1", None, Action.DELETE, "delete_binding"),
        ("get", "/billing-service/runtime", None, Action.VIEW, "usage_by_consumer"),
    ],
)
def test_each_route_checks_its_action_and_a_denial_never_reaches_the_store(
    method: str, path: str, body: Dict[str, Any], action: Action, store: str
) -> None:
    with patch(
        "app.consumer_binding_routes.enforce_permission", side_effect=HTTPException(status_code=403, detail="no")
    ) as gate, patch(f"app.consumer_binding_routes.{store}") as touched:
        kwargs = {"json": body} if body else {}
        response = getattr(client, method)(f"{_BASE}{path}", **kwargs)
    assert response.status_code == 403
    assert gate.call_args.args[3] == action
    touched.assert_not_called()


def test_a_store_refusal_keeps_its_status_and_code() -> None:
    with patch("app.consumer_binding_routes.enforce_permission", return_value="u"), patch(
        "app.consumer_binding_routes.create_binding",
        side_effect=BindingError(CODE_BINDING_EXISTS, "taken", status=409),
    ):
        response = client.post(f"{_BASE}/billing-service/bindings", json={"kind": "user_agent", "name": "billing/*"})
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": CODE_BINDING_EXISTS, "message": "taken"}


def test_the_created_binding_is_returned_with_201() -> None:
    with patch("app.consumer_binding_routes.enforce_permission", return_value="u"), patch(
        "app.consumer_binding_routes.create_binding", return_value=_BINDING
    ) as create:
        response = client.post(f"{_BASE}/billing-service/bindings", json={"kind": "user_agent", "name": "billing/*"})
    assert response.status_code == 201 and response.json()["id"] == "b1"
    assert create.call_args.kwargs["consumer_id"] == _CONSUMER.id


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "header", "name": "x-client-id", "value": "v" * 5000 + "SECRET-TAIL"},
        {"kind": "user_agent", "name": "billing/*", "value": "SECRET-TAIL"},
        {"kind": "header", "name": "x-client-id", "value": "SECRET-TAIL", "SECRET-TAIL": 1},
    ],
)
def test_a_malformed_create_never_echoes_the_value(body: Dict[str, Any]) -> None:
    with patch("app.consumer_binding_routes.enforce_permission", return_value="u"), patch(
        "app.consumer_binding_routes.create_binding"
    ) as create:
        response = client.post(f"{_BASE}/billing-service/bindings", json=body)
    assert response.status_code == 422
    assert "SECRET-TAIL" not in response.text
    create.assert_not_called()


def test_the_runtime_window_is_bounded() -> None:
    with patch("app.consumer_binding_routes.enforce_permission", return_value="u"):
        assert client.get(f"{_BASE}/billing-service/runtime?days=0").status_code == 422
        assert client.get(f"{_BASE}/billing-service/runtime?days=400").status_code == 422


def test_the_consumer_list_survives_an_unreadable_usage_index() -> None:
    with patch("app.consumer_contract_routes.enforce_permission", return_value="u"), patch(
        "app.consumer_contract_routes.resolve_project", return_value=_PROJECT
    ), patch(
        "app.consumer_contract_routes.list_consumer_summaries",
        return_value=[ConsumerSummary(consumer=_CONSUMER)],
    ), patch("app.consumer_binding_routes.usage_by_consumer", side_effect=RuntimeError("down")):
        response = client.get(_BASE)
    assert response.status_code == 200
    assert response.json()["consumers"][0]["runtime"] is None


def test_the_consumer_list_carries_runtime_counts() -> None:
    with patch("app.consumer_contract_routes.enforce_permission", return_value="u"), patch(
        "app.consumer_contract_routes.resolve_project", return_value=_PROJECT
    ), patch(
        "app.consumer_contract_routes.list_consumer_summaries",
        return_value=[ConsumerSummary(consumer=_CONSUMER)],
    ), patch("app.consumer_binding_routes.usage_by_consumer", return_value=[]) as read:
        response = client.get(f"{_BASE}?runtime_days=7")
    assert response.status_code == 200
    assert response.json()["consumers"][0]["runtime"]["calls"] == 0
    since, until = read.call_args.kwargs["since"], read.call_args.kwargs["until"]
    assert (until - since).days == 6


@pytest.mark.skipif(_MIGRATION is None, reason="apiome-db not checked out beside apiome-rest")
def test_v292_keeps_its_guard_rails() -> None:
    sql = _MIGRATION.read_text()
    assert "value_hmac ~ '^[0-9a-f]{64}$'" in sql
    assert "NULLS NOT DISTINCT" in sql and "WHERE deleted_at IS NULL" in sql
    assert "slug <> 'anonymous'" in sql
    # No regex repetition above Postgres's limit of 255.
    assert "{1,256}" not in sql
