"""``DELETE /v1/properties/{tenant}/{project}/{id}?force=true`` (CLI 6.5, #3227).

Without ``force`` the route soft-deletes as before. With it, the database removes the class
attributes using the property and deletes it in one transaction, reporting ``detached``; a use in
a published version is refused with ``409 property_in_published_version``. The SQL was checked
against a scratch Postgres 16 for the PR.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database, PropertyUsedInPublishedVersion
from app.main import app

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}
_PUBLISHED = [{"class_name": "Charge", "attribute_name": "amount", "version": "1.0.0"}]


def _delete(path, *, forced=None, error=None):
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with patch("app.properties_routes.db") as mock_db, patch("app.properties_routes.enforce_permission"):
            mock_db.get_project_by_id.return_value = {"id": "p1"}
            mock_db.get_property_by_id.return_value = {"id": "id-amount", "name": "amount"}
            mock_db.delete_property.return_value = True
            if error is not None:
                mock_db.force_delete_property.side_effect = error
            else:
                mock_db.force_delete_property.return_value = forced
            return client.delete(path), mock_db
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_without_force_the_delete_is_unchanged() -> None:
    response, mock_db = _delete("/v1/properties/acme/p1/id-amount")
    assert response.status_code == 200, response.text
    assert response.json() == {"message": "Property 'amount' deleted successfully"}
    mock_db.force_delete_property.assert_not_called()


def test_force_reports_how_many_attributes_were_removed() -> None:
    response, mock_db = _delete("/v1/properties/acme/p1/id-amount?force=true", forced=3)
    assert response.status_code == 200, response.text
    assert response.json()["detached"] == 3
    mock_db.force_delete_property.assert_called_once_with("id-amount", "p1")
    mock_db.delete_property.assert_not_called()


def test_force_with_a_published_use_is_409() -> None:
    response, _ = _delete("/v1/properties/acme/p1/id-amount?force=true", error=PropertyUsedInPublishedVersion(_PUBLISHED))
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "property_in_published_version"
    assert detail["uses"] == _PUBLISHED


def test_force_on_a_property_deleted_meanwhile_is_404() -> None:
    response, _ = _delete("/v1/properties/acme/p1/id-amount?force=true", forced=None)
    assert response.status_code == 404


def _database(*fetches, rowcount=0):
    """A Database whose cursor answers ``fetchone`` / ``fetchall`` in order."""
    database = Database.__new__(Database)
    cursor = MagicMock()
    cursor.fetchone.side_effect = [f for f in fetches if not isinstance(f, list)]
    cursor.fetchall.side_effect = [f for f in fetches if isinstance(f, list)]
    cursor.rowcount = rowcount
    database.connect = MagicMock()
    database.connect.return_value.cursor.return_value.__enter__.return_value = cursor
    return database, cursor


def test_the_database_removes_then_deletes_in_one_commit() -> None:
    database, cursor = _database({"id": "id-amount"}, [], rowcount=2)
    assert database.force_delete_property("id-amount", "p1") == 2
    sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert "FOR UPDATE" in sql[0]
    assert "v.published" in sql[1]
    assert "DELETE FROM apiome.class_properties" in sql[2] and "NOT v.published" in sql[2]
    assert "SET deleted_at" in sql[3]
    database.connect.return_value.commit.assert_called_once()


def test_the_database_refuses_published_uses_and_rolls_back() -> None:
    database, cursor = _database({"id": "id-amount"}, list(_PUBLISHED))
    try:
        database.force_delete_property("id-amount", "p1")
    except PropertyUsedInPublishedVersion as refused:
        assert refused.uses == _PUBLISHED
    else:
        raise AssertionError("expected PropertyUsedInPublishedVersion")
    assert len(cursor.execute.call_args_list) == 2
    database.connect.return_value.commit.assert_not_called()
    database.connect.return_value.rollback.assert_called()


def test_the_database_returns_none_for_a_missing_property() -> None:
    database, _ = _database(None)
    assert database.force_delete_property("nope", "p1") is None
    database.connect.return_value.commit.assert_not_called()
