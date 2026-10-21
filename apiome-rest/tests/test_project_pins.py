"""Pinned projects (#513).

* ``GET    /v1/projects/{tenant}/pinned``          — the caller's pins, newest first.
* ``PUT    /v1/projects/{tenant}/{id}/pin``        — pin a project (idempotent, 409 past 8).
* ``DELETE /v1/projects/{tenant}/{id}/pin``        — unpin a project (idempotent).

Routes are exercised with the database patched; the data layer is pinned against a scripted
cursor, and the migration is checked for the table, key and index it promises.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database
from app.main import app
from app.projects_routes import PROJECT_PIN_LIMIT

client = TestClient(app)

_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}
_API_KEY_NO_USER = {"tenant_id": "tenant-1", "auth_method": "api_key"}
_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
_PINNED_AT = datetime(2026, 10, 21, 14, 30, tzinfo=timezone.utc)


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


def test_the_limit_is_eight():
    assert PROJECT_PIN_LIMIT == 8


# ---------------------------------------------------------------------------
# PUT /pin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["pinned", "already_pinned"])
def test_pin_returns_the_pin_with_count_and_limit(authed, allowed, status):
    with patch("app.projects_routes.db") as db:
        db.pin_project.return_value = {
            "status": status,
            "pin": {"project_id": _PROJECT_ID, "pinned_at": _PINNED_AT},
            "count": 3,
        }
        res = client.put(f"/v1/projects/acme/{_PROJECT_ID}/pin")

    assert res.status_code == 200
    assert res.json() == {
        "projectId": _PROJECT_ID,
        "pinnedAt": "2026-10-21T14:30:00Z",
        "pinnedCount": 3,
        "pinLimit": 8,
    }
    db.pin_project.assert_called_once_with("tenant-1", "user-1", _PROJECT_ID, limit=8)


def test_pin_409_when_the_limit_is_reached(authed, allowed):
    with patch("app.projects_routes.db") as db:
        db.pin_project.return_value = {"status": "limit_reached", "pin": None, "count": 8}
        res = client.put(f"/v1/projects/acme/{_PROJECT_ID}/pin")

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "pin_limit_reached"
    assert detail["limit"] == 8
    assert "Unpin one first" in detail["message"]


def test_pin_404_when_project_missing_or_in_another_tenant(authed, allowed):
    with patch("app.projects_routes.db") as db:
        db.pin_project.return_value = {"status": "not_found", "pin": None, "count": 0}
        res = client.put(f"/v1/projects/acme/{_PROJECT_ID}/pin")
    assert res.status_code == 404


def test_pin_404_for_a_non_uuid_without_touching_the_database(authed, allowed):
    with patch("app.projects_routes.db") as db:
        res = client.put("/v1/projects/acme/not-a-uuid/pin")
    assert res.status_code == 404
    db.pin_project.assert_not_called()


def test_pin_403_without_an_attributable_user():
    app.dependency_overrides[validate_authentication] = lambda: _API_KEY_NO_USER
    try:
        with patch("app.projects_routes.get_authenticated_user_id", return_value=None), patch(
            "app.projects_routes.db"
        ) as db:
            res = client.put(f"/v1/projects/acme/{_PROJECT_ID}/pin")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert res.status_code == 403
    db.pin_project.assert_not_called()


def test_pin_403_when_projects_view_is_not_granted(authed):
    denied = HTTPException(status_code=403, detail="denied")
    with patch("app.projects_routes.enforce_permission", side_effect=denied), patch(
        "app.projects_routes.db"
    ) as db:
        res = client.put(f"/v1/projects/acme/{_PROJECT_ID}/pin")
    assert res.status_code == 403
    db.pin_project.assert_not_called()


# ---------------------------------------------------------------------------
# DELETE /pin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("removed", [True, False])
def test_unpin_is_idempotent(authed, removed):
    with patch("app.projects_routes.db") as db:
        db.unpin_project.return_value = removed
        res = client.delete(f"/v1/projects/acme/{_PROJECT_ID}/pin")
    assert res.status_code == 204
    db.unpin_project.assert_called_once_with("tenant-1", "user-1", _PROJECT_ID)
    # Not captured by DELETE /{tenant_slug}/{project_id}.
    db.soft_delete_project.assert_not_called()


def test_unpin_a_non_uuid_is_a_no_op(authed):
    with patch("app.projects_routes.db") as db:
        res = client.delete("/v1/projects/acme/not-a-uuid/pin")
    assert res.status_code == 204
    db.unpin_project.assert_not_called()


# ---------------------------------------------------------------------------
# GET /pinned
# ---------------------------------------------------------------------------


def test_list_returns_pins_newest_first_with_the_limit(authed, allowed):
    rows = [
        {
            "id": _PROJECT_ID,
            "name": "Payments",
            "slug": "payments-api",
            "description": None,
            "pinned_at": _PINNED_AT,
        }
    ]
    with patch("app.projects_routes.db") as db:
        db.list_pinned_projects.return_value = rows
        res = client.get("/v1/projects/acme/pinned")

    assert res.status_code == 200
    assert res.json() == {
        "projects": [
            {
                "id": _PROJECT_ID,
                "name": "Payments",
                "slug": "payments-api",
                "description": None,
                "pinnedAt": "2026-10-21T14:30:00Z",
            }
        ],
        "pinLimit": 8,
    }
    db.list_pinned_projects.assert_called_once_with("tenant-1", "user-1", 8)
    db.get_project_by_id.assert_not_called()


def test_list_403_without_an_attributable_user():
    app.dependency_overrides[validate_authentication] = lambda: _API_KEY_NO_USER
    try:
        with patch("app.projects_routes.get_authenticated_user_id", return_value=None), patch(
            "app.projects_routes.db"
        ) as db:
            res = client.get("/v1/projects/acme/pinned")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert res.status_code == 403
    db.list_pinned_projects.assert_not_called()


# ---------------------------------------------------------------------------
# Data layer — pin_project against a scripted cursor
# ---------------------------------------------------------------------------


class _Cursor:
    """A cursor that answers each SELECT from a script and records every statement."""

    def __init__(self, project: Optional[dict], count: int, existing: Optional[dict]):
        self.project = project
        self.count = count
        self.existing = existing
        self.statements: List[str] = []
        self._last: Any = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple = None) -> None:
        self.statements.append(sql)
        if "pg_advisory_xact_lock" in sql:
            self._last = None
        elif "FROM apiome.projects p" in sql and "COUNT" not in sql:
            self._last = self.project
        elif "COUNT(*)" in sql:
            self._last = {"n": self.count}
        elif "SELECT project_id, pinned_at" in sql:
            self._last = self.existing
        elif "INSERT INTO apiome.project_pins" in sql:
            self._last = {"project_id": _PROJECT_ID, "pinned_at": _PINNED_AT}

    def fetchone(self):
        return self._last


def _database(cursor: _Cursor) -> tuple[Database, MagicMock]:
    conn = MagicMock()
    conn.cursor.return_value = cursor
    database = Database.__new__(Database)
    database.connect = MagicMock(return_value=conn)
    return database, conn


def test_pin_project_inserts_under_the_limit():
    cursor = _Cursor(project={"id": _PROJECT_ID}, count=2, existing=None)
    database, conn = _database(cursor)

    result = database.pin_project("tenant-1", "user-1", _PROJECT_ID, limit=8)

    assert result["status"] == "pinned"
    assert result["count"] == 3
    assert "pg_advisory_xact_lock" in cursor.statements[0]
    assert any("INSERT INTO apiome.project_pins" in s for s in cursor.statements)
    conn.commit.assert_called_once()


def test_pin_project_refuses_at_the_limit_without_writing():
    cursor = _Cursor(project={"id": _PROJECT_ID}, count=8, existing=None)
    database, _ = _database(cursor)

    result = database.pin_project("tenant-1", "user-1", _PROJECT_ID, limit=8)

    assert result == {"status": "limit_reached", "pin": None, "count": 8}
    assert not any("INSERT" in s for s in cursor.statements)


def test_pin_project_is_idempotent_even_at_the_limit():
    existing = {"project_id": _PROJECT_ID, "pinned_at": _PINNED_AT}
    cursor = _Cursor(project={"id": _PROJECT_ID}, count=8, existing=existing)
    database, _ = _database(cursor)

    result = database.pin_project("tenant-1", "user-1", _PROJECT_ID, limit=8)

    assert result["status"] == "already_pinned"
    assert result["pin"] == existing
    assert not any("INSERT" in s for s in cursor.statements)


def test_pin_project_not_found_for_a_missing_or_foreign_project():
    cursor = _Cursor(project=None, count=0, existing=None)
    database, _ = _database(cursor)

    result = database.pin_project("tenant-1", "user-1", _PROJECT_ID, limit=8)

    assert result["status"] == "not_found"
    assert not any("INSERT" in s for s in cursor.statements)


def test_pin_project_counts_only_live_projects():
    cursor = _Cursor(project={"id": _PROJECT_ID}, count=0, existing=None)
    database, _ = _database(cursor)
    database.pin_project("tenant-1", "user-1", _PROJECT_ID, limit=8)

    count_sql = next(s for s in cursor.statements if "COUNT(*)" in s)
    assert "p.deleted_at IS NULL" in count_sql


def test_pin_project_rolls_back_on_error():
    conn = MagicMock()
    conn.cursor.side_effect = RuntimeError("boom")
    database = Database.__new__(Database)
    database.connect = MagicMock(return_value=conn)

    with pytest.raises(RuntimeError):
        database.pin_project("tenant-1", "user-1", _PROJECT_ID, limit=8)
    conn.rollback.assert_called_once()


def test_unpin_and_list_are_scoped_to_the_user():
    database = Database.__new__(Database)
    database._execute_write = MagicMock(return_value=1)
    database.execute_query = MagicMock(return_value=[])

    assert database.unpin_project("tenant-1", "user-1", _PROJECT_ID) is True
    sql, params = database._execute_write.call_args.args
    assert "DELETE FROM apiome.project_pins" in sql
    assert params == ("tenant-1", "user-1", _PROJECT_ID)

    database.list_pinned_projects("tenant-1", "user-1", 8)
    sql, params = database.execute_query.call_args.args
    assert "p.deleted_at IS NULL" in sql
    assert "ORDER BY pp.pinned_at DESC" in sql
    assert params == ("tenant-1", "user-1", 8)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

_MIGRATION_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS apiome.project_pins",
    "user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE",
    "project_id UUID NOT NULL REFERENCES apiome.projects(id) ON DELETE CASCADE",
    "tenant_id UUID NOT NULL REFERENCES apiome.tenants(id) ON DELETE CASCADE",
    "CONSTRAINT project_pins_pkey PRIMARY KEY (user_id, project_id)",
    "CREATE INDEX IF NOT EXISTS idx_project_pins_tenant_user_recent",
    "(tenant_id, user_id, pinned_at DESC)",
)


def test_migration_creates_the_project_pins_table(repo_root: Path):
    text = (repo_root / "apiome-db" / "scripts" / "V309__project_pins_513.sql").read_text()
    missing = [frag for frag in _MIGRATION_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
