"""AGX-2.1 invocation proxy — one agent ``tools/call`` as one governed upstream HTTP request (#4533).

:meth:`InvocationProxy.invoke` is the call path. For the verified agent key
(:func:`~apiome_mcp.agent_access.current_agent_access`) and one tool of its served toolset
(:mod:`apiome_mcp.agent_toolset_source`) it:

1. **validates** the arguments against the tool's ``inputSchema``
   (:func:`~apiome_mcp.agent_argument_validation.validate_arguments`). A failure is returned to the
   agent with every problem listed, and **nothing is sent upstream**;
2. **builds** the request the spec describes: path template expansion, query and header
   serialization, the body in its media type (:mod:`apiome_mcp.agent_request_builder`);
3. **routes** it (AGX-2.4 :func:`~apiome_mcp.mock_target.resolve_route`): ``mock`` toolsets go to
   the SIM mock for the version, ``prod`` toolsets to the spec's first absolute server;
4. **injects** the upstream credential for ``prod`` from the AGX-2.2 vault, server-side only
   (:func:`~apiome_mcp.agent_upstream_auth.resolve_upstream_injection`). A bound credential that
   cannot be opened fails the call closed, and a response that echoes the secret has it replaced
   by ``[redacted]`` before the agent sees it;
5. **calls** the upstream within the timeout / retry budget
   (:func:`~apiome_mcp.agent_upstream_client.send_upstream`);
6. **maps** the answer to an MCP result (:mod:`apiome_mcp.agent_result_mapping`): the body for a
   ``2xx`` (with a truncation marker when cut), or an ``isError`` result with a reason code and a
   hint for anything else.

Every call is audited as exactly one AGX-3.3 ``agent_invocations`` row
(:func:`~apiome_mcp.agent_invocations.audit_invocation`): ``success``, ``validation_failure``,
``upstream_error`` or ``internal_error``, with the reason as ``error_code``. The proxy never raises
into the MCP layer: an unexpected error becomes an ``invocation_failed`` result, recorded as
``internal_error``.

**Safety rails (AGX-2.3, #4535).** Between injecting and sending, the request must use the tool's
declared method and fit the request-body cap (:mod:`apiome_mcp.agent_safety_rails`); the upstream
client's SSRF guard then refuses a ``prod`` host that resolves to a non-public address. Each refusal is
its own result (``method_not_allowed``, ``request_too_large``, ``upstream_blocked``) and nothing is
sent. Quotas (AGX-3.2) run before the tool, in ``AgentQuotaMiddleware``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx
import structlog
from app.upstream_credential_binding import CredentialInjection
from fastmcp.tools.base import ToolResult
from psycopg_pool import AsyncConnectionPool

from apiome_mcp import __version__
from apiome_mcp.agent_access import AgentKey
from apiome_mcp.agent_argument_validation import validate_arguments
from apiome_mcp.agent_invocations import InvocationAudit, Target, audit_invocation
from apiome_mcp.agent_request_builder import InvalidArgumentsError, build_request, resolve_server_url
from apiome_mcp.agent_result_mapping import (
    InvocationErrorResult,
    InvocationFailure,
    InvocationReason,
    failure_for_response,
    fixed_failure,
    invalid_arguments,
    method_not_allowed,
    request_too_large,
    success_result,
    timeout_failure,
    unreachable_failure,
    upstream_blocked,
)
from apiome_mcp.agent_safety_rails import (
    MethodNotAllowedError,
    RequestTooLargeError,
    UpstreamBlockedError,
    enforce_declared_method,
    enforce_request_size,
)
from apiome_mcp.agent_toolset_source import ServedTool, ServedToolset
from apiome_mcp.agent_upstream_auth import UpstreamCredentialUnavailableError, resolve_upstream_injection
from apiome_mcp.agent_upstream_client import (
    UpstreamCallPolicy,
    UpstreamResponse,
    UpstreamTimeoutError,
    UpstreamUnreachableError,
    send_upstream,
)
from apiome_mcp.mock_target import (
    InvocationTarget,
    InvocationTargetError,
    MissingRouteInputError,
    MockCoordinates,
    parse_target,
    resolve_route,
)

if TYPE_CHECKING:
    from apiome_mcp.settings import Settings

_log = structlog.get_logger(__name__)

__all__ = ["CredentialSource", "InvocationConfig", "InvocationProxy", "SendUpstream"]

#: Opens the vault for one request: ``(pool, tenant_id, toolset_id, url) -> injection | None``.
CredentialSource = Callable[[AsyncConnectionPool, str, str, str], Awaitable[CredentialInjection | None]]

#: Sends one request (:func:`~apiome_mcp.agent_upstream_client.send_upstream`'s signature).
SendUpstream = Callable[..., Awaitable[UpstreamResponse]]


@dataclass(frozen=True)
class InvocationConfig:
    """Process-wide settings of the proxy.

    Attributes:
        policy: The upstream timeout / retry / size limits.
        mock_base_url: Root of the SIM mock the proxy sends ``mock`` traffic to.
        user_agent: The ``User-Agent`` sent upstream.
        max_request_bytes: Most request-body bytes one call may send (AGX-2.3).
    """

    policy: UpstreamCallPolicy
    mock_base_url: str
    user_agent: str = f"apiome-mcp-agent/{__version__}"
    max_request_bytes: int = 1_048_576

    @classmethod
    def from_settings(cls, settings: Settings) -> InvocationConfig:
        """Build the config from ``APIOME_MCP_AGENT_UPSTREAM_*`` and the mock settings."""
        return cls(
            policy=UpstreamCallPolicy(
                timeout_seconds=settings.agent_upstream_timeout_seconds,
                connect_timeout_seconds=settings.agent_upstream_connect_timeout_seconds,
                max_retries=settings.agent_upstream_max_retries,
                budget_seconds=settings.agent_upstream_budget_seconds,
                backoff_seconds=settings.agent_upstream_backoff_seconds,
                max_response_bytes=settings.agent_response_max_bytes,
            ),
            mock_base_url=settings.mock_invocation_base_url or settings.mock_public_base_url,
            max_request_bytes=settings.agent_request_max_bytes,
        )


@dataclass
class _Ended:
    """How a call ended: the agent's result, plus what the audit records."""

    result: ToolResult
    failure: InvocationFailure | None = None
    http_status: int | None = None
    response_text: str = ""


