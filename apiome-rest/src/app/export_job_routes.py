"""Async export job REST surface — MFX-3.1 (#3844).

The job counterpart of the synchronous export endpoints in :mod:`app.export_routes`:
where ``POST /export/{tenant_slug}/document`` emits inline and ``POST …/preview``
predicts fidelity inline, ``POST /export/{tenant_slug}/jobs`` runs the same pipeline
asynchronously — submit, poll, terminal state — for large or toolchain-backed exports.

The route layout and status contract deliberately mirror the spec-import surface
(:mod:`app.spec_import_routes`):

* ``POST   /v1/export/{tenant_slug}/jobs``          → 202 + ``{job_id, status_path}``
* ``GET    /v1/export/{tenant_slug}/jobs``          → summary list (in-memory, per process)
* ``GET    /v1/export/{tenant_slug}/jobs/{job_id}`` → ``{job_id, state, percent, events, progress, result}``
* ``DELETE /v1/export/{tenant_slug}/jobs/{job_id}`` → 204 cancel request

All routes are tenant-scoped (JWT or API key) via :func:`app.auth.validate_authentication`,
like the sibling export endpoints.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Response

from .auth import validate_authentication
from .export_job_engine import (
    ExportJobAccepted,
    ExportJobListResponse,
    ExportJobStartRequest,
    ExportJobStatus,
    schedule_export_job,
)
from .export_job_engine import (
    cancel_export_job as engine_cancel_export_job,
)
from .export_job_engine import (
    get_export_job_status as engine_get_export_job_status,
)
from .export_job_engine import (
    list_export_jobs as engine_list_export_jobs,
)
from .export_service import ExportError

router = APIRouter(prefix="/v1/export", tags=["export-jobs"])


@router.post(
    "/{tenant_slug}/jobs",
    status_code=202,
    response_model=ExportJobAccepted,
    summary="Start an asynchronous export job",
    description=(
        "Submit an export of one artifact/version to one target through the async job "
        "pipeline: load source → fidelity report → emit → validate → package. "
        "``dry_run: true`` stops after the fidelity report (no artifact), the async twin "
        "of ``POST …/preview``. Poll the returned ``status_path`` for progress; the "
        "status contract matches the spec-import job surface."
    ),
)
async def start_export_job(
    tenant_slug: str,
    request: ExportJobStartRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportJobAccepted:
    """Accept an export job for background execution.

    Args:
        tenant_slug: The tenant slug (scopes the job and the artifact lookup).
        request: Source coordinates + target + options + dry-run flag.
        auth_data: Authenticated tenant context (JWT or API key).

    Returns:
        The 202 acceptance payload (job id + poll path).

    Raises:
        HTTPException: 400 when the target is unknown; 422 when the emit options are
            invalid for the target. Source-related failures (unknown artifact/version,
            no reconstructable source) surface asynchronously in the job status.
    """
    tenant_id = str(auth_data["tenant_id"])
    try:
        return await schedule_export_job(tenant_slug, tenant_id, request)
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get(
    "/{tenant_slug}/jobs",
    response_model=ExportJobListResponse,
    summary="List export jobs",
    description=(
        "Jobs tracked in this API process for the tenant (in-memory). After a restart "
        "the list is empty; use GET …/jobs/{job_id} for a job's full event history."
    ),
)
async def list_export_jobs(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportJobListResponse:
    """List the tenant's export jobs known to this process.

    Args:
        tenant_slug: The tenant slug the jobs were submitted under.
        auth_data: Authenticated tenant context (JWT or API key).

    Returns:
        Summary rows (state, percent, progress) without event logs or fidelity envelopes.
    """
    _ = auth_data
    return await engine_list_export_jobs(tenant_slug)


@router.get(
    "/{tenant_slug}/jobs/{job_id}",
    response_model=ExportJobStatus,
    summary="Get export job status",
    description=(
        "Poll payload for one export job: state, percent, structured events, coarse "
        "progress, and — once completed — the result (resolved coordinates, fidelity "
        "envelope, and the emitted-file manifest; a dry-run carries the report only)."
    ),
)
async def get_export_job_status(
    tenant_slug: str,
    job_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportJobStatus:
    """Return the current status of one export job.

    Args:
        tenant_slug: The tenant slug the job was submitted under.
        job_id: The job id from the 202 acceptance payload.
        auth_data: Authenticated tenant context (JWT or API key).

    Returns:
        The job's poll payload.

    Raises:
        HTTPException: 404 when the job is unknown for this tenant (or the process restarted).
    """
    _ = auth_data
    return engine_get_export_job_status(tenant_slug, job_id)


@router.delete(
    "/{tenant_slug}/jobs/{job_id}",
    status_code=204,
    summary="Cancel an export job",
    description=(
        "Request cancellation. The pipeline stops at its next stage boundary; a job "
        "already in a terminal state is left unchanged (the request is a no-op)."
    ),
)
async def cancel_export_job(
    tenant_slug: str,
    job_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    # NB: return a Response (not `-> None`) — under `from __future__ import annotations`
    # FastAPI evaluates a `None` return annotation to NoneType and asserts that a 204
    # cannot carry a body. Mirrors the spec-import cancel route.
    _ = auth_data
    await engine_cancel_export_job(tenant_slug, job_id)
    return Response(status_code=204)
