from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.repositories_routes import (
    RepositoryFileRecord,
    _build_repository_sync_change_report_for_test_status,
    _complete_repository_scan_for_tests,
    _dispatch_import_jobs_for_scan,
    _get_repository_audit_rows_for_tests,
    _get_repository_change_reports_for_tests,
    _get_repository_import_jobs_for_tests,
    _get_repository_relations_exist_for_tests,
    _get_repository_resolved_versions_for_tests,
    _list_poll_targets_for_tests,
    _reset_repository_state_for_tests,
    _seed_repository_file_content_for_tests,
    _seed_repository_relations_for_tests,
)
from app.repositories.spec_detail import MAX_INLINE_PREVIEW_BYTES

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "tenant_slug": "test-tenant",
    "user_id": "11111111-2222-3333-4444-555555555555",
    "auth_method": "jwt",
}

_TENANT_SLUG = "test-tenant"


def _override_auth():
    return _MOCK_AUTH


def _override_auth_tenant_admin_with_repo_project_autocreate():
    return {
        **_MOCK_AUTH,
        "is_tenant_admin": True,
        "featureFlags": {"repoManifestProjectAutoCreate": True},
    }


def _override_auth_with_repository_scopes():
    return {
        **_MOCK_AUTH,
        "scopes": ["repository.read", "repository.write"],
    }


@pytest.fixture(autouse=True)
def _clear_repository_state():
    _reset_repository_state_for_tests()
    yield
    _reset_repository_state_for_tests()


def test_register_repository_returns_scan_job_and_timeline_entry():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000001",
                "provider": "github",
                "owner": "acme",
                "name": "api-platform",
                "branches": [{"branch": "main", "subpathGlob": "specs/**"}],
                "manifest": "scan:\n  paths:\n    - specs/openapi.yaml\n",
            },
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert response.status_code == 201
    body = response.json()
    assert body["initialScanJobId"]
    assert body["repository"]["fullName"] == "acme/api-platform"
    assert body["repository"]["status"] == "scan_in_progress"
    assert body["repository"]["timeline"][0]["message"] == "Scan in progress..."
    assert body["repository"]["branches"] == [{"branch": "main", "subpathGlob": "specs/**", "pollIntervalSec": None}]
    audit_rows = _get_repository_audit_rows_for_tests(body["repository"]["id"])
    assert [row["eventType"] for row in audit_rows] == ["repository.token_resolved", "repository.registered"]
    assert all(row["actorId"] == _MOCK_AUTH["user_id"] for row in audit_rows)
    assert all(isinstance(row["detail"], dict) for row in audit_rows)


def test_repository_list_and_detail_are_tenant_scoped():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000002",
                "provider": "github",
                "owner": "widgets-co",
                "name": "orders",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        list_response = client.get(f"/v1/repositories/{_TENANT_SLUG}")
        detail_response = client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    list_item = next((item for item in list_response.json()["repositories"] if item["id"] == repository_id), None)
    assert list_item is not None
    assert list_item["lastScanAt"] == create_response.json()["repository"]["timeline"][0]["createdAt"]
    assert detail_response.json()["id"] == repository_id


def test_register_repository_defaults_subpath_and_accepts_wildcard_branch():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000003",
                "provider": "github",
                "owner": "acme",
                "name": "api-platform",
                "branches": [{"branch": "release/*"}],
            },
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert response.status_code == 201
    body = response.json()
    assert body["repository"]["branches"] == [{"branch": "release/*", "subpathGlob": "**/*", "pollIntervalSec": None}]


def test_update_repository_branches_replaces_config_and_updates_timestamp():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000004",
                "provider": "github",
                "owner": "widgets-co",
                "name": "orders",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        original_updated_at = create_response.json()["repository"]["updatedAt"]
        patch_response = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/branches",
            json={
                "branches": [
                    {"branch": "release/*", "subpathGlob": "services/**", "pollIntervalSec": 120},
                    {"branch": "main", "pollIntervalSec": 300},
                ]
            },
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert patch_response.status_code == 200
    body = patch_response.json()
    assert body["branches"] == [
        {"branch": "release/*", "subpathGlob": "services/**", "pollIntervalSec": 120},
        {"branch": "main", "subpathGlob": "**/*", "pollIntervalSec": 300},
    ]
    assert body["updatedAt"] >= original_updated_at


def test_register_repository_normalizes_whitespace_only_subpath_glob():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000005",
                "provider": "github",
                "owner": "acme",
                "name": "whitespace-subpath-test",
                "branches": [{"branch": "main", "subpathGlob": "   "}],
            },
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert response.status_code == 201
    body = response.json()
    assert body["repository"]["branches"] == [{"branch": "main", "subpathGlob": "**/*", "pollIntervalSec": None}]


def test_patch_repository_updates_owner_name_and_manifest():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000011",
                "provider": "github",
                "owner": "acme",
                "name": "service-a",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        patch_response = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}",
            json={
                "owner": "acme-inc",
                "name": "service-core",
                "manifest": "scan:\n  include:\n    - src/**\n",
            },
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert patch_response.status_code == 200
    body = patch_response.json()
    assert body["owner"] == "acme-inc"
    assert body["name"] == "service-core"
    assert body["fullName"] == "acme-inc/service-core"
    assert body["manifest"] == "scan:\n  include:\n    - src/**\n"


def test_archive_unarchive_writes_audit_and_scheduler_skips_archived():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000012",
                "provider": "github",
                "owner": "acme",
                "name": "service-b",
                "branches": [{"branch": "main"}, {"branch": "release/*"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        archive_response = client.post(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/archive")
        poll_targets_after_archive = _list_poll_targets_for_tests(_MOCK_AUTH["tenant_id"])
        unarchive_response = client.post(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/unarchive")
        poll_targets_after_unarchive = _list_poll_targets_for_tests(_MOCK_AUTH["tenant_id"])
        audit_rows = _get_repository_audit_rows_for_tests(repository_id)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"
    assert archive_response.json()["archivedAt"] is not None
    assert poll_targets_after_archive == []

    assert unarchive_response.status_code == 200
    assert unarchive_response.json()["status"] == "healthy"
    assert unarchive_response.json()["archivedAt"] is None
    assert sorted(target["branch"] for target in poll_targets_after_unarchive) == ["main", "release/*"]

    assert [row["eventType"] for row in audit_rows] == [
        "repository.token_resolved",
        "repository.registered",
        "repository.archived",
        "repository.unarchived",
    ]


def test_pause_and_auto_pause_write_audit_and_scheduler_skips_paused():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000018",
                "provider": "github",
                "owner": "acme",
                "name": "service-paused",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        pause_response = client.post(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/pause")
        poll_targets_after_pause = _list_poll_targets_for_tests(_MOCK_AUTH["tenant_id"])
        auto_pause_response = client.post(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/auto-pause")
        poll_targets_after_auto_pause = _list_poll_targets_for_tests(_MOCK_AUTH["tenant_id"])
        audit_rows = _get_repository_audit_rows_for_tests(repository_id)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"
    assert poll_targets_after_pause == []
    assert auto_pause_response.status_code == 200
    assert auto_pause_response.json()["status"] == "paused"
    assert poll_targets_after_auto_pause == []
    assert [row["eventType"] for row in audit_rows] == [
        "repository.token_resolved",
        "repository.registered",
        "repository.paused",
        "repository.auto_paused",
    ]


def test_delete_repository_requires_confirmation_and_cascades():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000013",
                "provider": "github",
                "owner": "acme",
                "name": "service-c",
                "branches": [{"branch": "main"}],
            },
        )
        repository = create_response.json()["repository"]
        repository_id = repository["id"]
        _seed_repository_relations_for_tests(repository_id)
        wrong_confirmation = client.request(
            method="DELETE",
            url=f"/v1/repositories/{_TENANT_SLUG}/{repository_id}",
            json={"confirmFullName": "acme/wrong-repo"},
        )
        delete_response = client.request(
            method="DELETE",
            url=f"/v1/repositories/{_TENANT_SLUG}/{repository_id}",
            json={"confirmFullName": repository["fullName"]},
        )
        relations_exist = _get_repository_relations_exist_for_tests(repository_id)
        detail_response = client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}")
        audit_rows = _get_repository_audit_rows_for_tests(repository_id)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert wrong_confirmation.status_code == 400
    assert delete_response.status_code == 204
    assert all(not exists for exists in relations_exist.values())
    assert detail_response.status_code == 404
    assert [row["eventType"] for row in audit_rows] == [
        "repository.token_resolved",
        "repository.registered",
        "repository.removed",
    ]


def test_list_scans_returns_initial_register_scan_with_default_page_limit():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000021",
                "provider": "github",
                "owner": "acme",
                "name": "scan-api",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scans_response = client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert scans_response.status_code == 200
    body = scans_response.json()
    assert body["limit"] == 50
    assert len(body["items"]) == 1
    assert body["items"][0]["trigger"] == "register"
    assert body["items"][0]["status"] == "pending"


def test_post_scans_support_force_and_skipped_unchanged_with_single_audit_entry():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000022",
                "provider": "github",
                "owner": "acme",
                "name": "scan-retry",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        skipped_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": False},
        )
        skipped_repository_response = client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}")
        forced_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": True},
        )
        forced_repository_response = client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert skipped_response.status_code == 200
    assert skipped_repository_response.status_code == 200
    skipped_scan = skipped_response.json()
    assert skipped_scan["status"] == "skipped_unchanged"
    assert skipped_scan["filesSeen"] == 0
    assert len(skipped_scan["eventLog"]) == 1
    assert skipped_scan["eventLog"][0]["type"] == "repository.scan.skipped_unchanged"
    assert skipped_repository_response.json()["status"] == "healthy"
    assert skipped_repository_response.json()["timeline"][0]["status"] == "completed"

    assert forced_response.status_code == 200
    assert forced_repository_response.status_code == 200
    forced_scan = forced_response.json()
    assert forced_scan["status"] == "pending"
    assert forced_scan["eventLog"][0]["force"] is True
    assert forced_repository_response.json()["status"] == "scan_in_progress"
    assert forced_repository_response.json()["timeline"][0]["status"] == "in_progress"