def _audit_target(raw: str) -> Target:
    """The audit label for a stored target (``prod`` unless it parses as ``mock``)."""
    try:
        return "mock" if parse_target(raw) is InvocationTarget.MOCK else "prod"
    except InvocationTargetError:
        return "prod"


#: What an echoed credential is replaced with in an upstream response.
REDACTED = b"[redacted]"

#: Secrets shorter than this are not scrubbed (too likely to match ordinary text).
_MIN_REDACT_CHARS = 6


def _secret_values(injection: CredentialInjection) -> list[str]:
    """Every spelling of the injected secrets an upstream could echo back."""
    values: set[str] = set()
    for _, value in injection.headers:
        values.add(value)
        scheme, _, rest = value.partition(" ")
        if rest and scheme.lower() in ("bearer", "basic"):
            values.add(rest)
    for _, value in injection.query:
        values.update((value, quote(value, safe="")))
    return sorted((v for v in values if len(v) >= _MIN_REDACT_CHARS), key=len, reverse=True)


def _redact(response: UpstreamResponse, secrets: list[str]) -> UpstreamResponse:
    """``response`` with every injected secret in its body and headers replaced by ``[redacted]``.

    The agent must never see an upstream credential (AGX-2.2). An upstream that echoes the request
    (a debug endpoint, an error page quoting the ``Authorization`` header) would otherwise hand it
    back through the tool result.
    """
    if not secrets:
        return response
    content = response.content
    headers = dict(response.headers)
    for secret in secrets:
        content = content.replace(secret.encode("utf-8"), REDACTED)
        headers = {name: value.replace(secret, REDACTED.decode()) for name, value in headers.items()}
    return replace(response, content=content, headers=headers)


def _failed(failure: InvocationFailure) -> _Ended:
    """End a call with ``failure``."""
    return _Ended(result=InvocationErrorResult(failure), failure=failure, http_status=failure.http_status)


