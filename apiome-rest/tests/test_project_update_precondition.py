"""Optimistic concurrency on ``PUT /v1/projects/{tenant}/{id}`` (CLI 3.4, #3205).

``expectedUpdatedAt`` is an optional precondition: the update applies only when the project's
``updated_at`` still equals it, and the check is part of the ``UPDATE`` statement itself, so a
concurrent edit between the read and the write cannot slip through. A mismatch is a 409 with
code ``update_conflict`` and the project's current ``updated_at``, which ``apiome projects
update --from-file`` maps to exit 6.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database, ProjectUpdateConflict, _same_instant
from app.main import app

client = TestClient(app)

_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}
_UPDATED = datetime(2026, 10, 16, 12, 0, 0, 123456, tzinfo=timezone.utc)
_ROW = {
    "id": "p-1",
    "tenant_id": "tenant-1",
    "creator_id": "user-1",
    "name": "Payments",
    "description": None,
    "slug": "payments-api",
    "enabled": True,
    "metadata": {},
    "change_report_template_version_id": None,
    "publishable": True,
    "created_at": _UPDATED,
    "updated_at": _UPDATED,
    "deleted_at": None,
}


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def test_the_precondition_is_passed_to_the_write(authed) -> None:
    with patch("app.projects_routes.db") as mock_db, patch("app.projects_routes.enforce_permission"):
        mock_db.get_project_by_id.return_value = _ROW
        mock_db.update_project.return_value = {**_ROW, "name": "Payments v2"}
        response = client.put(
            "/v1/projects/acme/p-1",
            json={"name": "Payments v2", "expectedUpdatedAt": "2026-10-16T12:00:00.123456+00:00"},
        )
    assert response.status_code == 200
    kwargs = mock_db.update_project.call_args.kwargs
    assert kwargs["expected_updated_at"] == _UPDATED


def test_without_a_precondition_nothing_changes(authed) -> None:
    with patch("app.projects_routes.db") as mock_db, patch("app.projects_routes.enforce_permission"):
        mock_db.get_project_by_id.return_value = _ROW
        mock_db.update_project.return_value = _ROW
        response = client.put("/v1/projects/acme/p-1", json={"description": "x"})
    assert response.status_code == 200
    assert mock_db.update_project.call_args.kwargs["expected_updated_at"] is None


def test_a_stale_precondition_is_a_409_with_the_current_timestamp(authed) -> None:
    newer = datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)
    with patch("app.projects_routes.db") as mock_db, patch("app.projects_routes.enforce_permission"):
        mock_db.get_project_by_id.return_value = _ROW
        mock_db.update_project.side_effect = ProjectUpdateConflict(newer)
        response = client.put(
            "/v1/projects/acme/p-1",
            json={"name": "x", "expectedUpdatedAt": "2026-10-16T12:00:00Z"},
        )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "update_conflict"
    assert detail["current_updated_at"] == newer.isoformat()
    assert "re-fetch" in detail["message"]


def test_a_malformed_precondition_is_a_422(authed) -> None:
    with patch("app.projects_routes.db") as mock_db, patch("app.projects_routes.enforce_permission"):
        mock_db.get_project_by_id.return_value = _ROW
        response = client.put("/v1/projects/acme/p-1", json={"expectedUpdatedAt": "yesterday"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------


class _Cursor:
    def __init__(self, row: Optional[Dict[str, Any]]) -> None:
        self.row = row
        self.executed: List[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple) -> None:
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def _database(existing_rows: List[Optional[Dict[str, Any]]], update_row) -> tuple:
    database = Database.__new__(Database)
    reads = iter(existing_rows)
    database.get_project_by_id = lambda *_args, **_kwargs: next(reads)  # type: ignore[method-assign]
    cursor = _Cursor(update_row)
    database.connect = lambda: _Conn(cursor)  # type: ignore[method-assign]
    return database, cursor


def test_the_precondition_is_part_of_the_update_statement() -> None:
    database, cursor = _database([_ROW], {**_ROW, "name": "v2"})
    database.update_project("p-1", "tenant-1", {"name": "v2"}, expected_updated_at=_UPDATED)
    sql, params = cursor.executed[0]
    assert "AND updated_at = %s" in sql
    assert params[-1] == _UPDATED


def test_a_naive_precondition_is_read_as_utc() -> None:
    database, cursor = _database([_ROW], _ROW)
    database.update_project(
        "p-1", "tenant-1", {"name": "v2"}, expected_updated_at=_UPDATED.replace(tzinfo=None)
    )
    assert cursor.executed[0][1][-1] == _UPDATED


def test_a_stale_read_conflicts_before_writing() -> None:
    database, cursor = _database([_ROW], _ROW)
    with pytest.raises(ProjectUpdateConflict) as exc:
        database.update_project(
            "p-1", "tenant-1", {"name": "v2"}, expected_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
        )
    assert exc.value.current_updated_at == _UPDATED
    assert cursor.executed == []


def test_a_change_between_read_and_write_conflicts() -> None:
    newer = {**_ROW, "updated_at": datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)}
    # The read sees the expected timestamp; the guarded UPDATE matches nothing; the re-read
    # finds the newer row.
    database, _cursor = _database([_ROW, newer], None)
    with pytest.raises(ProjectUpdateConflict) as exc:
        database.update_project("p-1", "tenant-1", {"name": "v2"}, expected_updated_at=_UPDATED)
    assert exc.value.current_updated_at == newer["updated_at"]


def test_a_precondition_with_nothing_to_update_still_checks() -> None:
    database, _cursor = _database([_ROW, _ROW], _ROW)
    assert database.update_project("p-1", "tenant-1", {}, expected_updated_at=_UPDATED) == _ROW
    with pytest.raises(ProjectUpdateConflict):
        database.update_project(
            "p-1", "tenant-1", {}, expected_updated_at=datetime(2025, 1, 1, tzinfo=timezone.utc)
        )


def test_same_instant_compares_across_zones() -> None:
    assert _same_instant(_UPDATED, _UPDATED.astimezone(timezone.utc))
    assert _same_instant(_UPDATED.replace(tzinfo=None), _UPDATED)
    assert not _same_instant("2026-10-16", _UPDATED)
