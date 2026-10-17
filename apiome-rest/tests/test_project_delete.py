"""Project deletion for ``apiome projects delete`` (CLI 3.5, #3206).

* ``GET /v1/projects/{tenant}/{id}/deletion-impact`` — what a permanent delete would destroy,
  including for an already soft-deleted project.
* ``DELETE /v1/projects/{tenant}/{id}`` — unchanged soft delete by default; ``?permanent=true``
  deletes irreversibly in one transaction, and a non-cascading audit reference makes it a 409
  ``delete_blocked`` with nothing removed.

The data-layer cascade was also exercised against a live database while building this (a fresh
project with a published version and a class is removed entirely; one whose version carries a
``source_change_audit`` row is refused and rolled back). Here it is pinned with a scripted cursor.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg2 import errors as pg_errors

from app.auth import validate_authentication
from app.database import Database, ProjectDeleteBlocked
from app.main import app

client = TestClient(app)

_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}
_PROJECT = {"id": "p-1", "name": "Payments", "slug": "payments-api", "deleted_at": None}
_IMPACT = {
    "versions": 8,
    "published_versions": 3,
    "unpublished_versions": 5,
    "classes": 24,
    "properties": 142,
    "paths": 18,
}


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ---------------------------------------------------------------------------
# Deletion impact
# ---------------------------------------------------------------------------


def test_impact_reports_the_counts_and_whether_the_project_is_archived(authed) -> None:
    with patch("app.projects_routes.db") as mock_db, patch("app.projects_routes.enforce_permission"):
        mock_db.get_project_by_id.return_value = {**_PROJECT, "deleted_at": "2026-10-01T00:00:00Z"}
        mock_db.get_project_deletion_impact.return_value = _IMPACT
        response = client.get("/v1/projects/acme/p-1/deletion-impact")
    assert response.status_code == 200
    assert response.json() == {
        "project_id": "p-1",
        "slug": "payments-api",
        "name": "Payments",
        "deleted": True,
        **_IMPACT,
    }
    assert mock_db.get_project_by_id.call_args.kwargs == {"include_deleted": True}


def test_impact_404_for_an_unknown_project(authed) -> None:
    with patch("app.projects_routes.db") as mock_db, patch("app.projects_routes.enforce_permission"):
        mock_db.get_project_by_id.return_value = None
        response = client.get("/v1/projects/acme/nope/deletion-impact")
    assert response.status_code == 404


def test_impact_requires_projects_view(authed) -> None:
    with patch("app.projects_routes.db"), patch(
        "app.projects_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="forbidden"),
    ) as perm:
        response = client.get("/v1/projects/acme/p-1/deletion-impact")
    assert response.status_code == 403
    assert perm.call_args.args[3] == "view"


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


def test_delete_is_still_a_soft_delete_by_default(authed) -> None:
    with patch("app.projects_routes.db") as mock_db, patch("app.projects_routes.enforce_permission"):
        mock_db.get_project_by_id.return_value = _PROJECT
        mock_db.delete_project.return_value = True
        response = client.delete("/v1/projects/acme/p-1")
    assert response.status_code == 200
    assert response.json()["permanent"] is False
    mock_db.delete_project.assert_called_once_with("p-1", "tenant-1")
    mock_db.permanently_delete_project.assert_not_called()
    assert mock_db.get_project_by_id.call_args.kwargs == {"include_deleted": False}


def test_permanent_delete_removes_the_project_even_when_archived(authed) -> None:
    with patch("app.projects_routes.db") as mock_db, patch("app.projects_routes.enforce_permission"):
        mock_db.get_project_by_id.return_value = {**_PROJECT, "deleted_at": "2026-10-01T00:00:00Z"}
        mock_db.permanently_delete_project.return_value = True
        response = client.delete("/v1/projects/acme/p-1", params={"permanent": "true"})
    assert response.status_code == 200
    assert response.json() == {"message": "Project 'Payments' permanently deleted", "permanent": True}
    assert mock_db.get_project_by_id.call_args.kwargs == {"include_deleted": True}
    mock_db.delete_project.assert_not_called()


def test_a_blocked_permanent_delete_is_a_409_naming_the_table(authed) -> None:
    with patch("app.projects_routes.db") as mock_db, patch("app.projects_routes.enforce_permission"):
        mock_db.get_project_by_id.return_value = _PROJECT
        mock_db.permanently_delete_project.side_effect = ProjectDeleteBlocked("source_change_audit")
        response = client.delete("/v1/projects/acme/p-1", params={"permanent": "true"})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "delete_blocked"
    assert detail["table"] == "source_change_audit"
    assert "archive it" in detail["message"]


def test_permanent_delete_404s(authed) -> None:
    with patch("app.projects_routes.db") as mock_db, patch("app.projects_routes.enforce_permission"):
        mock_db.get_project_by_id.return_value = None
        response = client.delete("/v1/projects/acme/p-1", params={"permanent": "true"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------


class _Cursor:
    """Answers the existence and class lookups; records every statement."""

    def __init__(self, *, exists: bool, class_ids: List[str], fail_on: Optional[str] = None):
        self.exists = exists
        self.class_ids = class_ids
        self.fail_on = fail_on
        self.statements: List[str] = []
        self._last = ""

    def execute(self, sql: str, params: tuple) -> None:
        text = " ".join(sql.split())
        self.statements.append(text)
        self._last = text
        if self.fail_on and text.startswith(self.fail_on):
            raise pg_errors.ForeignKeyViolation("violates foreign key constraint")

    def fetchone(self):
        return {"?column?": 1} if self.exists else None

    def fetchall(self):
        return [{"id": cid} for cid in self.class_ids]


def _delete(cursor: _Cursor) -> Any:
    database = Database.__new__(Database)
    database._guarded_tx = lambda work: work(cursor)  # type: ignore[method-assign]
    return database.permanently_delete_project("p-1", "t-1")


def test_the_cascade_runs_in_dependency_order() -> None:
    cursor = _Cursor(exists=True, class_ids=["c-1", "c-2"])
    assert _delete(cursor) is True
    order = [s.split(" WHERE")[0] for s in cursor.statements]
    assert order == [
        "SELECT 1 FROM apiome.projects",
        "SELECT c.id FROM apiome.classes c JOIN apiome.versions v ON v.id = c.version_id",
        "UPDATE apiome.shared_path_response SET data = COALESCE(data, '{}'::jsonb)",
        "UPDATE apiome.shared_path_request_body_content SET inline_schema = COALESCE( inline_schema, '{\"type\":\"object\",\"properties\":[]}'::jsonb)",
        "DELETE FROM apiome.class_properties",
        "DELETE FROM apiome.classes",
        "DELETE FROM apiome.properties",
        "DELETE FROM apiome.merge_sessions",
        "DELETE FROM apiome.version_branches",
        "DELETE FROM apiome.projects",
    ]


def test_a_project_without_classes_skips_the_class_statements() -> None:
    cursor = _Cursor(exists=True, class_ids=[])
    assert _delete(cursor) is True
    assert not any("classes WHERE id" in s or "class_properties" in s for s in cursor.statements)


def test_an_unknown_project_writes_nothing() -> None:
    cursor = _Cursor(exists=False, class_ids=[])
    assert _delete(cursor) is False
    assert len(cursor.statements) == 1


def test_a_foreign_key_refusal_becomes_delete_blocked() -> None:
    cursor = _Cursor(exists=True, class_ids=[], fail_on="DELETE FROM apiome.projects")
    with pytest.raises(ProjectDeleteBlocked):
        _delete(cursor)


def test_impact_derives_unpublished_versions() -> None:
    database = Database.__new__(Database)
    database.execute_query = lambda *_a, **_k: [  # type: ignore[method-assign]
        {"versions": 8, "published_versions": 3, "classes": 1, "properties": 2, "paths": 3}
    ]
    assert database.get_project_deletion_impact("p-1", "t-1")["unpublished_versions"] == 5
    database.execute_query = lambda *_a, **_k: []  # type: ignore[method-assign]
    assert database.get_project_deletion_impact("p-1", "t-1") is None
