"""Export toolchain check console REST surface — MFX-44.6 (#4372).

The thin binding between Export Studio's **Toolchain checks** test-drive tab and the toolchain runner:

* ``POST /v1/export/{tenant_slug}/verify/tool-checks/{tool}`` → run one declared check of ``tool``
  (``buf`` + ``"check": "lint"``) on the artifact under review and stream its console as NDJSON.

The artifact is either a **completed export job's** artifact (``jobId`` — what the Review step shows)
or, without one, the verify buffer: the source revision **re-emitted server-side** for the same
``(target, options)`` ``/verify`` takes, so a caller can never have the server run a toolchain over
arbitrary bytes. Only a check the target's registry entry declares (MFX-44.1) can run; one whose tool
is not installed answers ``503`` with the registry's own reason.

The response body is one JSON object per line:

* ``{"event": "start", "tool", "check", "label", "command", "files"}`` — what runs, on which files;
* ``{"event": "output", "stream": "stdout" | "stderr", "text"}`` — each chunk as the tool writes it;
* ``{"event": "result", ...}`` — the closing :class:`~app.export_tool_checks.ExportToolCheckResult`
  (``status``: ``passed`` / ``failed`` / ``timed_out`` / ``unavailable`` / ``error``, ``exit_code``…),
  which the Studio attaches to the verify report.

Runs are tenant-scoped (JWT or API key, :func:`app.auth.validate_authentication`; the source and the
job are looked up within the caller's tenant) and rate-limited per user on top of the global
middleware (``export_tool_check_rate_limit_per_minute``); the runner's process-wide concurrency cap
and sandbox apply to every run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .config import settings
from .emitter import describe_emit_targets
from .export_service import ExportError, emit_canonical, resolve_emit_format
from .export_source import ExportSourceError, load_export_source
from .export_test_tools import ExportTestTool, ExportTestToolKind
from .export_tool_checks import (
    ExportToolCheckResult,
    ToolCheckArtifactError,
    ToolCheckStatus,
    files_from_download_body,
    files_from_emit,
    result_event,
    run_tool_check,
    tool_check_command,
)
from .rate_limit import FixedWindowRateLimiter

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/export", tags=["export"])

#: The NDJSON media type the console stream is served as.
NDJSON_MEDIA_TYPE = "application/x-ndjson"

_tool_check_limiter = FixedWindowRateLimiter()


class ExportToolCheckRequest(BaseModel):
    """Run one declared toolchain check on the artifact under review."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    artifact: str = Field(description="The artifact (project) id the export is of.")
    version: Optional[str] = Field(
        default=None,
        description="Revision UUID, version label (``1.0.0``), or null for the latest revision.",
    )
    target: str = Field(description="Target emitter key (``proto``) or format key (``proto3``).")
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Per-target emit options (MFX-1.4); null or empty applies the target defaults.",
    )
    check: str = Field(description="The declared check of the tool to run, e.g. ``lint`` for ``buf lint``.")
    job_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("jobId", "job_id"),
        description="A completed export job whose artifact to check; null re-emits the source for "
        "``target`` and ``options`` (the verify buffer).",
    )


def enforce_tool_check_rate_limit(tenant_id: str, user_id: str) -> None:
    """Record one check run against the user's budget, refusing when it is spent.

    Args:
        tenant_id: The caller's tenant.
        user_id: The caller (an API key's id stands in for a user).

    Raises:
        HTTPException: ``429`` with ``Retry-After`` and ``X-RateLimit-*`` headers when over
            ``export_tool_check_rate_limit_per_minute``. Does nothing while the global
            ``rate_limit_enabled`` kill switch is off.
    """
    if not settings.rate_limit_enabled:
        return
    limit = max(1, settings.export_tool_check_rate_limit_per_minute)
    window_seconds = max(1, settings.rate_limit_window_seconds)
    allowed, remaining, reset_after, retry_after = _tool_check_limiter.check(
        f"tool-check:{tenant_id}:{user_id}", limit, window_seconds, time.monotonic()
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many toolchain checks in a short time. Wait a moment, then run it again.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_after),
            },
        )


def _declared_check(target_format: str, tool: str, check: str) -> ExportTestTool:
    """The target's registry declaration of ``tool``'s ``check``.

    Args:
        target_format: A resolved registry format key (``proto3``).
        tool: The runner tool key (``buf``).
        check: The check (``lint``).

    Returns:
        The declared :class:`~app.export_test_tools.ExportTestTool`, with its availability here.

    Raises:
        HTTPException: ``404`` when the target declares no such check.
    """
    for entry in describe_emit_targets():
        descriptor = entry.descriptor
        if descriptor.format != target_format:
            continue
        for declared in descriptor.test_tools:
            if (declared.kind == ExportTestToolKind.TOOLCHAIN and declared.params.get("tool") == tool
                    and declared.params.get("check") == check):
                return declared
        raise HTTPException(
            status_code=404, detail=f"{descriptor.label} does not declare a {tool} {check} check.",
        )
    raise HTTPException(status_code=404, detail=f"No export target produces {target_format!r}.")