def test_list_scans_and_files_support_cursor_pagination_and_filters():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000023",
                "provider": "github",
                "owner": "acme",
                "name": "scan-pagination",
                "branches": [{"branch": "main"}],
                "manifest": "version: 2\nspecs:\n  - path: service.yaml\n",
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        for _ in range(3):
            post_response = client.post(
                f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
                json={"branch": "main", "force": True},
            )
            assert post_response.status_code == 200

        first_page = client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans", params={"limit": 2})
        next_cursor = first_page.json()["nextCursor"]
        second_page = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            params={"limit": 2, "cursor": next_cursor},
        )
        skipped_only = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            params={"status": "skipped_unchanged"},
        )
        initial_scan_id = create_response.json()["initialScanJobId"]
        files_response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{initial_scan_id}/files",
            params={"status": "manifest_error"},
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 2
    assert next_cursor is not None
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) >= 1
    assert skipped_only.status_code == 200
    assert skipped_only.json()["items"] == []

    assert files_response.status_code == 200
    file_rows = files_response.json()["items"]
    assert len(file_rows) == 1
    assert file_rows[0]["status"] == "manifest_error"


def test_complete_scan_classifies_files_and_writes_diff_summary():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000024",
                "provider": "github",
                "owner": "acme",
                "name": "scan-diff",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        first_scan_id = create_response.json()["initialScanJobId"]
        first_completed = _complete_repository_scan_for_tests(
            repository_id,
            first_scan_id,
            commit_sha="commit-one",
            files=[
                {"path": "apis/openapi.yaml", "blobSha": "111", "tracked": True},
                {"path": "events/asyncapi.yaml", "blobSha": "222", "tracked": True},
            ],
        )

        next_scan_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": True},
        )
        second_scan_id = next_scan_response.json()["id"]
        second_completed = _complete_repository_scan_for_tests(
            repository_id,
            second_scan_id,
            commit_sha="commit-two",
            files=[
                {"path": "apis/openapi.yaml", "blobSha": "333", "tracked": True},
                {"path": "docs/readme.md", "blobSha": "444", "tracked": False},
            ],
        )
        files_response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{second_scan_id}/files",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert next_scan_response.status_code == 200

    assert first_completed.status == "complete"
    assert first_completed.diffSummary == {
        "added": 2,
        "modified": 0,
        "removed": 0,
        "unchanged": 0,
        "skipped_unchanged_by_checksum": 0,
    }

    assert second_completed.status == "complete"
    assert second_completed.diffSummary == {
        "added": 1,
        "modified": 1,
        "removed": 1,
        "unchanged": 0,
        "skipped_unchanged_by_checksum": 0,
    }

    assert files_response.status_code == 200
    by_path = {row["path"]: row for row in files_response.json()["items"]}
    assert by_path["apis/openapi.yaml"]["status"] == "modified"
    assert by_path["docs/readme.md"]["status"] == "new"
    assert by_path["events/asyncapi.yaml"]["status"] == "removed"
    assert by_path["events/asyncapi.yaml"]["blobSha"] == "222"


def test_complete_scan_records_hashed_events_and_reuses_checksum_for_unchanged_blob_sha() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000024",
                "provider": "github",
                "owner": "acme",
                "name": "scan-checksum-reuse",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        first_scan_id = create_response.json()["initialScanJobId"]
        first_completed = _complete_repository_scan_for_tests(
            repository_id,
            first_scan_id,
            commit_sha="checksum-seed",
            files=[
                {
                    "path": "apis/openapi.yaml",
                    "blobSha": "abc123",
                    "contentAlgo": "sha256",
                    "contentChecksum": "031edd7d41651593c5fe5c006fa5752b37fddff7bc4e843aa6af0c950f4b9406",
                    "tracked": True,
                },
            ],
        )

        next_scan_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": True},
        )
        second_scan_id = next_scan_response.json()["id"]
        second_completed = _complete_repository_scan_for_tests(
            repository_id,
            second_scan_id,
            commit_sha="checksum-rescan",
            files=[
                {
                    "path": "apis/openapi.yaml",
                    "blobSha": "abc123",
                    "tracked": True,
                },
            ],
        )
        files_response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{second_scan_id}/files",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert next_scan_response.status_code == 200
    assert first_completed.status == "complete"
    assert second_completed.status == "complete"
    assert files_response.status_code == 200

    first_hashed_events = [event for event in first_completed.eventLog if event.get("type") == "repository.scan.hashed"]
    second_hashed_events = [event for event in second_completed.eventLog if event.get("type") == "repository.scan.hashed"]
    assert len(first_hashed_events) == 1
    assert len(second_hashed_events) == 1
    assert first_hashed_events[0]["content_algo"] == "sha256"
    assert first_hashed_events[0]["content_checksum_short"] == "031edd7d4165"
    assert second_hashed_events[0]["content_checksum_short"] == "031edd7d4165"

    only_file = files_response.json()["items"][0]
    assert only_file["status"] == "unchanged"
    assert only_file["contentAlgo"] == "sha256"
    assert only_file["contentChecksum"] == "031edd7d41651593c5fe5c006fa5752b37fddff7bc4e843aa6af0c950f4b9406"


def test_complete_scan_dispatches_import_jobs_and_records_parse_errors():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000025",
                "provider": "github",
                "owner": "acme",
                "name": "scan-import-binding",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        first_scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            first_scan_id,
            commit_sha="commit-first",
            files=[
                {
                    "path": "apis/stable.yaml",
                    "blobSha": "111",
                    "tracked": True,
                    "promote": "auto",
                    "importEnabled": True,
                    "autoImportEnabled": True,
                },
                {
                    "path": "apis/error.yaml",
                    "blobSha": "222",
                    "tracked": True,
                    "promote": "auto",
                    "importEnabled": True,
                    "autoImportEnabled": True,
                },
                {
                    "path": "apis/removed.yaml",
                    "blobSha": "333",
                    "tracked": True,
                    "promote": "manual",
                    "importEnabled": True,
                    "autoImportEnabled": True,
                },
            ],
        )
        baseline_job_count = len(_get_repository_import_jobs_for_tests(repository_id))
        baseline_audit_count = len(_get_repository_audit_rows_for_tests(repository_id))

        next_scan_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": True},
        )
        second_scan_id = next_scan_response.json()["id"]
        _complete_repository_scan_for_tests(
            repository_id,
            second_scan_id,
            commit_sha="commit-second",
            files=[
                {
                    "path": "apis/stable.yaml",
                    "blobSha": "111",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": True,
                },
                {
                    "path": "apis/error.yaml",
                    "blobSha": "999",
                    "tracked": True,
                    "promote": "auto",
                    "importEnabled": True,
                    "autoImportEnabled": True,
                    "settingsJson": {"forceImportFailure": "parser exploded"},
                },
            ],
        )
        second_scan_files = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{second_scan_id}/files",
        )
        import_jobs = _get_repository_import_jobs_for_tests(repository_id)
        change_reports = _get_repository_change_reports_for_tests(repository_id)
        audit_rows = _get_repository_audit_rows_for_tests(repository_id)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert next_scan_response.status_code == 200
    assert second_scan_files.status_code == 200

    # unchanged files do not dispatch new import jobs
    assert len(import_jobs) == baseline_job_count + 2
    second_scan_jobs = [job for job in import_jobs if job.scanId == second_scan_id]
    assert len(second_scan_jobs) == 2
    by_path = {job.diffSnapshot["path"]: job for job in second_scan_jobs}
    assert "apis/stable.yaml" not in by_path

    removed_job = by_path["apis/removed.yaml"]
    assert removed_job.operation == "removal"
    assert removed_job.state == "pending_review"
    assert removed_job.settingsJson["requiresExplicitApproval"] is True
    assert removed_job.sourceType == "git"
    assert removed_job.sourceUri == f"repo://{repository_id}/apis/removed.yaml@main/commit-second"
    assert removed_job.conflictRecords == []
    assert removed_job.eventLog[0]["type"] == "repository.sync.job_dispatched"

    failed_job = by_path["apis/error.yaml"]
    assert failed_job.operation == "import"
    assert failed_job.state == "failed"
    assert failed_job.errorDetail == "parser exploded"
    assert failed_job.diffSnapshot["status"] == "modified"
    assert failed_job.changeReportId is not None
    assert len(failed_job.conflictRecords) == 1
    assert failed_job.conflictRecords[0]["kinds"] == ["duplicate_schema"]
    assert failed_job.eventLog[0]["type"] == "repository.sync.job_dispatched"
    assert failed_job.eventLog[1]["type"] == "repository.sync.conflicts_detected"
    assert failed_job.eventLog[1]["taxonomy"] == "import_pipeline"
    assert failed_job.eventLog[1]["resolver"] == "import_conflict_resolver"
    assert failed_job.eventLog[1]["conflicts"][0]["kinds"] == ["duplicate_schema"]

    reports_by_job_id = {report.importJobId: report for report in change_reports}
    assert removed_job.id in reports_by_job_id
    assert failed_job.id in reports_by_job_id
    removed_report = reports_by_job_id[removed_job.id]
    failed_report = reports_by_job_id[failed_job.id]
    assert removed_report.sourceKind == "repository_sync"
    assert removed_report.changeModelJson["schemas"]["removed"] != []
    assert failed_report.changeModelJson["schemas"]["modified"] != []

    files_by_path = {row["path"]: row for row in second_scan_files.json()["items"]}
    assert files_by_path["apis/stable.yaml"]["status"] == "unchanged"
    assert files_by_path["apis/stable.yaml"]["lastImportJobId"] is None
    assert files_by_path["apis/removed.yaml"]["status"] == "removed"
    assert files_by_path["apis/error.yaml"]["status"] == "parse_error"
    assert files_by_path["apis/error.yaml"]["discriminator"] == "parser exploded"

    new_audit_rows = audit_rows[baseline_audit_count:]
    assert [row["eventType"] for row in new_audit_rows] == [
        "repository.polled",
        "repository.sync_pending_review",
        "repository.sync_failed",
        "repository.scanned",
    ]


