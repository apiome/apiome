"""Unpublish with a reason, tag moves and the ``version.unpublished`` webhook (CLI 4.6, #3213).

Covers the pure rules in :mod:`app.version_unpublish` and the
``POST /v1/versions/{tenant}/{project}/{id}/unpublish`` route with the database mocked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.version_unpublish import (
    EVENT_TYPE_VERSION_UNPUBLISHED,
    KEPT_IMMUTABLE,
    KEPT_NO_TARGET,
    KEPT_PROTECTED,
    KEPT_REQUESTED,
    build_unpublish_notification,
    count_active_subscriptions,
    notify_version_unpublished,
    plan_tag_moves,
    previous_published,
)

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}

_V1 = {
    "id": "v1",
    "version_id": "1.0.0",
    "published": True,
    "published_at": "2026-01-01T00:00:00Z",
    "created_at": "2026-01-01T00:00:00Z",
}
_V2 = {
    "id": "v2",
    "version_id": "2.0.0",
    "published": True,
    "published_at": "2026-02-01T00:00:00Z",
    "created_at": "2026-02-01T00:00:00Z",
}
_V3 = {
    "id": "v3",
    "version_id": "2.1.0",
    "published": True,
    "published_at": "2026-03-01T00:00:00Z",
    "created_at": "2026-03-01T00:00:00Z",
}
_DRAFT = {
    "id": "v4",
    "version_id": "3.0.0",
    "published": False,
    "published_at": None,
    "created_at": "2026-04-01T00:00:00Z",
}


def _tag(name: str, version_id: str = "v3", **extra: Any) -> Dict[str, Any]:
    return {
        "id": f"t-{name}",
        "name": name,
        "version_id": version_id,
        "immutable": False,
        "protected": False,
        **extra,
    }


# --- previous_published ---------------------------------------------------------------------


def test_the_previous_published_version_is_the_most_recently_published_other_one() -> None:
    assert previous_published([_V1, _V3, _V2, _DRAFT], "v3") is _V2


def test_published_at_wins_over_created_at() -> None:
    late_publish = {**_V1, "published_at": datetime(2026, 5, 1, tzinfo=timezone.utc)}
    assert previous_published([late_publish, _V2, _V3], "v3") is late_publish


def test_there_is_no_previous_published_version_when_it_is_the_only_one() -> None:
    assert previous_published([_V3, _DRAFT], "v3") is None


# --- plan_tag_moves -------------------------------------------------------------------------


def test_tags_on_the_revision_move_to_the_previous_published_version() -> None:
    plan = plan_tag_moves(
        [_tag("latest"), _tag("stable"), _tag("old", "v1")], "v3", _V2, keep_tags=False, is_admin=False
    )
    assert plan.moves == [
        {"id": "t-latest", "name": "latest", "toVersionId": "v2", "toVersionLabel": "2.0.0"},
        {"id": "t-stable", "name": "stable", "toVersionId": "v2", "toVersionLabel": "2.0.0"},
    ]
    assert plan.kept == []


def test_keep_tags_leaves_every_tag() -> None:
    plan = plan_tag_moves([_tag("latest")], "v3", _V2, keep_tags=True, is_admin=True)
    assert plan.moves == []
    assert plan.kept == [{"id": "t-latest", "name": "latest", "reason": KEPT_REQUESTED}]


def test_immutable_protected_and_targetless_tags_stay_with_a_reason() -> None:
    tags = [_tag("frozen", immutable=True), _tag("guarded", protected=True)]
    plan = plan_tag_moves(tags, "v3", _V2, keep_tags=False, is_admin=False)
    assert [(k["name"], k["reason"]) for k in plan.kept] == [
        ("frozen", KEPT_IMMUTABLE),
        ("guarded", KEPT_PROTECTED),
    ]

    admin_plan = plan_tag_moves(tags, "v3", _V2, keep_tags=False, is_admin=True)
    assert [m["name"] for m in admin_plan.moves] == ["guarded"]

    nowhere = plan_tag_moves([_tag("latest")], "v3", None, keep_tags=False, is_admin=False)
    assert nowhere.kept == [{"id": "t-latest", "name": "latest", "reason": KEPT_NO_TARGET}]


# --- notification ---------------------------------------------------------------------------


def test_the_webhook_payload_carries_the_reason_and_tag_moves() -> None:
    payload = build_unpublish_notification(
        project_id="p1",
        version_record_id="v3",
        version_label="2.1.0",
        actor_id="user-1",
        reason="Security regression",
        unpublished_at=datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc),
        tags_moved=[{"id": "t-latest", "name": "latest", "toVersionId": "v2", "toVersionLabel": "2.0.0"}],
    )
    assert payload == {
        "event": EVENT_TYPE_VERSION_UNPUBLISHED,
        "projectId": "p1",
        "versionId": "v3",
        "versionLabel": "2.1.0",
        "unpublishedBy": "user-1",
        "unpublishedAt": "2026-10-16T12:00:00+00:00",
        "reason": "Security regression",
        "tagsMoved": [{"name": "latest", "toVersionId": "v2", "toVersionLabel": "2.0.0"}],
    }


def test_the_webhook_is_enqueued_once_per_active_subscription() -> None:
    db = MagicMock()
    db.list_active_push_webhook_subscription_ids.return_value = ["s1", "s2"]
    db.enqueue_push_webhook_delivery.side_effect = [{"id": "e1"}, {"id": "e2"}]
    assert notify_version_unpublished(db, tenant_id="tenant-1", payload={"event": "x"}) == ["e1", "e2"]
    assert db.enqueue_push_webhook_delivery.call_args_list[0].args[:3] == (
        "tenant-1",
        "s1",
        EVENT_TYPE_VERSION_UNPUBLISHED,
    )


def test_an_unreadable_subscription_count_is_unknown_not_an_error() -> None:
    db = MagicMock()
    db.list_active_push_webhook_subscription_ids.side_effect = RuntimeError("down")
    assert count_active_subscriptions(db, "tenant-1") is None


# --- the route ------------------------------------------------------------------------------


def _existing(**extra: Any) -> Dict[str, Any]:
    return {**_V3, "project_id": "p1", "creator_id": "user-1", "visibility": "public", **extra}


def _post(
    body: Optional[Dict[str, Any]],
    *,
    is_admin: bool = False,
    tags: Optional[List[Dict[str, Any]]] = None,
    versions: Optional[List[Dict[str, Any]]] = None,
    unpublish_result: Any = "default",
):
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with (
            patch("app.versions_routes.db") as mock_db,
            patch("app.versions_routes.enforce_permission"),
            patch("app.versions_routes.get_authenticated_user_id", return_value="user-1"),
            patch("app.versions_routes.count_active_subscriptions", return_value=3),
            patch("app.versions_routes.notify_version_unpublished") as notify,
        ):
            mock_db.get_version_by_id.return_value = _existing()
            mock_db.version_has_data_records.return_value = False
            mock_db.is_user_tenant_admin.return_value = is_admin
            mock_db.get_versions_for_project.return_value = (
                versions if versions is not None else [_V1, _V2, _V3]
            )
            mock_db.list_version_tags_for_project.return_value = (
                tags if tags is not None else [_tag("latest")]
            )
            if unpublish_result == "default":
                unpublish_result = {
                    "version": _existing(
                        published=False,
                        published_at=None,
                        unpublish_reason=((body or {}).get("reason") or "").strip() or None,
                        unpublished_at="2026-10-16T12:00:00Z",
                        unpublished_by="user-1",
                    ),
                    "moved_tag_ids": ["t-latest"],
                }
            mock_db.unpublish_version.return_value = unpublish_result
            kwargs = {"json": body} if body is not None else {}
            response = client.post("/v1/versions/acme/p1/v3/unpublish", **kwargs)
            return response, mock_db, notify
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_an_empty_body_still_unpublishes_moves_tags_and_notifies() -> None:
    response, db, notify = _post(None)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["published"] is False
    assert data["tagsMoved"] == [
        {"id": "t-latest", "name": "latest", "toVersionId": "v2", "toVersionLabel": "2.0.0"}
    ]
    assert data["previousPublishedVersionLabel"] == "2.0.0"
    assert data["publishedVersionsRemaining"] == 2
    assert data["notify"] is True and data["webhookSubscribers"] == 3
    assert db.unpublish_version.call_args.kwargs == {"reason": None, "tag_moves": data["tagsMoved"]}
    notify.assert_called_once()
    assert notify.call_args.kwargs["payload"]["event"] == EVENT_TYPE_VERSION_UNPUBLISHED


def test_the_reason_is_stored_and_returned() -> None:
    response, db, _ = _post({"reason": "  Accidental publish  "})
    assert response.status_code == 200
    assert db.unpublish_version.call_args.kwargs["reason"] == "Accidental publish"
    assert response.json()["unpublishReason"] == "Accidental publish"


def test_keep_tags_moves_nothing() -> None:
    response, db, _ = _post(
        {"keepTags": True}, unpublish_result={"version": _existing(published=False), "moved_tag_ids": []}
    )
    assert response.status_code == 200
    assert db.unpublish_version.call_args.kwargs["tag_moves"] == []
    assert response.json()["tagsKept"] == [{"id": "t-latest", "name": "latest", "reason": "keep-tags"}]


def test_silent_needs_a_tenant_administrator() -> None:
    response, db, notify = _post({"silent": True})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "silent_requires_admin"
    db.unpublish_version.assert_not_called()
    notify.assert_not_called()


def test_a_silent_unpublish_by_an_administrator_sends_no_webhook() -> None:
    response, _, notify = _post({"silent": True, "reason": "wrong tenant"}, is_admin=True)
    assert response.status_code == 200
    assert response.json()["notify"] is False
    assert response.json()["webhookSubscribers"] == 0
    notify.assert_not_called()


def test_a_dry_run_writes_nothing_and_returns_the_plan() -> None:
    response, db, notify = _post({"dryRun": True})
    assert response.status_code == 200
    data = response.json()
    assert data["dryRun"] is True
    assert data["published"] is True
    assert [m["name"] for m in data["tagsMoved"]] == ["latest"]
    db.unpublish_version.assert_not_called()
    notify.assert_not_called()


def test_a_dry_run_by_someone_who_may_not_unpublish_is_refused() -> None:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with (
            patch("app.versions_routes.db") as mock_db,
            patch("app.versions_routes.enforce_permission"),
            patch("app.versions_routes.get_authenticated_user_id", return_value="user-1"),
            patch("app.versions_routes.count_active_subscriptions", return_value=0),
        ):
            mock_db.get_version_by_id.return_value = _existing(creator_id="someone-else")
            mock_db.version_has_data_records.return_value = False
            mock_db.is_user_tenant_admin.return_value = False
            mock_db.get_versions_for_project.return_value = [_V3]
            mock_db.list_version_tags_for_project.return_value = []
            response = client.post("/v1/versions/acme/p1/v3/unpublish", json={"dryRun": True})
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 403


def test_a_caller_who_may_not_unpublish_gets_a_403() -> None:
    response, _, notify = _post({}, unpublish_result=None)
    assert response.status_code == 403
    notify.assert_not_called()


def test_only_tags_the_database_actually_moved_are_reported() -> None:
    response, _, _ = _post(
        {},
        tags=[_tag("latest"), _tag("stable")],
        unpublish_result={"version": _existing(published=False), "moved_tag_ids": ["t-stable"]},
    )
    assert [m["name"] for m in response.json()["tagsMoved"]] == ["stable"]


def test_a_reason_longer_than_the_limit_is_a_422() -> None:
    response, db, _ = _post({"reason": "x" * 2001})
    assert response.status_code == 422
    db.unpublish_version.assert_not_called()
