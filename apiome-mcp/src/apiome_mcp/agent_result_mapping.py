"""AGX-2.1 response mapping — an upstream answer as an MCP tool result an agent can act on (#4533).

**Success** (``2xx``) becomes a normal tool result:

* the first text block is the response body as the upstream sent it (JSON stays JSON); an empty body
  becomes ``HTTP 204: no content``-style text;
* when the body was cut at ``max_response_bytes``, a second text block says so
  (``[truncated: …]``), so the agent knows it is not seeing everything;
* ``structuredContent`` carries ``httpStatus``, ``contentType``, ``truncated`` and, when the whole
  body was JSON, the parsed ``body``.

**Failure** becomes a result with ``isError: true`` (:class:`InvocationErrorResult`). A raised error
would lose its data: the MCP SDK folds anything raised during ``tools/call`` into text. Like the
AGX-3.2 quota refusal, the text starts with a reason code, and ``structuredContent`` carries the
details an agent can parse:

.. code-block:: json

    {"error": {"code": -32013, "reason": "upstream_not_found", "message": "…"},
     "reason": "upstream_not_found", "httpStatus": 404, "retryable": false,
     "hint": "…", "upstream": {"contentType": "application/json", "body": {…}}}

Each reason has its own hint: which argument the upstream complained about (``400``/``422``), which
identifiers to check (``404``), that credentials are the tenant's to fix (``401``/``403``), when to
retry (``429``, ``5xx``, timeouts). ``invalid_arguments`` uses JSON-RPC's ``-32602`` and lists every
problem under ``invalidArguments``. No result ever contains an upstream credential: the request
headers are never echoed.

The AGX-2.3 rails (:mod:`apiome_mcp.agent_safety_rails`) add three refusals, each sent before
anything reaches the upstream: ``upstream_blocked`` (the SSRF guard), ``method_not_allowed`` (a
method the tool does not declare) and ``request_too_large`` (the request-body cap).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

import mcp.types as mt
from fastmcp.tools.base import ToolResult

from apiome_mcp.agent_invocations import InvocationOutcome
from apiome_mcp.agent_request_builder import ArgumentIssue, OperationBinding
from apiome_mcp.agent_upstream_client import IDEMPOTENT_METHODS, UpstreamResponse

__all__ = [
    "AGENT_INVOCATION_ERROR_CODE",
    "INVALID_ARGUMENTS_CODE",
    "MAX_ERROR_BODY_CHARS",
    "InvocationErrorResult",
    "InvocationFailure",
    "InvocationReason",
    "failure_for_response",
    "fixed_failure",
    "invalid_arguments",
    "method_not_allowed",
    "request_too_large",
    "success_result",
    "timeout_failure",
    "unreachable_failure",
    "upstream_blocked",
]

#: ``structuredContent.error.code`` of every invocation failure except invalid arguments. Next to the
#: AGX-3.1 codes (-32010 key, -32011 toolset) and AGX-3.2's -32012 (quota).
AGENT_INVOCATION_ERROR_CODE = -32013

#: JSON-RPC "invalid params", for arguments refused before the upstream.
INVALID_ARGUMENTS_CODE = mt.INVALID_PARAMS

#: Longest upstream error body excerpt returned to the agent.
MAX_ERROR_BODY_CHARS = 2000


class InvocationReason(str, Enum):
    """Why a call failed: the result's text prefix and the invocation's ``error_code``."""

    INVALID_ARGUMENTS = "invalid_arguments"
    UPSTREAM_BAD_REQUEST = "upstream_bad_request"
    UPSTREAM_UNAUTHORIZED = "upstream_unauthorized"
    UPSTREAM_FORBIDDEN = "upstream_forbidden"
    UPSTREAM_NOT_FOUND = "upstream_not_found"
    UPSTREAM_CONFLICT = "upstream_conflict"
    UPSTREAM_RATE_LIMITED = "upstream_rate_limited"
    UPSTREAM_CLIENT_ERROR = "upstream_client_error"
    UPSTREAM_SERVER_ERROR = "upstream_server_error"
    UPSTREAM_REDIRECT = "upstream_redirect"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_UNREACHABLE = "upstream_unreachable"
    UPSTREAM_NOT_CONFIGURED = "upstream_not_configured"
    UPSTREAM_CREDENTIAL_UNAVAILABLE = "upstream_credential_unavailable"
    UPSTREAM_BLOCKED = "upstream_blocked"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    REQUEST_TOO_LARGE = "request_too_large"
    TOOL_NOT_INVOCABLE = "tool_not_invocable"
    INVOCATION_FAILED = "invocation_failed"


@dataclass(frozen=True)
class InvocationFailure:
    """One failed call, as the agent is told about it and as the audit records it.

    Attributes:
        reason: The reason code.
        message: What happened, one sentence.
        hint: What the agent should do next.
        outcome: The AGX-3.3 outcome recorded for the call.
        http_status: The upstream status, when it answered.
        retryable: Whether calling again unchanged can succeed.
        retry_after_seconds: How long to wait first, when known.
        invalid_arguments: The argument problems (``invalid_arguments`` only).
        upstream_content_type: The upstream error body's media type.
        upstream_body: The upstream error body (parsed JSON, or a text excerpt).
    """

    reason: InvocationReason
    message: str
    hint: str
    outcome: InvocationOutcome
    http_status: int | None = None
    retryable: bool = False
    retry_after_seconds: int | None = None
    invalid_arguments: tuple[ArgumentIssue, ...] = ()
    upstream_content_type: str | None = None
    upstream_body: Any = None

    @property
    def code(self) -> int:
        """The JSON-RPC-style code in ``structuredContent.error.code``."""
        if self.reason is InvocationReason.INVALID_ARGUMENTS:
            return INVALID_ARGUMENTS_CODE
        return AGENT_INVOCATION_ERROR_CODE

    def text(self) -> str:
        """The failure as text: reason code, message, the problems or the upstream body, the hint."""
        lines = [f"{self.reason.value}: {self.message}"]
        lines.extend(f"- {issue.argument}: {issue.problem}" for issue in self.invalid_arguments)
        if self.upstream_body is not None:
            body = self.upstream_body
            excerpt = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
            lines.append(f"Upstream response: {excerpt[:MAX_ERROR_BODY_CHARS]}")
        lines.append(f"Hint: {self.hint}")
        return "\n".join(lines)

    def payload(self) -> dict[str, Any]:
        """The failure as ``structuredContent``."""
        data: dict[str, Any] = {
            "error": {"code": self.code, "reason": self.reason.value, "message": self.message},
            "reason": self.reason.value,
            "retryable": self.retryable,
            "hint": self.hint,
        }
        if self.http_status is not None:
            data["httpStatus"] = self.http_status
        if self.retry_after_seconds is not None:
            data["retryAfterSeconds"] = self.retry_after_seconds
        if self.invalid_arguments:
            data["invalidArguments"] = [issue.to_dict() for issue in self.invalid_arguments]
        if self.upstream_body is not None or self.upstream_content_type:
            data["upstream"] = {"contentType": self.upstream_content_type, "body": self.upstream_body}
        return data


class InvocationErrorResult(ToolResult):
    """A failed ``tools/call``: ``isError: true`` with the failure as ``structuredContent``.

    FastMCP's :class:`~fastmcp.tools.base.ToolResult` cannot set ``isError``, so this subclass
    returns a ready :class:`mcp.types.CallToolResult` (the same approach as AGX-3.2's
    ``QuotaRefusalResult``).
    """

    def __init__(self, failure: InvocationFailure) -> None:
        """Build the result for ``failure``."""
        super().__init__(
            content=[mt.TextContent(type="text", text=failure.text())], structured_content=failure.payload()
        )

    def to_mcp_result(self) -> mt.CallToolResult:
        """Return the failure as an error ``CallToolResult``."""
        return mt.CallToolResult(content=self.content, structuredContent=self.structured_content, isError=True)


# --------------------------------------------------------------------------------------------------
# Building results
# --------------------------------------------------------------------------------------------------


def _is_json(content_type: str | None) -> bool:
    """Whether a ``Content-Type`` is JSON."""
    essence = (content_type or "").split(";", 1)[0].strip().lower()
    return essence.endswith("/json") or essence.endswith("+json")


def _decode(content: bytes) -> str:
    """Body bytes as text (UTF-8, undecodable bytes replaced)."""
    return content.decode("utf-8", errors="replace")


def _parse_json(response: UpstreamResponse) -> tuple[bool, Any]:
    """``(True, value)`` when the whole body is JSON, else ``(False, None)``."""
    if response.truncated or not response.content:
        return False, None
    if not _is_json(response.content_type) and response.content[:1] not in (b"{", b"["):
        return False, None
    try:
        return True, json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        return False, None


def success_result(response: UpstreamResponse) -> tuple[ToolResult, str]:
    """Map a ``2xx`` response to a tool result.

    Args:
        response: The upstream response.

    Returns:
        ``(result, text)`` where ``text`` is the body text handed to the agent (for the audit's
        sizes and optional body sample).
    """
    text = _decode(response.content) if response.content else f"HTTP {response.status}: no content"
    content: list[mt.TextContent] = [mt.TextContent(type="text", text=text)]
    if response.truncated:
        total = f" of {response.total_bytes}" if response.total_bytes is not None else ""
        content.append(
            mt.TextContent(
                type="text",
                text=(
                    f"[truncated: the response body is larger than this tool returns; showing the first "
                    f"{len(response.content)}{total} bytes. Narrow the request (filters, a smaller page size) "
                    "to see the rest.]"
                ),
            )
        )
    structured: dict[str, Any] = {
        "httpStatus": response.status,
        "contentType": response.content_type,
        "truncated": response.truncated,
    }
    parsed, value = _parse_json(response)
    if parsed:
        structured["body"] = value
    return ToolResult(content=content, structured_content=structured), text


def invalid_arguments(issues: Sequence[ArgumentIssue]) -> InvocationFailure:
    """The failure for arguments refused before anything was sent upstream."""
    count = len(issues)
    return InvocationFailure(
        reason=InvocationReason.INVALID_ARGUMENTS,
        message=f"{count} argument problem{'s' if count != 1 else ''}; nothing was sent to the API.",
        hint="Fix the listed arguments to match the tool's inputSchema and call again.",
        outcome=InvocationOutcome.VALIDATION_FAILURE,
        invalid_arguments=tuple(issues),
    )


def _error_body(response: UpstreamResponse) -> Any:
    """The upstream error body for the agent: parsed JSON when small enough, else a text excerpt."""
    if not response.content:
        return None
    parsed, value = _parse_json(response)
    if parsed and len(response.content) <= 4 * MAX_ERROR_BODY_CHARS:
        return value
    text = _decode(response.content)
    return text[:MAX_ERROR_BODY_CHARS] + ("…" if len(text) > MAX_ERROR_BODY_CHARS else "")


_MESSAGE_KEYS = ("detail", "message", "error_description", "title", "error", "msg", "description")
_FIELD_KEYS = ("name", "field", "param", "parameter", "pointer", "path", "loc", "property")
_ERROR_LISTS = ("errors", "invalid-params", "invalid_params", "invalidParams", "violations", "details", "fields")


def _upstream_message(body: Any) -> str | None:
    """The upstream's own one-line explanation, from the common error-body shapes."""
    if isinstance(body, str):
        return body.strip()[:300] or None
    if not isinstance(body, Mapping):
        return None
    for key in _MESSAGE_KEYS:
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
        if isinstance(value, Mapping):
            nested = _upstream_message(value)
            if nested:
                return nested
    return None


