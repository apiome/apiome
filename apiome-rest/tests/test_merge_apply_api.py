"""Merge apply rejects unresolved conflicts with structured detail (#2576)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "t1",
    "user_id": "u1",
    "auth_method": "jwt",
}

PID = "00000000-0000-0000-0000-0000000000a1"

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "t", "version": "1"},
    "components": {"schemas": {"Pet": {"type": "object"}}},
}


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _stub_workflow_audit():
    """
    Stub the merge workflow-audit write so these route tests stay DB-free.

    Both the apply and the gate-rejection paths persist a ``version.merge`` audit entry via
    ``db.insert_workflow_audit`` as a side effect. None of the assertions here concern that write, and
    leaving it unmocked drives the request into Postgres — so it fails in any environment without a
    live database (e.g. CI's unit job). Stub it to a no-op; the dedicated coverage in
    ``test_workflow_audit.py`` asserts the audit contents.
    """
    with patch("app.version_merge_routes.db.insert_workflow_audit", side_effect=lambda *a, **k: None):
        yield


def _merge_mocks():
    return (
        patch("app.version_merge_routes.db.get_project_by_id", return_value={"id": PID, "metadata": {}}),
        patch(
            "app.version_merge_routes.db.get_version_branch_by_name",
            side_effect=lambda pid, tid, name: (
                {"tip_version_id": "vs", "id": "1"}
                if name == "src"
                else {"tip_version_id": "vt", "id": "2"}
            ),
        ),
        patch(
            "app.version_merge_routes.db.get_version_by_id",
            side_effect=lambda vid, tid: {
                "id": vid,
                "project_id": PID,
                "published": False,
            },
        ),
        patch("app.version_merge_routes.db.compute_merge_base_revision_id", return_value="vb"),
        patch("app.version_merge_routes.openapi_for_revision", return_value=SPEC),
    )


def test_merge_apply_three_way_conflict_includes_unresolved_count():
    p0, p1, p2, p3, p4 = _merge_mocks()
    conflicts = ["schemas.A", "schemas.B"]
    with p0, p1, p2, p3, p4, patch(
        "app.version_merge_routes.merge_components_schemas_three_way",
        return_value=(None, conflicts),
    ):
        r = client.post(
            f"/v1/versions/acme/{PID}/version-branches/merge",
            json={
                "sourceBranchName": "src",
                "targetBranchName": "tgt",
                "baseRevisionId": "vt",
            },
        )
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "MERGE_UNRESOLVED_CONFLICTS"
    assert d["reason"] == "MERGE_CONFLICT"
    assert d["unresolvedCount"] == 2
    assert d["conflictPaths"] == conflicts
    assert "2 unresolved conflict" in d["message"]


def test_merge_apply_blend_conflict_includes_unresolved_count():
    p0, p1, p2, p3, p4 = _merge_mocks()
    blend_paths = ["schemas.Blend1", "schemas.Blend2", "schemas.Blend3"]
    merged_schemas = {"Pet": {"type": "object"}}
    with p0, p1, p2, p3, p4, patch(
        "app.version_merge_routes.merge_components_schemas_three_way",
        return_value=(merged_schemas, []),
    ), patch(
        "app.version_merge_routes.schema_merge_materializable_paths",
        return_value=(False, blend_paths),
    ):
        r = client.post(
            f"/v1/versions/acme/{PID}/version-branches/merge",
            json={
                "sourceBranchName": "src",
                "targetBranchName": "tgt",
                "baseRevisionId": "vt",
            },
        )
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "MERGE_UNRESOLVED_CONFLICTS"
    assert d["reason"] == "MERGE_BLEND"
    assert d["unresolvedCount"] == 3
    assert d["conflictPaths"] == blend_paths
    assert "3 unresolved conflict" in d["message"]


def test_merge_skip_compat_gate_requires_tenant_admin_when_gate_on():
    """#2590: breaking-glass skip of compat gate requires tenant admin + justification."""
    _m0, m1, m2, m3, m4 = _merge_mocks()
    p0 = patch(
        "app.version_merge_routes.db.get_project_by_id",
        return_value={"id": PID, "metadata": {"compatGateOnMerge": True}},
    )
    with (
        p0,
        m1,
        m2,
        m3,
        m4,
        patch("app.version_merge_routes.db.is_user_tenant_admin", return_value=False),
    ):
        r = client.post(
            f"/v1/versions/acme/{PID}/version-branches/merge",
            json={
                "sourceBranchName": "src",
                "targetBranchName": "tgt",
                "baseRevisionId": "vt",
                "skipCompatGate": True,
            },
        )
    assert r.status_code == 403
    assert "tenant administrator" in r.json()["detail"].lower()


def test_merge_skip_compat_gate_requires_reason_when_gate_on():
    _m0, m1, m2, m3, m4 = _merge_mocks()
    p0 = patch(
        "app.version_merge_routes.db.get_project_by_id",
        return_value={"id": PID, "metadata": {"compatGateOnMerge": True}},
    )
    with (
        p0,
        m1,
        m2,
        m3,
        m4,
        patch("app.version_merge_routes.db.is_user_tenant_admin", return_value=True),
    ):
        r = client.post(
            f"/v1/versions/acme/{PID}/version-branches/merge",
            json={
                "sourceBranchName": "src",
                "targetBranchName": "tgt",
                "baseRevisionId": "vt",
                "skipCompatGate": True,
            },
        )
    assert r.status_code == 422
    assert "compatGateOverrideReason" in r.json()["detail"]
