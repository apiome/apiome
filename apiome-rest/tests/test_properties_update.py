"""``PUT /v1/properties/{tenant}/{project}/{id}``: precondition and required-everywhere (CLI 6.4, #3226).

The route passes ``expectedUpdatedAt`` and ``requiredEverywhere`` to the database and maps a failed
precondition to ``409 update_conflict``; the database method checks the precondition before writing
and returns the bulk counts. The SQL was checked against a live database for the PR.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database, PropertyUpdateConflict
from app.main import app

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}
_STAMP = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def _row(**extra):
    row = {"id": "id-amount", "project_id": "p1", "name": "amount", "description": None,
           "data": {"type": "number"}, "updated_at": _STAMP}
    row.update(extra)
    return row


def _put(body, *, result=None, error=None):
    """PUT ``body`` with the database mocked; return the response and the mock."""
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with patch("app.properties_routes.db") as mock_db, patch("app.properties_routes.enforce_permission"):
            mock_db.get_project_by_id.return_value = {"id": "p1"}
            mock_db.get_property_by_id.return_value = _row()
            if error is not None:
                mock_db.update_property.side_effect = error
            else:
                mock_db.update_property.return_value = result or _row()
            return client.put("/v1/properties/acme/p1/id-amount", json=body), mock_db
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_the_route_passes_the_precondition_and_the_toggle() -> None:
    counts = {"changed": 2, "unchanged": 1, "skipped_published": 3}
    response, mock_db = _put(
        {"description": "x", "expectedUpdatedAt": "2026-10-17T12:00:00Z", "requiredEverywhere": True},
        result=_row(required_everywhere_result=counts),
    )
    assert response.status_code == 200, response.text
    kwargs = mock_db.update_property.call_args.kwargs
    assert kwargs["expected_updated_at"] == _STAMP
    assert kwargs["required_everywhere"] is True
    assert response.json()["required_everywhere_result"] == counts


def test_without_them_nothing_changes() -> None:
    response, mock_db = _put({"description": "x"})
    assert response.status_code == 200, response.text
    kwargs = mock_db.update_property.call_args.kwargs
    assert kwargs["expected_updated_at"] is None and kwargs["required_everywhere"] is None
    assert response.json()["required_everywhere_result"] is None


def test_a_stale_precondition_is_409_update_conflict() -> None:
    response, _ = _put(
        {"description": "x", "expected_updated_at": "2026-10-01T00:00:00Z"},
        error=PropertyUpdateConflict(_STAMP),
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "update_conflict"
    assert detail["current_updated_at"] == "2026-10-17T12:00:00+00:00"


def _database(existing):
    database = Database.__new__(Database)
    database.get_property_by_id = MagicMock(return_value=existing)
    database.connect = MagicMock()
    return database


def test_the_database_refuses_a_stale_precondition_before_writing() -> None:
    database = _database(_row())
    try:
        database.update_property("id-amount", "p1", {"description": "x"},
                                 expected_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    except PropertyUpdateConflict as conflict:
        assert conflict.current_updated_at == _STAMP
    else:
        raise AssertionError("expected PropertyUpdateConflict")
    database.connect.assert_not_called()


def test_a_naive_precondition_is_read_as_utc_and_nothing_to_do_returns_the_row() -> None:
    database = _database(_row())
    assert database.update_property("id-amount", "p1", {}, expected_updated_at=datetime(2026, 10, 17, 12, 0)) == _row()
    database.connect.assert_not_called()


def test_required_everywhere_alone_runs_only_the_bulk_update() -> None:
    database = _database(_row())
    cursor = MagicMock()
    cursor.fetchone.return_value = {"changed": 2, "unchanged": 0, "skipped_published": 1}
    database.connect.return_value.cursor.return_value.__enter__.return_value = cursor
    result = database.update_property("id-amount", "p1", {}, required_everywhere=False)
    assert result["required_everywhere_result"] == {"changed": 2, "unchanged": 0, "skipped_published": 1}
    [call] = cursor.execute.call_args_list
    sql, params = call.args
    assert "UPDATE apiome.class_properties" in sql and "NOT t.published" in sql
    assert params == {"property_id": "id-amount", "required": False}
    database.connect.return_value.commit.assert_called_once()