def _field_names(body: Any) -> set[str]:
    """Field names an error body points at (problem+json ``invalid-params``, ``errors[].field``…)."""
    names: set[str] = set()
    if not isinstance(body, Mapping):
        return names
    for list_key in _ERROR_LISTS:
        entries = body.get(list_key)
        if isinstance(entries, Mapping):
            names.update(str(k) for k in entries)
            continue
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, Mapping):
                continue
            for key in _FIELD_KEYS:
                value = entry.get(key)
                if isinstance(value, str):
                    names.update(part for part in re.split(r"[/.\[\]#]+", value) if part)
                elif isinstance(value, list):
                    names.update(str(part) for part in value if isinstance(part, (str, int)))
    return names


def _error_texts(body: Any) -> list[str]:
    """The upstream's prose: its top-level message and each listed error's message or reason.

    JSON keys are never included, so an argument called ``name`` is not "mentioned" by an error
    entry shaped ``{"name": "tag", ...}``.
    """
    texts = [_upstream_message(body) or ""]
    if isinstance(body, Mapping):
        for list_key in _ERROR_LISTS:
            entries = body.get(list_key)
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, str):
                    texts.append(entry)
                elif isinstance(entry, Mapping):
                    texts.extend(
                        str(entry[k]) for k in ("message", "reason", "detail", "msg") if isinstance(entry.get(k), str)
                    )
    return [text.lower() for text in texts if text]


