"""Publish prechecks: descriptions + compatibility (#3212)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.change_report_render import bundled_system_template_row
from app.compatibility_engine import CompatibilityCheckResult
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

_BASE_PUBLISHED = {
    "id": "base-1",
    "project_id": "pid-1",
    "creator_id": "user-a",
    "published": True,
    "version_id": "1.0.0",
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
    "short_message": None,
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


def test_publish_blocks_when_class_descriptions_missing():
    draft = dict(_UNPUBLISHED)
    shared = MagicMock()
    shared.get_version_by_id.return_value = draft
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": ""}]

    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared,
    ), patch("app.version_publish_prechecks.openapi_for_revision", return_value=_OPENAPI):
        res = client.post(
            "/v1/versions/acme/pid-1/vid-1/publish",
            json={"shortMessage": "Test revision note"},
        )

    assert res.status_code == 422
    assert "missing required descriptions" in res.json()["detail"]


def test_publish_blocks_breaking_without_allow_breaking():
    draft = dict(_UNPUBLISHED)
    shared = MagicMock()

    def gv(vid: str, _tid: str):
        if str(vid) == "vid-1":
            return draft
        if str(vid) == "base-1":
            return dict(_BASE_PUBLISHED)
        return None

    shared.get_version_by_id.side_effect = gv
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]
    shared.get_project_by_id.return_value = {"id": "pid-1", "slug": "pay"}
    shared.get_prior_published_baseline_revision_id.return_value = "base-1"

    breaking = CompatibilityCheckResult(
        overall="breaking",
        findings=tuple(),
        rule_hits=MappingProxyType({}),
        report_fingerprint="ab" * 32,
    )

    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared,
    ), patch("app.publication_change_report.db", shared), patch(
        "app.version_publish_prechecks.openapi_for_revision",
        return_value=_OPENAPI,
    ), patch(
        "app.version_publish_prechecks.CompatibilityCheckEngine.run",
        return_value=breaking,
    ):
        res = client.post(
            "/v1/versions/acme/pid-1/vid-1/publish",
            json={"shortMessage": "Test revision note"},
        )

    assert res.status_code == 409
    body = res.json()
    assert "detail" in body
    assert "Breaking schema changes" in body["detail"]


def test_publish_allows_breaking_when_allow_breaking_true():
    draft = dict(_UNPUBLISHED)
    shared = MagicMock()

    def gv(vid: str, _tid: str):
        if str(vid) == "vid-1":
            return draft
        if str(vid) == "base-1":
            return dict(_BASE_PUBLISHED)
        return None

    shared.get_version_by_id.side_effect = gv
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]
    shared.get_project_by_id.return_value = {"id": "pid-1", "slug": "pay", "metadata": {}}
    shared.get_prior_published_baseline_revision_id.return_value = "base-1"
    shared.publish_version.return_value = _PUBLISHED_ROW

    breaking = CompatibilityCheckResult(
        overall="breaking",
        findings=tuple(),
        rule_hits=MappingProxyType({}),
        report_fingerprint="cd" * 32,
    )

    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared,
    ), patch(
        "app.version_publish_prechecks.openapi_for_revision",
        return_value=_OPENAPI,
    ), patch(
        "app.version_publish_prechecks.CompatibilityCheckEngine.run",
        return_value=breaking,
    ), patch("app.publication_change_report.db", shared), patch(
        "app.publication_change_report.openapi_for_revision",
        return_value=_OPENAPI,
    ), patch(
        "app.publication_change_report.resolve_effective_change_report_template",
        return_value=bundled_system_template_row(),
    ):
        res = client.post(
            "/v1/versions/acme/pid-1/vid-1/publish",
            json={"allowBreaking": True, "shortMessage": "Test revision note"},
        )

    assert res.status_code == 200
    shared.publish_version.assert_called_once()
