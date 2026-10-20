"""Project / batch export — MFX-39.2 (#4334).

One export job over a **set of versions** of an artifact (every version, or a selected list) ×
one or more targets, delivered as **one archive**. It is the batch half of the export job engine
(:mod:`app.export_job_engine`): the same submit → poll → download contract, the same per-target
pipeline (fidelity → transcode guard → emit → re-parse → delivery gate), and the same shared
helpers for persistence and attestation.

What makes it a batch is **partial-failure semantics**. Each (version × target) pair is an
*item* with its own state. An item that fails — a version that does not load, a target that
does not resolve, a severe conversion without ``confirm``, an emitter fault, a blocked delivery —
is recorded on that item with the same structured error a single-target job would carry
(:class:`~app.export_job_engine.ExportJobError`), and the batch moves on. The job completes when
at least one item completed; only when **every** item failed does the job fail
(``EXPORT_BATCH_FAILED``, the items' errors in ``error.context.items``).

The archive (``export-batch.zip``) holds each completed item's files under
``<version>/<target>/`` plus a root ``manifest.json`` (``kind: "batch"``) listing every item —
completed or failed — with its files, fidelity, provenance, or error.

Pure seams (unit-tested without a job): :func:`version_directory`, :func:`build_batch_manifest`,
:func:`build_batch_zip`. The DB-backed version listing is :func:`list_project_version_ids`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from . import export_job_engine as engine
from .delivery_error_taxonomy import delivery_error_fields
from .emitter import EmitResult
from .export_delivery_gate import DeliveryGateReport
from .export_fidelity import ExportFidelity
from .export_fidelity_rollup import ExportFidelityRollup, build_fidelity_rollup
from .export_job_engine import (
    BUNDLE_MEDIA_TYPE,
    MAX_BATCH_ITEMS,
    ExportBatchItem,
    ExportBatchSummary,
    ExportDownloadArtifact,
    ExportJobError,
    ExportJobFile,
    ExportJobResult,
    ExportJobStartRequest,
    ExportJobTargetSpec,
    MultiTargetBundlePart,
    build_delivery_events,
    build_validation_events,
    delivery_failure,
    safe_bundle_segment,
    target_directory,
    write_parts_zip,
)
from .export_service import ExportError, ExportPersistenceContext, resolve_emit_format, resolve_emitter
from .export_source import ExportSource, ExportSourceError
from .export_validation_gate import EmittedValidationReport, build_validation_report
from .import_export_metrics import import_export_metrics
from .transcoding_guards import TranscodeGuard, classify_transcode

logger = logging.getLogger(__name__)

__all__ = [
    "BATCH_BUNDLE_FILENAME",
    "BATCH_MANIFEST_KIND",
    "list_project_version_ids",
    "version_directory",
    "build_batch_manifest",
    "build_batch_zip",
    "drive_batch_job_inner",
]

#: Download filename of a batch export's archive.
BATCH_BUNDLE_FILENAME = "export-batch.zip"
#: The ``kind`` a batch archive's root manifest declares.
BATCH_MANIFEST_KIND = "batch"

# Percent band every item shares (MFX-39.2): each item takes three steps (fidelity, emit,
# validate) inside it, so percent only ever rises; packaging reports 90 and completion 100.
_BATCH_BAND = (10, 90)
_STEPS_PER_ITEM = 3


# ===========================================================================
# Pure seams
# ===========================================================================


def list_project_version_ids(tenant_id: str, artifact_id: str) -> List[str]:
    """Every live revision id of an artifact, newest first (the ``all_versions`` selection).

    Args:
        tenant_id: The owning tenant id (scopes the lookup).
        artifact_id: The artifact (project) id.

    Returns:
        Revision ids, newest first; empty when the artifact is unknown or has no versions.
    """
    from .database import db

    return [str(row["id"]) for row in db.get_versions_for_project(artifact_id, tenant_id)]


def version_directory(source: ExportSource, taken: Set[str]) -> str:
    """The archive folder for one version of a batch export, unique within the archive.

    Named after the version label (``1.0.0``), or the revision id when the revision has no
    label, reduced to one safe path segment. When two revisions share a label the later one
    gets the start of its revision id appended (``1.0.0-3f2a9c1b``). The chosen name is added
    to ``taken``.

    Args:
        source: The loaded version.
        taken: Folder names already used in this archive (updated in place).

    Returns:
        A safe, unique folder name.
    """
    base = safe_bundle_segment(source.version_label or source.version_record_id, "version")
    name = base
    if name in taken:
        name = f"{base}-{safe_bundle_segment(source.version_record_id, 'revision')[:8]}"
    counter = 1
    while name in taken:
        counter += 1
        name = f"{base}-{counter}"
    taken.add(name)
    return name


def _manifest_item(item: ExportBatchItem, provenance: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """One item's section of the batch manifest (never any file content)."""
    section: Dict[str, Any] = {
        "version": item.version,
        "version_record_id": item.version_record_id,
        "version_label": item.version_label,
        "target": item.target,
        "directory": item.directory,
        "state": item.state,
    }
    if item.state == "completed":
        section.update(
            {
                "media_type": item.media_type,
                "file_count": len(item.files),
                "files": [f.model_dump() for f in item.files],
                "fidelity": {"tier": item.tier, "preserved_percent": item.preserved_percent},
                "provenance": provenance,
            }
        )
    elif item.error is not None:
        section["error"] = {"code": item.error.code, "message": item.error.message}
    return section


