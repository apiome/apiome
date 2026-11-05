"""The export pipeline for the MCP server — MFX-40.1 (#4339).

``apiome-mcp`` serves two generic export tools, ``export.targets`` and ``version.export``, for **every**
registered emitter: there is no per-format tool code (the per-format tools of #2866/#2867 are not
needed). The emitter registry, the fidelity prediction and the export job engine live here, so the MCP
server calls these two internal routes after it has authenticated the caller's MCP API key and checked
its scope:

* ``POST /v1/internal/mcp/export/targets`` — the same answer as ``GET /v1/export/{tenant}/targets``:
  every registered target with its per-source fidelity tier and options schema.
* ``POST /v1/internal/mcp/export/run`` — runs an export job (``schedule_export_job``, the same pipeline
  as ``POST /v1/export/{tenant}/jobs``) and waits a bounded time for it. A completed job answers with
  the full fidelity envelope (tier, the structured ``LossinessReport``, the advisory), the transcoding
  guard, the validation and delivery decisions, and the files — **inline** when they are small enough
  (``APIOME_MCP_EXPORT_INLINE_MAX_BYTES``), otherwise as a download reference. A job still running when
  the wait ends answers ``state: running`` with its ``jobId``; sending that ``jobId`` back collects it.

**Lossy conversions need ``allowLossy``** (MFX-40.2, #4340) — the CLI ``--force`` of MFX-8.2 for agents.
Before scheduling, ``run`` predicts the fidelity of (source, target, options) with the dispatch's dry run;
a tier other than ``lossless`` without ``allowLossy: true`` answers ``state: blocked`` with the report and
the advisory and emits **nothing** (no job, no files). Every answer that carries a fidelity envelope also
carries ``advisory`` — the canonical MFX-2.4 ``ExportAdvisory.message``, the very string the UI, the browse
page and the CLI render, so an agent reads the same words a person does.

Both routes are **internal**: they trust the ``tenantId`` the MCP server sends, so they require the
shared ``X-Internal-Service-Token`` (``INTERNAL_SERVICE_TOKEN``) and are fail-closed without it.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth_provider_resolved_routes import require_internal_service
from .config import settings
from .database import db
from .export_dispatch import dispatch_from_source
from .export_fidelity import ExportFidelityTier
from .export_job_engine import (
    ExportJobStartRequest,
    get_export_job_emit_result,
    get_export_job_status,
    schedule_export_job,
    serialize_file_content,
)
from .export_routes import ExportTargetsResponse, build_target_fidelity_entries
from .export_service import ExportError
from .export_source import ExportSourceError, load_export_source

router = APIRouter(prefix="/v1/internal/mcp/export", tags=["internal-mcp-export"],
                   dependencies=[Depends(require_internal_service)])

#: How long ``version.export`` waits for a job by default, and at most, in seconds.
DEFAULT_WAIT_SECONDS = 60
MAX_WAIT_SECONDS = 300
#: Seconds between status reads while waiting.
POLL_SECONDS = 0.25


class McpExportTargetsRequest(BaseModel):
    """``export.targets``: which source's targets."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    tenant_id: str = Field(alias="tenantId", description="The MCP key's tenant (trusted: internal route).")
    artifact: str = Field(description="The artifact (project or catalog item) id.")
    version: Optional[str] = Field(default=None, description="Revision id or label; the latest when omitted.")


class McpExportRunRequest(BaseModel):
    """``version.export``: start an export (``target``) or collect one (``jobId``)."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    tenant_id: str = Field(alias="tenantId", description="The MCP key's tenant (trusted: internal route).")
    artifact: Optional[str] = Field(default=None, description="The artifact id (required to start a job).")
    version: Optional[str] = Field(default=None, description="Revision id or label; the latest when omitted.")
    target: Optional[str] = Field(default=None, description="Any registered target key (`export.targets`).")
    options: Optional[Dict[str, Any]] = Field(default=None, description="The target's emit options (MFX-1.4).")
    confirm: bool = Field(default=False, description="Proceed with a severe conversion (MFX-3.3).")
    allow_lossy: bool = Field(default=False, alias="allowLossy",
                              description="Emit even when the conversion loses fidelity (MFX-40.2; the CLI "
                              "`--force`). Without it a lossy conversion answers `blocked` and emits nothing.")
    job_id: Optional[str] = Field(default=None, alias="jobId",
                                  description="Collect a job a previous call left running, instead of starting one.")
    wait_seconds: int = Field(default=DEFAULT_WAIT_SECONDS, alias="waitSeconds", ge=0, le=MAX_WAIT_SECONDS,
                              description="How long to wait for the job before answering `running`.")


class McpExportFile(BaseModel):
    """One emitted file: its path, type and size, and its content when inline."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str
    media_type: Optional[str] = Field(default=None, serialization_alias="mediaType")
    size_bytes: int = Field(serialization_alias="sizeBytes")
    content: Optional[str] = Field(default=None, description="The file's text, when the files are inline.")


