"""HTTP contract tests for draft branches and merge requests — COL-4.3 (#4527).

The store is stubbed; these pin what the routes own: the permission each route requires, how a
refusal maps to a status and body (``mr-not-ready`` carries ``blockers``, ``mr-conflicts`` carries
``conflicts``), review refusals passing through, and the OpenAPI contract. The store's rules run
against Postgres in ``test_merge_request_store_db``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import merge_request_routes as routes
from app.auth import validate_authentication
from app.keyset_pagination import Page, encode_time_id_cursor
from app.main import app
from app.merge_requests import (
    CODE_CONFLICTS,
    CODE_MERGE_REQUEST_NOT_FOUND,
    CODE_NOT_READY,
    DraftBranchRecord,
    MergeReadiness,
    MergeRequestDetail,
    MergeRequestRecord,
    MergeRequestValidationError,
)
from app.permissions import Action, Resource
from app.reviews import CODE_INVALID_REVIEWERS, ReviewValidationError

client = TestClient(app)
PROJECT = "/v1/tenants/acme/projects/petstore"
USER = "0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a00a1"
NOW = datetime.now(timezone.utc)


def _detail(**over) -> MergeRequestDetail:
    record = dict(
        id="mr-1",
        tenant_id="t-1",
        project_id="p-1",
        title="Add pet tags",
        state="open",
        source_branch_id="b-src",
        source_branch_name="feature/tags",
        target_branch_id="b-main",
        target_branch_name="main",
        created_at=NOW,
        updated_at=NOW,
    )
    record.update(over)
    return MergeRequestDetail(merge_request=MergeRequestRecord(**record), readiness=MergeReadiness(can_merge=False))


@pytest.fixture
def ctx(monkeypatch):
    state = {"permissions": []}

    def enforce(_db, _auth, resource, action, **_kw):
        state["permissions"].append((resource, action))
        return USER

    monkeypatch.setattr(routes, "enforce_permission", enforce)
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t-1", "user_id": USER}
    yield state
    app.dependency_overrides.pop(validate_authentication, None)


def test_create_draft_branch_needs_versions_create_and_answers_201(ctx, monkeypatch):
    seen = {}

    def create(tenant_id, project_ref, body, actor):
        seen.update(tenant=tenant_id, project=project_ref, name=body.name, base=body.base_branch, actor=actor)
        return DraftBranchRecord(
            id="b-src",
            project_id="p-1",
            name=body.name,
            tip_revision_id="v-2",
            base_branch_id="b-main",
            base_branch_name="main",
        )

    monkeypatch.setattr(routes.merge_request_store, "create_draft_branch", create)
    r = client.post(f"{PROJECT}/draft-branches", json={"name": "feature/tags", "base_branch": "main"})
    assert r.status_code == 201, r.text
    assert r.json()["base_branch_name"] == "main"
    assert seen == {"tenant": "t-1", "project": "petstore", "name": "feature/tags", "base": "main", "actor": USER}
    assert ctx["permissions"] == [(Resource.VERSIONS, Action.CREATE)]


def test_draft_branch_body_rejects_unknown_fields(ctx):
    assert client.post(f"{PROJECT}/draft-branches", json={"name": "x", "tip": "v-1"}).status_code == 422


def test_open_needs_versions_edit_and_review_refusals_pass_through(ctx, monkeypatch):
    def refuse(*_a):
        raise ReviewValidationError(CODE_INVALID_REVIEWERS, "name at least one reviewer")

    monkeypatch.setattr(routes.merge_request_store, "open_merge_request", refuse)
    r = client.post(f"{PROJECT}/merge-requests", json={"source_branch": "feature/tags", "title": "Tags"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == CODE_INVALID_REVIEWERS
    assert ctx["permissions"] == [(Resource.VERSIONS, Action.EDIT)]


def test_open_answers_201_with_the_detail(ctx, monkeypatch):
    monkeypatch.setattr(routes.merge_request_store, "open_merge_request", lambda *a: _detail())
    r = client.post(
        f"{PROJECT}/merge-requests", json={"source_branch": "feature/tags", "title": "Tags", "reviewers": [USER]}
    )
    assert r.status_code == 201, r.text
    assert r.json()["merge_request"]["target_branch_name"] == "main"


def test_list_reads_with_versions_view_and_filters_by_state(ctx, monkeypatch):
    seen = {}

    def list_(tenant_id, project_ref, *, state, limit, offset, cursor, include_total):
        seen.update(state=state, limit=limit, offset=offset, cursor=cursor, include_total=include_total)
        return Page(items=[_detail().merge_request], has_more=True, next_cursor="next"), 7 if include_total else None

    monkeypatch.setattr(routes.merge_request_store, "list_merge_requests", list_)
    body = client.get(f"{PROJECT}/merge-requests?state=open&limit=5&include_total=true").json()
    assert body["count"] == 1 and body["total"] == 7
    assert body["has_more"] is True and body["next_cursor"] == "next"
    assert seen == {"state": "open", "limit": 5, "offset": 0, "cursor": None, "include_total": True}
    assert ctx["permissions"] == [(Resource.VERSIONS, Action.VIEW)]
    assert client.get(f"{PROJECT}/merge-requests?state=bogus").status_code == 422

    # Keyset paging (#7196): the cursor reaches the store decoded, the total is opt-in, a bad
    # cursor is a 400 and the page size keeps its maximum.
    stamp = datetime(2026, 11, 22, tzinfo=timezone.utc)
    cursor = encode_time_id_cursor(stamp, "0a1b2c30-1111-4222-8333-000000000001")
    paged = client.get(f"{PROJECT}/merge-requests", params={"cursor": cursor, "offset": 9}).json()
    assert seen["cursor"] == (stamp, "0a1b2c30-1111-4222-8333-000000000001")
    assert paged["total"] is None and paged["offset"] == 0
    assert client.get(f"{PROJECT}/merge-requests?cursor=not-a-cursor").status_code == 400
    assert client.get(f"{PROJECT}/merge-requests?limit=101").status_code == 422
    assert client.get(f"{PROJECT}/merge-requests?offset=10001").status_code == 422


def test_unknown_merge_request_is_404(ctx, monkeypatch):
    def missing(*_a):
        raise MergeRequestValidationError(CODE_MERGE_REQUEST_NOT_FOUND, "no such merge request")

    monkeypatch.setattr(routes.merge_request_store, "get_merge_request", missing)
    r = client.get(f"{PROJECT}/merge-requests/mr-404")
    assert r.status_code == 404 and r.json()["detail"]["code"] == CODE_MERGE_REQUEST_NOT_FOUND


def test_merge_not_ready_is_409_with_blockers(ctx, monkeypatch):
    def refuse(*_a):
        raise MergeRequestValidationError(
            CODE_NOT_READY, "not ready", {"blockers": [{"code": "review-pending", "message": "1 reviewer(s)"}]}
        )

    monkeypatch.setattr(routes.merge_request_store, "merge_merge_request", refuse)
    r = client.post(f"{PROJECT}/merge-requests/mr-1/merge", json={})
    assert r.status_code == 409
    assert r.json()["detail"]["blockers"][0]["code"] == "review-pending"
    assert ctx["permissions"] == [(Resource.VERSIONS, Action.EDIT)]


def test_merge_conflicts_are_409_with_the_session(ctx, monkeypatch):
    def refuse(*_a):
        raise MergeRequestValidationError(
            CODE_CONFLICTS,
            "conflicts",
            {"merge_session_id": "ms-1", "conflicts": [{"path": "Pet", "kinds": ["threeWay"]}]},
        )

    monkeypatch.setattr(routes.merge_request_store, "merge_merge_request", refuse)
    detail = client.post(f"{PROJECT}/merge-requests/mr-1/merge").json()["detail"]
    assert detail["code"] == CODE_CONFLICTS and detail["merge_session_id"] == "ms-1"


def test_merge_forwards_the_immutability_override(ctx, monkeypatch):
    seen = {}

    def merge(tenant_slug, auth_data, actor, project_ref, mr_id, body):
        seen.update(
            slug=tenant_slug,
            actor=actor,
            mr=mr_id,
            override=body.override_published_immutability,
            reason=body.override_reason,
        )
        return _detail(state="merged", merged_at=NOW, merged_version_id="v-9")

    monkeypatch.setattr(routes.merge_request_store, "merge_merge_request", merge)
    r = client.post(
        f"{PROJECT}/merge-requests/mr-1/merge",
        json={"override_published_immutability": True, "override_reason": "hotfix"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["merge_request"]["merged_version_id"] == "v-9"
    assert seen == {"slug": "acme", "actor": USER, "mr": "mr-1", "override": True, "reason": "hotfix"}


def test_check_needs_only_versions_view(ctx, monkeypatch):
    def check(*_a):
        return _detail()

    monkeypatch.setattr(routes.merge_request_store, "check_merge_request", check)
    assert client.post(f"{PROJECT}/merge-requests/mr-1/check").status_code == 200
    assert ctx["permissions"] == [(Resource.VERSIONS, Action.VIEW)]


def test_close_and_review_need_versions_edit(ctx, monkeypatch):
    monkeypatch.setattr(
        routes.merge_request_store, "close_merge_request", lambda *a: _detail(state="closed", closed_at=NOW)
    )
    monkeypatch.setattr(routes.merge_request_store, "request_merge_request_review", lambda *a: _detail())
    assert client.post(f"{PROJECT}/merge-requests/mr-1/close").json()["merge_request"]["state"] == "closed"
    assert client.post(f"{PROJECT}/merge-requests/mr-1/review", json={}).status_code == 200
    assert ctx["permissions"] == [(Resource.VERSIONS, Action.EDIT), (Resource.VERSIONS, Action.EDIT)]


def test_openapi_documents_every_route():
    paths = app.openapi()["paths"]
    base = "/v1/tenants/{tenant_slug}/projects/{project_ref}"
    assert set(paths[f"{base}/draft-branches"]) == {"get", "post"}
    assert set(paths[f"{base}/merge-requests"]) == {"get", "post"}
    for suffix in ("", "/review", "/check", "/merge", "/close"):
        assert f"{base}/merge-requests/{{merge_request_id}}{suffix}" in paths