def test_checksum_matched_modified_file_skips_dispatch_and_updates_diff_summary() -> None:
    file_row = RepositoryFileRecord(
        id="11111111-1111-1111-1111-111111111111",
        repositoryId="22222222-2222-2222-2222-222222222222",
        scanId="33333333-3333-3333-3333-333333333333",
        path="apis/orders.yaml",
        blobSha="new-blob-sha",
        contentAlgo="sha256",
        contentChecksum="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tracked=True,
        importEnabled=True,
        autoImportEnabled=True,
        projectSlug="payments",
        versionStrategy="commit-sha",
        status="modified",
        createdAt="2026-04-26T00:00:00Z",
    )
    diff_summary = {
        "added": 0,
        "modified": 1,
        "removed": 0,
        "unchanged": 0,
        "skipped_unchanged_by_checksum": 0,
    }

    with patch("app.repositories_routes.db") as mdb:
        mdb.get_project_by_slug.return_value = {"id": "44444444-4444-4444-4444-444444444444"}
        mdb.get_latest_repository_source_checksum_for_project.return_value = (
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        audit_rows = _dispatch_import_jobs_for_scan(
            tenant_id=_MOCK_AUTH["tenant_id"],
            repository_id=file_row.repositoryId,
            scan_id=file_row.scanId,
            branch="main",
            commit_sha="commit-second",
            scan_files=[file_row],
            actor_id=_MOCK_AUTH["user_id"],
            force=False,
            diff_summary=diff_summary,
        )

    assert _get_repository_import_jobs_for_tests(file_row.repositoryId) == []
    assert file_row.status == "unchanged_checksum"
    assert file_row.lastImportJobId is None
    assert diff_summary["modified"] == 0
    assert diff_summary["skipped_unchanged_by_checksum"] == 1
    assert len(audit_rows) == 1
    assert audit_rows[0]["eventType"] == "repository.scan.skipped_checksum"
    assert audit_rows[0]["detail"]["path"] == "apis/orders.yaml"
    assert audit_rows[0]["detail"]["contentChecksumShort"] == "aaaaaaaaaaaa"


def test_force_scan_ignores_checksum_skip_and_dispatches_modified_file() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000044",
                "provider": "github",
                "owner": "acme",
                "name": "checksum-force-override",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        first_scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            first_scan_id,
            commit_sha="commit-first",
            files=[
                {
                    "path": "apis/orders.yaml",
                    "blobSha": "111",
                    "contentAlgo": "sha256",
                    "contentChecksum": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": True,
                    "projectSlug": "payments",
                }
            ],
        )

        next_scan_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": True},
        )
        second_scan_id = next_scan_response.json()["id"]
        with patch("app.repositories_routes.db") as mdb:
            mdb.get_project_by_slug.return_value = {"id": "55555555-5555-5555-5555-555555555555"}
            mdb.get_latest_repository_source_checksum_for_project.return_value = (
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            )
            second_completed = _complete_repository_scan_for_tests(
                repository_id,
                second_scan_id,
                commit_sha="commit-second",
                files=[
                    {
                        "path": "apis/orders.yaml",
                        "blobSha": "999",
                        "contentAlgo": "sha256",
                        "contentChecksum": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                        "tracked": True,
                        "importEnabled": True,
                        "autoImportEnabled": True,
                        "projectSlug": "payments",
                    }
                ],
            )
        second_scan_files = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{second_scan_id}/files",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert next_scan_response.status_code == 200
    assert second_scan_files.status_code == 200

    second_scan_jobs = [job for job in _get_repository_import_jobs_for_tests(repository_id) if job.scanId == second_scan_id]
    assert len(second_scan_jobs) == 1
    assert second_scan_jobs[0].diffSnapshot["path"] == "apis/orders.yaml"

    only_file = second_scan_files.json()["items"][0]
    assert only_file["status"] == "modified"
    assert second_completed.diffSummary["modified"] == 1
    assert second_completed.diffSummary["skipped_unchanged_by_checksum"] == 0


def test_sync_history_routes_persist_conflict_resolution_on_import_job_event_log() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000030",
                "provider": "github",
                "owner": "acme",
                "name": "sync-history-conflicts",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        first_scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            first_scan_id,
            commit_sha="commit-primer",
            files=[
                {
                    "path": "apis/orders.yaml",
                    "blobSha": "111",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": True,
                }
            ],
        )
        second_scan_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": True},
        )
        second_scan_id = second_scan_response.json()["id"]
        _complete_repository_scan_for_tests(
            repository_id,
            second_scan_id,
            commit_sha="commit-with-conflict",
            files=[
                {
                    "path": "apis/orders.yaml",
                    "blobSha": "999",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": True,
                    "settingsJson": {
                        "simulatedConflicts": [
                            {
                                "schemaName": "Order",
                                "kinds": ["duplicate_schema", "property_conflict"],
                                "message": "Schema differs from draft.",
                            }
                        ]
                    },
                }
            ],
        )
        sync_history_response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/sync-history",
            params={"hasConflicts": "true"},
        )
        conflict_job_id = sync_history_response.json()["items"][0]["id"]
        resolve_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/sync-history/{conflict_job_id}/resolve-conflict",
            json={
                "schemaName": "Order",
                "choice": "merge",
                "conflictKinds": ["duplicate_schema", "property_conflict"],
                "note": "Use additive merge strategy from import resolver.",
            },
        )
        refreshed_sync_history_response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/sync-history",
            params={"hasConflicts": "true"},
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert second_scan_response.status_code == 200
    assert sync_history_response.status_code == 200
    sync_history_body = sync_history_response.json()
    assert sync_history_body["items"]
    assert sync_history_body["items"][0]["conflictRecords"][0]["schemaName"] == "Order"
    assert sync_history_body["items"][0]["conflictRecords"][0]["kinds"] == ["duplicate_schema", "property_conflict"]

    assert resolve_response.status_code == 200
    resolve_body = resolve_response.json()
    assert resolve_body["eventLog"][-1]["type"] == "repository.sync.conflict_resolved"
    assert resolve_body["eventLog"][-1]["schemaName"] == "Order"
    assert resolve_body["eventLog"][-1]["choice"] == "merge"
    assert resolve_body["eventLog"][-1]["conflictKinds"] == ["duplicate_schema", "property_conflict"]
    assert resolve_body["eventLog"][-1]["note"] == "Use additive merge strategy from import resolver."

    assert refreshed_sync_history_response.status_code == 200
    refreshed_job = refreshed_sync_history_response.json()["items"][0]
    assert refreshed_job["id"] == conflict_job_id
    assert refreshed_job["eventLog"][-1]["type"] == "repository.sync.conflict_resolved"