class McpExportRunResponse(BaseModel):
    """What ``version.export`` answers.

    Attributes:
        job_id: The export job; ``None`` when ``blocked`` (no job was started).
        state: ``blocked`` (a lossy conversion without ``allowLossy``: nothing emitted), ``queued`` /
            ``running`` (collect it again with ``jobId``), ``completed``, ``failed`` or ``canceled``.
        advisory: The canonical fidelity advisory (MFX-2.4 ``ExportAdvisory.message``) — word for word
            what the UI, browse and the CLI show; ``None`` until the fidelity is known.
        fidelity: The full fidelity envelope of a one-target export: tier, the structured
            ``LossinessReport`` (``report``), the advisory.
        guard: The transcoding guard (MFX-3.3): verdict, whether it needs ``confirm``.
        files: The emitted files; each carries ``content`` when ``content_inline``.
        download_path: The REST download of the whole artifact, for files too large to inline.
        error: The structured failure of a failed job.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    job_id: Optional[str] = Field(default=None, serialization_alias="jobId")
    state: Literal["blocked", "queued", "running", "completed", "failed", "canceled"]
    advisory: Optional[str] = None
    artifact: Optional[str] = None
    target: Optional[str] = None
    version_record_id: Optional[str] = Field(default=None, serialization_alias="versionRecordId")
    version_label: Optional[str] = Field(default=None, serialization_alias="versionLabel")
    fidelity: Optional[Dict[str, Any]] = None
    guard: Optional[Dict[str, Any]] = None
    validation: Optional[Dict[str, Any]] = None
    delivery: Optional[Dict[str, Any]] = None
    media_type: Optional[str] = Field(default=None, serialization_alias="mediaType")
    files: List[McpExportFile] = Field(default_factory=list)
    content_inline: bool = Field(default=False, serialization_alias="contentInline")
    download_path: Optional[str] = Field(default=None, serialization_alias="downloadPath")
    error: Optional[Dict[str, Any]] = None


def _tenant_slug(tenant_id: str) -> str:
    """The tenant's slug, or 404 for a tenant that does not exist."""
    slug = db.get_tenant_slug_by_id(tenant_id)
    if not slug:
        raise HTTPException(status_code=404, detail={"code": "mcp-export-tenant-unknown",
                                                     "message": "The key's tenant does not exist."})
    return slug


def _dump(model: Any) -> Optional[Dict[str, Any]]:
    return model.model_dump(mode="json") if model is not None else None


def _files(tenant_slug: str, job_id: str, result: Any) -> tuple[List[McpExportFile], bool]:
    """The job's files, with their text inline when the whole set fits the inline cap."""
    listed = list(result.files or [])
    emitted = get_export_job_emit_result(tenant_slug, job_id)
    total = sum(int(f.size_bytes or 0) for f in listed)
    inline = emitted is not None and total <= int(settings.mcp_export_inline_max_bytes)
    contents: Dict[str, str] = {}
    if inline:
        contents = {f.path: serialize_file_content(f.content) for f in emitted.files}
    return [McpExportFile(path=f.path, media_type=f.media_type, size_bytes=int(f.size_bytes or 0),
                          content=contents.get(f.path) if inline else None) for f in listed], inline


def _advisory_message(fidelity: Optional[Dict[str, Any]]) -> Optional[str]:
    """The canonical advisory string of a dumped fidelity envelope (MFX-2.4), or ``None``."""
    advisory = (fidelity or {}).get("advisory")
    return advisory.get("message") if isinstance(advisory, dict) else None


def lossy_preflight(tenant_id: str, body: McpExportRunRequest) -> Optional[McpExportRunResponse]:
    """Refuse to emit a lossy conversion the caller did not allow (MFX-40.2).

    Predicts the fidelity of (source, target, options) with the dispatch's dry run — the builder the
    preview and the export job share, so the prediction is the export's own report — and, when the tier
    is not ``lossless`` and ``allow_lossy`` is unset, answers ``blocked`` with the report and the
    canonical advisory. Nothing is emitted and no job is started.

    Args:
        tenant_id: The tenant (scopes the source lookup).
        body: The export to start.

    Returns:
        The ``blocked`` answer, or ``None`` when the export may proceed (lossless, or ``allow_lossy``).

    Raises:
        ExportSourceError: For an unknown artifact / version or a source that cannot be rebuilt.
        ExportError: For an unknown target or invalid options.
    """
    if body.allow_lossy:
        return None
    source = load_export_source(tenant_id, body.artifact, body.version)
    dry = dispatch_from_source(source, body.target or "", options=body.options, dry_run=True)
    if dry.fidelity.summary.tier == ExportFidelityTier.LOSSLESS:
        return None
    fidelity = _dump(dry.fidelity)
    return McpExportRunResponse(
        state="blocked", artifact=dry.artifact, target=dry.target, version_record_id=dry.version_record_id,
        version_label=dry.version_label, advisory=_advisory_message(fidelity), fidelity=fidelity,
        guard=_dump(dry.guard),
        error={"code": "mcp-export-lossy-not-allowed",
               "message": "This conversion loses fidelity; nothing was emitted. Read the advisory and the "
                          "report, then call again with allow_lossy: true to export anyway."},
    )


