import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.repositories_routes import (
    _get_repository_audit_rows_for_tests,
    _get_repository_relations_exist_for_tests,
    _list_poll_targets_for_tests,
    _reset_repository_state_for_tests,
    _seed_repository_relations_for_tests,
)

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
    assert any(item["id"] == repository_id for item in list_response.json()["repositories"])
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

    assert [row["eventType"] for row in audit_rows] == ["repository.archived", "repository.unarchived"]


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
    assert [row["eventType"] for row in audit_rows] == ["repository.removed"]


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
        forced_response = client.post(
            f"/v1/repositories/{_TENANT_SLUG}/{repository_id}/scans",
            json={"branch": "main", "force": True},
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)

    assert skipped_response.status_code == 200
    skipped_scan = skipped_response.json()
    assert skipped_scan["status"] == "skipped_unchanged"
    assert skipped_scan["filesSeen"] == 0
    assert len(skipped_scan["eventLog"]) == 1
    assert skipped_scan["eventLog"][0]["type"] == "repository.scan.skipped_unchanged"

    assert forced_response.status_code == 200
    forced_scan = forced_response.json()
    assert forced_scan["status"] == "pending"
    assert forced_scan["eventLog"][0]["force"] is True


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
