"""Async export jobs — the export-side mirror of :mod:`app.spec_import_engine` — MFX-3.1 (#3844).

Large exports (multi-file, toolchain-backed targets) need the same asynchronous job
lifecycle the spec-import path has: submit → poll → terminal state. This module is that
engine. A job is submitted with the source coordinates (artifact/version), a target
(emitter key or format key), optional per-target emit options, and a ``dry_run`` flag,
and then runs through the export pipeline in the background:

1. **load source** — rebuild the revision's :class:`~app.canonical_model.CanonicalApi`
   (:func:`app.export_source.load_export_source`, the MFX-2.5 loader);
2. **analyze fidelity** — compute the full :class:`~app.export_fidelity.ExportFidelity`
   envelope (:func:`app.export_fidelity.build_export_fidelity`), byte-identical to what
   ``POST /export/preview`` returns for the same inputs;
3. **dry-run gate** — a ``dry_run`` job completes here: the result carries the fidelity
   report and **no artifact**;
4. **emit** — run the registered emitter through the Emitter SPI
   (:func:`app.export_service.emit_canonical`), with field-identity persistence;
5. **validate** — the MFX-EPIC-5 seam (:func:`validate_emitted_result`): round-trip the
   output through the matching import parser. Today a documented no-op placeholder;
6. **package** — the MFX-EPIC-4 seam (:func:`build_result_manifest`): reduce the emitted
   files to a download manifest. The raw :class:`~app.emitter.EmitResult` stays on the
   in-memory job record (:func:`get_export_job_emit_result`) so the delivery epics can
   serve bytes without re-emitting.

The status/polling contract deliberately matches the import engine's: the same job-record
store (in-memory, per-process, tenant-scoped), the same state vocabulary (a subset —
exports have no two-phase commit, so no ``pending-approval``/``committing``/``rolled-back``),
the same ``{job_id, state, percent, events, progress, result}`` poll payload shape, and the
same 202-accepted + ``status_path`` submission response.

Unlike imports (which shell out to the ``apiome-ui`` ``tsx`` worker for OpenAPI), the whole
export pipeline is in-process Python. Jobs are driven on the engine's own process-lifetime
event loop (a daemon thread), never on the submitting request's loop, so a job always
outlives its request; blocking stages run via :func:`asyncio.to_thread` so that loop stays
responsive, and a cancel request takes effect at the next stage boundary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .emitter import EmitResult
from .export_fidelity import ExportFidelity, build_export_fidelity
from .export_service import (
    ExportError,
    ExportPersistenceContext,
    emit_canonical,
    resolve_emit_format,
    resolve_emit_options,
    resolve_emitter,
)
from .export_source import ExportSource, ExportSourceError, load_export_source
from .lossiness import LossinessSeverity
from .transcoding_guards import TranscodeGuard, classify_transcode

logger = logging.getLogger(__name__)

__all__ = [
    "ExportJobState",
    "ExportJobEvent",
    "ExportJobProgress",
    "ExportJobStartRequest",
    "ExportJobFile",
    "ExportJobResult",
    "ExportJobStatus",
    "ExportJobListItem",
    "ExportJobListResponse",
    "ExportJobAccepted",
    "schedule_export_job",
    "get_export_job_status",
    "list_export_jobs",
    "cancel_export_job",
    "get_export_job_emit_result",
    "validate_emitted_result",
    "build_result_manifest",
]


# ===========================================================================
# Job models (the poll contract — field-for-field the import job shapes)
# ===========================================================================

# The import state vocabulary minus the two-phase-commit states: an export never holds an
# open transaction, so there is nothing to approve, commit, or roll back.
ExportJobState = Literal["queued", "running", "completed", "failed", "canceled"]

# A pending event as (level, code, message, context), before it is sequenced onto a job.
_EventTuple = tuple[str, str, str, Optional[Dict[str, Any]]]

_TERMINAL_STATES = frozenset({"completed", "failed", "canceled"})

# Pipeline stages in run order, with the percent the job reports while the stage runs.
# ``finalizing`` percent is implicit (100 on completion).
_STAGE_PERCENT = {
    "loading-source": 10,
    "analyzing-fidelity": 30,
    "emitting": 55,
    "validating": 75,
    "packaging": 90,
}
_STAGES: List[str] = list(_STAGE_PERCENT)


class ExportJobEvent(BaseModel):
    """Structured log line from an export job (same shape as an import job event)."""

    model_config = ConfigDict(extra="allow")

    id: str
    ts: int
    level: Literal["info", "warn", "error"]
    code: str
    message: str
    context: Optional[Dict[str, Any]] = None


class ExportJobProgress(BaseModel):
    """Coarse-grained progress snapshot (mirrors the import job's progress shape)."""

    model_config = ConfigDict(extra="forbid")

    phase: Literal[
        "loading-source",
        "analyzing-fidelity",
        "emitting",
        "validating",
        "packaging",
    ]
    total: int = Field(description="Total pipeline stages for this job.")
    completed: int = Field(description="Stages finished so far.")
    current_item: Optional[str] = Field(
        default=None, description="Human hint for the stage (e.g. the target key)."
    )


class ExportJobStartRequest(BaseModel):
    """Submit an export job: source coordinates + target + options + dry-run flag.

    The source half matches ``POST /export/preview`` / ``POST /export/document``
    (MFX-2.5/11.5); ``dry_run`` selects the preview-only path (fidelity report, no
    artifact), the async twin of the synchronous ``/export/preview`` endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id to export.")
    version: Optional[str] = Field(
        default=None,
        description="Revision UUID, version label (``1.0.0``), or null for the latest revision.",
    )
    target: str = Field(
        description="Target emitter key (``openapi``) or format key (``openapi-3.1``).",
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Per-target emit options (MFX-1.4); null or empty applies the target defaults.",
    )
    dry_run: bool = Field(
        default=False,
        description="When true, stop after the fidelity report: no artifact is emitted.",
    )
    confirm: bool = Field(
        default=False,
        description="When true, proceed with a **severe** conversion (MFX-3.3) the transcoding "
        "guard would otherwise fail the job on. Ignored for non-severe conversions and dry-runs.",
    )
    min_severity: LossinessSeverity = Field(
        default=LossinessSeverity.INFO,
        description="Lowest loss severity that raises the advisory (MFX-2.4); does not affect "
        "the report or counts.",
    )


class ExportJobFile(BaseModel):
    """One emitted file's manifest entry — metadata only, never the content.

    The delivery epics (MFX-4.x) serve the bytes; the job result carries just enough
    for a caller to show what was produced and how large it is.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Relative path within the output bundle.")
    media_type: Optional[str] = Field(
        default=None, description="The file's media type when it differs from the bundle default."
    )
    size_bytes: int = Field(description="Serialized size of the file's content in bytes.")
    subject: Optional[str] = Field(
        default=None,
        description="Schema Registry subject when the target assigns one (e.g. Avro).",
    )


class ExportJobResult(BaseModel):
    """What a terminal ``completed`` export job produced.

    Carries the resolved source coordinates, the resolved target, the full
    :class:`~app.export_fidelity.ExportFidelity` envelope (identical to a ``/export/preview``
    of the same inputs), and — for a real (non-dry-run) export — the emitted file manifest.
    """

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id the job exported.")
    version_record_id: str = Field(description="The resolved revision (``versions.id``).")
    version_label: Optional[str] = Field(
        default=None, description="The resolved revision's version label (e.g. ``1.0.0``)."
    )
    target: str = Field(description="The resolved target format key (e.g. ``openapi-3.1``).")
    dry_run: bool = Field(description="True when the job stopped after the fidelity report.")
    fidelity: ExportFidelity = Field(
        description="The full fidelity envelope (target + tier + report + advisory).",
    )
    guard: TranscodeGuard = Field(
        description="The pre-flight transcoding guard (MFX-3.3): the conversion band and why. "
        "A severe conversion only completes when it was submitted with ``confirm``.",
    )
    files: List[ExportJobFile] = Field(
        default_factory=list,
        description="Manifest of emitted files; empty for a dry-run.",
    )
    media_type: Optional[str] = Field(
        default=None,
        description="The bundle's primary media type; null for a dry-run.",
    )


class ExportJobStatus(BaseModel):
    """Poll payload for an export job (same shape as the import job status)."""

    job_id: str
    state: ExportJobState
    percent: int = Field(0, ge=0, le=100)
    events: List[ExportJobEvent] = Field(default_factory=list)
    progress: Optional[ExportJobProgress] = None
    result: Optional[ExportJobResult] = None


class ExportJobListItem(BaseModel):
    """Summary row for GET …/jobs (no event log, no full fidelity envelope)."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    state: ExportJobState
    percent: int = Field(0, ge=0, le=100)
    status_path: str = Field(description="Relative URL for GET …/jobs/{job_id}.")
    artifact: str = Field(description="The artifact (project) id being exported.")
    target: str = Field(description="The requested target (as submitted).")
    dry_run: bool = Field(description="True when the job is a fidelity-only dry-run.")
    progress: Optional[ExportJobProgress] = None


class ExportJobListResponse(BaseModel):
    """Tenant-scoped export jobs visible to this API process."""

    model_config = ConfigDict(extra="forbid")

    jobs: List[ExportJobListItem]


class ExportJobAccepted(BaseModel):
    """Returned when a job is accepted (HTTP 202) — mirrors the import acceptance."""

    job_id: str
    status_path: str = Field(
        description="Relative URL path for GET …/jobs/{job_id} until the job reaches a terminal state.",
    )


# ===========================================================================
# In-memory job store (per-process, tenant-scoped — same model as imports)
# ===========================================================================


@dataclass
class _ExportJobRecord:
    """One tracked export job. Mutated only under :data:`_jobs_lock`."""

    tenant_slug: str
    tenant_id: str
    job_id: str
    state: str
    status: ExportJobStatus
    request: ExportJobStartRequest
    cancel_requested: bool = False
    # Sequence for event ids ("export-1", "export-2", …) within this job.
    event_seq: int = 0
    # The raw emit result, retained so the delivery epics (MFX-4.x) can serve the
    # emitted bytes without re-running the emitter. None until emit succeeds.
    emit_result: Optional[EmitResult] = None


_jobs: Dict[str, _ExportJobRecord] = {}
# A *threading* lock, not an asyncio one: critical sections are short, purely synchronous
# dict/model mutations (no awaits while held), and the job store is touched from the
# caller's event loop, the engine loop (below), and worker threads alike. An asyncio.Lock
# would additionally bind to whichever event loop first contends on it.
_jobs_lock = threading.Lock()

# The dedicated, process-lifetime event loop that drives job pipelines. Jobs must not run
# on the submitting HTTP request's loop: a pipeline with real blocking stages outlives the
# request, and under some server/test harnesses (per-request portals) that loop is torn
# down when the response is sent, which would strand the job mid-flight. Lazily started as
# a daemon thread on first submission.
_engine_loop: Optional[asyncio.AbstractEventLoop] = None
_engine_loop_lock = threading.Lock()


def _get_engine_loop() -> asyncio.AbstractEventLoop:
    """Return the engine's own event loop, starting its daemon thread on first use."""
    global _engine_loop
    with _engine_loop_lock:
        if _engine_loop is None or _engine_loop.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever, name="export-job-engine", daemon=True
            )
            thread.start()
            _engine_loop = loop
        return _engine_loop