def run_response(tenant_slug: str, job_id: str, status: Any) -> McpExportRunResponse:
    """Project a job's status onto the ``version.export`` answer.

    Args:
        tenant_slug: The tenant the job runs under.
        job_id: The job.
        status: Its ``ExportJobStatus``.

    Returns:
        The answer — the fidelity report, guard and files for a completed job; the error for a failed one.
    """
    response = McpExportRunResponse(job_id=job_id, state=status.state, error=_dump(status.error))
    result = status.result
    if result is None:
        return response
    files, inline = _files(tenant_slug, job_id, result) if status.state == "completed" else ([], False)
    fidelity = _dump(result.fidelity)
    return response.model_copy(update={
        "advisory": _advisory_message(fidelity), "fidelity": fidelity,
        "artifact": result.artifact, "target": result.target, "version_record_id": result.version_record_id,
        "version_label": result.version_label, "guard": _dump(result.guard),
        "validation": _dump(getattr(result, "validation", None)), "delivery": _dump(getattr(result, "delivery", None)),
        "media_type": result.media_type, "files": files, "content_inline": inline,
        "download_path": result.download_path,
    })


@router.post(
    "/targets",
    response_model=ExportTargetsResponse,
    summary="Export targets for the MCP `export.targets` tool",
    description="Internal (`X-Internal-Service-Token`). The same answer as `GET /v1/export/{tenant}/targets` for "
    "the given tenant: every registered target with its per-source fidelity tier.",
)
async def mcp_export_targets(body: McpExportTargetsRequest) -> ExportTargetsResponse:
    """List every registered export target with its fidelity for one source.

    Args:
        body: The tenant and source.

    Returns:
        The per-target fidelity list.

    Raises:
        HTTPException: 404 for an unknown tenant or artifact/version; 422 / 400 as the targets route.
    """
    await asyncio.to_thread(_tenant_slug, body.tenant_id)
    try:
        source = await asyncio.to_thread(load_export_source, body.tenant_id, body.artifact, body.version)
    except ExportSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail()) from exc
    return ExportTargetsResponse(
        artifact=source.artifact_id, version=body.version, version_record_id=source.version_record_id,
        version_label=source.version_label, targets=build_target_fidelity_entries(source.api),
    )


@router.post(
    "/run",
    response_model=McpExportRunResponse,
    response_model_by_alias=True,
    summary="Run an export for the MCP `version.export` tool",
    description=(
        "Internal (`X-Internal-Service-Token`). Starts an export job for any registered `target` (the pipeline of "
        "`POST /v1/export/{tenant}/jobs`) and waits up to `waitSeconds`; or, with `jobId`, collects a job a previous "
        "call left running. A conversion that loses fidelity (tier other than `lossless`) "
        "without `allowLossy` answers `state: blocked` with the report and the canonical `advisory` and emits "
        "nothing. A completed job answers with the fidelity envelope (including the structured "
        "`LossinessReport`), the guard and the files — inline up to `APIOME_MCP_EXPORT_INLINE_MAX_BYTES`, otherwise "
        "with `downloadPath`. `400` / `422` for an unknown target or invalid options; `429` when the tenant's export "
        "slots are full; `404` for an unknown job."
    ),
)
async def mcp_export_run(body: McpExportRunRequest) -> McpExportRunResponse:
    """Start (or collect) one export job and answer with its outcome.

    Args:
        body: The tenant and either the export to start or the job to collect.

    Returns:
        The job's state and, when completed, its fidelity report and files.

    Raises:
        HTTPException: 400 / 422 for an invalid request, unknown target or options; 404 for an unknown
            tenant or job; 429 when the tenant already runs its maximum of export jobs.
    """
    tenant_slug = await asyncio.to_thread(_tenant_slug, body.tenant_id)
    if body.job_id:
        job_id = body.job_id
    else:
        if not body.artifact or not body.target:
            raise HTTPException(status_code=400, detail={"code": "mcp-export-invalid",
                                                         "message": "Name an `artifact` and a `target`, or a `jobId`."})
        try:
            blocked = await asyncio.to_thread(lossy_preflight, body.tenant_id, body)
            if blocked is not None:
                return blocked
            request = ExportJobStartRequest(artifact=body.artifact, version=body.version, target=body.target,
                                            options=body.options, confirm=body.confirm)
            accepted = await schedule_export_job(tenant_slug, body.tenant_id, request)
        except ExportSourceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.http_detail()) from exc
        except ExportError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": "mcp-export-refused",
                                                                     "message": str(exc)}) from exc
        except ValueError as exc:  # a pydantic ValidationError is a ValueError
            raise HTTPException(status_code=422, detail={"code": "mcp-export-invalid", "message": str(exc)}) from exc
        job_id = accepted.job_id
    deadline = time.monotonic() + body.wait_seconds
    while True:
        status = await get_export_job_status(tenant_slug, job_id)  # 404 for an unknown job
        if status.state in ("completed", "failed", "canceled") or time.monotonic() >= deadline:
            return run_response(tenant_slug, job_id, status)
        await asyncio.sleep(POLL_SECONDS)
