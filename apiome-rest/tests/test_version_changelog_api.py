"""Read APIs for stored version changelogs (CTG-3.2, #4476)."""

from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

TENANT_ID = str(uuid4())
PROJECT_ID = str(uuid4())
REVISION_ID = str(uuid4())
BASELINE_ID = str(uuid4())

_MOCK_AUTH = {
    "tenant_id": TENANT_ID,
    "tenant_slug": "acme",
    "auth_method": "api_key",
}


@pytest.fixture
def auth_override():
    """Route auth resolved to the test tenant for the duration of a test."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


CHANGELOG_JSON = {
    "schemaVersion": "ctg.changelog.v1",
    "fromVersion": "1.0.0",
    "toVersion": "2.0.0",
    "counts": {
        "breaking": 1,
        "non-breaking": 1,
        "docs-only": 0,
        "unclassified": 0,
        "total": 2,
    },
    "maxSeverity": "breaking",
    "entries": [
        {
            "severity": "breaking",
            "pathGroup": "/pets",
            "pointer": "/paths/~1pets/get",
            "ruleId": "operation-removed",
            "changeKind": "removed",
            "summary": "Operation removed",
            "before": {},
            "after": None,
            "unclassified": False,
            "fromVersion": "1.0.0",
            "toVersion": "2.0.0",
        },
        {
            "severity": "non-breaking",
            "pathGroup": "/pets",
            "pointer": "/paths/~1pets/post",
            "ruleId": "operation-added",
            "changeKind": "added",
            "summary": "Operation added",
            "before": None,
            "after": {},
            "unclassified": False,
            "fromVersion": "1.0.0",
            "toVersion": "2.0.0",
        },
    ],
}


# ---------------------------------------------------------------------------
# GET /v1/versions/{tenant}/{project}/{revision}/changelog
# ---------------------------------------------------------------------------


def test_get_version_changelog_ok(auth_override):
    version = {
        "id": REVISION_ID,
        "project_id": PROJECT_ID,
        "version_id": "2.0.0",
        "published": True,
        "published_at": datetime(2026, 7, 1, 12, 0, 0),
    }
    baseline = {"id": BASELINE_ID, "version_id": "1.0.0", "published": True}
    row = {
        "id": str(uuid4()),
        "tenant_id": TENANT_ID,
        "project_id": PROJECT_ID,
        "published_revision_id": REVISION_ID,
        "baseline_revision_id": BASELINE_ID,
        "changelog_json": CHANGELOG_JSON,
        "max_severity": "breaking",
        "status": "ready",
        "error": None,
        "created_at": datetime(2026, 7, 1, 12, 0, 1),
        "updated_at": datetime(2026, 7, 1, 12, 0, 1),
    }

    def _get_version(vid, _tid):
        if vid == REVISION_ID:
            return version
        if vid == BASELINE_ID:
            return baseline
        return None

    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_version_by_id.side_effect = _get_version
        mdb.get_version_changelog.return_value = row
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/{REVISION_ID}/changelog")

    assert r.status_code == 200
    body = r.json()
    assert body["publishedRevisionId"] == REVISION_ID
    assert body["baselineRevisionId"] == BASELINE_ID
    assert body["versionLabel"] == "2.0.0"
    assert body["baselineVersionLabel"] == "1.0.0"
    assert body["status"] == "ready"
    assert body["maxSeverity"] == "breaking"
    assert body["changelog"]["schemaVersion"] == "ctg.changelog.v1"
    assert len(body["changelog"]["entries"]) == 2
    assert body["changelog"]["entries"][0]["severity"] == "breaking"
    mdb.get_version_changelog.assert_called_once_with(REVISION_ID, TENANT_ID, PROJECT_ID)


def test_get_version_changelog_initial_publication_marker(auth_override):
    version = {
        "id": REVISION_ID,
        "project_id": PROJECT_ID,
        "version_id": "1.0.0",
        "published": True,
        "published_at": None,
    }
    row = {
        "published_revision_id": REVISION_ID,
        "baseline_revision_id": None,
        "changelog_json": {
            "schemaVersion": "ctg.changelog.v1",
            "initialPublication": True,
            "entries": [],
            "counts": {"total": 0},
            "maxSeverity": None,
        },
        "max_severity": None,
        "status": "initial",
        "error": None,
        "created_at": None,
        "updated_at": None,
    }
    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_version_by_id.return_value = version
        mdb.get_version_changelog.return_value = row
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/{REVISION_ID}/changelog")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "initial"
    assert body["baselineRevisionId"] is None
    assert body["baselineVersionLabel"] is None
    assert body["changelog"]["initialPublication"] is True


def test_get_version_changelog_version_missing_404(auth_override):
    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_version_by_id.return_value = None
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/{REVISION_ID}/changelog")
    assert r.status_code == 404


def test_get_version_changelog_non_uuid_revision_404_without_db_call(auth_override):
    with patch("app.version_changelog_routes.db") as mdb:
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/not-a-uuid/changelog")
    assert r.status_code == 404
    mdb.get_version_by_id.assert_not_called()


def test_get_version_changelog_wrong_project_404(auth_override):
    version = {"id": REVISION_ID, "project_id": str(uuid4()), "published": True}
    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_version_by_id.return_value = version
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/{REVISION_ID}/changelog")
    assert r.status_code == 404
    mdb.get_version_changelog.assert_not_called()


def test_get_version_changelog_unpublished_400(auth_override):
    version = {"id": REVISION_ID, "project_id": PROJECT_ID, "published": False}
    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_version_by_id.return_value = version
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/{REVISION_ID}/changelog")
    assert r.status_code == 400


def test_get_version_changelog_no_row_404(auth_override):
    version = {"id": REVISION_ID, "project_id": PROJECT_ID, "published": True}
    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_version_by_id.return_value = version
        mdb.get_version_changelog.return_value = None
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/{REVISION_ID}/changelog")
    assert r.status_code == 404


def test_get_version_changelog_failed_row_exposes_error(auth_override):
    version = {
        "id": REVISION_ID,
        "project_id": PROJECT_ID,
        "version_id": "3.0.0",
        "published": True,
    }
    row = {
        "published_revision_id": REVISION_ID,
        "baseline_revision_id": None,
        "changelog_json": None,
        "max_severity": None,
        "status": "failed",
        "error": "reconstruction failed",
    }
    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_version_by_id.return_value = version
        mdb.get_version_changelog.return_value = row
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/{REVISION_ID}/changelog")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"] == "reconstruction failed"
    assert body["changelog"] is None


def test_get_version_changelog_requires_auth():
    r = client.get(f"/v1/versions/acme/{PROJECT_ID}/{REVISION_ID}/changelog")
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /v1/versions/{tenant}/{project}/changelogs
# ---------------------------------------------------------------------------


def test_list_project_changelogs_ok_and_pending_rows(auth_override):
    project = {"id": PROJECT_ID, "slug": "payments-api"}
    rows = [
        {
            "published_revision_id": REVISION_ID,
            "version_label": "2.0.0",
            "published_at": datetime(2026, 7, 2, 9, 0, 0),
            "baseline_revision_id": BASELINE_ID,
            "baseline_version_label": "1.0.0",
            "max_severity": "breaking",
            "status": "ready",
            "error": None,
            "counts": {
                "breaking": 1,
                "non-breaking": 0,
                "docs-only": 0,
                "unclassified": 0,
                "total": 1,
            },
            "updated_at": datetime(2026, 7, 2, 9, 0, 1),
        },
        {
            # Published before CTG-3.1 backfill: no changelog row yet.
            "published_revision_id": BASELINE_ID,
            "version_label": "1.0.0",
            "published_at": datetime(2026, 6, 1, 9, 0, 0),
            "baseline_revision_id": None,
            "baseline_version_label": None,
            "max_severity": None,
            "status": None,
            "error": None,
            "counts": None,
            "updated_at": None,
        },
    ]
    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_project_by_id.return_value = project
        mdb.list_version_changelogs_for_project.return_value = rows
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/changelogs")

    assert r.status_code == 200
    body = r.json()
    assert body["projectId"] == PROJECT_ID
    assert body["filteredCount"] == 2
    first, second = body["changelogs"]
    assert first["publishedRevisionId"] == REVISION_ID
    assert first["versionLabel"] == "2.0.0"
    assert first["maxSeverity"] == "breaking"
    assert first["status"] == "ready"
    assert first["counts"]["breaking"] == 1
    assert second["status"] is None
    assert second["counts"] is None
    mdb.list_version_changelogs_for_project.assert_called_once_with(
        PROJECT_ID, TENANT_ID, limit=None
    )


def test_list_project_changelogs_passes_limit(auth_override):
    project = {"id": PROJECT_ID, "slug": "payments-api"}
    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_project_by_id.return_value = project
        mdb.list_version_changelogs_for_project.return_value = []
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/changelogs?limit=25")
    assert r.status_code == 200
    assert r.json()["filteredCount"] == 0
    mdb.list_version_changelogs_for_project.assert_called_once_with(
        PROJECT_ID, TENANT_ID, limit=25
    )


def test_list_project_changelogs_limit_bounds_422(auth_override):
    project = {"id": PROJECT_ID, "slug": "payments-api"}
    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_project_by_id.return_value = project
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/changelogs?limit=0")
    assert r.status_code == 422


def test_list_project_changelogs_project_missing_404(auth_override):
    with patch("app.version_changelog_routes.db") as mdb:
        mdb.get_project_by_id.return_value = None
        r = client.get(f"/v1/versions/acme/{PROJECT_ID}/changelogs")
    assert r.status_code == 404


def test_list_project_changelogs_non_uuid_project_400_without_db_call(auth_override):
    with patch("app.version_changelog_routes.db") as mdb:
        r = client.get("/v1/versions/acme/not-a-uuid/changelogs")
    assert r.status_code == 400
    mdb.get_project_by_id.assert_not_called()


def test_list_project_changelogs_requires_auth():
    r = client.get(f"/v1/versions/acme/{PROJECT_ID}/changelogs")
    assert r.status_code in (401, 403)