def _now_ms() -> int:
    """Current wall-clock time in epoch milliseconds (event timestamps)."""
    return int(time.time() * 1000)


def _next_event(rec: _ExportJobRecord, level: str, code: str, message: str,
                context: Optional[Dict[str, Any]] = None) -> ExportJobEvent:
    """Build the next sequenced event for ``rec``. Call under :data:`_jobs_lock`."""
    rec.event_seq += 1
    return ExportJobEvent(
        id=f"export-{rec.event_seq}",
        ts=_now_ms(),
        level=level,  # type: ignore[arg-type]
        code=code,
        message=message,
        context=context,
    )


def _log_event(job_id: str, event: ExportJobEvent) -> None:
    """Mirror a job event into the REST log at its level (like import event logging)."""
    line = f"export job={job_id} [{event.code}] {event.message}"
    if event.level == "error":
        logger.error(line)
    elif event.level == "warn":
        logger.warning(line)
    else:
        logger.info(line)


async def _publish(
    job_id: str,
    *,
    state: Optional[str] = None,
    percent: Optional[int] = None,
    stage: Optional[str] = None,
    event: Optional[_EventTuple] = None,
    result: Optional[ExportJobResult] = None,
) -> bool:
    """Apply one snapshot update to the job record; return False if the job is gone/canceled.

    ``event`` is ``(level, code, message, context)``; ``stage`` updates the progress
    snapshot (its position in :data:`_STAGES` gives total/completed). A job whose cancel
    flag is set is finalized to ``canceled`` here — the single stage-boundary cancel point.
    """
    logged: Optional[ExportJobEvent] = None
    with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None:
            return False
        if rec.cancel_requested and rec.state not in _TERMINAL_STATES:
            rec.state = "canceled"
            rec.status = ExportJobStatus(
                job_id=job_id,
                state="canceled",
                percent=rec.status.percent,
                events=rec.status.events,
                progress=rec.status.progress,
            )
            return False
        if state is not None:
            rec.state = state
            rec.status.state = state  # type: ignore[assignment]
        if percent is not None:
            rec.status.percent = percent
        if stage is not None:
            rec.status.progress = ExportJobProgress(
                phase=stage,  # type: ignore[arg-type]
                total=len(_STAGES),
                completed=_STAGES.index(stage),
                current_item=rec.request.target,
            )
        if event is not None:
            level, code, message, context = event
            logged = _next_event(rec, level, code, message, context)
            rec.status.events.append(logged)
        if result is not None:
            rec.status.result = result
    # Log outside the lock (logging handlers can block).
    if logged is not None:
        _log_event(job_id, logged)
    return True


