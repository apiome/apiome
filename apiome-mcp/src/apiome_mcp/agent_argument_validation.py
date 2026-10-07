"""AGX-2.1 argument validation — refuse bad ``tools/call`` arguments before the upstream (#4533).

An agent's arguments are checked against the tool's compiled ``inputSchema`` (AGX-1.1) before any
request is built. A call that fails never reaches the upstream API: the agent gets every problem at
once, each pointing at the argument it is about, so it can fix them in one retry.

Two rules beyond the schema itself:

* **Unknown top-level arguments are refused** unless the schema's root explicitly allows extra
  properties. Agents invent arguments; with a flat request body an invented argument would
  otherwise be sent upstream as a body field.
* **Messages never echo a whole value.** ``jsonschema`` messages quote the failing instance, which
  may be large or sensitive, so each message is cut to :data:`MAX_PROBLEM_CHARS`.

The JSON Schema dialect is the one MCP uses for ``inputSchema`` (2020-12). The compiled schemas use
only the portable keyword subset (``docs/TOOL_COMPILER.md``), so the dialect choice does not change
the outcome of any keyword they contain.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from apiome_mcp.agent_request_builder import ArgumentIssue

__all__ = ["MAX_ISSUES", "MAX_PROBLEM_CHARS", "validate_arguments"]

#: Most issues reported for one call; the rest are summarized in one extra issue.
MAX_ISSUES = 20

#: Longest problem sentence; ``jsonschema`` quotes values in its messages.
MAX_PROBLEM_CHARS = 200

#: Where an issue about the argument object itself points.
_ROOT = "(arguments)"


def _location(error: ValidationError) -> str:
    """The argument path of a validation error: ``name``, ``name.field``, ``name[0]``, or the root."""
    parts: list[str] = []
    for part in error.absolute_path:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        else:
            parts.append(f".{part}" if parts else str(part))
    return "".join(parts) or _ROOT


def _problem(error: ValidationError) -> str:
    """The error message, cut to :data:`MAX_PROBLEM_CHARS`."""
    message = str(error.message)
    if len(message) > MAX_PROBLEM_CHARS:
        message = message[: MAX_PROBLEM_CHARS - 1] + "…"
    return message


def _unknown_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> list[ArgumentIssue]:
    """Issues for top-level arguments the schema does not declare (unless it allows extras)."""
    extra = schema.get("additionalProperties")
    if extra is True or isinstance(extra, Mapping):
        return []
    properties = schema.get("properties")
    declared = set(properties) if isinstance(properties, Mapping) else set()
    unknown = sorted(name for name in arguments if name not in declared)
    if not unknown:
        return []
    expected = ", ".join(sorted(declared)) or "no arguments"
    return [ArgumentIssue(name, f"is not an argument of this tool (expected: {expected})") for name in unknown]


def validate_arguments(schema: Mapping[str, Any], arguments: Any) -> list[ArgumentIssue]:
    """Check one call's arguments against its tool's ``inputSchema``.

    Args:
        schema: The tool's compiled ``inputSchema`` (an object schema).
        arguments: What the agent sent (``params.arguments``; ``None`` counts as ``{}``).

    Returns:
        Every problem found, sorted by argument (at most :data:`MAX_ISSUES` plus one summary
        issue). Empty when the arguments are valid.
    """
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, Mapping):
        return [ArgumentIssue(_ROOT, "must be a JSON object of named arguments")]
    issues = _unknown_arguments(schema, arguments)
    try:
        validator = Draft202012Validator(dict(schema))
        errors = sorted(validator.iter_errors(dict(arguments)), key=lambda e: (_location(e), e.message))
    except SchemaError:
        # A compiled schema is always valid (validate_mcp_tool); never block a call on our own bug.
        errors = []
    issues.extend(ArgumentIssue(_location(error), _problem(error)) for error in errors)
    if len(issues) > MAX_ISSUES:
        hidden = len(issues) - MAX_ISSUES
        issues = issues[:MAX_ISSUES] + [ArgumentIssue(_ROOT, f"{hidden} more problem(s) not shown")]
    return issues