def test_complete_scan_applies_manifest_first_mapping_and_auto_fallback_rules():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000026",
                "provider": "github",
                "owner": "acme",
                "name": "mapping-rules",
                "branches": [{"branch": "main"}],
                "manifest": (
                    "version: 1\n"
                    "specs:\n"
                    "  - path: services/orders/openapi.yaml\n"
                    "    project: checkout-core\n"
                    "    versionStrategy: branch\n"
                ),
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="commit-mapping-rules",
            files=[
                {
                    "path": "services/orders/openapi.yaml",
                    "blobSha": "111",
                    "tracked": False,
                    "projectSlug": "should-not-win",
                    "versionStrategy": "commit-sha",
                },
                {
                    "path": "billing/openapi.yaml",
                    "blobSha": "222",
                },
                {
                    "path": "root-openapi.yaml",
                    "blobSha": "333",
                },
            ],
        )
        files_response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{scan_id}/files",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert files_response.status_code == 200
    by_path = {row["path"]: row for row in files_response.json()["items"]}

    assert by_path["services/orders/openapi.yaml"]["tracked"] is True
    assert by_path["services/orders/openapi.yaml"]["projectSlug"] == "checkout-core"
    assert by_path["services/orders/openapi.yaml"]["versionStrategy"] == "branch"

    assert by_path["billing/openapi.yaml"]["tracked"] is True
    assert by_path["billing/openapi.yaml"]["projectSlug"] == "billing"
    assert by_path["billing/openapi.yaml"]["versionStrategy"] == "commit-sha"

    assert by_path["root-openapi.yaml"]["tracked"] is False
    assert by_path["root-openapi.yaml"]["projectSlug"] is None
    assert by_path["root-openapi.yaml"]["versionStrategy"] == "commit-sha"
    assert by_path["root-openapi.yaml"]["settingsJson"] == {
        "mappingRequired": True,
        "mappingReason": "project_slug_not_resolved",
    }
    assert by_path["services/orders/openapi.yaml"]["importEnabled"] is True
    assert by_path["services/orders/openapi.yaml"]["autoImportEnabled"] is False
    assert by_path["billing/openapi.yaml"]["importEnabled"] is False
    assert by_path["billing/openapi.yaml"]["autoImportEnabled"] is False
    assert by_path["root-openapi.yaml"]["importEnabled"] is False
    assert by_path["root-openapi.yaml"]["autoImportEnabled"] is False


def test_commit_sha_jobs_bind_to_idempotent_auto_created_versions() -> None:
    expected_date_prefix = datetime.now(timezone.utc).strftime('%Y%m%d')
    app.dependency_overrides[validate_authentication] = _override_auth_tenant_admin_with_repo_project_autocreate
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000027",
                "provider": "github",
                "owner": "acme",
                "name": "version-binding",
                "branches": [{"branch": "main"}],
                "manifest": (
                    "version: 1\n"
                    "specs:\n"
                    "  - path: services/orders/openapi.yaml\n"
                    "    project: checkout-core\n"
                    "    versionStrategy: commit-sha\n"
                ),
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        first_scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            first_scan_id,
            commit_sha="abc123def4567890",
            files=[
                {
                    "path": "services/orders/openapi.yaml",
                    "blobSha": "111",
                    "autoImportEnabled": True,
                }
            ],
        )
        first_jobs = [job for job in _get_repository_import_jobs_for_tests(repository_id) if job.scanId == first_scan_id]
        first_versions = _get_repository_resolved_versions_for_tests(_MOCK_AUTH["tenant_id"])

        second_scan_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": True},
        )
        second_scan_id = second_scan_response.json()["id"]
        _complete_repository_scan_for_tests(
            repository_id,
            second_scan_id,
            commit_sha="abc123def4567890",
            files=[
                {
                    "path": "services/orders/openapi.yaml",
                    "blobSha": "222",
                    "autoImportEnabled": True,
                }
            ],
        )
        second_jobs = [job for job in _get_repository_import_jobs_for_tests(repository_id) if job.scanId == second_scan_id]
        second_versions = _get_repository_resolved_versions_for_tests(_MOCK_AUTH["tenant_id"])
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert second_scan_response.status_code == 200
    assert len(first_jobs) == 1
    assert len(second_jobs) == 1
    assert first_versions == []
    assert second_versions == []

    first_job = first_jobs[0]
    second_job = second_jobs[0]
    assert first_job.targetProjectSlug == "checkout-core"
    assert first_job.targetVersionId == f"{expected_date_prefix}-abc123def456"
    assert second_job.targetVersionId == f"{expected_date_prefix}-abc123def456"


def test_manifest_project_does_not_autocreate_without_flag_or_tenant_admin() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000028",
                "provider": "github",
                "owner": "acme",
                "name": "version-binding-guard",
                "branches": [{"branch": "main"}],
                "manifest": (
                    "version: 1\n"
                    "specs:\n"
                    "  - path: services/orders/openapi.yaml\n"
                    "    project: checkout-core\n"
                    "    versionStrategy: commit-sha\n"
                ),
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="abc123def4567890",
            files=[{"path": "services/orders/openapi.yaml", "blobSha": "111", "autoImportEnabled": True}],
        )
        jobs = [job for job in _get_repository_import_jobs_for_tests(repository_id) if job.scanId == scan_id]
        versions = _get_repository_resolved_versions_for_tests(_MOCK_AUTH["tenant_id"])
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert len(jobs) == 1
    assert jobs[0].targetProjectSlug is None
    assert jobs[0].targetVersionId is None
    assert versions == []


def test_noop_dry_run_change_report_is_zero_diff_for_unchanged_file() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000029",
                "provider": "github",
                "owner": "acme",
                "name": "zero-diff",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        first_scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            first_scan_id,
            commit_sha="unchanged-seed",
            files=[
                {
                    "path": "apis/stable.yaml",
                    "blobSha": "same",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": True,
                },
            ],
        )

        second_scan_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": True},
        )
        second_scan_id = second_scan_response.json()["id"]
        _complete_repository_scan_for_tests(
            repository_id,
            second_scan_id,
            commit_sha="unchanged-seed",
            files=[
                {
                    "path": "apis/stable.yaml",
                    "blobSha": "same",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": True,
                },
            ],
        )
        second_scan_jobs = [job for job in _get_repository_import_jobs_for_tests(repository_id) if job.scanId == second_scan_id]
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert second_scan_response.status_code == 200
    assert second_scan_jobs == []

    unchanged_report = _build_repository_sync_change_report_for_test_status("unchanged")
    assert unchanged_report["schemas"]["added"] == []
    assert unchanged_report["schemas"]["removed"] == []
    assert unchanged_report["schemas"]["modified"] == []


def test_default_promotion_mode_is_manual_for_new_repositories() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000041",
                "provider": "github",
                "owner": "acme",
                "name": "manual-by-default",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="default-manual-sha",
            files=[
                {
                    "path": "apis/default.yaml",
                    "blobSha": "111",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": True,
                }
            ],
        )
        files_response = client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{scan_id}/files")
        jobs = [job for job in _get_repository_import_jobs_for_tests(repository_id) if job.scanId == scan_id]
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert files_response.status_code == 200
    assert len(jobs) == 1
    assert jobs[0].state == "pending_review"
    assert files_response.json()["items"][0]["promote"] == "manual"


def test_auto_promotion_records_change_report_and_sync_committed_audit() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000042",
                "provider": "github",
                "owner": "acme",
                "name": "auto-commit-audit",
                "branches": [{"branch": "main"}],
                "manifest": (
                    "version: 1\n"
                    "specs:\n"
                    "  - path: apis/auto.yaml\n"
                    "    project: payments\n"
                    "    promote: auto\n"
                    "    onBreakingChange: warn\n"
                ),
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="auto-commit-sha",
            files=[{"path": "apis/auto.yaml", "blobSha": "111", "autoImportEnabled": True}],
        )
        jobs = [job for job in _get_repository_import_jobs_for_tests(repository_id) if job.scanId == scan_id]
        change_reports = _get_repository_change_reports_for_tests(repository_id)
        audit_rows = _get_repository_audit_rows_for_tests(repository_id)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert len(jobs) == 1
    assert jobs[0].state == "committed"
    assert jobs[0].changeReportId is not None
    assert any(report.importJobId == jobs[0].id for report in change_reports)
    assert [row["eventType"] for row in audit_rows] == [
        "repository.token_resolved",
        "repository.registered",
        "repository.sync_committed",
        "repository.scanned",
    ]


def test_on_breaking_change_block_forces_manual_even_when_promote_is_auto() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000043",
                "provider": "github",
                "owner": "acme",
                "name": "blocking-change-gate",
                "branches": [{"branch": "main"}],
                "manifest": (
                    "version: 1\n"
                    "specs:\n"
                    "  - path: apis/blocked.yaml\n"
                    "    project: payments\n"
                    "    promote: auto\n"
                    "    onBreakingChange: block\n"
                ),
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="blocked-commit-sha",
            files=[{"path": "apis/blocked.yaml", "blobSha": "111", "autoImportEnabled": True}],
        )
        jobs = [job for job in _get_repository_import_jobs_for_tests(repository_id) if job.scanId == scan_id]
        audit_rows = _get_repository_audit_rows_for_tests(repository_id)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert len(jobs) == 1
    assert jobs[0].state == "pending_review"
    assert jobs[0].settingsJson["onBreakingChange"] == "block"
    assert jobs[0].settingsJson["requiresExplicitApproval"] is True
    assert [row["eventType"] for row in audit_rows] == [
        "repository.token_resolved",
        "repository.registered",
        "repository.sync_pending_review",
        "repository.scanned",
    ]


