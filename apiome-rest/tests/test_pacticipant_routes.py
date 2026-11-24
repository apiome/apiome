"""HTTP contract tests for the pacticipant registry — PFX-1.1 (#6914).

``/v1/tenants/{tenant_slug}/pacticipants`` and the versions, branches and tags under it. The store
is faked (``test_pacticipant_db`` runs it against the real schema); what is asserted here is the
endpoint's own contract:

* every route is gated on the ``pacts`` RBAC resource, with *deleting* separated from recording,
  and a denial is a 403 before the store is touched;
* a refusal from the registry becomes the HTTP status that matches its kind (404 unknown, 409
  handle taken, 400 anything malformed) and always carries the stable code;
* recording a version answers 201 the first time and 200 after;
* the response shapes a client parses, and the tenant the store is asked for.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.pacticipant import (
    CODE_CONSUMER_NOT_FOUND,
    CODE_INVALID_BRANCH,
    CODE_INVALID_LABEL,
    CODE_INVALID_REASON,
    CODE_INVALID_SLUG,
    CODE_INVALID_TAG,
    CODE_INVALID_URL,
    CODE_INVALID_VERSION,
    CODE_LABEL_NOT_FOUND,
    CODE_NOT_DELETED,
    CODE_NOT_FOUND,
    CODE_PROJECT_NOT_FOUND,
    CODE_RESTORE_CONFLICT,
    CODE_SLUG_TAKEN,
    CODE_VERSION_IN_USE,
    CODE_VERSION_NOT_FOUND,
    PacticipantBranchRecord,
    PacticipantLabelRecord,
    PacticipantRecord,
    PacticipantValidationError,
    PacticipantVersionRecord,
    RecordedPacticipantVersion,
)
from app.pacticipant_store import BRANCHES_ORDER, PACTICIPANTS_ORDER, VERSIONS_ORDER

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "jwt", "user_email": "dev@example.com"}
_BASE = "/v1/tenants/acme/pacticipants"
_ROUTES = "app.pacticipant_routes"


def _pacticipant(**overrides: Any) -> PacticipantRecord:
    """A stored pacticipant as the store returns one."""
    payload: Dict[str, Any] = {
        "id": "22222222-2222-4222-8222-222222222222",
        "tenant_id": _TENANT,
        "slug": "billing-service",
        "name": "Billing Service",
        "main_branch": "main",
    }
    payload.update(overrides)
    return PacticipantRecord(**payload)


def _version(**overrides: Any) -> PacticipantVersionRecord:
    """A stored version as the store returns one."""
    payload: Dict[str, Any] = {
        "id": "33333333-3333-4333-8333-333333333333",
        "pacticipant_id": "22222222-2222-4222-8222-222222222222",
        "number": "1.0.0",
        "seq": 1,
        "branches": ["main"],
        "tags": ["prod"],
    }
    payload.update(overrides)
    return PacticipantVersionRecord(**payload)


def _label(**overrides: Any) -> PacticipantLabelRecord:
    """A stored label as the store returns one."""
    payload: Dict[str, Any] = {
        "name": "team-billing",
        "pacticipant_id": "22222222-2222-4222-8222-222222222222",
        "pacticipant_slug": "billing-service",
        "pacticipant_name": "Billing Service",
    }
    payload.update(overrides)
    return PacticipantLabelRecord(**payload)


def _branch(**overrides: Any) -> PacticipantBranchRecord:
    """A stored branch as the store returns one."""
    payload: Dict[str, Any] = {
        "id": "44444444-4444-4444-8444-444444444444",
        "pacticipant_id": "22222222-2222-4222-8222-222222222222",
        "name": "main",
        "head_version_id": "33333333-3333-4333-8333-333333333333",
        "head_version": "1.0.0",
        "is_main": True,
    }
    payload.update(overrides)
    return PacticipantBranchRecord(**payload)


@pytest.fixture(autouse=True)
def guard() -> Iterator[MagicMock]:
    """Authenticate every request and grant every permission; yields the permission guard."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce
    app.dependency_overrides.clear()


