"""Persisted merge sessions API (#2573)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import validate_authentication

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "t1",
    "user_id": "u1",
    "auth_method": "jwt",
}

PID = "00000000-0000-0000-0000-0000000000a1"
SID = "00000000-0000-0000-0000-0000000000c1"

_SESS = {
    "id": SID,
    "project_id": PID,
    "source_branch_id": None,
    "source_branch_name": "src",
    "target_branch_name": "tgt",
    "merge_base_version_id": "vb",
    "source_tip_version_id": "vs",
    "target_tip_version_id": "vt",
    "status": "preview",
    "created_by": None,
    "created_at": None,
    "updated_at": None,
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def test_get_merge_session_ok():
    with patch("app.version_merge_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "app.version_merge_routes.db.get_merge_session_detail",
        return_value={"session": _SESS, "status_events": []},
    ):
        r = client.get(f"/v1/versions/acme/{PID}/merge-sessions/{SID}")
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["mergeSession"]["id"] == SID
    assert d["statusEvents"] == []


def test_get_merge_session_unknown_project():
    with patch("app.version_merge_routes.db.get_project_by_id", return_value=None):
        r = client.get(f"/v1/versions/acme/{PID}/merge-sessions/{SID}")
    assert r.status_code == 404


def test_get_merge_session_not_found():
    with patch("app.version_merge_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "app.version_merge_routes.db.get_merge_session_detail",
        return_value=None,
    ):
        r = client.get(f"/v1/versions/acme/{PID}/merge-sessions/{SID}")
    assert r.status_code == 404


def test_list_merge_conflicts_ok():
    with patch("app.version_merge_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "app.version_merge_routes.db.list_merge_session_conflicts",
        return_value=[
            {
                "id": "x1",
                "path": "schemas.Foo",
                "kinds": ["threeWay"],
                "sort_order": 0,
                "created_at": None,
            }
        ],
    ):
        r = client.get(f"/v1/versions/acme/{PID}/merge-sessions/{SID}/conflicts")
    assert r.status_code == 200
    d = r.json()
    assert d["conflicts"][0]["path"] == "schemas.Foo"
    assert d["conflicts"][0]["kinds"] == ["threeWay"]


def test_patch_merge_session_status_ok():
    updated = {**_SESS, "status": "resolving"}
    with patch("app.version_merge_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "app.version_merge_routes.db.update_merge_session_status",
        return_value=(True, None),
    ), patch(
        "app.version_merge_routes.db.get_merge_session_detail",
        return_value={"session": updated, "status_events": []},
    ):
        r = client.patch(
            f"/v1/versions/acme/{PID}/merge-sessions/{SID}",
            json={"status": "resolving"},
        )
    assert r.status_code == 200
    assert r.json()["mergeSession"]["status"] == "resolving"


def test_patch_merge_session_invalid_transition():
    with patch("app.version_merge_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "app.version_merge_routes.db.update_merge_session_status",
        return_value=(False, "Cannot transition from applied to resolving"),
    ):
        r = client.patch(
            f"/v1/versions/acme/{PID}/merge-sessions/{SID}",
            json={"status": "resolving"},
        )
    assert r.status_code == 400