def test_no_manifest_import_enabled_false_does_not_dispatch() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000050",
                "provider": "github",
                "owner": "acme",
                "name": "import-off",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="commit-no-dispatch",
            files=[
                {"path": "apis/quiet.yaml", "blobSha": "a", "tracked": True, "importEnabled": False},
            ],
        )
        jobs = [job for job in _get_repository_import_jobs_for_tests(repository_id) if job.scanId == scan_id]
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert jobs == []


def test_manifest_import_enabled_false_does_not_dispatch() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000051",
                "provider": "github",
                "owner": "acme",
                "name": "manifest-import-off",
                "branches": [{"branch": "main"}],
                "manifest": (
                    "version: 1\n"
                    "specs:\n"
                    "  - path: apis/held.yaml\n"
                    "    importEnabled: false\n"
                    "    project: svc\n"
                    "    versionStrategy: commit-sha\n"
                ),
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="c1",
            files=[{"path": "apis/held.yaml", "blobSha": "x"}],
        )
        jobs = [job for job in _get_repository_import_jobs_for_tests(repository_id) if job.scanId == scan_id]
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert jobs == []


def test_patch_file_import_enabled_writes_audit() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        _reset_repository_state_for_tests()
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000052",
                "provider": "github",
                "owner": "acme",
                "name": "import-toggle",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="c1",
            files=[
                {
                    "path": "apis/patchable.yaml",
                    "blobSha": "1",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": True,
                },
            ],
        )
        file_id = (
            client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{scan_id}/files").json()["items"][0]["id"]
        )
        _audit_baseline = len(_get_repository_audit_rows_for_tests(repository_id))
        patch1 = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/files/{file_id}/import-enabled",
            json={"importEnabled": False, "source": "ui"},
        )
        _audit_after_first = _get_repository_audit_rows_for_tests(repository_id)
        no_op = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/files/{file_id}/import-enabled",
            json={"importEnabled": False, "source": "ui"},
        )
        _audit_after_noop = _get_repository_audit_rows_for_tests(repository_id)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
        _reset_repository_state_for_tests()

    assert create_response.status_code == 201
    assert patch1.status_code == 200
    assert patch1.json()["importEnabled"] is False
    assert patch1.json()["autoImportEnabled"] is False
    assert no_op.status_code == 200
    new_audits = _audit_after_first[_audit_baseline:]
    assert any(row["eventType"] == "repository.spec.selection_changed" for row in new_audits)
    last_sel = [row for row in new_audits if row["eventType"] == "repository.spec.selection_changed"][-1]
    assert last_sel["detail"]["path"] == "apis/patchable.yaml"
    assert last_sel["detail"]["before"] is True
    assert last_sel["detail"]["after"] is False
    assert last_sel["detail"]["field"] == "import_enabled"
    assert last_sel["detail"]["source"] == "ui"
    assert len(_audit_after_noop) == len(_audit_after_first)


def test_patch_file_auto_import_enabled_writes_audit_and_requires_import_enabled() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        _reset_repository_state_for_tests()
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000053",
                "provider": "github",
                "owner": "acme",
                "name": "auto-import-toggle",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="c1",
            files=[
                {
                    "path": "apis/auto-toggle.yaml",
                    "blobSha": "1",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": False,
                },
            ],
        )
        file_id = (
            client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{scan_id}/files").json()["items"][0]["id"]
        )
        audit_baseline = len(_get_repository_audit_rows_for_tests(repository_id))

        patch_auto = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/files/{file_id}/auto-import-enabled",
            json={"autoImportEnabled": True, "source": "ui"},
        )
        patch_import_off = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/files/{file_id}/import-enabled",
            json={"importEnabled": False, "source": "ui"},
        )
        invalid_patch = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/files/{file_id}/auto-import-enabled",
            json={"autoImportEnabled": True, "source": "ui"},
        )
        audit_rows = _get_repository_audit_rows_for_tests(repository_id)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
        _reset_repository_state_for_tests()

    assert create_response.status_code == 201
    assert patch_auto.status_code == 200
    assert patch_auto.json()["importEnabled"] is True
    assert patch_auto.json()["autoImportEnabled"] is True
    assert patch_import_off.status_code == 200
    assert patch_import_off.json()["importEnabled"] is False
    assert patch_import_off.json()["autoImportEnabled"] is False
    assert invalid_patch.status_code == 400

    selection_audits = [
        row for row in audit_rows[audit_baseline:] if row["eventType"] == "repository.spec.selection_changed"
    ]
    assert len(selection_audits) == 2
    assert selection_audits[0]["detail"]["field"] == "auto_import_enabled"
    assert selection_audits[0]["detail"]["before"] is False
    assert selection_audits[0]["detail"]["after"] is True
    assert selection_audits[1]["detail"]["field"] == "import_enabled"
    assert selection_audits[1]["detail"]["before"] is True
    assert selection_audits[1]["detail"]["after"] is False


def test_specs_routes_require_repository_scopes() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000060",
                "provider": "github",
                "owner": "acme",
                "name": "scope-required",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="scope-seed",
            files=[{"path": "apis/spec.yaml", "blobSha": "1", "tracked": True}],
        )
        file_id = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{scan_id}/files"
        ).json()["items"][0]["id"]

        list_response = client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs")
        patch_response = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}",
            json={"importEnabled": True},
        )
        bulk_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs:bulkUpdate",
            json={"file_ids": [file_id], "importEnabled": True},
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert list_response.status_code == 403
    assert list_response.json()["detail"]["code"] == "REPOSITORY_SCOPE_REQUIRED"
    assert patch_response.status_code == 403
    assert patch_response.json()["detail"]["code"] == "REPOSITORY_SCOPE_REQUIRED"
    assert bulk_response.status_code == 403
    assert bulk_response.json()["detail"]["code"] == "REPOSITORY_SCOPE_REQUIRED"


def test_list_specs_supports_status_search_and_cursor() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000061",
                "provider": "github",
                "owner": "acme",
                "name": "spec-listing",
                "branches": [{"branch": "main"}],
                "manifest": (
                    "version: 1\n"
                    "specs:\n"
                    "  - path: apis/imported.yaml\n"
                    "    project: payments\n"
                    "    promote: auto\n"
                ),
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="spec-listing-seed",
            files=[
                {"path": "apis/imported.yaml", "blobSha": "1", "tracked": True, "autoImportEnabled": True},
                {
                    "path": "apis/parse-error.yaml",
                    "blobSha": "2",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": True,
                    "settingsJson": {"forceImportFailure": "bad parser"},
                },
                {"path": "apis/not-imported.yaml", "blobSha": "3", "tracked": True, "importEnabled": False},
            ],
        )

        first_page = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs",
            params={"branch": "main", "limit": 1},
        )
        next_cursor = first_page.json()["nextCursor"]
        second_page = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs",
            params={"branch": "main", "limit": 2, "cursor": next_cursor},
        )
        parse_errors = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs",
            params={"branch": "main", "status": "parse_error"},
        )
        search_imported = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs",
            params={"branch": "main", "search": "imported.yaml"},
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 1
    assert next_cursor is not None
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) >= 1
    by_path = {
        item["path"]: item
        for item in (first_page.json()["items"] + second_page.json()["items"])
    }
    assert by_path["apis/imported.yaml"]["status"] == "imported"
    assert by_path["apis/parse-error.yaml"]["status"] == "parse_error"
    assert by_path["apis/not-imported.yaml"]["status"] == "not_imported"
    assert parse_errors.status_code == 200
    assert [row["path"] for row in parse_errors.json()["items"]] == ["apis/parse-error.yaml"]
    assert search_imported.status_code == 200
    assert sorted(row["path"] for row in search_imported.json()["items"]) == [
        "apis/imported.yaml",
        "apis/not-imported.yaml",
    ]


