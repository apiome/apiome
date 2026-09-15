"""HTTP contract tests for review requests — COL-2.1 (#4517).

``/v1/tenants/{tenant_slug}/projects/{project_ref}/reviews`` and the version review status. Storage
is the in-memory :class:`tests.fake_review_db.FakeReviewDb`, and the version's content fingerprint
is the fake's; everything above storage is real — the RBAC guard, the store's rules, and the state
machine. Asserted here:

* **The acceptance criteria.** The state machine end to end, including the re-request path that
  resets every decision to ``pending`` once the spec changed; decisions as immutable history that
  stays queryable after every reset; only unpublished versions entering review; an audit row for
  every transition and decision.
* The rules around them: one open review per version, the reviewer list, who may request, decide,
  and withdraw, refusing decisions on changed content, list filters, project scoping, and the
  OpenAPI contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import pytest
from fastapi.testclient import TestClient

from app import comment_store, review_routes, review_store
from app.auth import validate_authentication
from app.main import app
from app.review_lifecycle import is_allowed_transition
from tests.fake_review_db import ORIGINAL_FINGERPRINT, FakeReviewDb

client = TestClient(app)

TENANT = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0001"
PROJECT = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0002"
OTHER_PROJECT = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0003"
VERSION_1 = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0010"
VERSION_2 = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0011"
OTHER_VERSION = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0012"
ALICE = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0101"
BOB = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0102"
DAVE = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0103"
CAROL_ADMIN = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0104"
STRANGER = "7d2c4e10-8a1b-4c3d-9e2f-1a2b3c4d0999"

BASE = "/v1/tenants/acme/projects/pets/reviews"
VERSIONS = "/v1/tenants/acme/projects/pets/versions"


@pytest.fixture
def fake(monkeypatch) -> FakeReviewDb:
    """A seeded store, swapped in beneath the routes, the review store, and the comment store."""
    store = FakeReviewDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_project(TENANT, OTHER_PROJECT, "orders")
    store.add_version(PROJECT, VERSION_1, "1.0.0")
    store.add_version(PROJECT, VERSION_2, "2.0.0")
    store.add_version(OTHER_PROJECT, OTHER_VERSION, "1.0.0")
    store.add_member(ALICE, "Alice Anders", "alice@example.com")
    store.add_member(BOB, "Bob Brown", "bob@example.com")
    store.add_member(DAVE, "Dave Dunn", "dave@example.com")
    store.add_member(CAROL_ADMIN, "Carol Admin", "carol@example.com")
    store.admins.add((TENANT, CAROL_ADMIN))
    for module in (comment_store, review_store, review_routes):
        monkeypatch.setattr(module, "db", store)
    monkeypatch.setattr(review_store, "spec_fingerprint", store.spec_fingerprint)
    return store


@pytest.fixture
def act_as():
    """Switch the authenticated caller; defaults to Alice on a session."""

    def _set(user_id: Optional[str] = ALICE) -> None:
        auth: Dict[str, Any] = {"tenant_id": TENANT, "auth_method": "jwt", "user_id": user_id}
        app.dependency_overrides[validate_authentication] = lambda: auth

    _set()
    yield _set
    app.dependency_overrides.pop(validate_authentication, None)


def _request(reviewers: Sequence[str] = (BOB, DAVE), version: str = VERSION_1, base: str = BASE):
    """Request a review and return the raw response."""
    return client.post(base, json={"version": version, "reviewers": list(reviewers)})


def _requested(**kwargs: Any) -> Dict[str, Any]:
    """Request a review, assert it was created, and return the detail."""
    response = _request(**kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def _decide(review_id: str, decision: str, note: Optional[str] = None):
    """Record the current caller's decision and return the raw response."""
    payload: Dict[str, Any] = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return client.post(f"{BASE}/{review_id}/decision", json=payload)


def _decided(review_id: str, decision: str, note: Optional[str] = None) -> Dict[str, Any]:
    """Record a decision, assert it was accepted, and return the detail."""
    response = _decide(review_id, decision, note)
    assert response.status_code == 200, response.text
    return response.json()


def _re_request(review_id: str, payload: Optional[Dict[str, Any]] = None):
    """Re-request a review and return the raw response."""
    return client.post(f"{BASE}/{review_id}/re-request", json=payload)


def _code(response) -> str:
    """The stable refusal code of an error response."""
    return response.json()["detail"]["code"]


def _actions(fake: FakeReviewDb):
    """The audit actions written so far, in order."""
    return [row["action"] for row in fake.workflow_audits]


def _decisions(rows):
    """``(round, user_id, decision)`` for each reviewer row."""
    return [(row["round"], row["user_id"], row["decision"]) for row in rows]


