"""HTTP contract tests for comment threads — COL-1.1 (#4513).

``/v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads`` and its sub-resources. Storage
is the in-memory :class:`tests.fake_comment_db.FakeCommentDb`; everything above it is real — the
RBAC guard, the store's anchoring/ownership/deletion rules, and the mention resolver. Asserted here:

* **The acceptance criteria.** A thread on a class is listed by its version; ``mentions`` is filled
  by server-side parsing; read access grants commenting while edit/delete stay with the author or a
  tenant administrator; every endpoint is in the OpenAPI contract.
* Anchors must exist in the named version, and a version anchor is the version itself.
* Resolve/reopen stamps and clears resolution; deleting the last comment deletes the thread.
* The list filters and paging; scoping across projects; the per-user create rate limit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient

from app import comment_routes, comment_store
from app.auth import validate_authentication
from app.config import settings
from app.main import app
from app.rate_limit import FixedWindowRateLimiter
from tests.fake_comment_db import FakeCommentDb

client = TestClient(app)

TENANT = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0001"
PROJECT = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0002"
OTHER_PROJECT = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0003"
VERSION_1 = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0010"
VERSION_2 = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0011"
OTHER_VERSION = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0012"
CLASS_ID = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0020"
PROPERTY_ID = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0021"
PATH_ID = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0022"
OPERATION_ID = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0023"
ALICE = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0101"
BOB = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0102"
CAROL_ADMIN = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0103"
MISSING = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0999"

BASE = "/v1/tenants/acme/projects/pets/comment-threads"


@pytest.fixture
def fake(monkeypatch) -> FakeCommentDb:
    """A seeded store, swapped in beneath the routes and the store."""
    store = FakeCommentDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_project(TENANT, OTHER_PROJECT, "orders")
    store.add_version(PROJECT, VERSION_1, "1.0.0")
    store.add_version(PROJECT, VERSION_2, "2.0.0")
    store.add_version(OTHER_PROJECT, OTHER_VERSION, "1.0.0")
    store.add_anchor(VERSION_1, "class", CLASS_ID)
    store.add_anchor(VERSION_1, "property", PROPERTY_ID)
    store.add_anchor(VERSION_1, "path", PATH_ID)
    store.add_anchor(VERSION_1, "operation", OPERATION_ID)
    store.add_member(ALICE, "Alice Anders", "alice@example.com")
    store.add_member(BOB, "Bob Brown", "bob.brown@example.com")
    store.add_member(CAROL_ADMIN, "Carol Admin", "carol@example.com")
    store.admins.add((TENANT, CAROL_ADMIN))
    monkeypatch.setattr(comment_store, "db", store)
    monkeypatch.setattr(comment_routes, "db", store)
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


def _open(
    anchor_type: str = "class",
    anchor_id: Optional[str] = CLASS_ID,
    version: str = VERSION_1,
    body: str = "Why is this nullable?",
    base: str = BASE,
):
    """Open a thread and return the raw response."""
    payload: Dict[str, Any] = {"version": version, "anchor_type": anchor_type, "body": body}
    if anchor_id is not None:
        payload["anchor_id"] = anchor_id
    return client.post(base, json=payload)


def _opened(**kwargs: Any) -> Dict[str, Any]:
    """Open a thread, assert it was created, and return the detail."""
    response = _open(**kwargs)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------------------------
# Acceptance criteria
# ---------------------------------------------------------------------------------------------


def test_a_thread_on_a_class_is_listed_by_its_version(fake, act_as):
    detail = _opened()
    thread = detail["thread"]
    assert thread["anchor_type"] == "class"
    assert thread["anchor_id"] == CLASS_ID
    assert thread["version_id"] == VERSION_1
    assert thread["status"] == "open"
    assert thread["created_by"] == ALICE
    assert thread["created_by_name"] == "Alice Anders"
    assert [c["body"] for c in detail["comments"]] == ["Why is this nullable?"]

    by_id = client.get(BASE, params={"version": VERSION_1}).json()
    by_label = client.get(BASE, params={"version": "1.0.0"}).json()
    for listing in (by_id, by_label):
        assert [t["id"] for t in listing["threads"]] == [thread["id"]]
        assert listing["threads"][0]["root_comment"]["body"] == "Why is this nullable?"
        assert listing["threads"][0]["comment_count"] == 1
        assert listing["total"] == 1

    assert client.get(BASE, params={"version": VERSION_2}).json()["threads"] == []


def test_mentions_are_resolved_server_side_against_tenant_members(fake, act_as):
    detail = _opened(body="@bob.brown and @CarolAdmin — thoughts? (not `@alice`)")
    assert detail["comments"][0]["mentions"] == [BOB, CAROL_ADMIN]

    reply = client.post(f"{BASE}/{detail['thread']['id']}/comments", json={"body": "@alice@example.com"})
    assert reply.status_code == 201
    assert reply.json()["mentions"] == [ALICE]


def test_a_client_cannot_supply_its_own_mentions(fake, act_as):
    response = client.post(
        BASE,
        json={
            "version": VERSION_1,
            "anchor_type": "class",
            "anchor_id": CLASS_ID,
            "body": "hi",
            "mentions": [BOB],
        },
    )
    assert response.status_code == 422


_ROUTES = [
    ("get", BASE, None),
    ("post", BASE, {"version": VERSION_1, "anchor_type": "class", "anchor_id": CLASS_ID, "body": "x"}),
    ("get", f"{BASE}/{MISSING}", None),
    ("delete", f"{BASE}/{MISSING}", None),
    ("post", f"{BASE}/{MISSING}/resolve", None),
    ("post", f"{BASE}/{MISSING}/reopen", None),
    ("post", f"{BASE}/{MISSING}/comments", {"body": "x"}),
    ("patch", f"{BASE}/{MISSING}/comments/{MISSING}", {"body": "x"}),
    ("delete", f"{BASE}/{MISSING}/comments/{MISSING}", None),
]


@pytest.mark.parametrize("method,url,payload", _ROUTES)
def test_every_route_requires_project_read_access(fake, act_as, method, url, payload):
    fake.grants = {("versions", "view")}
    kwargs = {"json": payload} if payload is not None else {}
    response = client.request(method.upper(), url, **kwargs)
    assert response.status_code == 403
    assert "projects:view" in response.text
    assert fake.audits and fake.audits[-1]["detail"] == {"resource": "projects", "action": "view"}


def test_project_read_access_alone_grants_commenting(fake, act_as):
    fake.grants = {("projects", "view")}
    detail = _opened()
    thread_id = detail["thread"]["id"]
    assert client.post(f"{BASE}/{thread_id}/comments", json={"body": "agreed"}).status_code == 201
    assert client.post(f"{BASE}/{thread_id}/resolve").status_code == 200
    assert client.post(f"{BASE}/{thread_id}/reopen").status_code == 200
    assert client.get(f"{BASE}/{thread_id}").status_code == 200


def test_only_the_author_or_a_tenant_admin_can_edit_a_comment(fake, act_as):
    detail = _opened()
    thread_id = detail["thread"]["id"]
    comment_id = detail["comments"][0]["id"]
    url = f"{BASE}/{thread_id}/comments/{comment_id}"

    act_as(BOB)
    refused = client.patch(url, json={"body": "hijacked"})
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "comment-forbidden"

    act_as(ALICE)
    edited = client.patch(url, json={"body": "Why is this nullable, @bob.brown?"})
    assert edited.status_code == 200
    assert edited.json()["body"] == "Why is this nullable, @bob.brown?"
    assert edited.json()["mentions"] == [BOB]
    assert edited.json()["edited_at"] is not None

    act_as(CAROL_ADMIN)
    moderated = client.patch(url, json={"body": "[removed by an administrator]"})
    assert moderated.status_code == 200
    assert moderated.json()["mentions"] == []
    assert moderated.json()["author_id"] == ALICE


def test_only_the_author_or_a_tenant_admin_can_delete_a_comment(fake, act_as):
    detail = _opened()
    thread_id = detail["thread"]["id"]
    alice_reply = client.post(f"{BASE}/{thread_id}/comments", json={"body": "second"}).json()
    carol_target = client.post(f"{BASE}/{thread_id}/comments", json={"body": "third"}).json()

    act_as(BOB)
    refused = client.delete(f"{BASE}/{thread_id}/comments/{alice_reply['id']}")
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "comment-forbidden"

    act_as(ALICE)
    own = client.delete(f"{BASE}/{thread_id}/comments/{alice_reply['id']}")
    assert own.status_code == 200
    assert own.json() == {"deleted": True, "thread_deleted": False}

    act_as(CAROL_ADMIN)
    assert client.delete(f"{BASE}/{thread_id}/comments/{carol_target['id']}").status_code == 200
    assert client.get(f"{BASE}/{thread_id}").json()["thread"]["comment_count"] == 1


def test_only_the_opener_or_a_tenant_admin_can_delete_a_thread(fake, act_as):
    first = _opened()["thread"]["id"]
    second = _opened()["thread"]["id"]

    act_as(BOB)
    assert client.delete(f"{BASE}/{first}").status_code == 403

    act_as(ALICE)
    assert client.delete(f"{BASE}/{first}").status_code == 204
    assert client.get(f"{BASE}/{first}").status_code == 404

    act_as(CAROL_ADMIN)
    assert client.delete(f"{BASE}/{second}").status_code == 204
    assert fake.comments == {}


def test_a_role_grant_is_not_ownership(fake, act_as):
    """Holding every RBAC permission still does not let a non-author edit someone's words."""
    detail = _opened()
    act_as(BOB)
    fake.grants = None
    url = f"{BASE}/{detail['thread']['id']}/comments/{detail['comments'][0]['id']}"
    assert client.patch(url, json={"body": "nope"}).status_code == 403