def test_patch_specs_enforces_selection_invariant_and_writes_audit() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000062",
                "provider": "github",
                "owner": "acme",
                "name": "spec-patch",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="patch-seed",
            files=[
                {
                    "path": "apis/patchable.yaml",
                    "blobSha": "1",
                    "tracked": True,
                    "importEnabled": False,
                    "autoImportEnabled": False,
                }
            ],
        )
        file_id = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{scan_id}/files"
        ).json()["items"][0]["id"]
        audit_baseline = len(_get_repository_audit_rows_for_tests(repository_id))

        invalid_response = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}",
            json={"autoImportEnabled": True},
        )
        valid_response = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}",
            json={"importEnabled": True, "autoImportEnabled": True},
        )
        disable_response = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}",
            json={"importEnabled": False},
        )
        audit_rows = _get_repository_audit_rows_for_tests(repository_id)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert invalid_response.status_code == 400
    assert invalid_response.json()["detail"]["code"] == "SELECTION_INVARIANT_VIOLATION"
    assert valid_response.status_code == 200
    assert valid_response.json()["importEnabled"] is True
    assert valid_response.json()["autoImportEnabled"] is True
    assert disable_response.status_code == 200
    assert disable_response.json()["importEnabled"] is False
    assert disable_response.json()["autoImportEnabled"] is False
    new_selection_audits = [
        row for row in audit_rows[audit_baseline:] if row["eventType"] == "repository.spec.selection_changed"
    ]
    # Two PATCHes that each toggle both fields produce four field-level audits:
    # (False -> True) for import_enabled and auto_import_enabled, then (True -> False) for both
    # when the atomic auto-import disable kicks in alongside importEnabled=False.
    assert len(new_selection_audits) == 4
    assert {row["detail"]["field"] for row in new_selection_audits} == {"import_enabled", "auto_import_enabled"}


def test_bulk_update_specs_is_transactional_and_capped() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000063",
                "provider": "github",
                "owner": "acme",
                "name": "spec-bulk",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="bulk-seed",
            files=[
                {"path": "apis/a.yaml", "blobSha": "1", "tracked": True, "importEnabled": True, "autoImportEnabled": False},
                {"path": "apis/b.yaml", "blobSha": "2", "tracked": True, "importEnabled": False, "autoImportEnabled": False},
            ],
        )
        file_rows = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{scan_id}/files"
        ).json()["items"]
        file_ids = [row["id"] for row in file_rows]

        oversized_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs:bulkUpdate",
            json={"file_ids": file_ids + ["11111111-1111-1111-1111-111111111111"] * 499, "importEnabled": True},
        )
        invalid_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs:bulkUpdate",
            json={"file_ids": file_ids, "autoImportEnabled": True},
        )
        after_invalid = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs",
            params={"branch": "main"},
        )
        valid_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs:bulkUpdate",
            json={"file_ids": file_ids, "importEnabled": True, "autoImportEnabled": True},
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert oversized_response.status_code == 422
    assert invalid_response.status_code == 400
    assert invalid_response.json()["detail"]["code"] == "SELECTION_INVARIANT_VIOLATION"
    assert after_invalid.status_code == 200
    before_valid = {row["path"]: row for row in after_invalid.json()["items"]}
    assert before_valid["apis/a.yaml"]["autoImportEnabled"] is False
    assert before_valid["apis/b.yaml"]["importEnabled"] is False

    assert valid_response.status_code == 200
    assert valid_response.json()["updatedCount"] == 2
    after_valid = {row["path"]: row for row in valid_response.json()["items"]}
    assert after_valid["apis/a.yaml"]["importEnabled"] is True
    assert after_valid["apis/a.yaml"]["autoImportEnabled"] is True
    assert after_valid["apis/b.yaml"]["importEnabled"] is True
    assert after_valid["apis/b.yaml"]["autoImportEnabled"] is True


def test_list_specs_exposes_confidence_and_supports_min_confidence_filter() -> None:
    """REPO-9.4: spec listings expose sniffer confidence/discriminator and
    support a minimum-confidence filter so the ADE Specs tab can hide rows
    the walker did not classify."""
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000064",
                "provider": "github",
                "owner": "acme",
                "name": "spec-confidence",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="confidence-seed",
            files=[
                {
                    "path": "apis/high.yaml",
                    "blobSha": "1",
                    "tracked": True,
                    "format": "openapi_3_1",
                    "confidence": 0.9,
                    "discriminator": "openapi: 3.1.0",
                },
                {
                    "path": "apis/medium.yaml",
                    "blobSha": "2",
                    "tracked": True,
                    "format": "openapi_3_0",
                    "confidence": 0.6,
                    "discriminator": "openapi: 3.0",
                },
                {
                    "path": "apis/low.yaml",
                    "blobSha": "3",
                    "tracked": False,
                    "format": "json_schema",
                    "confidence": 0.3,
                },
                {
                    "path": "apis/missing.yaml",
                    "blobSha": "4",
                    "tracked": False,
                },
            ],
        )

        unfiltered = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs",
            params={"branch": "main"},
        )
        importable_only = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs",
            params={"branch": "main", "min_confidence": 0.5},
        )
        invalid_threshold = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs",
            params={"branch": "main", "min_confidence": 1.5},
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert unfiltered.status_code == 200
    unfiltered_paths = {row["path"] for row in unfiltered.json()["items"]}
    assert unfiltered_paths == {
        "apis/high.yaml",
        "apis/medium.yaml",
        "apis/low.yaml",
        "apis/missing.yaml",
    }
    high_row = next(row for row in unfiltered.json()["items"] if row["path"] == "apis/high.yaml")
    assert high_row["confidence"] == 0.9
    assert high_row["discriminator"] == "openapi: 3.1.0"
    assert high_row["lastImportedAt"] is None

    assert importable_only.status_code == 200
    importable_paths = sorted(row["path"] for row in importable_only.json()["items"])
    assert importable_paths == ["apis/high.yaml", "apis/medium.yaml"]

    assert invalid_threshold.status_code == 422


def test_import_now_dispatches_manual_job_idempotency_and_audit() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    r1 = None
    r2 = None
    by_path: dict = {}
    import_audits: list = []
    file_id = ""
    create_response = None
    repository_id = ""
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000070",
                "provider": "github",
                "owner": "acme",
                "name": "import-now",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="import-now-seed",
            files=[
                {
                    "path": "apis/manual.yaml",
                    "blobSha": "1",
                    "contentAlgo": "sha256",
                    "contentChecksum": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                    "tracked": True,
                    "importEnabled": True,
                    "autoImportEnabled": False,
                    "projectSlug": "payments",
                }
            ],
        )
        file_id = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{scan_id}/files",
        ).json()["items"][0]["id"]
        with patch("app.repositories_routes.db") as mdb:
            mdb.get_project_by_slug.return_value = {"id": "99999999-9999-9999-9999-999999999999"}
            mdb.get_latest_repository_source_checksum_for_project.return_value = None
            r1 = client.post(
                f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}:importNow",
                json={"branch": "main", "force": True},
            )
            r2 = client.post(
                f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}:importNow",
                json={"branch": "main", "force": True},
            )
        spec_row = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs",
            params={"branch": "main"},
        ).json()["items"]
        by_path = {r["path"]: r for r in spec_row}
        audit_rows = _get_repository_audit_rows_for_tests(repository_id)
        import_audits = [a for a in audit_rows if a["eventType"] == "repository.spec.import_now_triggered"]
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response is not None and create_response.status_code == 201
    assert r1 is not None and r1.status_code == 202
    assert r2 is not None and r2.status_code == 202
    job_id_1 = r1.json()["importJobId"]
    assert r2.json()["importJobId"] == job_id_1
    assert by_path["apis/manual.yaml"]["status"] == "importing"
    assert len(import_audits) == 1
    assert import_audits[0]["detail"]["fileId"] == file_id
    assert import_audits[0]["detail"]["branch"] == "main"
    assert import_audits[0]["detail"]["force"] is True
    jobs = [j for j in _get_repository_import_jobs_for_tests(repository_id) if j.id == job_id_1]
    assert len(jobs) == 1
    assert jobs[0].sourceKind == "repository_manual_import"


def test_import_now_rejects_disabled_import_and_unchanged_checksum() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000071",
                "provider": "github",
                "owner": "acme",
                "name": "import-now-gate",
                "branches": [{"branch": "main"}],
            },
        )
        repository_id = create_response.json()["repository"]["id"]
        scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="gate-seed",
            files=[
                {
                    "path": "apis/locked.yaml",
                    "blobSha": "1",
                    "contentAlgo": "sha256",
                    "contentChecksum": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                    "tracked": True,
                    "importEnabled": False,
                    "autoImportEnabled": False,
                    "projectSlug": "pay",
                },
            ],
        )
        file_id = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{scan_id}/files",
        ).json()["items"][0]["id"]
        disabled = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}:importNow",
            json={"force": False},
        )
        patch_response = client.patch(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}",
            json={"importEnabled": True},
        )
        opened_id = patch_response.json()["fileId"]
        with patch("app.repositories_routes.db") as mdb:
            mdb.get_project_by_slug.return_value = {"id": "88888888-8888-8888-8888-888888888888"}
            mdb.get_latest_repository_source_checksum_for_project.return_value = (
                "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
            )
            conflict = client.post(
                f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{opened_id}:importNow",
                json={"force": False},
            )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert create_response.status_code == 201
    assert disabled.status_code == 400
    assert disabled.json()["detail"]["code"] == "IMPORT_NOT_ENABLED"
    assert patch_response.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IMPORT_UNCHANGED_CHECKSUM"


# ----------------------------------------------------------------------
# REPO-9.6 — spec detail drawer endpoints
# ----------------------------------------------------------------------


