"""Time spent per project (#544).

``GET /v1/projects/{tenant}/time-spent?days=`` — the caller's own active time per project. The
route is exercised with the database patched; the data layer is pinned against the SQL it sends,
and the migration is checked for the table, key and constraint it promises.
"""

from __future__ import annotations

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


def _row(pid: str, name: str, seconds: int, total: int) -> dict:
    return {"id": pid, "name": name, "slug": name.lower(), "seconds": seconds, "total_seconds": total}


def test_returns_the_breakdown_most_time_first_with_the_total(authed, allowed):
    rows = [_row("p-1", "Payments", 5400, 7200), _row("p-2", "Orders", 1800, 7200)]
    with patch("app.projects_routes.db") as db:
        db.list_project_time.return_value = rows
        res = client.get("/v1/projects/acme/time-spent?days=30")

    assert res.status_code == 200
    assert res.json() == {
        "days": 30,
        "totalSeconds": 7200,
        "projects": [
            {"id": "p-1", "name": "Payments", "slug": "payments", "seconds": 5400},
            {"id": "p-2", "name": "Orders", "slug": "orders", "seconds": 1800},
        ],
    }
    # Tenant and user come from the token; the caller only ever sees their own time.
    db.list_project_time.assert_called_once_with("tenant-1", "user-1", 30, 50)


def test_defaults_to_seven_days(authed, allowed):
    with patch("app.projects_routes.db") as db:
        db.list_project_time.return_value = []
        res = client.get("/v1/projects/acme/time-spent")
    assert res.status_code == 200
    assert res.json() == {"days": 7, "totalSeconds": 0, "projects": []}
    db.list_project_time.assert_called_once_with("tenant-1", "user-1", 7, 50)
    # Not captured by GET /{tenant_slug}/{project_id}.
    db.get_project_by_id.assert_not_called()


@pytest.mark.parametrize("days", [0, 91, -7])
def test_rejects_windows_out_of_range(authed, allowed, days):
    with patch("app.projects_routes.db") as db:
        res = client.get(f"/v1/projects/acme/time-spent?days={days}")
    assert res.status_code == 422
    db.list_project_time.assert_not_called()


def test_403_without_an_attributable_user():
    app.dependency_overrides[validate_authentication] = lambda: _API_KEY_NO_USER
    try:
        with patch("app.projects_routes.get_authenticated_user_id", return_value=None), patch(
            "app.projects_routes.db"
        ) as db:
            res = client.get("/v1/projects/acme/time-spent")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert res.status_code == 403
    db.list_project_time.assert_not_called()


def test_403_when_projects_view_is_not_granted(authed):
    denied = HTTPException(status_code=403, detail="denied")
    with patch("app.projects_routes.enforce_permission", side_effect=denied), patch(
        "app.projects_routes.db"
    ) as db:
        res = client.get("/v1/projects/acme/time-spent")
    assert res.status_code == 403
    db.list_project_time.assert_not_called()


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------


def test_list_project_time_is_scoped_windowed_and_totalled():
    database = Database.__new__(Database)
    database.execute_query = MagicMock(return_value=[])

    assert database.list_project_time("tenant-1", "user-1", 7, 50) == []

    sql, params = database.execute_query.call_args.args
    assert params == ("tenant-1", "user-1", 7, 50)
    assert "pt.user_id = %s::uuid" in sql
    assert "p.deleted_at IS NULL" in sql
    assert "pt.day > (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date - %s::int" in sql
    assert "SUM(SUM(pt.active_seconds)) OVER ()" in sql
    assert "ORDER BY seconds DESC" in sql


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

_MIGRATION_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS apiome.project_time",
    "user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE",
    "project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE",
    "tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE",
    "day DATE NOT NULL",
    "active_seconds INTEGER NOT NULL DEFAULT 0",
    "CONSTRAINT project_time_pkey PRIMARY KEY (user_id, project_id, day)",
    "CHECK (active_seconds BETWEEN 0 AND 86400)",
    "CREATE INDEX IF NOT EXISTS idx_project_time_tenant_user_day",
)


def test_migration_creates_the_project_time_table(repo_root: Path):
    text = (repo_root / "apiome-db" / "scripts" / "V310__project_time_544.sql").read_text()
    missing = [frag for frag in _MIGRATION_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