def test_an_api_key_without_a_user_cannot_comment(fake, act_as):
    act_as(None, auth_method="api_key")
    response = _open()
    assert response.status_code == 403
    assert fake.threads == {}


def test_every_comment_endpoint_is_in_the_openapi_contract(fake):
    expected = {
        "/v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads": {"get", "post"},
        "/v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}": {"get", "delete"},
        "/v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}/resolve": {"post"},
        "/v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}/reopen": {"post"},
        "/v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}/comments": {"post"},
        "/v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}/comments/{comment_id}": {
            "patch",
            "delete",
        },
    }
    live = app.openapi()["paths"]
    committed = json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text(encoding="utf-8")
    )["paths"]
    for path, methods in expected.items():
        assert methods <= set(live[path]), path
        assert methods <= set(committed.get(path, {})), f"openapi.json is stale for {path}"


# ---------------------------------------------------------------------------------------------
# Anchoring
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "anchor_type,anchor_id",
    [("property", PROPERTY_ID), ("path", PATH_ID), ("operation", OPERATION_ID)],
)
def test_threads_anchor_to_every_element_kind(fake, act_as, anchor_type, anchor_id):
    thread = _opened(anchor_type=anchor_type, anchor_id=anchor_id)["thread"]
    assert (thread["anchor_type"], thread["anchor_id"]) == (anchor_type, anchor_id)


