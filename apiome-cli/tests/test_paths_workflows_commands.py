"""Tests for paths, operations, and workflows read commands."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_PATH_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_OPERATION_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_WORKFLOW_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

_PROJECT = {
    "id": _PROJECT_ID,
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "name": "Payments API",
    "slug": "payments-api",
    "source": "manual",
    "enabled": True,
}
_VERSION = {
    "id": _VERSION_ID,
    "project_id": _PROJECT_ID,
    "version": "1.0.0",
    "slug": "1.0.0",
    "source": "import",
    "enabled": True,
}
_PATH = {
    "id": _PATH_ID,
    "version_id": _VERSION_ID,
    "tenant_id": _PROJECT["tenant_id"],
    "pathname": "/payments",
    "metadata": {},
    "enabled": True,
    "created_on": "2026-01-01T00:00:00Z",
}
_OPERATION = {
    "id": _OPERATION_ID,
    "version_path_id": _PATH_ID,
    "tenant_id": _PROJECT["tenant_id"],
    "operation": "POST",
    "deprecated": False,
    "metadata": {},
    "enabled": True,
    "created_on": "2026-01-01T00:00:00Z",
    "description": {
        "operation_id": "createPayment",
        "summary": "Create a payment",
        "tags": ["payments"],
    },
}
_WORKFLOW = {
    "id": _WORKFLOW_ID,
    "version_id": _VERSION_ID,
    "tenant_id": _PROJECT["tenant_id"],
    "workflow_id": "createPaymentWorkflow",
    "summary": "Create payment flow",
    "description": None,
    "metadata": {},
    "enabled": True,
    "created_on": "2026-01-01T00:00:00Z",
}
_STEP = {
    "id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
    "version_workflow_id": _WORKFLOW_ID,
    "tenant_id": _PROJECT["tenant_id"],
    "step_id": "createPayment",
    "operation_id": "createPayment",
    "operation_path": None,
    "path_operation_id": _OPERATION_ID,
    "position": 0,
    "metadata": {},
    "enabled": True,
    "created_on": "2026-01-01T00:00:00Z",
}


def _mock_project_version_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/payments-api",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/1.0.0",
        json=_VERSION,
    )


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 commands require an API key."""
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def test_paths_list_human_output(httpx_mock: object) -> None:
    """paths list renders flattened operation rows."""
    _mock_project_version_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}",
        json={"total": 1, "offset": 0, "limit": 50, "items": [_PATH]},
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/operations"
        ),
        json={"total": 1, "offset": 0, "limit": 50, "items": [_OPERATION]},
    )

    result = runner.invoke(
        app,
        [
            "paths",
            "list",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
        ],
    )

    assert result.exit_code == EXIT_SUCCESS
    assert "/payments" in result.stdout
    assert "POST" in result.stdout
    assert "createPayment" in result.stdout


def test_paths_list_json_mode(httpx_mock: object) -> None:
    """paths list --json emits the REST paths list envelope."""
    list_payload = {"total": 1, "items": [_PATH]}
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}",
        json=list_payload,
    )

    result = runner.invoke(
        app,
        [
            "--json",
            "paths",
            "list",
            "--project",
            _PROJECT_ID,
            "--version",
            _VERSION_ID,
        ],
    )

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout.strip())
    assert payload["items"] == [_PATH]


def test_paths_list_passes_method_and_tag_filters(httpx_mock: object) -> None:
    """paths list forwards method and tag filters to the REST API."""
    _mock_project_version_scope(httpx_mock)
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}?method=POST&tag=payments"
        ),
        json={"total": 0, "offset": 0, "limit": 50, "items": []},
    )

    result = runner.invoke(
        app,
        [
            "paths",
            "list",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
            "--method",
            "post",
            "--tag",
            "payments",
        ],
    )

    assert result.exit_code == EXIT_SUCCESS
    assert len(httpx_mock.get_requests()) == 3


