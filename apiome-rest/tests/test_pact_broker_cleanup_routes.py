"""HTTP contract of the Pact Broker label and delete routes, and of the retention run — PFX-1.11 (#6924).

The store is faked (``test_pact_cleanup_db`` runs it against the real schema). Asserted here:

* every route is gated on the ``pacts`` resource with the right action — a label change is
  ``edit``, a delete ``delete``, a retention dry run ``view`` and applying it ``delete`` — and a
  denial is a 403 before the store is touched;
* the Pact Broker shapes a client parses (``_embedded.labels``, the label document's links, the
  ``Location`` of a new label);
* refusals keep their code and get their status (409 in use, 409 stale plan with the fresh plan,
  422 no selector).
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_retention import CODE_NO_SELECTOR, RetentionError, RetentionKeep, RetentionPlan
from app.pact_retention_store import RetentionPlanChangedError
from app.pacticipant import (
    CODE_VERSION_IN_USE,
    PacticipantLabelRecord,
    PacticipantRecord,
    PacticipantValidationError,
)

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_AUTH = {"tenant_id": _TENANT, "user_id": "u-1", "auth_method": "jwt", "user_email": "dev@example.com"}
_BROKER = "/v1/tenants/acme/pact-broker"
_ROUTES = "app.pact_broker_cleanup_routes"
_RETENTION_ROUTES = "app.pact_retention_routes"

_PACTICIPANT = PacticipantRecord(
    id="22222222-2222-4222-8222-222222222222",
    tenant_id=_TENANT,
    slug="billing-service",
    name="Billing Service",
    labels=["team-billing"],
)
_LABEL = PacticipantLabelRecord(
    name="team-billing",
    pacticipant_id=_PACTICIPANT.id,
    pacticipant_slug="billing-service",
    pacticipant_name="Billing Service",
    created_at="2026-11-24T00:00:00+00:00",
)


def _plan(**overrides: Any) -> RetentionPlan:
    payload: Dict[str, Any] = {
        "dry_run": True,
        "applied": False,
        "plan_digest": "sha256:" + "a" * 64,
        "keep": RetentionKeep(latest_per_branch=2),
        "evaluated": 3,
        "kept": 2,
        "deleted": 1,
        "grace_days": 30,
    }
    payload.update(overrides)
    return RetentionPlan(**payload)


@pytest.fixture
def guard() -> Iterator[MagicMock]:
    """Authenticate both ways and grant everything; yields the broker routes' permission guard."""
    app.dependency_overrides[validate_broker_authentication] = lambda: _AUTH
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    with patch(f"{_ROUTES}.enforce_permission", return_value="u-1") as enforce:
        yield enforce
    app.dependency_overrides.clear()


@pytest.fixture
def store(guard: MagicMock) -> Iterator[Dict[str, MagicMock]]:
    answers = {
        "get_pacticipant": _PACTICIPANT,
        "list_pacticipants": [_PACTICIPANT],
        "list_labels": [{"name": "team-billing"}, {"name": "tier-1"}],
        "get_label": _LABEL,
        "add_label": (_LABEL, True),
        "remove_label": _LABEL,
        "delete_pacticipant": _PACTICIPANT,
        "delete_version": MagicMock(),
    }
    patches = {name: patch(f"{_ROUTES}.{name}", return_value=answer) for name, answer in answers.items()}
    mocks = {name: patcher.start() for name, patcher in patches.items()}
    yield mocks
    for patcher in patches.values():
        patcher.stop()


_CALLS = [
    ("get", "/labels", "view", "list_labels"),
    ("get", "/pacticipants/label/team-billing", "view", "list_pacticipants"),
    ("get", "/pacticipants/billing-service/labels/team-billing", "view", "get_label"),
    ("put", "/pacticipants/billing-service/labels/team-billing", "edit", "add_label"),
    ("delete", "/pacticipants/billing-service/labels/team-billing", "edit", "remove_label"),
    ("delete", "/pacticipants/billing-service", "delete", "delete_pacticipant"),
    ("delete", "/pacticipants/billing-service/versions/1.0.0", "delete", "delete_version"),
]


@pytest.mark.parametrize(("method", "path", "action", "ends_in"), _CALLS)
def test_every_route_is_gated_on_the_pacts_resource(
    guard: MagicMock, store: Dict[str, MagicMock], method: str, path: str, action: str, ends_in: str
) -> None:
    response = getattr(client, method)(f"{_BROKER}{path}")
    assert response.status_code < 300, response.text
    assert guard.call_args.args[2:4] == ("pacts", action)
    assert store[ends_in].call_count == 1


@pytest.mark.parametrize(("method", "path", "action", "ends_in"), _CALLS)
def test_a_denied_request_never_reaches_the_store(
    guard: MagicMock, store: Dict[str, MagicMock], method: str, path: str, action: str, ends_in: str
) -> None:
    guard.side_effect = HTTPException(status_code=403, detail="Forbidden")
    assert getattr(client, method)(f"{_BROKER}{path}").status_code == 403
    assert all(mock.call_count == 0 for mock in store.values())