async def _fail(job_id: str, code: str, message: str,
                context: Optional[Dict[str, Any]] = None) -> None:
    """Move a job to ``failed`` with one terminal error event."""
    await _publish(
        job_id,
        state="failed",
        event=("error", code, message, context),
    )


# ===========================================================================
# EPIC seams (replaced/extended by later roadmap tickets)
# ===========================================================================


def validate_emitted_result(result: EmitResult, target_format: str) -> List[_EventTuple]:
    """Round-trip validation seam (MFX-EPIC-5): validate the emitted artifact.

    MFX-5.1 feeds the emitted output back through the matching MFI import parser and
    MFX-5.3 gates delivery on the outcome. Until those land, this placeholder records
    that validation was **deferred, not passed** — the job stays honest about what ran.

    Args:
        result: The emitter's output bundle.
        target_format: The resolved target format key (selects the future parser).

    Returns:
        Event tuples ``(level, code, message, context)`` to append to the job's event log.
    """
    _ = result
    return [
        (
            "info",
            "VALIDATION_DEFERRED",
            "Round-trip validation of the emitted artifact is not implemented yet "
            "(lands with MFX-5.1/5.3); the artifact was not re-parsed.",
            {"target": target_format},
        )
    ]


def _serialized_size(content: Any) -> int:
    """Byte size of an emitted file's content as it would be serialized for download."""
    if isinstance(content, dict):
        return len(json.dumps(content, indent=2, ensure_ascii=False).encode("utf-8"))
    return len(str(content).encode("utf-8"))


