"""Tests for ``apiome mcp test`` — invoke a cataloged tool (V2-MCP-22.4 / V2-MCP-25.4)."""

from __future__ import annotations

import json

import pytest
import typer
from typer.testing import CliRunner

from apiome_cli.client.mcp_test import (
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_TOOL_ERROR,
    build_test_request,
    classify_test_outcome,
    parse_tool_arguments,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_TENANT_SLUG = "acme"
_ENDPOINT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_TEST_URL = f"http://localhost:8000/v1/mcp/{_TENANT_SLUG}/endpoints/{_ENDPOINT_ID}/test"


def _result(**overrides: object) -> dict[str, object]:
    """A successful ``McpEndpointTestResponse`` payload, with ``overrides`` applied."""
    payload: dict[str, object] = {
        "success": True,
        "endpointId": _ENDPOINT_ID,
        "itemType": "tool",
        "itemName": "get_forecast",
        "method": "tools/call",
        "target": "get_forecast",
        "completed": True,
        "isError": False,
        "content": [{"type": "text", "text": "Sunny, 21C"}],
        "structuredContent": None,
        "latencyMs": 142.4,
        "error": None,
        "authOverrideApplied": False,
        "invocationId": "11111111-1111-4111-8111-111111111111",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """API key + base URL + slug tenant scope (no tenants/me round-trip)."""
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", _TENANT_SLUG)


def _sent_body(httpx_mock: object) -> dict[str, object]:
    request = httpx_mock.get_request(url=_TEST_URL, method="POST")
    return json.loads(request.content)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_parse_tool_arguments_decodes_json_values() -> None:
    args = parse_tool_arguments(None, ["city=Paris", "days=3", "metric=true", 'opts={"a":1}'])
    assert args == {"city": "Paris", "days": 3, "metric": True, "opts": {"a": 1}}


def test_parse_tool_arguments_keeps_quoted_string() -> None:
    assert parse_tool_arguments(None, ['zip="02139"']) == {"zip": "02139"}


def test_parse_tool_arguments_splits_on_first_equals() -> None:
    assert parse_tool_arguments(None, ["q=a=b"]) == {"q": "a=b"}


def test_parse_tool_arguments_merges_args_json_and_overrides() -> None:
    args = parse_tool_arguments('{"city": "Oslo", "days": 1}', ["days=5"])
    assert args == {"city": "Oslo", "days": 5}


def test_parse_tool_arguments_empty() -> None:
    assert parse_tool_arguments(None, None) == {}


@pytest.mark.parametrize("pair", ["novalue", "=x", "  =x"])
def test_parse_tool_arguments_rejects_bad_pair(pair: str) -> None:
    with pytest.raises(typer.BadParameter):
        parse_tool_arguments(None, [pair])


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '"text"'])
def test_parse_tool_arguments_rejects_non_object_args(raw: str) -> None:
    with pytest.raises(typer.BadParameter):
        parse_tool_arguments(raw, None)


def test_build_test_request_shape() -> None:
    body = build_test_request(" get_forecast ", {"a": 1}, confirm=True, call_timeout=10)
    assert body == {
        "item_type": "tool",
        "item_name": "get_forecast",
        "arguments": {"a": 1},
        "confirm": True,
        "timeout_seconds": 10,
    }


def test_build_test_request_omits_default_timeout() -> None:
    body = build_test_request("t", {}, confirm=False, call_timeout=None)
    assert "timeout_seconds" not in body


@pytest.mark.parametrize("bad", [0.5, 121])
def test_build_test_request_rejects_out_of_range_timeout(bad: float) -> None:
    with pytest.raises(typer.BadParameter):
        build_test_request("t", {}, confirm=False, call_timeout=bad)


def test_build_test_request_rejects_blank_tool() -> None:
    with pytest.raises(typer.BadParameter):
        build_test_request("  ", {}, confirm=False, call_timeout=None)


def test_classify_test_outcome() -> None:
    assert classify_test_outcome(_result()) == OUTCOME_OK
    assert classify_test_outcome(_result(isError=True)) == OUTCOME_TOOL_ERROR
    assert classify_test_outcome(_result(completed=False)) == OUTCOME_FAILED


# --------------------------------------------------------------------------- #
# Command
# --------------------------------------------------------------------------- #


def test_mcp_test_requires_api_key() -> None:
    result = runner.invoke(app, ["mcp", "test", _ENDPOINT_ID, "--tool", "t"])
    assert result.exit_code == EXIT_USAGE
    assert "API key required" in strip_ansi(result.stderr)


def test_mcp_test_requires_tool(mcp_env: None) -> None:
    result = runner.invoke(app, ["mcp", "test", _ENDPOINT_ID])
    assert result.exit_code == EXIT_USAGE


