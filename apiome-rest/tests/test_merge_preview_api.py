"""Merge preview dry-run API (#2572): counts, conflict metadata, optional merged OpenAPI."""

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
        patch("app.version_merge_routes.db.get_project_by_id", return_value={"id": PID}),
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
        "app.version_merge_routes.merge_components_schemas_three_way",
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
        "app.version_merge_routes._MERGE_PREVIEW_MAX_JSON_BYTES",
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


def test_merge_preview_persist_merge_session_calls_db():
    fake_ms = {
        "id": "00000000-0000-0000-0000-0000000000e1",
        "project_id": PID,
        "source_branch_id": "00000000-0000-0000-0000-0000000000b1",
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
    p0, p1, p2, p3, p4 = _preview_mocks()
    with p0, p1, p2, p3, p4, patch(
        "app.version_merge_routes.db.create_merge_session_for_preview",
        return_value=fake_ms,
    ) as pcm:
        r = client.post(
            f"/v1/versions/acme/{PID}/version-branches/merge-preview",
            json={
                "sourceBranchName": "src",
                "targetBranchName": "tgt",
                "persistMergeSession": True,
            },
        )
    assert r.status_code == 200
    d = r.json()
    assert d["mergeSessionId"] == "00000000-0000-0000-0000-0000000000e1"
    assert d["mergeSession"]["status"] == "preview"
    assert d["mergeSession"]["mergeBaseVersionId"] == "vb"
    pcm.assert_called_once()
    call_kw = pcm.call_args[1]
    assert call_kw["project_id"] == PID
    assert call_kw["source_branch_name"] == "src"
    assert "conflict_records" in call_kw
