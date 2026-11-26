"""MCP pact tools — PFX-4.5 (#6942).

Four tools over the workspace's Pact Broker, for agents that need what ``pact-broker`` gives a CI job:

* ``pact.list`` — the latest pact of every consumer → provider integration, with its latest verification
  result; optional ``provider`` / ``consumer`` filters; cursor-paginated (``limit`` ≤ 100).
* ``pact.matrix`` — the matrix query: structured ``selectors`` (pacticipant + version / latest / tag /
  branch / environment / main_branch), a destination (``to_environment``, ``to_tag``, ``latest``,
  ``main_branch``), ``latestby`` and ``ignore``. Answers the verdict and at most ``max_rows`` rows.
* ``pact.can_i_deploy`` — one pacticipant version to ``to_environment`` or ``to_tag``.
* ``pact.record_deployment`` — the version is now deployed to a named environment (a **write**).

**Tool-quality rules.** Output is bounded: lists page, matrix answers carry at most ``max_rows`` rows (≤ 100)
and say ``rowsTotal`` / ``rowsTruncated``; the verdict is always reached from every row. Errors are explicit:
every refusal is a ``ToolError`` that names the problem and, for a REST refusal, its stable code in brackets
(``[pact-matrix-invalid] …``). Unsupported input is never ignored — an unknown selector key, a value of the
wrong type, or both destinations at once is refused with the reason before anything is sent.

**Access.** Pacts are workspace-wide, so the key's own tenant must be in its scope and the key must not be
limited to projects. apiome-rest then applies the ``pacts`` role of the person who created the key:
``pacts:view`` for the three reads, ``pacts:create`` to record a deployment. The work happens in apiome-rest's
internal ``/v1/internal/mcp/pacts`` routes (``APIOME_MCP_REST_INTERNAL_URL``,
``APIOME_MCP_REST_INTERNAL_SERVICE_TOKEN``).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import httpx
from fastmcp.exceptions import ToolError

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.rest_internal import post_internal
from apiome_mcp.settings import Settings, get_settings

__all__ = [
    "MAX_LIST_LIMIT",
    "MAX_ROWS",
    "build_pact_can_i_deploy_response",
    "build_pact_list_response",
    "build_pact_matrix_response",
    "build_pact_record_deployment_response",
]

#: Pacts per ``pact.list`` page by default, and at most.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100
#: Matrix rows returned by default, and at most.
DEFAULT_MAX_ROWS = 50
MAX_ROWS = 100
#: The most selectors (plus ignores) a matrix query may carry — apiome-rest's own cap.
MAX_SELECTORS = 50
#: Read timeout of one call to apiome-rest, in seconds.
_TIMEOUT_SECONDS = 30.0

_BASE = "/v1/internal/mcp/pacts"

#: Selector keys: what an agent may write (snake_case or the broker's camelCase) → the REST field.
_SELECTOR_KEYS: dict[str, tuple[str, type]] = {
    "pacticipant": ("pacticipant", str),
    "version": ("version", str),
    "latest": ("latest", bool),
    "tag": ("tag", str),
    "branch": ("branch", str),
    "environment": ("environment", str),
    "main_branch": ("mainBranch", bool),
    "mainBranch": ("mainBranch", bool),
}
_IGNORE_KEYS: dict[str, tuple[str, type]] = {
    "pacticipant": ("pacticipant", str),
    "version": ("version", str),
}


# ---------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------


def _require_workspace_scope(auth_ctx: McpAuthContext) -> None:
    """Refuse a key whose scope does not cover its whole workspace (pacts are workspace-wide)."""
    if auth_ctx.scope.projects:
        raise ToolError(
            "This MCP API key is limited to projects; pacts belong to the whole workspace, so the pact tools need "
            "a key without a project limit."
        )
    if not auth_ctx.scope.allows(str(auth_ctx.tenant_id)):
        raise ToolError("This MCP API key's scope does not include its own workspace, so it cannot read its pacts.")


def _text(name: str, value: Any, *, required: bool = False) -> str | None:
    """A trimmed string argument, ``None`` when absent; refuse a non-string or a blank required one."""
    if value is None:
        if required:
            raise ToolError(f"{name} is required.")
        return None
    if not isinstance(value, str):
        raise ToolError(f"{name} must be a string, not {type(value).__name__}.")
    text = value.strip()
    if required and not text:
        raise ToolError(f"{name} is required.")
    return text or None


def _bounded(name: str, value: Any, default: int, maximum: int) -> int:
    """A whole-number argument from 1 to ``maximum``; refuse anything else (never clamp silently)."""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{name} must be a whole number from 1 to {maximum}.")
    if value < 1 or value > maximum:
        raise ToolError(f"{name} must be from 1 to {maximum} (got {value}).")
    return int(value)


def _entry(kind: str, index: int, raw: Any, keys: Mapping[str, tuple[str, type]]) -> dict[str, Any]:
    """One selector / ignore object, translated to the REST field names.

    Args:
        kind: ``selectors`` or ``ignore``, for messages.
        index: Its position, for messages.
        raw: What the agent sent: an object (or, for ``ignore``, a bare pacticipant name).
        keys: The keys it may carry.

    Returns:
        The entry for apiome-rest.

    Raises:
        ToolError: Not an object, an unknown key (named, with the supported ones), a wrongly typed value, or no
            ``pacticipant``.
    """
    if kind == "ignore" and isinstance(raw, str):
        raw = {"pacticipant": raw}
    if not isinstance(raw, Mapping):
        raise ToolError(f"{kind}[{index}] must be an object with a pacticipant.")
    unknown = sorted(str(key) for key in raw if key not in keys)
    if unknown:
        supported = ", ".join(sorted({k for k in keys if k != "mainBranch"}))
        raise ToolError(f"{kind}[{index}] has unsupported keys {unknown}; supported: {supported}.")
    entry: dict[str, Any] = {}
    for key, value in raw.items():
        field, expected = keys[key]
        if value is None:
            continue
        if expected is bool:
            if not isinstance(value, bool):
                raise ToolError(f"{kind}[{index}].{key} must be true or false.")
            entry[field] = value
        else:
            entry[field] = _text(f"{kind}[{index}].{key}", value)
    if not entry.get("pacticipant"):
        raise ToolError(f"{kind}[{index}].pacticipant is required.")
    return entry


def _entries(kind: str, raw: Any, keys: Mapping[str, tuple[str, type]]) -> list[dict[str, Any]]:
    """A list of selector / ignore objects; ``None`` is an empty list."""
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ToolError(f"{kind} must be a list.")
    return [_entry(kind, index, item, keys) for index, item in enumerate(raw)]


def _base(auth_ctx: McpAuthContext) -> dict[str, Any]:
    """What every request carries: the key's tenant and id."""
    return {"tenantId": str(auth_ctx.tenant_id), "keyId": str(auth_ctx.key_id)}


