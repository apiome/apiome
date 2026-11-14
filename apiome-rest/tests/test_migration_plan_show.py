"""``GET /v1/migration-plans/{tenant}/{plan_id}`` (CLI 11.3, #3262).

One migration plan by id, for ``apiome migrations show``. The route is tested with a mocked
``db``; the SQL row folding with a stubbed ``execute_query``.
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
_PLAN_ID = "3a91c2d4-5e6f-4a1b-8c2d-0e1f2a3bb41c"


def _authed():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH


def _clear():
    app.dependency_overrides.pop(validate_authentication, None)


def test_route_returns_the_plan() -> None:
    _authed()
    try:
        with patch("app.migration_plans_routes.db") as mock_db, patch(
            "app.migration_plans_routes.enforce_permission"
        ) as perm:
            mock_db.get_migration_plan.return_value = {"id": _PLAN_ID, "rules": []}
            response = client.get(f"/v1/migration-plans/acme/{_PLAN_ID}")
        assert response.status_code == 200
        assert response.json() == {"id": _PLAN_ID, "rules": []}
        mock_db.get_migration_plan.assert_called_once_with(_PLAN_ID, "tenant-1")
        assert perm.call_args.args[2:] == ("projects", "view")
    finally:
        _clear()


def test_route_404s_for_an_unknown_plan() -> None:
    _authed()
    try:
        with patch("app.migration_plans_routes.db") as mock_db, patch(
            "app.migration_plans_routes.enforce_permission"
        ):
            mock_db.get_migration_plan.return_value = None
            response = client.get(f"/v1/migration-plans/acme/{_PLAN_ID}")
        assert response.status_code == 404
        assert _PLAN_ID in response.json()["detail"]
    finally:
        _clear()


def test_route_404s_for_a_non_uuid_without_querying() -> None:
    _authed()
    try:
        with patch("app.migration_plans_routes.db") as mock_db, patch(
            "app.migration_plans_routes.enforce_permission"
        ):
            response = client.get("/v1/migration-plans/acme/not-a-uuid")
        assert response.status_code == 404
        mock_db.get_migration_plan.assert_not_called()
    finally:
        _clear()


def test_route_requires_projects_view() -> None:
    _authed()
    try:
        with patch("app.migration_plans_routes.db"), patch(
            "app.migration_plans_routes.enforce_permission",
            side_effect=HTTPException(status_code=403, detail="forbidden"),
        ):
            assert client.get(f"/v1/migration-plans/acme/{_PLAN_ID}").status_code == 403
    finally:
        _clear()


def test_counts_path_still_reaches_the_counts_route() -> None:
    _authed()
    try:
        with patch("app.migration_plans_routes.db") as mock_db:
            mock_db.get_migration_plan_rule_counts.return_value = {"Charge": 2}
            response = client.get(
                "/v1/migration-plans/acme/counts",
                params={"projectId": "p", "fromVersionId": "a", "toVersionId": "b"},
            )
        assert response.status_code == 200
        assert response.json() == {"counts": {"Charge": 2}}
        mock_db.get_migration_plan.assert_not_called()
    finally:
        _clear()


def _row(**overrides):
    row = {
        "plan_id": _PLAN_ID, "project_id": "p-1", "project_slug": "payments-api",
        "project_name": "Payments API", "from_version_id": "v1", "from_version": "2.0.0",
        "to_version_id": "v2", "to_version": "2.1.0", "created_at": "c", "updated_at": "u",
        "class_name": None, "source_property": None, "rule": None,
    }
    row.update(overrides)
    return row


def test_rows_fold_into_one_plan_with_its_rules() -> None:
    database = Database.__new__(Database)
    rows = [
        _row(class_name="Charge", source_property="fee", rule={"r": 1}),
        _row(class_name="Charge", source_property="legacy_status", rule={"r": 2}),
    ]
    seen = {}

    def _query(sql, params):
        seen["params"] = params
        return rows

    database.execute_query = _query  # type: ignore[method-assign]
    plan = database.get_migration_plan(_PLAN_ID, "tenant-1")
    assert seen["params"] == ("tenant-1", _PLAN_ID)
    assert plan == {
        "id": _PLAN_ID, "project_id": "p-1", "project_slug": "payments-api",
        "project_name": "Payments API", "from_version_id": "v1", "from_version": "2.0.0",
        "to_version_id": "v2", "to_version": "2.1.0", "created_at": "c", "updated_at": "u",
        "rules": [
            {"class_name": "Charge", "source_property": "fee", "rule": {"r": 1}},
            {"class_name": "Charge", "source_property": "legacy_status", "rule": {"r": 2}},
        ],
    }


def test_a_plan_without_rules_has_an_empty_list() -> None:
    database = Database.__new__(Database)
    database.execute_query = lambda *_a, **_k: [_row()]  # type: ignore[method-assign]
    assert database.get_migration_plan(_PLAN_ID, "tenant-1")["rules"] == []


def test_no_rows_is_none() -> None:
    database = Database.__new__(Database)
    database.execute_query = lambda *_a, **_k: []  # type: ignore[method-assign]
    assert database.get_migration_plan(_PLAN_ID, "tenant-1") is None
