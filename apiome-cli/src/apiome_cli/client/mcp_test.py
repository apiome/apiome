"""Helpers for ``apiome mcp test`` — the MCP test-harness command (V2-MCP-22.4 / 25.4).

The command calls ``POST /v1/mcp/{tenant}/endpoints/{id}/test`` (MCAT-8.2), which invokes one
discovered tool against the live server with the endpoint's stored credential. This module keeps
the pure pieces out of the Typer command so they can be unit-tested on their own:

* :func:`parse_tool_arguments` — turn ``--args`` JSON and repeated ``--arg key=value`` flags into
  the ``arguments`` object;
* :func:`build_test_request` — the request body;
* :func:`classify_test_outcome` / :func:`emit_test_result` — classify and print the response.
"""

from __future__ import annotations

import json
from typing import Any

import typer

from apiome_cli.output import RecordField, emit_json, emit_record_table

#: The REST bounds on ``timeout_seconds`` (``McpEndpointTestRequest``), validated locally.
MIN_CALL_TIMEOUT_SECONDS = 1.0
MAX_CALL_TIMEOUT_SECONDS = 120.0

#: HTTP status the harness returns when a destructive / open-world tool was sent without confirm.
CONFIRM_REQUIRED_STATUS = 428

#: Outcome labels, keyed by how the call ended (see :func:`classify_test_outcome`).
OUTCOME_OK = "ok"
OUTCOME_TOOL_ERROR = "tool error"
OUTCOME_FAILED = "failed"


def _parse_arg_value(raw: str) -> Any:
    """Decode one ``--arg`` value: JSON when it parses (numbers, booleans, objects), else text.

    ``--arg limit=5`` sends the number ``5`` and ``--arg city=Paris`` the string ``"Paris"``.
    Quote a JSON string to force text: ``--arg zip='"02139"'`` sends ``"02139"``.

    Args:
        raw: The text after the first ``=``.

    Returns:
        The decoded JSON value, or ``raw`` unchanged when it is not valid JSON.
    """
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def parse_tool_arguments(args_json: str | None, pairs: list[str] | None) -> dict[str, Any]:
    """Build the tool's ``arguments`` object from ``--args`` and ``--arg`` flags.

    ``--args`` supplies a whole JSON object (for nested values); each ``--arg key=value`` then
    sets or overrides one top-level key, so the two can be combined.

    Args:
        args_json: The ``--args`` JSON text, or ``None``.
        pairs: The repeated ``--arg key=value`` values, or ``None``.

    Returns:
        The merged arguments object (empty when neither flag was given).

    Raises:
        typer.BadParameter: ``--args`` is not a JSON object, or an ``--arg`` has no ``=`` or an
            empty key.
    """
    arguments: dict[str, Any] = {}
    if args_json is not None:
        try:
            decoded = json.loads(args_json)
        except ValueError as exc:
            raise typer.BadParameter(f"not valid JSON ({exc.msg})", param_hint="--args") from None
        if not isinstance(decoded, dict):
            raise typer.BadParameter("must be a JSON object", param_hint="--args")
        arguments.update(decoded)
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise typer.BadParameter(
                f"{pair!r} must be key=value with a non-empty key",
                param_hint="--arg",
            )
        arguments[key.strip()] = _parse_arg_value(value)
    return arguments


def build_test_request(
    tool: str,
    arguments: dict[str, Any],
    *,
    confirm: bool,
    call_timeout: float | None,
) -> dict[str, Any]:
    """Build the ``POST …/test`` body for a tool call.

    Args:
        tool: The discovered tool name (``item_name``).
        arguments: The tool arguments (validated server-side against its ``inputSchema``).
        confirm: Whether the caller acknowledged a destructive / open-world tool.
        call_timeout: Per-request timeout in seconds, or ``None`` for the server default (30s).

    Returns:
        The JSON request body.

    Raises:
        typer.BadParameter: ``tool`` is blank or ``call_timeout`` is outside 1-120 seconds.
    """
    name = tool.strip()
    if not name:
        raise typer.BadParameter("must not be empty", param_hint="--tool")
    body: dict[str, Any] = {
        "item_type": "tool",
        "item_name": name,
        "arguments": arguments,
        "confirm": confirm,
    }
    if call_timeout is not None:
        if not MIN_CALL_TIMEOUT_SECONDS <= call_timeout <= MAX_CALL_TIMEOUT_SECONDS:
            raise typer.BadParameter(
                "must be between 1 and 120 seconds",
                param_hint="--call-timeout",
            )
        body["timeout_seconds"] = call_timeout
    return body


def classify_test_outcome(result: dict[str, Any]) -> str:
    """Classify a harness response into one of the three outcomes.

    Args:
        result: The ``McpEndpointTestResponse`` payload.

    Returns:
        :data:`OUTCOME_OK` (the tool ran and succeeded), :data:`OUTCOME_TOOL_ERROR` (the tool ran
        and reported ``isError``) or :data:`OUTCOME_FAILED` (transport / JSON-RPC failure).
    """
    if not result.get("completed"):
        return OUTCOME_FAILED
    return OUTCOME_TOOL_ERROR if result.get("isError") else OUTCOME_OK


def _format_latency(value: object) -> str:
    """Render ``latencyMs`` as a whole number of milliseconds (``"142 ms"``)."""
    if isinstance(value, (int, float)):
        return f"{round(value)} ms"
    return ""


def _format_error(value: object) -> str:
    """Render the classified ``error`` object as ``code: message`` (blank when absent)."""
    if not isinstance(value, dict):
        return ""
    code = value.get("code")
    message = value.get("message") or ""
    return f"{code}: {message}" if code and message else str(code or message)


_TEST_FIELDS: tuple[RecordField, ...] = (
    ("Tool", "itemName", None),
    ("Method", "method", None),
    ("Outcome", "outcome", None),
    ("Latency", "latencyMs", _format_latency),
    ("isError", "isError", None),
    ("Error", "error", _format_error),
    ("Invocation", "invocationId", lambda value: "" if value is None else str(value)),
)


def _content_text(item: object) -> str:
    """Render one returned content item: its text for ``type: text``, otherwise pretty JSON."""
    if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
        return item["text"]
    return json.dumps(item, indent=2, sort_keys=True)


def emit_test_result(result: dict[str, Any], *, json_mode: bool) -> None:
    """Print a harness response: the summary table, then the tool's content.

    In JSON mode the raw response is printed unchanged. Otherwise a field table (tool, method,
    outcome, latency, ``isError``, error, invocation id) is followed by each content item — text
    items verbatim, anything else as JSON — and the ``structuredContent`` object when present.

    Args:
        result: The ``McpEndpointTestResponse`` payload.
        json_mode: Whether ``--json`` / ``--output json`` was requested.
    """
    if json_mode:
        emit_json(result)
        return
    emit_record_table({**result, "outcome": classify_test_outcome(result)}, _TEST_FIELDS)
    content = result.get("content") or []
    if content:
        typer.echo("")
        typer.echo("Content:")
        for item in content:
            typer.echo(_content_text(item))
    structured = result.get("structuredContent")
    if structured is not None:
        typer.echo("")
        typer.echo("Structured content:")
        typer.echo(json.dumps(structured, indent=2, sort_keys=True))
