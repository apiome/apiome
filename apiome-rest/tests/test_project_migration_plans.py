"""``GET /v1/migration-plans/{tenant}/projects/{project_id}`` (CLI 3.6, #3207).

Every migration plan of a project with its rules, in one call, for ``apiome projects export``.
The SQL grouping is pinned with a stubbed ``execute_query``; it was also run against a live
database (a two-version project with one saved plan reads back as one plan with its rule).
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database
from app.main import app

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}


def _authed():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH


def _clear():
    app.dependency_overrides.pop(validate_authentication, None)


def test_route_returns_the_projects_plans() -> None:
    _authed()
    try:
        with patch("app.migration_plans_routes.db") as mock_db, patch(
            "app.migration_plans_routes.enforce_permission"
        ) as perm:
            mock_db.get_project_by_id.return_value = {"id": "p-1"}
            mock_db.get_migration_plans_for_project.return_value = [{"id": "mp1", "rules": []}]
            response = client.get("/v1/migration-plans/acme/projects/p-1")
        assert response.status_code == 200
        assert response.json() == {"plans": [{"id": "mp1", "rules": []}]}
        mock_db.get_migration_plans_for_project.assert_called_once_with("p-1", "tenant-1")
        assert perm.call_args.args[3] == "view"
    finally:
        _clear()


def test_route_404s_for_an_unknown_project() -> None:
    _authed()
    try:
        with patch("app.migration_plans_routes.db") as mock_db, patch(
            "app.migration_plans_routes.enforce_permission"
        ):
            mock_db.get_project_by_id.return_value = None
            response = client.get("/v1/migration-plans/acme/projects/nope")
        assert response.status_code == 404
    finally:
        _clear()


def test_route_requires_projects_view() -> None:
    _authed()
    try:
        with patch("app.migration_plans_routes.db"), patch(
            "app.migration_plans_routes.enforce_permission",
            side_effect=HTTPException(status_code=403, detail="forbidden"),
        ):
            assert client.get("/v1/migration-plans/acme/projects/p-1").status_code == 403
    finally:
        _clear()


def test_rows_group_into_plans_with_their_rules() -> None:
    database = Database.__new__(Database)
    rows = [
        {"plan_id": "mp1", "from_version_id": "v1", "to_version_id": "v2", "created_at": None,
         "updated_at": None, "class_name": "Address", "source_property": "zip", "rule": {"r": 1}},
        {"plan_id": "mp1", "from_version_id": "v1", "to_version_id": "v2", "created_at": None,
         "updated_at": None, "class_name": "Order", "source_property": "id", "rule": {"r": 2}},
        {"plan_id": "mp2", "from_version_id": "v2", "to_version_id": "v3", "created_at": None,
         "updated_at": None, "class_name": None, "source_property": None, "rule": None},
    ]
    database.execute_query = lambda *_a, **_k: rows  # type: ignore[method-assign]
    plans = database.get_migration_plans_for_project("p-1", "tenant-1")
    assert [p["id"] for p in plans] == ["mp1", "mp2"]
    assert [r["class_name"] for r in plans[0]["rules"]] == ["Address", "Order"]
    assert plans[1]["rules"] == []
