"""Branch divergence API tests (#2721)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.version_merge_routes import _strong_etag_for_branch_tips

client = TestClient(app)

_TENANT = "t1"
_PROJECT_ID = "00000000-0000-0000-0000-0000000000a1"
_BRANCH_ID = "00000000-0000-0000-0000-0000000000b1"
_AGAINST_ID = "00000000-0000-0000-0000-0000000000b2"
_OTHER_PROJECT_ID = "00000000-0000-0000-0000-0000000000a2"

_MOCK_AUTH = {
    "tenant_id": _TENANT,
    "user_id": "u1",
    "auth_method": "jwt",
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def _branch_row(branch_id: str, project_id: str, name: str, tip_id: str, *, is_default: bool = False):
    return {
        "id": branch_id,
        "project_id": project_id,
        "name": name,
        "tip_version_id": tip_id,
        "is_default": is_default,
    }


def test_divergence_success_with_against_branch_and_etag():
    with patch("app.version_merge_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": _PROJECT_ID}
        mdb.get_version_branch_by_id.side_effect = [
            _branch_row(_BRANCH_ID, _PROJECT_ID, "feature/x", "rev-feature"),
            _branch_row(_AGAINST_ID, _PROJECT_ID, "main", "rev-main", is_default=True),
        ]
        mdb.compute_branch_divergence.return_value = {
            "merge_base_revision_id": "rev-base",
            "merge_base_created_at": "2026-04-20T12:00:00Z",
            "ahead_count": 3,
            "behind_count": 1,
            "ahead_sample": [{"revisionId": "rev-f3", "shortMessage": "feature: add field"}],
            "behind_sample": [{"revisionId": "rev-m1", "shortMessage": "main: tighten schema"}],
        }

        r = client.get(
            f"/v1/versions/acme/{_PROJECT_ID}/version-branches/{_BRANCH_ID}/divergence?against={_AGAINST_ID}"
        )

    assert r.status_code == 200
    data = r.json()
    assert data["branch"]["id"] == _BRANCH_ID
    assert data["against"]["id"] == _AGAINST_ID
    assert data["mergeBase"]["revisionId"] == "rev-base"
    assert data["ahead"] == 3
    assert data["behind"] == 1
    assert data["aheadSample"][0]["revisionId"] == "rev-f3"
    assert data["behindSample"][0]["revisionId"] == "rev-m1"
    assert r.headers.get("etag") == _strong_etag_for_branch_tips("rev-feature", "rev-main")
    mdb.compute_branch_divergence.assert_called_once_with(
        project_id=_PROJECT_ID,
        tenant_id=_TENANT,
        branch_tip_revision_id="rev-feature",
        against_tip_revision_id="rev-main",
        sample_limit=5,
    )


def test_divergence_defaults_to_project_default_branch():
    with patch("app.version_merge_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": _PROJECT_ID}
        mdb.get_version_branch_by_id.return_value = _branch_row(
            _BRANCH_ID, _PROJECT_ID, "feature/x", "rev-feature"
        )
        mdb.list_version_branches_for_project.return_value = [
            _branch_row(_BRANCH_ID, _PROJECT_ID, "feature/x", "rev-feature"),
            _branch_row(_AGAINST_ID, _PROJECT_ID, "main", "rev-main", is_default=True),
        ]
        mdb.compute_branch_divergence.return_value = {
            "merge_base_revision_id": "rev-base",
            "merge_base_created_at": None,
            "ahead_count": 0,
            "behind_count": 0,
            "ahead_sample": [],
            "behind_sample": [],
        }
        r = client.get(f"/v1/versions/acme/{_PROJECT_ID}/version-branches/{_BRANCH_ID}/divergence")

    assert r.status_code == 200
    assert r.json()["against"]["id"] == _AGAINST_ID
    mdb.list_version_branches_for_project.assert_called_once_with(_PROJECT_ID, _TENANT)


def test_divergence_self_divergence_400():
    with patch("app.version_merge_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": _PROJECT_ID}
        r = client.get(
            f"/v1/versions/acme/{_PROJECT_ID}/version-branches/{_BRANCH_ID}/divergence?against={_BRANCH_ID}"
        )

    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "SELF_DIVERGENCE"
    mdb.compute_branch_divergence.assert_not_called()


def test_divergence_against_branch_project_mismatch_400():
    with patch("app.version_merge_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": _PROJECT_ID}
        mdb.get_version_branch_by_id.side_effect = [
            _branch_row(_BRANCH_ID, _PROJECT_ID, "feature/x", "rev-feature"),
            _branch_row(_AGAINST_ID, _OTHER_PROJECT_ID, "other/main", "rev-other"),
        ]
        r = client.get(
            f"/v1/versions/acme/{_PROJECT_ID}/version-branches/{_BRANCH_ID}/divergence?against={_AGAINST_ID}"
        )

    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BRANCHES_PROJECT_MISMATCH"
    mdb.compute_branch_divergence.assert_not_called()


def test_divergence_returns_304_when_if_none_match_matches_tip_hash():
    with patch("app.version_merge_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": _PROJECT_ID}
        mdb.get_version_branch_by_id.side_effect = [
            _branch_row(_BRANCH_ID, _PROJECT_ID, "feature/x", "rev-feature"),
            _branch_row(_AGAINST_ID, _PROJECT_ID, "main", "rev-main", is_default=True),
        ]
        etag = _strong_etag_for_branch_tips("rev-feature", "rev-main")
        r = client.get(
            f"/v1/versions/acme/{_PROJECT_ID}/version-branches/{_BRANCH_ID}/divergence?against={_AGAINST_ID}",
            headers={"If-None-Match": etag},
        )

    assert r.status_code == 304
    assert r.headers.get("etag") == etag
    assert r.content == b""
    mdb.compute_branch_divergence.assert_not_called()