def test_a_version_anchor_defaults_to_the_version_itself(fake, act_as):
    thread = _opened(anchor_type="version", anchor_id=None)["thread"]
    assert thread["anchor_id"] == VERSION_1 == thread["version_id"]
    explicit = _opened(anchor_type="version", anchor_id=VERSION_1.upper())["thread"]
    assert explicit["anchor_id"] == VERSION_1


def test_a_version_anchor_cannot_name_another_version(fake, act_as):
    response = _open(anchor_type="version", anchor_id=VERSION_2)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "comment-invalid-anchor"


def test_an_element_of_another_version_is_not_found(fake, act_as):
    response = _open(version=VERSION_2)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "comment-anchor-not-found"


@pytest.mark.parametrize("anchor_id", [None, "not-a-uuid"])
def test_a_non_version_anchor_needs_an_element_id(fake, act_as, anchor_id):
    response = _open(anchor_id=anchor_id)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "comment-invalid-anchor"


def test_an_unknown_anchor_type_is_rejected_by_the_contract(fake, act_as):
    assert _open(anchor_type="canvas").status_code == 422


def test_uppercase_anchor_ids_are_stored_canonically(fake, act_as):
    thread = _opened(anchor_id=CLASS_ID.upper())["thread"]
    assert thread["anchor_id"] == CLASS_ID