def _setup_repo_for_spec_drawer(
    *,
    linked_account_id: str,
    repo_name: str,
    file_path: str = "openapi/orders-v3.yaml",
    file_size: int | None = None,
    import_enabled: bool = True,
    auto_import_enabled: bool = False,
) -> tuple[str, str, str]:
    """Helper that registers a repo, completes a scan with one file, and
    returns ``(repository_id, scan_id, file_id)`` for spec-drawer tests."""
    create_response = client.post(
        f"/v1/repositories/{_TENANT_SLUG}",
        json={
            "linkedAccountId": linked_account_id,
            "provider": "github",
            "owner": "acme",
            "name": repo_name,
            "branches": [{"branch": "main"}],
            "manifest": (
                "version: 1\n"
                "specs:\n"
                f"  - path: {file_path}\n"
                "    project: payments\n"
                "    promote: auto\n"
                "    importEnabled: true\n"
            ),
        },
    )
    repository_id = create_response.json()["repository"]["id"]
    scan_id = create_response.json()["initialScanJobId"]
    seed_file: dict = {
        "path": file_path,
        "blobSha": "sha-1",
        "contentAlgo": "sha256",
        "contentChecksum": "f" * 64,
        "tracked": True,
        "importEnabled": import_enabled,
        "autoImportEnabled": auto_import_enabled,
        "projectSlug": "payments",
    }
    if file_size is not None:
        seed_file["sizeBytes"] = file_size
    _complete_repository_scan_for_tests(
        repository_id,
        scan_id,
        commit_sha="drawer-seed",
        files=[seed_file],
    )
    file_id = client.get(
        f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans/{scan_id}/files",
    ).json()["items"][0]["id"]
    return repository_id, scan_id, file_id


def test_spec_detail_returns_provider_links_imports_and_lint_summary() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    detail = None
    try:
        repository_id, _scan_id, file_id = _setup_repo_for_spec_drawer(
            linked_account_id="aaaaaaaa-bbbb-cccc-dddd-000000000080",
            repo_name="drawer-detail",
        )
        with patch("app.repositories_routes.db") as mdb:
            mdb.get_project_by_slug.return_value = {"id": "99999999-9999-9999-9999-999999999999"}
            mdb.get_latest_repository_source_checksum_for_project.return_value = None
            client.post(
                f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}:importNow",
                json={"branch": "main", "force": True},
            )
        detail = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}/detail",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert detail is not None
    assert detail.status_code == 200
    body = detail.json()
    assert body["fullName"] == "acme/drawer-detail"
    assert body["provider"] == "github"
    assert body["providerWebUrl"] == "https://github.com/acme/drawer-detail/blob/main/openapi/orders-v3.yaml"
    assert body["providerRawUrl"] == "https://raw.githubusercontent.com/acme/drawer-detail/main/openapi/orders-v3.yaml"
    assert body["spec"]["fileId"] == file_id
    assert body["branch"] == "main"
    assert body["path"] == "openapi/orders-v3.yaml"
    assert len(body["recentImports"]) == 1
    job = body["recentImports"][0]
    assert job["sourceKind"] == "repository_manual_import"
    assert job["state"] in {"pending_review", "committed"}
    assert job["lintSummary"]["sourceImportJobId"] == job["id"]
    assert isinstance(body["lintSummary"]["errors"], int)
    assert body["lintSummary"]["sourceImportJobId"] == job["id"]


def test_spec_detail_requires_repository_read_scope() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    response = None
    try:
        repository_id, _scan_id, file_id = _setup_repo_for_spec_drawer(
            linked_account_id="aaaaaaaa-bbbb-cccc-dddd-000000000081",
            repo_name="drawer-scope",
        )
        response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}/detail",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert response is not None
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "REPOSITORY_SCOPE_REQUIRED"


def test_spec_detail_404_for_missing_file() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    response = None
    try:
        repository_id, _scan_id, _file_id = _setup_repo_for_spec_drawer(
            linked_account_id="aaaaaaaa-bbbb-cccc-dddd-000000000082",
            repo_name="drawer-missing",
        )
        response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/00000000-0000-4000-8000-000000000000/detail",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert response is not None and response.status_code == 404


def test_spec_content_returns_inline_text_when_under_limit() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    response = None
    expected_text = "openapi: 3.1.0\ninfo:\n  title: Orders\n  version: 3.4.0\n"
    try:
        repository_id, _scan_id, file_id = _setup_repo_for_spec_drawer(
            linked_account_id="aaaaaaaa-bbbb-cccc-dddd-000000000083",
            repo_name="drawer-content",
        )
        _seed_repository_file_content_for_tests(repository_id, file_id, expected_text.encode("utf-8"))
        response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}/content",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert response is not None
    assert response.status_code == 200
    body = response.json()
    assert body["encoding"] == "utf-8"
    assert body["content"] == expected_text
    assert body["sizeBytes"] == len(expected_text.encode("utf-8"))
    assert body["tooLargeForPreview"] is False
    assert body["truncated"] is False
    assert body["maxInlineBytes"] == MAX_INLINE_PREVIEW_BYTES
    assert body["providerRawUrl"].startswith("https://raw.githubusercontent.com/")


def test_spec_content_returns_download_prompt_when_size_metadata_exceeds_2mb() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    response = None
    try:
        oversized = MAX_INLINE_PREVIEW_BYTES + 1024
        repository_id, _scan_id, file_id = _setup_repo_for_spec_drawer(
            linked_account_id="aaaaaaaa-bbbb-cccc-dddd-000000000084",
            repo_name="drawer-oversized",
            file_size=oversized,
        )
        response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}/content",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert response is not None
    assert response.status_code == 200
    body = response.json()
    assert body["tooLargeForPreview"] is True
    assert body["content"] is None
    assert body["sizeBytes"] == oversized
    assert body["providerRawUrl"].endswith("openapi/orders-v3.yaml")


def test_spec_content_returns_download_prompt_when_actual_payload_exceeds_2mb() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    response = None
    try:
        repository_id, _scan_id, file_id = _setup_repo_for_spec_drawer(
            linked_account_id="aaaaaaaa-bbbb-cccc-dddd-000000000085",
            repo_name="drawer-actual-oversized",
        )
        big_payload = b"x" * (MAX_INLINE_PREVIEW_BYTES + 32)
        _seed_repository_file_content_for_tests(repository_id, file_id, big_payload)
        response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}/content",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert response is not None
    assert response.status_code == 200
    body = response.json()
    assert body["tooLargeForPreview"] is True
    assert body["content"] is None
    assert body["sizeBytes"] == len(big_payload)


def test_spec_content_returns_base64_for_binary_payload() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    response = None
    binary_payload = b"\x00\x01\x02PNGSTUB\x00\xff"
    try:
        repository_id, _scan_id, file_id = _setup_repo_for_spec_drawer(
            linked_account_id="aaaaaaaa-bbbb-cccc-dddd-000000000086",
            repo_name="drawer-binary",
            file_path="schemas/binary.bin",
        )
        _seed_repository_file_content_for_tests(repository_id, file_id, binary_payload)
        response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}/content",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert response is not None
    assert response.status_code == 200
    body = response.json()
    assert body["encoding"] == "base64"
    import base64 as _b64
    assert _b64.b64decode(body["content"]) == binary_payload


def test_spec_content_requires_repository_read_scope() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    response = None
    try:
        repository_id, _scan_id, file_id = _setup_repo_for_spec_drawer(
            linked_account_id="aaaaaaaa-bbbb-cccc-dddd-000000000087",
            repo_name="drawer-content-scope",
        )
        response = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/specs/{file_id}/content",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert response is not None
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "REPOSITORY_SCOPE_REQUIRED"


def test_scan_reports_list_requires_repository_read_scope() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        response = client.get(f"/v1/repositories/{_TENANT_SLUG}/scan-reports")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "REPOSITORY_SCOPE_REQUIRED"


def test_repository_corpus_stats_requires_repository_read_scope() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        response = client.get(f"/v1/dashboard/{_TENANT_SLUG}/repository_corpus_stats")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "REPOSITORY_SCOPE_REQUIRED"


def test_repository_attention_requires_repository_read_scope() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        response = client.get(f"/v1/dashboard/{_TENANT_SLUG}/repository_attention?limit=5")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "REPOSITORY_SCOPE_REQUIRED"


def test_repository_attention_shape_and_tenant_rollup() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        r = client.get(f"/v1/dashboard/{_TENANT_SLUG}/repository_attention?limit=3")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert "repositoriesTracked" in body
    assert "needingAttentionCount" in body
    assert "otherHealthyCount" in body
    assert "refreshedAt" in body
    assert isinstance(body["items"], list)
    assert body["repositoriesTracked"] >= 0
    assert body["needingAttentionCount"] >= 0
    assert body["otherHealthyCount"] >= 0
    assert body["needingAttentionCount"] <= max(0, body["repositoriesTracked"])
    assert body["otherHealthyCount"] + body["needingAttentionCount"] == body["repositoriesTracked"]
    for it in body["items"]:
        assert "repositoryId" in it
        assert "fullName" in it
        assert "topReason" in it
        assert "detailTab" in it
        assert "openCount" in it
        assert "lastChangeAt" in it