def test_paths_show_by_pathname(httpx_mock: object) -> None:
    """paths show resolves a path template and lists operations."""
    _mock_project_version_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}",
        json={"total": 1, "offset": 0, "limit": 50, "items": [_PATH]},
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/operations"
        ),
        json={"total": 1, "offset": 0, "limit": 50, "items": [_OPERATION]},
    )

    result = runner.invoke(
        app,
        [
            "paths",
            "show",
            "/payments",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
        ],
    )

    assert result.exit_code == EXIT_SUCCESS
    assert "createPayment" in result.stdout


def test_paths_show_json_mode(httpx_mock: object) -> None:
    """paths show --json returns path and operations payloads."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}",
        json=_PATH,
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/operations"
        ),
        json={"total": 1, "offset": 0, "limit": 50, "items": [_OPERATION]},
    )

    result = runner.invoke(
        app,
        [
            "--json",
            "paths",
            "show",
            _PATH_ID,
            "--project",
            _PROJECT_ID,
            "--version",
            _VERSION_ID,
        ],
    )

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout.strip())
    assert payload["path"]["id"] == _PATH_ID
    assert payload["operations"]["items"] == [_OPERATION]


def test_operations_show_by_operation_id(httpx_mock: object) -> None:
    """operations show locates an operationId across version paths."""
    _mock_project_version_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}",
        json={"total": 1, "offset": 0, "limit": 50, "items": [_PATH]},
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/operations"
        ),
        json={"total": 1, "offset": 0, "limit": 50, "items": [_OPERATION]},
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/parameters"
        ),
        json={"total": 0, "offset": 0, "limit": 50, "items": []},
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/request-bodies"
        ),
        json={"total": 0, "offset": 0, "limit": 50, "items": []},
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/responses"
        ),
        json={"total": 0, "offset": 0, "limit": 50, "items": []},
    )

    result = runner.invoke(
        app,
        [
            "operations",
            "show",
            "createPayment",
            "--project",
            "payments-api",
            "--version",
            "1.0.0",
        ],
    )

    assert result.exit_code == EXIT_SUCCESS
    assert "createPayment" in result.stdout
    assert "Parameters: 0" in result.stdout


def test_operations_show_json_mode(httpx_mock: object) -> None:
    """operations show --json emits enriched operation detail."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}",
        json={"total": 1, "offset": 0, "limit": 50, "items": [_PATH]},
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/operations"
        ),
        json={"total": 1, "offset": 0, "limit": 50, "items": [_OPERATION]},
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/parameters"
        ),
        json={"total": 0, "offset": 0, "limit": 50, "items": []},
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/request-bodies"
        ),
        json={"total": 0, "offset": 0, "limit": 50, "items": []},
    )
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/paths/acme-corp/{_VERSION_ID}/{_PATH_ID}/responses"
        ),
        json={"total": 0, "offset": 0, "limit": 50, "items": []},
    )

    result = runner.invoke(
        app,
        [
            "--json",
            "operations",
            "show",
            _OPERATION_ID,
            "--project",
            _PROJECT_ID,
            "--version",
            _VERSION_ID,
        ],
    )

    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout.strip())
    assert payload["operation"]["id"] == _OPERATION_ID


def test_workflows_command_removed_from_cli() -> None:
    """Workflows are not registered after /v1 REST alignment."""
    result = runner.invoke(app, ["workflows", "list", "--help"])
    assert result.exit_code != EXIT_SUCCESS


def test_paths_list_missing_project_exits_usage(httpx_mock: object) -> None:
    """Unknown project slug maps to a clear usage error."""
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/missing",
        status_code=404,
        json={"code": 404, "message": "not found"},
    )

    result = runner.invoke(
        app,
        [
            "paths",
            "list",
            "--project",
            "missing",
            "--version",
            "1.0.0",
        ],
    )

    assert result.exit_code == EXIT_USAGE
    assert "404" in result.stderr


def test_paths_list_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier 2 paths commands exit usage without an API key."""
    monkeypatch.delenv("APIOME_API_KEY", raising=False)
    result = runner.invoke(
        app,
        [
            "paths",
            "list",
            "--project",
            _PROJECT_ID,
            "--version",
            _VERSION_ID,
        ],
    )
    assert result.exit_code == EXIT_USAGE