def build_result_manifest(result: EmitResult) -> List[ExportJobFile]:
    """Packaging seam (MFX-EPIC-4): reduce an emit result to a download manifest.

    MFX-4.1/4.2 add single-file download and zip bundling on top of the retained
    :class:`~app.emitter.EmitResult`; the job result itself carries only this metadata
    manifest so poll payloads stay small.

    Args:
        result: The emitter's output bundle.

    Returns:
        One :class:`ExportJobFile` per emitted file, in the emitter's (path-sorted) order.
    """
    return [
        ExportJobFile(
            path=f.path,
            media_type=f.media_type,
            size_bytes=_serialized_size(f.content),
            subject=f.subject,
        )
        for f in result.files
    ]


# ===========================================================================
# Pipeline
# ===========================================================================


async def _drive_export_job(job_id: str) -> None:
    """Run one export job through the pipeline, publishing progress after each stage.

    Every blocking stage (DB-backed source load, fidelity walk, emit) runs in a worker
    thread; the cancel flag is honoured at each stage boundary via :func:`_publish`.
    Any fault is converted to a terminal ``failed`` status — this task never raises.
    """
    with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None:
            return
        request = rec.request
        tenant_id = rec.tenant_id

    try:
        if not await _publish(
            job_id,
            state="running",
            percent=_STAGE_PERCENT["loading-source"],
            stage="loading-source",
            event=(
                "info",
                "EXPORT_STARTED",
                f"Export to {request.target!r} started"
                + (" (dry-run: fidelity report only)" if request.dry_run else ""),
                {"artifact": request.artifact, "target": request.target,
                 "dry_run": request.dry_run},
            ),
        ):
            return

        # --- Stage 1: load the source canonical model (DB-bound) -------------------
        try:
            source: ExportSource = await asyncio.to_thread(
                load_export_source, tenant_id, request.artifact, request.version
            )
        except ExportSourceError as exc:
            await _fail(job_id, "SOURCE_LOAD_FAILED", str(exc),
                        {"status_code": exc.status_code})
            return

        if not await _publish(
            job_id,
            percent=_STAGE_PERCENT["analyzing-fidelity"],
            stage="analyzing-fidelity",
            event=(
                "info",
                "SOURCE_LOADED",
                f"Loaded revision {source.version_record_id} "
                f"(version {source.version_label or 'latest'}) of artifact {source.artifact_id}",
                {"version_record_id": source.version_record_id,
                 "version_label": source.version_label},
            ),
        ):
            return

        # --- Stage 2: fidelity envelope (pure CPU; same builder as /export/preview) -
        try:
            emitter_cls = type(resolve_emitter(request.target))
            target_format = resolve_emit_format(request.target)
        except ExportError as exc:
            # The submit path validates the target, but the registry is re-consulted
            # here; a mid-flight registry change must fail the job, not crash the task.
            await _fail(job_id, "UNSUPPORTED_TARGET", str(exc),
                        {"status_code": exc.status_code})
            return

        fidelity: ExportFidelity = await asyncio.to_thread(
            build_export_fidelity,
            source.api,
            emitter_cls,
            min_severity=request.min_severity,
        )
        # Classify the conversion off the envelope's report (MFX-3.3), so the job's guard and
        # the /preview guard agree and the pre-flight gate can refuse a severe conversion.
        guard: TranscodeGuard = classify_transcode(
            source.api, emitter_cls, report=fidelity.report
        )

        if not await _publish(
            job_id,
            event=(
                "info",
                "FIDELITY_COMPUTED",
                f"Fidelity: {fidelity.summary.tier.value}, "
                f"{fidelity.summary.preserved_percent}% preserved "
                f"({fidelity.summary.total} constructs); transcode guard: {guard.verdict.value}",
                {"tier": fidelity.summary.tier.value,
                 "preserved_percent": fidelity.summary.preserved_percent,
                 "guard": guard.verdict.value},
            ),
        ):
            return

        # --- Dry-run gate: report only, no artifact ---------------------------------
        if request.dry_run:
            result = ExportJobResult(
                artifact=source.artifact_id,
                version_record_id=source.version_record_id,
                version_label=source.version_label,
                target=target_format,
                dry_run=True,
                fidelity=fidelity,
                guard=guard,
                files=[],
                media_type=None,
            )
            await _publish(
                job_id,
                state="completed",
                percent=100,
                result=result,
                event=("info", "DRY_RUN_COMPLETED",
                       "Dry-run finished: fidelity report attached, no artifact emitted.",
                       None),
            )
            return

        # --- Transcode guard gate (MFX-3.3): a severe conversion needs explicit confirmation ---
        if guard.requires_confirmation and not request.confirm:
            await _fail(
                job_id,
                "TRANSCODE_CONFIRMATION_REQUIRED",
                guard.message,
                {"verdict": guard.verdict.value,
                 "reasons": guard.reasons,
                 "preserved_percent": guard.preserved_percent},
            )
            return

        # --- Stage 3: emit through the Emitter SPI ----------------------------------
        if not await _publish(job_id, percent=_STAGE_PERCENT["emitting"], stage="emitting"):
            return
        try:
            emit_result: EmitResult = await asyncio.to_thread(
                emit_canonical,
                source.api,
                request.target,
                opts=request.options,
                persistence=ExportPersistenceContext(
                    tenant_id=tenant_id, artifact_id=source.artifact_id
                ),
            )
        except ExportError as exc:
            await _fail(job_id, "EMIT_FAILED", str(exc), {"status_code": exc.status_code})
            return

        if not emit_result.files:
            await _fail(
                job_id,
                "EMPTY_EMIT",
                f"Target {request.target!r} produced no document for this source.",
                None,
            )
            return

        if not await _publish(
            job_id,
            percent=_STAGE_PERCENT["validating"],
            stage="validating",
            event=("info", "EMITTED",
                   f"Emitted {len(emit_result.files)} file(s)",
                   {"files": [f.path for f in emit_result.files]}),
        ):
            return

        # --- Stage 4: round-trip validation seam (MFX-EPIC-5) -----------------------
        for level, code, message, context in validate_emitted_result(emit_result, target_format):
            if not await _publish(job_id, event=(level, code, message, context)):
                return

        # --- Stage 5: packaging seam (MFX-EPIC-4) -----------------------------------
        if not await _publish(job_id, percent=_STAGE_PERCENT["packaging"], stage="packaging"):
            return
        manifest = build_result_manifest(emit_result)

        result = ExportJobResult(
            artifact=source.artifact_id,
            version_record_id=source.version_record_id,
            version_label=source.version_label,
            target=target_format,
            dry_run=False,
            fidelity=fidelity,
            guard=guard,
            files=manifest,
            media_type=emit_result.media_type,
        )

        with _jobs_lock:
            rec = _jobs.get(job_id)
            if rec is not None:
                rec.emit_result = emit_result

        await _publish(
            job_id,
            state="completed",
            percent=100,
            result=result,
            event=("info", "EXPORT_COMPLETED",
                   f"Export to {target_format!r} completed "
                   f"({len(manifest)} file(s), {sum(f.size_bytes for f in manifest)} bytes)",
                   None),
        )
    except Exception as exc:  # noqa: BLE001 - a background task must never raise
        logger.exception("export job crashed job=%s", job_id)
        await _fail(job_id, "EXPORT_EXCEPTION", str(exc), None)


