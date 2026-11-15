"""HTTP contract tests for suggested changes — COL-4.2 (#4526).

The store is stubbed; these pin what the routes own: the ``projects:view`` guard, how a refusal
maps to a status (a stale apply is a 409 carrying ``conflict_paths``), ``can_decide``, and the
OpenAPI contract. The store's rules run against Postgres in ``test_review_suggestion_store_db``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import review_suggestion_routes as routes
from app.auth import validate_authentication
from app.main import app
from app.review_suggestions import (
    CODE_FORBIDDEN,
    CODE_STALE,
    SuggestionApplyResult,
    SuggestionRecord,
    SuggestionValidationError,
)
from app.reviews import CODE_REVIEW_NOT_FOUND, ReviewValidationError

client = TestClient(app)
BASE = "/v1/tenants/acme/projects/petstore/reviews/r-1/suggestions"
REQUESTER = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a00a1"
REVIEWER = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a00a2"
REVIEW = {"id": "r-1", "project_id": "p-1", "requested_by": REQUESTER, "round": 1}


def _record(**over) -> SuggestionRecord:
    data = dict(
        id="s-1", review_id="r-1", version_id="v-1", author_id=REVIEWER, target_type="property",
        target_id="t-1", target_label="Pet.name", base={"description": "a", "data": {}},
        patch=[{"op": "replace", "path": "/description", "value": "b"}],
        proposed={"description": "b", "data": {}}, status="open", created_at=datetime.now(timezone.utc),
    )
    data.update(over)
    return SuggestionRecord(**data)


@pytest.fixture
def ctx(monkeypatch):
    state = {"user": REVIEWER, "editor": False, "calls": []}
    monkeypatch.setattr(routes, "enforce_permission", lambda *a, **k: state["user"])
    monkeypatch.setattr(routes, "has_permission", lambda *a, **k: state["editor"])
    monkeypatch.setattr(routes.review_store, "resolve_project", lambda t, ref: {"id": "p-1"})
    monkeypatch.setattr(routes.review_store, "_review_row", lambda t, p, r: dict(REVIEW))
    monkeypatch.setattr(routes.review_store, "_review_version", lambda t, r: {"id": "v-1", "published": False})
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t-1", "user_id": state["user"]}
    yield state
    app.dependency_overrides.pop(validate_authentication, None)


def test_list_reports_can_decide_for_the_requester_and_editors(ctx, monkeypatch):
    monkeypatch.setattr(routes.review_suggestion_store, "list_suggestions", lambda review: [_record()])
    assert client.get(BASE).json()["can_decide"] is False
    ctx["user"] = REQUESTER
    body = client.get(BASE).json()
    assert body["can_decide"] is True and body["suggestions"][0]["target_label"] == "Pet.name"
    ctx["user"], ctx["editor"] = REVIEWER, True
    assert client.get(BASE).json()["can_decide"] is True


def test_create_passes_the_editor_flag_and_answers_201(ctx, monkeypatch):
    seen = {}

    def create(tenant_id, review, version, actor_id, body, *, is_editor):
        seen.update(actor=actor_id, editor=is_editor, patch=body.patch)
        return _record()

    monkeypatch.setattr(routes.review_suggestion_store, "create_suggestion", create)
    r = client.post(BASE, json={"target_type": "property", "target_id": "t-1",
                                "patch": [{"op": "replace", "path": "/description", "value": "b"}]})
    assert r.status_code == 201, r.text
    assert seen == {"actor": REVIEWER, "editor": False, "patch": [{"op": "replace", "path": "/description", "value": "b"}]}


def test_create_rejects_an_empty_patch_and_unknown_target_types(ctx):
    assert client.post(BASE, json={"target_type": "property", "target_id": "t", "patch": []}).status_code == 422
    assert client.post(BASE, json={"target_type": "path", "target_id": "t", "patch": [{"op": "test"}]}).status_code == 422


def test_stale_apply_is_409_with_conflict_paths(ctx, monkeypatch):
    def stale(*a, **k):
        raise SuggestionValidationError(CODE_STALE, "the element changed", ["data.maxLength"])

    monkeypatch.setattr(routes.review_suggestion_store, "apply_suggestion", stale)
    r = client.post(f"{BASE}/s-1/apply")
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": CODE_STALE, "message": "the element changed", "conflict_paths": ["data.maxLength"]}


def test_apply_returns_the_written_element(ctx, monkeypatch):
    monkeypatch.setattr(
        routes.review_suggestion_store, "apply_suggestion",
        lambda *a, **k: SuggestionApplyResult(suggestion=_record(status="applied"), element={"description": "b", "data": {}}, merged_around=False),
    )
    r = client.post(f"{BASE}/s-1/apply")
    assert r.status_code == 200 and r.json()["element"]["description"] == "b"


def test_forbidden_is_403_and_reject_accepts_no_body(ctx, monkeypatch):
    def forbid(*a, **k):
        raise SuggestionValidationError(CODE_FORBIDDEN, "no")

    monkeypatch.setattr(routes.review_suggestion_store, "reject_suggestion", forbid)
    assert client.post(f"{BASE}/s-1/reject").status_code == 403


def test_reject_records_the_reason(ctx, monkeypatch):
    seen = {}

    def reject(review, version, sid, actor, *, is_editor, reason=None):
        seen["reason"] = reason
        return _record(status="rejected", reason=reason, decided_at=datetime.now(timezone.utc), decided_by=actor)

    monkeypatch.setattr(routes.review_suggestion_store, "reject_suggestion", reject)
    r = client.post(f"{BASE}/s-1/reject", json={"reason": "Keep the old name"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and seen["reason"] == "Keep the old name"


def test_unknown_review_is_404(ctx, monkeypatch):
    def missing(*a):
        raise ReviewValidationError(CODE_REVIEW_NOT_FOUND, "no review")

    monkeypatch.setattr(routes.review_store, "_review_row", missing)
    assert client.get(BASE).status_code == 404


def test_every_route_is_in_the_openapi_contract():
    paths = client.get("/openapi.json").json()["paths"]
    base = "/v1/tenants/{tenant_slug}/projects/{project_ref}/reviews/{review_id}/suggestions"
    assert {base, f"{base}/{{suggestion_id}}/apply", f"{base}/{{suggestion_id}}/reject"} <= set(paths)
