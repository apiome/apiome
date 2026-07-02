"""Unit tests for REST error formatting."""

from __future__ import annotations

import httpx
import pytest
import typer
from typer.testing import CliRunner

from apiome_cli.client.errors import (
    CliError,
    format_api_error,
    format_connection_error,
    format_unhandled_error,
    handle_cli_failure,
    http_exit_code,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE

runner = CliRunner()


def test_format_api_error_from_json_body() -> None:
    """Structured REST errors include code and message."""
    response = httpx.Response(
        422,
        json={"code": 422, "message": "Validation failed", "details": {}},
        request=httpx.Request("GET", "http://localhost/health"),
    )
    assert format_api_error(response) == "HTTP 422: Validation failed"


def test_format_api_error_session_auth_includes_hint() -> None:
    """401 session-only routes explain API key vs session bearer usage."""
    response = httpx.Response(
        401,
        json={"code": 401, "message": "Session token required"},
        request=httpx.Request("GET", "http://localhost/dashboard/api-keys"),
    )
    result = format_api_error(response)
    assert result.startswith("HTTP 401: Session token required")
    assert "APIOME_API_KEY" in result
    assert "APIOME_SESSION_TOKEN" in result


def test_format_api_error_version_lookup_details() -> None:
    """404 version lookup payloads show project and version identifiers."""
    response = httpx.Response(
        404,
        json={
            "code": 404,
            "message": "Project version not found",
            "details": {
                "project_slug": "control-api-v1",
                "version": "1.0.14",
                "version_slug": "1.0.14",
            },
        },
        request=httpx.Request("POST", "http://localhost/imports/openapi"),
    )
    result = format_api_error(response)
    assert "HTTP 404: Project version not found" in result
    assert "project slug 'control-api-v1'" in result
    assert "version '1.0.14'" in result
    assert "version slug '1.0.14'" in result


def test_format_api_error_from_plain_text() -> None:
    """Non-JSON bodies fall back to status and text."""
    response = httpx.Response(
        500,
        text="internal error",
        request=httpx.Request("GET", "http://localhost/health"),
    )
    assert format_api_error(response) == "HTTP 500: internal error"


def test_format_api_error_includes_validation_details_for_4xx() -> None:
    """4xx responses append structured validation detail lines."""
    response = httpx.Response(
        422,
        json={
            "code": 422,
            "message": "Validation error",
            "details": [
                {
                    "type": "missing",
                    "loc": ["body", "name"],
                    "msg": "Field required",
                },
            ],
        },
        request=httpx.Request("POST", "http://localhost/tenants"),
    )
    assert format_api_error(response) == (
        "HTTP 422: Validation error\n  name: Field required"
    )


def test_format_api_error_includes_import_message_details_for_4xx() -> None:
    """Import validation envelopes use ImportMessage code/message/path fields."""
    response = httpx.Response(
        422,
        json={
            "code": 422,
            "message": "OpenAPI import validation failed",
            "details": [
                {
                    "code": "invalid_openapi",
                    "message": (
                        "At /: 'parameters' does not match any of the regexes: '^x-'"
                    ),
                    "path": "/",
                },
            ],
        },
        request=httpx.Request("POST", "http://localhost/imports/openapi"),
    )
    assert format_api_error(response) == (
        "HTTP 422: OpenAPI import validation failed\n"
        "  [invalid_openapi] At /: 'parameters' does not match any of the "
        "regexes: '^x-' at /"
    )


def test_format_api_error_omits_details_for_5xx() -> None:
    """5xx responses keep the top-level message without client detail noise."""
    response = httpx.Response(
        500,
        json={
            "code": 500,
            "message": "Internal Server Error",
            "details": {"trace_id": "abc"},
        },
        request=httpx.Request("GET", "http://localhost/health"),
    )
    assert format_api_error(response) == "HTTP 500: Internal Server Error"


def test_format_connection_error_is_concise() -> None:
    """Transport failures use a single-line message."""
    exc = httpx.ConnectError("connection refused", request=httpx.Request("GET", "http://x"))
    assert format_connection_error(exc) == "Connection error: connection refused"


def test_format_unhandled_error_is_concise() -> None:
    """Unexpected failures use a single-line message."""
    assert format_unhandled_error(RuntimeError("boom")) == "Error: boom"


def test_handle_cli_failure_exits_without_traceback() -> None:
    """Non-verbose failures exit with a concise stderr message."""
    with pytest.raises(typer.Exit) as exit_info:
        handle_cli_failure(RuntimeError("boom"), verbose=False)
    assert exit_info.value.exit_code == EXIT_ERROR


def test_handle_cli_failure_reraises_when_verbose() -> None:
    """Verbose mode re-raises for full traceback rendering."""
    with pytest.raises(RuntimeError, match="boom"):
        handle_cli_failure(RuntimeError("boom"), verbose=True)


def test_health_api_failure_has_no_traceback(httpx_mock: object) -> None:
    """HTTP 4xx failures exit with EXIT_USAGE and do not print Python tracebacks."""
    from apiome_cli.main import app

    httpx_mock.add_response(
        url="http://localhost:8000/health",
        status_code=422,
        json={
            "code": 422,
            "message": "Validation error",
            "details": [{"type": "value_error", "loc": ["query", "x"], "msg": "bad"}],
        },
    )
    result = runner.invoke(app, ["health"])
    assert result.exit_code == EXIT_USAGE
    assert "Validation error" in result.stderr
    assert "Traceback" not in result.stderr + result.stdout


def test_health_connection_error_has_no_traceback(httpx_mock: object) -> None:
    """Transport failures do not print Python tracebacks by default."""
    from apiome_cli.main import app

    httpx_mock.add_exception(httpx.ConnectError("connection refused"))
    result = runner.invoke(app, ["health"])
    assert result.exit_code == EXIT_ERROR
    assert "Connection error:" in result.stderr
    assert "Traceback" not in result.stderr + result.stdout


# ---------------------------------------------------------------------------
# CliError
# ---------------------------------------------------------------------------


def test_cli_error_stores_message_and_exit_code() -> None:
    """CliError holds the provided message and exit code."""
    err = CliError(message="bad request", exit_code=EXIT_USAGE)
    assert err.message == "bad request"
    assert err.exit_code == EXIT_USAGE


def test_cli_error_default_exit_code_is_error() -> None:
    """CliError uses EXIT_ERROR when no exit_code is supplied."""
    err = CliError(message="something went wrong")
    assert err.exit_code == EXIT_ERROR


def test_cli_error_str_returns_message() -> None:
    """str(CliError) is the human-readable message."""
    err = CliError(message="oops", exit_code=EXIT_ERROR)
    assert str(err) == "oops"


def test_cli_error_is_exception() -> None:
    """CliError is an Exception subclass and can be raised/caught."""
    with pytest.raises(CliError, match="boom"):
        raise CliError(message="boom", exit_code=EXIT_ERROR)


# ---------------------------------------------------------------------------
# http_exit_code
# ---------------------------------------------------------------------------


def test_http_exit_code_422_is_usage() -> None:
    """422 Unprocessable Entity maps to EXIT_USAGE (client input error)."""
    assert http_exit_code(422) == EXIT_USAGE


def test_http_exit_code_400_is_usage() -> None:
    """400 Bad Request maps to EXIT_USAGE."""
    assert http_exit_code(400) == EXIT_USAGE


def test_http_exit_code_404_is_usage() -> None:
    """404 Not Found maps to EXIT_USAGE."""
    assert http_exit_code(404) == EXIT_USAGE


def test_http_exit_code_499_is_usage() -> None:
    """Top boundary of 4xx range still maps to EXIT_USAGE."""
    assert http_exit_code(499) == EXIT_USAGE


def test_http_exit_code_500_is_error() -> None:
    """500 Internal Server Error maps to EXIT_ERROR."""
    assert http_exit_code(500) == EXIT_ERROR


def test_http_exit_code_503_is_error() -> None:
    """503 Service Unavailable maps to EXIT_ERROR."""
    assert http_exit_code(503) == EXIT_ERROR


def test_http_exit_code_200_is_error() -> None:
    """200 is outside error range; falls back to EXIT_ERROR."""
    assert http_exit_code(200) == EXIT_ERROR


# ---------------------------------------------------------------------------
# format_api_error — 503 hint
# ---------------------------------------------------------------------------


def test_format_api_error_503_with_json_body_includes_hint() -> None:
    """503 with a JSON message body appends the service-unavailable hint."""
    response = httpx.Response(
        503,
        json={"code": 503, "message": "Service Unavailable"},
        request=httpx.Request("GET", "http://localhost/health"),
    )
    result = format_api_error(response)
    assert "Service Unavailable" in result
    assert "temporarily unavailable" in result


def test_format_api_error_503_plain_text_includes_hint() -> None:
    """503 with plain-text body also appends the service-unavailable hint."""
    response = httpx.Response(
        503,
        text="service down",
        request=httpx.Request("GET", "http://localhost/health"),
    )
    result = format_api_error(response)
    assert "service down" in result
    assert "temporarily unavailable" in result


def test_format_api_error_503_without_message_key_includes_hint() -> None:
    """503 JSON payload without a 'message' key still appends the hint."""
    response = httpx.Response(
        503,
        json={"status": "error"},
        request=httpx.Request("GET", "http://localhost/health"),
    )
    result = format_api_error(response)
    assert "temporarily unavailable" in result


def test_format_api_error_non_503_5xx_no_hint() -> None:
    """Non-503 5xx responses do not include the service-unavailable hint."""
    response = httpx.Response(
        500,
        json={"code": 500, "message": "Internal Server Error"},
        request=httpx.Request("GET", "http://localhost/health"),
    )
    result = format_api_error(response)
    assert "temporarily unavailable" not in result


# ---------------------------------------------------------------------------
# exit_on_api_error — differentiated exit codes end-to-end
# ---------------------------------------------------------------------------


def test_422_response_exits_with_usage_code(httpx_mock: object) -> None:
    """422 API response exits with EXIT_USAGE (2)."""
    from apiome_cli.main import app

    httpx_mock.add_response(
        url="http://localhost:8000/health",
        status_code=422,
        json={
            "code": 422,
            "message": "Validation failed",
            "details": [{"type": "missing", "loc": ["body", "name"], "msg": "Field required"}],
        },
    )
    result = runner.invoke(app, ["health"])
    assert result.exit_code == EXIT_USAGE
    assert "name: Field required" in result.stderr


def test_503_response_exits_with_error_code(httpx_mock: object) -> None:
    """503 API response exits with EXIT_ERROR (1) and includes the hint."""
    from apiome_cli.main import app

    httpx_mock.add_response(
        url="http://localhost:8000/health",
        status_code=503,
        json={"code": 503, "message": "Service Unavailable"},
    )
    result = runner.invoke(app, ["health"])
    assert result.exit_code == EXIT_ERROR
    assert "Service Unavailable" in result.stderr
    assert "temporarily unavailable" in result.stderr
