"""Tests for the ``mcp`` catalog command group (register/list/show)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_TENANT_SLUG = "acme"
_ENDPOINT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_ENDPOINTS_URL = f"http://localhost:8000/v1/mcp/{_TENANT_SLUG}/endpoints"
_ENDPOINT_URL = f"{_ENDPOINTS_URL}/{_ENDPOINT_ID}"
_CREDENTIALS_URL = f"{_ENDPOINT_URL}/credentials"

_ENDPOINT = {
    "id": _ENDPOINT_ID,
    "tenant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "name": "Weather MCP",
    "slug": "weather-mcp",
    "endpoint_url": "https://mcp.example.com/sse",
    "transport": "streamable_http",
    "description": "Weather lookups",
    "category": "tools",
    "visibility": "private",
    "published": False,
    "enabled": True,
    "discovery_cadence_seconds": None,
    "last_discovered_at": "2026-06-20T12:00:00Z",
    "last_discovery_status": "success",
    "consecutive_failures": 0,
    "next_discovery_after": None,
    "quarantined": False,
    "quarantined_at": None,
    "quarantine_reason": None,
    "current_version_id": None,
    "created_at": "2026-06-01T00:00:00Z",
    "updated_at": None,
}

_CREDENTIAL_STATUS = {
    "success": True,
    "credential": {
        "endpoint_id": _ENDPOINT_ID,
        "auth_type": "bearer",
        "configured": True,
        "masked_secret": "****",
        "key_version": 1,
        "oauth_metadata": {},
        "last_refreshed_at": None,
        "created_at": "2026-06-01T00:00:00Z",
        "updated_at": None,
    },
}


@pytest.fixture
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """API key + base URL + slug tenant scope (no tenants/me round-trip)."""
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", _TENANT_SLUG)


@pytest.fixture
def api_key_only_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")


# --------------------------------------------------------------------------- #
# Auth / scope guards
# --------------------------------------------------------------------------- #


def test_mcp_list_requires_api_key() -> None:
    result = runner.invoke(app, ["mcp", "list"])
    assert result.exit_code == EXIT_USAGE
    assert "API key required" in strip_ansi(result.stderr)


def test_mcp_list_requires_tenant_scope(api_key_only_env: None) -> None:
    result = runner.invoke(app, ["mcp", "list"])
    assert result.exit_code == EXIT_USAGE
    assert "Tenant scope required" in strip_ansi(result.stderr)


# --------------------------------------------------------------------------- #
# register
# --------------------------------------------------------------------------- #


def test_mcp_register_human_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="POST",
        status_code=201,
        json={"success": True, "endpoint": _ENDPOINT},
        match_headers={"X-API-Key": "obj_test_workspace_key"},
    )
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Weather MCP" in output
    assert "weather-mcp" in output
    assert "streamable_http" in output

    request = httpx_mock.get_request(url=_ENDPOINTS_URL, method="POST")
    body = json.loads(request.content)
    assert body == {
        "name": "Weather MCP",
        "endpoint_url": "https://mcp.example.com/sse",
        "transport": "streamable_http",
        "visibility": "private",
    }


def test_mcp_register_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="POST",
        status_code=201,
        json={"success": True, "endpoint": _ENDPOINT},
    )
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--transport",
            "sse",
            "--description",
            "Weather lookups",
            "--category",
            "tools",
            "--visibility",
            "public",
            "--slug",
            "weather",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["endpoint"]["id"] == _ENDPOINT_ID

    request = httpx_mock.get_request(url=_ENDPOINTS_URL, method="POST")
    body = json.loads(request.content)
    assert body == {
        "name": "Weather MCP",
        "endpoint_url": "https://mcp.example.com/sse",
        "transport": "sse",
        "visibility": "public",
        "slug": "weather",
        "description": "Weather lookups",
        "category": "tools",
    }


def test_mcp_register_with_bearer_sets_credential(
    httpx_mock: object,
    mcp_env: None,
) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="POST",
        status_code=201,
        json={"success": True, "endpoint": _ENDPOINT},
    )
    httpx_mock.add_response(
        url=_CREDENTIALS_URL,
        method="PUT",
        json=_CREDENTIAL_STATUS,
    )
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--bearer",
            "s3cret-token",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "Credential set (bearer)." in strip_ansi(result.stdout)

    cred_request = httpx_mock.get_request(url=_CREDENTIALS_URL, method="PUT")
    cred_body = json.loads(cred_request.content)
    assert cred_body == {"auth_type": "bearer", "payload": {"token": "s3cret-token"}}


def test_mcp_register_with_header_sets_credential(
    httpx_mock: object,
    mcp_env: None,
) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="POST",
        status_code=201,
        json={"success": True, "endpoint": _ENDPOINT},
    )
    httpx_mock.add_response(
        url=_CREDENTIALS_URL,
        method="PUT",
        json=_CREDENTIAL_STATUS,
    )
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--header",
            "X-Api-Token: abc123",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    cred_request = httpx_mock.get_request(url=_CREDENTIALS_URL, method="PUT")
    cred_body = json.loads(cred_request.content)
    assert cred_body == {
        "auth_type": "header",
        "payload": {"name": "X-Api-Token", "value": "abc123"},
    }


def test_mcp_register_rejects_bearer_and_header_together(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--bearer",
            "tok",
            "--header",
            "X-Api-Token: abc",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "not both" in strip_ansi(result.stderr)


def test_mcp_register_rejects_malformed_header(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--header",
            "no-colon-here",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "Name:Value" in strip_ansi(result.stderr)


def test_mcp_register_rejects_bad_transport(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--transport",
            "carrier-pigeon",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "--transport must be" in strip_ansi(result.stderr)


def test_mcp_register_rejects_bad_visibility(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        [
            "mcp",
            "register",
            "--name",
            "Weather MCP",
            "--url",
            "https://mcp.example.com/sse",
            "--visibility",
            "secret",
        ],
    )
    assert result.exit_code == EXIT_USAGE
    assert "--visibility must be" in strip_ansi(result.stderr)


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def test_mcp_list_human_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="GET",
        json={"success": True, "endpoints": [_ENDPOINT]},
        match_headers={"X-API-Key": "obj_test_workspace_key"},
    )
    result = runner.invoke(app, ["mcp", "list"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Weather MCP" in output
    assert "weather-mcp" in output
    assert "streamable_http" in output
    assert "private" in output


def test_mcp_list_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="GET",
        json={"success": True, "endpoints": [_ENDPOINT]},
    )
    result = runner.invoke(app, ["mcp", "list", "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["endpoints"][0]["id"] == _ENDPOINT_ID


def test_mcp_list_global_json_flag(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="GET",
        json={"success": True, "endpoints": [_ENDPOINT]},
    )
    result = runner.invoke(app, ["--json", "mcp", "list"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["endpoints"][0]["name"] == "Weather MCP"


def test_mcp_list_empty(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINTS_URL,
        method="GET",
        json={"success": True, "endpoints": []},
    )
    result = runner.invoke(app, ["mcp", "list"])
    assert result.exit_code == EXIT_SUCCESS
    assert "No MCP endpoints." in strip_ansi(result.stdout)


# --------------------------------------------------------------------------- #
# show
# --------------------------------------------------------------------------- #


def test_mcp_show_human_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINT_URL,
        method="GET",
        json={"success": True, "endpoint": _ENDPOINT},
    )
    result = runner.invoke(app, ["mcp", "show", _ENDPOINT_ID])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Weather MCP" in output
    assert "https://mcp.example.com/sse" in output
    assert "success" in output


def test_mcp_show_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINT_URL,
        method="GET",
        json={"success": True, "endpoint": _ENDPOINT},
    )
    result = runner.invoke(app, ["mcp", "show", _ENDPOINT_ID, "--output", "json"])
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["endpoint"]["slug"] == "weather-mcp"


def test_mcp_show_not_found(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINT_URL,
        method="GET",
        status_code=404,
        json={"detail": "MCP endpoint not found"},
    )
    result = runner.invoke(app, ["mcp", "show", _ENDPOINT_ID])
    assert result.exit_code == EXIT_USAGE


def test_mcp_show_rejects_non_uuid(mcp_env: None) -> None:
    result = runner.invoke(app, ["mcp", "show", "not-a-uuid"])
    assert result.exit_code == EXIT_USAGE


# --------------------------------------------------------------------------- #
# discover + poll (V2-MCP-25.2)
# --------------------------------------------------------------------------- #

_JOB_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_VERSION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_DISCOVER_URL = f"{_ENDPOINT_URL}/discover"
_JOB_URL = f"{_ENDPOINT_URL}/jobs/{_JOB_ID}"
_LINT_URL = f"{_ENDPOINT_URL}/versions/{_VERSION_ID}/lint"

_QUEUED_JOB = {
    "id": _JOB_ID,
    "endpoint_id": _ENDPOINT_ID,
    "tenant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "state": "queued",
    "trigger": "manual",
    "terminal": False,
    "result": {},
}


def _status(state: str, **extra: object) -> dict[str, object]:
    """Build a discovery-job status snapshot envelope for a poll response."""
    job: dict[str, object] = {
        "job_id": _JOB_ID,
        "endpoint_id": _ENDPOINT_ID,
        "tenant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "state": state,
        "trigger": "manual",
        "terminal": state in ("completed", "failed"),
        "result": {},
    }
    job.update(extra)
    return {"success": True, "job": job}


def test_mcp_discover_requires_api_key() -> None:
    result = runner.invoke(app, ["mcp", "discover", _ENDPOINT_ID])
    assert result.exit_code == EXIT_USAGE
    assert "API key required" in strip_ansi(result.stderr)


def test_mcp_discover_rejects_non_uuid(mcp_env: None) -> None:
    result = runner.invoke(app, ["mcp", "discover", "not-a-uuid"])
    assert result.exit_code == EXIT_USAGE


def test_mcp_discover_no_wait_prints_job(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_DISCOVER_URL,
        method="POST",
        status_code=202,
        json={"success": True, "deduplicated": False, "job": _QUEUED_JOB},
    )
    result = runner.invoke(app, ["mcp", "discover", _ENDPOINT_ID, "--no-wait"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Discovery enqueued." in output
    assert _JOB_ID in output
    assert "queued" in output


def test_mcp_discover_no_wait_dedup_note(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_DISCOVER_URL,
        method="POST",
        status_code=202,
        json={"success": True, "deduplicated": True, "job": _QUEUED_JOB},
    )
    result = runner.invoke(app, ["mcp", "discover", _ENDPOINT_ID, "--no-wait"])
    assert result.exit_code == EXIT_SUCCESS
    assert "deduplicated" in strip_ansi(result.stdout)


def test_mcp_discover_waits_and_prints_version_and_score(
    httpx_mock: object,
    mcp_env: None,
) -> None:
    httpx_mock.add_response(
        url=_DISCOVER_URL,
        method="POST",
        status_code=202,
        json={"success": True, "deduplicated": False, "job": _QUEUED_JOB},
    )
    httpx_mock.add_response(url=_JOB_URL, method="GET", json=_status("running"))
    httpx_mock.add_response(
        url=_JOB_URL,
        method="GET",
        json=_status(
            "completed",
            version_id=_VERSION_ID,
            changed=True,
            duration_ms=1234,
            result={
                "version_id": _VERSION_ID,
                "version_seq": 2,
                "version_tag": "2026-06-28",
                "changed": True,
                "change_count": 3,
            },
        ),
    )
    httpx_mock.add_response(
        url=_LINT_URL,
        method="GET",
        json={"success": True, "score": 87, "grade": "B"},
    )
    result = runner.invoke(
        app,
        ["mcp", "discover", _ENDPOINT_ID, "--poll-interval", "0.1"],
    )
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Discovery completed." in output
    assert _VERSION_ID in output
    assert "seq 2" in output
    assert "Changed: yes (3 changes)" in output
    assert "Score: 87 (grade B)" in output


def test_mcp_discover_unchanged_surface(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_DISCOVER_URL,
        method="POST",
        status_code=202,
        json={"success": True, "deduplicated": False, "job": _QUEUED_JOB},
    )
    httpx_mock.add_response(
        url=_JOB_URL,
        method="GET",
        json=_status(
            "completed",
            version_id=_VERSION_ID,
            changed=False,
            result={"version_id": _VERSION_ID, "version_seq": 1, "changed": False},
        ),
    )
    # Best-effort score read returns 404 (never scored) — must not fail the command.
    httpx_mock.add_response(url=_LINT_URL, method="GET", status_code=404, json={})
    result = runner.invoke(
        app,
        ["mcp", "discover", _ENDPOINT_ID, "--poll-interval", "0.1"],
    )
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Changed: no (surface unchanged)" in output
    assert "Score:" not in output


def test_mcp_discover_failed_job_exits_error(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_DISCOVER_URL,
        method="POST",
        status_code=202,
        json={"success": True, "deduplicated": False, "job": _QUEUED_JOB},
    )
    httpx_mock.add_response(
        url=_JOB_URL,
        method="GET",
        json=_status(
            "failed",
            error="handshake refused",
            error_detail={"code": "HANDSHAKE_FAILED"},
        ),
    )
    result = runner.invoke(
        app,
        ["mcp", "discover", _ENDPOINT_ID, "--poll-interval", "0.1"],
    )
    assert result.exit_code == 1
    assert "Discovery failed: handshake refused" in strip_ansi(result.stderr)


def test_mcp_discover_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_DISCOVER_URL,
        method="POST",
        status_code=202,
        json={"success": True, "deduplicated": False, "job": _QUEUED_JOB},
    )
    httpx_mock.add_response(
        url=_JOB_URL,
        method="GET",
        json=_status(
            "completed",
            version_id=_VERSION_ID,
            changed=True,
            result={"version_id": _VERSION_ID, "version_seq": 2, "changed": True},
        ),
    )
    httpx_mock.add_response(
        url=_LINT_URL,
        method="GET",
        json={"success": True, "score": 90, "grade": "A"},
    )
    result = runner.invoke(
        app,
        ["mcp", "discover", _ENDPOINT_ID, "--poll-interval", "0.1", "--output", "json"],
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["deduplicated"] is False
    assert payload["job"]["version_id"] == _VERSION_ID
    assert payload["lint"]["score"] == 90


# --------------------------------------------------------------------------- #
# lint + score (V2-MCP-25.3)
# --------------------------------------------------------------------------- #

# Mirrors the camelCase ``McpLintReportResponse`` wire shape (serialization aliases).
_LINT_REPORT = {
    "success": True,
    "endpointId": _ENDPOINT_ID,
    "versionId": _VERSION_ID,
    "versionSeq": 2,
    "versionTag": "2026-06-28",
    "score": 82,
    "grade": "B",
    "findings": [
        {
            "id": "f1",
            "path": "tools/get_weather",
            "category": "documentation",
            "rule": "tool-missing-description",
            "severity": "warning",
            "message": "Tool has no description.",
        },
        {
            "id": "f2",
            "path": "tools/get_weather/inputSchema",
            "category": "schema",
            "rule": "param-untyped",
            "severity": "info",
            "message": "Parameter 'city' has no type.",
        },
    ],
    "ruleHits": {"tool-missing-description": 1, "param-untyped": 1},
    "severityCounts": {"error": 0, "warning": 1, "info": 1},
    "reportFingerprint": "deadbeef",
    "source": "stored",
    "scoredAt": "2026-06-28T00:00:00Z",
}


def _endpoint_with_current(version_id: str | None) -> dict[str, object]:
    """Clone the endpoint fixture with a chosen ``current_version_id``."""
    return {**_ENDPOINT, "current_version_id": version_id}


def test_mcp_lint_requires_api_key() -> None:
    result = runner.invoke(app, ["mcp", "lint", _ENDPOINT_ID])
    assert result.exit_code == EXIT_USAGE
    assert "API key required" in strip_ansi(result.stderr)


def test_mcp_lint_rejects_non_uuid(mcp_env: None) -> None:
    result = runner.invoke(app, ["mcp", "lint", "not-a-uuid"])
    assert result.exit_code == EXIT_USAGE


def test_mcp_lint_explicit_version_human_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_LINT_URL, method="GET", json=_LINT_REPORT)
    result = runner.invoke(app, ["mcp", "lint", _ENDPOINT_ID, "--version", _VERSION_ID])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert "Quality score: 82/100  (grade B)" in output
    assert "1 warning" in output
    assert "tool-missing-description" in output
    assert "param-untyped" in output


def test_mcp_lint_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_LINT_URL, method="GET", json=_LINT_REPORT)
    result = runner.invoke(
        app,
        ["mcp", "lint", _ENDPOINT_ID, "--version", _VERSION_ID, "--output", "json"],
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["score"] == 82
    assert payload["grade"] == "B"
    assert payload["source"] == "stored"


def test_mcp_lint_resolves_current_version(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINT_URL,
        method="GET",
        json={"success": True, "endpoint": _endpoint_with_current(_VERSION_ID)},
    )
    httpx_mock.add_response(url=_LINT_URL, method="GET", json=_LINT_REPORT)
    result = runner.invoke(app, ["mcp", "lint", _ENDPOINT_ID])
    assert result.exit_code == EXIT_SUCCESS
    assert "Quality score: 82/100" in strip_ansi(result.stdout)


def test_mcp_lint_no_current_version_errors(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_ENDPOINT_URL,
        method="GET",
        json={"success": True, "endpoint": _endpoint_with_current(None)},
    )
    result = runner.invoke(app, ["mcp", "lint", _ENDPOINT_ID])
    assert result.exit_code == 1
    assert "no current version" in strip_ansi(result.stderr)


def test_mcp_lint_min_grade_gate_fails(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_LINT_URL,
        method="GET",
        json={**_LINT_REPORT, "grade": "C", "score": 71},
    )
    result = runner.invoke(
        app,
        ["mcp", "lint", _ENDPOINT_ID, "--version", _VERSION_ID, "--min-grade", "B"],
    )
    assert result.exit_code == 1
    # The report is still printed before the gate trips.
    assert "Quality score: 71/100  (grade C)" in strip_ansi(result.stdout)


def test_mcp_lint_min_grade_gate_passes(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_LINT_URL,
        method="GET",
        json={**_LINT_REPORT, "grade": "A", "score": 95},
    )
    result = runner.invoke(
        app,
        ["mcp", "lint", _ENDPOINT_ID, "--version", _VERSION_ID, "--min-grade", "B"],
    )
    assert result.exit_code == EXIT_SUCCESS


def test_mcp_lint_rejects_bad_min_grade(mcp_env: None) -> None:
    result = runner.invoke(
        app,
        ["mcp", "lint", _ENDPOINT_ID, "--version", _VERSION_ID, "--min-grade", "Z"],
    )
    assert result.exit_code == EXIT_USAGE
    assert "A, B, C, D, F" in strip_ansi(result.stderr)


def test_mcp_lint_global_json_flag(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_LINT_URL, method="GET", json=_LINT_REPORT)
    result = runner.invoke(
        app,
        ["--json", "mcp", "lint", _ENDPOINT_ID, "--version", _VERSION_ID],
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["versionId"] == _VERSION_ID