async def _job_files(tenant_slug: str, job_id: str, target_format: str) -> Dict[str, str]:
    """The files of a completed export job of this tenant, for ``target_format``.

    Raises:
        HTTPException: ``404`` for an unknown job; ``409`` when the job is not a completed
            single-target export of this target; ``410`` when its artifact expired; ``422`` when the
            artifact cannot be staged.
    """
    from .export_job_engine import get_export_job_status, resolve_export_download

    status = await get_export_job_status(tenant_slug, job_id)
    result = status.result
    if status.state != "completed" or result is None or result.target != target_format:
        raise HTTPException(
            status_code=409,
            detail="That export job is not a completed export of this target; generate it again.",
        )
    download = resolve_export_download(tenant_slug, job_id)
    try:
        return files_from_download_body(download.filename, download.body)
    except ToolCheckArtifactError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _emitted_files(tenant_id: str, payload: ExportToolCheckRequest, target_format: str) -> Dict[str, str]:
    """The source revision re-emitted for the request's target and options (the verify buffer).

    Raises:
        HTTPException: The source's or emitter's own status (``404`` / ``422`` / ``400``); ``422``
            when the artifact cannot be staged.
    """
    try:
        source = load_export_source(tenant_id, payload.artifact, payload.version)
    except ExportSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    try:
        emit = emit_canonical(source.api, target_format, opts=payload.options)
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    try:
        return files_from_emit(emit)
    except ToolCheckArtifactError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _ndjson(event: Dict[str, Any]) -> str:
    """One NDJSON line."""
    return json.dumps(event, ensure_ascii=False) + "\n"


@router.post(
    "/{tenant_slug}/verify/tool-checks/{tool}",
    response_class=StreamingResponse,
    summary="Run a target's toolchain check on the artifact under review, streaming its console",
    description=(
        "Run one toolchain check the target's registry entry declares (``test_tools`` of kind "
        "``toolchain``: ``tool`` in the path, ``check`` in the body) through the sandboxed toolchain "
        "runner, against a completed export job's artifact (``jobId``) or the source re-emitted for "
        "``target`` and ``options``. The body streams as NDJSON: a ``start`` event, an ``output`` "
        "event per stdout/stderr chunk, and a closing ``result`` event (``status`` ``passed`` / "
        "``failed`` / ``timed_out`` / ``unavailable`` / ``error``, ``exit_code``, ``duration_ms``, "
        "``command``, ``files``, ``message``). A check whose tool is not installed answers ``503`` "
        "with the reason; runs are rate-limited per user (``429``)."
    ),
    responses={
        200: {
            "description": "The check's console, one JSON event per line.",
            "content": {NDJSON_MEDIA_TYPE: {"schema": {"type": "string"}}},
        },
        404: {"description": "Unknown target, job or source, or the target declares no such check."},
        409: {"description": "The job is not a completed export of this target."},
        422: {"description": "No runnable command for the check, or the artifact cannot be staged."},
        429: {"description": "Too many toolchain checks in a short time."},
        503: {"description": "The check's toolchain is not installed on this server."},
    },
)
async def run_export_tool_check(
    tenant_slug: str,
    tool: str,
    payload: ExportToolCheckRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StreamingResponse:
    """Run a declared toolchain check and stream its console.

    Args:
        tenant_slug: The tenant slug (scopes the source and job lookups).
        tool: The runner tool key (``buf``).
        payload: Source coordinates, target, options, the check, and an optional job id.
        auth_data: Authenticated tenant context (JWT or API key).

    Returns:
        An NDJSON stream of ``start`` / ``output`` / ``result`` events.

    Raises:
        HTTPException: See the route's documented responses.
    """
    tenant_id = str(auth_data["tenant_id"])
    enforce_tool_check_rate_limit(tenant_id, str(get_authenticated_user_id(auth_data) or "anonymous"))

    try:
        target_format = resolve_emit_format(payload.target)
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    declared = _declared_check(target_format, tool, payload.check)
    command = tool_check_command(tool, payload.check)
    if command is None:
        raise HTTPException(
            status_code=422, detail=f"This server has no command for the {declared.label} check.",
        )
    if not declared.available:
        raise HTTPException(
            status_code=503,
            detail=declared.unavailable_reason or f"The {tool} toolchain is not installed on this server.",
        )

    if payload.job_id:
        files = await _job_files(tenant_slug, payload.job_id, target_format)
    else:
        files = _emitted_files(tenant_id, payload, target_format)

    queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = asyncio.Queue()

    async def _run() -> None:
        try:
            result = await run_tool_check(command, files, label=declared.label, on_event=queue.put_nowait)
        except Exception as exc:  # noqa: BLE001 - the stream has started; report, never drop it
            _logger.exception("toolchain check %s %s failed", tool, payload.check)
            result = ExportToolCheckResult(tool=tool, check=payload.check, label=declared.label,
                                           status=ToolCheckStatus.ERROR, command=declared.label,
                                           message=f"{declared.label} could not run: {exc}")
        queue.put_nowait(result_event(result))
        queue.put_nowait(None)

    async def _stream() -> AsyncIterator[str]:
        task = asyncio.create_task(_run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield _ndjson(event)
        finally:
            # A client that disconnects mid-run cancels the generator: stop the tool with it.
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        _stream(),
        media_type=NDJSON_MEDIA_TYPE,
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