class InvocationProxy:
    """Turns one agent ``tools/call`` into one upstream request and its MCP result."""

    def __init__(
        self,
        config: InvocationConfig,
        *,
        credentials: CredentialSource = resolve_upstream_injection,
        send: SendUpstream = send_upstream,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the proxy.

        Args:
            config: Limits and the mock root.
            credentials: Opens the vault (default: :func:`resolve_upstream_injection`).
            send: Sends the request (default: :func:`send_upstream`).
            monotonic: Clock for the overhead log line (tests).
        """
        self._config = config
        self._credentials = credentials
        self._send = send
        self._monotonic = monotonic

    async def invoke(
        self,
        *,
        pool: AsyncConnectionPool,
        client: httpx.AsyncClient,
        key: AgentKey,
        toolset: ServedToolset,
        tool: ServedTool,
        arguments: Mapping[str, Any] | None,
    ) -> ToolResult:
        """Run one call and record it.

        Args:
            pool: The shared Postgres pool (vault and audit).
            client: The shared HTTP client.
            key: The verified agent key.
            toolset: The key's served toolset.
            tool: The tool called (already checked as permitted by the access middleware).
            arguments: The call's arguments.

        Returns:
            The tool result: the upstream body on success, an ``isError`` result otherwise.
        """
        args: dict[str, Any] = dict(arguments or {})
        raw_args = json.dumps(args, separators=(",", ":"), ensure_ascii=False, default=str)
        started = self._monotonic()
        async with audit_invocation(
            pool,
            key,
            tool_name=tool.name,
            target=_audit_target(toolset.manifest.target),
            request_bytes=len(raw_args.encode("utf-8")),
            capture=toolset.manifest.body_capture,
        ) as audit:
            try:
                ended, upstream_ms = await self._run(pool, client, key, toolset, tool, args)
            except Exception:
                _log.warning("agent_invocation_failed", tool=tool.name, key_id=key.key_id, exc_info=True)
                ended, upstream_ms = _failed(fixed_failure(InvocationReason.INVOCATION_FAILED)), 0
            self._record(audit, ended, raw_args)
        total_ms = int(round((self._monotonic() - started) * 1000))
        _log.info(
            "agent_invocation",
            tool=tool.name,
            key_id=key.key_id,
            tenant_id=key.tenant_id,
            toolset_id=key.toolset_id,
            outcome=ended.failure.reason.value if ended.failure else "success",
            http_status=ended.http_status,
            latency_ms=total_ms,
            upstream_ms=upstream_ms,
            overhead_ms=max(0, total_ms - upstream_ms),
        )
        return ended.result

    @staticmethod
    def _record(audit: InvocationAudit, ended: _Ended, raw_args: str) -> None:
        """Report the call's outcome (and, if sampled, its bodies) to the audit."""
        text = ended.response_text or (ended.failure.text() if ended.failure else "")
        size = len(text.encode("utf-8"))
        audit.attach_bodies(request_body=raw_args, response_body=text)
        if ended.failure is None:
            audit.succeeded(http_status=ended.http_status, response_bytes=size)
        else:
            audit.failed(
                ended.failure.outcome, ended.failure.reason.value, http_status=ended.http_status, response_bytes=size
            )

    async def _run(
        self,
        pool: AsyncConnectionPool,
        client: httpx.AsyncClient,
        key: AgentKey,
        toolset: ServedToolset,
        tool: ServedTool,
        args: dict[str, Any],
    ) -> tuple[_Ended, int]:
        """Validate, build, route, inject, send, map. Returns ``(how it ended, upstream ms)``."""
        binding = tool.binding
        if binding is None:
            return _failed(fixed_failure(InvocationReason.TOOL_NOT_INVOCABLE)), 0

        issues = validate_arguments(tool.definition.input_schema, args)
        if issues:
            return _failed(invalid_arguments(issues)), 0
        try:
            request = build_request(binding, args)
        except InvalidArgumentsError as exc:
            return _failed(invalid_arguments(exc.issues)), 0

        try:
            enforce_declared_method(binding.method, request.method, request.headers)
            enforce_request_size(request.content, self._config.max_request_bytes)
        except MethodNotAllowedError as exc:
            _log.warning("agent_invocation_method_refused", tool=tool.name, declared=exc.declared, sent=exc.attempted)
            return _failed(method_not_allowed(exc.declared, exc.attempted)), 0
        except RequestTooLargeError as exc:
            return _failed(request_too_large(exc.size, exc.limit)), 0

        manifest = toolset.manifest
        try:
            is_mock = parse_target(manifest.target) is InvocationTarget.MOCK
        except InvocationTargetError:
            _log.warning("agent_invocation_target_invalid", toolset_id=manifest.toolset_id)
            return _failed(fixed_failure(InvocationReason.INVOCATION_FAILED)), 0
        try:
            route = resolve_route(
                target=manifest.target,
                upstream_base_url=None if is_mock else resolve_server_url(toolset.api),
                mock_public_base_url=self._config.mock_base_url,
                coordinates=(
                    MockCoordinates(manifest.tenant_slug, manifest.project_slug, manifest.version_label)
                    if is_mock
                    else None
                ),
            )
        except MissingRouteInputError:
            return _failed(fixed_failure(InvocationReason.UPSTREAM_NOT_CONFIGURED)), 0
        except InvocationTargetError:
            _log.warning("agent_invocation_route_invalid", toolset_id=manifest.toolset_id, exc_info=True)
            reason = InvocationReason.INVOCATION_FAILED if is_mock else InvocationReason.UPSTREAM_NOT_CONFIGURED
            return _failed(fixed_failure(reason)), 0

        url = request.url(route.base_url)
        headers = {**request.headers, "User-Agent": self._config.user_agent, **route.extra_headers}
        secrets: list[str] = []
        if route.inject_upstream_credentials:
            try:
                injection = await self._credentials(pool, key.tenant_id, key.toolset_id, url)
            except UpstreamCredentialUnavailableError:
                return _failed(fixed_failure(InvocationReason.UPSTREAM_CREDENTIAL_UNAVAILABLE)), 0
            if injection is not None:
                url, headers = injection.apply(url, headers)
                secrets = _secret_values(injection)

        policy = self._config.policy
        try:
            response = await self._send(
                client, request.method, url, headers=headers, content=request.content, policy=policy
            )
        except UpstreamBlockedError as exc:
            return _failed(upstream_blocked(exc.host)), 0
        except UpstreamTimeoutError as exc:
            return _failed(timeout_failure(binding, policy.budget_seconds, exc.attempts)), exc.elapsed_ms
        except UpstreamUnreachableError as exc:
            return _failed(unreachable_failure(binding, exc.attempts)), exc.elapsed_ms

        response = _redact(response, secrets)
        if 200 <= response.status < 300:
            result, text = success_result(response)
            return _Ended(result=result, http_status=response.status, response_text=text), response.elapsed_ms
        return _failed(failure_for_response(response, binding, args)), response.elapsed_ms