def build_batch_manifest(
    items: List[ExportBatchItem],
    *,
    artifact: str,
    rollup: Optional[ExportFidelityRollup],
    provenance: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the root ``manifest.json`` of a batch archive (MFX-39.2).

    Lists every item — completed ones with their files, fidelity and provenance, failed ones
    with their error code and message — so the archive alone tells a reader what is missing and
    why. Every file sits under an item folder, so the root manifest never collides with one.

    Args:
        items: Every item of the batch, in run order.
        artifact: The exported artifact (project) id.
        rollup: The fidelity rollup over the completed items (``None`` when there are none).
        provenance: Snapshot + version provenance per completed item, keyed by its directory.

    Returns:
        The manifest as a JSON-serializable dict.
    """
    sections = [
        _manifest_item(item, provenance.get(item.directory or "")) for item in items
    ]
    completed = [item for item in items if item.state == "completed"]
    return {
        "kind": BATCH_MANIFEST_KIND,
        "manifest": "manifest.json",
        "artifact": artifact,
        "version_count": len({item.version for item in items}),
        "item_count": len(items),
        "completed_count": len(completed),
        "failed_count": len(items) - len(completed),
        "file_count": sum(len(item.files) for item in completed),
        "items": sections,
        "fidelity_rollup": rollup.model_dump(mode="json") if rollup is not None else None,
    }


def build_batch_zip(
    parts: List[MultiTargetBundlePart],
    items: List[ExportBatchItem],
    *,
    artifact: str,
    rollup: Optional[ExportFidelityRollup],
) -> bytes:
    """Package a batch export's completed items into one deterministic zip (MFX-39.2).

    Args:
        parts: The completed items' files, each part's ``directory`` being ``<version>/<target>``.
        items: Every item of the batch (completed and failed), for the manifest.
        artifact: The exported artifact (project) id.
        rollup: The fidelity rollup over the completed items.

    Returns:
        The zip archive as raw bytes, ready to serve as ``application/zip``.
    """
    manifest = build_batch_manifest(
        items,
        artifact=artifact,
        rollup=rollup,
        provenance={part.directory: part.provenance for part in parts},
    )
    return write_parts_zip(parts, manifest)


# ===========================================================================
# Pipeline
# ===========================================================================


class _JobCanceledError(Exception):
    """Raised inside the batch driver when a publish finds the job canceled (or gone)."""


@dataclass
class _ItemRun:
    """One (version × target) item as it moves through the batch pipeline."""

    version: str
    spec: ExportJobTargetSpec
    target: str
    source: Optional[ExportSource] = None
    directory: Optional[str] = None
    fidelity: Optional[ExportFidelity] = None
    guard: Optional[TranscodeGuard] = None
    snapshot_hash: Optional[str] = None
    emit_result: Optional[EmitResult] = None
    validation_report: Optional[EmittedValidationReport] = None
    delivery: Optional[DeliveryGateReport] = None
    files: List[ExportJobFile] = field(default_factory=list)
    error: Optional[ExportJobError] = None

    @property
    def label(self) -> str:
        """The item as ``<version> → <target>`` for progress hints and events."""
        version = (self.source.version_label if self.source else None) or self.version
        return f"{version} → {self.target}"

    def to_item(self) -> ExportBatchItem:
        """The poll-payload view of this item."""
        return ExportBatchItem(
            version=self.version,
            version_record_id=self.source.version_record_id if self.source else None,
            version_label=self.source.version_label if self.source else None,
            target=self.target,
            directory=self.directory,
            state="failed" if self.error is not None else "completed",
            snapshot_hash=self.snapshot_hash,
            options=self.spec.options,
            tier=self.fidelity.summary.tier.value if self.fidelity else None,
            preserved_percent=self.fidelity.summary.preserved_percent if self.fidelity else None,
            guard=self.guard,
            validation=self.validation_report,
            delivery=self.delivery,
            files=self.files,
            media_type=self.emit_result.media_type if self.emit_result else None,
            error=self.error,
        )


@dataclass
class _BatchContext:
    """What every item of one batch job shares."""

    job_id: str
    request: ExportJobStartRequest
    tenant_id: str
    tenant_slug: str
    item_total: int
    correlation_id: Optional[str]


async def _step(job_id: str, **kwargs: Any) -> None:
    """Publish one snapshot update; raise :class:`_JobCanceledError` when the job was canceled."""
    if not await engine._publish(job_id, **kwargs):
        raise _JobCanceledError()


def _percent(ctx: _BatchContext, item_index: int, sub_step: int) -> int:
    """The job percent for ``sub_step`` of the item at ``item_index``."""
    return engine._band_percent(
        _BATCH_BAND, item_index * _STEPS_PER_ITEM + sub_step, ctx.item_total * _STEPS_PER_ITEM
    )


async def _fail_item(
    ctx: _BatchContext,
    run: _ItemRun,
    code: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
) -> _ItemRun:
    """Record a failure on one item (not the job) and log it as a ``warn`` event.

    The error is built from the delivery taxonomy exactly as a failed job's would be, and the
    failure counter is incremented for the item's target (IXH-6.6).

    Args:
        ctx: The batch context.
        run: The failing item.
        code: The delivery taxonomy code.
        message: The failure message.
        context: Structured detail.

    Returns:
        ``run``, now carrying its error.
    """
    detail: Dict[str, Any] = {"version": run.version, "target": run.target}
    if context:
        detail.update(context)
    run.error = ExportJobError(
        **delivery_error_fields(
            code, message, context=detail, correlation_id=ctx.correlation_id or ctx.job_id
        )
    )
    try:
        import_export_metrics.record_failure(
            kind="export", code=run.error.code, adapter_or_target=run.target
        )
    except Exception:  # noqa: BLE001 - metrics must never affect the job
        logger.debug("Failed to record batch item failure metric", exc_info=True)
    await _step(
        ctx.job_id,
        event=(
            "warn",
            "BATCH_ITEM_FAILED",
            f"{run.label} failed ({run.error.code}): {run.error.message}",
            {"version": run.version, "target": run.target, "code": run.error.code},
        ),
    )
    return run


async def _run_item(
    ctx: _BatchContext,
    run: _ItemRun,
    *,
    version_dir: str,
    item_index: int,
    lint_cache: Dict[str, Any],
) -> _ItemRun:
    """Plan, emit, re-parse and gate one item; a failure is recorded on the item.

    Mirrors one target of the multi-target pipeline (MFX-39.1), except that every step that
    would fail the job there fails only this item here. A dry-run item stops after its fidelity.

    Args:
        ctx: The batch context.
        run: The item, with its loaded ``source``.
        version_dir: The archive folder of the item's version.
        item_index: The item's position in the batch (progress).
        lint_cache: Per-version holder for the source lint report, computed on first use.

    Returns:
        ``run``, completed or carrying its error.

    Raises:
        _JobCanceledError: When the job was canceled at a stage boundary.
    """
    request = ctx.request
    source = run.source
    assert source is not None
    try:
        emitter_cls = type(resolve_emitter(run.spec.target))
        run.target = resolve_emit_format(run.spec.target)
    except ExportError as exc:
        return await _fail_item(
            ctx, run, "UNSUPPORTED_TARGET", str(exc), {"status_code": exc.status_code}
        )
    run.directory = f"{version_dir}/{target_directory(run.target)}"
    hint = f"{run.label} ({item_index + 1}/{ctx.item_total})"

    await _step(
        ctx.job_id,
        percent=_percent(ctx, item_index, 0),
        stage="analyzing-fidelity",
        current_item=hint,
    )
    run.fidelity = await asyncio.to_thread(
        engine.build_export_fidelity,
        source.api,
        emitter_cls,
        min_severity=request.min_severity,
        options=run.spec.options,
    )
    run.snapshot_hash = run.fidelity.projection.manifest_hash
    run.guard = classify_transcode(source.api, emitter_cls, report=run.fidelity.report)
    await _step(
        ctx.job_id,
        event=(
            "info",
            "FIDELITY_COMPUTED",
            f"Fidelity for {run.label}: {run.fidelity.summary.tier.value}, "
            f"{run.fidelity.summary.preserved_percent}% preserved; transcode guard: "
            f"{run.guard.verdict.value}",
            {"version": run.version,
             "target": run.target,
             "tier": run.fidelity.summary.tier.value,
             "preserved_percent": run.fidelity.summary.preserved_percent,
             "guard": run.guard.verdict.value},
        ),
    )
    if request.dry_run:
        return run

    if run.guard.requires_confirmation and not request.confirm:
        return await _fail_item(
            ctx,
            run,
            "TRANSCODE_CONFIRMATION_REQUIRED",
            run.guard.message,
            {"verdict": run.guard.verdict.value,
             "reasons": run.guard.reasons,
             "preserved_percent": run.guard.preserved_percent},
        )

    await _step(
        ctx.job_id, percent=_percent(ctx, item_index, 1), stage="emitting", current_item=hint
    )
    try:
        emit_result: EmitResult = await asyncio.to_thread(
            engine.emit_canonical,
            source.api,
            run.spec.target,
            opts=run.spec.options,
            persistence=ExportPersistenceContext(
                tenant_id=ctx.tenant_id, artifact_id=source.artifact_id
            ),
        )
    except ExportError as exc:
        return await _fail_item(
            ctx, run, "EMIT_FAILED", str(exc), {"status_code": exc.status_code}
        )
    if not emit_result.files:
        return await _fail_item(
            ctx,
            run,
            "EMPTY_EMIT",
            f"Target {run.spec.target!r} produced no document for this source.",
        )
    await _step(
        ctx.job_id,
        percent=_percent(ctx, item_index, 2),
        stage="validating",
        current_item=hint,
        event=("info", "EMITTED",
               f"Emitted {len(emit_result.files)} file(s) for {run.label}",
               {"version": run.version,
                "target": run.target,
                "files": [f.path for f in emit_result.files]}),
    )

    validation = await engine.validate_emitted_artifact(run.target, emit_result, api=source.api)
    validation_report = build_validation_report(validation)
    if "lint" not in lint_cache:
        # The source lint depends only on the version, so it runs once per version.
        lint_cache["lint"] = await asyncio.to_thread(
            engine.lint_delivery_source,
            source.api,
            tenant_id=ctx.tenant_id,
            project_id=source.artifact_id,
        )
    delivery = await engine._gate_delivery(
        tenant_id=ctx.tenant_id,
        tenant_slug=ctx.tenant_slug,
        source=source,
        source_lint=lint_cache["lint"],
        target_format=run.target,
        fidelity=run.fidelity,
        validation_report=validation_report,
    )
    run.validation_report = validation_report
    if delivery.blocks_delivery:
        code, message, context = delivery_failure(delivery, validation, run.target)
        return await _fail_item(ctx, run, code, message, context)
    for event in build_validation_events(validation) + build_delivery_events(delivery):
        await _step(ctx.job_id, event=event)
    run.emit_result = emit_result
    run.delivery = delivery
    return run


async def _run_items(
    ctx: _BatchContext, version_refs: List[str], specs: List[ExportJobTargetSpec]
) -> List[_ItemRun]:
    """Run every (version × target) item, version by version.

    A version that fails to load fails each of its items; a second reference to a revision
    already in the batch (a label and its revision id) is skipped with a warning.

    Args:
        ctx: The batch context.
        version_refs: The versions to export, as requested.
        specs: The targets to export each version to.

    Returns:
        Every item that ran, in order.

    Raises:
        _JobCanceledError: When the job was canceled at a stage boundary.
    """
    runs: List[_ItemRun] = []
    taken: Set[str] = set()
    seen_revisions: Set[str] = set()
    for version_index, ref in enumerate(version_refs):
        first_item = version_index * len(specs)
        await _step(
            ctx.job_id,
            percent=_percent(ctx, first_item, 0),
            stage="loading-source",
            current_item=f"{ref} ({version_index + 1}/{len(version_refs)})",
        )
        try:
            source: ExportSource = await asyncio.to_thread(
                engine.load_export_source, ctx.tenant_id, ctx.request.artifact, ref
            )
        except ExportSourceError as exc:
            for spec in specs:
                run = _ItemRun(version=ref, spec=spec, target=spec.target)
                runs.append(
                    await _fail_item(
                        ctx, run, "SOURCE_LOAD_FAILED", str(exc), {"status_code": exc.status_code}
                    )
                )
            continue
        if source.version_record_id in seen_revisions:
            await _step(
                ctx.job_id,
                event=(
                    "warn",
                    "BATCH_VERSION_DUPLICATE",
                    f"Version {ref!r} is revision {source.version_record_id}, which this batch "
                    "already exports; skipped.",
                    {"version": ref, "version_record_id": source.version_record_id},
                ),
            )
            continue
        seen_revisions.add(source.version_record_id)
        version_dir = version_directory(source, taken)
        lint_cache: Dict[str, Any] = {}
        for target_index, spec in enumerate(specs):
            run = _ItemRun(version=ref, spec=spec, target=spec.target, source=source)
            try:
                runs.append(
                    await _run_item(
                        ctx,
                        run,
                        version_dir=version_dir,
                        item_index=first_item + target_index,
                        lint_cache=lint_cache,
                    )
                )
            except _JobCanceledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one item's fault must not sink the batch
                logger.exception("batch export item crashed job=%s item=%s", ctx.job_id, run.label)
                runs.append(await _fail_item(ctx, run, "EXPORT_EXCEPTION", str(exc)))
    return runs


def _summary(runs: List[_ItemRun], target_count: int) -> ExportBatchSummary:
    """The per-item outcome table of a finished batch."""
    items = [run.to_item() for run in runs]
    completed = sum(1 for item in items if item.state == "completed")
    return ExportBatchSummary(
        version_count=len({item.version for item in items}),
        target_count=target_count,
        item_count=len(items),
        completed_count=completed,
        failed_count=len(items) - completed,
        items=items,
    )


async def drive_batch_job_inner(job_id: str) -> None:
    """Run one batch export job (MFX-39.2): a version set × targets → one archive.

    1. **select** — the requested ``versions``, or every version of the artifact for
       ``all_versions`` (``EXPORT_BATCH_TOO_LARGE`` past :data:`MAX_BATCH_ITEMS` items);
    2. **items** — each version loads once, then each target runs the single-target pipeline;
       any failure is recorded on its item and the batch continues (:func:`_run_items`);
    3. **package** — the completed items' files go into one zip under ``<version>/<target>/``
       with a root manifest listing every item, persisted for download; each completed item's
       delivery is then attested against the archive's digest.

    The job completes when at least one item completed (a dry-run stops after step 2 with every
    item's fidelity) and fails with ``EXPORT_BATCH_FAILED`` when none did. Any unexpected fault
    outside an item fails the job (``EXPORT_EXCEPTION``) — this task never raises.

    Args:
        job_id: The job to drive.
    """
    with engine._jobs_lock:
        rec = engine._jobs.get(job_id)
        if rec is None:
            return
        request = rec.request
        tenant_id = rec.tenant_id
        tenant_slug = rec.tenant_slug
        correlation_id = rec.correlation_id
    specs = request.target_specs

    try:
        await _step(
            job_id,
            state="running",
            percent=engine._STAGE_PERCENT["loading-source"],
            stage="loading-source",
            event=(
                "info",
                "EXPORT_STARTED",
                f"Batch export of artifact {request.artifact} to {request.target_label} started"
                + (" (dry-run: fidelity reports only)" if request.dry_run else ""),
                {"artifact": request.artifact,
                 "versions": request.versions if request.versions is not None else "all",
                 "targets": [spec.target for spec in specs],
                 "dry_run": request.dry_run},
            ),
        )

        if request.versions is not None:
            version_refs = list(request.versions)
        else:
            try:
                version_refs = await asyncio.to_thread(
                    list_project_version_ids, tenant_id, request.artifact
                )
            except Exception as exc:  # noqa: BLE001 - a listing fault fails the job cleanly
                logger.warning("batch export could not list versions job=%s", job_id, exc_info=True)
                await engine._fail(job_id, "SOURCE_LOAD_FAILED", str(exc), None)
                return
            if not version_refs:
                await engine._fail(
                    job_id,
                    "SOURCE_LOAD_FAILED",
                    f"Artifact {request.artifact!r} has no versions to export.",
                    {"status_code": 404},
                )
                return
        item_total = len(version_refs) * len(specs)
        if item_total > MAX_BATCH_ITEMS:
            await engine._fail(
                job_id,
                "EXPORT_BATCH_TOO_LARGE",
                f"This batch would export {len(version_refs)} versions × {len(specs)} targets "
                f"= {item_total} items; one batch export runs at most {MAX_BATCH_ITEMS}.",
                {"version_count": len(version_refs),
                 "target_count": len(specs),
                 "item_count": item_total,
                 "max_items": MAX_BATCH_ITEMS},
            )
            return
        await _step(
            job_id,
            event=(
                "info",
                "BATCH_PLANNED",
                f"Exporting {len(version_refs)} version(s) × {len(specs)} target(s) "
                f"= {item_total} item(s)",
                {"version_count": len(version_refs),
                 "target_count": len(specs),
                 "item_count": item_total},
            ),
        )

        ctx = _BatchContext(
            job_id=job_id,
            request=request,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            item_total=item_total,
            correlation_id=correlation_id,
        )
        runs = await _run_items(ctx, version_refs, specs)
        completed = [run for run in runs if run.error is None]
        if not completed:
            await engine._fail(
                job_id,
                "EXPORT_BATCH_FAILED",
                f"All {len(runs)} item(s) of the batch export failed.",
                {"items": [
                    {"version": run.version,
                     "target": run.target,
                     "code": run.error.code if run.error else None,
                     "message": run.error.message if run.error else None}
                    for run in runs
                ]},
            )
            return

        rollup = build_fidelity_rollup(
            [(run.directory, run.fidelity, run.guard) for run in completed]  # type: ignore[misc]
        )
        failed_count = len(runs) - len(completed)
        if request.dry_run:
            await _step(
                job_id,
                state="completed",
                percent=100,
                result=ExportJobResult(
                    artifact=request.artifact,
                    dry_run=True,
                    fidelity_rollup=rollup,
                    batch=_summary(runs, len(specs)),
                ),
                event=("info", "DRY_RUN_COMPLETED",
                       f"Dry-run finished: fidelity reports for {len(completed)} of {len(runs)} "
                       "item(s) attached, no artifact emitted.",
                       {"completed_count": len(completed), "failed_count": failed_count}),
            )
            return

        await _package_and_complete(ctx, runs, completed, rollup, len(specs))
    except _JobCanceledError:
        return
    except Exception as exc:  # noqa: BLE001 - a background task must never raise
        logger.exception("batch export job crashed job=%s", job_id)
        await engine._fail(job_id, "EXPORT_EXCEPTION", str(exc), None)


async def _package_and_complete(
    ctx: _BatchContext,
    runs: List[_ItemRun],
    completed: List[_ItemRun],
    rollup: ExportFidelityRollup,
    target_count: int,
) -> None:
    """Zip the completed items, persist the archive, attest each item, and complete the job.

    Args:
        ctx: The batch context.
        runs: Every item (for the manifest and the result).
        completed: The completed items, whose files go into the archive.
        rollup: The fidelity rollup over the completed items.
        target_count: Targets per version.

    Raises:
        _JobCanceledError: When the job was canceled at a stage boundary.
    """
    job_id = ctx.job_id
    await _step(
        job_id,
        percent=engine._STAGE_PERCENT["packaging"],
        stage="packaging",
        current_item=f"{len(completed)} item(s)",
    )
    parts: List[MultiTargetBundlePart] = []
    for run in completed:
        part = MultiTargetBundlePart(
            target=run.target,
            directory=run.directory,  # type: ignore[arg-type]  # set once the target resolved
            emit_result=run.emit_result,  # type: ignore[arg-type]  # set on completion
            fidelity=run.fidelity,  # type: ignore[arg-type]
            provenance=engine._bundle_provenance(
                run.snapshot_hash, run.source, run.spec.options, run.fidelity  # type: ignore[arg-type]
            ),
        )
        run.files = engine._part_files(part)
        parts.append(part)

    items_before_attestation = [run.to_item() for run in runs]
    expires_at = engine._artifact_expiry_from(engine._now_ms())
    persisted = await engine._persist_download(
        job_id,
        ctx.tenant_slug,
        lambda: ExportDownloadArtifact(
            filename=BATCH_BUNDLE_FILENAME,
            media_type=BUNDLE_MEDIA_TYPE,
            body=build_batch_zip(
                parts, items_before_attestation, artifact=ctx.request.artifact, rollup=rollup
            ),
        ),
        expires_at,
    )
    if persisted is None:
        return
    download, stored = persisted

    # Attest each completed item against the archive's digest (IXH-2.5).
    for run in completed:
        run.delivery = engine._attest_delivery(
            run.delivery,  # type: ignore[arg-type]  # set on completion
            job_id=job_id,
            tenant_id=ctx.tenant_id,
            tenant_slug=ctx.tenant_slug,
            source=run.source,  # type: ignore[arg-type]
            target_format=run.target,
            snapshot_hash=run.snapshot_hash or "",
            options=run.spec.options,
            fidelity=run.fidelity,  # type: ignore[arg-type]
            validation_report=run.validation_report,  # type: ignore[arg-type]
            download=download,
            stored=stored,
            files=[f.path for f in run.files],
        )
        attested = engine._attestation_event(run.delivery, stored, target=run.target)
        if attested is not None:
            level, code, message, context = attested
            await _step(
                job_id, event=(level, code, message, {**(context or {}), "version": run.version})
            )

    all_files = [f for run in completed for f in run.files]
    summary = _summary(runs, target_count)
    result = ExportJobResult(
        artifact=ctx.request.artifact,
        dry_run=False,
        files=all_files,
        media_type=BUNDLE_MEDIA_TYPE,
        download_path=engine._download_path(ctx.tenant_slug, job_id),
        download_expires_at=expires_at,
        fidelity_rollup=rollup,
        batch=summary,
    )
    with engine._jobs_lock:
        rec = engine._jobs.get(job_id)
        if rec is not None:
            rec.retained_download = download
            rec.artifact_expires_at_ms = expires_at

    if summary.failed_count:
        await _step(
            job_id,
            event=(
                "warn",
                "BATCH_PARTIAL",
                f"{summary.failed_count} of {summary.item_count} item(s) failed and are not in "
                "the archive; see result.batch.items for each error.",
                {"completed_count": summary.completed_count,
                 "failed_count": summary.failed_count},
            ),
        )
    await engine._publish(
        job_id,
        state="completed",
        percent=100,
        result=result,
        event=("info", "EXPORT_COMPLETED",
               f"Batch export completed: {summary.completed_count} of {summary.item_count} "
               f"item(s), {len(all_files)} file(s), {sum(f.size_bytes for f in all_files)} bytes; "
               f"worst tier: {rollup.tier.value}",
               {"completed_count": summary.completed_count,
                "failed_count": summary.failed_count}),
    )