@pytest.fixture
def store() -> Iterator[Dict[str, MagicMock]]:
    """Every store function the routes call, faked with a plausible answer."""
    answers = {
        "list_pacticipants": [_pacticipant()],
        "create_pacticipant": _pacticipant(),
        "get_pacticipant": _pacticipant(),
        "update_pacticipant": _pacticipant(name="Billing"),
        "delete_pacticipant": _pacticipant(),
        "list_versions": [_version()],
        "record_version": RecordedPacticipantVersion(version=_version(), created=True, head_moved=True),
        "get_version": _version(),
        "add_tag": _version(),
        "list_branches": [_branch()],
        # PFX-1.11 (#6924): deletes, restores and labels.
        "restore_pacticipant": _pacticipant(),
        "delete_version": _version(deleted_at="2026-11-24T00:00:00+00:00", delete_cause="version"),
        "restore_version": _version(),
        "list_labels": [{"name": "team-billing"}],
        "list_pacticipant_labels": [_label()],
        "get_label": _label(),
        "add_label": (_label(), True),
        "remove_label": _label(),
    }
    patches = {name: patch(f"{_ROUTES}.{name}", return_value=answer) for name, answer in answers.items()}
    mocks = {name: patcher.start() for name, patcher in patches.items()}
    yield mocks
    for patcher in patches.values():
        patcher.stop()


# (method, path, json body, resource action, store function the route ends in)
_CALLS = [
    ("get", "", None, "view", "list_pacticipants"),
    ("post", "", {"name": "Billing Service"}, "create", "create_pacticipant"),
    ("get", "/billing-service", None, "view", "get_pacticipant"),
    ("patch", "/billing-service", {"name": "Billing"}, "edit", "update_pacticipant"),
    ("delete", "/billing-service", None, "delete", "delete_pacticipant"),
    ("get", "/billing-service/versions", None, "view", "list_versions"),
    ("put", "/billing-service/versions/1.0.0", {"branch": "main"}, "create", "record_version"),
    ("get", "/billing-service/versions/1.0.0", None, "view", "get_version"),
    ("put", "/billing-service/versions/1.0.0/tags/prod", None, "create", "add_tag"),
    ("get", "/billing-service/branches", None, "view", "list_branches"),
    ("post", "/billing-service/restore", None, "delete", "restore_pacticipant"),
    ("delete", "/billing-service/versions/1.0.0", None, "delete", "delete_version"),
    ("post", "/billing-service/versions/1.0.0/restore", None, "delete", "restore_version"),
    ("get", "/billing-service/labels", None, "view", "list_pacticipant_labels"),
    ("get", "/billing-service/labels/team-billing", None, "view", "get_label"),
    ("put", "/billing-service/labels/team-billing", None, "edit", "add_label"),
    ("delete", "/billing-service/labels/team-billing", None, "edit", "remove_label"),
]


def _send(method: str, path: str, body: Any) -> Any:
    kwargs = {"json": body} if body is not None else {}
    return getattr(client, method)(f"{_BASE}{path}", **kwargs)


# ===========================================================================
# Permissions
# ===========================================================================


@pytest.mark.parametrize(("method", "path", "body", "action", "ends_in"), _CALLS)
def test_every_route_is_gated_on_the_pacts_resource(
    guard: MagicMock, store: Dict[str, MagicMock], method: str, path: str, body: Any, action: str, ends_in: str
) -> None:
    response = _send(method, path, body)
    assert response.status_code < 300, response.text
    assert guard.call_count == 1
    assert guard.call_args.args[2:4] == ("pacts", action)
    assert store[ends_in].call_count == 1


@pytest.mark.parametrize(("method", "path", "body", "action", "ends_in"), _CALLS)
def test_a_denied_request_never_reaches_the_store(
    guard: MagicMock, store: Dict[str, MagicMock], method: str, path: str, body: Any, action: str, ends_in: str
) -> None:
    guard.side_effect = HTTPException(status_code=403, detail="Forbidden")
    assert _send(method, path, body).status_code == 403
    assert all(mock.call_count == 0 for mock in store.values())