# ===========================================================================
# Public engine API (mirrors the spec-import engine's surface)
# ===========================================================================


def _get_record_locked(tenant_slug: str, job_id: str) -> _ExportJobRecord:
    """Look up a job scoped to the tenant while :data:`_jobs_lock` is held."""
    rec = _jobs.get(job_id)
    if rec is None or rec.tenant_slug != tenant_slug:
        raise HTTPException(status_code=404, detail="Export job not found")
    return rec


def _get_record(tenant_slug: str, job_id: str) -> _ExportJobRecord:
    """Look up a job scoped to the tenant; 404 when unknown or cross-tenant."""
    with _jobs_lock:
        return _get_record_locked(tenant_slug, job_id)


def _status_path(tenant_slug: str, job_id: str) -> str:
    """Relative poll URL for a job (matches the router's path layout)."""
    return f"/v1/export/{tenant_slug}/jobs/{job_id}"


async def schedule_export_job(
    tenant_slug: str,
    tenant_id: str,
    request: ExportJobStartRequest,
) -> ExportJobAccepted:
    """Accept an export job and start it in the background.

    The target and its options are validated **synchronously** so an unknown target or
    invalid options are rejected at submit time (400/422, matching the sibling
    ``/export/document`` route) rather than surfacing as an async failure. The source
    load — the DB-heavy part — happens inside the job.

    Args:
        tenant_slug: The tenant slug (job scoping + status path).
        tenant_id: The authenticated tenant id (scopes the source lookup).
        request: The submitted job request.

    Returns:
        The 202 acceptance payload (job id + poll path).

    Raises:
        ExportError: When the target is unknown (400) or its options are invalid (422).
    """
    # Fail fast on a bad target/options; also warms the emitter registry.
    resolve_emit_options(request.target, request.options)

    job_id = str(uuid.uuid4())
    initial = ExportJobStatus(job_id=job_id, state="queued", percent=0)
    with _jobs_lock:
        _jobs[job_id] = _ExportJobRecord(
            tenant_slug=tenant_slug,
            tenant_id=tenant_id,
            job_id=job_id,
            state="queued",
            status=initial,
            request=request,
        )
    # Run on the engine's own loop (not the request's) so the job survives the request.
    asyncio.run_coroutine_threadsafe(_drive_export_job(job_id), _get_engine_loop())
    return ExportJobAccepted(job_id=job_id, status_path=_status_path(tenant_slug, job_id))