def test_mcp_test_rejects_non_uuid(mcp_env: None) -> None:
    result = runner.invoke(app, ["mcp", "test", "not-a-uuid", "--tool", "t"])
    assert result.exit_code == EXIT_USAGE


def test_mcp_test_human_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_TEST_URL,
        method="POST",
        json=_result(),
        match_headers={"X-API-Key": "obj_test_workspace_key"},
    )
    result = runner.invoke(
        app,
        ["mcp", "test", _ENDPOINT_ID, "--tool", "get_forecast", "--arg", "city=Paris"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    output = strip_ansi(result.stdout)
    assert "get_forecast" in output
    assert "tools/call" in output
    assert "142 ms" in output
    assert "ok" in output
    assert "Sunny, 21C" in output
    assert _sent_body(httpx_mock) == {
        "item_type": "tool",
        "item_name": "get_forecast",
        "arguments": {"city": "Paris"},
        "confirm": False,
    }


def test_mcp_test_json_output(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_TEST_URL, method="POST", json=_result())
    result = runner.invoke(
        app, ["mcp", "test", _ENDPOINT_ID, "--tool", "get_forecast", "--output", "json"]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["latencyMs"] == 142.4


def test_mcp_test_global_json_flag(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_TEST_URL, method="POST", json=_result())
    result = runner.invoke(app, ["--json", "mcp", "test", _ENDPOINT_ID, "--tool", "get_forecast"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["itemName"] == "get_forecast"


def test_mcp_test_prints_structured_content(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_TEST_URL,
        method="POST",
        json=_result(content=[{"type": "image", "mimeType": "image/png"}], structuredContent={"t": 21}),
    )
    result = runner.invoke(app, ["mcp", "test", _ENDPOINT_ID, "--tool", "get_forecast"])
    assert result.exit_code == EXIT_SUCCESS
    output = strip_ansi(result.stdout)
    assert '"mimeType": "image/png"' in output
    assert "Structured content:" in output
    assert '"t": 21' in output


def test_mcp_test_confirm_and_timeout_are_sent(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=_TEST_URL, method="POST", json=_result())
    result = runner.invoke(
        app,
        [
            "mcp",
            "test",
            _ENDPOINT_ID,
            "--tool",
            "get_forecast",
            "--args",
            '{"days": 2}',
            "--confirm",
            "--call-timeout",
            "15",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS
    body = _sent_body(httpx_mock)
    assert body["confirm"] is True
    assert body["timeout_seconds"] == 15
    assert body["arguments"] == {"days": 2}


def test_mcp_test_destructive_tool_needs_confirm(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_TEST_URL,
        method="POST",
        status_code=428,
        json={"detail": "'drop_table' is flagged destructiveHint; resend with confirm=true"},
    )
    result = runner.invoke(app, ["mcp", "test", _ENDPOINT_ID, "--tool", "drop_table"])
    assert result.exit_code == EXIT_USAGE
    assert "--confirm" in strip_ansi(result.stderr)


def test_mcp_test_tool_error_exits_non_zero(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_TEST_URL,
        method="POST",
        json=_result(isError=True, content=[{"type": "text", "text": "city not found"}]),
    )
    result = runner.invoke(app, ["mcp", "test", _ENDPOINT_ID, "--tool", "get_forecast"])
    assert result.exit_code == EXIT_ERROR
    output = strip_ansi(result.stdout)
    assert "tool error" in output
    assert "city not found" in output


def test_mcp_test_transport_failure_exits_non_zero(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_TEST_URL,
        method="POST",
        json=_result(
            completed=False,
            content=[],
            error={"code": "timeout", "message": "server did not answer"},
        ),
    )
    result = runner.invoke(app, ["mcp", "test", _ENDPOINT_ID, "--tool", "get_forecast"])
    assert result.exit_code == EXIT_ERROR
    output = strip_ansi(result.stdout)
    assert "failed" in output
    assert "timeout: server did not answer" in output


def test_mcp_test_schema_rejection_is_usage_error(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(
        url=_TEST_URL,
        method="POST",
        status_code=422,
        json={"detail": "arguments do not match the tool's inputSchema: 'city' is a required property"},
    )
    result = runner.invoke(app, ["mcp", "test", _ENDPOINT_ID, "--tool", "get_forecast"])
    assert result.exit_code == EXIT_USAGE
    assert "required property" in strip_ansi(result.stderr)


def test_mcp_test_bad_arg_is_usage_error(mcp_env: None) -> None:
    result = runner.invoke(app, ["mcp", "test", _ENDPOINT_ID, "--tool", "t", "--arg", "oops"])
    assert result.exit_code == EXIT_USAGE