async def _call(path: str, body: dict[str, Any], settings: Settings | None, transport: Any) -> dict[str, Any]:
    """Send one pact request to apiome-rest."""
    return await post_internal(
        f"{_BASE}{path}",
        body,
        settings=settings or get_settings(),
        what="pact request",
        timeout_seconds=_TIMEOUT_SECONDS,
        transport=transport,
        with_code=True,
    )


# ---------------------------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------------------------


async def build_pact_list_response(
    *,
    auth_ctx: McpAuthContext,
    provider: str | None = None,
    consumer: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """The latest pact of every integration, one page.

    Args:
        auth_ctx: The authenticated MCP key.
        provider: Only pacts for this provider (handle, id or name).
        consumer: Only pacts of this consumer.
        limit: Pacts per page (1–100, default 50).
        cursor: ``nextCursor`` of the previous page.
        settings: Overrides the process settings (tests).
        transport: An ``httpx`` transport (tests).

    Returns:
        ``{items: [{consumer, provider, consumerVersion, sha, specificationVersion, interactionCount, revision,
        publishedAt, updatedAt, latestVerification}], hasMore, nextCursor}``.

    Raises:
        ToolError: A key limited to projects, a bad argument, an unknown pacticipant, or a REST refusal.
    """
    _require_workspace_scope(auth_ctx)
    body = {
        **_base(auth_ctx),
        "provider": _text("provider", provider),
        "consumer": _text("consumer", consumer),
        "limit": _bounded("limit", limit, DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT),
        "cursor": _text("cursor", cursor),
    }
    return await _call("/list", body, settings, transport)


async def build_pact_matrix_response(
    *,
    auth_ctx: McpAuthContext,
    selectors: Any,
    latestby: str | None = None,
    to_environment: str | None = None,
    to_tag: str | None = None,
    latest: bool | None = None,
    main_branch: bool | None = None,
    ignore: Any = None,
    limit: int | None = None,
    max_rows: int | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Answer a Pact Broker matrix query.

    Args:
        auth_ctx: The authenticated MCP key.
        selectors: The versions in question: ``[{pacticipant, version?, latest?, tag?, branch?, environment?,
            main_branch?}]``. One selector with a destination asks "can I deploy this?"; two or more ask "do
            these work together?".
        latestby: ``cvp``, ``cvpv`` or ``cp`` — how rows collapse.
        to_environment: Destination: every version currently in this environment.
        to_tag: Destination: the latest version with this tag (with ``latest``).
        latest: Destination: each other pacticipant's latest version.
        main_branch: Destination: each other pacticipant's main branch.
        ignore: Pacticipants (``"Name"`` or ``{pacticipant, version?}``) whose rows do not count.
        limit: The most rows the query reads (1–1000; the broker default 100).
        max_rows: The most rows returned (1–100, default 50).
        settings: Overrides the process settings (tests).
        transport: An ``httpx`` transport (tests).

    Returns:
        ``{summary: {deployable, reason, success, failed, unknown}, notices, noticesTruncated, rows, rowsTotal,
        rowsTruncated, retryAfterSeconds}``.

    Raises:
        ToolError: A key limited to projects, an unsupported or malformed argument, or a REST refusal
            (``[pact-matrix-invalid]`` for a query the broker cannot answer).
    """
    _require_workspace_scope(auth_ctx)
    chosen = _entries("selectors", selectors, _SELECTOR_KEYS)
    if not chosen:
        raise ToolError("selectors is required: at least one {pacticipant, …} object.")
    ignored = _entries("ignore", ignore, _IGNORE_KEYS)
    if len(chosen) + len(ignored) > MAX_SELECTORS:
        raise ToolError(f"A matrix query may carry at most {MAX_SELECTORS} selectors and ignores together.")
    collapse = _text("latestby", latestby)
    if collapse is not None and collapse not in ("cvp", "cvpv", "cp"):
        raise ToolError("latestby must be one of cvp, cvpv, cp.")
    for name, flag in (("latest", latest), ("main_branch", main_branch)):
        if flag is not None and not isinstance(flag, bool):
            raise ToolError(f"{name} must be true or false.")
    body = {
        **_base(auth_ctx),
        "selectors": chosen,
        "latestby": collapse,
        "toEnvironment": _text("to_environment", to_environment),
        "toTag": _text("to_tag", to_tag),
        "latest": latest,
        "mainBranch": main_branch,
        "ignore": ignored,
        "limit": _bounded("limit", limit, 100, 1000) if limit is not None else None,
        "maxRows": _bounded("max_rows", max_rows, DEFAULT_MAX_ROWS, MAX_ROWS),
    }
    return await _call("/matrix", body, settings, transport)


async def build_pact_can_i_deploy_response(
    *,
    auth_ctx: McpAuthContext,
    pacticipant: str,
    version: str,
    to_environment: str | None = None,
    to_tag: str | None = None,
    ignore: Any = None,
    max_rows: int | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Can one pacticipant version be deployed to an environment (or a tag)?

    Args:
        auth_ctx: The authenticated MCP key.
        pacticipant: What is being deployed.
        version: Its version number, exactly as recorded.
        to_environment: Where it goes (give this or ``to_tag``).
        to_tag: The tag it is checked against instead.
        ignore: Pacticipants (``"Name"`` or ``{pacticipant, version?}``) whose rows do not count.
        max_rows: The most rows returned (1–100, default 50).
        settings: Overrides the process settings (tests).
        transport: An ``httpx`` transport (tests).

    Returns:
        The same answer as ``pact.matrix``: read ``summary.deployable`` (``true`` / ``false`` / ``null`` while a
        verification result is missing — then ``retryAfterSeconds`` says when to ask again).

    Raises:
        ToolError: Neither or both destinations, a missing argument, a key limited to projects, or a REST refusal.
    """
    _require_workspace_scope(auth_ctx)
    environment = _text("to_environment", to_environment)
    tag = _text("to_tag", to_tag)
    if environment and tag:
        raise ToolError("Give to_environment or to_tag, not both.")
    if not environment and not tag:
        raise ToolError("Give to_environment (where the version is deployed) or to_tag.")
    body = {
        **_base(auth_ctx),
        "pacticipant": _text("pacticipant", pacticipant, required=True),
        "version": _text("version", version, required=True),
        "toEnvironment": environment,
        "toTag": tag,
        "ignore": _entries("ignore", ignore, _IGNORE_KEYS),
        "maxRows": _bounded("max_rows", max_rows, DEFAULT_MAX_ROWS, MAX_ROWS),
    }
    return await _call("/can-i-deploy", body, settings, transport)


async def build_pact_record_deployment_response(
    *,
    auth_ctx: McpAuthContext,
    pacticipant: str,
    version: str,
    environment: str,
    application_instance: str | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Record that a pacticipant version is now deployed to an environment.

    Args:
        auth_ctx: The authenticated MCP key.
        pacticipant: The deployed pacticipant.
        version: The deployed version number (it must have been recorded: published a pact or verified one).
        environment: The environment's name.
        application_instance: The instance deployed to (a region, a customer); omit for the only one.
        settings: Overrides the process settings (tests).
        transport: An ``httpx`` transport (tests).

    Returns:
        ``{created, deployment: {uuid, pacticipant, version, environment, applicationInstance, currentlyDeployed,
        createdAt}}`` — ``created: false`` when it already was the current deployment there.

    Raises:
        ToolError: A missing argument, a key limited to projects, the key owner lacking ``pacts:create``, or an
            unknown pacticipant, version or environment.
    """
    _require_workspace_scope(auth_ctx)
    body = {
        **_base(auth_ctx),
        "pacticipant": _text("pacticipant", pacticipant, required=True),
        "version": _text("version", version, required=True),
        "environment": _text("environment", environment, required=True),
        "applicationInstance": _text("application_instance", application_instance),
    }
    return await _call("/record-deployment", body, settings, transport)