def test_a_credential_without_a_tenant_is_refused(store: Dict[str, MagicMock]) -> None:
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": "u", "auth_method": "jwt"}
    assert client.get(_BASE).status_code == 403
    assert store["list_pacticipants"].call_count == 0


def test_the_store_is_asked_for_the_authenticated_tenant_not_the_url(store: Dict[str, MagicMock]) -> None:
    client.get("/v1/tenants/someone-else/pacticipants/billing-service")
    assert store["get_pacticipant"].call_args.args[1:] == (_TENANT, "billing-service")


# ===========================================================================
# Refusals
# ===========================================================================


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (CODE_NOT_FOUND, 404),
        (CODE_VERSION_NOT_FOUND, 404),
        (CODE_PROJECT_NOT_FOUND, 404),
        (CODE_CONSUMER_NOT_FOUND, 404),
        (CODE_SLUG_TAKEN, 409),
        (CODE_INVALID_SLUG, 400),
        (CODE_INVALID_URL, 400),
        (CODE_INVALID_BRANCH, 400),
        (CODE_INVALID_TAG, 400),
        (CODE_INVALID_VERSION, 400),
    ],
)
def test_a_refusal_keeps_its_code_and_gets_the_matching_status(
    store: Dict[str, MagicMock], code: str, status: int
) -> None:
    store["create_pacticipant"].side_effect = PacticipantValidationError(code, "because")
    response = client.post(_BASE, json={"name": "Billing Service"})
    assert response.status_code == status
    assert response.json()["detail"] == {"code": code, "message": "because"}


@pytest.mark.parametrize(("method", "path", "body", "action", "ends_in"), _CALLS[2:])
def test_an_unknown_pacticipant_is_a_404_on_every_route(
    store: Dict[str, MagicMock], method: str, path: str, body: Any, action: str, ends_in: str
) -> None:
    missing = PacticipantValidationError(CODE_NOT_FOUND, "no pacticipant 'billing-service' in this tenant")
    for name in ("get_pacticipant", "update_pacticipant", "delete_pacticipant", "restore_pacticipant"):
        store[name].side_effect = missing
    response = _send(method, path, body)
    assert response.status_code == 404 and response.json()["detail"]["code"] == CODE_NOT_FOUND


def test_unknown_body_fields_are_refused(store: Dict[str, MagicMock]) -> None:
    assert client.post(_BASE, json={"name": "A", "tenant_id": "x"}).status_code == 422
    assert client.patch(f"{_BASE}/billing-service", json={"slug": "renamed"}).status_code == 422
    assert client.put(f"{_BASE}/billing-service/versions/1.0.0", json={"number": "2"}).status_code == 422
    assert all(mock.call_count == 0 for mock in store.values())


def test_a_malformed_cursor_is_a_400(store: Dict[str, MagicMock]) -> None:
    for path in ("", "/billing-service/versions", "/billing-service/branches"):
        assert client.get(f"{_BASE}{path}", params={"cursor": "not-a-cursor"}).status_code == 400


# ===========================================================================
# Shapes
# ===========================================================================


def test_listing_pages_by_cursor(store: Dict[str, MagicMock]) -> None:
    rows = [_pacticipant(slug="accounts", id="a" * 8 + "-1111-4111-8111-111111111111"), _pacticipant()]
    store["list_pacticipants"].return_value = rows
    body = client.get(_BASE, params={"limit": 1}).json()
    assert store["list_pacticipants"].call_args.kwargs == {"limit": 2, "cursor": None, "label": None, "deleted": False}
    assert [row["slug"] for row in body["pacticipants"]] == ["accounts"]
    assert body["count"] == 1 and body["has_more"] is True
    assert PACTICIPANTS_ORDER.decode(body["next_cursor"]) == ["accounts", rows[0].id]

    client.get(_BASE, params={"cursor": body["next_cursor"]})
    assert store["list_pacticipants"].call_args.kwargs["cursor"] == ["accounts", rows[0].id]