def test_the_label_documents_have_the_pact_broker_shape(store: Dict[str, MagicMock]) -> None:
    labels = client.get(f"{_BROKER}/labels")
    assert labels.headers["content-type"].startswith("application/hal+json")
    assert labels.json()["_embedded"]["labels"] == [{"name": "team-billing"}, {"name": "tier-1"}]
    assert labels.json()["_links"]["self"]["href"].endswith("/pact-broker/labels")

    created = client.put(f"{_BROKER}/pacticipants/billing-service/labels/team-billing")
    assert created.status_code == 201
    assert created.headers["location"].endswith("/pact-broker/pacticipants/billing-service/labels/team-billing")
    body = created.json()
    assert body["name"] == "team-billing" and body["createdAt"] == "2026-11-24T00:00:00+00:00"
    assert body["_links"]["self"]["title"] == "Label"
    assert body["_links"]["pacticipant"]["href"].endswith("/pact-broker/pacticipants/billing-service")

    store["add_label"].return_value = (_LABEL, False)
    again = client.put(f"{_BROKER}/pacticipants/billing-service/labels/team-billing")
    assert again.status_code == 200 and "location" not in again.headers

    listed = client.get(f"{_BROKER}/pacticipants/label/team-billing").json()
    assert store["list_pacticipants"].call_args.kwargs == {"label": "team-billing"}
    (document,) = listed["_embedded"]["pacticipants"]
    assert document["_embedded"]["labels"][0]["name"] == "team-billing"
    assert document["_links"]["pb:label"]["href"].endswith("/pacticipants/billing-service/labels/{label}")
    assert listed["_links"]["pb:pacticipants"][0]["name"] == "Billing Service"


def test_a_delete_passes_reason_and_force_and_maps_in_use_to_409(store: Dict[str, MagicMock]) -> None:
    response = client.delete(f"{_BROKER}/pacticipants/billing-service", params={"reason": "gone", "force": "true"})
    assert response.status_code == 204
    kwargs = store["delete_pacticipant"].call_args.kwargs
    assert (kwargs["reason"], kwargs["force"]) == ("gone", True)
    store["delete_version"].side_effect = PacticipantValidationError(CODE_VERSION_IN_USE, "deployed")
    refused = client.delete(f"{_BROKER}/pacticipants/billing-service/versions/1.0.0")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == CODE_VERSION_IN_USE


def test_the_broker_routes_no_longer_answer_501(store: Dict[str, MagicMock]) -> None:
    for method, path, _action, _ends in _CALLS:
        assert getattr(client, method)(f"{_BROKER}{path}").status_code != 501


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def retention(guard: MagicMock) -> Iterator[Dict[str, MagicMock]]:
    with patch(f"{_RETENTION_ROUTES}.enforce_permission", return_value="u-1") as enforce, patch(
        f"{_RETENTION_ROUTES}.run_retention", return_value=_plan()
    ) as run:
        yield {"enforce": enforce, "run": run}


def test_a_dry_run_needs_view_and_applying_needs_delete(retention: Dict[str, MagicMock]) -> None:
    dry = client.post("/v1/tenants/acme/pact-retention", json={"keep": {"latest_per_branch": 2}})
    assert dry.status_code == 200, dry.text
    assert retention["enforce"].call_args.args[2:4] == ("pacts", "view")
    assert dry.json()["plan_digest"].startswith("sha256:")
    request = retention["run"].call_args.args[2]
    assert request.dry_run is True and request.keep.latest_per_branch == 2

    retention["run"].return_value = _plan(dry_run=False, applied=True)
    applied = client.post(
        "/v1/tenants/acme/pact-retention",
        json={"keep": {"latest_per_branch": 2}, "dry_run": False, "plan_digest": "sha256:" + "a" * 64},
    )
    assert applied.status_code == 200 and applied.json()["applied"] is True
    assert retention["enforce"].call_args.args[2:4] == ("pacts", "delete")


def test_retention_refusals(retention: Dict[str, MagicMock]) -> None:
    retention["run"].side_effect = RetentionPlanChangedError(_plan(deleted=3))
    stale = client.post("/v1/tenants/acme/pact-retention", json={"keep": {}, "dry_run": False, "plan_digest": "x"})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "pact-retention-plan-changed"
    assert stale.json()["detail"]["plan"]["deleted"] == 3

    retention["run"].side_effect = RetentionError(CODE_NO_SELECTOR, "needs a selector")
    none = client.post("/v1/tenants/acme/pact-retention", json={"keep": {"deployed_or_released": False}})
    assert (none.status_code, none.json()["detail"]["code"]) == (422, CODE_NO_SELECTOR)

    retention["run"].side_effect = PacticipantValidationError("pacticipant-not-found", "no pacticipant 'x'")
    unknown = client.post("/v1/tenants/acme/pact-retention", json={"keep": {}, "pacticipants": ["x"]})
    assert unknown.status_code == 404

    assert client.post("/v1/tenants/acme/pact-retention", json={}).status_code == 422
    retention["enforce"].side_effect = HTTPException(status_code=403, detail="Forbidden")
    retention["run"].reset_mock()
    assert client.post("/v1/tenants/acme/pact-retention", json={"keep": {}}).status_code == 403
    assert retention["run"].call_count == 0