# ---------------------------------------------------------------------------------------------
# Resolution, replies, deletion
# ---------------------------------------------------------------------------------------------


def test_resolve_records_who_and_when_and_reopen_clears_it(fake, act_as):
    thread_id = _opened()["thread"]["id"]

    act_as(BOB)
    resolved = client.post(f"{BASE}/{thread_id}/resolve").json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == BOB
    assert resolved["resolved_at"] is not None

    again = client.post(f"{BASE}/{thread_id}/resolve").json()
    assert again["resolved_at"] == resolved["resolved_at"]
    assert again["last_activity_at"] == resolved["last_activity_at"]

    reopened = client.post(f"{BASE}/{thread_id}/reopen").json()
    assert reopened["status"] == "open"
    assert reopened["resolved_by"] is None and reopened["resolved_at"] is None


def test_a_resolved_thread_accepts_replies_and_stays_resolved(fake, act_as):
    older = _opened()["thread"]["id"]
    newer = _opened()["thread"]["id"]
    client.post(f"{BASE}/{older}/resolve")
    assert client.post(f"{BASE}/{older}/comments", json={"body": "one more thing"}).status_code == 201

    detail = client.get(f"{BASE}/{older}").json()
    assert detail["thread"]["status"] == "resolved"
    assert [c["body"] for c in detail["comments"]] == ["Why is this nullable?", "one more thing"]
    listed = [t["id"] for t in client.get(BASE).json()["threads"]]
    assert listed == [older, newer]


def test_deleting_the_last_comment_deletes_the_thread(fake, act_as):
    detail = _opened()
    thread_id = detail["thread"]["id"]
    response = client.delete(f"{BASE}/{thread_id}/comments/{detail['comments'][0]['id']}")
    assert response.json() == {"deleted": True, "thread_deleted": True}
    assert client.get(f"{BASE}/{thread_id}").status_code == 404


@pytest.mark.parametrize("body", ["", "   \n\t "])
def test_a_blank_comment_is_refused(fake, act_as, body):
    response = _open(body=body)
    assert response.status_code in (400, 422)
    if response.status_code == 400:
        assert response.json()["detail"]["code"] == "comment-empty-body"
    thread_id = _opened()["thread"]["id"]
    reply = client.post(f"{BASE}/{thread_id}/comments", json={"body": body})
    assert reply.status_code in (400, 422)


def test_an_oversized_comment_is_refused(fake, act_as):
    assert _open(body="x" * 20_001).status_code == 422


# ---------------------------------------------------------------------------------------------
# Scoping and not-found
# ---------------------------------------------------------------------------------------------


def test_a_thread_is_not_reachable_through_another_project(fake, act_as):
    thread_id = _opened()["thread"]["id"]
    other = "/v1/tenants/acme/projects/orders/comment-threads"
    assert client.get(f"{other}/{thread_id}").status_code == 404
    assert client.post(f"{other}/{thread_id}/comments", json={"body": "x"}).status_code == 404
    assert client.get(other).json()["threads"] == []


def test_a_version_of_another_project_is_not_found(fake, act_as):
    response = _open(version=OTHER_VERSION)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "comment-version-not-found"


@pytest.mark.parametrize(
    "method,url,code",
    [
        ("get", "/v1/tenants/acme/projects/nope/comment-threads", "comment-project-not-found"),
        ("get", f"{BASE}/{MISSING}", "comment-thread-not-found"),
        ("get", f"{BASE}/not-a-uuid", "comment-thread-not-found"),
        ("post", f"{BASE}/{MISSING}/resolve", "comment-thread-not-found"),
        ("delete", f"{BASE}/{MISSING}", "comment-thread-not-found"),
    ],
)
def test_unknown_resources_are_404_with_a_stable_code(fake, act_as, method, url, code):
    response = client.request(method.upper(), url)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == code


def test_an_unknown_comment_is_404(fake, act_as):
    thread_id = _opened()["thread"]["id"]
    for method, payload in (("patch", {"body": "x"}), ("delete", None)):
        kwargs = {"json": payload} if payload else {}
        response = client.request(method.upper(), f"{BASE}/{thread_id}/comments/{MISSING}", **kwargs)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "comment-not-found"