def test_versions_and_branches_page_the_same_way(store: Dict[str, MagicMock]) -> None:
    store["list_versions"].return_value = [_version(seq=9), _version(seq=4, number="0.9.0")]
    versions = client.get(f"{_BASE}/billing-service/versions", params={"limit": 1, "branch": "main", "tag": "prod"})
    assert versions.json()["has_more"] is True
    assert VERSIONS_ORDER.decode(versions.json()["next_cursor"]) == [9]
    assert store["list_versions"].call_args.kwargs == {
        "branch": "main",
        "tag": "prod",
        "limit": 2,
        "cursor": None,
        "deleted": False,
    }

    store["list_branches"].return_value = [_branch(), _branch(name="release", is_main=False)]
    branches = client.get(f"{_BASE}/billing-service/branches", params={"limit": 1}).json()
    assert branches["branches"][0]["head_version"] == "1.0.0" and branches["has_more"] is True
    assert BRANCHES_ORDER.decode(branches["next_cursor"])[0] == "main"


def test_registering_answers_201_with_the_record_and_names_the_actor(store: Dict[str, MagicMock]) -> None:
    response = client.post(_BASE, json={"name": "Billing Service", "project": "billing-api"})
    assert response.status_code == 201
    assert response.json()["slug"] == "billing-service"
    call = store["create_pacticipant"].call_args
    assert call.args[1] == _TENANT and call.args[2].project == "billing-api"
    assert (call.kwargs["actor"].user_id, call.kwargs["actor"].label) == ("test-user-id", "dev@example.com")


def test_a_patch_passes_on_which_fields_were_sent(store: Dict[str, MagicMock]) -> None:
    client.patch(f"{_BASE}/billing-service", json={"project": None})
    assert store["update_pacticipant"].call_args.args[3].model_fields_set == {"project"}


def test_deleting_answers_an_empty_204(store: Dict[str, MagicMock]) -> None:
    response = client.delete(f"{_BASE}/billing-service")
    assert response.status_code == 204 and response.content == b""


def test_recording_a_version_is_201_once_and_200_after(store: Dict[str, MagicMock]) -> None:
    first = client.put(f"{_BASE}/billing-service/versions/1.0.0", json={"branch": "main", "tags": ["prod"]})
    assert first.status_code == 201
    assert first.json()["created"] is True and first.json()["head_moved"] is True
    assert first.json()["version"]["branches"] == ["main"]
    call = store["record_version"].call_args
    assert call.args[1] == store["get_pacticipant"].return_value and call.args[2] == "1.0.0"
    assert (call.args[3].branch, call.args[3].tags) == ("main", ["prod"])

    store["record_version"].return_value = RecordedPacticipantVersion(
        version=_version(), created=False, head_moved=False
    )
    again = client.put(f"{_BASE}/billing-service/versions/1.0.0", json={"branch": "main"})
    assert again.status_code == 200 and again.json()["created"] is False


def test_a_version_can_be_recorded_without_a_body(store: Dict[str, MagicMock]) -> None:
    assert client.put(f"{_BASE}/billing-service/versions/3f2a9c1").status_code == 201
    details = store["record_version"].call_args.args[3]
    assert (details.build_url, details.branch, details.tags) == (None, None, [])


def test_a_tag_may_contain_a_slash(store: Dict[str, MagicMock]) -> None:
    response = client.put(f"{_BASE}/billing-service/versions/1.0.0/tags/feat/new-invoice")
    assert response.status_code == 200
    assert store["add_tag"].call_args.args[2:] == ("1.0.0", "feat/new-invoice")


def test_an_unknown_version_is_a_404(store: Dict[str, MagicMock]) -> None:
    store["get_version"].side_effect = PacticipantValidationError(CODE_VERSION_NOT_FOUND, "no version")
    response = client.get(f"{_BASE}/billing-service/versions/9.9.9")
    assert response.status_code == 404 and response.json()["detail"]["code"] == CODE_VERSION_NOT_FOUND


