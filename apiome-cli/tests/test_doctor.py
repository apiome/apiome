"""Tests for the `doctor` connectivity probe command."""

from __future__ import annotations

import os

import httpx
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

# Base URL used by conftest fixture (no real .env present in CI)
_BASE_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_doctor_prints_ok_and_base_url(httpx_mock: object) -> None:
    """Successful GET /health prints 'OK: <base_url>' and exits 0."""
    httpx_mock.add_response(
        url=f"{_BASE_URL}/health",
        json={"status": "ok"},
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == EXIT_SUCCESS
    assert f"OK: {_BASE_URL}" in result.stdout


def test_doctor_base_url_in_output_matches_configured_url(httpx_mock: object) -> None:
    """The base URL printed reflects --base-url when overridden."""
    custom = "http://api.example.com:9000"
    httpx_mock.add_response(
        url=f"{custom}/health",
        json={"status": "ok"},
    )
    env = {k: v for k, v in os.environ.items() if k not in {"APIOME_BASE_URL", "APIOME_API_KEY"}}
    result = runner.invoke(app, ["--base-url", custom, "doctor"], env=env)
    assert result.exit_code == EXIT_SUCCESS
    assert f"OK: {custom}" in result.stdout


def test_doctor_success_does_not_print_json_body(httpx_mock: object) -> None:
    """Doctor output is a short status line, not the raw JSON response body."""
    httpx_mock.add_response(
        url=f"{_BASE_URL}/health",
        json={"status": "ok", "database": "connected"},
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == EXIT_SUCCESS
    assert "database" not in result.stdout
    assert '"status"' not in result.stdout


# ---------------------------------------------------------------------------
# Authentication – doctor must NOT send API key
# ---------------------------------------------------------------------------


def test_doctor_does_not_send_api_key_header(httpx_mock: object) -> None:
    """doctor sends no X-API-Key even when one is configured via --api-key."""
    httpx_mock.add_response(
        url=f"{_BASE_URL}/health",
        json={"status": "ok"},
    )
    env = {k: v for k, v in os.environ.items() if k not in {"APIOME_BASE_URL", "APIOME_API_KEY"}}
    env["APIOME_BASE_URL"] = _BASE_URL
    result = runner.invoke(app, ["--api-key", "secret-key", "doctor"], env=env)
    assert result.exit_code == EXIT_SUCCESS
    # X-API-Key must NOT appear in the request headers
    request = httpx_mock.get_requests()[0]
    assert "x-api-key" not in {h.lower() for h in request.headers}


def test_doctor_does_not_send_api_key_from_env(httpx_mock: object) -> None:
    """doctor sends no X-API-Key even when APIOME_API_KEY env var is set."""
    httpx_mock.add_response(
        url=f"{_BASE_URL}/health",
        json={"status": "ok"},
    )
    env = {k: v for k, v in os.environ.items() if k not in {"APIOME_BASE_URL", "APIOME_API_KEY"}}
    env["APIOME_BASE_URL"] = _BASE_URL
    env["APIOME_API_KEY"] = "env-secret"
    result = runner.invoke(app, ["doctor"], env=env)
    assert result.exit_code == EXIT_SUCCESS
    request = httpx_mock.get_requests()[0]
    assert "x-api-key" not in {h.lower() for h in request.headers}


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_doctor_exits_error_on_503(httpx_mock: object) -> None:
    """HTTP 503 exits 1 and writes a message to stderr."""
    httpx_mock.add_response(
        url=f"{_BASE_URL}/health",
        status_code=503,
        json={"code": 503, "message": "Service Unavailable"},
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == EXIT_ERROR
    assert result.stderr  # some diagnostic message must be present
    assert "OK:" not in result.stdout


def test_doctor_exits_usage_on_4xx(httpx_mock: object) -> None:
    """HTTP 4xx exits EXIT_USAGE (2) per clig.dev conventions."""
    httpx_mock.add_response(
        url=f"{_BASE_URL}/health",
        status_code=404,
        text="not found",
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == EXIT_USAGE
    assert "OK:" not in result.stdout


def test_doctor_exits_error_on_connection_failure(httpx_mock: object) -> None:
    """Transport-level error exits 1 with a diagnostic on stderr."""
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == EXIT_ERROR
    assert result.stderr
    assert "OK:" not in result.stdout


def test_doctor_stderr_message_on_503(httpx_mock: object) -> None:
    """503 response produces a human-readable message on stderr."""
    httpx_mock.add_response(
        url=f"{_BASE_URL}/health",
        status_code=503,
        json={"code": 503, "message": "Service Unavailable"},
    )
    result = runner.invoke(app, ["doctor"])
    assert "Service Unavailable" in result.stderr or "503" in result.stderr


def test_doctor_stderr_message_on_connection_error(httpx_mock: object) -> None:
    """Connection error produces a human-readable message on stderr."""
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    result = runner.invoke(app, ["doctor"])
    assert "Connection error" in result.stderr or "refused" in result.stderr


# ---------------------------------------------------------------------------
# --insecure flag
# ---------------------------------------------------------------------------


def test_doctor_insecure_flag_accepted(httpx_mock: object) -> None:
    """doctor honours the root --insecure flag (no TLS error in test env)."""
    httpx_mock.add_response(
        url=f"{_BASE_URL}/health",
        json={"status": "ok"},
    )
    result = runner.invoke(app, ["--insecure", "doctor"])
    assert result.exit_code == EXIT_SUCCESS
    assert f"OK: {_BASE_URL}" in result.stdout


# ---------------------------------------------------------------------------
# --timeout flag
# ---------------------------------------------------------------------------


def test_doctor_timeout_flag_propagates(httpx_mock: object) -> None:
    """--timeout value is forwarded to the HTTP client without error."""
    httpx_mock.add_response(
        url=f"{_BASE_URL}/health",
        json={"status": "ok"},
    )
    result = runner.invoke(app, ["--timeout", "5.0", "doctor"])
    assert result.exit_code == EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_doctor_help_exits_zero() -> None:
    """doctor --help exits 0 and documents the purpose."""
    for args in (["doctor", "--help"], ["doctor", "-h"]):
        result = runner.invoke(app, args)
        assert result.exit_code == EXIT_SUCCESS
        assert "health" in result.stdout.lower() or "doctor" in result.stdout.lower()


def test_doctor_appears_in_root_help() -> None:
    """doctor is listed as a subcommand in root --help."""
    result = runner.invoke(app, ["--help"], env={"COLUMNS": "200", "LINES": "200"})
    assert result.exit_code == EXIT_SUCCESS
    assert "doctor" in result.stdout