def _mentioned_arguments(body: Any, arguments: Iterable[str]) -> list[str]:
    """The call's argument names the upstream's error points at or mentions in its prose."""
    pointed = _field_names(body)
    texts = _error_texts(body)
    found = []
    for name in arguments:
        word = re.compile(rf"(?<![a-z0-9_]){re.escape(name.lower())}(?![a-z0-9_])")
        if name in pointed or (len(name) > 2 and any(word.search(text) for text in texts)):
            found.append(name)
    return sorted(found)


def _status_reason(status: int) -> InvocationReason:
    """The reason code for an upstream status."""
    if 300 <= status < 400:
        return InvocationReason.UPSTREAM_REDIRECT
    return {
        400: InvocationReason.UPSTREAM_BAD_REQUEST,
        422: InvocationReason.UPSTREAM_BAD_REQUEST,
        401: InvocationReason.UPSTREAM_UNAUTHORIZED,
        403: InvocationReason.UPSTREAM_FORBIDDEN,
        404: InvocationReason.UPSTREAM_NOT_FOUND,
        410: InvocationReason.UPSTREAM_NOT_FOUND,
        409: InvocationReason.UPSTREAM_CONFLICT,
        429: InvocationReason.UPSTREAM_RATE_LIMITED,
    }.get(status, InvocationReason.UPSTREAM_SERVER_ERROR if status >= 500 else InvocationReason.UPSTREAM_CLIENT_ERROR)


