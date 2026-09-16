"""HTTP contract tests for the notification inbox — COL-3.1 (#4521).

``/v1/tenants/{tenant_slug}/notifications`` and its two sub-resources. Storage is the in-memory
:class:`tests.fake_notification_db.FakeNotificationDb`; everything above it is real. Asserted here:

* **The acceptance criteria.** The unread count is correct and follows ``read_at``; marking read
  moves it and nothing else does; every endpoint is in the OpenAPI contract.
* An inbox is the caller's own: another user's rows are neither listed nor counted nor markable,
  and a tenant administrator gets no privileged view.
* No route asks for a ``resource:action`` — the fake refuses every permission and the inbox still
  reads, which is what "no RBAC resource" means in practice.
* A credential that resolves to no user has no inbox (``403 notification-forbidden``).
* The filters, the paging, and the shape of a row the notification centre (COL-3.2) will render.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient

from app import notification_routes, notification_store
from app.auth import validate_authentication
from app.main import app
from app.notifications import NOTIFICATION_TYPES, RETENTION_PER_USER
from tests.fake_notification_db import FakeNotificationDb

client = TestClient(app)

TENANT = "5a2b7c10-0000-4000-8000-00000000a001"
OTHER_TENANT = "5a2b7c10-0000-4000-8000-00000000a002"
PROJECT = "5a2b7c10-0000-4000-8000-00000000b001"
VERSION = "5a2b7c10-0000-4000-8000-00000000c001"
ALICE = "5a2b7c10-0000-4000-8000-00000000e001"
BOB = "5a2b7c10-0000-4000-8000-00000000e002"
CAROL_ADMIN = "5a2b7c10-0000-4000-8000-00000000e003"

BASE = "/v1/tenants/acme/notifications"


@pytest.fixture
def fake(monkeypatch) -> FakeNotificationDb:
    """An empty inbox store, swapped in beneath the routes and the store."""
    store = FakeNotificationDb()
    store.add_user(BOB, "Bob Brown")
    store.admins.add((TENANT, CAROL_ADMIN))
    monkeypatch.setattr(notification_store, "db", store)
    monkeypatch.setattr(notification_routes, "db", store)
    return store


@pytest.fixture
def act_as():
    """Switch the authenticated caller; defaults to Alice on a session."""

    def _set(user_id: Optional[str] = ALICE, *, auth_method: str = "jwt") -> None:
        auth: Dict[str, Any] = {"tenant_id": TENANT, "auth_method": auth_method}
        if user_id:
            auth["user_id"] = user_id
        app.dependency_overrides[validate_authentication] = lambda: auth

    _set()
    yield _set
    app.dependency_overrides.pop(validate_authentication, None)


def _seed(fake: FakeNotificationDb, *, user_id: str = ALICE, **kwargs: Any) -> str:
    """Put one notification in an inbox."""
    return fake.add_notification(
        tenant_id=kwargs.pop("tenant_id", TENANT),
        user_id=user_id,
        actor_id=kwargs.pop("actor_id", BOB),
        project_id=kwargs.pop("project_id", PROJECT),
        version_id=kwargs.pop("version_id", VERSION),
        **kwargs,
    )


# ---------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------


def test_the_inbox_lists_newest_first_with_the_actors_name(fake, act_as):
    _seed(fake, type="mention", payload={"thread_id": "t1"})
    _seed(fake, type="version_published")
    body = client.get(BASE).json()
    assert [row["type"] for row in body["notifications"]] == ["version_published", "mention"]
    assert body["count"] == 2 and body["total"] == 2
    row = body["notifications"][1]
    assert row["actor_id"] == BOB
    assert row["actor_name"] == "Bob Brown"
    assert row["project_id"] == PROJECT and row["version_id"] == VERSION
    assert row["payload"] == {"thread_id": "t1"}
    assert row["read_at"] is None


def test_an_inbox_holds_only_its_owners_rows(fake, act_as):
    _seed(fake, user_id=BOB)
    assert client.get(BASE).json()["notifications"] == []
    act_as(BOB)
    assert len(client.get(BASE).json()["notifications"]) == 1


def test_an_inbox_is_scoped_to_the_authenticated_tenant(fake, act_as):
    _seed(fake, tenant_id=OTHER_TENANT)
    assert client.get(BASE).json()["total"] == 0


def test_a_tenant_administrator_reads_no_colleagues_inbox(fake, act_as):
    _seed(fake, user_id=ALICE)
    act_as(CAROL_ADMIN)
    assert client.get(BASE).json()["total"] == 0


def test_no_inbox_route_asks_for_a_permission(fake, act_as):
    # The fake refuses every resource:action; the inbox still reads.
    _seed(fake)
    assert client.get(BASE).status_code == 200
    assert client.get(f"{BASE}/unread-count").status_code == 200
    assert client.post(f"{BASE}/read", json={"all": True}).status_code == 200
    assert fake.audits == []


def test_a_credential_with_no_user_has_no_inbox(fake, act_as):
    act_as(None, auth_method="api_key")
    response = client.get(BASE)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "notification-forbidden"


def test_the_unread_filter_and_the_type_filter_combine(fake, act_as):
    _seed(fake, type="mention")
    _seed(fake, type="mention", read=True)
    _seed(fake, type="review_requested")
    assert client.get(BASE, params={"unread": "true"}).json()["total"] == 2
    assert client.get(BASE, params={"type": "mention"}).json()["total"] == 2
    assert client.get(BASE, params={"unread": "true", "type": "mention"}).json()["total"] == 1


def test_an_unknown_type_filter_is_refused_rather_than_ignored(fake, act_as):
    assert client.get(BASE, params={"type": "nonsense"}).status_code == 422


def test_the_list_pages_and_reports_the_total(fake, act_as):
    for _ in range(5):
        _seed(fake)
    body = client.get(BASE, params={"limit": 2, "offset": 2}).json()
    assert (body["count"], body["total"], body["limit"], body["offset"]) == (2, 5, 2, 2)


def test_reading_the_list_never_marks_anything_read(fake, act_as):
    _seed(fake)
    client.get(BASE)
    assert client.get(f"{BASE}/unread-count").json()["total"] == 1


# ---------------------------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------------------------


def test_the_unread_count_reports_every_type_including_zeroes(fake, act_as):
    _seed(fake, type="mention")
    _seed(fake, type="mention")
    _seed(fake, type="review_decision", read=True)
    body = client.get(f"{BASE}/unread-count").json()
    assert body["total"] == 2
    assert body["by_type"]["mention"] == 2
    assert set(body["by_type"]) == set(NOTIFICATION_TYPES)
    assert body["by_type"]["review_decision"] == 0


def test_an_empty_inbox_counts_zero(fake, act_as):
    body = client.get(f"{BASE}/unread-count").json()
    assert body["total"] == 0
    assert set(body["by_type"]) == set(NOTIFICATION_TYPES)


# ---------------------------------------------------------------------------------------------
# Marking read
# ---------------------------------------------------------------------------------------------


def test_marking_ids_read_moves_the_count_and_reports_the_new_one(fake, act_as):
    first = _seed(fake, type="mention")
    _seed(fake, type="mention")
    body = client.post(f"{BASE}/read", json={"ids": [first]}).json()
    assert body["updated"] == 1
    assert body["unread"]["total"] == 1
    assert client.get(f"{BASE}/unread-count").json()["total"] == 1


def test_marking_all_read_clears_the_badge(fake, act_as):
    for _ in range(3):
        _seed(fake)
    body = client.post(f"{BASE}/read", json={"all": True}).json()
    assert body["updated"] == 3
    assert body["unread"]["total"] == 0


def test_marking_read_is_idempotent(fake, act_as):
    identifier = _seed(fake)
    assert client.post(f"{BASE}/read", json={"ids": [identifier]}).json()["updated"] == 1
    assert client.post(f"{BASE}/read", json={"ids": [identifier]}).json()["updated"] == 0


def test_a_row_stays_read_and_keeps_its_stamp(fake, act_as):
    identifier = _seed(fake)
    client.post(f"{BASE}/read", json={"ids": [identifier]})
    row = client.get(BASE).json()["notifications"][0]
    assert row["read_at"] is not None


def test_marking_somebody_elses_notification_changes_nothing(fake, act_as):
    theirs = _seed(fake, user_id=BOB)
    assert client.post(f"{BASE}/read", json={"ids": [theirs]}).json()["updated"] == 0
    act_as(BOB)
    assert client.get(f"{BASE}/unread-count").json()["total"] == 1


def test_marking_nothing_is_not_an_error(fake, act_as):
    _seed(fake)
    body = client.post(f"{BASE}/read", json={}).json()
    assert body["updated"] == 0
    assert body["unread"]["total"] == 1


def test_a_malformed_id_marks_nothing_rather_than_failing(fake, act_as):
    _seed(fake)
    assert client.post(f"{BASE}/read", json={"ids": ["not-a-uuid"]}).json()["updated"] == 0


def test_the_mark_read_body_refuses_unknown_fields_and_oversized_lists(fake, act_as):
    assert client.post(f"{BASE}/read", json={"every": True}).status_code == 422
    too_many = [f"5a2b7c10-0000-4000-8000-{index:012d}" for index in range(RETENTION_PER_USER + 1)]
    assert client.post(f"{BASE}/read", json={"ids": too_many}).status_code == 422


# ---------------------------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------------------------


def test_every_notification_endpoint_is_in_the_openapi_contract(fake):
    expected = {
        "/v1/tenants/{tenant_slug}/notifications": {"get"},
        "/v1/tenants/{tenant_slug}/notifications/unread-count": {"get"},
        "/v1/tenants/{tenant_slug}/notifications/read": {"post"},
    }
    live = app.openapi()["paths"]
    committed = json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text(encoding="utf-8")
    )["paths"]
    for path, methods in expected.items():
        assert methods <= set(live[path]), path
        assert methods <= set(committed.get(path, {})), f"openapi.json is stale for {path}"


def test_there_is_no_endpoint_that_creates_a_notification():
    created = {
        path
        for path, methods in app.openapi()["paths"].items()
        if path.endswith("/notifications") and "post" in methods
    }
    assert created == set()