# ---------------------------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------------------------


def test_requesting_a_review_moves_a_draft_version_into_review(fake, act_as):
    before = client.get(f"{VERSIONS}/1.0.0/review")
    assert before.status_code == 200, before.text
    assert before.json() == {
        "version_id": VERSION_1,
        "version_label": "1.0.0",
        "published": False,
        "state": "draft",
        "review": None,
    }

    detail = _requested()
    review = detail["review"]
    assert review["state"] == "in_review"
    assert review["round"] == 1
    assert review["requested_by"] == ALICE
    assert review["requested_by_name"] == "Alice Anders"
    assert review["version_label"] == "1.0.0"
    assert review["spec_fingerprint"] == ORIGINAL_FINGERPRINT
    assert (review["reviewer_count"], review["pending_count"]) == (2, 2)
    assert review["closed_at"] is None
    assert _decisions(detail["reviewers"]) == [(1, BOB, "pending"), (1, DAVE, "pending")]
    assert detail["history"] == []
    assert detail["spec_changed"] is False

    after = client.get(f"{VERSIONS}/{VERSION_1}/review").json()
    assert after["state"] == "in_review"
    assert after["review"]["review"]["id"] == review["id"]

    [audit] = fake.workflow_audits
    assert audit["action"] == "review.requested"
    assert audit["actor_id"] == ALICE
    assert audit["version_id"] == VERSION_1
    assert audit["detail"]["from_state"] == "draft"
    assert audit["detail"]["to_state"] == "in_review"
    assert audit["detail"]["reviewers"] == [BOB, DAVE]


def test_the_review_is_approved_once_every_reviewer_approved(fake, act_as):
    review_id = _requested()["review"]["id"]

    act_as(BOB)
    first = _decided(review_id, "approve")
    assert first["review"]["state"] == "in_review"
    assert (first["review"]["approved_count"], first["review"]["pending_count"]) == (1, 1)

    act_as(DAVE)
    second = _decided(review_id, "approve", note="Looks right to me.")
    assert second["review"]["state"] == "approved"
    assert _decisions(second["reviewers"]) == [(1, BOB, "approve"), (1, DAVE, "approve")]
    dave = second["reviewers"][1]
    assert dave["note"] == "Looks right to me."
    assert dave["decided_at"] is not None

    assert _actions(fake) == ["review.requested", "review.decision", "review.decision", "review.state_changed"]
    changed = fake.workflow_audits[-1]
    assert changed["actor_id"] == DAVE
    assert (changed["detail"]["from_state"], changed["detail"]["to_state"]) == ("in_review", "approved")


def test_one_request_for_changes_decides_the_round_at_once(fake, act_as):
    review_id = _requested()["review"]["id"]

    act_as(BOB)
    detail = _decided(review_id, "request_changes", note="Rename `id` to `petId`.")
    assert detail["review"]["state"] == "changes_requested"
    assert detail["review"]["pending_count"] == 1

    act_as(DAVE)
    late = _decide(review_id, "approve")
    assert late.status_code == 409
    assert _code(late) == "review-not-in-review"
    assert _actions(fake)[-1] == "review.state_changed"
    assert fake.workflow_audits[-1]["detail"]["to_state"] == "changes_requested"


def test_a_re_request_after_a_spec_change_resets_every_decision_to_pending(fake, act_as):
    review_id = _requested()["review"]["id"]
    act_as(BOB)
    _decided(review_id, "request_changes", note="Rename `id` to `petId`.")

    act_as(ALICE)
    new_fingerprint = fake.change_spec(VERSION_1)
    response = _re_request(review_id)
    assert response.status_code == 200, response.text
    detail = response.json()

    assert detail["review"]["state"] == "in_review"
    assert detail["review"]["round"] == 2
    assert detail["review"]["spec_fingerprint"] == new_fingerprint
    assert detail["spec_changed"] is False
    assert _decisions(detail["reviewers"]) == [(2, BOB, "pending"), (2, DAVE, "pending")]
    assert _decisions(detail["history"]) == [(1, BOB, "request_changes"), (1, DAVE, "pending")]
    assert detail["history"][0]["note"] == "Rename `id` to `petId`."

    audit = fake.workflow_audits[-1]
    assert audit["action"] == "review.re_requested"
    assert audit["detail"]["from_state"] == "changes_requested"
    assert audit["detail"]["to_state"] == "in_review"
    assert (audit["detail"]["previous_round"], audit["detail"]["round"]) == (1, 2)