def _retry_after_seconds(response: UpstreamResponse) -> int | None:
    """A whole-second ``Retry-After`` from the upstream, if it sent one."""
    raw = response.headers.get("retry-after")
    if raw and raw.strip().isdigit():
        return max(1, int(raw.strip()))
    return None


def _not_idempotent_caveat(method: str) -> str:
    """A warning that a non-idempotent call may have taken effect."""
    if method.upper() in IDEMPOTENT_METHODS:
        return ""
    return f" A {method.upper()} may already have taken effect: check the current state before calling again."


def failure_for_response(
    response: UpstreamResponse, binding: OperationBinding, arguments: Mapping[str, Any]
) -> InvocationFailure:
    """Map a non-``2xx`` response to a failure with a hint.

    Args:
        response: The upstream response.
        binding: The tool's binding (method, path arguments).
        arguments: The arguments sent (names only are used, to say which one the upstream rejected).

    Returns:
        The failure.
    """
    status = response.status
    reason = _status_reason(status)
    body = _error_body(response)
    said = _upstream_message(body)
    detail = f": {said}" if said else "."
    retry_after = _retry_after_seconds(response)
    retryable = False

    if reason is InvocationReason.UPSTREAM_BAD_REQUEST:
        mentioned = _mentioned_arguments(body, arguments)
        pointer = f" The upstream points at: {', '.join(mentioned)}." if mentioned else ""
        message = f"The API rejected the request (HTTP {status}){detail}"
        hint = (
            f"Correct the arguments the upstream complained about and call again.{pointer} "
            "Retrying unchanged will fail the same way."
        )
    elif reason is InvocationReason.UPSTREAM_UNAUTHORIZED:
        message = f"The API refused the credentials Apiome sent for this toolset (HTTP {status})."
        hint = (
            "This is not something the agent can fix: a tenant administrator must add or rotate the toolset's "
            "upstream credential. Do not retry."
        )
    elif reason is InvocationReason.UPSTREAM_FORBIDDEN:
        message = f"The API does not allow this operation for the configured credential (HTTP {status}){detail}"
        hint = "Do not retry; ask a tenant administrator to grant the upstream credential access to this operation."
    elif reason is InvocationReason.UPSTREAM_NOT_FOUND:
        ids = [f"{name}={arguments.get(name)!r}" for name in binding.path_arguments if name in arguments]
        which = f" ({', '.join(ids)})" if ids else ""
        message = f"The API found nothing at {binding.method} {binding.path_template} (HTTP {status})."
        hint = (
            f"Check the identifiers you passed{which}; list or search the collection first to find a valid one. "
            "Retrying unchanged will not help."
        )
    elif reason is InvocationReason.UPSTREAM_CONFLICT:
        message = f"The request conflicts with the resource's current state (HTTP {status}){detail}"
        hint = "Read the current resource, then call again with arguments that fit its state."
    elif reason is InvocationReason.UPSTREAM_RATE_LIMITED:
        wait = f"after {retry_after} s" if retry_after else "later, with exponential backoff"
        message = f"The API is rate-limiting these calls (HTTP {status})."
        hint = f"Wait and retry {wait}."
        retryable = True
    elif reason is InvocationReason.UPSTREAM_SERVER_ERROR:
        message = f"The API failed to handle the request (HTTP {status}){detail}"
        retried = "Apiome already retried where that was safe. " if binding.method in IDEMPOTENT_METHODS else ""
        hint = (
            f"{retried}This is an upstream fault, not an argument problem: retry later with backoff, and stop if it "
            f"persists.{_not_idempotent_caveat(binding.method)}"
        )
        retryable = True
    elif reason is InvocationReason.UPSTREAM_REDIRECT:
        location = response.headers.get("location")
        message = f"The API answered with a redirect (HTTP {status}) that Apiome does not follow."
        hint = (
            f"The toolset's upstream address may be out of date{f' (redirect to {location})' if location else ''}; "
            "ask a tenant administrator to check it."
        )
    else:
        message = f"The API rejected the request (HTTP {status}){detail}"
        hint = "Check the arguments against the tool description; retrying unchanged will likely fail the same way."

    return InvocationFailure(
        reason=reason,
        message=message,
        hint=hint,
        outcome=InvocationOutcome.UPSTREAM_ERROR,
        http_status=status,
        retryable=retryable,
        retry_after_seconds=retry_after,
        upstream_content_type=response.content_type,
        upstream_body=body,
    )