def test_the_project_may_be_named_by_id(fake, act_as):
    base = f"/v1/tenants/acme/projects/{PROJECT}/comment-threads"
    thread_id = _opened(base=base)["thread"]["id"]
    assert client.get(f"{BASE}/{thread_id}").status_code == 200


# ---------------------------------------------------------------------------------------------
# List filters
# ---------------------------------------------------------------------------------------------


def test_list_filters_combine(fake, act_as):
    on_class = _opened()["thread"]["id"]
    on_path = _opened(anchor_type="path", anchor_id=PATH_ID, body="@bob.brown rename?")["thread"]["id"]
    on_version = _opened(anchor_type="version", anchor_id=None)["thread"]["id"]
    client.post(f"{BASE}/{on_class}/resolve")

    def ids(**params):
        return {t["id"] for t in client.get(BASE, params=params).json()["threads"]}

    assert ids() == {on_class, on_path, on_version}
    assert ids(status="resolved") == {on_class}
    assert ids(status="open") == {on_path, on_version}
    assert ids(anchor_type="path") == {on_path}
    assert ids(anchor_type="class", anchor_id=CLASS_ID) == {on_class}
    assert ids(version=VERSION_1, status="open", anchor_type="version") == {on_version}

    assert ids(mentions_me="true") == set()
    act_as(BOB)
    assert ids(mentions_me="true") == {on_path}


def test_mentions_me_matches_a_mention_in_any_reply(fake, act_as):
    thread_id = _opened()["thread"]["id"]
    client.post(f"{BASE}/{thread_id}/comments", json={"body": "cc @bob.brown"})
    act_as(BOB)
    listing = client.get(BASE, params={"mentions_me": "true"}).json()
    assert [t["id"] for t in listing["threads"]] == [thread_id]
    assert listing["threads"][0]["root_comment"]["mentions"] == []


def test_list_pages_with_a_total(fake, act_as):
    opened = [_opened()["thread"]["id"] for _ in range(3)]
    page = client.get(BASE, params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 3
    assert page["count"] == 2
    assert (page["limit"], page["offset"]) == (2, 1)
    assert [t["id"] for t in page["threads"]] == [opened[1], opened[0]]


def test_a_malformed_anchor_filter_is_400(fake, act_as):
    response = client.get(BASE, params={"anchor_id": "nope"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "comment-invalid-anchor"


@pytest.mark.parametrize("params", [{"status": "closed"}, {"anchor_type": "canvas"}, {"limit": 0}])
def test_list_filter_vocabularies_are_enforced(fake, act_as, params):
    assert client.get(BASE, params=params).status_code == 422


# ---------------------------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def tight_budget(monkeypatch):
    """Enable rate limiting with a two-comment budget and a fresh limiter."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "comment_create_rate_limit_per_minute", 2)
    monkeypatch.setattr(comment_routes, "_comment_limiter", FixedWindowRateLimiter())


def test_creating_comments_is_rate_limited_per_user(fake, act_as, tight_budget):
    thread_id = _opened()["thread"]["id"]
    assert client.post(f"{BASE}/{thread_id}/comments", json={"body": "two"}).status_code == 201

    over = client.post(f"{BASE}/{thread_id}/comments", json={"body": "three"})
    assert over.status_code == 429
    assert over.json()["detail"]["code"] == "comment-rate-limited"
    # The global middleware stamps its own X-RateLimit-* headers on every response, so only the
    # comment budget's Retry-After is asserted here.
    assert int(over.headers["Retry-After"]) >= 0
    assert _open().status_code == 429

    act_as(BOB)
    assert client.post(f"{BASE}/{thread_id}/comments", json={"body": "bob's own budget"}).status_code == 201


def test_reads_and_moderation_are_not_rate_limited(fake, act_as, tight_budget):
    detail = _opened()
    thread_id = detail["thread"]["id"]
    comment_url = f"{BASE}/{thread_id}/comments/{detail['comments'][0]['id']}"
    for _ in range(3):
        assert client.get(BASE).status_code == 200
        assert client.patch(comment_url, json={"body": "edited"}).status_code == 200
        assert client.post(f"{BASE}/{thread_id}/resolve").status_code == 200