def get_export_job_status(tenant_slug: str, job_id: str) -> ExportJobStatus:
    """Return the current poll payload for a job (404 when unknown for this tenant)."""
    with _jobs_lock:
        return _get_record_locked(tenant_slug, job_id).status.model_copy(deep=True)


async def list_export_jobs(tenant_slug: str) -> ExportJobListResponse:
    """List this process's export jobs for the tenant (summary rows, no event logs)."""
    with _jobs_lock:
        items: List[ExportJobListItem] = []
        for rec in _jobs.values():
            if rec.tenant_slug != tenant_slug:
                continue
            st = rec.status
            items.append(
                ExportJobListItem(
                    job_id=st.job_id,
                    state=st.state,
                    percent=st.percent,
                    status_path=_status_path(tenant_slug, st.job_id),
                    artifact=rec.request.artifact,
                    target=rec.request.target,
                    dry_run=rec.request.dry_run,
                    progress=st.progress,
                )
            )
    return ExportJobListResponse(jobs=items)


async def cancel_export_job(tenant_slug: str, job_id: str) -> None:
    """Request cancellation of a job; a no-op when it is already terminal.

    The pipeline honours the flag at its next stage boundary — an in-flight blocking
    stage (source load / emit) finishes its thread first, then the job finalizes to
    ``canceled`` without publishing further progress or a result.
    """
    with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None or rec.tenant_slug != tenant_slug:
            raise HTTPException(status_code=404, detail="Export job not found")
        if rec.state in _TERMINAL_STATES:
            return
        rec.cancel_requested = True


def get_export_job_emit_result(tenant_slug: str, job_id: str) -> Optional[EmitResult]:
    """The retained raw emit result for a completed job, for the delivery epics (MFX-4.x).

    Returns ``None`` while the job is running, after a failure/cancel, or for a dry-run.

    Raises:
        HTTPException: 404 when the job is unknown for this tenant.
    """
    with _jobs_lock:
        emit_result = _get_record_locked(tenant_slug, job_id).emit_result
        return None if emit_result is None else emit_result.model_copy(deep=True)
