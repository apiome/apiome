"""Publish route schedules persisted change report (CR-04 + CR-02, #2704)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.change_report_render import bundled_system_template_row
from app.main import app

client = TestClient(app)

_MOCK_JWT = {
    "tenant_id": "t1",
    "user_id": "user-a",
    "auth_method": "jwt",
}

_CANDIDATE_OPENAPI = {
    "openapi": "3.1.0",
    "info": {"title": "API", "version": "1.0.0"},
    "paths": {},
    "components": {"schemas": {"Pet": {"type": "object"}}},
}

_UNPUBLISHED = {
    "id": "vid-1",
    "project_id": "pid-1",
    "creator_id": "user-a",
    "published": False,
    "version_id": "1.0.0",
    "description": None,
    "change_log": None,
}

_PUBLISHED_ROW = {
    "id": "vid-1",
    "project_id": "pid-1",
    "creator_id": "user-a",
    "version_id": "1.0.0",
    "short_message": None,
    "changelog": None,
    "visibility": "private",
    "published": True,
    "published_at": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
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


def test_publish_persists_change_report_via_background_task():
    """After POST …/publish, the publication hook inserts a change_reports row (best-effort)."""
    shared = MagicMock()
    shared.get_version_by_id.side_effect = [_UNPUBLISHED, {**_UNPUBLISHED, "published": True, "published_at": _PUBLISHED_ROW["published_at"]}]
    shared.publish_version.return_value = _PUBLISHED_ROW
    shared.get_project_by_id.return_value = {"id": "pid-1", "name": "My Project", "slug": "my-project", "metadata": {}}
    shared.get_prior_published_baseline_revision_id.return_value = None
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]

    with patch("app.versions_routes.db", shared), patch("app.publication_change_report.db", shared), patch(
        "app.version_publish_prechecks.db", shared,
    ), patch(
        "app.version_publish_prechecks.openapi_for_revision",
        return_value=_CANDIDATE_OPENAPI,
    ), patch(
        "app.publication_change_report.openapi_for_revision",
        return_value=_CANDIDATE_OPENAPI,
    ), patch(
        "app.publication_change_report.resolve_effective_change_report_template",
        return_value=bundled_system_template_row(),
    ):
        res = client.post(
            "/v1/versions/tn/pid-1/vid-1/publish",
            json={"shortMessage": "release"},
        )

    assert res.status_code == 200
    shared.insert_change_report_if_absent.assert_called_once()
    pos, kw = shared.insert_change_report_if_absent.call_args
    assert pos == ("t1", "pid-1", "vid-1")
    assert kw.get("baseline_revision_id") is None
    cm = kw["change_model_json"]
    assert cm.get("initialPublication") is True
    assert "Pet" in str(cm.get("schemas", {}))
    shared.insert_workflow_audit.assert_called()
    audit = shared.insert_workflow_audit.call_args_list[-1]
    assert audit[0][4] == "success"
