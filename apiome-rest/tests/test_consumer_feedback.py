"""Portal consumer feedback — COL-4.4 (#4528) acceptance criteria.

* A signed-in Browse reader opens a feedback thread on a published spec element (the version, or an
  operation by method + path).
* The thread appears in the owning team's Discussion list tagged ``consumer``.
* Team replies are visible to the reader; resolve works as on internal threads (either side).
* Signed-out users cannot file feedback.

Reader requests run through the real routes, reader-session check and store; storage is the
in-memory :class:`~tests.fake_comment_db.FakeCommentDb` (threads) and
:class:`~fake_portal_auth_repo.FakePortalAuthRepository` (reader sessions). The team side uses the
real COL-1.1 routes against the same fake, so "visible to the team" is checked end to end.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

import pytest
from fake_portal_auth_repo import FakePortalAuthRepository, RecordingMailer
from fastapi.testclient import TestClient

from app import comment_routes, comment_store, consumer_feedback_store, notification_store, portal_auth_store
from app.auth import validate_authentication
from app.config import settings
from app.main import app
from app.rate_limit import FixedWindowRateLimiter
from tests.fake_comment_db import FakeCommentDb

client = TestClient(app)

# The reader repository's tenant `acme` has this id (fake_portal_auth_repo.TENANT_ID).
TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0002"
VERSION = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0010"
DRAFT = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0011"
PRIVATE = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0012"
OPERATION = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0023"
ALICE = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0101"

FEEDBACK = "/v1/portal/acme/feedback/pets/1.0.0/threads"
TEAM = "/v1/tenants/acme/projects/pets/comment-threads"


@pytest.fixture
def fake(monkeypatch) -> FakeCommentDb:
    """Threads storage with one published public version (+ a draft and a private one)."""
    store = FakeCommentDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_version(PROJECT, VERSION, "1.0.0")
    store.add_version(PROJECT, DRAFT, "2.0.0-draft")
    store.add_version(PROJECT, PRIVATE, "1.5.0")
    store.publish_version(VERSION)
    store.publish_version(PRIVATE, public=False)
    store.add_operation(VERSION, OPERATION, "get", "/pets/{petId}")
    store.add_member(ALICE, "Alice Anders", "alice@example.com")
    store.user_names[ALICE] = "Alice Anders"
    for module in (comment_store, comment_routes, notification_store, consumer_feedback_store):
        monkeypatch.setattr(module, "db", store)
    return store


@pytest.fixture
def readers(monkeypatch) -> FakePortalAuthRepository:
    """The reader-session store."""
    repo = FakePortalAuthRepository()
    monkeypatch.setattr(portal_auth_store, "default_repository", lambda: repo)
    return repo


def _session(readers: FakePortalAuthRepository, fake: FakeCommentDb, email: str, tenant: str = "acme") -> Dict[str, str]:
    """Sign a reader in and return their ``Authorization`` header."""
    mailer = RecordingMailer()
    portal_auth_store.request_magic_link(
        readers, mailer, tenant_slug=tenant, email=email, return_to=None,
        browse_url="", signup_rejection=lambda _e: None,
    )
    grant = portal_auth_store.exchange_token(
        readers, tenant_slug=tenant, token=mailer.last_token(), user_agent=None, session_ttl=timedelta(days=1)
    )
    fake.user_names[grant.reader.user_id] = grant.reader.name or email
    return {"Authorization": f"Reader {grant.session_token}"}


@pytest.fixture
def ada(readers, fake) -> Dict[str, str]:
    """A signed-in reader of `acme`."""
    return _session(readers, fake, "ada@example.com")


@pytest.fixture
def team():
    """Act as Alice, a workspace member, on the internal routes."""
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": TENANT, "user_id": ALICE, "auth_method": "jwt"
    }
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _send(headers, **payload: Any):
    body = {"target": "version", "body": "The 404 response has no schema."} | payload
    return client.post(FEEDBACK, json=body, headers=headers)


# ---------------------------------------------------------------------------------------------
# Anonymous users cannot file feedback
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Reader prs_unknown_session_token_value"}, {"Authorization": "Bearer x.y.z"}],
)
def test_no_live_reader_session_cannot_file_or_read(fake, readers, headers):
    assert _send(headers).status_code == 401
    response = client.get(FEEDBACK, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "portal-session-invalid"
    assert fake.threads == {}


def test_a_reader_of_another_portal_cannot_file_here(fake, readers):
    globex = _session(readers, fake, "ada@example.com", tenant="globex")
    assert _send(globex).status_code == 401
    assert fake.threads == {}


def test_a_revoked_session_is_refused_on_the_next_request(fake, readers, ada):
    portal_auth_store.revoke_session(readers, ada["Authorization"].split(" ", 1)[1])
    assert _send(ada).status_code == 401


# ---------------------------------------------------------------------------------------------
# A reader opens a thread on a published spec element
# ---------------------------------------------------------------------------------------------


def test_a_reader_opens_feedback_on_the_whole_version(fake, ada):
    response = _send(ada)
    assert response.status_code == 201, response.text
    thread = response.json()
    assert thread["target"] == "version" and thread["operation"] is None and thread["status"] == "open"
    (comment,) = thread["comments"]
    assert comment["body"] == "The 404 response has no schema." and comment["from_team"] is False
    (row,) = fake.threads.values()
    assert row["origin"] == "consumer" and row["anchor_type"] == "version" and row["anchor_id"] == VERSION


def test_a_reader_opens_feedback_on_an_operation_by_method_and_path(fake, ada):
    response = _send(ada, target="operation", method="get", path="/pets/{petId}")
    assert response.status_code == 201, response.text
    assert response.json()["operation"] == {"method": "GET", "path": "/pets/{petId}"}
    (row,) = fake.threads.values()
    assert row["anchor_type"] == "operation" and row["anchor_id"] == OPERATION


def test_an_unknown_operation_is_404(fake, ada):
    response = _send(ada, target="operation", method="DELETE", path="/pets/{petId}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "feedback-operation-not-found"


@pytest.mark.parametrize("label", ["2.0.0-draft", "1.5.0", "9.9.9"])
def test_only_a_published_public_version_takes_feedback(fake, ada, label):
    response = client.post(
        f"/v1/portal/acme/feedback/pets/{label}/threads", json={"target": "version", "body": "hi"}, headers=ada
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "feedback-version-not-found"


@pytest.mark.parametrize(
    "payload",
    [
        {"target": "operation", "body": "x"},
        {"target": "version", "method": "GET", "path": "/pets", "body": "x"},
        {"target": "class", "body": "x"},
        {"target": "version", "body": ""},
    ],
)
def test_malformed_requests_are_422(fake, ada, payload):
    assert client.post(FEEDBACK, json=payload, headers=ada).status_code == 422


def test_a_blank_body_is_refused(fake, ada):
    response = _send(ada, body="   ")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "comment-empty-body"


def test_reader_mentions_are_never_resolved(fake, ada):
    _send(ada, body="@alice please look")
    (comment,) = fake.comments.values()
    assert comment["mentions"] == []
    assert fake.member_reads == 0


# ---------------------------------------------------------------------------------------------
# The thread appears in the team's Discussion list tagged consumer
# ---------------------------------------------------------------------------------------------


def test_the_team_sees_the_thread_tagged_consumer(fake, ada, team):
    _send(ada)
    client.post(TEAM, json={"version": "1.0.0", "anchor_type": "version", "body": "internal note"})
    listing = client.get(TEAM).json()
    assert {t["origin"] for t in listing["threads"]} == {"consumer", "internal"}
    consumer = client.get(TEAM, params={"origin": "consumer", "include_total": "true"}).json()
    assert consumer["total"] == 1 and consumer["threads"][0]["origin"] == "consumer"
    internal = client.get(TEAM, params={"origin": "internal", "include_total": "true"}).json()
    assert internal["total"] == 1 and internal["threads"][0]["root_comment"]["body"] == "internal note"


def test_an_unknown_origin_filter_is_422(fake, team):
    assert client.get(TEAM, params={"origin": "partner"}).status_code == 422


# ---------------------------------------------------------------------------------------------
# Team replies are visible to the reader; resolve works as on internal threads
# ---------------------------------------------------------------------------------------------


def test_team_replies_reach_the_reader_without_internal_details(fake, ada, team):
    thread_id = _send(ada).json()["id"]
    assert client.post(f"{TEAM}/{thread_id}/comments", json={"body": "Fixed in 1.0.1, thanks!"}).status_code == 201

    (thread,) = client.get(FEEDBACK, headers=ada).json()["threads"]
    reader, staff = thread["comments"]
    assert reader["from_team"] is False
    assert staff == {**staff, "from_team": True, "author_name": "Alice Anders", "body": "Fixed in 1.0.1, thanks!"}
    assert set(staff) == {"id", "body", "from_team", "author_name", "created_at", "edited_at"}
    assert ALICE not in str(thread)


def test_the_reader_replies_and_the_team_sees_it(fake, ada, team):
    thread_id = _send(ada).json()["id"]
    response = client.post(f"{FEEDBACK}/{thread_id}/comments", json={"body": "Any ETA?"}, headers=ada)
    assert response.status_code == 201
    assert [c["body"] for c in response.json()["comments"]][-1] == "Any ETA?"
    detail = client.get(f"{TEAM}/{thread_id}").json()
    assert [c["body"] for c in detail["comments"]] == ["The 404 response has no schema.", "Any ETA?"]


def test_the_team_resolves_and_the_reader_sees_it(fake, ada, team):
    thread_id = _send(ada).json()["id"]
    assert client.post(f"{TEAM}/{thread_id}/resolve").json()["status"] == "resolved"
    (thread,) = client.get(FEEDBACK, headers=ada).json()["threads"]
    assert thread["status"] == "resolved" and thread["resolved_at"]


def test_resolving_a_consumer_thread_notifies_the_team_but_never_the_reader(fake, ada, team):
    bob = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0102"
    fake.add_member(bob, "Bob Brown", "bob@example.com")
    thread_id = _send(ada).json()["id"]
    reader_id = next(iter(fake.threads.values()))["created_by"]
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": TENANT, "user_id": bob, "auth_method": "jwt"}
    client.post(f"{TEAM}/{thread_id}/comments", json={"body": "Looking"})
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": TENANT, "user_id": ALICE, "auth_method": "jwt"}
    client.post(f"{TEAM}/{thread_id}/resolve")
    recipients = {row["user_id"] for row in fake.notifications}
    assert bob in recipients
    assert reader_id not in recipients


def test_the_reader_resolves_and_reopens_their_own_thread(fake, ada, team):
    thread_id = _send(ada).json()["id"]
    resolved = client.post(f"{FEEDBACK}/{thread_id}/resolve", headers=ada)
    assert resolved.status_code == 200 and resolved.json()["status"] == "resolved"
    assert client.get(f"{TEAM}/{thread_id}").json()["thread"]["status"] == "resolved"
    reopened = client.post(f"{FEEDBACK}/{thread_id}/reopen", headers=ada)
    assert reopened.json()["status"] == "open" and reopened.json()["resolved_at"] is None


# ---------------------------------------------------------------------------------------------
# A reader only ever sees their own feedback
# ---------------------------------------------------------------------------------------------


def test_readers_never_see_or_touch_each_others_threads(fake, readers, ada, team):
    thread_id = _send(ada).json()["id"]
    lin = _session(readers, fake, "lin@example.com")
    assert client.get(FEEDBACK, headers=lin).json()["threads"] == []
    for suffix in ("comments", "resolve", "reopen"):
        payload = {"json": {"body": "hi"}} if suffix == "comments" else {}
        response = client.post(f"{FEEDBACK}/{thread_id}/{suffix}", headers=lin, **payload)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "feedback-thread-not-found"


def test_internal_threads_are_invisible_to_readers(fake, ada, team):
    internal_id = client.post(TEAM, json={"version": "1.0.0", "anchor_type": "version", "body": "secret"}).json()[
        "thread"
    ]["id"]
    assert client.get(FEEDBACK, headers=ada).json()["threads"] == []
    assert client.post(f"{FEEDBACK}/{internal_id}/resolve", headers=ada).status_code == 404


def test_the_list_is_scoped_to_the_version_in_the_url(fake, ada):
    fake.add_version(PROJECT, "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0013", "1.1.0")
    fake.publish_version("0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0013")
    _send(ada)
    assert client.get("/v1/portal/acme/feedback/pets/1.1.0/threads", headers=ada).json()["threads"] == []


# ---------------------------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------------------------


def test_feedback_shares_the_comment_budget(fake, ada, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_public_per_minute", 10_000)
    monkeypatch.setattr(settings, "rate_limit_authenticated_per_minute", 10_000)
    monkeypatch.setattr(settings, "comment_create_rate_limit_per_minute", 2)
    monkeypatch.setattr(comment_routes, "_comment_limiter", FixedWindowRateLimiter())
    assert _send(ada).status_code == 201
    assert _send(ada).status_code == 201
    response = _send(ada)
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "comment-rate-limited"
