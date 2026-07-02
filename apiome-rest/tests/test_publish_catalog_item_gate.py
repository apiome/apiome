"""Non-publishable enforcement at the publish endpoint (MFI-23.8, #4017).

A *catalog item* is the ``publishable = false`` slice of projects (MFI-23.1): an OpenAPI-worthy
*non*-OpenAPI import (gRPC, GraphQL, AsyncAPI, …) that may be incomplete and is therefore never a
publish candidate. The "no publish" rule is enforced in REST (not merely hidden in the UI): a direct
``POST …/publish`` against a version whose project is non-publishable is refused with a helpful
message pointing at the convert-to-OpenAPI flow. Ordinary (publishable) projects publish unchanged,
including the back-compatible case where the project row carries no ``publishable`` key at all.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_JWT = {
    "tenant_id": "t1",
    "user_id": "user-a",
    "auth_method": "jwt",
}

_UNPUBLISHED = {
    "id": "vid-1",
    "project_id": "pid-1",
    "creator_id": "user-a",
    "published": False,
    "version_id": "2.0.0",
    "description": None,
    "change_log": None,
}

_OPENAPI = {
    "openapi": "3.1.0",
    "info": {"title": "API", "version": "1.0.0"},
    "paths": {},
    "components": {"schemas": {}},
}

_PUBLISHED_ROW = {
    "id": "vid-1",
    "project_id": "pid-1",
    "creator_id": "user-a",
    "version_id": "2.0.0",
    "short_message": "Test revision note",
    "changelog": None,
    "visibility": "private",
    "published": True,
    "published_at": datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
    "published_immutable": True,
    "enabled": True,
    "parent_version_id": None,
    "merge_parent_version_id": None,
    "forked_from_revision_id": None,
    "upstream_project_id": None,
    "revision_locked": False,
    "metadata": None,
    "creator_name": None,
    "creator_email": None,
    "project_name": "P",
    "project_slug": "p",
    "created_at": None,
    "updated_at": None,
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_publish_refused_for_catalog_item():
    """A catalog item (``publishable = false``) is refused with a convert-to-OpenAPI hint."""
    shared = MagicMock()
    shared.get_version_by_id.return_value = dict(_UNPUBLISHED)
    shared.get_project_by_id.return_value = {"id": "pid-1", "slug": "grpc-svc", "publishable": False}

    with patch("app.versions_routes.db", shared):
        res = client.post(
            "/v1/versions/acme/pid-1/vid-1/publish",
            json={"shortMessage": "Test revision note"},
        )

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "catalog item" in detail
    assert "convert-to-OpenAPI" in detail
    # The refusal happens before any attempt to persist a publish.
    shared.publish_version.assert_not_called()


def _publish_publishable(project_row):
    """Drive the publish endpoint for a publishable project and return the response.

    The change-report baseline resolves to ``None`` so the prechecks short-circuit after the
    class-description gate, keeping the success path free of compatibility machinery; the
    post-publish change-report background task is stubbed out.
    """
    shared = MagicMock()
    shared.get_version_by_id.return_value = dict(_UNPUBLISHED)
    shared.get_project_by_id.return_value = project_row
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]
    shared.publish_version.return_value = dict(_PUBLISHED_ROW)

    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared,
    ), patch(
        "app.version_publish_prechecks.openapi_for_revision", return_value=_OPENAPI,
    ), patch(
        "app.version_publish_prechecks.resolve_baseline_revision_id_for_change_report",
        return_value=None,
    ), patch("app.versions_routes.generate_change_report_on_publish", MagicMock()):
        res = client.post(
            "/v1/versions/acme/pid-1/vid-1/publish",
            json={"shortMessage": "Test revision note"},
        )
    return res, shared


def test_publish_proceeds_for_publishable_project():
    """An explicitly publishable project (``publishable = true``) publishes normally."""
    res, shared = _publish_publishable(
        {"id": "pid-1", "slug": "p", "metadata": {}, "publishable": True}
    )
    assert res.status_code == 200
    shared.publish_version.assert_called_once()


def test_publish_proceeds_when_publishable_flag_absent():
    """Back-compat: a project row without a ``publishable`` key is treated as publishable."""
    res, shared = _publish_publishable({"id": "pid-1", "slug": "p", "metadata": {}})
    assert res.status_code == 200
    shared.publish_version.assert_called_once()
