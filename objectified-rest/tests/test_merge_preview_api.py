"""Merge preview dry-run API (#2572): counts, conflict metadata, optional merged OpenAPI."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.auth import validate_authentication

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
    "components": {
        "schemas": {
            "Pet": {"type": "object", "properties": {"id": {"type": "string"}}},
        }
    },
}


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.clear()


def _preview_mocks():
    return (
        patch("src.app.version_merge_routes.db.get_project_by_id", return_value={"id": PID}),
        patch(
            "src.app.version_merge_routes.db.get_version_branch_by_name",
            side_effect=lambda pid, tid, name: (
                {"tip_version_id": "vs", "id": "1"}
                if name == "src"
                else {"tip_version_id": "vt", "id": "2"}
            ),
        ),
        patch(
            "src.app.version_merge_routes.db.get_version_by_id",
            side_effect=lambda vid, tid: {
                "id": vid,
                "project_id": PID,
                "published": False,
            },
        ),
        patch("src.app.version_merge_routes.db.compute_merge_base_revision_id", return_value="vb"),
        patch("src.app.version_merge_routes._openapi_for_revision", return_value=SPEC),
    )


def test_merge_preview_dry_run_counts_and_merged_openapi():
    p0, p1, p2, p3, p4 = _preview_mocks()
    with p0, p1, p2, p3, p4:
        r = client.post(
            f"/v1/versions/acme/{PID}/version-branches/merge-preview",
            json={"sourceBranchName": "src", "targetBranchName": "tgt"},
        )
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert d["dryRun"] is True
    assert "summaryCounts" in d
    assert all(k in d["summaryCounts"] for k in ("added", "removed", "modified", "unchanged"))
    assert "conflictCounts" in d
    assert d["conflictCounts"]["uniquePaths"] == 0
    assert d["conflictCounts"]["threeWay"] == 0
    assert d["classification"]["canAutoMerge"] is True
    assert d["classification"]["addedSchemaNames"] == []
    assert "mergedOpenApi" in d
    assert d["mergedOpenApi"]["components"]["schemas"]["Pet"]["type"] == "object"
    assert d["conflicts"] == []


def test_merge_preview_conflict_records_and_no_merged_when_blocked():
    p0, p1, p2, p3, p4 = _preview_mocks()
    with p0, p1, p2, p3, p4, patch(
        "src.app.version_merge_routes.merge_components_schemas_three_way",
        return_value=(None, ["schemas.Foo"]),
    ):
        r = client.post(
            f"/v1/versions/acme/{PID}/version-branches/merge-preview",
            json={"sourceBranchName": "src", "targetBranchName": "tgt"},
        )
    assert r.status_code == 200
    d = r.json()
    assert d["classification"]["canAutoMerge"] is False
    assert d["conflictCounts"]["uniquePaths"] >= 1
    assert d["conflicts"]
    assert d["conflicts"][0]["path"] == "schemas.Foo"
    assert "threeWay" in d["conflicts"][0]["kinds"]
    assert "mergedOpenApi" not in d


def test_merge_preview_omit_merged_openapi_flag():
    p0, p1, p2, p3, p4 = _preview_mocks()
    with p0, p1, p2, p3, p4:
        r = client.post(
            f"/v1/versions/acme/{PID}/version-branches/merge-preview",
            json={
                "sourceBranchName": "src",
                "targetBranchName": "tgt",
                "includeMergedOpenApi": False,
            },
        )
    assert r.status_code == 200
    d = r.json()
    assert d["classification"]["canAutoMerge"] is True
    assert "mergedOpenApi" not in d


def test_merge_preview_merged_omitted_when_over_size_cap():
    p0, p1, p2, p3, p4 = _preview_mocks()
    with p0, p1, p2, p3, p4, patch(
        "src.app.version_merge_routes._MERGE_PREVIEW_MAX_JSON_BYTES",
        10,
    ):
        r = client.post(
            f"/v1/versions/acme/{PID}/version-branches/merge-preview",
            json={"sourceBranchName": "src", "targetBranchName": "tgt"},
        )
    assert r.status_code == 200
    d = r.json()
    assert d["classification"]["canAutoMerge"] is True
    assert d.get("mergedOpenApiOmitted") is True
    assert d.get("mergedOpenApiOmittedReason") == "payload_too_large"
    assert "mergedOpenApi" not in d