def test_an_approved_review_is_stale_after_a_spec_change_until_re_requested(fake, act_as):
    review_id = _requested()["review"]["id"]
    act_as(BOB)
    _decided(review_id, "approve")
    act_as(DAVE)
    approved = _decided(review_id, "approve")
    assert approved["review"]["state"] == "approved"

    fake.change_spec(VERSION_1)
    stale = client.get(f"{BASE}/{review_id}").json()
    assert stale["review"]["state"] == "approved"
    assert stale["spec_changed"] is True

    act_as(ALICE)
    detail = _re_request(review_id, {}).json()
    assert detail["review"]["state"] == "in_review"
    assert (detail["review"]["approved_count"], detail["review"]["pending_count"]) == (0, 2)
    # The round-1 approvals are history, exactly as they were recorded.
    assert detail["history"] == approved["reviewers"]
    assert fake.workflow_audits[-1]["detail"]["from_state"] == "approved"


def test_a_re_request_without_a_spec_change_is_refused(fake, act_as):
    review_id = _requested()["review"]["id"]
    act_as(BOB)
    _decided(review_id, "request_changes")

    act_as(ALICE)
    response = _re_request(review_id)
    assert response.status_code == 409
    assert _code(response) == "review-spec-unchanged"
    review = client.get(f"{BASE}/{review_id}").json()["review"]
    assert (review["state"], review["round"]) == ("changes_requested", 1)
    assert "review.re_requested" not in _actions(fake)


def test_a_decision_on_changed_content_is_refused_until_re_requested(fake, act_as):
    review_id = _requested()["review"]["id"]
    act_as(BOB)
    _decided(review_id, "approve")

    fake.change_spec(VERSION_1)
    act_as(DAVE)
    refused = _decide(review_id, "approve")
    assert refused.status_code == 409
    assert _code(refused) == "review-spec-changed"
    assert client.get(f"{BASE}/{review_id}").json()["review"]["state"] == "in_review"

    # Bob's approval judged the old content, so it must not count towards approving the new one.
    act_as(ALICE)
    detail = _re_request(review_id).json()
    assert (detail["review"]["state"], detail["review"]["round"]) == ("in_review", 2)
    assert _decisions(detail["reviewers"]) == [(2, BOB, "pending"), (2, DAVE, "pending")]
    assert _decisions(detail["history"]) == [(1, BOB, "approve"), (1, DAVE, "pending")]
    assert fake.workflow_audits[-1]["detail"]["from_state"] == "in_review"


def test_past_decisions_remain_queryable_after_every_reset(fake, act_as):
    review_id = _requested()["review"]["id"]
    act_as(BOB)
    _decided(review_id, "request_changes", note="round one")

    act_as(ALICE)
    fake.change_spec(VERSION_1)
    _re_request(review_id)
    act_as(BOB)
    _decided(review_id, "approve")
    act_as(DAVE)
    round_two = _decided(review_id, "request_changes", note="round two")

    act_as(ALICE)
    fake.change_spec(VERSION_1)
    detail = _re_request(review_id).json()

    assert detail["review"]["round"] == 3
    assert _decisions(detail["history"]) == [
        (1, BOB, "request_changes"),
        (1, DAVE, "pending"),
        (2, BOB, "approve"),
        (2, DAVE, "request_changes"),
    ]
    assert [row["note"] for row in detail["history"]] == ["round one", None, None, "round two"]
    assert detail["history"][2:] == round_two["reviewers"]


# ---------------------------------------------------------------------------------------------
# Only drafts, one open review
# ---------------------------------------------------------------------------------------------


def test_a_published_version_cannot_enter_review(fake, act_as):
    fake.publish(VERSION_2)
    response = _request(version="2.0.0")
    assert response.status_code == 409
    assert _code(response) == "review-version-published"
    assert fake.workflow_audits == []

    status = client.get(f"{VERSIONS}/2.0.0/review").json()
    assert (status["published"], status["state"], status["review"]) == (True, "draft", None)


