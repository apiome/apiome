"""CanonicalApi → emitter dispatch — the one-shot transcode primitive — MFX-3.2 (#3845).

The single, reusable step at the heart of every export surface: **load** the source
revision's :class:`~app.canonical_model.CanonicalApi`, **resolve** the target emitter from
the registry, **run** it, and **attach** the fidelity report. It is the synchronous, one-shot
twin of the async export job (:mod:`app.export_job_engine`, MFX-3.1): the job runs this same
composition in the background with staged progress + cancellation for large or toolchain-backed
targets, while this module returns the emitted artifact **and** its honest fidelity envelope in
a single call — the right shape for small artifacts, the ``apiome export`` CLI (MFX-8.x), and
any caller that does not want to submit a job and poll.

The composition reuses the format seams built earlier in the epic rather than re-deriving them:

1. **load** — :func:`app.export_source.load_export_source` resolves ``(tenant, artifact, version)``
   to a canonical model (tenant-scoped; the same parse + normalize the import ran);
2. **resolve + run** — :func:`app.export_service.resolve_emitter` / :func:`~app.export_service.emit_canonical`
   route the model through the Emitter SPI for the requested target, with field-identity persistence;
3. **attach** — :func:`app.export_fidelity.build_export_fidelity` computes the full
   :class:`~app.export_fidelity.ExportFidelity` envelope (target + tier + report + advisory),
   byte-identical to what ``POST /v1/export/{tenant_slug}/preview`` returns for the same inputs.

A ``dry_run`` dispatch stops after step 3: it carries the fidelity report and **no artifact** —
the synchronous twin of ``POST /v1/export/{tenant_slug}/preview``. Every failure mode is a typed exception the
caller maps straight to an HTTP status: :class:`~app.export_source.ExportSourceError` (unknown
artifact/version, no reconstructable source) and :class:`~app.export_service.ExportError`
(unknown target, invalid options, an emitter that produced nothing).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from .emitter import EmitResult, get_emitter
from .export_fidelity import ExportFidelity, build_export_fidelity
from .export_service import (
    ExportError,
    ExportPersistenceContext,
    emit_canonical,
    resolve_emit_format,
)
from .export_source import ExportSource, load_export_source
from .lossiness import LossinessSeverity
from .transcoding_guards import (
    TranscodeGuard,
    classify_transcode,
    enforce_transcode_guard,
)

__all__ = [
    "ExportDispatch",
    "dispatch_from_source",
    "dispatch_export",
]


class ExportDispatch(BaseModel):
    """The result of one dispatch: the resolved source, the fidelity report, and the artifact.

    Pairs the emitted artifact with the fidelity envelope that describes what the conversion
    cost — the "run it, attach the fidelity report" unit MFX-3.2 delivers. A ``dry_run``
    dispatch carries the report with :attr:`emit` left ``None`` (no artifact was produced).
    """

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id the dispatch exported.")
    version_record_id: str = Field(description="The resolved revision (``versions.id``).")
    version_label: Optional[str] = Field(
        default=None, description="The resolved revision's version label (e.g. ``1.0.0``)."
    )
    target: str = Field(description="The resolved target format key (e.g. ``openapi-3.1``).")
    dry_run: bool = Field(description="True when the dispatch stopped after the fidelity report.")
    fidelity: ExportFidelity = Field(
        description="The full fidelity envelope (target + tier + report + advisory).",
    )
    guard: TranscodeGuard = Field(
        description="The pre-flight transcoding guard (MFX-3.3): the conversion band "
        "(clean / lossy / near-empty / severe) and why. A severe conversion is only reached "
        "here when the caller confirmed it (or on a dry-run, which never blocks).",
    )
    emit: Optional[EmitResult] = Field(
        default=None,
        description="The emitter's output bundle; ``None`` for a dry-run (no artifact emitted).",
    )


def dispatch_from_source(
    source: ExportSource,
    target: str,
    *,
    options: Optional[Dict[str, Any]] = None,
    min_severity: LossinessSeverity = LossinessSeverity.INFO,
    dry_run: bool = False,
    confirm: bool = False,
    persistence: Optional[ExportPersistenceContext] = None,
) -> ExportDispatch:
    """Dispatch an already-loaded source to ``target``: resolve, guard, run, attach fidelity.

    The pure composition, with the DB-bound source load already done by the caller. Resolves the
    target emitter, computes the fidelity envelope, classifies the conversion with the
    transcoding guard (MFX-3.3), and — unless ``dry_run`` — runs the emitter, returning them
    together. Splitting the load out lets callers that already hold an
    :class:`~app.export_source.ExportSource` (e.g. the public browse path) reuse the dispatch
    without a second lookup.

    A **severe** conversion (an event API to an operation-only target, or an export that drops a
    critical construct) is refused with a :class:`~app.transcoding_guards.TranscodeGuardError`
    unless ``confirm`` is set — the guard's gate — so a caller cannot silently produce a
    near-empty or semantically-broken artifact. A ``dry_run`` never emits, so it never blocks:
    it always returns the guard for the caller to prompt on.

    Args:
        source: The loaded export source (its canonical model + resolved coordinates).
        target: Target emitter ``key`` (``openapi``) or format key (``openapi-3.1``).
        options: Per-target emit options (MFX-1.4); ``None``/empty applies the target defaults.
        min_severity: Lowest loss severity that raises the advisory (MFX-2.4); does not affect
            the report or counts.
        dry_run: When true, stop after the fidelity report — no artifact is emitted (and the
            guard never blocks).
        confirm: When true, proceed with a **severe** conversion the guard would otherwise block.
            Ignored for non-severe conversions.
        persistence: Optional field-identity persistence context (proto3 field numbers, MFX-12.2);
            ``None`` keeps the emit read-only.

    Returns:
        The :class:`ExportDispatch` pairing the resolved coordinates, the fidelity envelope, the
        transcoding guard, and — for a real (non-dry-run) dispatch — the emitted bundle.

    Raises:
        ExportError: When ``target`` does not resolve (400), its options are invalid (422), or the
            emitter produced no document (422).
        TranscodeGuardError: When the conversion is severe and ``confirm`` is not set (409); a
            dry-run never raises it.
    """
    # Resolve the format key (and validate the target) once; a bad target fails here, before any
    # emit, matching the preview/document routes.
    target_format = resolve_emit_format(target)
    emitter_cls = get_emitter(target_format)

    # The fidelity envelope is computed the same way the preview endpoint does, so a preview and
    # the dispatch it previews agree byte-for-byte. The guard reuses the envelope's report so it
    # never re-walks the model and always corroborates what the report shows.
    fidelity = build_export_fidelity(source.api, emitter_cls, min_severity=min_severity)
    guard = classify_transcode(source.api, emitter_cls, report=fidelity.report)

    if dry_run:
        return ExportDispatch(
            artifact=source.artifact_id,
            version_record_id=source.version_record_id,
            version_label=source.version_label,
            target=target_format,
            dry_run=True,
            fidelity=fidelity,
            guard=guard,
            emit=None,
        )

    # Pre-flight gate: a severe conversion needs explicit confirmation before any emit runs.
    enforce_transcode_guard(guard, confirmed=confirm)

    emit_result = emit_canonical(
        source.api, target_format, opts=options, persistence=persistence
    )
    if not emit_result.files:
        # A registered emitter that yields nothing for this source is a target error, not a
        # source error — surface it the way the /document route does.
        raise ExportError(
            f"Target {target!r} produced no document for this source.",
            status_code=422,
        )

    return ExportDispatch(
        artifact=source.artifact_id,
        version_record_id=source.version_record_id,
        version_label=source.version_label,
        target=target_format,
        dry_run=False,
        fidelity=fidelity,
        guard=guard,
        emit=emit_result,
    )


def dispatch_export(
    tenant_id: str,
    artifact: str,
    version: Optional[str],
    target: str,
    *,
    options: Optional[Dict[str, Any]] = None,
    min_severity: LossinessSeverity = LossinessSeverity.INFO,
    dry_run: bool = False,
    confirm: bool = False,
    persist: bool = True,
) -> ExportDispatch:
    """Load a (tenant, artifact, version) source and dispatch it to ``target``.

    The full, tenant-scoped primitive: resolve the revision's canonical model, then resolve the
    emitter, guard the conversion (MFX-3.3), run it, and attach the fidelity report. Tenant
    scoping is enforced by the loader — the ``tenant_id`` scopes every source lookup — and the
    emit's field-identity writes are scoped to ``(tenant, artifact)`` via the persistence context.

    Args:
        tenant_id: The authenticated tenant id (scopes the source lookup and any field-identity
            persistence).
        artifact: The artifact (project) id to export.
        version: A revision UUID, a version label (``1.0.0``), or ``None`` for the latest revision.
        target: Target emitter ``key`` or format key.
        options: Per-target emit options (MFX-1.4); ``None``/empty applies the target defaults.
        min_severity: Lowest loss severity that raises the advisory (MFX-2.4).
        dry_run: When true, stop after the fidelity report — no artifact is emitted.
        confirm: When true, proceed with a **severe** conversion the transcoding guard would
            otherwise block. Ignored for non-severe conversions.
        persist: When true (the default for an authenticated export), persist synthesized
            field-identity numbers for proto3 targets (MFX-12.2). A dry-run never emits, so this
            has no effect on it.

    Returns:
        The :class:`ExportDispatch` for the loaded source.

    Raises:
        ExportSourceError: When the artifact/version is unknown (404) or the revision has no
            reconstructable source (422).
        ExportError: When the target is unknown (400), its options are invalid (422), or the
            emitter produced no document (422).
        TranscodeGuardError: When the conversion is severe and ``confirm`` is not set (409).
    """
    source = load_export_source(tenant_id, artifact, version)
    persistence = (
        ExportPersistenceContext(tenant_id=tenant_id, artifact_id=source.artifact_id)
        if persist
        else None
    )
    return dispatch_from_source(
        source,
        target,
        options=options,
        min_severity=min_severity,
        dry_run=dry_run,
        confirm=confirm,
        persistence=persistence,
    )
