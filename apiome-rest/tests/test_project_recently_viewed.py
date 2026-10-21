"""Recently viewed projects (#510).

* ``POST   /v1/projects/{tenant}/{id}/views``         — record that the caller opened a project.
* ``GET    /v1/projects/{tenant}/recently-viewed``    — the caller's history, newest first.
* ``DELETE /v1/projects/{tenant}/recently-viewed``    — forget the caller's history.

Routes are exercised with the database patched; the data layer is pinned against the SQL it
sends, and the migration is checked for the table, key and index it promises.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database
from app.main import app

client = TestClient(app)

_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}
_API_KEY_NO_USER = {"tenant_id": "tenant-1", "auth_method": "api_key"}
_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
_FIRST = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
_LAST = datetime(2026, 10, 21, 14, 30, tzinfo=timezone.utc)


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture
def allowed():
    """Grant every permission check."""
    with patch("app.projects_routes.enforce_permission", return_value="user-1") as gate:
        yield gate


# ---------------------------------------------------------------------------
# POST /views
# ---------------------------------------------------------------------------


def test_record_view_returns_the_upserted_record(authed, allowed):
    row = {
        "project_id": _PROJECT_ID,
        "first_viewed_at": _FIRST,
        "last_viewed_at": _LAST,
        "view_count": 3,
    }
    with patch("app.projects_routes.db") as db:
        db.record_project_view.return_value = row
        res = client.post(f"/v1/projects/acme/{_PROJECT_ID}/views")

    assert res.status_code == 200
    body = res.json()
    assert body == {
        "projectId": _PROJECT_ID,
        "firstViewedAt": "2026-10-01T09:00:00Z",
        "lastViewedAt": "2026-10-21T14:30:00Z",
        "viewCount": 3,
    }
    # Tenant and user come from the token, never from the URL.
    db.record_project_view.assert_called_once_with("tenant-1", "user-1", _PROJECT_ID)


def test_record_view_404_when_project_missing_or_in_another_tenant(authed, allowed):
    with patch("app.projects_routes.db") as db:
        db.record_project_view.return_value = None
        res = client.post(f"/v1/projects/acme/{_PROJECT_ID}/views")
    assert res.status_code == 404


def test_record_view_404_for_a_non_uuid_without_touching_the_database(authed, allowed):
    with patch("app.projects_routes.db") as db:
        res = client.post("/v1/projects/acme/not-a-uuid/views")
    assert res.status_code == 404
    db.record_project_view.assert_not_called()


def test_record_view_403_without_an_attributable_user():
    app.dependency_overrides[validate_authentication] = lambda: _API_KEY_NO_USER
    try:
        with patch("app.projects_routes.get_authenticated_user_id", return_value=None), patch(
            "app.projects_routes.db"
        ) as db:
            res = client.post(f"/v1/projects/acme/{_PROJECT_ID}/views")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert res.status_code == 403
    db.record_project_view.assert_not_called()


def test_record_view_403_when_projects_view_is_not_granted(authed):
    denied = HTTPException(status_code=403, detail="denied")
    with patch("app.projects_routes.enforce_permission", side_effect=denied), patch(
        "app.projects_routes.db"
    ) as db:
        res = client.post(f"/v1/projects/acme/{_PROJECT_ID}/views")
    assert res.status_code == 403
    db.record_project_view.assert_not_called()


# ---------------------------------------------------------------------------
# GET /recently-viewed
# ---------------------------------------------------------------------------


def test_list_returns_rows_newest_first_in_camel_case(authed, allowed):
    rows = [
        {
            "id": _PROJECT_ID,
            "name": "Payments",
            "slug": "payments-api",
            "description": "Card payments",
            "first_viewed_at": _FIRST,
            "last_viewed_at": _LAST,
            "view_count": 4,
        }
    ]
    with patch("app.projects_routes.db") as db:
        db.list_recently_viewed_projects.return_value = rows
        res = client.get("/v1/projects/acme/recently-viewed")

    assert res.status_code == 200
    assert res.json() == {
        "projects": [
            {
                "id": _PROJECT_ID,
                "name": "Payments",
                "slug": "payments-api",
                "description": "Card payments",
                "firstViewedAt": "2026-10-01T09:00:00Z",
                "lastViewedAt": "2026-10-21T14:30:00Z",
                "viewCount": 4,
            }
        ]
    }
    db.list_recently_viewed_projects.assert_called_once_with("tenant-1", "user-1", 10)
    # Not captured by GET /{tenant_slug}/{project_id}.
    db.get_project_by_id.assert_not_called()


def test_list_empty_history(authed, allowed):
    with patch("app.projects_routes.db") as db:
        db.list_recently_viewed_projects.return_value = []
        res = client.get("/v1/projects/acme/recently-viewed")
    assert res.status_code == 200
    assert res.json() == {"projects": []}


def test_list_passes_the_limit(authed, allowed):
    with patch("app.projects_routes.db") as db:
        db.list_recently_viewed_projects.return_value = []
        res = client.get("/v1/projects/acme/recently-viewed?limit=5")
    assert res.status_code == 200
    db.list_recently_viewed_projects.assert_called_once_with("tenant-1", "user-1", 5)


@pytest.mark.parametrize("limit", [0, 51, -1])
def test_list_rejects_out_of_range_limits(authed, allowed, limit):
    with patch("app.projects_routes.db") as db:
        res = client.get(f"/v1/projects/acme/recently-viewed?limit={limit}")
    assert res.status_code == 422
    db.list_recently_viewed_projects.assert_not_called()


def test_list_403_without_an_attributable_user():
    app.dependency_overrides[validate_authentication] = lambda: _API_KEY_NO_USER
    try:
        with patch("app.projects_routes.get_authenticated_user_id", return_value=None), patch(
            "app.projects_routes.db"
        ) as db:
            res = client.get("/v1/projects/acme/recently-viewed")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert res.status_code == 403
    db.list_recently_viewed_projects.assert_not_called()


# ---------------------------------------------------------------------------
# DELETE /recently-viewed
# ---------------------------------------------------------------------------


def test_clear_forgets_only_the_callers_history(authed):
    with patch("app.projects_routes.db") as db:
        db.clear_recently_viewed_projects.return_value = 2
        res = client.delete("/v1/projects/acme/recently-viewed")
    assert res.status_code == 204
    db.clear_recently_viewed_projects.assert_called_once_with("tenant-1", "user-1")
    # Not captured by DELETE /{tenant_slug}/{project_id}.
    db.soft_delete_project.assert_not_called()


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------


def _db_with_rows(rows):
    """A Database whose execute_query returns ``rows`` and records its call."""
    database = Database.__new__(Database)
    database.execute_query = MagicMock(return_value=rows)
    database._execute_write = MagicMock(return_value=len(rows))
    return database


def test_record_project_view_upserts_scoped_to_live_tenant_projects():
    row = {"project_id": _PROJECT_ID, "first_viewed_at": _FIRST, "last_viewed_at": _LAST, "view_count": 1}
    database = _db_with_rows([row])

    assert database.record_project_view("tenant-1", "user-1", _PROJECT_ID) == row

    sql, params = database.execute_query.call_args.args
    assert "INSERT INTO apiome.project_views" in sql
    assert "p.tenant_id = %s::uuid AND p.deleted_at IS NULL" in sql
    assert "ON CONFLICT (user_id, project_id) DO UPDATE" in sql
    assert "view_count = apiome.project_views.view_count + 1" in sql
    assert params == ("user-1", _PROJECT_ID, "tenant-1")


def test_record_project_view_none_when_nothing_matched():
    database = _db_with_rows([])
    assert database.record_project_view("tenant-1", "user-1", _PROJECT_ID) is None


def test_list_recently_viewed_skips_deleted_and_orders_newest_first():
    database = _db_with_rows([])
    database.list_recently_viewed_projects("tenant-1", "user-1", 7)

    sql, params = database.execute_query.call_args.args
    assert "p.deleted_at IS NULL" in sql
    assert "ORDER BY pv.last_viewed_at DESC" in sql
    assert params == ("tenant-1", "user-1", 7)


def test_clear_recently_viewed_is_scoped_to_the_user():
    database = _db_with_rows([{}, {}])
    assert database.clear_recently_viewed_projects("tenant-1", "user-1") == 2

    sql, params = database._execute_write.call_args.args
    assert "DELETE FROM apiome.project_views" in sql
    assert "user_id = %s::uuid" in sql
    assert params == ("tenant-1", "user-1")


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

_MIGRATION_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS apiome.project_views",
    "user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE",
    "project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE",
    "tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE",
    "view_count INTEGER NOT NULL DEFAULT 1",
    "CONSTRAINT project_views_pkey PRIMARY KEY (user_id, project_id)",
    "CREATE INDEX IF NOT EXISTS idx_project_views_tenant_user_recent",
    "(tenant_id, user_id, last_viewed_at DESC)",
)


def test_migration_creates_the_project_views_table(repo_root: Path):
    path = repo_root / "apiome-db" / "scripts" / "V308__project_views_510.sql"
    text = path.read_text()
    missing = [frag for frag in _MIGRATION_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
