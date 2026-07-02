"""Tests for tenant repository list/files commands and unsupported stubs."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_TENANT_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_REPO_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_REPO_ID_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

_REPO_ITEM = {
    "id": _REPO_ID,
    "tenant_id": _TENANT_ID,
    "name": "API Specs",
    "provider": "github",
    "linked_account_id": None,
    "clone_url": "https://github.com/acme/api-specs.git",
    "default_branch": "main",
    "visibility": "private",
    "status": "ready",
    "last_scanned_at": "2026-06-07T12:00:00Z",
    "total_files": 12,
    "total_bytes": 4096,
    "last_error_message": None,
    "enabled": True,
    "created_on": "2026-06-01T00:00:00Z",
    "updated_on": None,
    "deleted_on": None,
    "_links": {
        "self": {"href": f"/tenants/{_TENANT_ID}/repositories/{_REPO_ID}"},
        "files": {"href": f"/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files"},
        "imports": {"href": f"/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/imports"},
        "scans": {"href": f"/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/scans"},
        "branches": {"href": f"/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/branches"},
    },
}

_REPO_ITEM_2 = {
    **_REPO_ITEM,
    "id": _REPO_ID_2,
    "name": "Public Specs",
    "provider": "public_url",
    "status": "pending",
    "last_scanned_at": None,
    "total_files": 0,
}

_LINKED_ACCOUNT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

_TENANTS_ME_URL = "http://localhost:8000/v1/tenants/me?offset=0&limit=200"
_TENANTS_ME_BODY = {
    "items": [{"slug": _TENANT_ID}],
    "total": 1,
    "offset": 0,
    "limit": 200,
}

_FILE_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

_FILE_ITEM = {
    "id": _FILE_ID,
    "repository_id": _REPO_ID,
    "branch_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "path": "openapi.yaml",
    "name": "openapi.yaml",
    "ext": "yaml",
    "size_bytes": 128,
    "blob_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "content_integrity_verified": True,
    "signature_status": "valid",
    "last_commit_sha": None,
    "last_commit_at": None,
    "detected_kind": "openapi-candidate",
    "detected_confidence": "filename_only",
    "importable": True,
    "import_blocked_reason": None,
    "enabled": True,
    "created_on": "2026-06-07T12:00:00Z",
    "updated_on": None,
    "deleted_on": None,
    "_links": {
        "self": {
            "href": (
                f"/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files/{_FILE_ID}"
            ),
        },
        "content": {
            "href": (
                f"/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files/{_FILE_ID}/content"
            ),
        },
        "sniff": {
            "href": (
                f"/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files/{_FILE_ID}/sniff"
            ),
        },
        "import": {
            "href": (
                f"/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files/{_FILE_ID}/import"
            ),
        },
    },
}

_FILE_ITEM_2 = {
    **_FILE_ITEM,
    "id": "11111111-1111-4111-8111-111111111111",
    "path": "docs/readme.md",
    "name": "readme.md",
    "ext": "md",
    "size_bytes": 64,
    "detected_kind": None,
    "detected_confidence": None,
    "importable": None,
}


_NOT_SUPPORTED_MESSAGE = "not supported via the /v1 REST API yet"


@pytest.fixture
def repos_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", _TENANT_ID)


@pytest.fixture
def api_key_only_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")


def test_repos_list_requires_api_key() -> None:
    result = runner.invoke(app, ["repos", "list"])
    assert result.exit_code == EXIT_USAGE
    assert "API key required" in strip_ansi(result.stderr)


def test_repos_list_requires_tenant_scope(api_key_only_env: None) -> None:
    result = runner.invoke(app, ["repos", "list"])
    assert result.exit_code == EXIT_USAGE
    assert "Tenant scope required" in strip_ansi(result.stderr)


def test_repos_list_human_output(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories",
        json={"items": [_REPO_ITEM], "total": 1, "offset": 0, "limit": 50},
        match_headers={"X-API-Key": "obj_test_workspace_key"},
    )
    result = runner.invoke(app, ["repos", "list"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "API" in output
    assert "Specs" in output
    assert "github" in output
    assert "ready" in output
    assert "main" in output
    assert "private" in output
    assert "12" in output
    assert "Showing 1 of 1" in output


def test_repos_list_json_format(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories",
        json={"items": [_REPO_ITEM], "total": 1, "offset": 0, "limit": 50},
    )
    result = runner.invoke(app, ["repos", "list", "--format", "json"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["total"] == 1
    assert payload["items"][0]["name"] == "API Specs"
    assert payload["items"][0]["provider"] == "github"


def test_repos_list_global_json_flag(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories",
        json={"items": [_REPO_ITEM], "total": 1, "offset": 0, "limit": 50},
    )
    result = runner.invoke(app, ["--json", "repos", "list"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["items"][0]["status"] == "ready"


def test_repos_list_filtered_by_provider_status_and_name(
    httpx_mock: object,
    repos_env: None,
) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories"
            "?provider=github&status=ready&name=API"
        ),
        json={"items": [_REPO_ITEM], "total": 1, "offset": 0, "limit": 50},
    )
    result = runner.invoke(
        app,
        [
            "repos",
            "list",
            "--provider",
            "github",
            "--status",
            "ready",
            "--name",
            "API",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "API" in output
    assert "Specs" in output
    assert "Public" not in output


def test_repos_list_rejects_invalid_provider(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    result = runner.invoke(app, ["repos", "list", "--provider", "svn"])
    assert result.exit_code != EXIT_SUCCESS
    assert "provider must be one of" in strip_ansi(result.output)


def test_repos_list_rejects_invalid_status(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    result = runner.invoke(app, ["repos", "list", "--status", "deleted"])
    assert result.exit_code != EXIT_SUCCESS
    assert "status must be one of" in strip_ansi(result.output)


def test_repos_list_rejects_invalid_format(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "list", "--format", "yaml"])
    assert result.exit_code != EXIT_SUCCESS
    assert "format must be 'table' or 'json'" in strip_ansi(result.output)


def test_repos_list_empty_human_output(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories",
        json={"items": [], "total": 0, "offset": 0, "limit": 50},
    )
    result = runner.invoke(app, ["repos", "list"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "No items." in output
    assert "Total: 0" in output


def test_repos_list_multiple_items(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories",
        json={
            "items": [_REPO_ITEM, _REPO_ITEM_2],
            "total": 2,
            "offset": 0,
            "limit": 50,
        },
    )
    result = runner.invoke(app, ["repos", "list"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "API" in output
    assert "Specs" in output
    assert "Public" in output
    assert "Showing 2 of 2" in output


def test_repos_list_resolves_tenant_slug(httpx_mock: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")

    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp/repositories",
        json={"items": [_REPO_ITEM_2], "total": 1, "offset": 0, "limit": 50},
    )

    result = runner.invoke(app, ["repos", "list"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Public" in output
    assert "Specs" in output
    assert "public" in output


def test_repos_help_lists_subcommands() -> None:
    group_result = runner.invoke(app, ["repos", "--help"])
    assert group_result.exit_code == EXIT_SUCCESS
    group_help = strip_ansi(group_result.stdout)
    assert "list" in group_help
    assert "show" in group_help
    assert "files" in group_help
    assert "content" in group_help
    assert "add" in group_help
    assert "scan" in group_help
    assert "inspect" in group_help
    assert "import" in group_help
    assert "imports" in group_help
    assert "verify" in group_help

    inspect_result = runner.invoke(app, ["repos", "inspect", "--help"])
    assert inspect_result.exit_code == EXIT_SUCCESS

    files_result = runner.invoke(app, ["repos", "files", "--help"])
    assert files_result.exit_code == EXIT_SUCCESS
    files_help = strip_ansi(files_result.stdout)
    assert "--glob" in files_help
    assert "--regex" in files_help
    assert "--preset" in files_help
    assert "--detected-kind" in files_help
    assert "--importable" in files_help

    list_result = runner.invoke(app, ["repos", "list", "--help"])
    assert list_result.exit_code == EXIT_SUCCESS
    list_help = strip_ansi(list_result.stdout)
    assert "--provider" in list_help
    assert "--status" in list_help
    assert "--format" in list_help

    add_result = runner.invoke(app, ["repos", "add", "--help"])
    assert add_result.exit_code == EXIT_SUCCESS

    scan_result = runner.invoke(app, ["repos", "scan", "--help"])
    assert scan_result.exit_code == EXIT_SUCCESS


def test_repos_add_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "add"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_add_requires_api_key(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "add"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_add_requires_tenant_scope(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "add"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_add_requires_mode(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "add"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_add_rejects_mixed_modes(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "add"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_add_public_url_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "add"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_add_linked_account_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "add"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_add_rejects_invalid_format(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "add"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_scan_requires_api_key(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "scan"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_scan_requires_tenant_scope(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "scan"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_scan_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "scan"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_scan_with_branch_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "scan"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_scan_wait_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "scan"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_scan_rejects_invalid_format(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "scan"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_files_requires_api_key() -> None:
    result = runner.invoke(app, ["repos", "files", _REPO_ID])
    assert result.exit_code == EXIT_USAGE
    assert "API key required" in strip_ansi(result.stderr)


def test_repos_files_requires_tenant_scope(api_key_only_env: None) -> None:
    result = runner.invoke(app, ["repos", "files", _REPO_ID])
    assert result.exit_code == EXIT_USAGE
    assert "Tenant scope required" in strip_ansi(result.stderr)


def test_repos_files_human_output(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files"
        ),
        json={"items": [_FILE_ITEM, _FILE_ITEM_2], "total": 2, "offset": 0, "limit": 50},
        match_headers={"X-API-Key": "obj_test_workspace_key"},
    )
    result = runner.invoke(app, ["repos", "files", _REPO_ID])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "openapi.yaml" in output
    assert "openapi-candidate" in output
    assert "yes" in output
    assert "docs/readme.md" in output
    assert "pending" in output
    assert "Showing 2 of 2" in output


def test_repos_files_json_format(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files"
        ),
        json={"items": [_FILE_ITEM], "total": 1, "offset": 0, "limit": 50},
    )
    result = runner.invoke(app, ["repos", "files", _REPO_ID, "--format", "json"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["total"] == 1
    assert payload["items"][0]["path"] == "openapi.yaml"
    assert payload["items"][0]["detected_kind"] == "openapi-candidate"
    assert payload["items"][0]["importable"] is True


def test_repos_files_filtered_by_glob_preset_and_importable(
    httpx_mock: object,
    repos_env: None,
) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files"
            "?glob=%2A%2A%2Fopenapi%2A.yaml&preset=openapi&importable=true"
        ),
        json={"items": [_FILE_ITEM], "total": 1, "offset": 0, "limit": 50},
    )
    result = runner.invoke(
        app,
        [
            "repos",
            "files",
            _REPO_ID,
            "--glob",
            "**/openapi*.yaml",
            "--preset",
            "openapi",
            "--importable",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "openapi.yaml" in output
    assert "readme.md" not in output


def test_repos_files_filtered_by_regex(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files"
            "?regex=openapi"
        ),
        json={"items": [_FILE_ITEM], "total": 1, "offset": 0, "limit": 50},
    )
    result = runner.invoke(
        app,
        ["repos", "files", _REPO_ID, "--regex", "openapi"],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "openapi.yaml" in strip_ansi(result.stdout)


def test_repos_files_rejects_glob_and_regex_together(
    httpx_mock: object,
    repos_env: None,
) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    result = runner.invoke(
        app,
        [
            "repos",
            "files",
            _REPO_ID,
            "--glob",
            "**/*.yaml",
            "--regex",
            "openapi",
        ],
    )
    assert result.exit_code != EXIT_SUCCESS
    assert "mutually exclusive" in strip_ansi(result.output)


def test_repos_files_rejects_invalid_preset(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    result = runner.invoke(
        app,
        ["repos", "files", _REPO_ID, "--preset", "custom"],
    )
    assert result.exit_code != EXIT_SUCCESS
    assert "preset must be one of" in strip_ansi(result.output)


def test_repos_files_empty_human_output(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files"
        ),
        json={"items": [], "total": 0, "offset": 0, "limit": 50},
    )
    result = runner.invoke(app, ["repos", "files", _REPO_ID])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "No items." in output
    assert "Total: 0" in output


def test_repos_files_filtered_by_detected_kind(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files"
            "?detected_kind=openapi-candidate"
        ),
        json={"items": [_FILE_ITEM], "total": 1, "offset": 0, "limit": 50},
    )
    result = runner.invoke(
        app,
        ["repos", "files", _REPO_ID, "--detected-kind", "openapi-candidate"],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "openapi.yaml" in strip_ansi(result.stdout)


def test_repos_files_filtered_by_not_importable(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files"
            "?importable=false"
        ),
        json={
            "items": [
                {
                    **_FILE_ITEM_2,
                    "importable": False,
                    "import_blocked_reason": "Unsupported format",
                },
            ],
            "total": 1,
            "offset": 0,
            "limit": 50,
        },
    )
    result = runner.invoke(app, ["repos", "files", _REPO_ID, "--not-importable"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "readme.md" in output
    assert "no (Unsupported format)" in output


def test_repos_files_global_json_flag(httpx_mock: object, repos_env: None) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/files"
        ),
        json={"items": [_FILE_ITEM], "total": 1, "offset": 0, "limit": 50},
    )
    result = runner.invoke(app, ["--json", "repos", "files", _REPO_ID])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["items"][0]["path"] == "openapi.yaml"


def test_repos_files_rejects_invalid_format(repos_env: None) -> None:
    result = runner.invoke(
        app,
        ["repos", "files", _REPO_ID, "--format", "yaml"],
    )
    assert result.exit_code != EXIT_SUCCESS
    assert "format must be 'table' or 'json'" in strip_ansi(result.output)


def test_repos_inspect_requires_api_key(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "inspect"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_inspect_requires_tenant_scope(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "inspect"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_inspect_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "inspect"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_inspect_rejects_invalid_format(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "inspect"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_inspect_deep_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "inspect"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_inspect_closure_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "inspect"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_verify_requires_api_key(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "verify"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_verify_requires_tenant_scope(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "verify"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_verify_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "verify"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_verify_repository_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "verify"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_verify_rejects_invalid_format(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "verify"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_import_requires_api_key(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "import"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_import_requires_tenant_scope(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "import"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_import_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "import"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_import_new_project_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "import"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_import_existing_project_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "import"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_import_dry_run_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "import"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_import_rejects_invalid_format(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "import"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_import_manifest_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "import"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_import_batch_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "import"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_help_lists_import_subcommand() -> None:
    group_result = runner.invoke(app, ["repos", "--help"])
    assert group_result.exit_code == EXIT_SUCCESS
    assert "import" in strip_ansi(group_result.stdout)

    import_result = runner.invoke(app, ["repos", "import", "--help"])
    assert import_result.exit_code == EXIT_SUCCESS


def test_repos_imports_requires_api_key(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "imports"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_imports_requires_tenant_scope(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "imports"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_imports_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "imports"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_imports_filtered_not_supported(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "imports"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_imports_rejects_invalid_format(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "imports"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_imports_rejects_invalid_since(repos_env: None) -> None:
    result = runner.invoke(app, ["repos", "imports"])
    assert result.exit_code == EXIT_USAGE
    assert _NOT_SUPPORTED_MESSAGE in strip_ansi(result.stderr)


def test_repos_help_lists_imports_subcommand() -> None:
    group_result = runner.invoke(app, ["repos", "--help"])
    assert group_result.exit_code == EXIT_SUCCESS
    assert "imports" in strip_ansi(group_result.stdout)

    imports_result = runner.invoke(app, ["repos", "imports", "--help"])
    assert imports_result.exit_code == EXIT_SUCCESS
