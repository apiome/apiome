"""Branch policy PATCH endpoint tests (#2583).

Covers PATCH /v1/versions/{tenant}/{project}/version-branches/{branch_id}:
- 403 when caller is not a tenant admin
- 422 when neither protected nor requireMergePath is provided
- 200 + audit insert when protected is set
- 200 + audit insert when requireMergePath is set
- 200 + audit insert when both fields are set
"""

from unittest.mock import patch, call

import pytest
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.auth import validate_authentication

client = TestClient(app)

_TENANT = "t1"
_USER = "u1"
_PROJECT_ID = "00000000-0000-0000-0000-0000000000a1"
_BRANCH_ID = "00000000-0000-0000-0000-0000000000b1"

_MOCK_AUTH = {
    "tenant_id": _TENANT,
    "user_id": _USER,
    "auth_method": "jwt",
}

_BRANCH_ROW = {
    "id": _BRANCH_ID,
    "project_id": _PROJECT_ID,
    "name": "main",
    "tip_version_id": "00000000-0000-0000-0000-0000000000v1",
    "branched_from_revision_id": None,
    "protected": True,
    "require_merge_path": False,
    "created_by": _USER,
    "created_at": None,
    "updated_at": None,
}

_PATCH_URL = f"/v1/versions/acme/{_PROJECT_ID}/version-branches/{_BRANCH_ID}"


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 403: non-tenant-admin
# ---------------------------------------------------------------------------

def test_patch_branch_policy_non_admin_403():
    with patch("src.app.version_merge_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = False
        r = client.patch(_PATCH_URL, json={"protected": True})
    assert r.status_code == 403
    assert "tenant admin" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 422: neither field provided (Pydantic validation)
# ---------------------------------------------------------------------------

def test_patch_branch_policy_no_fields_422():
    """Pydantic model_validator rejects body with no recognised fields."""
    with patch("src.app.version_merge_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        r = client.patch(_PATCH_URL, json={})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 200 + audit insert: protected only
# ---------------------------------------------------------------------------

def test_patch_branch_policy_protected_only_200():
    with patch("src.app.version_merge_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        mdb.get_project_by_id.return_value = {"id": _PROJECT_ID}
        updated_row = dict(_BRANCH_ROW, protected=True)
        mdb.update_version_branch_protection_policy.return_value = updated_row
        r = client.patch(_PATCH_URL, json={"protected": True})
    assert r.status_code == 200
    data = r.json()
    assert data["branch"]["protected"] is True
    mdb.insert_version_protection_audit.assert_called_once()
    audit_detail = mdb.insert_version_protection_audit.call_args.args[7]
    assert "protected" in audit_detail
    assert "requireMergePath" not in audit_detail


# ---------------------------------------------------------------------------
# 200 + audit insert: requireMergePath only
# ---------------------------------------------------------------------------

def test_patch_branch_policy_require_merge_path_only_200():
    with patch("src.app.version_merge_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        mdb.get_project_by_id.return_value = {"id": _PROJECT_ID}
        updated_row = dict(_BRANCH_ROW, require_merge_path=True)
        mdb.update_version_branch_protection_policy.return_value = updated_row
        r = client.patch(_PATCH_URL, json={"requireMergePath": True})
    assert r.status_code == 200
    data = r.json()
    assert data["branch"]["requireMergePath"] is True
    mdb.insert_version_protection_audit.assert_called_once()
    audit_detail = mdb.insert_version_protection_audit.call_args.args[7]
    assert "requireMergePath" in audit_detail
    assert "protected" not in audit_detail


# ---------------------------------------------------------------------------
# 200 + audit insert: both fields
# ---------------------------------------------------------------------------

def test_patch_branch_policy_both_fields_200():
    with patch("src.app.version_merge_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        mdb.get_project_by_id.return_value = {"id": _PROJECT_ID}
        updated_row = dict(_BRANCH_ROW, protected=True, require_merge_path=True)
        mdb.update_version_branch_protection_policy.return_value = updated_row
        r = client.patch(_PATCH_URL, json={"protected": True, "requireMergePath": True})
    assert r.status_code == 200
    data = r.json()
    assert data["branch"]["protected"] is True
    assert data["branch"]["requireMergePath"] is True
    mdb.insert_version_protection_audit.assert_called_once()
    audit_detail = mdb.insert_version_protection_audit.call_args.args[7]
    assert "protected" in audit_detail
    assert "requireMergePath" in audit_detail


# ---------------------------------------------------------------------------
# 404: branch not found
# ---------------------------------------------------------------------------

def test_patch_branch_policy_branch_not_found_404():
    with patch("src.app.version_merge_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        mdb.get_project_by_id.return_value = {"id": _PROJECT_ID}
        mdb.update_version_branch_protection_policy.return_value = None
        r = client.patch(_PATCH_URL, json={"protected": False})
    assert r.status_code == 404
