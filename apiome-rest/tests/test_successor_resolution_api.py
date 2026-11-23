"""Tests for GET version successor resolution (#749)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "test-tenant-id",
    "user_id": "test-user-id",
    "auth_method": "jwt",
}


def _override_auth():
    return _MOCK_AUTH


def _min_version(rid: str, version_line: str, metadata=None):
    return {
        "id": rid,
        "project_id": "proj-1",
        "creator_id": "test-user-id",
        "version_id": version_line,
        "description": None,
        "change_log": None,
        "visibility": "private",
        "published": False,
        "published_at": None,
        "enabled": True,
        "parent_version_id": None,
        "merge_parent_version_id": None,
        "forked_from_revision_id": None,
        "upstream_project_id": None,
        "revision_locked": False,
        "metadata": metadata,
        "created_at": None,
        "updated_at": None,
        "creator_name": None,
        "creator_email": None,
        "project_name": "P",
        "project_slug": "p",
    }


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_get_version_resolve_returns_final_revision_and_headers():
    va = _min_version("rev-a", "1.0.0", {"successorRevisionId": "rev-b"})
    vb = _min_version("rev-b", "1.0.1", {})
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.side_effect = lambda vid, tid: (
            va if vid == "rev-a" else vb if vid == "rev-b" else None
        )
        mdb.get_version_core.side_effect = lambda vid, tid: (
            va if vid == "rev-a" else vb if vid == "rev-b" else None
        )
        mdb.resolve_successor_revision_chain.return_value = ("rev-b", ["rev-b"], "resolved", None)
        mdb.insert_version_protection_audit = MagicMock()
        r = client.get(
            "/v1/versions/tn/proj-1/rev-a?successorResolution=resolve",
        )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "rev-b"
    assert r.headers.get("etag") == '"rev-b"'
    assert r.headers.get("x-apiome-resolved-from") == "rev-a"
    assert r.headers.get("x-apiome-successor-chain") == "rev-b"
    assert r.headers.get("x-apiome-successor-resolution-status") == "resolved"


def test_get_version_successor_cycle_409():
    va = _min_version("rev-a", "1.0.0", {"successorRevisionId": "rev-b"})
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = va
        mdb.get_version_core.return_value = va
        mdb.resolve_successor_revision_chain.return_value = ("rev-a", ["rev-b"], "cycle", None)
        r = client.get(
            "/v1/versions/tn/proj-1/rev-a?successorResolution=resolve",
        )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "SUCCESSOR_CYCLE"


def test_get_version_redirect_307():
    va = _min_version("rev-a", "1.0.0", {"successorRevisionId": "rev-b"})
    vb = _min_version("rev-b", "1.0.1", {})
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.side_effect = lambda vid, tid: (
            va if vid == "rev-a" else vb if vid == "rev-b" else None
        )
        mdb.get_version_core.side_effect = lambda vid, tid: (
            va if vid == "rev-a" else vb if vid == "rev-b" else None
        )
        mdb.resolve_successor_revision_chain.return_value = ("rev-b", ["rev-b"], "resolved", None)
        r = client.get(
            "/v1/versions/tn/proj-1/rev-a?successorResolution=redirect",
            follow_redirects=False,
        )
    assert r.status_code == 307
    loc = r.headers.get("location") or ""
    assert "rev-b" in loc
    assert "successorResolution=none" in loc


#: uuid-shaped revision ids for the unit tests (the start must look like a revision id).
_A = "00000000-0000-4000-8000-00000000000a"
_B = "00000000-0000-4000-8000-00000000000b"


def _chain_row(rid: str, successor=None, protected=False, project="proj-1"):
    """A row of ``SUCCESSOR_CHAIN_SQL`` (DBP-1.14, #7197)."""
    return {"id": rid, "project_id": project, "successor": successor, "protected": protected}


def _resolve(rows, start=_A):
    """Run ``resolve_successor_revision_chain`` on prefetched chain rows; return result and calls."""
    from app.database import Database

    db = Database()
    with patch.object(db, "execute_query", return_value=rows) as eq:
        out = db.resolve_successor_revision_chain(start, "test-tenant-id", "proj-1")
    return out, eq


def test_resolve_successor_chain_unit():
    (final, hops, status, miss), eq = _resolve([_chain_row(_A, _B), _chain_row(_B)])
    assert final == _B
    assert hops == [_B]
    assert status == "resolved"
    assert miss is None
    assert eq.call_count == 1  # the whole chain is one recursive statement


def test_resolve_successor_chain_cycle():
    (_final, _hops, status, miss), _ = _resolve([_chain_row(_A, _B), _chain_row(_B, _A)])
    assert status == "cycle"
    assert miss is None


def test_resolve_successor_blocked_when_protected_ref():
    (final, hops, status, miss), _ = _resolve([_chain_row(_A, _B, protected=True)])
    assert final == _A
    assert hops == []
    assert status == "blocked_protected_ref"
    assert miss is None


def test_resolve_successor_non_uuid_start_runs_no_query():
    (final, hops, status, miss), eq = _resolve([], start="rev-a")
    assert (final, hops, status, miss) == ("rev-a", [], "missing_target", None)
    eq.assert_not_called()