def _attempts(count: int) -> str:
    """``1 attempt`` / ``3 attempts``."""
    return f"{count} attempt{'s' if count != 1 else ''}"


def timeout_failure(binding: OperationBinding, budget_seconds: float, attempts: int) -> InvocationFailure:
    """The failure for an upstream that did not answer within the budget."""
    return InvocationFailure(
        reason=InvocationReason.UPSTREAM_TIMEOUT,
        message=f"The API did not answer within {budget_seconds:g} s ({_attempts(attempts)}).",
        hint="Retry later with backoff; narrow the request if it is expensive."
        + _not_idempotent_caveat(binding.method),
        outcome=InvocationOutcome.UPSTREAM_ERROR,
        retryable=True,
    )


def unreachable_failure(binding: OperationBinding, attempts: int) -> InvocationFailure:
    """The failure for an upstream that could not be connected to."""
    return InvocationFailure(
        reason=InvocationReason.UPSTREAM_UNREACHABLE,
        message=f"Apiome could not connect to the API ({_attempts(attempts)}).",
        hint="The upstream may be down; retry later with backoff, and stop if it persists.",
        outcome=InvocationOutcome.UPSTREAM_ERROR,
        retryable=True,
    )


def upstream_blocked(host: str) -> InvocationFailure:
    """The failure for an upstream the AGX-2.3 SSRF guard refused (nothing was sent).

    Args:
        host: The host the spec named. The refused address is not shown.
    """
    return InvocationFailure(
        reason=InvocationReason.UPSTREAM_BLOCKED,
        message=(
            f"The API host {host!r} resolves to a private, loopback, link-local or metadata address, so Apiome "
            "refused to call it (SSRF guard). Nothing was sent."
        ),
        hint=(
            "Not fixable by the agent: a tenant administrator must point the API's server at a public address. "
            "Do not retry."
        ),
        outcome=InvocationOutcome.INTERNAL_ERROR,
    )