# ===========================================================================
# PFX-1.11 (#6924): soft delete, restore, labels
# ===========================================================================


def test_the_workspace_labels_list_is_gated_and_paged(guard: MagicMock, store: Dict[str, MagicMock]) -> None:
    response = client.get("/v1/tenants/acme/pacticipant-labels")
    assert response.status_code == 200, response.text
    assert response.json()["labels"] == [{"name": "team-billing"}]
    assert guard.call_args.args[2:4] == ("pacts", "view")
    assert client.get("/v1/tenants/acme/pacticipant-labels", params={"cursor": "bad"}).status_code == 400


def test_delete_passes_the_reason_and_force_and_the_actor(guard: MagicMock, store: Dict[str, MagicMock]) -> None:
    response = client.delete(f"{_BASE}/billing-service", params={"reason": "retired service", "force": "true"})
    assert response.status_code == 204
    kwargs = store["delete_pacticipant"].call_args.kwargs
    assert kwargs["reason"] == "retired service" and kwargs["force"] is True
    assert kwargs["actor"].label == "dev@example.com"
    version = client.delete(f"{_BASE}/billing-service/versions/1.0.0", params={"reason": "bad build"})
    assert version.status_code == 204
    assert store["delete_version"].call_args.kwargs["reason"] == "bad build"
    assert store["delete_version"].call_args.kwargs["force"] is False


def test_a_reason_over_500_characters_is_refused_before_the_store(store: Dict[str, MagicMock]) -> None:
    assert client.delete(f"{_BASE}/billing-service", params={"reason": "x" * 501}).status_code == 422
    assert store["delete_pacticipant"].call_count == 0


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (CODE_VERSION_IN_USE, 409),
        (CODE_RESTORE_CONFLICT, 409),
        (CODE_NOT_DELETED, 409),
        (CODE_LABEL_NOT_FOUND, 404),
        (CODE_INVALID_LABEL, 400),
        (CODE_INVALID_REASON, 400),
    ],
)
def test_the_cleanup_refusals_get_their_status(store: Dict[str, MagicMock], code: str, status: int) -> None:
    store["delete_version"].side_effect = PacticipantValidationError(code, "because")
    response = client.delete(f"{_BASE}/billing-service/versions/1.0.0")
    assert response.status_code == status
    assert response.json()["detail"] == {"code": code, "message": "because"}


def test_the_state_filter_lists_deleted_rows_with_their_purge_time(store: Dict[str, MagicMock]) -> None:
    store["list_pacticipants"].return_value = [_pacticipant(deleted_at="2026-11-01T00:00:00+00:00")]
    body = client.get(_BASE, params={"state": "deleted", "label": "team-billing"}).json()
    assert store["list_pacticipants"].call_args.kwargs["deleted"] is True
    assert store["list_pacticipants"].call_args.kwargs["label"] == "team-billing"
    assert body["pacticipants"][0]["purge_after"].startswith("2026-12-01")
    store["list_versions"].return_value = [_version(deleted_at="2026-11-01T00:00:00+00:00", delete_cause="retention")]
    versions = client.get(f"{_BASE}/billing-service/versions", params={"state": "deleted"}).json()
    assert store["list_versions"].call_args.kwargs["deleted"] is True
    assert versions["versions"][0]["delete_cause"] == "retention"
    assert client.get(_BASE, params={"state": "gone"}).status_code == 422


def test_a_new_label_is_201_and_a_repeat_200(store: Dict[str, MagicMock]) -> None:
    assert client.put(f"{_BASE}/billing-service/labels/team-billing").status_code == 201
    store["add_label"].return_value = (_label(), False)
    again = client.put(f"{_BASE}/billing-service/labels/team-billing")
    assert again.status_code == 200 and again.json()["name"] == "team-billing"
    # A label may contain a slash.
    client.put(f"{_BASE}/billing-service/labels/team/billing")
    assert store["add_label"].call_args.args[3] == "team/billing"