def test_repository_attention_full_name_uses_rid_when_owner_or_name_missing() -> None:
    """Regression: fullName must not produce 'owner/' or '/name' when one part is absent."""
    fake_rows = [
        {
            "repository_id": "repo-only-owner",
            "owner": "myorg",
            "name": "",
            "reasons": ["parse_error"],
            "open_count": 1,
            "attention_score": 20,
            "last_change_at": "2025-01-01T00:00:00+00:00",
        },
        {
            "repository_id": "repo-only-name",
            "owner": "",
            "name": "myrepo",
            "reasons": ["parse_error"],
            "open_count": 1,
            "attention_score": 20,
            "last_change_at": "2025-01-01T00:00:00+00:00",
        },
    ]
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        with patch("app.dashboard_routes.db") as mdb:
            mdb.list_repository_attention_for_tenant.return_value = (fake_rows, 2, 2)
            r = client.get(f"/v1/dashboard/{_TENANT_SLUG}/repository_attention?limit=5")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert r.status_code == 200, r.text
    items = {it["repositoryId"]: it["fullName"] for it in r.json()["items"]}
    assert items["repo-only-owner"] == "myorg"
    assert items["repo-only-name"] == "myrepo"


def test_recent_imports_attention_requires_repository_read_scope() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        response = client.get(f"/v1/dashboard/{_TENANT_SLUG}/recent_imports_attention?limit=5")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "REPOSITORY_SCOPE_REQUIRED"


def test_recent_imports_attention_returns_shape_and_empty() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        r = client.get(f"/v1/dashboard/{_TENANT_SLUG}/recent_imports_attention?limit=5")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert "refreshedAt" in body


def test_recent_imports_attention_dismiss_calls_db() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        with patch("app.dashboard_routes.db") as mdb:
            r = client.post(
                f"/v1/dashboard/{_TENANT_SLUG}/recent_imports_attention/dismiss",
                json={"importJobId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
            )
            assert mdb.dismiss_recent_import_attention_job.called
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_repository_corpus_stats_matches_latest_scan_rollup() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000201",
                "provider": "github",
                "owner": "acme",
                "name": "corpus-rollup",
                "branches": [{"branch": "main"}],
            },
        )
        assert create_response.status_code == 201, create_response.text
        create_body = create_response.json()
        repository_id = create_body["repository"]["id"]
        scan_id = create_body["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="c1",
            files=[
                {
                    "path": "specs/api.yaml",
                    "format": "openapi_3.1",
                    "confidence": 0.9,
                    "tracked": True,
                },
            ],
        )
        stats = client.get(f"/v1/dashboard/{_TENANT_SLUG}/repository_corpus_stats")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert stats.status_code == 200, stats.text
    s = stats.json()
    assert s["repositoriesTracked"] >= 1
    assert s["importableSpecs"] >= 1
    assert s["refreshedAt"]


def test_register_repository_recomputes_corpus_rollup() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        c1 = client.get(f"/v1/dashboard/{_TENANT_SLUG}/repository_corpus_stats")
        assert c1.status_code == 200
        before = c1.json()["repositoriesTracked"]
        r = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000202",
                "provider": "github",
                "owner": "acme",
                "name": "corpus-track-count",
                "branches": [{"branch": "main"}],
            },
        )
        assert r.status_code == 201, r.text
        c2 = client.get(f"/v1/dashboard/{_TENANT_SLUG}/repository_corpus_stats")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert c2.status_code == 200
    after = c2.json()["repositoriesTracked"]
    assert after == before + 1


def test_scan_reports_list_includes_materialized_row_after_scan() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000088",
                "provider": "github",
                "owner": "acme",
                "name": "scan-report-probe",
                "branches": [{"branch": "main"}],
            },
        )
        assert create_response.status_code == 201, f"Repository creation failed: {create_response.text}"
        create_body = create_response.json()
        repository_id = create_body["repository"]["id"]
        scan_id = create_body["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            scan_id,
            commit_sha="abc1234",
            files=[
                {
                    "path": "specs/api.yaml",
                    "format": "openapi_3.1",
                    "confidence": 0.9,
                    "tracked": True,
                }
            ],
        )
        list_response = client.get(f"/v1/repositories/{_TENANT_SLUG}/scan-reports")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] >= 1
    item = next((row for row in body["items"] if row["repositoryId"] == repository_id), None)
    assert item is not None
    assert item["totals"] is not None
    assert int(item["totals"]["importable"]) >= 1
    assert item["lastScanId"] == scan_id
    assert item.get("lastReportId")


def test_per_repository_scan_reports_list_detail_latest_and_diff() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        create_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}",
            json={
                "linkedAccountId": "aaaaaaaa-bbbb-cccc-dddd-000000000099",
                "provider": "github",
                "owner": "acme",
                "name": "per-repo-reports",
                "branches": [{"branch": "main"}],
            },
        )
        assert create_response.status_code == 201, create_response.text
        repository_id = create_response.json()["repository"]["id"]
        first_scan_id = create_response.json()["initialScanJobId"]
        _complete_repository_scan_for_tests(
            repository_id,
            first_scan_id,
            commit_sha="c1",
            files=[
                {
                    "path": "specs/api.yaml",
                    "format": "openapi_3.1",
                    "confidence": 0.9,
                    "tracked": True,
                },
            ],
        )
        tlist = client.get(f"/v1/repositories/{_TENANT_SLUG}/scan-reports")
        assert tlist.status_code == 200
        t_item = next(
            (row for row in tlist.json()["items"] if row["repositoryId"] == repository_id), None
        )
        assert t_item is not None
        assert t_item.get("lastReportId")
        report_a = str(t_item["lastReportId"])
        rlist = client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scan-reports")
        assert rlist.status_code == 200
        rj = rlist.json()
        assert rj["total"] == 1
        assert rj["items"][0]["id"] == report_a
        latest = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scan-reports/latest",
            follow_redirects=False,
        )
        assert latest.status_code == 302
        assert report_a in (latest.headers.get("location") or "")

        detail = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scan-reports/{report_a}"
        )
        assert detail.status_code == 200
        dj = detail.json()
        assert dj["id"] == report_a
        assert dj["compareToPrevious"] is None
        assert isinstance(dj["payload"], list) and len(dj["payload"]) >= 1
        assert dj["scan"] is not None

        next_scan = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": True},
        )
        assert next_scan.status_code == 200, next_scan.text
        second_scan_id = next_scan.json()["id"]
        _complete_repository_scan_for_tests(
            repository_id,
            second_scan_id,
            commit_sha="c2",
            files=[
                {
                    "path": "specs/api.yaml",
                    "format": "openapi_3.1",
                    "confidence": 0.9,
                    "tracked": True,
                },
            ],
        )
        rlist2 = client.get(f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scan-reports")
        assert rlist2.json()["total"] == 2
        report_b = rlist2.json()["items"][0]["id"]
        det_b = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scan-reports/{report_b}"
        )
        body_b = det_b.json()
        assert body_b["compareToPrevious"] is not None
        assert body_b["compareToPrevious"]["otherReportId"] == report_a
        diff = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scan-reports/{report_b}/diff/{report_a}"
        )
        assert diff.status_code == 200
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_per_repo_scan_report_endpoints_require_repository_read_scope() -> None:
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        r = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/"
            "aaaaaaaa-bbbb-cccc-dddd-00000000aaaa/scan-reports",
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "REPOSITORY_SCOPE_REQUIRED"


def test_scan_report_export_202_and_empty_csv() -> None:
    """0 matching repositories → 202, completed job with header-only CSV."""
    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        p = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/scan-reports:export",
            json={"format": "csv", "filter": {"provider": "all", "status": "all", "search": ""}},
        )
        assert p.status_code == 202, p.text
        eid = p.json()["exportJobId"]
        g = client.get(f"/v1/repositories/{_TENANT_SLUG}/scan-reports/exports/{eid}")
        assert g.status_code == 200
        gj = g.json()
        assert gj.get("status") == "completed"
        assert gj.get("rowCount") == 0
        token = (gj.get("downloadUrl") or "").split("token=")[-1]
        d = client.get(
            f"/v1/repositories/{_TENANT_SLUG}/scan-reports/exports/{eid}/content?token={token}"
        )
        assert d.status_code == 200
        assert b"scan_id" in d.content
        l = client.get(f"/v1/repositories/{_TENANT_SLUG}/scan-reports/exports")
        assert l.status_code == 200
        assert len(l.json()["items"]) >= 1
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_scan_report_export_row_cap_400() -> None:
    from app import repositories_routes as rr

    app.dependency_overrides[validate_authentication] = _override_auth_with_repository_scopes
    try:
        with patch.object(
            rr,
            "count_scan_report_export_row_candidates",
            return_value=100_001,
        ):
            p = client.post(
                f"/v1/repositories/{_TENANT_SLUG}/scan-reports:export",
                json={"format": "csv", "filter": {}},
            )
        assert p.status_code == 400
        det = p.json()["detail"]
        assert isinstance(det, dict) and det.get("code") == "EXPORT_ROW_CAP_EXCEEDED"
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