def method_not_allowed(declared: str, attempted: str) -> InvocationFailure:
    """The failure for a request that would have used a method the tool does not declare (nothing was sent)."""
    return InvocationFailure(
        reason=InvocationReason.METHOD_NOT_ALLOWED,
        message=(
            f"This tool may only send {declared}; the request would have sent {attempted}, so it was refused. "
            "Nothing was sent."
        ),
        hint=(
            f"Call the tool without any method override; to {attempted} a resource, use the tool for that "
            "operation if the toolset exposes one."
        ),
        outcome=InvocationOutcome.VALIDATION_FAILURE,
    )


def request_too_large(size: int, limit: int) -> InvocationFailure:
    """The failure for a request body over the size cap (nothing was sent)."""
    return InvocationFailure(
        reason=InvocationReason.REQUEST_TOO_LARGE,
        message=f"The request body is {size} bytes, over this runtime's {limit}-byte limit. Nothing was sent.",
        hint="Send less in one call: split the payload across several calls, or leave out optional fields.",
        outcome=InvocationOutcome.VALIDATION_FAILURE,
    )


#: ``(message, hint)`` of the failures that do not depend on the call (configuration or internal).
_FIXED: dict[InvocationReason, tuple[str, str]] = {
    InvocationReason.UPSTREAM_NOT_CONFIGURED: (
        "The API's description names no absolute server URL to call.",
        "Not fixable by the agent: a tenant administrator must give the spec an absolute https server, or "
        "switch the toolset to the mock target.",
    ),
    InvocationReason.UPSTREAM_CREDENTIAL_UNAVAILABLE: (
        "The upstream credential bound to this API cannot be opened, so the call was not sent.",
        "Not fixable by the agent: a tenant administrator must rotate the toolset's upstream credential. Do not retry.",
    ),
    InvocationReason.TOOL_NOT_INVOCABLE: (
        "This tool's operation has no HTTP method and path, so it cannot be called through the proxy.",
        "Use another tool; this operation can only be described, not invoked.",
    ),
    InvocationReason.INVOCATION_FAILED: (
        "The call could not be completed because of an error inside Apiome.",
        "Retry once later; if it fails again, report it to the tenant administrator.",
    ),
}


def fixed_failure(reason: InvocationReason) -> InvocationFailure:
    """A configuration or internal failure (recorded as ``internal_error``).

    Args:
        reason: One of ``upstream_not_configured``, ``upstream_credential_unavailable``,
            ``tool_not_invocable`` or ``invocation_failed``.

    Returns:
        The failure, with its fixed wording.
    """
    message, hint = _FIXED[reason]
    return InvocationFailure(reason=reason, message=message, hint=hint, outcome=InvocationOutcome.INTERNAL_ERROR)