def test_a_version_published_mid_review_takes_no_decisions_or_re_requests(fake, act_as):
    review_id = _requested()["review"]["id"]
    fake.publish(VERSION_1)

    act_as(BOB)
    decision = _decide(review_id, "approve")
    assert decision.status_code == 409
    assert _code(decision) == "review-version-published"

    act_as(ALICE)
    fake.change_spec(VERSION_1)
    re_request = _re_request(review_id)
    assert re_request.status_code == 409
    assert _code(re_request) == "review-version-published"

    withdrawn = client.post(f"{BASE}/{review_id}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text


def test_a_version_has_at_most_one_open_review(fake, act_as):
    review_id = _requested()["review"]["id"]
    second = _request(reviewers=[CAROL_ADMIN])
    assert second.status_code == 409
    assert _code(second) == "review-already-open"

    assert client.post(f"{BASE}/{review_id}/withdraw").status_code == 200
    again = _requested(reviewers=[CAROL_ADMIN])
    assert again["review"]["id"] != review_id
    assert client.get(BASE, params={"open": "false"}).json()["total"] == 1


# ---------------------------------------------------------------------------------------------
# Reviewers, permissions, withdrawal
# ---------------------------------------------------------------------------------------------


def test_only_a_reviewer_of_the_current_round_decides_and_only_once(fake, act_as):
    review_id = _requested()["review"]["id"]

    act_as(CAROL_ADMIN)
    outsider = _decide(review_id, "approve")
    assert outsider.status_code == 403
    assert _code(outsider) == "review-not-reviewer"

    act_as(BOB)
    _decided(review_id, "approve")
    again = _decide(review_id, "request_changes")
    assert again.status_code == 409
    assert _code(again) == "review-already-decided"
    reviewers = client.get(f"{BASE}/{review_id}").json()["reviewers"]
    assert _decisions(reviewers) == [(1, BOB, "approve"), (1, DAVE, "pending")]


def test_the_reviewer_list_is_checked(fake, act_as):
    self_review = _request(reviewers=[BOB, ALICE])
    assert self_review.status_code == 400
    assert _code(self_review) == "review-self-review"

    outsider = _request(reviewers=[BOB, STRANGER])
    assert outsider.status_code == 400
    assert _code(outsider) == "review-invalid-reviewers"
    assert STRANGER in outsider.json()["detail"]["message"]

    malformed = _request(reviewers=["bob"])
    assert malformed.status_code == 400
    assert _code(malformed) == "review-invalid-reviewers"

    assert _request(reviewers=[]).status_code == 422
    assert _request(reviewers=[BOB] * 21).status_code == 422
    assert fake.workflow_audits == []

    detail = _requested(reviewers=[BOB, BOB.upper()])
    assert _decisions(detail["reviewers"]) == [(1, BOB, "pending")]


def test_requesting_needs_versions_edit_while_deciding_needs_only_project_view(fake, act_as):
    view_only = {("projects", "view")}
    fake.grants = view_only
    assert _request().status_code == 403

    fake.grants = None
    review_id = _requested()["review"]["id"]

    fake.grants = view_only
    assert client.get(BASE).status_code == 200
    fake.change_spec(VERSION_1)
    assert _re_request(review_id).status_code == 403
    fake.fingerprints.pop(VERSION_1)

    act_as(BOB)
    assert _decide(review_id, "approve").status_code == 200
    assert client.post(f"{BASE}/{review_id}/withdraw").status_code == 403


def test_withdrawing_belongs_to_the_requester_or_a_tenant_admin(fake, act_as):
    review_id = _requested()["review"]["id"]

    act_as(BOB)
    forbidden = client.post(f"{BASE}/{review_id}/withdraw")
    assert forbidden.status_code == 403
    assert _code(forbidden) == "review-forbidden"

    act_as(CAROL_ADMIN)
    response = client.post(f"{BASE}/{review_id}/withdraw")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["review"]["closed_at"] is not None
    assert detail["review"]["closed_by"] == CAROL_ADMIN
    assert detail["review"]["state"] == "in_review"
    assert detail["spec_changed"] is None
    assert fake.workflow_audits[-1]["action"] == "review.withdrawn"
    assert fake.workflow_audits[-1]["actor_id"] == CAROL_ADMIN

    act_as(BOB)
    assert _code(_decide(review_id, "approve")) == "review-closed"
    act_as(ALICE)
    fake.change_spec(VERSION_1)
    assert _code(_re_request(review_id)) == "review-closed"
    again = client.post(f"{BASE}/{review_id}/withdraw")
    assert again.status_code == 409
    assert _code(again) == "review-closed"
    assert client.get(f"{VERSIONS}/1.0.0/review").json()["state"] == "draft"


def test_a_re_request_can_name_the_next_rounds_reviewers(fake, act_as):
    review_id = _requested()["review"]["id"]
    act_as(BOB)
    _decided(review_id, "request_changes")

    act_as(ALICE)
    fake.change_spec(VERSION_1)
    self_review = _re_request(review_id, {"reviewers": [ALICE]})
    assert self_review.status_code == 400
    assert _code(self_review) == "review-self-review"

    detail = _re_request(review_id, {"reviewers": [CAROL_ADMIN]}).json()
    assert _decisions(detail["reviewers"]) == [(2, CAROL_ADMIN, "pending")]

    act_as(BOB)
    assert _code(_decide(review_id, "approve")) == "review-not-reviewer"
    act_as(CAROL_ADMIN)
    assert _decided(review_id, "approve")["review"]["state"] == "approved"


# ---------------------------------------------------------------------------------------------
# Reads, scope, audit, contract
# ---------------------------------------------------------------------------------------------


def test_the_list_filters_by_version_state_and_openness(fake, act_as):
    withdrawn_id = _requested()["review"]["id"]
    client.post(f"{BASE}/{withdrawn_id}/withdraw")
    open_id = _requested()["review"]["id"]
    decided_id = _requested(version=VERSION_2)["review"]["id"]
    act_as(BOB)
    _decided(decided_id, "request_changes")
    act_as(ALICE)

    def ids(**params: Any):
        body = client.get(BASE, params=params).json()
        return [review["id"] for review in body["reviews"]], body["total"]

    assert ids() == ([decided_id, open_id, withdrawn_id], 3)
    assert ids(version="1.0.0") == ([open_id, withdrawn_id], 2)
    assert ids(state="changes_requested") == ([decided_id], 1)
    assert ids(open="true") == ([decided_id, open_id], 2)
    assert ids(open="false") == ([withdrawn_id], 1)
    assert ids(limit=1, offset=1) == ([open_id], 3)

    page = client.get(BASE, params={"version": VERSION_2}).json()
    assert page["reviews"][0]["changes_requested_count"] == 1
    assert (page["count"], page["limit"], page["offset"]) == (1, 50, 0)

    unknown = client.get(BASE, params={"version": "9.9.9"})
    assert unknown.status_code == 404
    assert _code(unknown) == "review-version-not-found"


def test_reviews_are_scoped_to_their_project(fake, act_as):
    review_id = _requested()["review"]["id"]

    other = client.get(f"/v1/tenants/acme/projects/orders/reviews/{review_id}")
    assert other.status_code == 404
    assert _code(other) == "review-not-found"

    assert _code(client.get(f"{BASE}/not-a-uuid")) == "review-not-found"
    assert _code(client.get("/v1/tenants/acme/projects/nope/reviews")) == "review-project-not-found"

    foreign_version = _request(version=OTHER_VERSION)
    assert foreign_version.status_code == 404
    assert _code(foreign_version) == "review-version-not-found"


def test_every_transition_and_decision_is_audited(fake, act_as):
    review_id = _requested()["review"]["id"]
    act_as(BOB)
    _decided(review_id, "request_changes")
    act_as(ALICE)
    fake.change_spec(VERSION_1)
    _re_request(review_id)
    act_as(BOB)
    _decided(review_id, "approve")
    act_as(DAVE)
    _decided(review_id, "approve")
    act_as(ALICE)
    client.post(f"{BASE}/{review_id}/withdraw")

    assert _actions(fake) == [
        "review.requested",
        "review.decision",
        "review.state_changed",
        "review.re_requested",
        "review.decision",
        "review.decision",
        "review.state_changed",
        "review.withdrawn",
    ]
    assert [row["actor_id"] for row in fake.workflow_audits] == [ALICE, BOB, BOB, ALICE, BOB, DAVE, DAVE, ALICE]
    for row in fake.workflow_audits:
        assert (row["tenant_id"], row["project_id"], row["version_id"]) == (TENANT, PROJECT, VERSION_1)
        assert row["outcome"] == "success"
        assert row["detail"]["review_id"] == review_id
        if "to_state" in row["detail"]:
            assert is_allowed_transition(row["detail"]["from_state"], row["detail"]["to_state"])
    assert [row["detail"]["round"] for row in fake.workflow_audits] == [1, 1, 1, 2, 2, 2, 2, 2]


def test_every_review_endpoint_is_in_the_openapi_contract(fake):
    base = "/v1/tenants/{tenant_slug}/projects/{project_ref}"
    expected = {
        f"{base}/reviews": {"get", "post"},
        f"{base}/reviews/{{review_id}}": {"get"},
        f"{base}/reviews/{{review_id}}/decision": {"post"},
        f"{base}/reviews/{{review_id}}/re-request": {"post"},
        f"{base}/reviews/{{review_id}}/withdraw": {"post"},
        f"{base}/versions/{{version_ref}}/review": {"get"},
    }
    live = app.openapi()["paths"]
    committed = json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text(encoding="utf-8")
    )["paths"]
    for path, methods in expected.items():
        assert methods <= set(live.get(path, {})), f"missing route {path}"
        assert methods <= set(committed.get(path, {})), f"openapi.json is stale for {path}"
